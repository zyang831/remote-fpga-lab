"""Route-level self-check: join/upload validation + status/ack/finish wiring.

Run: python test_main.py

TestClient is used WITHOUT a `with` block on purpose, so the lifespan hook
never runs and no real deploy is attempted.
"""

import os
import time

os.environ.setdefault("MENDER_URL", "http://fake")
os.environ.setdefault("MENDER_USER", "fake")
os.environ.setdefault("MENDER_PASS", "fake")

from fastapi.testclient import TestClient

import config
import main
import queue_manager as qm

client = TestClient(main.app)


GOOD_RBF = config.RBF_MAGIC + b"\x00" * config.MIN_RBF_BYTES  # header + size of a real core.rbf


def join():
    return client.post("/queue/join").json()["job_id"]


def program(job_id, filename, data):
    return client.post(
        "/session/program",
        params={"job_id": job_id},
        files={"bitstream": (filename, data, "application/octet-stream")},
    )


def test_rejects_bad_extension():
    assert program(join(), "evil.exe", b"x").status_code == 400


def test_rejects_oversize():
    config.MAX_RBF_BYTES = 10
    assert program(join(), "big.rbf", b"x" * 11).status_code == 413


def test_join_and_queue_status():
    config.MAX_RBF_BYTES = 8 * 1024 * 1024  # undo test_rejects_oversize
    r = client.post("/queue/join")
    assert r.status_code == 200, r.text
    job_id = r.json()["job_id"]
    assert r.json()["position"] == 1

    assert client.get("/queue/status", params={"job_id": job_id}).json() == {
        "state": "queued",
        "position": 1,
        "eta_seconds": 0,  # nothing active, nobody ahead
    }
    s = client.get("/session/status", params={"job_id": job_id}).json()
    assert s == {
        "state": "queued",
        "seconds_left": None,
        "expiring_soon": False,
        "program_state": "none",
        "program_error": None,
        "model_state": "none",
        "model_error": None,
        "upload_state": "none",
        "upload_error": None,
        "phase": None,
        "busy_seconds": None,
    }

    # not active yet -> every session action must refuse
    assert client.post("/session/ack", params={"job_id": job_id}).status_code == 409
    assert client.post("/session/finish", params={"job_id": job_id}).status_code == 409
    assert program(job_id, "design.rbf", GOOD_RBF).status_code == 409


def test_program_saves_file_for_active_session():
    config.MAX_RBF_BYTES = 8 * 1024 * 1024
    job_id = join()
    job = qm.get(job_id)
    job.state = qm.JobState.ACTIVE     # the loop is not running under TestClient
    qm._active = job
    qm._queue.clear()

    assert program(job_id, "design.rbf", GOOD_RBF).status_code == 200
    assert job.pending_rbf.read_bytes() == GOOD_RBF
    job.pending_rbf.unlink()


def test_rejects_not_an_rbf():
    """Random bytes wedged the board's FPGA manager; a truncated file programmed "ok"."""
    config.MAX_RBF_BYTES = 8 * 1024 * 1024
    job_id = join()
    job = qm.get(job_id)
    job.state = qm.JobState.ACTIVE
    qm._active = job
    qm._queue.clear()
    for data in (os.urandom(len(GOOD_RBF)), GOOD_RBF[:65536]):
        r = program(job_id, "design.rbf", data)
        assert r.status_code == 400, r.text
    assert job.pending_rbf is None


def test_seconds_left_is_relative_not_absolute():
    """The client cannot trust its own clock, so status must count down for it."""
    job_id = join()
    job = qm.get(job_id)
    job.state = qm.JobState.ACTIVE
    job.session_ends_at = time.time() + 300
    s = client.get("/session/status", params={"job_id": job_id}).json()
    assert 299 <= s["seconds_left"] <= 300, s
    assert s["expiring_soon"] is False

    job.session_ends_at = time.time() + 60
    assert client.get("/session/status", params={"job_id": job_id}).json()["expiring_soon"] is True

    # An overrun session reports 0, never a negative countdown.
    job.session_ends_at = time.time() - 5
    assert client.get("/session/status", params={"job_id": job_id}).json()["seconds_left"] == 0


def test_unknown_job_404():
    assert client.get("/queue/status", params={"job_id": "nope"}).status_code == 404
    assert client.post("/session/ack", params={"job_id": "nope"}).status_code == 404


def test_eta_counts_the_live_slot_plus_full_slots_ahead():
    """Position alone is meaningless; the client renders this as '~34 min'."""
    active = qm.get(join())
    active.state = qm.JobState.ACTIVE
    active.session_ends_at = time.time() + 300
    qm._active = active
    qm._queue.clear()

    first, second = join(), join()
    eta = lambda j: client.get("/queue/status", params={"job_id": j}).json()["eta_seconds"]

    assert 299 <= eta(first) <= 300, eta(first)
    assert abs(eta(second) - eta(first) - config.SESSION_SECONDS) < 1

    # The active job is out of the queue, so it has no wait to report.
    assert eta(active.id) is None


def test_config_endpoint():
    assert client.get("/config").json() == {
        "board_stream_url": config.BOARD_STREAM_URL,
        "max_rbf_bytes": config.MAX_RBF_BYTES,
        "mender_problems": [],  # lifespan (preflight) does not run under TestClient
    }


def test_model_catalog_and_switch_gate():
    assert client.get("/session/models").json() == {"models": list(config.MODEL_CATALOG), "builtin": sorted(config.BUILTIN_MODELS)}
    job_id = join()  # queued, not active
    r = client.post("/session/model", params={"job_id": job_id}, json={"name": "flag"})
    assert r.status_code == 409, r.text
    assert client.post("/session/model", params={"job_id": job_id}, json={"name": "nope"}).status_code == 400
    assert client.post("/session/model", params={"job_id": "nope"}, json={"name": "flag"}).status_code == 404
    job = qm.get(job_id)
    qm._active, job.state = job, qm.JobState.ACTIVE  # fake an active session
    try:
        assert client.post("/session/model", params={"job_id": job_id}, json={"name": "flag"}).json() == {"switching": True}
        s = client.get("/session/status", params={"job_id": job_id}).json()
        assert s["model_state"] == "switching" and s["model_error"] is None
        assert s["phase"] == "queued for the board" and 0 <= s["busy_seconds"] < 5
    finally:
        qm._active = None


def test_model_upload_validation():
    """The fruit-v1 IR is a valid user upload (the notebook kit, ResNet-18, N=15); everything else must bounce."""
    import shutil

    flag = config.EDGE_AI_DIR / "models" / "fruit-v1"
    xml, cats = (flag / "model.xml").read_bytes(), (flag / "categories.txt").read_bytes()
    bin_size = (flag / "model.bin").stat().st_size

    def upload(name, xml=xml, cats=cats, bin_bytes=None, job_id=None):
        return client.post(
            "/session/model/upload",
            params={"job_id": job_id},
            data={"name": name},
            files={
                "model_xml": ("model.xml", xml, "application/xml"),
                "model_bin": ("model.bin", bin_bytes if bin_bytes is not None else b"\0" * bin_size, "application/octet-stream"),
                "categories": ("categories.txt", cats, "text/plain"),
            },
        )

    job = qm.get(join())
    assert upload("t-flag", job_id=job.id).status_code == 409  # queued, not active
    qm._active, job.state = job, qm.JobState.ACTIVE
    try:
        assert upload("Bad Name", job_id=job.id).status_code == 400
        assert upload("fruit", job_id=job.id).status_code == 400  # built-in
        assert upload("fruit-v1", job_id=job.id).status_code == 400  # the reference IR every upload is checked against
        r = upload("t-flag", cats=cats + b"extra\n", job_id=job.id)
        assert r.status_code == 400 and "16" in r.json()["detail"], r.text
        r = upload("t-flag", xml=xml.replace(b'type="SoftMax"', b'type="Sigmoid"', 1), job_id=job.id)
        assert r.status_code == 400 and "differs" in r.json()["detail"], r.text
        r = upload("t-flag", bin_bytes=b"\0" * (bin_size - 4), job_id=job.id)
        assert r.status_code == 400 and "model.bin is" in r.json()["detail"], r.text
        assert upload("t-flag", bin_bytes=b"\0" * (config.MAX_IR_BIN_BYTES + 1), job_id=job.id).status_code == 413
        assert (config.EDGE_AI_DIR / "models" / "t-flag").exists() is False  # nothing written on reject

        r = upload("t-flag", job_id=job.id)
        assert r.status_code == 200 and r.json() == {"building": True, "classes": 15}, r.text
        d = config.EDGE_AI_DIR / "models" / "t-flag"
        assert (d / "model.bin").stat().st_size == bin_size and (d / "name").read_text() == "t-flag\n"
        assert job.upload_state == "building" and job.pending_upload == "t-flag"
        assert upload("t-flag2", job_id=job.id).status_code == 409  # one build at a time
        # Same name from a second tab while it builds: refused before it touches the files the build reads.
        assert upload("t-flag", bin_bytes=b"\1" * bin_size, job_id=job.id).status_code == 409
        assert (d / "model.bin").read_bytes()[:1] == b"\0"
    finally:
        qm._active = None
        shutil.rmtree(config.EDGE_AI_DIR / "models" / "t-flag", ignore_errors=True)
        shutil.rmtree(config.EDGE_AI_DIR / "models" / "t-flag2", ignore_errors=True)


def test_live_camera_gate_and_parse():
    import io
    from PIL import Image
    import board_infer

    assert client.get("/session/camera/stream", params={"job_id": join()}).status_code == 409  # queued, not active
    jpg = io.BytesIO()
    Image.new("RGB", (8, 4), (200, 10, 10)).save(jpg, format="JPEG")
    js = b'{"top5":[{"index":0,"label":"apple\\r","prob":0.9}],"latency_ms":234,"frame":7}'
    r = board_infer.parse_live(b"fruit", js, jpg.getvalue())
    assert r["model"] == "fruit" and r["frame"] == 7
    assert r["top5"][0]["label"] == "apple"
    assert "top5" not in board_infer.parse_live(b"fruit", b"", jpg.getvalue())  # frame before the first inference
    assert r["image"].startswith("data:image/jpeg;base64,")


def test_static_files_revalidate():
    r = client.get("/app.js")
    assert r.headers["cache-control"] == "no-cache"
    assert client.get("/app.js", headers={"if-none-match": r.headers["etag"]}).status_code == 304


def test_notebook_points_at_this_server():
    r = TestClient(main.app, base_url="http://10.0.0.5:8000").get("/training_demo.ipynb")
    assert r.status_code == 200 and "localhost:8000" not in r.text
    assert 'LAB_URL = \\"http://10.0.0.5:8000\\"' in r.text


if __name__ == "__main__":
    for t in (
        test_rejects_bad_extension,
        test_rejects_oversize,
        test_join_and_queue_status,
        test_program_saves_file_for_active_session,
        test_rejects_not_an_rbf,
        test_seconds_left_is_relative_not_absolute,
        test_eta_counts_the_live_slot_plus_full_slots_ahead,
        test_unknown_job_404,
        test_config_endpoint,
        test_model_catalog_and_switch_gate,
        test_model_upload_validation,
        test_live_camera_gate_and_parse,
        test_static_files_revalidate,
        test_notebook_points_at_this_server,
    ):
        qm._jobs.clear()
        qm._queue.clear()
        qm._active = None
        t()
        print("ok:", t.__name__)
