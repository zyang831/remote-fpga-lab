"""The board's dla-server over ssh: the live camera stream (every frame it
publishes in <spool>/results, with the newest classification) and the staged
model's name + labels."""

import asyncio
import base64
import json
import shlex

import config


class InferError(Exception):
    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status, self.detail = status, detail


async def _ssh(script: str, stdin: bytes | None = None, timeout: float = 20.0) -> tuple[int, bytes, bytes]:
    proc = await asyncio.create_subprocess_exec(
        "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
        # Multiplex: the handshake is ~0.5 s of a ~0.9 s round trip otherwise.
        "-o", "ControlMaster=auto", "-o", "ControlPersist=120", "-o", f"ControlPath={config.UPLOADS_DIR}/.ssh-%C",
        config.BOARD_SSH, script,
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(stdin), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise InferError(504, "the board did not answer in time") from None
    return proc.returncode, out, err


LIVE_STALE_SECONDS = 5  # dla-server writes live.jpg ~15 Hz; a gap this long means it is gone or importing

# Runs on the board for the whole stream: every new live.jpg goes out as
# `<len name> <len json> <len jpg> <mtime ns>\n` + model name + live.json + live.jpg.
# Polling a stat is cheap; the board has no inotify tools. Exit 5: no camera.
_LIVE_STREAM = r"""
import os, sys, time
res, name_file = sys.argv[1:]
jpg, js = res + "/live.jpg", res + "/live.json"
if not os.path.exists(jpg):
    sys.exit(5)
out, last = sys.stdout.buffer, 0
while True:
    try:
        m = os.stat(jpg).st_mtime_ns
        if m != last:
            last = m
            parts = [open(f, "rb").read().strip() for f in (name_file, js)] + [open(jpg, "rb").read()]
            out.write(b"%d %d %d %d\n" % (*map(len, parts), m) + b"".join(parts))
            out.flush()
    except FileNotFoundError:  # live.json before the first inference, or a rename in flight
        pass
    time.sleep(0.01)
"""


def parse_live(name: bytes, js: bytes, jpg: bytes) -> dict:
    """One streamed frame -> live.json's fields (none before the first
    inference) plus model and the frame as a JPEG data URL."""
    result = json.loads(js) if js else {}
    for t in result.get("top5", ()):
        t["label"] = t["label"].strip()
    result.update(model=name.decode().strip(), image="data:image/jpeg;base64," + base64.b64encode(jpg).decode())
    return result


async def live_stream():
    """Yields every new camera frame dla-server publishes (parse_live dicts), or
    None when none came for LIVE_STALE_SECONDS. One ssh for the whole stream;
    it only reads files."""
    s = shlex.quote(config.BOARD_SPOOL)
    d = shlex.quote(config.BOARD_MODEL_DIR)
    proc = await asyncio.create_subprocess_exec(
        "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
        "-o", "ControlMaster=auto", "-o", "ControlPersist=120", "-o", f"ControlPath={config.UPLOADS_DIR}/.ssh-%C",
        config.BOARD_SSH, f"python3 -c {shlex.quote(_LIVE_STREAM)} {s}/results {d}/name",
        stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        limit=1 << 20,
    )
    try:
        while True:
            try:
                header = await asyncio.wait_for(proc.stdout.readline(), LIVE_STALE_SECONDS)
            except asyncio.TimeoutError:
                yield None
                continue
            if not header:
                rc = await proc.wait()
                if rc == 5:
                    raise InferError(404, "no live camera on this model")
                err = (await proc.stderr.read()).decode(errors="replace").strip()[:200]
                raise InferError(502, f"board ssh failed ({rc}): {err}")
            n_name, n_js, n_jpg, mtime = map(int, header.split())
            body = await proc.stdout.readexactly(n_name + n_js + n_jpg)
            frame = parse_live(body[:n_name], body[n_name:n_name + n_js], body[n_name + n_js:])
            frame["board_ms"] = mtime // 1_000_000  # when the board wrote it: the UI's fps clock
            yield frame
    finally:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()


async def live_model() -> dict:
    """{name, categories} as staged on the board: what the labels in results mean."""
    d = shlex.quote(config.BOARD_MODEL_DIR)
    rc, out, err = await _ssh(f"head -1 {d}/name && cat {d}/categories.txt")
    if rc != 0:
        raise InferError(502, f"no model staged on the board: {err.decode(errors='replace').strip()[:200]}")
    name, _, cats = out.decode().partition("\n")
    return {"name": name.strip(), "categories": cats.splitlines()}


if __name__ == "__main__":
    # Smoke test against the real board: python board_infer.py
    print(json.dumps(asyncio.run(live_model())["name"]))
