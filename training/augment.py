"""Training-time augmentations that make clean dataset photos look like what the
board's IMX519 camera sees (PIL image in, PIL image out, any size).

  RotateNoCorners  rotate up to +-45 deg, then crop the square that has no black
                   corners (a plain rotation leaves them; the camera never does)
  CameraScreen     the image as shown on a screen (dark bezel, moire bands, glare)
                   and/or as filmed by this camera (blue/cyan cast, exposure,
                   vignetting, blur, noise, JPEG). Each effect is on with probability p.

Printed paper needs nothing extra: ColorJitter (desaturation, tint) + blur cover it.

  python augment.py      # self-check + runs/augment_sheet.jpg (64 samples to eyeball)
"""
import io
import math
import random

import numpy as np
from PIL import Image


class RotateNoCorners:
    def __init__(self, degrees: float = 45):
        self.degrees = degrees

    def __call__(self, img: Image.Image) -> Image.Image:
        t = math.radians(random.uniform(-self.degrees, self.degrees))
        w, h = img.size
        # Largest centred square inside the rotated frame, minus 2 px of interpolated edge.
        s = int(min(w, h) / (abs(math.cos(t)) + abs(math.sin(t)))) - 2
        l, u = (w - s) // 2, (h - s) // 2
        return img.rotate(math.degrees(t), Image.BILINEAR).crop((l, u, l + s, u + s)).resize((w, h), Image.BILINEAR)


class CameraScreen:
    def __init__(self, p: float = 0.3):
        self.p = p

    def _on(self) -> bool:
        return random.random() < self.p

    def __call__(self, img: Image.Image) -> Image.Image:
        w, h = img.size
        if self._on():  # screen bezel: the picture sits inside a dark frame
            k = random.uniform(0.03, 0.12)
            frame = Image.new("RGB", (w, h), tuple(random.randint(5, 40) for _ in range(3)))
            frame.paste(img.resize((int(w * (1 - 2 * k)), int(h * (1 - 2 * k)))), (int(w * k), int(h * k)))
            img = frame
        a = np.asarray(img, np.float32) / 255
        y, x = np.mgrid[0:h, 0:w].astype(np.float32)
        if self._on():  # moire: low-frequency colour bands where the screen's pixel grid beats the sensor's
            f, th, amp = random.uniform(0.02, 0.15), random.uniform(0, math.pi), random.uniform(0.05, 0.2)
            u = 2 * math.pi * f * (x * math.cos(th) + y * math.sin(th))
            ph = random.uniform(0, 2 * math.pi)
            a *= np.stack([1 - amp * (0.5 + 0.5 * np.cos(u + ph + c * 2.1)) for c in range(3)], -1)
        if self._on():  # glare: a soft bright blob from a light reflected in the glass
            cx, cy, sx, sy = random.uniform(0, w), random.uniform(0, h), random.uniform(0.1, 0.4) * w, random.uniform(0.1, 0.4) * h
            a += random.uniform(0.2, 0.6) * np.exp(-((x - cx) ** 2 / sx ** 2 + (y - cy) ** 2 / sy ** 2))[..., None]
        if self._on():  # colour cast: fixed sensor white balance leans blue/cyan
            a *= np.array([random.uniform(0.7, 1.1), random.uniform(0.85, 1.15), random.uniform(0.95, 1.3)], np.float32)
        if self._on():  # exposure: fixed shutter/gain, so rooms come out too dark or a bit bright
            a *= 2 ** random.uniform(-1.5, 0.5)
        if self._on():  # vignetting: corners darker than the centre
            r2 = ((x - w / 2) ** 2 + (y - h / 2) ** 2) / ((w / 2) ** 2 + (h / 2) ** 2)
            a *= (1 - random.uniform(0.1, 0.4) * r2)[..., None]
        if self._on():  # sensor noise
            a += np.random.default_rng(random.getrandbits(32)).normal(0, random.uniform(0.01, 0.04), a.shape)
        img = Image.fromarray((np.clip(a, 0, 1) * 255).astype(np.uint8))
        if self._on():  # soft optics / small object: down then up
            k = random.uniform(0.35, 0.7)
            img = img.resize((max(1, int(w * k)), max(1, int(h * k))), Image.BILINEAR).resize((w, h), Image.BILINEAR)
        if self._on():  # JPEG, as in the live frame
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=random.randint(60, 90))
            img = Image.open(buf).convert("RGB")
        return img


if __name__ == "__main__":
    from pathlib import Path

    random.seed(0)
    white = Image.new("RGB", (224, 224), (255, 255, 255))
    for _ in range(50):  # no black corners at any angle
        assert np.asarray(RotateNoCorners()(white)).min() > 240
    out = CameraScreen(p=1.0)(white)
    assert out.size == white.size and out.mode == "RGB"
    root = Path(__file__).resolve().parent
    files = sorted((root.parent / "demo-images").rglob("*.jpg"))
    random.shuffle(files)
    sheet = Image.new("RGB", (8 * 160, 8 * 160))
    rot, cam = RotateNoCorners(), CameraScreen(p=0.5)
    for i, f in enumerate(files[:64]):
        img = Image.open(f).convert("RGB")
        s = min(img.size)
        img = img.crop(((img.width - s) // 2, (img.height - s) // 2, (img.width + s) // 2, (img.height + s) // 2))
        sheet.paste(cam(rot(img.resize((224, 224)))).resize((160, 160)), ((i % 8) * 160, (i // 8) * 160))
    (root / "runs").mkdir(exist_ok=True)
    sheet.save(root / "runs" / "augment_sheet.jpg", quality=85)
    print("ok ->", root / "runs" / "augment_sheet.jpg")
