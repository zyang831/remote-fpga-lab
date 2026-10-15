"""D6: CPU-plugin latency/throughput of ResNet-18 and ResNet-50 IRs (ticket 05).

  bench_cpu.py THREADS [--runs 100] [--warmup 10] [--device CPU] [--env ID] [--models r18=PATH r50=PATH]

Per-run times -> data/D6-cpu-t<THREADS>/runs.csv (harness.Series; warm-ups flagged), plus
summary rows printed and appended to data/D6-cpu-t<THREADS>/summary_stats.csv.
Method: synchronous single-image infer() on a fixed random 0..255 [1,3,224,224] tensor (latency does
not depend on pixel values), INFERENCE_NUM_THREADS=THREADS, model compiled once, timed with
time.monotonic around infer only. throughput = 1 / mean latency (batch 1, one request).
Needs python `openvino` (PC: ~/build-openvino-dev/openvino_env/bin/python). The board has NO python
openvino (aarch64); there use the C++ route in the ticket notes (dla_benchmark -d CPU or benchmark_app).
Pin cores outside this script: `taskset -c 2,3 ...` (A76 = cpu2-3 on the board).
"""
import argparse, csv, os, sys, statistics as st
import numpy as np, openvino as ov
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from harness import Series, DATA, sha

M = os.path.expanduser("~/edge-ai-demo/models")
DEFAULT = {"resnet18": f"{M}/fruit-v1/model.xml", "resnet50": f"{M}/my-flags/model.xml"}  # my-flags = ResNet-50 (53 convs)


def pct(xs, q):
    xs = sorted(xs); k = (len(xs) - 1) * q
    return xs[int(k)] + (xs[min(int(k) + 1, len(xs) - 1)] - xs[int(k)]) * (k - int(k))


def stats(ms):
    return dict(n=len(ms), median_ms=st.median(ms), p95_ms=pct(ms, .95), mean_ms=st.mean(ms),
                min_ms=min(ms), max_ms=max(ms), throughput_fps=1000 / st.mean(ms))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("threads", type=int)
    ap.add_argument("--runs", type=int, default=100)
    ap.add_argument("--warmup", type=int, default=10)
    ap.add_argument("--device", default="CPU")
    ap.add_argument("--env", default="")
    ap.add_argument("--models", nargs="*", default=[f"{k}={v}" for k, v in DEFAULT.items()])
    a = ap.parse_args()
    x = np.random.default_rng(0).uniform(0, 255, (1, 3, 224, 224)).astype(np.float32)
    item = f"D6-cpu-t{a.threads}"
    out = []
    with Series(item, a.env, root=DATA) as s:
        for spec in a.models:
            name, path = spec.split("=", 1)
            cm = ov.Core().compile_model(path, a.device, {"INFERENCE_NUM_THREADS": a.threads,
                                                          "PERFORMANCE_HINT": "LATENCY"})
            req = cm.create_infer_request()
            req.set_input_tensor(ov.Tensor(x))
            f = lambda: (req.infer(), "ok")[1]
            h = sha(path.replace(".xml", ".bin"))
            for _ in range(a.warmup): s.timed(f"{name}-t{a.threads}", f, h, warmup=True)
            for _ in range(a.runs): s.timed(f"{name}-t{a.threads}", f, h)
            ms = [float(r["seconds"]) * 1000 for r in s.rows() if r["input"] == f"{name}-t{a.threads}"
                  and r["warmup"] != "1" and r["result"] == "ok"][-a.runs:]
            out.append(dict(model=name, device=a.device, threads=a.threads, **stats(ms)))
            print(out[-1])
    p = os.path.join(s.dir, "summary_stats.csv")
    new = not os.path.exists(p)
    with open(p, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out[0]))
        if new: w.writeheader()
        w.writerows(out)
