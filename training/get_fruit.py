"""Build the fruit dataset in the student layout data/fruit/<label>/*.jpg (+ data/fruit/none/)
and a held-out test set ../demo-images/fruit/<label>_<nn>.jpg (incl. none_<nn>.jpg) that is
never trained on. Then: python prepare.py fruit.

Sources (download both first, see README):
- HF VinayHajare/Fruits-30 (Apache-2.0): real photos, 15 classes, used as they are. 2 per
  class are held out as demo images.
- Fruits-360 100x100 (CC BY-SA 4.0) in data/fruits-360: one fruit on white, many angles.
  Cut out and pasted 1-3 times onto a COCO scene (data/coco) at 30-90 % of the frame, so
  the model sees fruit in any venue. Varieties map to our labels by the first word of the
  folder name; every other variety becomes `none`, except LOOKALIKES (a mandarin would
  have to be called "none" while looking exactly like an orange).

  python get_fruit.py
"""
import random
import shutil
from pathlib import Path

import numpy as np
from huggingface_hub import snapshot_download
from PIL import Image, ImageFilter

from common import coco_images

HERE = Path(__file__).parent
CLASSES = {  # HF dir -> label (singular, lowercase: what categories.txt and filenames use)
    "apples": "apple", "bananas": "banana", "cherries": "cherry", "grapes": "grape",
    "kiwifruit": "kiwi", "lemons": "lemon", "limes": "lime", "mangos": "mango",
    "oranges": "orange", "peaches": "peach", "pineapples": "pineapple",
    "pomegranates": "pomegranate", "raspberries": "raspberry", "strawberries": "strawberry",
    "watermelons": "watermelon",
}
LOOKALIKES = ("Clementine", "Mandarine", "Tangelo", "Kumquats", "Grapefruit", "Pomelo", "Nectarine",
              "Apricot", "Tomato Cherry", "Blackberry", "BlackBerry", "Mulberry", "Plum", "Quince", "Kaki",
              "Physalis", "Papaya", "Tamarillo", "Guava", "Gooseberry", "Mangostan")
N_COMPOSITE, N_NONE, N_DEMO_NONE, SIZE = 300, 300, 10, 256
rng = random.Random(0)


def fruits360_label(variety: str) -> str | None:
    """'Apple Red 2' -> 'apple', 'Limes 1' -> 'lime', 'Pear 3' -> 'none', 'Plum 1' -> None (skip)."""
    if variety.startswith(LOOKALIKES):
        return None
    first = variety.split()[0].lower()
    first = {"limes": "lime"}.get(first, first)
    return first if first in CLASSES.values() else "none"


def cutout(path: Path) -> Image.Image:
    """Fruits-360 photo -> RGBA with the white background transparent (soft edge)."""
    rgb = Image.open(path).convert("RGB")
    mask = Image.fromarray(((np.asarray(rgb).min(-1) < 235) * 255).astype(np.uint8))
    rgb.putalpha(mask.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(1)))
    return rgb


def composite(frames: list[Path], bg: Path) -> Image.Image:
    """Paste 1-3 fruits (a bunch of cherries, a pile of lemons) onto a square COCO crop."""
    img = Image.open(bg).convert("RGB")
    s = min(img.size)
    img = img.crop(((img.width - s) // 2, (img.height - s) // 2, (img.width + s) // 2, (img.height + s) // 2))
    img = img.resize((SIZE, SIZE))
    n = rng.choice((1, 1, 1, 2, 3))
    for f in rng.sample(frames, min(n, len(frames))):
        side = int(SIZE * rng.uniform(0.3, 0.9) / n ** 0.5)
        fruit = cutout(f).resize((side, side), Image.BICUBIC)
        img.paste(fruit, (rng.randint(0, SIZE - side), rng.randint(0, SIZE - side)), fruit)
    return img


def frames_by_label(split: str) -> dict[str, list[Path]]:
    """Every 4th frame per variety (neighbours are near-identical frames of one rotating fruit)."""
    out: dict[str, list[Path]] = {}
    for d in sorted((HERE / "data" / "fruits-360" / split).iterdir()):
        label = fruits360_label(d.name)
        if label:
            out.setdefault(label, []).extend(sorted(d.glob("*.jpg"))[::4])
    return out


src = Path(snapshot_download("VinayHajare/Fruits-30", repo_type="dataset",
                             allow_patterns=[f"FruitImageDataset/{d}/*" for d in CLASSES]))
data, demo = HERE / "data" / "fruit", HERE.parent / "demo-images" / "fruit"
for d in (data, demo):
    shutil.rmtree(d, ignore_errors=True)
demo.mkdir(parents=True)
coco_train, coco_test = coco_images("train"), coco_images("test")
counts = {}
for hf_dir, label in CLASSES.items():  # real photos: 2 held out, the rest to train
    files = sorted((src / "FruitImageDataset" / hf_dir).glob("*.jpg"))
    rng.shuffle(files)
    (data / label).mkdir(parents=True)
    for f in files[2:]:
        shutil.copyfile(f, data / label / f"f30_{f.name}")
    for i, f in enumerate(files[:2]):  # the "224x224" dataset is really full-size photos
        img = Image.open(f).convert("RGB")
        img.thumbnail((800, 800))  # keep the repo small
        img.save(demo / f"{label}_{i:02d}.jpg", quality=90)
    counts[label] = len(files) - 2

train_frames, test_frames = frames_by_label("Training"), frames_by_label("Test")
missing = set(CLASSES.values()) - set(train_frames)
assert not missing, f"Fruits-360 has no folders for {missing}: redo the sparse checkout (README)"
(data / "none").mkdir()
for label, frames in sorted(train_frames.items()):  # composites (none = other produce)
    n = N_NONE if label == "none" else N_COMPOSITE
    for i in range(n):
        composite(frames, rng.choice(coco_train)).save(data / label / f"f360_{i:03d}.jpg", quality=90)
    counts[label] = counts.get(label, 0) + n
for i in range(N_DEMO_NONE):  # held-out negatives: unseen COCO scenes + unseen produce frames
    Image.open(coco_test[i * 7]).convert("RGB").save(demo / f"none_{i:02d}.jpg", quality=90)
    composite(test_frames["none"], coco_test[i * 7 + 3]).save(demo / f"none_{N_DEMO_NONE + i:02d}.jpg", quality=90)

for label, n in sorted(counts.items()):
    print(f"{label:12s} {n:4d}")
print(f"-> {data}  (+ {len(list(demo.glob('*.jpg')))} held-out demo images in {demo})")
