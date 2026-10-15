"""One switch with PC-side phase timeline + board journal window -> data/D3-pilot/. Usage: stage_pilot.py model|bit"""
import sys, time, subprocess, requests, os, harness as h
kind = sys.argv[1]; out = f"{h.DATA}/D3-pilot"; os.makedirs(out, exist_ok=True)
j = h.join(); ev = []
t0 = time.time(); tm = time.monotonic()
if kind == "model":
    r = requests.post(f"{h.BACKEND}/session/model", params={"job_id": j}, json={"name": sys.argv[2]}); key = "model_state"
else:
    r = requests.post(f"{h.BACKEND}/session/program", params={"job_id": j}, files={"bitstream": open(sys.argv[2], "rb")}); key = "program_state"
ev.append((time.time(), "request_done", r.status_code)); last = None
while time.monotonic() - tm < 200:
    s = h.status(j); cur = (s["phase"], s[key])
    if cur != last: ev.append((time.time(), "phase", cur)); last = cur
    if s[key] in ("ok", "failed"): break
    time.sleep(0.1)
t1 = time.time(); time.sleep(4)
with open(f"{out}/{kind}_pc.txt", "w") as f:
    f.write(f"t0 {t0:.3f}\n" + "".join(f"{t:.3f} {k} {v}\n" for t, k, v in ev))
log = subprocess.run(["ssh", "terasic@coredla", f"journalctl --no-pager -o short-iso-precise --since '@{t0-2:.0f}' --until '@{t1+5:.0f}' | cut -c1-230"], capture_output=True, text=True, timeout=60).stdout
open(f"{out}/{kind}_board.txt", "w").write(log)
h.finish(j); print(len(ev), "events", len(log.splitlines()), "board lines", f"{t1-t0:.1f}s")
