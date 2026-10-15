"""Score data/flag-real/<label>/*.jpg with models/flag/model.xml on the CPU plugin
(synthetic-trained model vs real photos) and write a contact sheet per country
with the prediction drawn on each tile, for eyeballing which photos are usable.

  python score_real.py            # -> data/flag-real/_sheets/<label>.jpg, summary on stdout
"""
from pathlib import Path

import numpy as np
import openvino as ov
from PIL import Image, ImageDraw

from common import ROOT, categories, load_deploy_image

HERE = Path(__file__).parent
real = HERE / "data" / "flag-real"
classes = categories("flag")
cm = ov.Core().compile_model(str(ROOT / "models" / "flag" / "model.xml"), "CPU")
sheets = real / "_sheets"
sheets.mkdir(exist_ok=True)
tot_hit = tot = 0
for d in sorted(p for p in real.iterdir() if p.is_dir() and not p.name.startswith("_")):
    files = sorted(d.glob("*.jpg"))
    if not files:
        continue
    tiles, hit = [], 0
    for f in files:
        p = cm(load_deploy_image(f))[0][0]
        i = int(p.argmax())
        hit += classes[i] == d.name
        t = Image.open(f).convert("RGB").resize((224, 224))
        ImageDraw.Draw(t).rectangle([0, 0, 224, 18], fill=(0, 128, 0) if classes[i] == d.name else (160, 0, 0))
        ImageDraw.Draw(t).text((3, 3), f"{f.name} {classes[i]} {p[i]:.2f}", fill=(255, 255, 255))
        tiles.append(t)
    sheet = Image.new("RGB", (224 * len(tiles), 224))
    for k, t in enumerate(tiles):
        sheet.paste(t, (224 * k, 0))
    sheet.save(sheets / f"{d.name}.jpg", quality=85)
    print(f"{d.name:16s} {hit}/{len(files)}")
    tot_hit += hit
    tot += len(files)
print(f"real-photo top-1: {tot_hit}/{tot} = {tot_hit / max(tot, 1):.2f}")
