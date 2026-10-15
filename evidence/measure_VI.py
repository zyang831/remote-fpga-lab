"""VI re-measure: python3 measure.py bit N | up N. Times are client wall clock, POST to final state."""
import sys, time, json, statistics as st, requests
B = "http://localhost:8000"; R = "/home/<user>/edge-ai-demo"
def join():
    j = requests.post(f"{B}/queue/join").json()["job_id"]
    if not requests.post(f"{B}/session/ack", params={"job_id": j}).ok:
        requests.post(f"{B}/queue/skip", params={"job_id": j}); time.sleep(3)
        for _ in range(60):
            if requests.post(f"{B}/session/ack", params={"job_id": j}).ok: return j
            time.sleep(2)
        raise SystemExit("never became active")
    return j
def status(j): return requests.get(f"{B}/session/status", params={"job_id": j}).json()
def wait(j, key, bad="failed", every=0.25, limit=300):
    t = time.time()
    while time.time() - t < limit:
        s = status(j)
        if s[key] == "ok": return True
        if s[key] == bad: return s
        time.sleep(every)
    return "timeout"
def finish(j): requests.post(f"{B}/session/finish", params={"job_id": j})
def summary(name, xs):
    if not xs: print(name, "no data"); return
    print(f"{name}: n={len(xs)} min={min(xs):.1f} mean={st.mean(xs):.1f} median={st.median(xs):.1f} max={max(xs):.1f}", flush=True)
mode, n = sys.argv[1], int(sys.argv[2]); out = []; j = join()
if mode == "bit":
    files = [f"{R}/demo/webui/1-bitstream/{f}.core.rbf" for f in ("led-bouncing", "led-johnson", "ghrd")]
    for i in range(n):
        if (status(j)["seconds_left"] or 0) < 120: finish(j); time.sleep(40); j = join()
        f = files[i % 3]; t = time.time()
        r = requests.post(f"{B}/session/program", params={"job_id": j}, files={"bitstream": open(f, "rb")})
        ok = wait(j, "program_state") if r.ok else r.text
        dt = time.time() - t; print(i, f.split("/")[-1], r.status_code, ok, f"{dt:.1f}", flush=True)
        if ok is True: out.append(dt)
        time.sleep(1)
    summary("student bitstream program (s)", out)
else:
    d = f"{R}/models/fruit-v1"
    for i in range(n):
        if (status(j)["seconds_left"] or 0) < 240: finish(j); time.sleep(40); j = join()
        name = f"meas-{int(time.time())%100000}"; t = time.time()
        r = requests.post(f"{B}/session/model/upload", params={"job_id": j}, data={"name": name},
            files={"model_xml": open(f"{d}/model.xml", "rb"), "model_bin": open(f"{d}/model.bin", "rb"), "categories": open(f"{d}/categories.txt", "rb")})
        if not r.ok: print(i, r.status_code, r.text); continue
        ok = wait(j, "upload_state", limit=400)
        ok2 = wait(j, "model_state", limit=400) if ok is True else ok
        t_ok = time.time() - t
        live = None
        for _ in range(240):
            try:
                if requests.get(f"{B}/session/model", timeout=5).json().get("name") == name: live = time.time() - t; break
            except Exception: pass
            time.sleep(0.5)
        print(i, name, ok, ok2, f"deployed {t_ok:.1f}", f"live {live}", flush=True)
        if live: out.append(live)
        requests.delete(f"{B}/session/model", params={"job_id": j, "name": name})
        time.sleep(1)
    summary("upload to live (s)", out)
finish(j)
