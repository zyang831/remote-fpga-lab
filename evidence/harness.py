"""Measurement harness for DATA_TODO runs.

python3 harness.py selfcheck   # stats + CSV round-trip asserts
python3 harness.py env         # write data/env.md (auto facts + manual TODO list)
python3 harness.py offset [N]  # board-minus-PC clock offset, appended to data/env.md

Use from a script:
    with Series("D2-model-switch", env_id) as s:          # data/<item>/runs.csv, raw/
        s.timed("fruit-v1", lambda: do_run() and "ok", sha256=sha(path), warmup=True)
        s.cleanup(lambda: delete_test_models())             # runs on exit, logged
    print(s.summary())                                      # also writes summary.md
CSV columns: index,input,sha256,result,seconds,env,warmup. result is "ok" or "fail:<reason>".
"""
import csv, hashlib, math, os, statistics as st, subprocess, sys, time, traceback
import requests

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
COLS = ["index", "input", "sha256", "result", "seconds", "env", "warmup"]
BACKEND = os.environ.get("BACKEND", "http://localhost:8000")
BOARD = os.environ.get("BOARD_SSH", "terasic@coredla")


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def fail_bound(k, n, alpha=0.05):
    """Exact (Clopper-Pearson) one-sided 100*(1-alpha)% upper bound on failure rate after k fails in n runs."""
    if k >= n: return 1.0
    cdf = lambda p: sum(math.comb(n, i) * p**i * (1 - p) ** (n - i) for i in range(k + 1))
    lo, hi = 0.0, 1.0
    for _ in range(60):  # P(X<=k) falls as p rises; find p with P = alpha
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if cdf(mid) > alpha else (lo, mid)
    return hi


def stats(xs):
    if not xs: return {}
    return dict(n=len(xs), mean=st.mean(xs), median=st.median(xs), sd=st.stdev(xs) if len(xs) > 1 else 0.0,
                min=min(xs), max=max(xs))


def summarize(rows):
    """rows: dicts as read from runs.csv. Warm-ups excluded; failures stay in the success rate."""
    rows = [r for r in rows if r["warmup"] != "1"]
    ok = [float(r["seconds"]) for r in rows if r["result"] == "ok"]
    k, n = len(rows) - len(ok), len(rows)
    return dict(runs=n, failures=k, fail_upper95=fail_bound(k, n) if n else None, **stats(ok))


class Series:
    def __init__(self, item, env_id="", root=DATA):
        self.dir, self.env_id, self._cleanups = os.path.join(root, item), env_id, []
        os.makedirs(os.path.join(self.dir, "raw"), exist_ok=True)
        self.path = os.path.join(self.dir, "runs.csv")
        new = not os.path.exists(self.path)
        self._f = open(self.path, "a", newline="")
        self._w = csv.writer(self._f)
        if new: self._w.writerow(COLS)
        self._i = 0 if new else len(self.rows())

    def __enter__(self): return self

    def __exit__(self, *exc):
        for fn in reversed(self._cleanups):
            try: fn(); self.log("cleanup ok")
            except Exception: self.log("cleanup FAILED " + traceback.format_exc())
        self._f.close()

    def log(self, msg):
        with open(os.path.join(self.dir, "raw", "harness.log"), "a") as f:
            f.write(f"{time.strftime('%F %T')} {msg}\n")

    def cleanup(self, fn): self._cleanups.append(fn)

    def record(self, inp, result, seconds, sha256="", warmup=False):
        self._w.writerow([self._i, inp, sha256, result, f"{seconds:.6f}", self.env_id, int(warmup)])
        self._f.flush(); self._i += 1

    def timed(self, inp, fn, sha256="", warmup=False):
        """fn() returns "ok" or a failure reason; exceptions become fail rows, never dropped."""
        t = time.monotonic()
        try: res = fn()
        except Exception as e: res = f"fail:{type(e).__name__}:{e}"
        dt = time.monotonic() - t
        res = "ok" if res in (True, "ok") else (res if str(res).startswith("fail") else f"fail:{res}")
        self.record(inp, res, dt, sha256, warmup)
        return res, dt

    def rows(self):
        with open(self.path, newline="") as f: return list(csv.DictReader(f))

    def summary(self):
        s = summarize(self.rows())
        lines = [f"# {os.path.basename(self.dir)} summary (generated from runs.csv)", ""]
        lines += [f"- {k}: {v:.3f}" if isinstance(v, float) else f"- {k}: {v}" for k, v in s.items()]
        lines += ["", "Feeds: (fill in table/section)", "Caveats: (fill in)"]
        with open(os.path.join(self.dir, "summary.md"), "w") as f: f.write("\n".join(lines) + "\n")
        return s


# --- backend session helpers (same calls the web page makes; lifted from measure_VI.py) ---
def join(base=BACKEND):
    j = requests.post(f"{base}/queue/join").json()["job_id"]
    for _ in range(60):
        if requests.post(f"{base}/session/ack", params={"job_id": j}).ok: return j
        time.sleep(2)
    raise SystemExit("never became active")


def status(j, base=BACKEND): return requests.get(f"{base}/session/status", params={"job_id": j}).json()


def wait(j, key, every=0.25, limit=300, base=BACKEND):
    """Poll session status[key] until ok. Returns "ok" or "fail:<state>"; deadline is monotonic."""
    t = time.monotonic()
    while time.monotonic() - t < limit:
        s = status(j, base)[key]
        if s == "ok": return "ok"
        if s == "failed": return "fail:failed"
        time.sleep(every)
    return "fail:timeout"


def finish(j, base=BACKEND): requests.post(f"{base}/session/finish", params={"job_id": j})


# --- environment and clock offset ---
def sh(cmd, ssh=False):
    if ssh: cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", BOARD, cmd]
    r = subprocess.run(cmd, shell=isinstance(cmd, str), capture_output=True, text=True, timeout=60)
    return (r.stdout + r.stderr).strip()


def clock_offset(n=20):
    """Board minus PC seconds over one persistent ssh (ControlMaster). Best (lowest-RTT) sample; error <= RTT/2."""
    sock = f"/tmp/harness-cm-{os.getpid()}"
    opt = ["-o", "BatchMode=yes", "-o", f"ControlPath={sock}", "-o", "ControlMaster=auto", "-o", "ControlPersist=30"]
    subprocess.run(["ssh", *opt, BOARD, "true"], capture_output=True, timeout=30)
    best = None
    for _ in range(n):
        t0 = time.time()
        out = subprocess.run(["ssh", *opt, BOARD, "date +%s.%N"], capture_output=True, text=True, timeout=10).stdout
        t1 = time.time()
        try: tb = float(out)
        except ValueError: continue
        s = (tb - (t0 + t1) / 2, t1 - t0)
        if best is None or s[1] < best[1]: best = s
    subprocess.run(["ssh", *opt, "-O", "exit", BOARD], capture_output=True)
    return best  # (offset_s, rtt_s)


def env_report():
    L = ["# Environment (auto-captured %s)" % time.strftime("%F %T"), ""]
    add = lambda k, v: L.append(f"- {k}: {v}")
    add("lab PC CPU", sh("lscpu | grep 'Model name' | sed 's/.*: *//'"))
    add("lab PC RAM", sh("free -h | awk '/Mem:/{print $2}'"))
    add("lab PC OS / kernel", sh("(. /etc/os-release; echo $PRETTY_NAME); uname -r").replace("\n", " / "))
    add("backend commit", sh("git -C ~/mender/lab-backend log --oneline -1"))
    add("Mender server images (id, created)", sh(
        "docker images --format '{{.Repository}}:{{.Tag}} {{.ID}} {{.CreatedSince}}' | grep -E 'deployments|deviceauth|useradm'"
    ).replace("\n", "; "))
    add("OpenVINO (lab PC)", sh("ls /opt/intel | tr '\\n' ' '"))
    add("Quartus", sh("quartus_sh --version | sed -n 2p"))
    add("board kernel / OS", sh("uname -r; . /etc/os-release; echo $PRETTY_NAME", ssh=True).replace("\n", " / "))
    add("board artifact_name", sh("grep artifact_name /etc/mender/artifact_info", ssh=True))
    add("board Mender client", sh("mender-update --version 2>&1 | head -1", ssh=True))
    L += ["", "## Manual (fill before first reported run)", "",
          "- [ ] FPGA AI Suite version (board /opt/dla is root-only; read from the build tree)",
          "- [ ] board SD image id",
          "- [ ] Mender server release (images are tagged :main; record deployed date or digest above)",
          "- [ ] network path for this session (direct link / routed / Wi-Fi)",
          "- [ ] OpenVINO version on board"]
    return "\n".join(L) + "\n"


def selfcheck():
    import tempfile
    assert abs(fail_bound(0, 20) - 0.139) < 0.001, fail_bound(0, 20)   # 1-0.05**(1/20)
    assert abs(fail_bound(0, 40) - 0.072) < 0.001, fail_bound(0, 40)
    assert abs(fail_bound(1, 20) - 0.216) < 0.001, fail_bound(1, 20)   # published CP value 0.2157
    with tempfile.TemporaryDirectory() as d:
        cleaned = []
        with Series("t", "env0", root=d) as s:
            s.cleanup(lambda: cleaned.append(1))
            s.timed("a", lambda: "ok", warmup=True)               # warm-up: excluded
            for x in (0.01, 0.02, 0.03): s.timed("a", lambda: time.sleep(x) or "ok")
            s.timed("b", lambda: "boom")                          # fail row kept
            s.timed("b", lambda: 1 / 0)                           # exception -> fail row
        assert cleaned == [1]
        s = Series("t", "env0", root=d); rows = s.rows(); s._f.close()
        assert len(rows) == 6 and sum(r["result"].startswith("fail") for r in rows) == 2
        r = summarize(rows)
        assert r["runs"] == 5 and r["failures"] == 2 and r["n"] == 3, r
        assert 0.019 < r["median"] < 0.035, r
    print("selfcheck ok")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "selfcheck": selfcheck()
    elif cmd == "env":
        os.makedirs(DATA, exist_ok=True)
        open(os.path.join(DATA, "env.md"), "w").write(env_report()); print(open(os.path.join(DATA, "env.md")).read())
    elif cmd == "offset":
        off, rtt = clock_offset(int(sys.argv[2]) if len(sys.argv) > 2 else 20)
        line = f"- clock offset board-PC {time.strftime('%F %T')}: {off:+.3f} s (best RTT {rtt:.3f} s, error <= {rtt/2:.3f} s)\n"
        os.makedirs(DATA, exist_ok=True); open(os.path.join(DATA, "env.md"), "a").write(line); print(line, end="")
    else: print(__doc__)
