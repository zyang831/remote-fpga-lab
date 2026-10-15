"""Run demo-images/<name>/ through the board's dla-server file inbox over ssh and
compare board top-1 with models/<name>/cpu_reference.json and with the filename
ground truth. Bypasses the lab backend (no session), so check nobody is mid-demo.

  python board_check.py fruit [terasic@coredla]
"""
import io
import json
import subprocess
import sys

from PIL import Image

from common import ROOT

name = sys.argv[1]
board = sys.argv[2] if len(sys.argv) > 2 else "terasic@coredla"
ref = json.loads((ROOT / "models" / name / "cpu_reference.json").read_text())
S = "/var/lib/dla/spool"


def ssh(script, stdin=b""):
    return subprocess.run(["ssh", "-o", "BatchMode=yes", board, script], input=stdin,
                          capture_output=True, check=True, timeout=60).stdout.decode()


live = ssh("head -1 /var/lib/dla/model/name").strip()
assert live == name, f"board is running {live!r}, not {name!r}"

agree = hit = n = 0
lat = []
for fname, cpu in sorted(ref.items()):
    png = io.BytesIO()  # the board's OpenCV has no JPEG codec
    Image.open(ROOT / "demo-images" / name / fname).convert("RGB").save(png, format="PNG")
    f = f"check-{n}.png"
    res = json.loads(ssh(
        f"cat > {S}/inbox/.{f}; mv {S}/inbox/.{f} {S}/inbox/{f}; i=0; "
        f"while [ ! -f {S}/results/{f}.json ] && [ $i -lt 300 ]; do sleep 0.1; i=$((i+1)); done; "
        f"cat {S}/results/{f}.json; rm -f {S}/results/{f}.json {S}/done/{f}", png.getvalue()))
    board_top = res["top5"][0]["label"].strip()
    truth = fname.rsplit("_", 1)[0]
    agree += board_top == cpu[0]["label"]
    hit += board_top == truth
    n += 1
    lat.append(res["latency_ms"])
    flag = "" if board_top == cpu[0]["label"] else f"   <- cpu {cpu[0]['label']} {cpu[0]['prob']}"
    print(f"{fname:24s} board {board_top:12s} {res['top5'][0]['prob']:.3f}  {res['latency_ms']:.0f} ms{flag}")
print(f"board == cpu top-1: {agree}/{n}   board == filename truth: {hit}/{n}   "
      f"latency mean {sum(lat) / n:.0f} ms max {max(lat):.0f} ms")
