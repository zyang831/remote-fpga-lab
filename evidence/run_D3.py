"""D3 stage breakdown: python3 run_D3.py model|bit N. Per run: PC phase events + board journal markers -> data/D3-<kind>/stages.csv, raw/<i>_board.txt.
Board clock offset (board minus PC) is measured first and subtracted. Stage = difference of consecutive markers; missing marker -> blank."""
import sys, re, time, csv, subprocess, statistics as st, datetime as dt, requests, harness as h
R = "/home/<user>/edge-ai-demo/demo/webui/1-bitstream"
kind, n = sys.argv[1], int(sys.argv[2]); off, rtt = h.clock_offset(20)
M = [("pickup", r'Deployment with ID .* started'), ("install_start", r'Stopping CoreDLA inference server'),
     ("overlay_removed", r'mSGDMA Userio driver removed'), ("fabric_write", r'writing output_design\.core\.rbf'),
     ("drivers_loaded", r'Userio driver probe success'), ("srv_started", r'Started CoreDLA inference server'),
     ("srv_ready", r'ready: input'), ("finished", r'finished with status')]
PCM = ["t_request", "t_created", "t_download", "t_installing", "t_ok"]
def epoch(line): return dt.datetime.fromisoformat(line.split()[0]).timestamp() - off
j = h.join()
with h.Series(f"D3-{kind}", f"offset={off:+.3f}s") as s:
    s.cleanup(lambda: h.finish(j))
    f = open(f"{s.dir}/stages.csv", "w", newline=""); w = csv.writer(f); w.writerow(["index", "input", "warmup", "result"] + PCM + [m for m, _ in M])
    for i in range(n + 1):
        if (h.status(j)["seconds_left"] or 0) < 150: h.finish(j); time.sleep(40); j = h.join()
        if kind == "model": inp = ["flag", "fruit"][i % 2]
        else: inp = ["led-bouncing", "led-johnson", "ghrd"][i % 3]
        t0 = time.time(); tm = time.monotonic(); pc = {"t_request": t0}
        if kind == "model":
            r = requests.post(f"{h.BACKEND}/session/model", params={"job_id": j}, json={"name": inp}); key = "model_state"
        else:
            r = requests.post(f"{h.BACKEND}/session/program", params={"job_id": j}, files={"bitstream": open(f"{R}/{inp}.core.rbf", "rb")}); key = "program_state"
        res = "ok" if r.ok else f"fail:http{r.status_code}"
        while r.ok and time.monotonic() - tm < 300:
            st_ = h.status(j); ph = st_["phase"] or ""; now = time.time()
            for k, pat in (("t_created", "asking"), ("t_download", "downloading"), ("t_installing", "installing")):
                if pat in ph and k not in pc: pc[k] = now
            if st_[key] in ("ok", "failed"): pc["t_ok"] = now; res = "ok" if st_[key] == "ok" else "fail:failed"; break
            time.sleep(0.1)
        else:
            if r.ok: res = "fail:timeout"
        t1 = time.time(); time.sleep(5)
        log = subprocess.run(["ssh", h.BOARD, f"journalctl --no-pager -o short-iso-precise --since '@{t0 - 3 + off:.0f}' --until '@{t1 + 8 + off:.0f}' | cut -c1-230"],
                             capture_output=True, text=True, timeout=60).stdout
        open(f"{s.dir}/raw/{i}_board.txt", "w").write(log)
        mk = {}
        for line in log.splitlines():
            for name, pat in M:
                if name not in mk and re.search(pat, line):
                    e = epoch(line)
                    if e >= t0 - 1: mk[name] = e
        w.writerow([i, inp, int(i == 0), res] + [f"{pc.get(k, ''):.3f}" if k in pc else "" for k in PCM] + [f"{mk[m]:.3f}" if m in mk else "" for m, _ in M]); f.flush()
        s.record(inp, res, (pc.get("t_ok", t1)) - t0, warmup=(i == 0)); print(i, inp, res, f"{t1 - t0:.1f}", len(mk), "markers", flush=True)
    f.close(); print(s.summary())
