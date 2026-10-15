"""D4 upload rejection matrix: python3 run_D4.py [bit|model|all] [reps]. One row per attempt -> data/D4-matrix/matrix.csv.
Records HTTP status, message, whether a Mender deployment was created (total count before/after), seconds to answer, board state afterwards."""
import sys, os, re, time, csv, json, random, asyncio, subprocess, requests, tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import harness as h
for l in open(os.path.expanduser("~/mender/lab-backend/lab-backend.env")):
    if "=" in l and not l.startswith("#"): k, v = l.strip().split("=", 1); os.environ.setdefault(k, v)
sys.path.insert(0, os.path.expanduser("~/mender/lab-backend")); import mender_client as mc
R = os.path.expanduser("~/edge-ai-demo"); FV = f"{R}/models/fruit-v1"; MF = f"{R}/models/my-flags"
which = sys.argv[1] if len(sys.argv) > 1 else "all"; reps = int(sys.argv[2]) if len(sys.argv) > 2 else 3
def dep_total():
    async def f(): return int((await mc._request("GET", "/api/management/v1/deployments/deployments", params={"per_page": 1})).headers["X-Total-Count"])
    return asyncio.run(f())
def board():
    try: nm = requests.get(f"{h.BACKEND}/session/model", timeout=5).json().get("name")
    except Exception as e: nm = f"err:{type(e).__name__}"
    r = subprocess.run(["ssh", "-o", "ConnectTimeout=8", h.BOARD, "echo $(systemctl is-active dla-server) $(cat /sys/class/fpga_manager/fpga0/state)"], capture_output=True, text=True, timeout=30)
    return f"{nm}|{r.stdout.strip() or 'ssh-fail'}"
def healthy(limit=240):
    t = time.time()
    while time.time() - t < limit:
        b = board()
        if b.endswith("active operating") and not b.startswith("err"): return True, b
        time.sleep(5)
    return False, board()
def restore():  # last resort: re-apply the idle design on the board (needs BOARD_SUDO in the environment)
    import shlex
    cmd = f"echo {shlex.quote(os.environ['BOARD_SUDO'])} | sudo -S -p '' sh -c 'cp /var/lib/dla/idle/* /lib/firmware/ && /usr/local/sbin/coredla-fpga-up.sh && systemctl start dla-server'"
    subprocess.run(["ssh", h.BOARD, cmd], capture_output=True, timeout=300)
d = tempfile.mkdtemp(); valid = open(f"{R}/demo/webui/1-bitstream/led-bouncing.core.rbf", "rb").read()
BIT = {  # case -> (filename, bytes)
 "empty file": ("a.core.rbf", b""), "random bytes 2 MiB": ("a.core.rbf", os.urandom(2 << 20)),
 "valid header, 64 KiB cut": ("a.core.rbf", valid[:65536]), "valid file cut to 75%": ("a.core.rbf", valid[: int(len(valid) * .75)]),
 "wrong header, right size": ("a.core.rbf", b"\0" * 8 + valid[8:]), "valid header + 9 MiB": ("a.core.rbf", valid[:8] + os.urandom(9 << 20)),
 "wrong extension": ("a.bin", valid)}
xml = open(f"{FV}/model.xml", "rb").read(); binw = open(f"{FV}/model.bin", "rb").read(); cats = open(f"{FV}/categories.txt", "rb").read()
def drop_layer(x, typ): return re.sub(rb'\s*<layer [^>]*type="%s".*?</layer>' % typ, b"", x, count=1, flags=re.S)
layers_end = xml.rindex(b"</layers>")
MOD = {  # case -> (name, xml, bin, cats)
 "ResNet-50 (wrong topology)": ("rej", open(f"{MF}/model.xml", "rb").read(), open(f"{MF}/model.bin", "rb").read(), open(f"{MF}/categories.txt", "rb").read()),
 "extra layer": ("rej", xml.replace(b"</layers>", b'<layer id="999" type="ReLU" version="opset1"/></layers>', 1), binw, cats),
 "final layer (SoftMax) missing": ("rej", drop_layer(xml, b"SoftMax"), binw, cats),
 "SoftMax replaced by Sigmoid": ("rej", xml.replace(b'type="SoftMax"', b'type="Sigmoid"', 1), binw, cats),
 "preprocessing (Divide) missing": ("rej", drop_layer(xml, b"Divide"), binw, cats),
 "categories: one extra line": ("rej", xml, binw, cats + b"extra\n"),
 "categories: empty": ("rej", xml, binw, b""), "categories: one line": ("rej", xml, binw, b"only\n"),
 "categories: blank line inside": ("rej", xml, binw, cats.replace(b"banana\n", b"\n", 1)),
 "name: uppercase/space": ("My Model", xml, binw, cats), "name: starts with dash": ("-x", xml, binw, cats),
 "name: 33 chars": ("a" * 33, xml, binw, cats), "name: built-in 'fruit'": ("fruit", xml, binw, cats),
 "model.xml truncated (half)": ("rej", xml[: len(xml) // 2], binw, cats), "model.bin truncated (half)": ("rej", xml, binw[: len(binw) // 2], cats),
 "model.xml not OpenVINO (random bytes)": ("rej", os.urandom(4096), binw, cats), "model.bin not weights (random, right size)": ("rej", xml, os.urandom(len(binw)), cats),
 "ACCEPT? duplicate categories": ("rej", xml, binw, b"apple\n" * 15),
 "ACCEPT: valid, random weights": None}
import array
_a = array.array('f', (random.Random(1).gauss(0, .01) for _ in range(len(binw) // 4)))
MOD["ACCEPT: valid, random weights"] = ("rej", xml, _a.tobytes(), cats)  # little-endian host; overwrites int64 shape constants too, so it fails at the build-time load check
MOD["ACCEPT: valid weights, labels reversed (wrong answers)"] = ("rej", xml, binw, b"".join(reversed(cats.splitlines(True))))
def session():
    j = h.join(); return j
def run_case(w, kind, case, rep):
    j = session(); before = dep_total(); t = time.monotonic(); accepted = False
    try:
        if kind == "bit":
            fn, data = BIT[case]
            r = requests.post(f"{h.BACKEND}/session/program", params={"job_id": j}, files={"bitstream": (fn, data)})
        else:
            nm, x, b, c = MOD[case]; nm = nm if nm != "rej" else f"rej-{int(time.time())%100000}-{rep}"
            r = requests.post(f"{h.BACKEND}/session/model/upload", params={"job_id": j}, data={"name": nm}, files={"model_xml": ("model.xml", x), "model_bin": ("model.bin", b), "categories": ("categories.txt", c)})
        dt = time.monotonic() - t; msg = ""
        try: msg = json.dumps(r.json().get("detail", r.json()))[:160]
        except Exception: msg = r.text[:160]
        final = ""
        if r.ok:
            accepted = True; key = "program_state" if kind == "bit" else "upload_state"
            final = h.wait(j, key, limit=400)
            if kind == "model" and final == "ok": final = "build:" + h.wait(j, "model_state", limit=400)
        time.sleep(4); after = dep_total()
        if accepted and kind == "model":
            requests.delete(f"{h.BACKEND}/session/model", params={"job_id": j, "name": nm})
    finally:
        h.finish(j); time.sleep(3)
    ok, b = healthy(240 if accepted else 60)
    if not ok: restore(); ok, b = healthy(240)
    w.writerow([kind, case, rep, r.status_code, msg, int(after > before), f"{dt:.2f}", final, b + ("" if ok else " UNHEALTHY")]); print(kind, case, rep, r.status_code, msg[:70], after > before, f"{dt:.1f}s", final, b, flush=True)
    return ok
os.makedirs(f"{h.DATA}/D4-matrix", exist_ok=True); path = f"{h.DATA}/D4-matrix/matrix.csv"; new = not os.path.exists(path)
with open(path, "a", newline="") as f:
    w = csv.writer(f)
    if new: w.writerow(["kind", "case", "rep", "http", "message", "deployment_created", "seconds_to_answer", "final_state", "board_after(model|dla-server fpga)"])
    for kind, cases in (("bit", BIT), ("model", MOD)):
        if which not in (kind, "all"): continue
        for case in cases:
            if len(sys.argv) > 3 and sys.argv[3] not in case: continue
            for rep in range(reps):
                if not run_case(w, kind, case, rep): print("UNHEALTHY board, stopping"); sys.exit(1)
                f.flush()
