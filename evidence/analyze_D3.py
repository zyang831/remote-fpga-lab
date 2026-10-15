"""python3 analyze_D3.py model|bit -> median/mean/min/max per stage from data/D3-<kind>/stages.csv (warm-up excluded), writes summary_stages.md"""
import sys, csv, statistics as st, harness as h
kind = sys.argv[1]; d = f"{h.DATA}/D3-{kind}"
rows = [r for r in csv.DictReader(open(f"{d}/stages.csv")) if r["warmup"] != "1" and r["result"] == "ok"]
order = ["t_request", "t_created", "pickup", "install_start", "overlay_removed", "fabric_write", "drivers_loaded", "srv_started", "srv_ready", "finished", "t_ok"]
stages = {}
for r in rows:
    pts = [(k, float(r[k])) for k in order if r.get(k)]
    for (a, ta), (b, tb) in zip(pts, pts[1:]): stages.setdefault(f"{a} -> {b}", []).append(tb - ta)
out = [f"# D3 {kind} stage medians (n={len(rows)} ok runs, warm-up excluded; generated)", "", "| stage | n | median s | mean | min | max |", "|---|---|---|---|---|---|"]
for k, v in stages.items(): out.append(f"| {k} | {len(v)} | {st.median(v):.2f} | {st.mean(v):.2f} | {min(v):.2f} | {max(v):.2f} |")
tot = [float(r["t_ok"]) - float(r["t_request"]) for r in rows if r["t_ok"]]
out.append(f"\nTotal request->ok: median {st.median(tot):.2f}, mean {st.mean(tot):.2f}, min {min(tot):.2f}, max {max(tot):.2f}")
out += ["", "Cumulative seconds since request (median [min-max]); markers can swap order (drivers_loaded vs srv_started: dla-server unit starts while drivers load), so read this table, not the consecutive diffs, for those two:", "", "| marker | n | median | min | max |", "|---|---|---|---|---|"]
for k in order[1:]:
    v = [float(r[k]) - float(r["t_request"]) for r in rows if r[k]]
    if v: out.append(f"| {k} | {len(v)} | {st.median(v):.1f} | {min(v):.1f} | {max(v):.1f} |")
open(f"{d}/summary_stages.md", "w").write("\n".join(out) + "\n"); print("\n".join(out))
