"""D6 CPU baseline on the board: stops dla-server (sudo) for the run, always restarts it. python3 run_D6.py [runs]"""
import sys, subprocess, time, statistics as st, harness as h
runs = int(sys.argv[1]) if len(sys.argv) > 1 else 150; warm = 20
BIN = "/home/<user>/fyp/final/paper/notes/cpu_bench/build/cpu_bench"
MODELS = {"resnet18": "~/bench/r18/model.xml", "resnet50": "~/bench/r50/model.xml"}
CONF = [("A76", "2,3", 2), ("A76", "2", 1), ("A55", "0,1", 2), ("A55", "0", 1)]
SUDO = "echo '<BOARD_PASSWORD>' | sudo -S -p '' "
def ssh(cmd, t=600): return subprocess.run(["ssh", h.BOARD, cmd], capture_output=True, text=True, timeout=t)
subprocess.run(["scp", "-q", BIN, f"{h.BOARD}:bench/cpu_bench"], check=True)
was = ssh("systemctl is-active dla-server").stdout.strip(); print("dla-server was", was)
env = ssh("uptime; uname -r").stdout.strip().replace("\n", " | ")
try:
    ssh(SUDO + "systemctl stop dla-server.service"); time.sleep(20)
    print("load after stop:", ssh("cat /proc/loadavg").stdout.strip())
    for mname, mp in MODELS.items():
        for core, cpus, thr in CONF:
            it = f"D6-cpu-{mname}-{core}-t{thr}"
            with h.Series(it, env) as s:
                cmd = (f"cd ~/app && export COREDLA_ROOT=$PWD && taskset -c {cpus} ./sdklibs/ld-linux-aarch64.so.1 --library-path ./sdklibs:. "
                       f"$HOME/bench/cpu_bench ./plugins.xml {mp} {thr} {warm} {runs}")
                r = ssh(cmd); us = [int(x) for x in r.stdout.split()]
                open(f"{s.dir}/raw/stderr.txt", "w").write(r.stderr)
                if len(us) != runs: s.record(mname, f"fail:got{len(us)}", 0); print(it, "FAIL", r.stderr[-300:]); continue
                for u in us: s.record(mname, "ok", u / 1e6)
                m = st.median(us) / 1e3; p95 = sorted(us)[int(.95 * len(us)) - 1] / 1e3
                print(f"{it}: median {m:.1f} ms p95 {p95:.1f} mean {st.mean(us)/1e3:.1f} -> {1000/st.mean(us)*1e3:.2f} img/s", flush=True)
finally:
    ssh(SUDO + "systemctl start dla-server.service"); print("dla-server restarted:", ssh("systemctl is-active dla-server").stdout.strip())
