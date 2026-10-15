"""FastAPI app: upload/status routes over queue_manager, plus the static frontend.

Every state transition belongs to the queue_manager background loop started
here on startup; these handlers only enqueue jobs or set flags it reads.
"""

import asyncio
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import Body, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

import board_infer
import config
import mender_client
import model_upload
import queue_manager as qm

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

_EXPIRING_SOON_SECONDS = 120
_mender_problems: list[str] = []  # set once by mender_client.preflight() at startup


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _mender_problems
    try:
        _mender_problems = await mender_client.preflight()
    except Exception as e:  # server down or bad creds: still serve the GUI, say why deploys will fail
        log.exception("mender preflight failed")
        _mender_problems = [f"Mender server check failed: {type(e).__name__}: {e}"]
    task = asyncio.create_task(qm.run_loop())
    yield
    task.cancel()


app = FastAPI(lifespan=lifespan)


def _job_or_404(job_id: str) -> qm.Job:
    job = qm.get(job_id)
    if not job:
        raise HTTPException(404, "unknown job_id")
    return job


@app.post("/queue/join")
async def queue_join():
    """Take a place in line for the board. No bitstream needed until the session starts."""
    job = qm.join()
    log.info("queued job %s", job.id)
    return {"job_id": job.id, "position": qm.position(job.id)}


@app.post("/session/program")
async def session_program(job_id: str, bitstream: UploadFile = File(...)):
    """Reconfigure the board from inside a live session. Repeatable."""
    _job_or_404(job_id)
    name = bitstream.filename or ""
    if not name.endswith(".rbf"):
        raise HTTPException(400, "filename must end in .rbf")
    if bitstream.size is None or bitstream.size > config.MAX_RBF_BYTES:
        raise HTTPException(413, f"bitstream exceeds {config.MAX_RBF_BYTES} bytes")

    data = await bitstream.read()
    if not data.startswith(config.RBF_MAGIC):
        raise HTTPException(400, "not an Agilex 5 .core.rbf (unexpected header)")
    if len(data) < config.MIN_RBF_BYTES:
        raise HTTPException(400, "too small to be a complete Agilex 5 .core.rbf")

    config.UPLOADS_DIR.mkdir(exist_ok=True)
    dest = config.UPLOADS_DIR / f"{uuid.uuid4()}.rbf"
    dest.write_bytes(data)

    if not qm.program(job_id, dest):
        dest.unlink(missing_ok=True)
        raise HTTPException(409, "not the active session, or a deploy is already running")
    log.info("job %s programming from %s (%s bytes)", job_id, name, bitstream.size)
    return {"programming": True}


@app.post("/queue/skip")
async def queue_skip(job_id: str):
    """Demo: cut to the front of the line; the live session (if any) is released."""
    _job_or_404(job_id)
    if not qm.skip(job_id):
        raise HTTPException(409, "job is not queued")
    log.info("job %s skipped the queue", job_id)
    return {"skipped": True}


@app.get("/queue/status")
async def queue_status(job_id: str):
    job = _job_or_404(job_id)
    return {
        "state": job.state,
        "position": qm.position(job_id),
        "eta_seconds": qm.eta_seconds(job_id),
    }


@app.get("/session/status")
async def session_status(job_id: str):
    job = _job_or_404(job_id)
    # Relative, not an absolute epoch: the browser's clock can be minutes off ours.
    left = None if job.session_ends_at is None else max(0.0, job.session_ends_at - time.time())
    return {
        "state": job.state,
        "seconds_left": left,
        "expiring_soon": job.state is qm.JobState.ACTIVE and left is not None and left <= _EXPIRING_SOON_SECONDS,
        "program_state": job.program_state,
        "program_error": job.program_error,
        "model_state": job.model_state,
        "model_error": job.model_error,
        "upload_state": job.upload_state,
        "upload_error": job.upload_error,
        # Progress of the in-flight deploy/build: a step name and how long the whole
        # operation has run (relative seconds, same clock-skew reasoning as above).
        "phase": job.phase,
        "busy_seconds": None if job.busy_since is None else max(0.0, time.time() - job.busy_since),
    }


@app.post("/session/ack")
async def session_ack(job_id: str):
    _job_or_404(job_id)
    if not qm.ack(job_id):
        raise HTTPException(409, "job is not active")
    return {"acked": True}


@app.post("/session/finish")
async def session_finish(job_id: str):
    _job_or_404(job_id)
    if not qm.finish(job_id):
        raise HTTPException(409, "job is not the active session")
    return {"releasing": True}


def _live_gate(job_id: str):
    _job_or_404(job_id)
    if not qm.is_active(job_id):
        raise HTTPException(409, "not the active session")
    if qm.get(job_id).program_state != "none":
        raise HTTPException(409, "your .rbf replaced the classifier design; pick a model to bring it back")


@app.get("/session/camera/stream")
async def session_camera_stream(job_id: str):
    """Server-sent events: `frame` per new camera frame (~14 Hz, with the newest
    classification, ~4 Hz), `problem` while none arrive, `fatal` then end."""
    _live_gate(job_id)

    def sse(event: str, data: dict) -> str:
        return f"event: {event}\ndata: {json.dumps(data)}\n\n"

    async def events():
        try:
            async for frame in board_infer.live_stream():
                try:
                    _live_gate(job_id)  # session ended or an .rbf went on mid-stream
                except HTTPException as e:
                    yield sse("fatal", {"detail": e.detail})
                    return
                if frame is None:
                    yield sse("problem", {"detail": "the camera feed is not running (model loading, or no camera on this model)"})
                else:
                    yield sse("frame", frame)
        except board_infer.InferError as e:
            yield sse("fatal", {"detail": e.detail})

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@app.get("/session/model")
async def session_model():
    """Live classifier name + its labels, so the client can match filename ground truth."""
    try:
        return await board_infer.live_model()
    except board_infer.InferError as e:
        raise HTTPException(e.status, e.detail)


@app.get("/session/models")
async def session_models():
    """Catalog the active session can switch between."""
    return {"models": list(config.MODEL_CATALOG), "builtin": sorted(config.BUILTIN_MODELS)}


@app.delete("/session/model")
async def session_delete_model(job_id: str, name: str):
    """Demo cleanup: remove a user upload so the chip row does not pile up."""
    _job_or_404(job_id)
    if not qm.is_active(job_id):
        raise HTTPException(409, "not the active session")
    if why := await qm.delete_model(name):
        raise HTTPException(409, why)
    log.info("job %s deleted model %s", job_id, name)
    return {"deleted": True}


@app.post("/session/model")
async def session_switch_model(job_id: str, name: str = Body(embed=True)):
    """Deploy a catalog model to the board (minutes: ~120 MB over Tailscale + graph import)."""
    _job_or_404(job_id)
    if name not in config.MODEL_CATALOG:
        raise HTTPException(400, f"unknown model; choose one of {', '.join(config.MODEL_CATALOG)}")
    if not qm.switch_model(job_id, name):
        raise HTTPException(409, "not the active session, or a deploy is already running")
    log.info("job %s switching model to %s", job_id, name)
    return {"switching": True}


@app.post("/session/model/upload")
async def session_model_upload(
    job_id: str,
    name: str = Form(...),
    model_xml: UploadFile = File(...),
    model_bin: UploadFile = File(...),
    categories: UploadFile = File(...),
):
    """Fine-tuned ResNet-18 IR in, catalog entry + deploy out. Validation here is
    what can fail fast; dla_compiler runs in the queue loop (upload_state)."""
    _job_or_404(job_id)
    if not qm.is_active(job_id):
        raise HTTPException(409, "not the active session")
    if not model_upload.NAME_RE.match(name):
        raise HTTPException(400, "name must be 1-32 chars of a-z, 0-9, - (starting with a letter or digit)")
    if name in config.BUILTIN_MODELS or name == config.REFERENCE_IR_XML.parent.name:
        raise HTTPException(400, f"{name} is a built-in model; pick another name")
    for f, cap, what in (
        (model_xml, config.MAX_IR_XML_BYTES, "model.xml"),
        (model_bin, config.MAX_IR_BIN_BYTES, "model.bin"),
        (categories, config.MAX_CATEGORIES_BYTES, "categories.txt"),
    ):
        if f.size is None or f.size > cap:
            raise HTTPException(413, f"{what} exceeds {cap} bytes")
    xml, cats_bytes = await model_xml.read(), await categories.read()
    try:
        cats = model_upload.read_categories(cats_bytes)
        n_ref = len(model_upload.read_categories((config.REFERENCE_IR_XML.parent / "categories.txt").read_bytes()))
        model_upload.check_ir(xml, config.REFERENCE_IR_XML.read_bytes(), n_ref, len(cats))
    except ValueError as e:
        log.warning("job %s upload %s rejected: %s", job_id, name, e)
        raise HTTPException(400, str(e))
    # Expected weight size: reference minus its FC (N x 512 + N floats) plus ours.
    ref_bin = (config.REFERENCE_IR_XML.parent / "model.bin").stat().st_size
    if model_bin.size != ref_bin + (len(cats) - n_ref) * 513 * 4:
        msg = f"model.bin is {model_bin.size} bytes; a {len(cats)}-class ResNet-18 IR should be {ref_bin + (len(cats) - n_ref) * 513 * 4}"
        log.warning("job %s upload %s rejected: %s", job_id, name, msg)
        raise HTTPException(400, msg)

    # Last await: from the idle check to build_model() nothing else runs, so a second
    # upload (another tab) can not overwrite the files a running build reads.
    weights = await model_bin.read()
    if not qm._idle_active(job_id):
        raise HTTPException(409, "not the active session, or a deploy is already running")
    d = config.EDGE_AI_DIR / "models" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "model.xml").write_bytes(xml)
    (d / "categories.txt").write_text("".join(f"{c}\n" for c in cats))  # normalized line endings
    (d / "name").write_text(name + "\n")
    (d / "model.bin").write_bytes(weights)
    qm.build_model(job_id, name)
    log.info("job %s uploaded IR %s (%d classes)", job_id, name, len(cats))
    return {"building": True, "classes": len(cats)}


@app.get("/config")
async def client_config():
    """Frontend reads the board stream URL from here (no templating dependency)."""
    return {
        "board_stream_url": config.BOARD_STREAM_URL,
        # So the client can reject an oversize .rbf before uploading 8 MB of it.
        "max_rbf_bytes": config.MAX_RBF_BYTES,
        "mender_problems": _mender_problems,
    }


@app.get("/training_demo.ipynb")
async def training_notebook(request: Request):
    """The notebook fetches fruit-v1.pt from LAB_URL; point it at the address it was
    downloaded from, so it also works on a student laptop, not just on this host."""
    nb = (config.BASE_DIR / "static" / "training_demo.ipynb").read_text(encoding="utf-8")
    nb = nb.replace("http://localhost:8000", str(request.base_url).rstrip("/"))
    return Response(nb, media_type="application/x-ipynb+json", headers={"Cache-Control": "no-cache"})


class _Revalidated(StaticFiles):
    """no-cache: without it the browser reuses a stale app.js after a redeploy
    (heuristic freshness from Last-Modified); the ETag keeps reloads a cheap 304."""

    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        resp.headers["Cache-Control"] = "no-cache"
        return resp


# Mounted last so it never shadows the API routes above.
app.mount("/", _Revalidated(directory=config.BASE_DIR / "static", html=True), name="static")
