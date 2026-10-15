"""Mender management API + mender-artifact CLI wrapper.

One function per API call, plus deploy() which orchestrates
build -> upload -> create deployment -> poll.
"""

import asyncio
import logging
import shutil
import tempfile
import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

import config

log = logging.getLogger(__name__)

_token: str | None = None
_TIMEOUT = httpx.Timeout(120.0, connect=10.0)

# Progress callback: deploy()/deploy_existing() report each step through it so the
# caller can show "board downloading" instead of a silent 3-minute wait.
OnPhase = Callable[[str], None]
_no_phase: OnPhase = lambda _: None

# Mender per-device statuses, in the words a user waiting at the browser needs.
# "pending" is the long unexplained one: the board only polls the server every so often.
_DEVICE_PHASE = {
    "pending": "waiting for the board to check in and pick up the update",
    "downloading": "board downloading the update",
    "installing": "board installing the update",
    "rebooting": "board rebooting",
    "pause_before_installing": "board paused before installing",
    "pause_before_committing": "board paused before committing",
    "pause_before_rebooting": "board paused before rebooting",
}


async def login() -> str:
    """Fetch a fresh JWT (raw token in the response body) and cache it."""
    global _token
    async with httpx.AsyncClient(base_url=config.MENDER_URL, timeout=_TIMEOUT) as c:
        r = await c.post(
            "/api/management/v1/useradm/auth/login",
            auth=(config.MENDER_USER, config.MENDER_PASS),
        )
        r.raise_for_status()
    _token = r.text.strip()
    return _token


async def _request(method: str, path: str, **kw) -> httpx.Response:
    """Authenticated request; logs in on first use, re-logs in once on 401."""
    token = _token or await login()
    async with httpx.AsyncClient(base_url=config.MENDER_URL, timeout=_TIMEOUT) as c:
        r = await c.request(method, path, headers={"Authorization": f"Bearer {token}"}, **kw)
        if r.status_code == 401:
            token = await login()
            r = await c.request(method, path, headers={"Authorization": f"Bearer {token}"}, **kw)
    r.raise_for_status()
    return r


_BOARD_RBF_NAME = "output_design.core.rbf"  # hardcoded in the on-board fpga-reconfig module


async def build_artifact(rbf_path: Path, dtb_path: Path, artifact_name: str, out_path: Path) -> Path:
    """Run mender-artifact to package the .rbf + .dtb as an fpga-reconfig artifact.

    mender-artifact names each payload file after its source basename, and the
    board-side module reads back a fixed filename (see _BOARD_RBF_NAME) — so the
    source file must be staged under that name before packaging, whatever the
    caller's rbf_path is actually called.
    """
    staged_rbf = out_path.parent / _BOARD_RBF_NAME
    shutil.copyfile(rbf_path, staged_rbf)
    proc = await asyncio.create_subprocess_exec(
        "mender-artifact", "write", "module-image",
        "-T", "fpga-reconfig",
        "-t", config.DEVICE_TYPE,
        "-n", artifact_name,
        "-o", str(out_path),
        "-f", str(staged_rbf),
        "-f", str(dtb_path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    out, _ = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"mender-artifact failed ({proc.returncode}): {out.decode().strip()}")
    return out_path


async def artifact_exists(artifact_name: str) -> bool:
    r = await _request("GET", "/api/management/v1/deployments/artifacts", params={"name": artifact_name})
    return any(a.get("name") == artifact_name for a in r.json())


async def delete_artifact(artifact_name: str) -> None:
    """Remove an artifact from the server. Mender refuses (409) while a deployment
    references it, so callers treat failure as best effort."""
    r = await _request("GET", "/api/management/v1/deployments/artifacts", params={"name": artifact_name})
    for a in r.json():
        if a.get("name") == artifact_name:
            await _request("DELETE", f"/api/management/v1/deployments/artifacts/{a['id']}")


async def upload_artifact(mender_file: Path) -> None:
    """Upload a .mender artifact. The binary part must be last in the multipart body."""
    with mender_file.open("rb") as fh:
        await _request(
            "POST",
            "/api/management/v1/deployments/artifacts",
            files={"artifact": (mender_file.name, fh, "application/octet-stream")},
        )


async def create_deployment(artifact_name: str, device_id: str) -> str:
    """Create a deployment for one device; returns the deployment id."""
    r = await _request(
        "POST",
        "/api/management/v1/deployments/deployments",
        json={"name": artifact_name, "artifact_name": artifact_name, "devices": [device_id]},
    )
    return r.headers["Location"].rstrip("/").rsplit("/", 1)[-1]


async def device_status(deployment_id: str) -> str | None:
    """Our device's status inside one deployment (pending/downloading/installing/...)."""
    r = await _request("GET", f"/api/management/v1/deployments/deployments/{deployment_id}/devices")
    return next((d.get("status") for d in r.json() if d.get("id") == config.DEVICE_ID), None)


async def poll_until_finished(deployment_id: str, timeout: float = 900.0, on_phase: OnPhase = _no_phase) -> str | None:
    """Poll until the deployment leaves pending/inprogress. None if the device succeeded,
    otherwise a message describing why it did not. Reports the device's step via on_phase."""
    deadline = time.monotonic() + timeout
    last_status = None
    while time.monotonic() < deadline:
        r = await _request("GET", f"/api/management/v1/deployments/deployments/{deployment_id}")
        if r.json().get("status") != "finished":
            try:
                status = await device_status(deployment_id)
            except Exception:  # progress detail only; the outer poll still decides the outcome
                status = None
            if status and status != last_status:
                last_status = status
                on_phase(_DEVICE_PHASE.get(status, f"board: {status}"))
        if r.json().get("status") == "finished":
            stats = (await _request(
                "GET", f"/api/management/v1/deployments/deployments/{deployment_id}/statistics"
            )).json()
            ok = stats.get("failure", 0) == 0 and (
                stats.get("success", 0) + stats.get("already-installed", 0)
            ) > 0
            if ok:
                return None
            log.error("deployment %s finished unsuccessfully: %s", deployment_id, stats)
            return f"the board rejected the bitstream and rolled back ({stats})"
        await asyncio.sleep(2)
    log.error("deployment %s still unfinished after %ss, aborting it", deployment_id, timeout)
    # Otherwise a slow board installs it later, in the next student's session.
    try:
        await _request("PUT", f"/api/management/v1/deployments/deployments/{deployment_id}/status",
                       json={"status": "aborted"})
    except Exception:  # 422 = it finished meanwhile; either way the caller reports the timeout
        log.exception("abort of deployment %s failed", deployment_id)
    return f"the board did not report back within {timeout:.0f}s"


_LIVE_WITHIN = timedelta(minutes=5)  # board polls every 5 s (board/mender.conf)


async def preflight() -> list[str]:
    """Run once at startup, before the queue loop. Points config.DEVICE_ID at the
    board that is actually checking in (the id changes whenever the board's Mender
    identity does), and aborts deployments a previous backend left unfinished:
    nothing will ever poll them and the board would install them out of turn.
    Returns the problems it could not fix, for the GUI to show."""
    problems = []
    now = datetime.now(timezone.utc)
    accepted = (await _request("GET", "/api/management/v2/devauth/devices",
                               params={"status": "accepted", "per_page": 500})).json()
    live = [d["id"] for d in accepted
            if d.get("check_in_time") and now - datetime.fromisoformat(d["check_in_time"]) < _LIVE_WITHIN]
    if config.DEVICE_ID not in live:
        if len(live) == 1:
            log.warning("DEVICE_ID %s has not checked in; switching to live board %s", config.DEVICE_ID, live[0])
            config.DEVICE_ID = live[0]
        else:
            pending = (await _request("GET", "/api/management/v2/devauth/devices",
                                      params={"status": "pending", "per_page": 500})).json()
            problems.append(
                f"board {config.DEVICE_ID} has not checked in with Mender for 5+ min "
                f"({len(live)} other live boards"
                + (f"; pending, accept one in the Mender UI: {', '.join(d['id'] for d in pending)}" if pending else "")
                + "); model switches will not reach it"
            )
    for status in ("pending", "inprogress"):
        r = await _request("GET", "/api/management/v1/deployments/deployments",
                           params={"status": status, "per_page": 500})
        for d in r.json():
            await _request("PUT", f"/api/management/v1/deployments/deployments/{d['id']}/status",
                           json={"status": "aborted"})
            log.warning("aborted leftover deployment %s (%s)", d["id"], d.get("artifact_name"))
    for p in problems:
        log.error("mender preflight: %s", p)
    return problems


async def deploy_existing(artifact_name: str, on_phase: OnPhase = _no_phase) -> str | None:
    """Deploy an artifact that is already on the server (a prebuilt coredla-model) and wait.

    Mender reports already-installed when the board is on it, which counts as success.
    """
    try:
        on_phase("asking the update server to send it to the board")
        dep_id = await create_deployment(artifact_name, config.DEVICE_ID)
        log.info("deployment %s created for existing artifact %s", dep_id, artifact_name)
        return await poll_until_finished(dep_id, on_phase=on_phase)
    except httpx.HTTPStatusError as e:
        log.exception("deploy failed for artifact %s", artifact_name)
        return f"{e.request.method} {e.request.url.path} -> {e.response.status_code}: {e.response.text[:200]}"
    except Exception as e:
        log.exception("deploy failed for artifact %s", artifact_name)
        return f"{type(e).__name__}: {e}"


async def deploy(rbf_path: Path, artifact_name: str, on_phase: OnPhase = _no_phase) -> str | None:
    """Build, upload, deploy and wait.

    None on success; on failure, a short message for the caller to surface. The
    message reaches the user's browser, so it names what actually went wrong
    rather than making them read the server log.
    """
    try:
        with tempfile.TemporaryDirectory() as tmp:
            on_phase("packaging the bitstream")
            art = await build_artifact(
                Path(rbf_path), config.DTB_PATH, artifact_name, Path(tmp) / f"{artifact_name}.mender"
            )
            on_phase("uploading the package to the update server")
            await upload_artifact(art)
        on_phase("asking the update server to send it to the board")
        dep_id = await create_deployment(artifact_name, config.DEVICE_ID)
        log.info("deployment %s created for artifact %s", dep_id, artifact_name)
        return await poll_until_finished(dep_id, on_phase=on_phase)
    except httpx.HTTPStatusError as e:
        log.exception("deploy failed for artifact %s", artifact_name)
        # Mender puts the useful part in the body, not the status line.
        return f"{e.request.method} {e.request.url.path} -> {e.response.status_code}: {e.response.text[:200]}"
    except Exception as e:
        log.exception("deploy failed for artifact %s", artifact_name)
        return f"{type(e).__name__}: {e}"


if __name__ == "__main__":
    # Smoke test against the real server: python mender_client.py <file.rbf> [artifact-name]
    import sys

    logging.basicConfig(level=logging.INFO)
    rbf = Path(sys.argv[1])
    name = sys.argv[2] if len(sys.argv) > 2 else f"smoke-{int(time.time())}"
    print("deploy error:", asyncio.run(deploy(rbf, name)) or "none (success)")
