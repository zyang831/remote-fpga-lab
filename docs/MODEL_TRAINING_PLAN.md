# Fruit + flag classifiers — dataset → training → IR → graph.bin

Date: 2026-09-17. **Executed the same day — see `training/README.md` for the scripts and measured results; deviations from this plan are listed at the end (§8).** Fills the gap that stopped plan step 1.0 ([EDGE_AI_DEMO_PLAN.md](EDGE_AI_DEMO_PLAN.md)): no fruit/flag model exists. This is also the phase-3 "export kit" — whatever a user uploads later must come out of the same scripts.

Everything lands in `training/` in this repo; datasets and checkpoints in `training/data/` and `training/runs/` (gitignored). Outputs per model go to `models/<name>/` and feed `artifacts/build-model.sh <name>` unchanged.

## 0. The contract the model must meet (fixed by what already runs)

Measured on the board and in dla-server, not assumed:

| Item | Value | Where it is enforced |
|---|---|---|
| Arch | `AGX5_Small_k16c16_sb20480.arch` (`models/imagenet/`) | bitstream on the board; graph must be compiled for it |
| IR input | one tensor, **`[1,3,224,224]` f32 NCHW** after dlac (NHWC IR is fine, dlac folds the transpose) | `dla-server/main.cpp` asserts 4-D, 3 channels, f32 |
| Pixel values | **RGB, 0–255, plain resize to 224×224, no crop** | `dla-server` `fill_input()`; mean/scale must be inside the graph |
| IR output | one tensor `[1,N]`, softmax probabilities | dla-server top-5 sorts raw floats; softmax runs on the CPU sub-model (arch has no softmax primitive) |
| `categories.txt` | N lines, line i = output i, no implicit background | dla-server refuses to start on mismatch |
| Labels | lowercase, `a-z0-9`, spaces allowed (browser maps spaces→`_` for filename ground truth) | `static/app.js` `truthFromName()` |
| Toolchain | OpenVINO **2024.6.0** IR (`ovc` from that version), dlac **2025.3.1/20** | board runtime is 2024.6.0; plugin checks `build_version.txt` |

Finding while checking this: the shipped `resnet-50-tf` IR was converted with `--reverse_input_channels`, so it expects **BGR**; dla_benchmark and dla-server feed RGB. On the 10 sample images BGR input scores higher (sax 0.57 vs "flute" 0.78 wrong; banana 0.95 vs 0.70) — top-1 still 8/10 either way. Our own exports take RGB, so nothing changes in dla-server. Optional later: re-convert the ImageNet IR without `--reverse_input_channels` and recompile so the fallback model is consistent too.

## 1. Environment (host, RTX 4080 SUPER 16 GB, 32 cores)

Use `~/build-openvino-dev/openvino_env`: torch 2.5.1+cu118 (CUDA verified working), torchvision 0.20.1, openvino + openvino-dev 2024.6.0, pillow, numpy. TensorFlow 2.17 in the same venv fails to initialise (`_pywrap_checkpoint_reader` SystemError) → **train in PyTorch**, not Keras. Add `cairosvg` (flag rasterising), `kaggle` (only if a Kaggle dataset is chosen).

dlac: `source /opt/altera/fpga_ai_suite_2025.3.1/dla/bin/init_env.sh` (plus `source /opt/intel/openvino_2024/setupvars.sh`), as in RUNBOOK step 13.

No x86 emulator build exists (`build_Release` is the aarch64 tree). Validation = IR on the OpenVINO CPU plugin (host) + the real board. Building `build_runtime.sh -target_emulation` is optional and not on the critical path.

## 2. Datasets

Class count drives N in `categories.txt` and the FC layer. Keep both demos small enough that a visitor can name every class: **~15 fruits, ~30 flags**.

### 2.1 Fruit

Two candidates; pick by what the demo audience will upload (phone photos of real fruit):

1. **Fruit and Vegetable Image Recognition** (Kaggle, kritikseth) — 36 classes, ~3.8 k web-scraped photos with backgrounds, train/validation/test folders given. Realistic → generalises to phone photos. Needs a Kaggle API token (`~/.kaggle/kaggle.json`, none present today). Check the licence on the dataset page before the FYP writeup. **Recommended.** Keep only the fruit classes (~15: apple, banana, grapes, kiwi, lemon, mango, orange, pear, pineapple, pomegranate, watermelon, …), drop vegetables.
2. **Fruits-360** (GitHub `Horea94/Fruit-Images-Dataset`, CC BY-SA 4.0, no account) — 100×100 px, white background, one rotating fruit per class, 130+ varieties. Trains to ~100 % in minutes but generalises badly to real photos. Fallback only, or extra training data after merging varieties (`Apple Red 1/2/3` → `apple`).

Steps:
1. `training/get_fruit.sh` — download, unzip into `training/data/fruit/{train,val,test}/<class>/`, keep chosen classes, lowercase names. Record the class list in `models/fruit/categories.txt` (sorted, one per line) — this is the only place the order is defined; `train.py` reads it.
2. Sanity: `find training/data/fruit -name "*.jpg" | wc -l` per split; open 5 random images per class; delete corrupt files (`PIL.Image.verify()` loop).
3. **Demo test set**: 2–3 images per class copied to `demo-images/fruit/<label>_<nn>.jpg` (repo, small). Also add ~10 of your own phone photos named the same way — those are what the demo is judged on.

### 2.2 Flags

Photos of flags per country are scarce and licences messy. Render them instead:

1. `flag-icons` (GitHub `lipis/flag-icons`, MIT) — SVG for every ISO country. `git clone --depth 1` into `training/data/flag-icons`.
2. Choose ~30 countries (ASEAN + G20 + host country is a natural demo set). `models/flag/categories.txt` = lowercase country names (`malaysia`, `united kingdom`, …), sorted.
3. `training/make_flags.py`: rasterise each SVG at 512 px (`cairosvg`), then generate ~400 train / 50 val images per class with augmentation that mimics photos: random perspective warp, a sinusoidal "waving" displacement, random background photos (any free texture set or the fruit train images), scale 40–100 % of frame, brightness/contrast/blur/JPEG-quality jitter, slight hue shift. Save as JPEG in `training/data/flag/{train,val}/<class>/`.
4. **Real test set** (mandatory, otherwise accuracy means nothing): 3–5 real photos per country — Wikimedia Commons (check each licence), or photograph printed/screen flags with a phone. `demo-images/flag/<label>_<nn>.jpg`. Held out from training entirely.

Risk: synthetic→real gap. If real-photo top-1 < 80 %, add the real photos' siblings to training (keep the demo set held out) or reduce to 15 visually distinct flags.

## 3. Training — `training/train.py` (one script, both models)

- Backbone: `torchvision.models.resnet50(weights=IMAGENET1K_V1)`; replace `fc` with `Linear(2048, N)`, N = lines in `models/<name>/categories.txt`. Replace `model.avgpool = nn.AvgPool2d(7)` **before** training/export — `AdaptiveAvgPool2d` converts to a `ReduceMean`, which may not be an FPGA primitive; `AvgPool 7×7` is.
- Input pipeline (must match the board): train `RandomResizedCrop(224, scale=(0.5,1))` + flip (fruit only; flags are chiral, no flip) + ColorJitter; **val/test: `Resize((224,224))` — not Resize(256)+CenterCrop(224)**, because dla-server does a plain resize. Normalise with ImageNet mean/std inside the training transform; the same normalisation gets baked into the exported graph (§4).
- Recipe: AdamW lr 1e-4 (backbone) / 1e-3 (fc), cosine schedule, label smoothing 0.1, batch 64, AMP, 15 epochs fruit / 10 epochs flag. First 2 epochs backbone frozen. ~5–10 min per model on the 4080.
- Outputs: `training/runs/<name>/best.pt` (best val top-1), `metrics.json` (per-epoch loss/top-1/top-5), confusion matrix PNG for the writeup.
- Verify: val top-1 ≥ 90 % (fruit) / ≥ 95 % synthetic val and ≥ 80 % on the real flag test set. Below that → more data/augmentation, not more epochs.

## 4. Export — `training/export.py` → `models/<name>/model.{xml,bin}`

1. Wrap the trained model so the graph takes raw 0–255 RGB:
   ```python
   class Deploy(nn.Module):           # x: [1,3,224,224] float, 0..255, RGB
       def forward(self, x):
           x = (x / 255.0 - MEAN) / STD    # constants -> folded into the IR
           return torch.softmax(self.net(x), dim=1)
   ```
   Softmax stays in the graph so the output matches the ImageNet IR (`[1,N]` probabilities; dlac places it on CPU).
2. `ov.convert_model(Deploy(model).eval(), example_input=torch.zeros(1,3,224,224), input=[1,3,224,224])` → `ov.save_model(m, "models/<name>/model.xml", compress_to_fp16=False)`. FP32 IR: dlac does its own quantisation; FP16 weights just add a convert. Pin the input name (`m.inputs[0].get_tensor().set_names({"image"})`) so phase-3's "xml equal except FC" diff is stable.
3. CPU check: run `model.xml` on the OpenVINO CPU plugin over the val split with the exact dla-server preprocessing (PIL resize → RGB → f32, no normalisation) and assert top-1 == PyTorch top-1 on ≥ 99 % of images. Save `models/<name>/cpu_reference.json` (`{filename: top5}`) over `demo-images/<name>/` — this is the oracle plan step 1.0 asks for.
4. `wc -l models/<name>/categories.txt` == output dim (read from the IR). Write `models/<name>/name`.

## 5. Compile + package + deploy — `training/compile.sh <name>`

```bash
source /opt/intel/openvino_2024/setupvars.sh
source /opt/altera/fpga_ai_suite_2025.3.1/dla/bin/init_env.sh
cd models/<name>
dla_compiler --march AGX5_Small_k16c16_sb20480.arch --network-file model.xml \
             --foutput-format dla_compiled_result --o graph.bin --fdisplay-device
```
Checks after the compile (all in `compile.sh`, fail loudly):
- `*_FPGA_dla_layer_device.csv`: every layer on FPGA except the final `Softmax` (and nothing else on CPU). A `ReduceMean`/`Gather`/unexpected CPU layer means the export changed the graph — fix in §4, not by accepting a slower hetero split.
- `ddr_buffer_info_*.txt`: configFilterBuffer + buffers < 256 MB window (ResNet-50 is ~56 MB; only FC size changes with N).
- `graph.bin` starts with `HETERO:FPGA,CPU\0` (dla-server checks this too).
- File sizes: `graph.bin` ≈ 150 MB regardless of N.

Then, unchanged from phase 1: `artifacts/build-model.sh <name>` → `artifacts/mender-deploy.sh build/coredla-model-<name>-<hash>.mender`, set `MODEL_ARTIFACT_NAME`/`MODEL_NAME` in lab-backend `config.py`, restart uvicorn.

Board verify (phase-1 criteria): `demo-images/<name>/` through the browser → per-image top-1 matches `cpu_reference.json` (allow ≤ 1 disagreement per 20 images from FPGA FP12 filters; investigate more); accuracy line matches a hand count; unlabeled file shows no ✓/✗.

## 6. Order and effort

| Step | Time | Output |
|---|---|---|
| 1 Kaggle token or Fruits-360 clone; `get_fruit.sh` | 30 min | `data/fruit/`, `models/fruit/categories.txt` |
| 2 `train.py fruit` | 15 min | `runs/fruit/best.pt`, val ≥ 90 % |
| 3 `export.py fruit` + CPU check | 15 min | `models/fruit/model.xml/.bin`, `cpu_reference.json` |
| 4 `compile.sh fruit` → build-model → deploy → browser | 30 min | fruit live on the board = **phase 1 done as written** |
| 5 `make_flags.py` + real flag photos | 2–3 h (photo collection dominates) | `data/flag/`, `demo-images/flag/` |
| 6 steps 2–4 for flag | 1 h | flag artifact = phase 2 catalog entry |
| 7 Re-convert ImageNet IR without `--reverse_input_channels`, recompile (optional) | 30 min | consistent fallback model |

Step 4 is the first moment a custom-FC graph goes through dlac — the untested risk from the plan. Do fruit end to end before touching flags.

## 7. Decisions taken here

- PyTorch/torchvision ResNet-50, not the TF `resnet_v1-50` frozen graph: TF is broken in the venv, and dla-server only needs the tensor contract. Consequence: phase 3's "xml == reference except FC dims" compares against **our** export, not the OMZ IR.
- Normalisation and softmax inside the graph; dla-server stays a dumb resize+RGB feeder.
- Plain 224×224 resize everywhere (train val, CPU oracle, board) — one preprocessing, no crop.
- Flags synthetic-trained, real-tested. Fruit real-trained.
- Class lists live in `models/<name>/categories.txt` and nowhere else.

## 8. What actually happened (2026-09-17)

- Fruit data: no Kaggle token, so HF `VinayHajare/Fruits-30` (Apache-2.0, real photos) instead — 15 classes, 381 train / 87 val. Small; apple (13) and banana (9) are thin. Val top-1 0.908, top-5 1.0.
- AvgPool: `AvgPool2d(7)` also fails — arch caps pool **strides** at 4 ("exceeds maximum width/height strides (4, 4)") and takes the FC with it to the CPU. `AvgPool2d(7, stride=1)` compiles fully on the FPGA; only Softmax on CPU, like the ImageNet graph. DDR: configFilterBuffer 47.7 MB.
- Fruit on the board: 28/30 demo images match the CPU oracle, 28/30 match filename truth, 329 ms/image. The two disagreements are low-confidence (0.27–0.41) borderline cases, one each way.
- Flags: 30 countries, 300/40 synthetic per class, val 1.0. Real Commons photos (`get_flag_photos.py`, CC/PD only, `intitle:` search): 0.57 → 0.63 top-1 after adding sky backgrounds, small scale (0.2+), foreshortening and stronger perspective to the generator. That number is a lower bound — Commons titles are noisy (Canada photos showing Chinese flags, historical variants). `demo-images/flag/` = 81 title-filtered real photos (max 3/country), CPU oracle 52/81.
- Below the 80 % real-photo target → applied the §2.2 risk clause: `get_flag_photos.py` now pulls up to 25 photos per country (alternate title phrases for thin ones: "american flag", "union jack", "jalur gemilang"…), `split_flag_real.py` keeps 3/country held out in `demo-images/flag` (90) and puts 373 into training, oversampled ×8 (`WeightedRandomSampler`). Held-out real top-1: 0.64 → **0.73** (≈ 0.78 after discounting mislabeled Commons files); remaining misses are flags < 5 % of the frame.
- Storage: HF download cache (a second copy of the fruit set) is deleted by `get_fruit.py` after the split; old `.mender` files and `runtime.tar` removed — artifacts live on the Mender server, `build-runtime.sh` regenerates the tar.
