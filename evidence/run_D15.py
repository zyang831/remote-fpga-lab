"""D15: own-model upload to live (method of MEASURE_VI.md line 6), random 0-5 s gap (seed 1).
python3 run_D15.py N   (N excludes the 1 warm-up). Rows -> data/D15-ownmodel/runs.csv. Time = POST upload until /session/model reports the new name."""
import sys, time, random, requests, harness as h
d = "/home/fyp-student/edge-ai-demo/models/fruit-v1"; n = int(sys.argv[1]); env = open(f"{h.DATA}/env.md").readline().strip()
random.seed(1); j = h.join(); made = []
def fresh(need):
    global j
    if (h.status(j)["seconds_left"] or 0) < need: h.finish(j); time.sleep(40); j = h.join()
with h.Series("D15-ownmodel", env) as s:
    s.cleanup(lambda: h.finish(j))
    def delete_models():
        requests.post(f"{h.BACKEND}/session/model", params={"job_id": j}, json={"name": "fruit"}); h.wait(j, "model_state", limit=300)
        for m in made: requests.delete(f"{h.BACKEND}/session/model", params={"job_id": j, "name": m})
    s.cleanup(delete_models)
    for i in range(n + 1):
        fresh(240); name = f"d15-{int(time.time()) % 100000}"; made.append(name)
        def run():
            r = requests.post(f"{h.BACKEND}/session/model/upload", params={"job_id": j}, data={"name": name},
                files={"model_xml": open(f"{d}/model.xml", "rb"), "model_bin": open(f"{d}/model.bin", "rb"), "categories": open(f"{d}/categories.txt", "rb")})
            if not r.ok: return f"fail:http{r.status_code}:{r.text[:80]}"
            res = h.wait(j, "upload_state", limit=400)
            if res == "ok": res = h.wait(j, "model_state", limit=400)
            if res != "ok": return res
            for _ in range(240):
                try:
                    if requests.get(f"{h.BACKEND}/session/model", timeout=5).json().get("name") == name: return "ok"
                except Exception: pass
                time.sleep(0.5)
            return "fail:not_live"
        print(i, name, s.timed(name, run, warmup=(i == 0)), flush=True)
        g = random.uniform(0, 5); print(f"gap {g:.2f}", flush=True); time.sleep(g)
    print(s.summary())
