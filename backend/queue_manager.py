"""FIFO queue + session state machine for the single DE25-Nano board.

In-memory, single process. One background loop (`run_loop`) owns every state
transition; the HTTP handlers only enqueue jobs or set flags the loop reads.
That keeps the deploy calls serialised without any locking.

Users queue for the board itself, not for one bitstream: a session starts as
soon as the board is free, and the user reprograms it as often as they like
within their slot. A failed deploy is reported and the session continues.
"""

import asyncio
import logging
import shutil
import time
import uuid
from collections import deque
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import config
import mender_client

log = logging.getLogger(__name__)


class JobState(str, Enum):
    QUEUED = "queued"
    ACTIVE = "active"
    RELEASED = "released"


@dataclass
class Job:
    id: str
    state: JobState = JobState.QUEUED
    session_ends_at: float | None = None  # epoch seconds, set on entering ACTIVE
    ack_deadline: float | None = None     # epoch seconds
    acked: bool = False
    release_reason: str | None = None     # set by finish(), consumed by the loop
    pending_rbf: Path | None = None       # set by program(), consumed by the loop
    program_state: str = "none"           # none | programming | ok | failed
    program_error: str | None = None
    pending_model: str | None = None      # set by switch_model(), consumed by the loop
    model_state: str = "none"             # none | switching | ok | failed
    model_error: str | None = None
    pending_upload: str | None = None     # set by build_model(), consumed by the loop
    upload_state: str = "none"            # none | building | ok | failed
    upload_error: str | None = None
    # What the in-flight deploy/build is doing right now, and since when the
    # whole operation has been running. Shown in the browser so a 3-minute
    # model load reads as progress, not as a hang.
    phase: str | None = None
    busy_since: float | None = None       # epoch seconds


_jobs: dict[str, Job] = {}
_queue: deque[str] = deque()
_active: Job | None = None
# Catalog entry the board is (believed to be) on. ponytail: a backend restart
# forgets a switch; the next post-.rbf release then puts the default back.
_live_model: str = config.MODEL_NAME


def join() -> Job:
    """Take a place in line for the board."""
    job = Job(id=str(uuid.uuid4()))
    _jobs[job.id] = job
    _queue.append(job.id)
    return job


def get(job_id: str) -> Job | None:
    return _jobs.get(job_id)


def position(job_id: str) -> int | None:
    """1-based place in line, or None once the job has left the queue."""
    try:
        return _queue.index(job_id) + 1
    except ValueError:
        return None


def eta_seconds(job_id: str) -> float | None:
    """Rough wait before a queued job starts: rest of the live slot + full slots ahead.

    Assumes nobody releases early, so it is an upper bound, which is the kind
    users forgive. None once the job has left the queue.
    """
    pos = position(job_id)
    if pos is None:
        return None
    eta = (pos - 1) * config.SESSION_SECONDS
    if _active and _active.session_ends_at is not None:
        eta += max(0.0, _active.session_ends_at - time.time())
    return eta


def ack(job_id: str) -> bool:
    """User confirmed they are at the keyboard; clears the no-show timer."""
    job = _jobs.get(job_id)
    if not job or job.state is not JobState.ACTIVE:
        return False
    job.acked = True
    return True


def is_active(job_id: str) -> bool:
    """True while this job owns the board (inference is allowed)."""
    return bool(_active) and _active.id == job_id and _active.state is JobState.ACTIVE


def _idle_active(job_id: str) -> bool:
    """This job owns the board and no deploy is in flight."""
    return (
        is_active(job_id)
        and _active.program_state != "programming"
        and _active.model_state != "switching"
        and _active.upload_state != "building"
    )


def program(job_id: str, rbf_path: Path) -> bool:
    """Hand a bitstream to the loop. False unless this is the idle active session."""
    if not _idle_active(job_id):
        return False
    _active.pending_rbf = Path(rbf_path)
    _active.program_state = "programming"  # set here, not in the loop, so a second
    _active.program_error = None           # upload is rejected before the loop ticks
    _begin(_active, "queued for the board")
    return True


def switch_model(job_id: str, name: str) -> bool:
    """Hand a catalog model to the loop. False unless idle active and name is in the catalog."""
    if name not in config.MODEL_CATALOG or not _idle_active(job_id):
        return False
    _active.pending_model = name
    _active.model_state = "switching"
    _active.model_error = None
    _begin(_active, "queued for the board")
    return True


def build_model(job_id: str, name: str) -> bool:
    """Hand an uploaded IR (already in EDGE_AI_DIR/models/<name>/) to the loop: compile,
    bundle, upload, add to the catalog, then deploy it. False unless idle active."""
    if not _idle_active(job_id):
        return False
    _active.pending_upload = name
    _active.upload_state = "building"
    _active.upload_error = None
    _begin(_active, "queued for the build")
    return True


async def delete_model(name: str) -> str | None:
    """Drop a user-uploaded model: catalog entry, IR + graph on disk, bundle, and
    (best effort) the Mender artifact. Returns a reason when it must stay."""
    if name in config.BUILTIN_MODELS or name not in config.MODEL_CATALOG:
        return "not a user-uploaded model"
    if name == _live_model:
        return "that model is on the board; switch to another one first"
    if _active and name in (_active.pending_model, _active.pending_upload):
        return "that model is being deployed"
    artifact = config.MODEL_CATALOG.pop(name)
    shutil.rmtree(config.EDGE_AI_DIR / "models" / name, ignore_errors=True)
    (config.EDGE_AI_DIR / "build" / f"{artifact}.mender").unlink(missing_ok=True)
    try:
        await mender_client.delete_artifact(artifact)
    except Exception as e:  # Mender keeps artifacts referenced by past deployments
        log.warning("could not delete artifact %s from Mender: %s", artifact, e)
    log.info("deleted user model %s (%s)", name, artifact)
    return None


def _begin(job: Job, phase: str) -> None:
    job.phase, job.busy_since = phase, time.time()


def _done(job: Job) -> None:
    job.phase = job.busy_since = None


def _phase_setter(job: Job):
    def set_phase(text: str) -> None:
        job.phase = text
    return set_phase


def finish(job_id: str) -> bool:
    """Voluntary early release. The loop performs the actual release next tick."""
    if not _active or _active.id != job_id or _active.state is not JobState.ACTIVE:
        return False
    _active.release_reason = "finished"
    return True


def skip(job_id: str) -> bool:
    """Demo shortcut: jump this queued job to the front and kick the live session.
    ponytail: unauthenticated, anyone can preempt anyone; gate behind an env flag
    or drop the route before real students share the board."""
    job = _jobs.get(job_id)
    if not job or job.state is not JobState.QUEUED:
        return False
    _queue.remove(job_id)
    _queue.appendleft(job_id)
    if _active and _active.state is JobState.ACTIVE:
        _active.release_reason = "preempted"
    return True


async def _program(job: Job) -> None:
    """Deploy the bitstream the user just uploaded. Failure does not end the session."""
    rbf, job.pending_rbf = job.pending_rbf, None
    # Artifact names must be unique per deploy: one session programs many times.
    err = await mender_client.deploy(rbf, f"fpga-lab-{job.id}-{int(time.time())}", _phase_setter(job))
    job.program_state = "failed" if err else "ok"
    job.program_error = err
    _done(job)
    if err:
        log.error("deploy failed for job %s: %s", job.id, err)


async def _switch(job: Job) -> None:
    """Deploy a catalog model. Its bundle carries the DLA .rbf, so a user .rbf is gone after it."""
    global _live_model
    name, job.pending_model = job.pending_model, None
    err = await mender_client.deploy_existing(config.MODEL_CATALOG[name], _phase_setter(job))
    job.model_state = "failed" if err else "ok"
    job.model_error = err
    _done(job)
    if err:
        log.error("model switch to %s failed for job %s: %s", name, job.id, err)
        return
    _live_model = name
    job.program_state, job.program_error = "none", None


async def _build(job: Job) -> None:
    """dla_compiler on the host (~1 min) + artifact upload, then a normal switch.
    The loop blocks meanwhile, like it does for a deploy: one compile at a time.
    Lines the script prints as "=== <step>" become the phase shown in the browser."""
    name, job.pending_upload = job.pending_upload, None
    script = config.EDGE_AI_DIR / "artifacts" / "build-user-model.sh"
    proc = await asyncio.create_subprocess_exec(
        str(script), name, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    lines: list[str] = []

    async def read_out() -> None:
        async for raw in proc.stdout:
            line = raw.decode(errors="replace").rstrip()
            lines.append(line)
            if line.startswith("=== "):
                job.phase = line[4:]
        await proc.wait()

    try:
        await asyncio.wait_for(read_out(), config.BUILD_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        proc.kill()
        proc.returncode = -1
    text = "\n".join(lines).strip()
    if proc.returncode != 0:
        # Last lines carry the compiler's or smoke test's own complaint.
        job.upload_state, job.upload_error = "failed", f"build failed: {text[-400:] or 'timed out'}"
        log.error("build of %s for job %s failed:\n%s", name, job.id, text)
        _done(job)
        return
    artifact = text.rsplit("\n", 1)[-1]
    job.phase = "uploading the compiled model to the update server"
    try:
        if not await mender_client.artifact_exists(artifact):
            await mender_client.upload_artifact(config.EDGE_AI_DIR / "build" / f"{artifact}.mender")
    except Exception as e:
        job.upload_state, job.upload_error = "failed", f"artifact upload failed: {type(e).__name__}: {e}"
        log.exception("artifact upload of %s failed for job %s", artifact, job.id)
        _done(job)
        return
    config.MODEL_CATALOG[name] = artifact
    job.upload_state = "ok"
    log.info("job %s built %s -> %s", job.id, name, artifact)
    # Straight into the switch: busy_since keeps counting from the upload, phase moves on.
    job.pending_model, job.model_state, job.model_error = name, "switching", None
    job.phase = "queued for the board"


async def _release(job: Job, reason: str) -> None:
    """End the session. The idle design is the CoreDLA classifier; only a session
    that programmed its own .rbf over it needs it put back. The board keeps the last
    good model design itself (/var/lib/dla/idle), so a 5 KB restore artifact does it."""
    global _active
    job.state = JobState.RELEASED
    _active = None
    log.info("released job %s (%s)", job.id, reason)
    if job.program_state == "none":
        return
    # A lost release once left the board on a student .rbf with no classifier, so retry.
    # ponytail: holds the queue for up to RELEASE_RETRIES tries; the next student would
    # otherwise start on a board with no classifier.
    for attempt in range(1, config.RELEASE_RETRIES + 1):
        err = await mender_client.deploy_existing(config.RESTORE_ARTIFACT)
        if not err:
            return
        log.error("restore after job %s failed (try %d): %s", job.id, attempt, err)
        await asyncio.sleep(config.RELEASE_RETRY_SECONDS)


async def run_loop(tick: float = 1.0) -> None:
    """Background task started on FastAPI startup. Runs until cancelled."""
    global _active
    while True:
        if _active is None and _queue:
            job = _jobs[_queue.popleft()]
            now = time.time()
            _active = job
            job.state = JobState.ACTIVE
            job.session_ends_at = now + config.SESSION_SECONDS
            job.ack_deadline = now + config.ACK_GRACE_SECONDS
            log.info("session started for job %s", job.id)

        if _active:
            job, now = _active, time.time()
            if job.release_reason:
                await _release(job, job.release_reason)
            elif not job.acked and now > job.ack_deadline:
                await _release(job, "no-show")
            elif now > job.session_ends_at:
                await _release(job, "timeout")
            elif job.pending_rbf:
                await _program(job)
            elif job.pending_model:
                await _switch(job)
            elif job.pending_upload:
                await _build(job)

        await asyncio.sleep(tick)
