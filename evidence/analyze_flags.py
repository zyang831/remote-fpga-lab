"""D5: board vs CPU-reference flag classification (ticket 04).

Python: ~/build-openvino-dev/openvino_env/bin/python (has openvino 2024.6, cv2, PIL).

  analyze_flags.py cpu     [--resize pil|cv] [--set flag]   CPU run -> data/D5-flag/cpu_<resize>.csv
  analyze_flags.py board   [--set flag]                     BOARD ONLY (ssh): -> data/D5-flag/board.csv
  analyze_flags.py compare BOARD.csv CPU.csv [--tie 0.10]   -> data/D5-flag/per_image.csv + report
  analyze_flags.py selfcheck

Row format of board.csv / cpu.csv: filename,true,top1,top5   top5 = "label:prob|label:prob|..."
(prob is the softmax output baked into the graph; margin = top1 - top2 prob).
Ground truth = filename prefix before the last "_" (e.g. "united kingdom_01.jpg" -> "united kingdom").

Preprocessing (what dla-server fill_input does, ~/edge-ai-demo/dla-server/main.cpp:265):
centre square crop of the shorter side, RGB, cv::resize(W,H) with the DEFAULT interpolation
(INTER_LINEAR, no antialiasing), float32 0..255, NCHW; normalisation + softmax are inside the IR.
The shipped cpu_reference.json (training/export.py) instead used PIL BILINEAR, which antialiases
on downscale. So --resize cv reproduces the board's resize, --resize pil reproduces the old reference.
Decoding is identical on both sides: board_check/this script send PIL-decoded pixels as PNG
(the board OpenCV has no JPEG codec).
Precision: CPU reference is FP32; the FPGA part of the board graph runs FP16 (CoreDLA).
"""
import csv, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data", "D5-flag")
DEMO = os.path.expanduser("~/edge-ai-demo")
SPOOL = "/var/lib/dla/spool"


def truth(fname): return fname.rsplit("_", 1)[0]


def enc(top5): return "|".join(f"{l}:{p:.6g}" for l, p in top5)


def dec(s): return [(x.rsplit(":", 1)[0], float(x.rsplit(":", 1)[1])) for x in s.split("|")]


def load_deploy(path, resize):
    import numpy as np
    from PIL import Image
    img = Image.open(path).convert("RGB")
    s = min(img.size); l, t = (img.width - s) // 2, (img.height - s) // 2
    img = img.crop((l, t, l + s, t + s))
    if resize == "pil":
        a = np.asarray(img.resize((224, 224), Image.BILINEAR))
    else:
        import cv2
        a = cv2.resize(np.asarray(img), (224, 224))  # default INTER_LINEAR, as dla-server
    return a.astype(np.float32).transpose(2, 0, 1)[None]


def cmd_cpu(name, resize):
    import numpy as np, openvino as ov
    cls = open(f"{DEMO}/models/{name}/categories.txt").read().rstrip("\n").split("\n")
    m = ov.Core().compile_model(f"{DEMO}/models/{name}/model.xml", "CPU",
                                {"INFERENCE_NUM_THREADS": 2})  # PC: stay out of the timing cores' way
    os.makedirs(OUT, exist_ok=True)
    path = f"{OUT}/cpu_{resize}.csv"
    with open(path, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["filename", "true", "top1", "top5"])
        for fn in sorted(os.listdir(f"{DEMO}/demo-images/{name}")):
            if not fn.endswith(".jpg"): continue
            p = m(load_deploy(f"{DEMO}/demo-images/{name}/{fn}", resize))[0][0]
            top = np.argsort(-p)[:5]
            w.writerow([fn, truth(fn), cls[top[0]], enc([(cls[i], float(p[i])) for i in top])])
    print("wrote", path)


def cmd_board(name, board="terasic@coredla"):
    """BOARD ONLY. Same inbox protocol as ~/edge-ai-demo/training/board_check.py (untested here).
    Needs: model `name` live on the board (`ssh board head -1 /var/lib/dla/model/name`), nobody mid-session,
    and no timing experiment running (110 inferences + 110 ssh round trips)."""
    import io, json, subprocess
    from PIL import Image
    def ssh(script, stdin=b""):
        return subprocess.run(["ssh", "-o", "BatchMode=yes", board, script], input=stdin,
                              capture_output=True, check=True, timeout=60).stdout.decode()
    live = ssh(f"head -1 {SPOOL}/../model/name").strip()
    assert live == name, f"board runs {live!r}, not {name!r}"
    os.makedirs(OUT, exist_ok=True)
    path = f"{OUT}/board.csv"
    with open(path, "w", newline="") as f:
        w = csv.writer(f); w.writerow(["filename", "true", "top1", "top5"])
        for n, fn in enumerate(sorted(x for x in os.listdir(f"{DEMO}/demo-images/{name}") if x.endswith(".jpg"))):
            png = io.BytesIO(); Image.open(f"{DEMO}/demo-images/{name}/{fn}").convert("RGB").save(png, format="PNG")
            t = f"d5-{n}.png"
            res = json.loads(ssh(
                f"cat > {SPOOL}/inbox/.{t}; mv {SPOOL}/inbox/.{t} {SPOOL}/inbox/{t}; i=0; "
                f"while [ ! -f {SPOOL}/results/{t}.json ] && [ $i -lt 300 ]; do sleep 0.1; i=$((i+1)); done; "
                f"cat {SPOOL}/results/{t}.json; rm -f {SPOOL}/results/{t}.json {SPOOL}/done/{t}", png.getvalue()))
            top = [(x["label"].strip(), x["prob"]) for x in res["top5"]]
            w.writerow([fn, truth(fn), top[0][0], enc(top)])
    print("wrote", path)


def read(path):
    with open(path, newline="") as f: return {r["filename"]: r for r in csv.DictReader(f)}


def margin(top5): return top5[0][1] - top5[1][1]


def compare(board, cpu, tie, out=None):
    """board, cpu: {filename: row}. Returns (per-image rows, summary dict)."""
    rows = []
    for fn in sorted(set(board) & set(cpu)):
        b, c = dec(board[fn]["top5"]), dec(cpu[fn]["top5"])
        t = board[fn]["true"]
        mb, mc = margin(b), margin(c)
        mis = b[0][0] != c[0][0]
        rows.append(dict(filename=fn, true=t, board_top1=b[0][0], cpu_top1=c[0][0],
                         board_margin=f"{mb:.4f}", cpu_margin=f"{mc:.4f}",
                         mismatch=int(mis), near_tie=int(min(mb, mc) < tie),
                         board_correct=int(b[0][0] == t), cpu_correct=int(c[0][0] == t),
                         board_top5=board[fn]["top5"], cpu_top5=cpu[fn]["top5"]))
    n = len(rows); mm = [r for r in rows if r["mismatch"]]
    s = dict(n=n, only_board=len(set(board) - set(cpu)), only_cpu=len(set(cpu) - set(board)),
             mismatches=len(mm), mismatch_near_tie=sum(r["near_tie"] for r in mm),
             mismatch_real=sum(not r["near_tie"] for r in mm),
             board_acc=sum(r["board_correct"] for r in rows) / n, cpu_acc=sum(r["cpu_correct"] for r in rows) / n)
    if out:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    return rows, s


def report(rows, s, tie):
    print(f"images {s['n']} (board-only {s['only_board']}, cpu-only {s['only_cpu']}); near-tie = min(margin) < {tie}")
    print(f"mismatches {s['mismatches']}: near-tie {s['mismatch_near_tie']}, real (both confident) {s['mismatch_real']}")
    print(f"top-1 vs ground truth: board {s['board_acc']:.3f}  cpu {s['cpu_acc']:.3f}")
    for r in rows:
        if r["mismatch"]:
            print(f"  {r['filename']:26s} true {r['true']:12s} board {r['board_top1']:12s} m={r['board_margin']}"
                  f"  cpu {r['cpu_top1']:12s} m={r['cpu_margin']}  {'near-tie' if r['near_tie'] else 'REAL'}")


def selfcheck():
    import tempfile
    mk = lambda t5: {"top5": enc(t5)}
    cpu = {"a_0.jpg": {"true": "a", **mk([("a", .9), ("b", .05)])},
           "b_0.jpg": {"true": "b", **mk([("b", .50), ("c", .45)])},   # near-tie, board flips
           "c_0.jpg": {"true": "c", **mk([("a", .80), ("c", .10)])}}   # cpu wrong, board differs confidently
    board = {"a_0.jpg": {"true": "a", **mk([("a", .88), ("b", .06)])},
             "b_0.jpg": {"true": "b", **mk([("c", .48), ("b", .47)])},
             "c_0.jpg": {"true": "c", **mk([("c", .70), ("a", .20)])}}
    with tempfile.TemporaryDirectory() as d:
        rows, s = compare(board, cpu, 0.10, os.path.join(d, "p.csv"))
        assert len(read(os.path.join(d, "p.csv"))) == 3
    assert (s["n"], s["mismatches"], s["mismatch_near_tie"], s["mismatch_real"]) == (3, 2, 1, 1), s
    assert abs(s["board_acc"] - 2 / 3) < 1e-9 and abs(s["cpu_acc"] - 2 / 3) < 1e-9, s
    assert rows[1]["near_tie"] == 1 and rows[2]["near_tie"] == 0
    print("selfcheck ok")


if __name__ == "__main__":
    a = sys.argv[1:]
    opt = lambda k, d: a[a.index(k) + 1] if k in a else d
    c = a[0] if a else ""
    if c == "selfcheck": selfcheck()
    elif c == "cpu": cmd_cpu(opt("--set", "flag"), opt("--resize", "cv"))
    elif c == "board": cmd_board(opt("--set", "flag"))
    elif c == "compare":
        tie = float(opt("--tie", 0.10))
        rows, s = compare(read(a[1]), read(a[2]), tie, f"{OUT}/per_image.csv")
        report(rows, s, tie)
    else: sys.exit(__doc__)
