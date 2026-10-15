"""Synthesise the flag training set from flag-icons SVGs (MIT).

  python make_flags.py     # -> data/flag/<label>/*.jpg + data/flag/none/, demo-images/flag/none_*.jpg
  python split_flag_real.py  # then: python prepare.py flag

Per class: rasterise the 4x3 SVG once, then N_TRAIN variants as a printed or
on-screen flag would look: optional white paper margin, slight paper curl,
perspective, 30-100 % of the frame, on a COCO scene (data/coco), a flat/noisy
colour or sky, brightness/contrast/blur/JPEG jitter. No rotation here: train.py
rotates everything by up to 45 degrees. Every other flag-icons flag (EU, UN,
regions, ~240 countries) goes to data/flag/none/, except ones that render almost
identically to one of ours (Monaco = Indonesia, territories that fly the French
flag, ...): those would teach "none" and "indonesia" for the same picture.
"""
import io
import math
import random
import shutil
from pathlib import Path

import cairosvg
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter

HERE = Path(__file__).parent
ICONS = HERE / "data" / "flag-icons" / "flags" / "4x3"
BACKGROUNDS: list[Path] = []  # COCO scenes, filled in __main__ (other scripts import COUNTRIES)
COUNTRIES = {  # ISO code -> label (what categories.txt and filenames use)
    "au": "australia", "br": "brazil", "ca": "canada", "cn": "china", "de": "germany",
    "fr": "france", "gb": "united kingdom", "id": "indonesia", "in": "india", "it": "italy",
    "jp": "japan", "kr": "south korea", "my": "malaysia", "mx": "mexico", "nz": "new zealand",
    "ph": "philippines", "sg": "singapore", "th": "thailand", "tr": "turkey", "us": "united states",
    "vn": "vietnam", "za": "south africa", "ar": "argentina", "es": "spain", "sa": "saudi arabia",
    "ru": "russia", "se": "sweden", "ch": "switzerland", "gr": "greece", "pt": "portugal",
}
N_TRAIN, N_NONE, N_DEMO_NONE, SIZE = 300, 300, 10, 256
rng = random.Random(0)


def rasterise(code: str) -> Image.Image:
    png = cairosvg.svg2png(url=str(ICONS / f"{code}.svg"), output_width=480, output_height=360)
    return Image.open(io.BytesIO(png)).convert("RGB")


def wave(img: Image.Image) -> Image.Image:
    """Paper curl: shift each column vertically by a sine of x."""
    a = np.asarray(img)
    h, w = a.shape[:2]
    amp, freq, phase = rng.uniform(0, 0.02) * h, rng.uniform(1, 3), rng.uniform(0, 2 * math.pi)
    out = np.empty_like(a)
    for x in range(w):
        dy = int(amp * math.sin(freq * 2 * math.pi * x / w + phase))
        out[:, x] = np.roll(a[:, x], dy, axis=0)
    return Image.fromarray(out)


def perspective(img: Image.Image, jitter: float) -> Image.Image:
    w, h = img.size
    j = lambda: rng.uniform(-jitter, jitter)
    dst = [(w * j(), h * j()), (w * (1 + j()), h * j()), (w * (1 + j()), h * (1 + j())), (w * j(), h * (1 + j()))]
    src = [(0, 0), (w, 0), (w, h), (0, h)]
    # Solve for the 8 perspective coefficients (PIL wants dst->src).
    A, B = [], []
    for (x, y), (u, v) in zip(dst, src):
        A += [[x, y, 1, 0, 0, 0, -u * x, -u * y], [0, 0, 0, x, y, 1, -v * x, -v * y]]
        B += [u, v]
    coeffs = np.linalg.solve(np.array(A, dtype=float), np.array(B, dtype=float))
    return img.transform(img.size, Image.PERSPECTIVE, coeffs.tolist(), Image.BICUBIC)


def background() -> Image.Image:
    r = rng.random()
    if BACKGROUNDS and r < 0.6:
        img = Image.open(rng.choice(BACKGROUNDS)).convert("RGB")
        s = min(img.size)
        return img.crop(((img.width - s) // 2, (img.height - s) // 2, (img.width + s) // 2,
                         (img.height + s) // 2)).resize((SIZE, SIZE))
    if r < 0.75:  # sky gradient: the Commons photos are flags on poles against sky
        top = np.array([rng.randint(60, 140), rng.randint(120, 190), rng.randint(190, 255)])
        bot = np.array([rng.randint(150, 230), rng.randint(180, 240), rng.randint(220, 255)])
        t = np.linspace(0, 1, SIZE)[:, None, None]
        return Image.fromarray((top * (1 - t) + bot * t).astype(np.uint8).repeat(SIZE, 1))
    base = np.full((SIZE, SIZE, 3), [rng.randint(0, 255) for _ in range(3)], np.uint8)
    noise = np.random.default_rng(rng.randint(0, 1 << 30)).integers(-25, 25, base.shape)
    return Image.fromarray(np.clip(base + noise, 0, 255).astype(np.uint8))


def variant(flag: Image.Image) -> Image.Image:
    f = flag
    if rng.random() < 0.5:  # printed on paper: a white margin around the flag
        m = int(f.width * rng.uniform(0.02, 0.1))
        paper = Image.new("RGB", (f.width + 2 * m, f.height + 2 * m), tuple([rng.randint(225, 255)] * 3))
        paper.paste(f, (m, m))
        f = paper
    f = wave(f).convert("RGBA")
    scale = rng.uniform(0.3, 1.0)  # held up to the camera: >= 30 % of the frame
    fw = int(SIZE * scale)
    aspect = 0.75 * rng.uniform(0.45, 1.1)  # foreshortening when seen from the side
    f = f.resize((fw, max(8, int(fw * aspect))), Image.BICUBIC)
    f = perspective(f, rng.uniform(0, 0.2))
    bg = background()
    x = rng.randint(min(0, SIZE - f.width), max(0, SIZE - f.width))
    y = rng.randint(min(0, SIZE - f.height), max(0, SIZE - f.height))
    bg.paste(f, (x, y), f)
    img = bg
    img = ImageEnhance.Brightness(img).enhance(rng.uniform(0.6, 1.4))
    img = ImageEnhance.Contrast(img).enhance(rng.uniform(0.7, 1.3))
    img = ImageEnhance.Color(img).enhance(rng.uniform(0.7, 1.3))
    if rng.random() < 0.4:
        img = img.filter(ImageFilter.GaussianBlur(rng.uniform(0.3, 1.5)))
    return img


if __name__ == "__main__":
    from common import coco_images

    BACKGROUNDS.extend(coco_images("train"))
    data, demo = HERE / "data" / "flag", HERE.parent / "demo-images" / "flag"
    shutil.rmtree(data, ignore_errors=True)
    ours = {code: rasterise(code) for code in COUNTRIES}
    for code, label in COUNTRIES.items():
        (data / label).mkdir(parents=True)
        for i in range(N_TRAIN):
            variant(ours[code]).save(data / label / f"{code}_{i:03d}.jpg", quality=rng.randint(60, 95))
        print(label)

    def thumb(img):
        return np.asarray(img.resize((64, 48)), np.float32) / 255

    others, twins = [], []
    for svg in sorted(ICONS.glob("*.svg")):
        if svg.stem in COUNTRIES:
            continue
        flag = rasterise(svg.stem)
        diff = min(np.abs(thumb(flag) - thumb(o)).mean() for o in ours.values())
        # 0.07: Monaco 0.044 and the blue ensigns (<= 0.070) out, Bulgaria (0.073) stays a negative
        (twins if diff < 0.07 else others).append((svg.stem, flag))
    print(f"none: {len(others)} other flags; excluded as near-identical to ours: {[c for c, _ in twins]}")
    (data / "none").mkdir()
    for i in range(N_NONE):
        code, flag = rng.choice(others)
        variant(flag).save(data / "none" / f"{code}_{i:03d}.jpg", quality=rng.randint(60, 95))
    demo.mkdir(parents=True, exist_ok=True)  # held-out negatives: unseen COCO scenes + other flags on them
    for old in demo.glob("none_*.jpg"):
        old.unlink()
    BACKGROUNDS[:] = coco_images("test")
    for i in range(N_DEMO_NONE):
        Image.open(BACKGROUNDS[i * 7]).convert("RGB").save(demo / f"none_{i:02d}.jpg", quality=90)
        variant(rng.choice(others)[1]).save(demo / f"none_{N_DEMO_NONE + i:02d}.jpg", quality=90)
    print(f"{len(COUNTRIES)} classes x {N_TRAIN} + none {N_NONE} -> {data}; {2 * N_DEMO_NONE} none demo images")
