"""D8 failure repeats: python3 run_D8.py cut N | release N | stall T.  Needs BOARD_SUDO? no (PC sudo is passwordless for tc).
cut: truncated-graph model artifact deployed N times; release: program student bitstream then release, N times; stall: throttle link during a model download."""
import sys, os, time, json, asyncio, subprocess, shutil, requests
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import harness as h
for l in open(os.path.expanduser("~/mender/lab-backend/lab-backend.env")):
    if "=" in l and not l.startswith("#"): k, v = l.strip().split("=", 1); os.environ.setdefault(k, v)
sys.path.insert(0, os.path.expanduser("~/mender/lab-backend")); import mender_client as mc, config
R = os.path.expanduser("~/edge-ai-demo"); MUX = ["-o", "BatchMode=yes", "-o", "ControlMaster=auto", "-o", "ControlPath=/tmp/d8-%C", "-o", "ControlPersist=300"]
def state():
    r = subprocess.run(["ssh", *MUX, h.BOARD, "echo $(systemctl is-active dla-server) $(test -f /var/lib/dla/spool/ready && echo ready || echo noready) $(cat /var/lib/dla/model/name 2>/dev/null)"], capture_output=True, text=True, timeout=30)
    return r.stdout.strip()
def wait_state(want, limit=300, t0=None):
    t0 = t0 or time.monotonic()
    while time.monotonic() - t0 < limit:
        s = state()
        if s == want: return time.monotonic() - t0, s
        time.sleep(0.5)
    return None, state()
mode, n = sys.argv[1], float(sys.argv[2]); n = int(n)
prev = state(); print("start state:", prev, flush=True); assert prev.startswith("active ready"), prev
live = prev.split()[-1]
if mode == "cut":
    with h.Series("D8-graphcut", f"live-before={live}") as s:
        d = f"{R}/models/badgraph-1"; shutil.rmtree(d, ignore_errors=True); shutil.copytree(f"{R}/models/{live}", d)
        with open(f"{R}/models/{live}/graph.bin", "rb") as f: open(f"{d}/graph.bin", "wb").write(f.read(1 << 20))
        open(f"{d}/name", "w").write("badgraph-1\n"); s.cleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        out = subprocess.run(["bash", f"{R}/artifacts/build-model.sh", "badgraph-1"], capture_output=True, text=True, cwd=R); print(out.stdout[-200:], out.stderr[-200:])
        art = sorted(__import__("glob").glob(f"{R}/build/coredla-model-badgraph-1-*.mender"))[-1]; name = os.path.basename(art)[:-7]
        if not asyncio.run(mc.artifact_exists(name)): asyncio.run(mc.upload_artifact(__import__("pathlib").Path(art)))
        s.cleanup(lambda: asyncio.run(mc.delete_artifact(name))); s.cleanup(lambda: os.remove(art))
        for i in range(n):
            async def one():
                t = time.monotonic(); dep = await mc.create_deployment(name, config.DEVICE_ID); seen = []; last = None
                while True:
                    r = await mc._request("GET", f"/api/management/v1/deployments/deployments/{dep}")
                    st = await mc.device_status(dep)
                    if st != last: seen.append((round(time.monotonic() - t, 1), st)); last = st
                    if r.json().get("status") == "finished": break
                    await asyncio.sleep(0.5)
                stats = (await mc._request("GET", f"/api/management/v1/deployments/deployments/{dep}/statistics")).json()
                return time.monotonic() - t, stats, seen
            dt, stats, seen = asyncio.run(one()); back, st_ = wait_state(f"active ready {live}", 300)
            ok = stats.get("failure", 0) == 1 and back is not None
            s.record(f"badgraph-1:{live}", "ok" if ok else f"fail:{stats}|{st_}", dt)
            print(i, f"failed-status {dt:.1f}s", stats, seen, "classifier back after", None if back is None else f"{back:.1f}s", st_, flush=True)
            open(f"{s.dir}/raw/{i}_phases.txt", "w").write(json.dumps({"stats": stats, "seen": seen, "back_s": back, "state": st_}))
elif mode == "release":
    with h.Series("D8-release", f"live-before={live}") as s:
        f = f"{R}/demo/webui/1-bitstream/ghrd.core.rbf"
        for i in range(n):
            j = h.join(); r = requests.post(f"{h.BACKEND}/session/program", params={"job_id": j}, files={"bitstream": open(f, "rb")}); res = h.wait(j, "program_state")
            time.sleep(2); down = state()
            t = time.monotonic(); requests.post(f"{h.BACKEND}/session/finish", params={"job_id": j}); back, st_ = wait_state(f"active ready {live}", 300, t)
            s.record("ghrd-then-release", "ok" if back and res == "ok" else f"fail:{res}|{st_}", back or 0)
            print(i, "program", res, "state while own bitstream:", down, "| classifier back after release:", None if back is None else f"{back:.1f}s", st_, flush=True)
            time.sleep(3)
elif mode == "stall":
    T = n; IF = "eno1"
    with h.Series("D8-stall", f"live-before={live}") as s:
        target = "flag" if live != "flag" else "fruit"; name = config.MODEL_CATALOG[target]
        sh = lambda c: subprocess.run(c, shell=True, capture_output=True, text=True)
        s.cleanup(lambda: sh(f"sudo tc qdisc del dev {IF} root"))
        print(sh(f"sudo tc qdisc add dev {IF} root tbf rate 64kbit burst 1600 latency 400ms"))
        async def go():
            t = time.monotonic(); dep = await mc.create_deployment(name, config.DEVICE_ID); seen = []; last = None
            while time.monotonic() - t < T:
                st = await mc.device_status(dep)
                if st != last: seen.append((round(time.monotonic() - t, 1), st)); last = st
                await asyncio.sleep(1)
            ta = time.monotonic()
            await mc._request("PUT", f"/api/management/v1/deployments/deployments/{dep}/status", json={"status": "aborted"})
            return dep, seen, ta
        dep, seen, ta = asyncio.run(go()); print("device phases during stall:", seen, "| abort sent", flush=True)
        state_during = state(); print("board during stall:", state_during)
        sh(f"sudo tc qdisc del dev {IF} root"); t_rm = time.monotonic()
        # board must notice the abort, end the download and return to idle with the old model serving
        back, st_ = wait_state(f"active ready {live}", 600, ta); print("old model serving", back, st_)
        async def fin():
            return (await mc._request("GET", f"/api/management/v1/deployments/deployments/{dep}")).json().get("status"), await mc.device_status(dep)
        print("deployment/device status after abort:", asyncio.run(fin()))
        s.record(f"stall-{target}", "ok" if back is not None else f"fail:{st_}", back or 0)
        json.dump({"seen": seen, "state_during": state_during, "abort_to_old_model_s": back, "after": st_}, open(f"{s.dir}/raw/stall.json", "w"))
