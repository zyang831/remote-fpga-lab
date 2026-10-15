# Edge AI Remote FPGA Lab — implementation plan

Date: 2026-09-14, revised 2026-09-17 (fruit/flag two-model scenario). Research backing every decision: [EDGE_AI_DEMO_RESEARCH.md](EDGE_AI_DEMO_RESEARCH.md).

**Goal:** browser user uploads a fine-tuned ResNet-50 (IR weights + `categories.txt`), uploads test images, clicks "run inference", sees per-image top-5 + latency and aggregate accuracy from the real FPGA. Demo models: **fruit** and **country-flag** classifiers (two pretrained ResNet-50 fine-tunes, own `categories.txt` each). Built on existing lab-backend (`~/mender/lab-backend`) + Mender server + Tailscale.

## Architecture

```
browser ──HTTP──▶ lab-backend (FastAPI, ~/mender/lab-backend)
                    ├─ model upload ──▶ dlac (host, x86) ──▶ .mender bundle ──▶ Mender server ──▶ board
                    └─ image upload ──▶ scp over Tailscale ──▶ board:/var/lib/dla/inbox/
                                                                    │
board (CoreDLA SD): dla-server (C++, persistent, graph imported once) watches inbox,
                    writes <image>.json {top5:[{label,prob}], latency_ms} ──▶ backend ssh reads back
```

## Fixed decisions

- One board (board-01 == coredla, SD swapped). Use the **CoreDLA SD card**; add Mender to it. Do not port DLA onto the lab SD.
- Boot contract permanent: `mem=768M`, CoreDLA DT nodes in base dtb, 2 GB swap, `altera-msgdma` / `msgdma_userio` blacklisted from autoload (loaded by the update module after reconfig).
- Topology fixed: resnet-50-tf. Only final FC dims may vary. User supplies IR `.xml` + `.bin` + `categories.txt`; we supply the export kit.
- Demo models: **fruit** (N_fruit classes) and **flag** (N_flag classes), each with its own `categories.txt`. Both must exist as OpenVINO IR from the pinned `ovc` with the phase-3 preprocessing contract (RGB, 224×224, mean/scale folded). Exist only as TF/PyTorch checkpoints → run the export kit once on the host before phase 1.0. Record actual N_fruit / N_flag here once checked.
- `categories.txt` contract: one label per line, UTF-8, line index == FC output index, line count == FC output dim exactly. No implicit background line — the shipped ImageNet 1001-line file is just the N=1001 case. Ships in every `coredla-model` bundle beside graph.bin; dla-server reads N from it at import and aborts if N != output tensor dim. Nothing hardcodes 1001.
- Inference API stays single-image: `POST /session/infer` = one file → one result. Multi-image runs = browser loops sequentially (board has one importer; requests serialize anyway). No batch endpoint, no zip upload. ponytail: add multi-file scp when a demo set exceeds ~50 images.
- Ground truth is optional and lives in the filename: `<category>_<anything>.<ext>`, `<category>` matched case-insensitively (spaces → `_`) against the live model's `categories.txt`. Browser computes top-1/top-5 accuracy over labeled files only; unlabeled files get top-5 + latency. No server-side label handling.
- Which model is live is backend state (set at deploy). Every result JSON returned to the browser carries `model` so rows can't be mislabeled across a switch.
- Board never receives IR or a user-made graph.bin. Only `dlac` output from the host. (graph.bin drives DMA on identity-mapped F2SDRAM with no IOMMU.)
- Arch = `AGX5_Nano_k32c16_sb12883` (stream_buffer_depth 12288→12883 vs stock k32c16; board-confirmed 2026-09-04: 6.1574 FPS IP / 3.0131 FPS system / 331.9 ms latency, +9.6%/+9.3%/−8.5% vs k32c16; already flashed on board). Softmax stays as the CPU submodel already inside the compile. No further arch/bitstream change.
- Two Mender module types:
  - `coredla-runtime` — rare: sdklibs + OpenVINO/OpenCV libs + dla-server (~675 MB).
  - `coredla-model` — per deploy: rbf + overlay.dtb + .arch + graph.bin + categories.txt (~150 MB).
- Inference traffic never goes through Mender.
- Board-side inference = new small persistent C++ server. Shipped `streaming_inference_app` needs an S2M bitstream; `classification_sample_async` cannot build for HPS (`DISABLE_JIT`); `dla_benchmark` pays 76 s import per process; no pyopenvino for aarch64.

## Phase 0 — Mender onto CoreDLA SD

1. Mount lab SD on host; copy `/usr/share/mender/modules/v3/fpga-reconfig`, `my_overlay.dts`, `/etc/mender/mender.conf`. Read the module fully.
2. CoreDLA SD: install `mender-client4` (arm64 deb, Ubuntu 22.04 rootfs), point at `mender.example.ts.net`, accept device in Mender UI. Blacklist `altera-msgdma`, `msgdma_userio` autoload.
3. Test live reconfig on the CoreDLA kernel using the `coredla-fpga-up.sh` flow (rmmod → configfs overlay → wait `fpga0/state == operating` → modprobe chain) → `dla_benchmark` passes.
   - Fail → fallback: module copies rbf to the FAT partition + `NeedsArtifactReboot: Automatic`. Proven U-Boot `fatload`/`fpga load` path, ~1 min per deploy.
4. Overlay: widen `ranges` past `0x20000` and add coredla0/msgdma child nodes, or keep DLA nodes in base dtb and overlay only `firmware-name`. Pick whichever step 3 shows works.

**Verify:** Mender deploys idle GHRD rbf → deploys DLA rbf → `dla_benchmark` passes, no panic; failed deploy rolls back to previous rbf.

## Phase 1 — one fixed demo model (fruit), images in → labels + accuracy out

**Status 2026-09-17: built and verified on the ImageNet fallback** (1.0 could not run: no fruit/flag IR or checkpoints exist on the host). What differs from the text below: dla-server lives in this repo (`dla-server/`), not `~/coredla_work/runtime/`; the runtime payload is 72 MB, not 675 MB (only the libs dla-server actually loads); model artifacts are prebuilt + pre-uploaded, so the backend deploys by artifact name (`deploy_existing`) and `build_artifact()` is unchanged; ssh is multiplexed (0.48 s/image, of which 332 ms is the IP). Idle design is now the classifier, not GHRD: release redeploys the model artifact only if the session programmed its own rbf. Measured: import 69 s, 96 MB RSS steady after 100 images, top-1 = host CPU plugin 10/10 on the sample set.

0. **Demo model prep (host, by hand):** fruit IR → `dla_compiler --march AGX5_Nano_k32c16_sb12883.arch --network-file model.xml --foutput-format dla_compiled_result --o graph.bin --fdisplay-device` → confirm output tensor `[1,N_fruit]` and `categories.txt` has N_fruit lines → smoke-run on `plugins_emulation.xml` with one image. Run the same IR on the OpenVINO CPU plugin over the demo test set; save top-5 per image (reference oracle for Verify). Fail → phase 1 falls back to shipped `resnet50_sb12883.bin` + 1001-line ImageNet `categories.txt`; custom-FC compile becomes a phase 2 item.
1. **dla-server** (C++, new target in `~/coredla_work/runtime/`): copy `dla_benchmark` `-cm` import (`dla_benchmark/main.cpp:960-990`) + `streaming_inference_app` top-5/categories code, but N = line count of `categories.txt` (assert == output dim; drop the 1001 assumption). Loop: inotify/poll `inbox/`, resize to 224×224 u8 NCHW (as `inputs_filling.cpp`), infer, write JSON, move image to `done/`. Free file buffers after import. systemd service, restart on failure.
2. **coredla-runtime** module: dir-overlay pattern, unpacks to `/opt/dla/`, restarts dla-server.
3. **coredla-model** module: rmmod → rbf → overlay → modprobe → swap graph.bin + categories.txt → restart dla-server. Rollback = previous set.
4. **lab-backend**: `POST /session/infer` (one image, ≤ 2 MiB, jpg/png/bmp) → scp to inbox → poll result via ssh → return JSON + `model`. `GET /session/model` → `{name, categories}` (frontend needs the list for filename labels). Raise bundle size cap (`MAX_RBF_BYTES` 8 MiB) and `poll_until_finished` (300 s → ~900 s). `build_artifact()` gains `-T <type>` + N × `-f`.
5. Frontend: multi-file picker → "Run inference" → sequential `POST /session/infer` per file → one table row per image (thumbnail, top-1, top-5 bars, latency ms, ✓/✗ when filename-labeled) + summary line (model, n, mean/max latency, top-1/top-5 accuracy over labeled files).

**Verify:** fruit demo test set (≥ 10 filename-labeled images) via browser: per-image top-1 matches the host CPU-plugin run from 1.0; accuracy summary matches a hand count; an unlabeled file shows a row without ✓/✗ and is excluded from accuracy; server survives 100 sequential images without RSS growth; second image returns < 1 s.

## Phase 2 — model catalog

**Status 2026-09-17: done.** Catalog is `config.MODEL_CATALOG` in lab-backend (env-overridable, artifacts `coredla-model-{fruit-25779ed3,flag-6cdf79d1,imagenet-016647b1}` on the Mender server). Switch goes through the queue loop like `program()` (mutually exclusive with it); `model_state`/`model_error` on `/session/status`; `infer` results read `model` off the board in the same ssh, so the name can't lag. Release after a user `.rbf` redeploys the last chosen model, not always fruit.

1. Precompile the flag graph exactly as 1.0 (fruit already done). Catalog = {fruit, flag, imagenet (shipped graph)}, one `coredla-model` artifact each with its own `categories.txt`.
2. Backend: `GET /session/models` lists catalog; `POST /session/model {name}` → deploy; `GET /session/model` reflects the switch. Frontend: model picker + "deploying…" state (~150 MB over Tailscale, minutes).

**Verify:** fruit → flag → fruit remotely via browser; flag test set scores only under flag, fruit set only under fruit; `GET /session/model` categories change; result rows carry the right `model`; no brick; msgdma back each time.

## Phase 3 — user weights upload

**Status 2026-09-18: done.** Export kit = `training/` (`train.py` + `export.py`, pinned openvino 2024.6 `convert_model`, preprocessing baked in via `common.Deploy`). Backend `POST /session/model/upload` + `lab-backend/model_upload.py` (structural xml diff vs the fruit reference, N from `categories.txt`, `model.bin` size formula) → `artifacts/build-user-model.sh` in the queue loop (CPU-plugin smoke stands in for the emulator, which has no x86 build) → catalog + deploy. Verified: flag IR re-uploaded as `my-flags` reproduces the catalog flag results on the board; extra-layer xml and N±1 rejected.

1. Export kit: notebook/script — load resnet-50-tf, replace FC (N classes), train, `ovc` pinned version, fixed preprocessing (RGB, mean/scale). Emits `model.bin`, `model.xml`, `categories.txt`. Flag and fruit IR + `categories.txt` are the reference inputs for this phase.
2. Backend `POST /session/model/upload` (`model.xml` + `model.bin` + `categories.txt` + name): validate `.xml` == reference except FC dims; N == lines in `categories.txt`; run the 1.0 dlac compile + emulator smoke-run; bundle; add to catalog under the given name; deploy. Queue — one compile at a time.
3. Reject paths: xml mismatch, class-count mismatch, dlac failure, emulator failure → clear error to user, nothing deployed.

**Verify:** fruit IR + `categories.txt` uploaded via browser → same per-image results as the catalog fruit entry on the same test set; flag likewise; a fresh export-kit fine-tune classifies held-out images on board; xml with extra layer rejected; `categories.txt` with N±1 lines rejected.

## Risks

- Live configfs reconfig on CoreDLA kernel unverified → fallback ready (phase 0.3).
- Import 76 s + ~475 MB peak RSS on 683 MB usable → dla-server restarts only on model change, never per request. Never two importers at once.
- dlac compile = minutes per user upload → queue + progress state in UI.
- dlac on a custom-FC IR unproven until phase 1.0 → ImageNet fallback keeps phase 1 shippable.
- Flag/fruit models may not be IR yet → one-off export-kit conversion (pinned `ovc`) before 1.0; preprocessing must match dla-server (RGB 224×224, mean folded into the graph).
- 150 MB per deploy over Tailscale relay → longer poll timeout; show progress.

## Order

0 → 1 is the demo (fruit model, upload images, accuracy). 2 adds fruit ↔ flag switching = "edge AI". 3 turns "upload trained model" from a catalog pick into a real user action — stretch goal; state so in the FYP writeup.
