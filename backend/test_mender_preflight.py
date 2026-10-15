"""Startup Mender check against a fake server. Run: python test_mender_preflight.py"""

import asyncio
import os
from datetime import datetime, timedelta, timezone

os.environ.setdefault("MENDER_URL", "http://fake")
os.environ.setdefault("MENDER_USER", "fake")
os.environ.setdefault("MENDER_PASS", "fake")

import config
import mender_client


def ago(minutes):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z")


class Resp:
    def __init__(self, body):
        self.body = body

    def json(self):
        return self.body


def fake_server(accepted, pending=(), deployments=()):
    aborted = []

    async def request(method, path, **kw):
        status = kw.get("params", {}).get("status")
        if method == "PUT":
            aborted.append(path.split("/")[-2])
            return Resp(None)
        if path.endswith("devauth/devices"):
            return Resp(accepted if status == "accepted" else list(pending))
        return Resp([d for d in deployments if d["status"] == status])

    mender_client._request = request
    return aborted


async def main():
    # Configured id is live: nothing changes, leftover deployments aborted.
    config.DEVICE_ID = "live"
    aborted = fake_server([{"id": "live", "check_in_time": ago(0.1)}, {"id": "old", "check_in_time": ago(60 * 24)}],
                          deployments=[{"id": "d1", "status": "pending", "artifact_name": "a"},
                                       {"id": "d2", "status": "inprogress", "artifact_name": "b"}])
    assert await mender_client.preflight() == []
    assert config.DEVICE_ID == "live" and aborted == ["d1", "d2"]

    # Stale configured id (the 2026-09-23 bug): switch to the one live board.
    config.DEVICE_ID = "old"
    fake_server([{"id": "live", "check_in_time": ago(1)}, {"id": "old", "check_in_time": ago(60 * 24)}])
    assert await mender_client.preflight() == []
    assert config.DEVICE_ID == "live"

    # No live board, one pending: cannot fix, report it with the pending id.
    config.DEVICE_ID = "old"
    fake_server([{"id": "old", "check_in_time": ago(60)}], pending=[{"id": "new"}])
    (p,) = await mender_client.preflight()
    assert config.DEVICE_ID == "old" and "new" in p
    print("ok: preflight")

    # A deployment the board never finishes is aborted when the wait times out.
    aborted = fake_server([])
    orig = mender_client._request

    async def never_finished(method, path, **kw):
        if method == "GET" and path.endswith("/d9"):
            return Resp({"status": "inprogress"})
        return await orig(method, path, **kw)

    mender_client._request = never_finished
    assert "did not report back" in await mender_client.poll_until_finished("d9", timeout=0.01)
    assert aborted == ["d9"]
    print("ok: abort on timeout")


if __name__ == "__main__":
    asyncio.run(main())
