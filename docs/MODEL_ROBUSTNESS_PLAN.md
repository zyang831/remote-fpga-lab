# Fruit + flag classifiers: robustness retrain and student guide

Date: 2026-09-24. Status: **built 2026-09-24 (steps 1–7, §9); deviations from the plan in §9.1.**
Follows [MODEL_TRAINING_PLAN.md](MODEL_TRAINING_PLAN.md) (first training, 2026-09-17) and
[CAMERA_MIGRATION_PLAN.md](CAMERA_MIGRATION_PLAN.md) (live IMX519 camera).

## 1. Goal and constraints

**Primary deliverable: a guide.** A student downloads data, trains a model, exports it and uploads it
to the board. It lives in `training/README.md`, and the catalog `fruit` and `flag` models are built by
the same path, as the worked examples.

**Secondary: the catalog models themselves.** Retrain `fruit` (replaces `fruit-v1` in the catalog) and
`flag` so each plausibly recognises its target on the board's MIPI IMX519 camera:

- **Where it's shown:** on any screen (phone, tablet, laptop, including an examiner's device), printed on
  paper, or, for fruit, the real fruit.
- **What must hold:** any venue, lighting changes, rotation up to ±45°.
- **Anything else in view** (not in the lists) should read `none`.

Accuracy is **not** a project goal: no comparisons or ablations, and nothing needs to beat the current
models. The pipeline has to be clear and reproducible.

**Fixed contract** (unchanged unless noted):
- **Model:** ResNet-50 with `AvgPool2d(7, stride=1)`. Input is RGB 0–255, **centre square crop** (new,
  §2), then resize to 224×224. Normalisation and softmax are baked in by `common.Deploy`. Compiled for
  arch `AGX5_Small_k16c16_sb20480`.
- **Tooling:** `export.py` / `compile.sh` / `build-model.sh` unchanged.
- **Camera settings frozen** for the project and the demo: `DLA_CAM_EXPOSURE` 1147, `DLA_CAM_GAIN` 850,
  fixed R/B gains from `imx519_modes.h`, no auto-exposure or auto white balance.

**Out of scope:**
- **Rotation beyond ±45°**: flipped or upside-down flags get confused. Flags keep `--no-flip`.
- **Cartoon/clipart fruit, black-and-white prints, two different fruits in one frame.**
- **Fabric flags as a target.**
- **Objects smaller than 30 % of the square's width.** The guide says "hold it closer".
- **Any real-camera data capture.** No venue is fixed and there's no capture time. Robustness on the
  camera itself is **not measured**; only a live check by eye (§7).
- **The training notebook.** It only gets a crop sync (§9).

## 2. What the camera delivers (probed 2026-09-24)

| Property | Value | Consequence |
|---|---|---|
| Live frame | 1080p debayered and shrunk to 480×270 (16:9) | — |
| Model input | **centre 270×270 square**, then resized to 224 (since runtime `02530e18`); was a plain squash (~1.8× horizontal) | objects undistorted, small objects ~1.8× larger |
| Exposure / white balance | fixed, no auto-exposure or auto white balance | blue/cyan cast, dark frames; lighting changes reach the model uncorrected |
| Optics | strong vignetting (dark corners); ~8 px magenta stripe on the left edge (outside the centre square) | vignetting simulated in training |
| GUI | live box is `aspect-ratio: 1; object-fit: cover` | shows exactly the centre square the model sees |
| GUI prediction | raw top-1 per frame at ~4 Hz, no threshold, no smoothing | an empty scene still gets a label, hence the `none` class |

## 3. Techniques, by name

| Problem | Technique | How it's used here |
|---|---|---|
| Lighting | photometric augmentation (AugMix-style colour corruption) | colour-cast, exposure and white-balance jitter matched to the IMX519 |
| Orientation | geometric augmentation | `RandomRotation(45)` + `RandomPerspective` |
| Unknown venue | domain randomization (Tobin et al. 2017), copy-paste compositing | Fruits-360 cut-outs and flag rasters pasted on random COCO scenes |
| Screen / print | recapture simulation (moiré synthesis as in demoiréing work, e.g. UniDemoiré) | subpixel-grid moiré, glare, bezel. Print is covered by colour jitter (desaturation, tint) |
| Open set | explicit reject class | `none` = COCO scenes + non-target flags + non-target produce |
| Small data, OOD robustness | LP-FT (Kumar et al. 2022) | existing `train.py` schedule: 2 epochs head-only, then full fine-tune |

TrivialAugmentWide is not used: its rotation goes up to ±135°, and a short list of explicit transforms is
easier to teach.

## 4. Datasets

All under `training/data/` (gitignored).

| Directory | Content | Role | Status |
|---|---|---|---|
| `fruit/` | HF Fruits-30, 15 classes, real photos in scenes | fruit, as they are | on disk |
| `fruits-360/{Training,Test}/<variety>/` | Fruits-360 100×100, 89 varieties, CC BY-SA 4.0 | fruit cut-outs for compositing (all angles) | on disk |
| `fruits-360` extra folders | ~20 non-target produce (pear, tomato, avocado, …) via one more sparse-checkout line | `none` | **to fetch** |
| `coco/val2017` + annotations | COCO val2017, 5k scenes (~800 MB). Images containing COCO banana/apple/orange are dropped | `none` + compositing backgrounds | **to fetch** |
| `flag-icons/` | 271 SVGs (MIT) | our 30 flags + ~240 others for `none` | on disk |
| `flag-real/` | Commons photos (fabric flags) | training weight ×1; first 3 per country held out | on disk |
| `flag/` | synthetic set | regenerated by `make_flags.py` + `split_flag_real.py` | **to regenerate** |

**Handling rules:**
- **Fruits-360 labels:** varieties map to labels by folder prefix (`Apple*`→apple, `Limes`→lime,
  `orange 4`→orange, …).
- **Fruits-360 sampling:** keep every 4th frame (neighbouring frames are near-duplicates of one rotating
  fruit), and cap each class at ~600.
- **Fruits-360 `Test/`:** same physical fruits as `Training/`, so it is not an independent test.
- **Lookalikes excluded from `none`,** documented as "read as the nearest target": Monaco (≈ Indonesia),
  mandarin/tangerine/clementine (≈ orange), nectarine (≈ peach), grapefruit, cherry tomato (≈ cherry).
  Poland and every other flag stay `none`.
- **Held-out splits** for the sanity checks (§7) are separated by source image before any augmentation.

## 5. Data pipeline

**Student contract** (Q22): everything downstream reads only `data/<name>/<label>/*.jpg`. A plain folder
of photos (≥ 30 per class recommended), or a download script that produces one. The catalog models use
dataset-specific scripts that write into this layout:

- **`get_fruit.py`** (extended): Fruits-30 images, plus Fruits-360 cut-outs (white background removed by
  threshold) at random scale 30–90 % of the frame and ±45°, pasted on COCO backgrounds.
- **`make_flags.py`** (changed):
  - backgrounds: COCO scenes instead of fruit photos
  - rotation ±45°
  - flat rectangles with an optional white paper margin as the main case
  - only a mild cloth wave (read as paper curl)
- **`prepare.py <name>`** (new; the step shared by students and catalog models):
  - adds `none` (COCO scenes + the dataset-specific negatives: other flags or other produce)
  - splits train/val per source image
  - writes `models/<name>/categories.txt`
  - `none` sized at ~2× an average class; tuned only if the §7 checks say so

**`augment.py`** (new, one transform, each effect on at p≈0.3):

| Effect | Parameters |
|---|---|
| Camera look | per-channel gain 0.7–1.3 with blue/cyan bias; exposure −1.5…+0.5 EV; radial vignetting up to 40 %; down-then-up resample (blur); sensor noise; JPEG q60–90 |
| Screen | subpixel RGB-grid resample at random pitch/angle (moiré); gamma and colour-temperature shift; elliptical glare blob; dark bezel; perspective warp |

Print is covered by `ColorJitter` (desaturation, tint) and blur. There's no separate print simulation.

## 6. Training

- **Script:** `train.py`. ImageNet ResNet-50, AdamW (backbone 1e-4, head 1e-3), cosine schedule, label
  smoothing 0.1, LP-FT (`FREEZE_EPOCHS = 2`), 15 epochs.
- **Augmentation:**
  - `RandomResizedCrop(224, scale=(0.5,1))`
  - `RandomRotation(45)` + `RandomPerspective(0.2)`
  - `ColorJitter`
  - `augment.py`
  - `RandomHorizontalFlip` (fruit only)
- **Validation:** `common.center_square` + resize, exactly the deploy transform.
- **Checkpoint:** the **last** epoch, not the best (Q15). Validation runs on simulated held-out images for
  monitoring only.
- **Sampler:** Commons `real_` flags drop from ×8 to ×1.
- **Not done:** backbone swap (only ResNet-50 is proven fully on the FPGA), LoRA.

## 7. Checks (printed, not gating)

**Printed by `train.py` at the end** as PASS/LOW next to each number (Q26):
- top-1 on each held-out source (Fruits-30 val, Commons held-out, simulated held-out), bar ≥ 80 %
- `none` recall on held-out negatives (COCO, other flags, other produce), bar ≥ 80 %

**Unchanged:**
- `export.py`: CPU plugin == PyTorch on every val image; regenerates `cpu_reference.json` with the crop.
- `board_check.py`: board == CPU on `demo-images/`.

**Live check by eye after deploy** (Q24): the laptop screen shows a few fruit, flag and `none` images to
the board camera for ~5 min. Nothing is recorded; it catches pipeline bugs (crop, colour), nothing more.

## 8. Student guide (`training/README.md`, Q21)

Steps, one command each:
1. Put photos in `data/<name>/<label>/`, or use the HF download example (`get_fruit.py` style).
2. `prepare.py <name>`: adds `none`, splits val, writes `categories.txt`.
3. `train.py <name>` (`--no-flip` for chiral classes such as flags, text or logos).
4. `export.py <name>`: `model.xml`/`model.bin` + `categories.txt`.
5. Upload in the web GUI (**My model +**). The lab validates, compiles and deploys it (phase 3 path).

| Part | Student action |
|---|---|
| `data/<name>/<label>/` photos | **replace** with their own classes |
| `--no-flip`, rotation range, `augment.py` on/off | **set** per dataset |
| `prepare.py`, `train.py`, `augment.py`, `export.py`, backbone | **keep unchanged** |

The current scripts reference table and gotchas stay below the guide. The results table is replaced by
the §7 check output.

## 9. Work order

| # | Step | Check |
|---|---|---|
| 1 | Centre-square crop: `dla-server` `fill_input` + `common.center_square` (`load_deploy_image`, `train.py` val); runtime `coredla-runtime-02530e18` via Mender | **done 2026-09-24:** board == CPU-crop 6/6, == old squash 0/6 on 3:1 composites; live 0 overruns |
| 2 | Fetch COCO val2017 + annotations, extra Fruits-360 produce folders | counts; fruit-bearing COCO images dropped |
| 3 | `augment.py` | contact sheet of 64 augmented samples looks like the camera |
| 4 | `get_fruit.py` compositing; `make_flags.py` changes; `prepare.py` (`none`, split) | contact sheets per class + `none`; class counts |
| 5 | `train.py`: rotation, `augment.py`, last-epoch save, ×1 Commons, §7 printout | printout on both models |
| 6 | Export → compile → `build-model.sh` → deploy `fruit` and `flag`; catalog `fruit` replaces `fruit-v1` (lab-backend `MODEL_CATALOG`, `reset.sh` default) | `board_check.py` board == CPU; live check by eye (§7) |
| 7 | `training/README.md` → guide (§8); notebook: centre crop in its preprocessing only; RUNBOOK wording for the replaced `fruit-v1` | a dry run of the guide's steps on a toy 2-class folder ends with an upload in the GUI |

### 9.1 As built (2026-09-24): deviations from the plan above

- **Rotation only in training.** `augment.RotateNoCorners(45)` in `train.py`, applied after
  `RandomResizedCrop`; it crops the rotated square's black corners. Generators don't rotate, so
  rotations don't stack. `RandomPerspective` was dropped for the same black-corner reason; the flag
  generator already warps perspective.
- **No sampler weighting.** Plain shuffle, since Commons ×1 made the `WeightedRandomSampler` uniform
  anyway.
- **Composite and `none` sizes:**
  - Fruits-360: 300 composites per class (1–3 fruits each), not 600.
  - `none`: 300 dataset-specific negatives (other produce / other flags), topped up with COCO train
    scenes to 2× the average class.
- **Checks run on `demo-images/<name>/`** as the held-out set. Fruit: 30 Fruits-30 photos + 20
  `none`. Flag: 90 Commons photos + 20 `none`. The dataset scripts write the `none_*.jpg` files from
  COCO's held-out split (image id % 10 == 0) and from unseen produce/flags.
- **Flag lookalikes are detected automatically:** mean abs difference < 0.07 on 64×48 renders
  against our 30. Excluded: 12 territories flying French/US/UK/Australian flags, Monaco, and the
  blue ensigns of Pitcairn, Montserrat and Ascension.
- **Checkpoint file:** `runs/<name>/model.pt`, replacing `best.pt`.
- **Split output:** `prepare.py` writes `data/<name>-split/` (symlinks). `data/fruit-v1` is removed;
  `runs/fruit-v1/best.pt` stays, since it's the notebook's `static/fruit-v1.pt`.
- **Notebook** regenerated with the centre crop: v1 22/30 → 29/30 (val 79.3 % → 93.1 %).
- **RUNBOOK story rewritten.** The board runs the built-in robust models. The notebook improves the
  quick first model v1 (22/30 → ~29/30) and uploads it as `fruit-demo`. Live, the audience compares it
  with the built-in model; `fruit-demo` has no `none` answer, which leads into the full recipe. The
  notebook text now calls v1 "the quick first model", not "the board's model".
- **Deployed and checked 2026-09-24:** fruit board == CPU 50/50 (truth 48/50); flag board == CPU
  101/110 (truth 85/110); 239 ms. `reset.sh` passes with the new defaults, and the backend was
  restarted on them.
- **Board fault during the first fruit deploy:** `smmu=4 usb=1027`, the known dwc2/SMMU class. It
  needed a power cycle, then the redeploy succeeded.

## 10. Decision log (grilling, 2026-09-24)

| # | Question | Decision |
|---|---|---|
| — | Centre crop in dla-server | yes (done) |
| — | Catalog `fruit-v1` | replaced by the new robust `fruit` |
| — | Commons fabric flags | not a target; weight ×1, kept |
| Q1 | Nothing in view | explicit `none` class |
| Q2 | Print/screen source images | must not be training images (only relevant to the live check now) |
| Q3 | Screen devices | must handle any device; covered by screen simulation, not device-specific data |
| Q4 | Camera settings | frozen at current values |
| Q5, Q9, Q17, Q19, Q20 | Real-camera capture | **none at all**: no venue fixed, no time; recapture setup skipped |
| Q6 | Meaning of "reliable" | per-frame top-1; no GUI smoothing |
| Q7 | Class lists | keep 15 fruits, 30 flags |
| Q8, Q11 | Scenarios | any plausible: whole, sliced and bunches of fruit; flag emoji; fingers partly covering. Out: cartoon fruit, black-and-white, two different fruits |
| Q10, Q13 | Scope of `none` | anything not on the lists: COCO val2017 + other flags + other produce |
| Q12 | Minimum size | object ≥ 30 % of the square's width |
| Q14 | Lookalikes | excluded from `none`, documented |
| Q15 | Checkpoint | last epoch |
| Q16 | Comparisons | none; the deliverable is the guide |
| Q18, Q26 | Bars | ≥ 80 % per held-out source, `none` recall ≥ 80 %; printed, not gating. The draft's "≤ 5-point drop from adding `none`" was dropped: it needs a comparison run, which Q16 ruled out |
| Q21 | Guide | `training/README.md`, ends with the GUI upload |
| Q22 | Student input | a photo folder per class; HF download shown as the example |
| Q23 | `capture.py` | deleted |
| Q24 | Camera check | live by eye after deploy |
| Q25 | Pipeline | `none`, compositing, ±45°, crop, one camera+screen transform; print via colour jitter; Commons ×1 kept |
