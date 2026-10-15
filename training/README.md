# training/ — train your own image classifier for the board

Photos in folders → ResNet-18 fine-tune → OpenVINO model → upload in the web GUI → runs on the
board's DLA with the live camera. The catalog `fruit` and `flag` models are built exactly this way;
their download scripts are the worked examples. Plan and rationale:
[../docs/MODEL_ROBUSTNESS_PLAN.md](../docs/MODEL_ROBUSTNESS_PLAN.md).

## Guide

**0. Environment (once).** Everything runs in `~/build-openvino-dev/openvino_env` (torch 2.5.1+cu118,
openvino 2024.6.0, plus `huggingface_hub cairosvg requests`); other versions may fail the lab's
model check. An NVIDIA GPU is assumed (`train.py` uses CUDA). Then fetch COCO, which every model
uses for its `none` class:

```bash
source ~/build-openvino-dev/openvino_env/bin/activate && cd training
mkdir -p data/coco && cd data/coco
curl -LO http://images.cocodataset.org/zips/val2017.zip && unzip -q val2017.zip && rm val2017.zip
curl -LO http://images.cocodataset.org/annotations/annotations_trainval2017.zip
unzip -q annotations_trainval2017.zip annotations/instances_val2017.json && rm annotations_trainval2017.zip
cd ../..
```

**1. Your photos.** One folder per class, at least 30 photos each (phone photos or downloads, any size):

```
data/<name>/<label>/*.jpg        e.g. data/snacks/chips/001.jpg, data/snacks/cookie/001.jpg
data/<name>/none/*.jpg           optional: things that are NOT your classes but look close
../demo-images/<name>/<label>_<nn>.jpg   optional: a few test photos per class, never in data/
```

Labels are lowercase, spaces allowed. `none` is reserved (step 2 adds it).

**2. Prepare.** `python prepare.py <name>` adds the `none` class (your `data/<name>/none/` topped up
with COCO scenes), splits 15 % per class off for validation into `data/<name>-split/`, and writes
`../models/<name>/categories.txt`. Without `none`, the model names one of your classes for every
frame, even an empty room.

**3. Train.** `python train.py <name>` (about 2 min for 5k images on an RTX 4080). Add `--no-flip` if
a mirror image changes the class (flags, text, logos). It prints validation accuracy per epoch and,
at the end, PASS/LOW checks on your `demo-images` (as they are, through the camera/screen
simulation, and `none` recall). The model is `runs/<name>/model.pt`.

**4. Export.** `python export.py <name>` writes `../models/<name>/model.xml` and `model.bin` (the
OpenVINO model with normalisation and softmax built in) and checks it against PyTorch.

**5. Upload.** In the web GUI: **My model +** → drop `model.xml`, `model.bin`, `categories.txt` from
`../models/<name>/`, pick a name → **Upload & deploy**. The lab checks it, compiles it for the DLA
and puts it on the board (a few minutes). Hold your objects up to the camera inside the square.

### What to change for your own data

| Part | Change it? |
|---|---|
| `data/<name>/…` photos, `demo-images/<name>/` | **yes**: your classes |
| `--no-flip`, `--no-sim` | **per dataset** |
| `augment.py` (rotation angle, effect strengths) | only if your objects need it |
| `prepare.py`, `train.py`, `export.py`, `common.py` | **no**: they define what the board expects |

### Why it works on the board camera

- **Same crop as the board.** The board classifies the centre square of the 16:9 camera frame (what
  the web page shows). `common.center_square` does the same in validation, export and checks.
- **Camera/screen simulation** (`augment.py`). The camera has a fixed exposure and white balance
  (blue-ish, often dark), dark corners, blur and JPEG. Objects shown on a phone add a bezel, moiré
  bands and glare. Training images get these at random, plus rotation up to ±45° without black
  corners, and colour jitter (which also covers printed paper).
- **`none` class** for everything else in view.

**Limits.** Objects should fill at least 30 % of the square. Rotation beyond 45° isn't trained.
Near-identical things are read as the closest class, not `none` (Monaco as Indonesia, a mandarin as
an orange). Robustness on the real camera is not measured, only simulated and checked by eye.

## Scripts

```
common.py           class list, deploy preprocessing (center_square + resize), backbone() (ResNet-18
                    default, AvgPool 7x7 stride 1), Deploy wrapper, coco_images() (COCO split: id % 10 == 0 is held out)
augment.py          RotateNoCorners, CameraScreen; `python augment.py` = self-check + runs/augment_sheet.jpg
prepare.py <name>   data/<name>/<label>/ -> data/<name>-split/{train,val}/ + none + models/<name>/categories.txt
train.py <name>     ImageNet ResNet-18 fine-tune -> runs/<name>/model.pt, metrics.json, confusion.txt
export.py <name>    model.pt -> ../models/<name>/model.{xml,bin} + cpu_reference.json over ../demo-images/<name>/
compile.sh <name>   dla_compiler -> ../models/<name>/graph.bin, placement/DDR checks   (catalog models only;
board_check.py <name>  demo-images through the board's dla-server inbox over ssh vs cpu_reference.json   the GUI does both for uploads)

Worked examples (write data/<name>/ + demo-images/<name>/):
get_fruit.py        HF VinayHajare/Fruits-30 (Apache-2.0, real photos, 2/class held out) + Fruits-360 100x100
                    (CC BY-SA 4.0) cut out and pasted on COCO scenes; other produce -> none
make_flags.py       flag-icons SVGs (MIT) as printed/on-screen flags on COCO scenes; ~225 other flags -> none
                    (near-identical ones such as Monaco are excluded automatically)
get_flag_photos.py  Wikimedia Commons (CC/PD only, up to 25/country) -> data/flag-real/<label>/ + SOURCES.md
split_flag_real.py  first 3/country -> ../demo-images/flag (held out), the rest -> data/flag/<label>/real_*.jpg
score_real.py       flag IR on data/flag-real via CPU plugin, contact sheets in data/flag-real/_sheets
```

Catalog models: `get_fruit.py` (or `make_flags.py` + `split_flag_real.py`) → `prepare.py` →
`train.py` (`--no-flip` for flags) → `export.py` → `compile.sh` → `../artifacts/build-model.sh <name>`
→ `../artifacts/mender-deploy.sh` → `board_check.py`. Fruits-360 for `get_fruit.py` (sparse
checkout of the folders it uses, ~1.7 GB):

```bash
cd data && git clone --depth 1 --filter=blob:none --sparse https://github.com/fruits-360/fruits-360-100x100.git fruits-360
cd fruits-360 && git sparse-checkout set --no-cone --stdin < ../../fruits360-folders.txt
```

## Gotchas found on the way

- `nn.AdaptiveAvgPool2d(1)` exports as ReduceMean and `nn.AvgPool2d(7)` (stride 7) hits "Pool
  strides exceed maximum (4, 4)" — either one drops the pool *and everything after it* to the CPU.
  `AvgPool2d(7, stride=1)` keeps the whole network on the FPGA except Softmax.
- `ARCH` is already an environment variable on this host (`arm64`); scripts use `DLA_ARCH`.
- Fruits-30 claims 224×224 but ships full-size photos (some > 2 MiB); demo copies are downscaled.
- `make_flags.py` is imported by `get_flag_photos.py` / `split_flag_real.py` for the country list,
  so its generator body is under `if __name__ == "__main__"`.
- Commons search `"flag of X"` returns crowds and buildings (15 % usable); `intitle:"flag of X"`
  with `-intitle:map -intitle:coat` gives mostly flags on poles. Still eyeball `_sheets/`.
- A plain rotation leaves black corners the camera never produces; `RotateNoCorners` crops them off.
- Several flag-icons territories fly exactly our flags (French territories, `um` = US, `hm` =
  Australia, `sh` = UK); training them as `none` would contradict the real class.

## Results (2026-09-24, centre-crop runtime `coredla-runtime-02530e18`)

| model | classes | train / val | final val top-1 | held-out (as is / camera-screen sim) | none recall | CPU == torch | board |
|---|---|---|---|---|---|---|---|
| fruit `eec306c8` (ResNet-50, rollback; run now `runs/fruit-resnet50`) | 15 + none | 4 764 / 832 (Fruits-30 + Fruits-360 composites + COCO) | 0.977 | 28/30 / 26/30 | 38/40 | 832/832 | board == CPU 50/50, == truth 48/50, 239 ms |
| fruit `7580298c` (ResNet-18, 2026-09-28, defaults) | 15 + none | same | 0.972 | 27/30 / 25/30 | 38/40 | 832/832 | board == CPU 50/50, == truth 46/50, ~98 ms |
| flag `73107bc0` (ResNet-18, 2026-09-28, `--no-flip --teacher flag-resnet50 --sim-p 0.5`) | 30 + none | same | 0.981 | 68/90 / 66/90 | 37/40 | 1483/1483 | board == CPU 101/110, == truth 79/110, ~96 ms |
| flag `60483e80` (ResNet-50, rollback + teacher; `runs/flag-resnet50`) | 30 + none | 8 514 / 1 483 (synthetic print/screen + 373 Commons + COCO) | 0.980 | 71/90 / 66/90 (Commons fabric flags, not a target) | 34/40 | 1483/1483 | board == CPU 101/110, == truth 85/110, 239 ms |

Training takes ~2 min (fruit) and ~3 min (flag) on the RTX 4080. The flag held-out set is flags on
poles (fabric), which is out of scope. The old flag v2 scored 66/90 on the same photos with the old
squashed input.
