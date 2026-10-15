"""D6 CoreDLA latency on the board (same method as the CPU baseline): stops dla-server (sudo), always restarts it. python3 run_D6dla.py [runs]"""
import os, sys, shlex, subprocess, time, statistics as st, harness as h
runs = int(sys.argv[1]) if len(sys.argv) > 1 else 150; warm = 20
M = os.path.expanduser("~/edge-ai-demo/models")
BIN = "/home/fyp-student/fyp/final/paper/notes/dla_bench/build/dla_bench"
MODELS = {"resnet18": f"{M}/fruit-v1", "resnet50": f"{M}/my-flags"}  # graph.bin + .arch per model
SUDO = f"echo {shlex.quote(os.environ['BOARD_SUDO'])} | sudo -S -p '' "  # board sudo password from the environment
def ssh(cmd, t=900): return subprocess.run(["ssh", h.BOARD, cmd], capture_output=True, text=True, timeout=t)
ssh("mkdir -p ~/bench/dla-resnet18 ~/bench/dla-resnet50")
subprocess.run(["scp", "-q", BIN, f"{h.BOARD}:bench/dla_bench"], check=True)
for m, d in MODELS.items():
    subprocess.run(["scp", "-q", f"{d}/graph.bin", f"{d}/AGX5_Small_k16c16_sb20480.arch", f"{h.BOARD}:bench/dla-{m}/"], check=True)
was = ssh("systemctl is-active dla-server").stdout.strip(); print("dla-server was", was)
env = ssh("uptime; uname -r; cat /var/lib/dla/model/name").stdout.strip().replace("\n", " | ")
try:
    ssh(SUDO + "systemctl stop dla-server.service"); time.sleep(20)
    print("load after stop:", ssh("cat /proc/loadavg").stdout.strip())
    for m in MODELS:
        it = f"D6-dla-{m}"
        with h.Series(it, env) as s:
            cmd = (f"cd ~/app && export COREDLA_ROOT=$PWD && ./sdklibs/ld-linux-aarch64.so.1 --library-path ./sdklibs:. "
                   f"$HOME/bench/dla_bench ./plugins.xml $HOME/bench/dla-{m}/graph.bin $HOME/bench/dla-{m}/AGX5_Small_k16c16_sb20480.arch {warm} {runs}")
            r = ssh(cmd); us = [int(x) for x in r.stdout.split("\n") if x.strip().isdigit()]
            open(f"{s.dir}/raw/stderr.txt", "w").write(r.stderr)
            if len(us) != runs: s.record(m, f"fail:got{len(us)}", 0); print(it, "FAIL", r.stderr[-400:], flush=True); continue
            for u in us: s.record(m, "ok", u / 1e6)
            med = st.median(us) / 1e3; p95 = sorted(us)[int(.95 * len(us)) - 1] / 1e3
            print(f"{it}: median {med:.1f} ms p95 {p95:.1f} mean {st.mean(us)/1e3:.1f} sd {st.stdev(us)/1e3:.1f} -> {1e6/st.mean(us):.2f} img/s", flush=True)
finally:
    ssh(SUDO + "systemctl start dla-server.service"); print("dla-server restarted:", ssh("systemctl is-active dla-server").stdout.strip(), flush=True)
