"""torchvision ImageNet ResNet-18 (no training) -> models/imagenet/: model.{xml,bin},
categories.txt (the 1000 torchvision labels, no background), name, and a sanity check.

  python export_imagenet.py

Same graph contract as export.py (raw 0..255 RGB [1,3,224,224] in, softmax out, via
common.Deploy), so dla-server and compile.sh take it like fruit/flag. The fixed 7x7
AvgPool keeps the pooling on the FPGA (see common.backbone). Check: CPU plugin == PyTorch
on the fruit demo images, and how many of them land on an ImageNet fruit class.
"""
import numpy as np
import openvino as ov
import torch
import torch.nn as nn
import torchvision

from common import ROOT, Deploy, load_deploy_image

weights = torchvision.models.ResNet18_Weights.IMAGENET1K_V1
net = torchvision.models.resnet18(weights=weights)
net.avgpool = nn.AvgPool2d(7, stride=1)
deploy = Deploy(net).eval()
labels = weights.meta["categories"]

out_dir = ROOT / "models" / "imagenet"
out_dir.mkdir(exist_ok=True)
m = ov.convert_model(deploy, example_input=torch.zeros(1, 3, 224, 224), input=[1, 3, 224, 224])
m.inputs[0].get_tensor().set_names({"image"})
m.outputs[0].get_tensor().set_names({"prob"})
ov.save_model(m, out_dir / "model.xml", compress_to_fp16=False)
(out_dir / "categories.txt").write_text("\n".join(labels) + "\n")
(out_dir / "name").write_text("imagenet\n")
assert list(m.outputs[0].get_shape()) == [1, len(labels)] == [1, 1000]

cm = ov.Core().compile_model(str(out_dir / "model.xml"), "CPU")
fruit = {"banana", "orange", "lemon", "pineapple", "strawberry", "pomegranate", "fig", "Granny Smith", "custard apple", "jackfruit"}
n = hit = 0
with torch.no_grad():
    for f in sorted((ROOT / "demo-images" / "fruit").glob("*.jpg")):
        x = load_deploy_image(f)
        p_ov, p_pt = cm(x)[0][0], deploy(torch.from_numpy(x))[0].numpy()
        assert p_ov.argmax() == p_pt.argmax() and np.abs(p_ov - p_pt).max() < 1e-3, f
        n += 1
        hit += labels[p_ov.argmax()] in fruit
print(f"CPU == PyTorch on {n} fruit demo images; {hit} predicted as an ImageNet fruit class")
print("IR:", out_dir / "model.xml")
