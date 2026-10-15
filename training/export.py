"""runs/<name>/model.pt -> models/<name>/model.{xml,bin} (OpenVINO 2024.6 IR, FP32)
+ models/<name>/cpu_reference.json (top-5 per demo image on the CPU plugin).

  python export.py fruit [--arch resnet50|mobilenet_v2]

--arch: export runs/<name>-<arch>/ (train.py --arch) to models/<name>-<arch>/, which
also gets categories.txt and name so compile.sh / build-model.sh take it as is.

The IR takes raw 0..255 RGB [1,3,224,224] (normalisation + softmax are inside,
see common.Deploy) so it matches what dla-server feeds. Checks: CPU-plugin top-1
== PyTorch top-1 on every val image, output dim == len(categories.txt).
"""
import argparse
import json
from pathlib import Path

import numpy as np
import openvino as ov
import torch

from common import ARCHS, ROOT, Deploy, backbone, categories, load_deploy_image, run_name

ap = argparse.ArgumentParser()
ap.add_argument("name")
ap.add_argument("--arch", choices=ARCHS, default=ARCHS[0])
args = ap.parse_args()
name, run = args.name, run_name(args.name, args.arch)
HERE = Path(__file__).parent
classes = categories(name)
ckpt = torch.load(HERE / "runs" / run / "model.pt", map_location="cpu", weights_only=True)
assert ckpt["classes"] == classes, "checkpoint classes != categories.txt"
assert ckpt.get("arch", "resnet50") == args.arch, f"runs/{run} was trained as {ckpt.get('arch', 'resnet50')}"
net = backbone(args.arch, len(classes))
net.load_state_dict(ckpt["state_dict"])
deploy = Deploy(net).eval()

out_dir = ROOT / "models" / run
if run != name:
    out_dir.mkdir(exist_ok=True)
    (out_dir / "categories.txt").write_text((ROOT / "models" / name / "categories.txt").read_text())
    (out_dir / "name").write_text(run + "\n")
m = ov.convert_model(deploy, example_input=torch.zeros(1, 3, 224, 224), input=[1, 3, 224, 224])
m.inputs[0].get_tensor().set_names({"image"})
m.outputs[0].get_tensor().set_names({"prob"})
ov.save_model(m, out_dir / "model.xml", compress_to_fp16=False)
assert list(m.outputs[0].get_shape()) == [1, len(classes)], m.outputs[0].get_shape()

# CPU plugin vs PyTorch on the val split, deploy preprocessing on both sides.
cm = ov.Core().compile_model(str(out_dir / "model.xml"), "CPU")
val = sorted((HERE / "data" / f"{name}-split" / "val").rglob("*.jpg"))
agree = 0
with torch.no_grad():
    for f in val:
        x = load_deploy_image(f)
        p_ov = cm(x)[0][0]
        p_pt = deploy(torch.from_numpy(x))[0].numpy()
        agree += int(p_ov.argmax() == p_pt.argmax())
        assert np.abs(p_ov - p_pt).max() < 1e-3, (f, np.abs(p_ov - p_pt).max())
print(f"CPU plugin vs PyTorch top-1 agreement on val: {agree}/{len(val)}")
assert agree == len(val)

ref = {}
for f in sorted((ROOT / "demo-images" / name).glob("*.jpg")):
    p = cm(load_deploy_image(f))[0][0]
    top = np.argsort(-p)[:5]
    ref[f.name] = [{"index": int(i), "label": classes[i], "prob": round(float(p[i]), 4)} for i in top]
(out_dir / "cpu_reference.json").write_text(json.dumps(ref, indent=1))
hits = sum(r[0]["label"] == n.rsplit("_", 1)[0] for n, r in ref.items())
print(f"demo-images/{name}: CPU top-1 {hits}/{len(ref)} -> {out_dir / 'cpu_reference.json'}")
print("IR:", out_dir / "model.xml", f"{(out_dir / 'model.bin').stat().st_size / 1e6:.1f} MB")
