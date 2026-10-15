"""Shared bits: class list from models/<name>/categories.txt, the deploy-time
preprocessing (centre square crop, 224x224 resize, RGB, 0-255 float) and the export wrapper
that bakes ImageNet normalisation + softmax into the graph so dla-server can
stay a dumb resize+RGB feeder."""
import json
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torchvision
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
MEAN = torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1)
STD = torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1)


def categories(name: str) -> list[str]:
    return (ROOT / "models" / name / "categories.txt").read_text().rstrip("\n").split("\n")


ARCHS = ("resnet18", "resnet50", "mobilenet_v2")  # on the board: ~9, ~4, ~17 Hz live; first = default


def backbone(arch: str, n_classes: int) -> nn.Module:
    """ImageNet-pretrained `arch` with a new n_classes head (see ARCHS)."""
    m = getattr(torchvision.models, arch)(weights="IMAGENET1K_V1")
    if arch == "mobilenet_v2":  # its pooling is functional; dlac maps it to the FPGA as is
        m.classifier[-1] = nn.Linear(m.last_channel, n_classes)
        return m
    # AdaptiveAvgPool2d exports as ReduceMean, which dlac would push to the CPU;
    # a fixed 7x7 AvgPool is the FPGA primitive and identical at 224x224. Stride
    # must be 1: the arch caps pool strides at 4 (dlac: "exceeds maximum strides").
    m.avgpool = nn.AvgPool2d(7, stride=1)
    m.fc = nn.Linear(m.fc.in_features, n_classes)
    return m


def run_name(name: str, arch: str) -> str:
    """runs/ and models/ directory: <name> for the default ResNet-18, else <name>-<arch>."""
    return name if arch == ARCHS[0] else f"{name}-{arch}"


def center_square(img: Image.Image) -> Image.Image:
    """Centre square of the shorter side, as dla-server fill_input() crops."""
    s = min(img.size)
    l, t = (img.width - s) // 2, (img.height - s) // 2
    return img.crop((l, t, l + s, t + s))


def coco_images(split: str) -> list[Path]:
    """COCO val2017 scenes (data/coco) with no banana/apple/orange in them: image id % 10 == 0
    is 'test' (held-out none_* demo images), the rest 'train' (backgrounds + the none class).
    ponytail: a few COCO scenes show a national flag; they stay in none as label noise."""
    root = ROOT / "training" / "data" / "coco"
    ann = json.loads((root / "annotations" / "instances_val2017.json").read_text())
    fruit = {c["id"] for c in ann["categories"] if c["name"] in ("banana", "apple", "orange")}
    bad = {a["image_id"] for a in ann["annotations"] if a["category_id"] in fruit}
    return sorted(root / "val2017" / i["file_name"] for i in ann["images"]
                  if i["id"] not in bad and (i["id"] % 10 == 0) == (split == "test"))


def load_deploy_image(path) -> np.ndarray:
    """Exactly what dla-server feeds the graph: RGB, centre square, resize, f32 0..255, NCHW."""
    img = center_square(Image.open(path).convert("RGB")).resize((224, 224), Image.BILINEAR)
    return np.asarray(img, dtype=np.float32).transpose(2, 0, 1)[None]


class Deploy(nn.Module):
    """Graph as exported: raw 0..255 RGB in, class probabilities out."""

    def __init__(self, net: nn.Module):
        super().__init__()
        self.net = net
        self.register_buffer("mean", MEAN * 255.0)
        self.register_buffer("std", STD * 255.0)

    def forward(self, x):
        return torch.softmax(self.net((x - self.mean) / self.std), dim=1)
