"""D10 video bandwidth: python3 run_D10.py [seconds]. Per condition: N viewers pull for T s; bytes counted at the client, NIC counters from the lab PC.
live = backend SSE /session/camera/stream (needs an active session); webcam = board MJPEG http://coredla:8080/stream."""
import sys, time, threading, csv, requests, subprocess, harness as h
T = float(sys.argv[1]) if len(sys.argv) > 1 else 30
ifs = ["eno1", "tailscale0", "lo"]
def nic(): return {i: tuple(int(open(f"/sys/class/net/{i}/statistics/{d}_bytes").read()) for d in ("rx", "tx")) for i in ifs}
def load(): return subprocess.run(["ssh", h.BOARD, "cut -d' ' -f1 /proc/loadavg"], capture_output=True, text=True).stdout.strip()
def viewer(url, out, k, params=None):
    n = 0; t = time.monotonic()
    try:
        with requests.get(url, params=params, stream=True, timeout=(5, 10)) as r:
            for c in r.iter_content(65536):
                n += len(c)
                if time.monotonic() - t >= T: break
    except Exception as e: out[k] = (n, f"fail:{e}"); return
    out[k] = (n, "ok")
j = h.join()
with h.Series("D10-video", "") as s, open(f"{s.dir}/viewers.csv", "a", newline="") as f:
    s.cleanup(lambda: h.finish(j)); w = csv.writer(f)
    if f.tell() == 0: w.writerow(["condition", "viewers", "seconds", "viewer", "bytes", "mbit_s", "result"])
    nl = csv.writer(open(f"{s.dir}/nic.csv", "a", newline=""))
    conds = [("idle", 0), ("live", 1), ("live", 5), ("webcam", 1), ("webcam", 5)]
    for kind, n in conds:
        time.sleep(8); a, la = nic(), load(); t0 = time.monotonic(); out = {}
        if kind == "live": url, p = f"{h.BACKEND}/session/camera/stream", {"job_id": j}
        else: url, p = "http://coredla:8080/stream", None
        th = [threading.Thread(target=viewer, args=(url, out, i, p)) for i in range(n)]
        [x.start() for x in th]
        if n == 0: time.sleep(T)
        [x.join() for x in th]; dt = time.monotonic() - t0; b, lb = nic(), load()
        for i in range(n):
            by, res = out.get(i, (0, "fail:none")); w.writerow([kind, n, f"{dt:.1f}", i, by, f"{by*8/dt/1e6:.3f}", res])
        nl.writerow([kind, n, f"{dt:.1f}", la, lb] + [x for i in ifs for x in (b[i][0]-a[i][0], b[i][1]-a[i][1])])
        ok = [v for v in out.values() if v[1] == "ok"]
        s.record(f"{kind}-{n}", "ok" if len(ok) == n else "fail:viewer", dt)
        print(kind, n, f"{dt:.1f}s", [f"{v[0]*8/dt/1e6:.2f}" for v in out.values()], "Mbit/s per viewer; load", la, "->", lb, flush=True)
    f.flush()
print("nic columns: condition,viewers,seconds,load_before,load_after," + ",".join(f"{i}_rx,{i}_tx" for i in ifs))
