"""D2: python3 run_D2.py model N | bit N   (N excludes the 1 warm-up). Rows -> data/D2-*/runs.csv."""
import sys, time, requests, harness as h
R = "/home/<user>/edge-ai-demo"; L = "/home/<user>/fyp/legacy/ota_test_artifacts_2026-07"
BITS = [f"{R}/demo/webui/1-bitstream/{n}.core.rbf" for n in ("led-bouncing", "led-johnson", "ghrd", "edge-ai-dla")] + \
       [f"{L}/CoreDLA_NoSoftmax/output_design.core.rbf", f"{L}/CoreDLA_Softmax/output_design.core.rbf"]
mode, n = sys.argv[1], int(sys.argv[2]); env = open(f"{h.DATA}/env.md").readline().strip()[-19:]
j = h.join()
def fresh(need):
    global j
    if (h.status(j)["seconds_left"] or 0) < need: h.finish(j); time.sleep(40); j = h.join()
def live(): return requests.get(f"{h.BACKEND}/session/model", timeout=5).json().get("name")
with h.Series(f"D2-{mode}", env) as s:
    s.cleanup(lambda: h.finish(j))
    if mode == "model":
        names = ["flag", "fruit"]
        for i in range(n + 1):
            fresh(150); tgt = names[i % 2]
            def run():
                r = requests.post(f"{h.BACKEND}/session/model", params={"job_id": j}, json={"name": tgt})
                if not r.ok: return f"fail:http{r.status_code}"
                res = h.wait(j, "model_state", limit=300)
                return res if res != "ok" else ("ok" if live() == tgt else "fail:not_live")
            print(i, tgt, s.timed(tgt, run, warmup=(i == 0)), flush=True); time.sleep(1)
    else:
        for i in range(n + 1):
            fresh(120); f = BITS[i % len(BITS)]
            def run():
                r = requests.post(f"{h.BACKEND}/session/program", params={"job_id": j}, files={"bitstream": open(f, "rb")})
                return h.wait(j, "program_state") if r.ok else f"fail:http{r.status_code}"
            print(i, f.split("/")[-2] if "output_design" in f else f.split("/")[-1], s.timed(
                f.split("/")[-2] if "output_design" in f else f.split("/")[-1], run, sha256=h.sha(f), warmup=(i == 0)), flush=True)
            time.sleep(1)
    print(s.summary())
