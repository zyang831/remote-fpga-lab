"""State-machine self-check with a fake mender_client. Run: python test_queue_manager.py

No hardware, no server, no framework.
"""

import asyncio
import os
from pathlib import Path

os.environ.setdefault("MENDER_URL", "http://fake")
os.environ.setdefault("MENDER_USER", "fake")
os.environ.setdefault("MENDER_PASS", "fake")

import config
import mender_client
import queue_manager as qm

deployed: list[str] = []
deploy_results: list[str | None] = []  # popped per call; empty means success


phases: list[str] = []  # every on_phase() the fakes were handed


async def fake_deploy(rbf_path, artifact_name, on_phase=lambda _: None):
    """Mirrors the real contract: None on success, a message on failure, steps via on_phase."""
    deployed.append(artifact_name)
    on_phase("board downloading the update")
    phases.append("board downloading the update")
    return deploy_results.pop(0) if deploy_results else None


async def fake_deploy_existing(artifact_name, on_phase=lambda _: None):
    deployed.append(artifact_name)
    on_phase("board installing the update")
    phases.append("board installing the update")
    return deploy_results.pop(0) if deploy_results else None


mender_client.deploy = fake_deploy
mender_client.deploy_existing = fake_deploy_existing

uploaded: list[str] = []


async def fake_artifact_exists(name):
    return False


async def fake_upload_artifact(path):
    uploaded.append(path.name)


mender_client.artifact_exists = fake_artifact_exists
mender_client.upload_artifact = fake_upload_artifact
mender_client.delete_artifact = lambda name: asyncio.sleep(0)


def reset():
    qm._jobs.clear()
    qm._queue.clear()
    qm._active = None
    deployed.clear()
    deploy_results.clear()


async def wait_for(pred, timeout=2.0):
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        if pred():
            return True
        await asyncio.sleep(0.01)
    return False


async def run_with_loop(body):
    task = asyncio.create_task(qm.run_loop(tick=0.01))
    try:
        await body()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_happy_path():
    reset()
    config.ACK_GRACE_SECONDS = 60
    config.SESSION_SECONDS = 60
    job = qm.join()
    assert job.state is qm.JobState.QUEUED
    assert qm.position(job.id) == 1

    async def body():
        # session starts with no bitstream: the board is free, that is enough
        assert await wait_for(lambda: job.state is qm.JobState.ACTIVE), job.state
        assert qm.position(job.id) is None
        assert deployed == []
        assert job.session_ends_at and job.ack_deadline
        assert qm.ack(job.id)

        assert qm.program(job.id, Path("/tmp/user.rbf"))
        assert await wait_for(lambda: job.program_state == "ok"), job.program_state
        assert deployed[0].startswith(f"fpga-lab-{job.id}-")

        assert qm.finish(job.id)
        assert await wait_for(lambda: job.state is qm.JobState.RELEASED), job.state
        # the session replaced the classifier design, so release puts the board's idle design back
        assert deployed[1] == config.RESTORE_ARTIFACT
        assert qm._active is None

    await run_with_loop(body)


async def test_model_switch():
    reset()
    qm._live_model = config.MODEL_NAME
    job = qm.join()

    async def body():
        assert await wait_for(lambda: job.state is qm.JobState.ACTIVE), job.state
        assert not qm.switch_model(job.id, "no-such-model")
        assert qm.program(job.id, Path("/tmp/user.rbf"))
        assert not qm.switch_model(job.id, "flag")  # a deploy is already running
        assert await wait_for(lambda: job.program_state == "ok"), job.program_state

        assert qm.switch_model(job.id, "flag")
        assert job.phase == "queued for the board" and job.busy_since is not None  # progress starts with the request
        assert not qm.program(job.id, Path("/tmp/user.rbf"))  # and vice versa
        assert await wait_for(lambda: job.model_state == "ok"), job.model_state
        assert phases[-1] == "board installing the update"
        assert job.phase is None and job.busy_since is None  # and is cleared when the deploy ends
        assert deployed[-1] == config.MODEL_CATALOG["flag"]
        assert job.program_state == "none"  # the model bundle carries the DLA design
        assert qm._live_model == "flag"

        deploy_results.append("boom")
        assert qm.switch_model(job.id, "fruit")
        assert await wait_for(lambda: job.model_state == "failed"), job.model_state
        assert job.model_error == "boom" and qm._live_model == "flag"
        assert job.phase is None and job.busy_since is None  # cleared on failure too

        # a later .rbf then release: the restore artifact, which on the board puts back the
        # last model that installed (flag), not the default
        assert qm.program(job.id, Path("/tmp/user.rbf"))
        assert await wait_for(lambda: job.program_state == "ok")
        assert qm.finish(job.id)
        assert await wait_for(lambda: job.state is qm.JobState.RELEASED)
        assert deployed[-1] == config.RESTORE_ARTIFACT

    await run_with_loop(body)


async def test_model_upload_build():
    """_build runs the host script; its last stdout line is the artifact, then a switch follows."""
    import tempfile

    reset()
    uploaded.clear()
    tmp = Path(tempfile.mkdtemp())
    (tmp / "artifacts").mkdir()
    script = tmp / "artifacts" / "build-user-model.sh"
    script.write_text("#!/bin/sh\ncase $1 in bad) echo 'dlac: boom' >&2; exit 1;; esac\n"
                      "echo '=== compiling for the FPGA'\nsleep 0.05\necho compiling\necho coredla-model-$1-deadbeef\n")
    script.chmod(0o755)
    config.EDGE_AI_DIR = tmp
    job = qm.join()

    async def body():
        assert await wait_for(lambda: job.state is qm.JobState.ACTIVE), job.state
        assert qm.build_model(job.id, "mine")
        assert not qm.program(job.id, Path("/tmp/user.rbf"))  # busy
        # "=== <step>" lines from the script surface as the phase while it runs
        assert await wait_for(lambda: job.phase == "compiling for the FPGA"), job.phase
        assert await wait_for(lambda: job.model_state == "ok"), (job.upload_state, job.upload_error)
        assert job.upload_state == "ok" and job.upload_error is None
        assert job.phase is None and job.busy_since is None
        assert config.MODEL_CATALOG["mine"] == "coredla-model-mine-deadbeef"
        assert uploaded == ["coredla-model-mine-deadbeef.mender"]
        assert deployed[-1] == "coredla-model-mine-deadbeef" and qm._live_model == "mine"

        assert qm.build_model(job.id, "bad")
        assert await wait_for(lambda: job.upload_state == "failed"), job.upload_state
        assert "boom" in job.upload_error and "bad" not in config.MODEL_CATALOG
        assert job.model_state == "ok"  # the failed build did not touch the live model

    await run_with_loop(body)
    del config.MODEL_CATALOG["mine"]


async def test_release_retries_restore():
    """A lost release (Mender unreachable) once left the board without a classifier."""
    reset()
    config.RELEASE_RETRY_SECONDS = 0
    job = qm.join()

    async def body():
        assert await wait_for(lambda: job.state is qm.JobState.ACTIVE)
        assert qm.program(job.id, Path("/tmp/user.rbf"))
        assert await wait_for(lambda: job.program_state == "ok")
        deploy_results.extend(["ConnectError: Name or service not known", "boom"])
        assert qm.finish(job.id)
        assert await wait_for(lambda: deployed.count(config.RESTORE_ARTIFACT) == 3), deployed
        await asyncio.sleep(0.1)
        assert deployed.count(config.RESTORE_ARTIFACT) == 3  # stops once one succeeds

    await run_with_loop(body)
    config.RELEASE_RETRY_SECONDS = 30


async def test_no_show_release():
    reset()
    config.ACK_GRACE_SECONDS = 0.05
    config.SESSION_SECONDS = 60
    job = qm.join()

    async def body():
        # never acked -> released once the grace window passes; nothing was
        # programmed, so the classifier is still live and no redeploy is needed
        assert await wait_for(lambda: job.state is qm.JobState.RELEASED), job.state
        assert not job.acked
        assert deployed == []

    await run_with_loop(body)


async def test_failed_program_keeps_session():
    reset()
    config.ACK_GRACE_SECONDS = 60
    config.SESSION_SECONDS = 60
    deploy_results.append("board rejected it")  # first deploy of the session fails
    job = qm.join()

    async def body():
        assert await wait_for(lambda: job.state is qm.JobState.ACTIVE), job.state
        qm.ack(job.id)

        assert qm.program(job.id, Path("/tmp/bad.rbf"))
        assert await wait_for(lambda: job.program_state == "failed"), job.program_state
        assert job.program_error and job.state is qm.JobState.ACTIVE

        # the user retries within the same slot
        assert qm.program(job.id, Path("/tmp/good.rbf"))
        assert await wait_for(lambda: job.program_state == "ok"), job.program_state
        assert job.program_error is None
        assert len(deployed) == 2, deployed

    await run_with_loop(body)


async def test_program_rejected_while_busy():
    reset()
    config.ACK_GRACE_SECONDS = 60
    config.SESSION_SECONDS = 60
    other = qm.join()   # queued, never active
    job = qm.join()

    async def body():
        assert await wait_for(lambda: other.state is qm.JobState.ACTIVE), other.state
        assert not qm.program(job.id, Path("/tmp/user.rbf"))  # not the active session
        assert qm.program(other.id, Path("/tmp/a.rbf"))
        assert not qm.program(other.id, Path("/tmp/b.rbf"))   # deploy already pending

    await run_with_loop(body)


async def test_session_timeout():
    reset()
    config.ACK_GRACE_SECONDS = 60
    config.SESSION_SECONDS = 0.05
    job = qm.join()

    async def body():
        assert await wait_for(lambda: job.state is qm.JobState.ACTIVE), job.state
        qm.ack(job.id)
        assert await wait_for(lambda: job.state is qm.JobState.RELEASED), job.state

    await run_with_loop(body)


async def test_skip_preempts_active():
    reset()
    config.ACK_GRACE_SECONDS = 60
    config.SESSION_SECONDS = 60
    first, second, third = qm.join(), qm.join(), qm.join()

    async def body():
        assert await wait_for(lambda: first.state is qm.JobState.ACTIVE), first.state
        qm.ack(first.id)
        assert not qm.skip(first.id)  # only a queued job can skip
        assert qm.skip(third.id)
        assert qm.position(third.id) == 1 and qm.position(second.id) == 2
        assert await wait_for(lambda: first.state is qm.JobState.RELEASED), first.state
        assert await wait_for(lambda: third.state is qm.JobState.ACTIVE), third.state
        assert second.state is qm.JobState.QUEUED
        assert deployed == []  # nothing programmed, no redeploy

    await run_with_loop(body)


async def test_delete_model():
    reset()
    config.MODEL_CATALOG["tmp-x"] = "coredla-model-tmp-x-deadbeef"
    d = config.EDGE_AI_DIR / "models" / "tmp-x"
    d.mkdir(parents=True, exist_ok=True)
    (d / "name").write_text("tmp-x\n")
    assert await qm.delete_model("fruit") == "not a user-uploaded model"
    assert await qm.delete_model("nope") == "not a user-uploaded model"
    qm._live_model = "tmp-x"
    assert "on the board" in await qm.delete_model("tmp-x")
    qm._live_model = config.MODEL_NAME
    assert await qm.delete_model("tmp-x") is None
    assert "tmp-x" not in config.MODEL_CATALOG and not d.exists()


async def main():
    for t in (
        test_happy_path,
        test_model_switch,
        test_model_upload_build,
        test_release_retries_restore,
        test_no_show_release,
        test_failed_program_keeps_session,
        test_program_rejected_while_busy,
        test_session_timeout,
        test_skip_preempts_active,
        test_delete_model,
    ):
        await t()
        print("ok:", t.__name__)


if __name__ == "__main__":
    asyncio.run(main())
