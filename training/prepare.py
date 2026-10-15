"""Step 2 of the guide: data/<name>/<label>/*.jpg -> data/<name>-split/{train,val}/<label>/
(symlinks, 15 % val per class, fixed seed) plus ../models/<name>/categories.txt.

Adds the `none` class ("nothing I know"): whatever is in data/<name>/none/ (optional,
e.g. other flags for the flag model), topped up with COCO scenes (data/coco) to twice
the average class size. Without it the model names one of its classes for every frame,
including an empty room.

  python prepare.py fruit
"""
import argparse
import random
import shutil
from pathlib import Path

from common import ROOT, coco_images

ap = argparse.ArgumentParser()
ap.add_argument("name")
args = ap.parse_args()

HERE = Path(__file__).parent
src, out = HERE / "data" / args.name, HERE / "data" / f"{args.name}-split"
IMAGES = {".jpg", ".jpeg", ".png"}
labels = sorted(d.name for d in src.iterdir() if d.is_dir() and d.name != "none")
assert labels, f"no class folders in {src}: expected {src}/<label>/*.jpg"
files = {label: sorted(f for f in (src / label).iterdir() if f.suffix.lower() in IMAGES) for label in labels}
own_none = sorted(f for f in (src / "none").glob("*") if f.suffix.lower() in IMAGES)
target = 2 * sum(map(len, files.values())) // len(labels)
rng = random.Random(0)
coco = coco_images("train")
rng.shuffle(coco)
files["none"] = own_none + coco[:max(0, target - len(own_none))]

shutil.rmtree(out, ignore_errors=True)
for label, fs in sorted(files.items()):
    if len(fs) < 30:
        print(f"warning: {label!r} has only {len(fs)} images; 30+ per class recommended")
    rng.shuffle(fs)
    n_val = max(1, len(fs) * 15 // 100)
    for split, part in (("val", fs[:n_val]), ("train", fs[n_val:])):
        d = out / split / label
        d.mkdir(parents=True)
        for f in part:
            (d / f.name).symlink_to(f.resolve())
    print(f"{label:16s} train {len(fs) - n_val:4d}  val {n_val:3d}")

# Class order = sorted folder names: what ImageFolder in train.py uses, so line i of
# categories.txt is output i of the model (dla-server labels its results with it).
model_dir = ROOT / "models" / args.name
model_dir.mkdir(parents=True, exist_ok=True)
(model_dir / "categories.txt").write_text("".join(f"{c}\n" for c in sorted(files)))
if not (model_dir / "name").exists():
    (model_dir / "name").write_text(f"{args.name}\n")
print(f"{len(files)} classes (incl. none) -> {out}, {model_dir / 'categories.txt'}")
