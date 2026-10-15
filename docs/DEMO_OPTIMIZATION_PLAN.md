# Demo optimization plan (hardware + software)

Status 2026-09-28: **closed.** Aspects 1-6 done (each section has its result), 7 not needed.

| # | Aspect | Result |
|---|---|---|
| 1 | Browser live view | already paints every frame (28.5 fps); no change |
| 2 | USB webcam | 10 -> 29-30 fps (ustreamer `--desired-fps=30`) |
| 3 | MIPI live view | 28.5 -> 29.7 fps at 480x270, two-stage display loop, torn-frame glitch fixed |
| 4 | DLA inference | ~4 -> ~9 Hz: fruit, flag (distilled) and imagenet on ResNet-18 |
| 5 | Model switch | ~2-2.5 min -> ~25 s (smaller graphs, direct Ethernet) |
| 6 | Robustness | backend systemd unit, board dla-server watchdog, memory flat |
| 7 | USB kernel options | not needed (webcam at 29-30 fps) |

Naming (after closing, 2026-09-28): the GUI highlights the live model by matching the board's
`name` file to the catalog key, so the ResNet-18 models were made canonical: `models/{fruit,flag,
imagenet}/` now hold them (name = key), artifacts `coredla-model-fruit-7580298c`,
`coredla-model-flag-73107bc0`, `coredla-model-imagenet-9e0571d4` (same graphs as the
`*-resnet18-*` artifacts named below). Training default is ResNet-18 (`--arch resnet50` =
`runs/<name>-resnet50`, the old runs; the flag teacher is `flag-resnet50`).

Original plan below: each aspect had a baseline, a goal, steps with a check, and a rollback.

## Baseline (measured 2026-09-28, board on direct Ethernet to lab PC)

| What | Measured | Where |
|---|---|---|
| MIPI frames written on board | 28.5 fps, gap 36 ms p50/p95/max, ~10.7 KB, 480x270 q80 | `results/live.jpg` mtimes |
| MIPI frames shown in browser | not measured (GUI fps counts board write times, not arrivals) | `static/app.js` `liveStream()` |
| USB webcam (ustreamer) | captured 9 fps, desired 15, 640x480 MJPEG, HW encoder (now 29-30 fps, aspect 2) | `curl :8080/state` |
| DLA live classification | ~4.2 Hz (~230 ms), `AGX5_Small_k16c16_sb20480`, IP estimate 4.94 fps | live.json `infer_fps` |
| Board CPU | dla-server 200 %, tailscaled ~24 %, load 2.8 | `top` |
| Board memory | 683 MB total (`mem=768M`), 210 MB in swap | `top` |
| Model switch | ~2.5 min: ~15 s poll, ~50 s download (DERP era), ~10 s reprogram, ~62 s graph import (141 MB ResNet-50) | Mender deploy |

## Order

| # | Aspect | Payoff | Effort |
|---|---|---|---|
| 1 | MIPI live view transport | smooth 28 fps picture | small (backend + app.js) |
| 2 | USB webcam frame rate | 9 fps toward 15 | small (board config) |
| 3 | MIPI picture resolution | sharper picture | small (one constant + measure) |
| 4 | DLA inference rate | 4.2 Hz upward | medium (dla-server) to large (retrain) |
| 5 | Model switch time | 2.5 min downward | small (measure) to medium |
| 6 | Service robustness | fewer manual restarts | small |
| 7 | USB kernel (DDMA / passthrough) | fewer lost frames, wedge risk | large, optional |

---

## 1. MIPI live view transport

Status 2026-09-28: **closed after step 1, no change needed on the lab PC.** Measured over 15 s:

| Stage | Rate | Gap p50 | p95 | max |
|---|---|---|---|---|
| Board writes `live.jpg` | 28.5 fps | 36 ms | 36 | 40 |
| Arrival at backend (`board_infer.live_stream()`) | 28.5 fps | 33 ms | 43 | 48 |
| Painted in browser (headless Firefox on lab PC, `demo/probe_live_view.py`) | 28.5 fps | 32 ms | 43 | 49 |
| Browser animation frames (main-thread health) | 60/s | 17 ms | 17 | 17 |

Every frame reaches the screen and the main thread never stalls, so steps 2-5 (MJPEG
endpoint) are skipped. Re-run `demo/probe_live_view.py` if the GUI is shown from a
different machine (weaker laptop, or remote over Tailscale) and reopen this aspect if
painted p95 goes above ~60 ms or animation max above ~50 ms.

**Problem.** The board side is steady (36 ms gaps). Each frame then goes: board Python
polls `live.jpg` every 10 ms, ssh stdout, backend base64-encodes it into JSON, SSE,
browser `JSON.parse`, `<img src="data:...">` swap. Per frame that is a ~15 KB string
parse plus a main-thread JPEG decode, 28 times a second, so the browser can show bursts
and dropped frames.

**Goal.** Browser arrival gaps close to the board's (p95 under ~60 ms), no visible judder.

**Steps.**
1. Measure first: in `liveStream()` log `performance.now()` gaps between `frame` events
   for ~10 s; print p50/p95/max. If already tight, stop here.
   Check: numbers recorded in this doc.
2. Add backend `GET /session/camera/mjpeg?job_id=` returning
   `multipart/x-mixed-replace; boundary=frame`, reusing `board_infer.live_stream()` and
   `_live_gate()`, writing the raw JPEG bytes (no base64).
   Check: `curl -N` shows `--frame` parts at ~28 per second.
3. Point the hero `<img>` at the MJPEG URL while live. Keep the SSE stream for the
   classification only, and stop sending `image` in it (tiny events).
   Check: step 1 measurement again, plus eyeball.
4. The GUI fps counter moves from SSE frames to the classification stream or is fed the
   frame count some other way (decide during the work; the MJPEG `<img>` exposes no per-frame event).
5. Update `test_main.py` for the new endpoint.

Cheaper fallback if step 2 is not wanted: keep SSE, but `await img.decode()` (or
`createImageBitmap` into a canvas) before swapping frames, and drop frames that arrive
while a decode is pending.

**Rollback.** Frontend change only switches the `<img>` source back; old endpoint stays until the new one is proven.

## 2. USB webcam frame rate

Status 2026-09-28: **done, 10 to 29-30 fps.** The steps below were the plan; the actual
cause was different:

- Not exposure: manual 10 ms exposure gave the same 10-11 fps as auto (camera has no
  `exposure_auto_priority` control anyway; `Auto Exposure` 3 = aperture priority).
- Not USB: a 5 s uvcvideo trace (`trace=0x480`) showed 152 `Frame complete` (~30 fps)
  and only 4 lost isochronous packets. The camera was already sending 30 fps.
- Cause: ustreamer `--desired-fps=15`. The camera only offers 30/25/20 fps, the driver
  coerced 15 to 20, and ustreamer then kept only ~10 of the ~30 frames it received.
- Fix (board only, not in the repo): `/etc/systemd/system/ustreamer.service.d/override.conf`
  `--desired-fps=15` changed to `--desired-fps=30`. Old file: `~terasic/ustreamer-override.conf.bak`.
  Full line: `ExecStart=/usr/bin/ustreamer --device=/dev/video0 --host=0.0.0.0 --port=8080 --format=MJPEG --resolution=640x480 --desired-fps=30 --drop-same-frames=30`
- Result: captured 28-30 fps over a 10 min soak; a client received 350 frames in 12 s
  (~29 fps, ~45 KB each, ~1.3 MB/s); 0 SMMU `event 0x10` / `AHB ERROR` / uvc `-110`;
  ustreamer never restarted. USB load is unchanged (same 30 fps on the wire as before).
- Tool left on the board: `/tmp/uvcctl.py` (lists UVC controls and MJPEG frame rates,
  `uvcctl.py "<control>" <value>` sets one; board has no `v4l2-ctl`). Lost on reboot.

**Problem.** ustreamer captures 9 fps against 15 desired. Lost isochronous frames are down
to ~0.8/s since the dongle was removed, so USB loss is probably no longer the limit. Most
likely suspect: auto exposure lowering the frame rate in dim light (UVC
`exposure_auto_priority` / `exposure_dynamic_framerate`).

**Goal.** Steady 15 fps captured in demo lighting.

**Steps.**
1. Test the lighting hypothesis for free: shine a lamp at the webcam and watch
   `captured_fps` in `curl -s coredla:8080/state`.
   Check: fps rises with light means exposure is the limit.
2. The board has no `v4l2-ctl`. Get it (package or cross-built static binary) or a
   20-line `VIDIOC_S_CTRL` Python/ctypes script.
3. List controls; set `exposure_auto_priority=0` (or manual exposure) and pin the value in a
   `ExecStartPre=` of the ustreamer drop-in so it survives reboots.
   Check: 15 fps captured for 10 min, `dmesg` free of `-63` bursts and SMMU `event 0x10`.
4. If still short: count `-63` per second again; if loss is back up, go to aspect 7.

**Rollback.** Remove the `ExecStartPre=` line.

## 3. MIPI picture resolution

Status 2026-09-28: **done, stayed at 480x270 by choice (stability over sharpness).**
What shipped in `dla-server/main.cpp` (hand-installed on the board at `/opt/dla/dla-server`,
previous binary `/opt/dla/dla-server.pre-aspect3`; not Mender-deployed):

- Display loop is now two stages on the A76s: stage one copies the newest ring slot out
  of uncached memory (~28 ms, one core); stage two debayers, hands the frame to inference
  and writes `live.jpg` (~9 ms at 480x270, ~20 ms at 960x540). They overlap, so the copy
  alone sets the rate.
- `DLA_LIVE_DECIM` env knob (default 2 = 480x270; 1 = 960x540).
- Live JPEG uses `JDCT_IFAST` (9.6 to 8.4 ms at 960x540).

Measured stage times (single-threaded, before the pipeline):

| Stage | 480x270 | 960x540 |
|---|---|---|
| Copy 4 MB uncached ring | 28.2 ms | 28.4 ms |
| Debayer | 6.2 ms | 11.5 ms |
| JPEG q80 | 2.5 ms | 9.5 ms |
| Total | 37.5 ms | 50.0 ms (19.9 fps) |

Torn frames (colour-phase slips, counted on every frame over 20-40 s with a
per-frame mean R-B outlier test):

| Build | Picture | fps | Torn | DLA Hz |
|---|---|---|---|---|
| Before (single thread) | 480x270 | 28.5 | 0.2 % | 4.0 |
| Copy split across both A76s | 960x540 | 26-28 | 6.5-7.3 % | 3.6-3.8 |
| Single copy, no pipeline | 960x540 | ~19 | 0 % | 4.0 |
| Pipeline | 960x540 | 27.9 | 0.7 % | 3.8 |
| **Pipeline (shipped)** | **480x270** | **28.9** | **0.3 %** | **3.9** |

**Lesson: never read the camera ring from two cores at once.** Splitting the uncached
copy across both A76s only sped it up 28 to ~18 ms (the interconnect, not the core, is
the limit) and starved the camera mSGDMA of DDR bandwidth: it dropped lines and ~7 % of
frames came out shifted with the wrong Bayer phase (user saw the GUI glitching). A real-time
capture thread with 100 us DMA polling did not help (7.3 %), so arming latency is not the
cause. The remaining ~0.2-0.3 % torn frames predate this work; removing them needs DMA/fabric
work (e.g. a frame-start aligned descriptor or a larger camera FIFO), not logged as an aspect.

Soak of the shipped build (10 min, every frame checked): 17,802 frames = 29.7 fps, 0.2 %
torn (40, same as the old binary), 0 ring overruns, DLA 3.97 Hz, dla-server RSS 76 MB,
0 SMMU / AHB / `-110` events, dla-server and ustreamer active throughout.

**Problem.** 480x270 q80 (~11 KB) was sized for the old 1.6 MB/s Tailscale relay. The
board now reaches the PC directly (1 ms). On a projector 480x270 looks soft.

**Constraint.** The display thread (pinned to the A76s, cpu2-3) does the uncached ring
copy + debayer + encode in ~32 ms of its 36 ms budget. The same `rgb` frame is also the
inference input (centre-cropped and resized to the graph input), so a bigger frame also
costs a little in the inference loop.

**Goal.** 960x540 (or 640x360 if 960x540 does not fit) at the same ~28 fps.

**Steps.**
1. Time the display loop stages (copy, debayer, encode) with `steady_clock` at the
   current size; log once per second.
2. Change `DECIM` (or add a separate display size) to reach 960x540; re-time.
   Check: write rate still ~28 fps (same `live.jpg` mtime script as the baseline), inference Hz unchanged.
3. If over budget: drop to 640x360, or encode at lower quality, or split debayer and
   encode across the two A76 cores.

**Rollback.** Revert the constant; runtime rebuild + redeploy (hand-install or Mender, see
`camera-migration` notes on which runtime is live).

## 4. DLA inference rate

Status 2026-09-28: **measured; software steps dropped; backbone swap awaits a decision.**

Findings:
- `latency_ms` in live.json times `req.infer()` alone: ~245 ms of the ~252 ms period.
  Preprocessing + post-processing are ~10 ms, so pipelining them (steps 2-3) is worth
  at most ~4 %. Dropped.
- `infer()` is FPGA-bound: moving the inference thread from an A76 to an A55 (`taskset`)
  left latency unchanged (245 vs 248 ms). Its ~97 % CPU is the plugin busy-waiting.
- The backbone is the only lever (the arch cannot grow, see step 4). Compiler estimate
  (`dla_compiler --fanalyze-performance`, same arch, its assumed 350 MHz) and a real
  board run of untrained 16-class graphs in a temporary dla-server:

| Backbone | Estimate | Board latency | Board live Hz | graph.bin | Import on board | All layers on FPGA |
|---|---|---|---|---|---|---|
| ResNet-50 (now) | 16.8 fps | 245 ms | 3.9-4.0 | 141 MB | 62-75 s | yes (softmax on CPU) |
| ResNet-34 | 22.5 fps | not run | ~5 (scaled) | not built | not run | not checked |
| ResNet-18 | 44.5 fps | 98 ms | 9.4 | 68 MB | 14 s | yes (softmax on CPU) |
| MobileNetV2 | 120 fps | 48 ms | 16.8 | 16 MB | 1.9 s | yes (softmax on CPU) |

A smaller backbone also shrinks graph import and download, which is most of aspect 5.
Open questions before switching: accuracy on the robust-retrain test sets (fruit/flag,
MIPI-captured conditions), and the fine-tune notebook (`make_notebook.py`,
`static/fruit-v1.pt`) is built on ResNet-50. Test IRs/graphs live only in the session
scratchpad; board copies in `~terasic/mtest/` (safe to delete).

**Bake-off (fruit, 2026-09-28).** `train.py`/`export.py` gained `--arch resnet18|mobilenet_v2`
(writes `runs/`/`models/fruit-<arch>/`, the live `fruit` is untouched). Same recipe as
ResNet-50 otherwise; held-out = 30 photos never trained on:

| Model | Epochs | Val top-1 | Held-out | Sim | None recall | Demo images CPU | Board == CPU | Board |
|---|---|---|---|---|---|---|---|---|
| ResNet-50 (live) | 15 | 97.7 % | 28/30 | 26/30 | 0.95 | 48/50 | yes | 245 ms, 3.9 Hz |
| ResNet-18 | 15 | 96.0 % | 23/30 | 22/30 | 0.97 | not run | not run | not run |
| MobileNetV2 | 15 | 94.8 % | 24/30 | 22/30 | 0.88 | not run | not run | not run |
| **ResNet-18** | **30** | **97.2 %** | **27/30** | **25/30** | **0.95** | **46/50** | **50/50** | **~97 ms, 9.2 Hz, import 6 s** |
| MobileNetV2 | 30 | 96.3 % | 23/30 | 24/30 | 0.90 | not run | not run | not run |

ResNet-18 at 30 epochs is within noise of ResNet-50 (one photo per check, two demo
images) at 2.4x the live rate; MobileNetV2 dropped. `models/fruit-resnet18/` is built
(graph.bin 64 MB).

**Adopted for fruit (2026-09-28):** `coredla-model-fruit-resnet18-7580298c` (60 MB artifact) is
the catalog `fruit` (lab-backend `config.py` default, `artifacts/reset.sh` default, README,
RUNBOOK, training/README). Board: model name `fruit-resnet18`, 98 ms, 9.1-9.3 Hz live,
graph import 8.5 s. Rollback: `MODEL_CATALOG` / `reset.sh coredla-model-fruit-eec306c8`
(ResNet-50, still on the Mender server).

**Flag stays ResNet-50 for now.** ResNet-18, 30 epochs, `--no-flip`: val 97.8 % (R50 98.0),
held-out fabric 68/90 (71), **camera/screen sim 56/90 (66)**, none 36/40 (34/40), CPU demo
images 86/110 (88). The sim drop is the demo-relevant one. `models/flag-resnet18/` is
exported, not compiled.

**Flag training experiments (ResNet-18, 30 epochs, `--no-flip`; held-out = 90 Commons fabric
flags, out of scope; sim = the same photos through the camera/screen simulation):**

| Run | Held-out | Sim | None recall |
|---|---|---|---|
| ResNet-50 (live teacher) | 71 | 66 | 34/40 |
| baseline, 2 runs | 68, 66 | 56, 60 | 36, 36 |
| `--sim-p 0.5` | 65 | 63 | 37 |
| `--teacher flag` (distillation), 2 runs | 71, 66 | 66, 62 | 34, 38 |
| **`--teacher flag --sim-p 0.5`** | **68** | **66** | **37** |

Distillation from the ResNet-50 flag model (T=4, weight 0.7) is the lever (+6 sim on
average); with the heavier simulation it matches ResNet-50 on sim. Chosen run exported and
compiled (`models/flag-resnet18/`, graph 67 MB): CPU demo images 86/110 (R50 88; flags 68/90
vs 71, none 18/20 vs 17). **Board: == CPU 101/110 (R50 101), == truth 79/110 (R50 85)**,
~96 ms, import 6.4 s: the small net loses a few more fabric photos to FPGA precision. **Adopted 2026-09-28** (user: accuracy is not
the project's main metric) as `coredla-model-flag-resnet18-73107bc0`: deploy 25 s, 98.7 ms, 9.4 Hz live. Rollback: the
ResNet-50 `coredla-model-flag-60483e80`.

Notebook (`make_notebook.py`, `static/fruit-v1.pt`) unchanged, still ResNet-50. **Moved to ResNet-18
2026-09-28** (`train.py fruit-v1 --epochs 2 --no-sim` on the notebook's split, R50 run kept as
`runs/fruit-v1-resnet50`): notebook 13/30 → 29/30 (val 40 % → 88 %), upload→live 45 s (was ~2.5 min),
import 14.9 s, 9.9 Hz; lab-backend upload reference + bin-size check (FC 513 floats/class) follow.

**ImageNet (2026-09-28):** torchvision ResNet-18 (no training, `training/export_imagenet.py`,
same `Deploy` wrapper, 1000 labels, graph 70 MB) is the catalog `imagenet` as `coredla-model-imagenet-resnet18-9e0571d4`:
deploy 25 s, import 6.8 s, 99 ms, 9.3 Hz live; board == CPU 8/10 on fruit demo images (the two
misses are low-margin: kiwi, a none scene). ImageNet top-1 ~70 % vs ~76 % for ResNet-50.
Rollback: `coredla-model-imagenet-ec18177a` (stock resnet-50-tf). All three catalog models
are now ResNet-18.

**Problem.** Live classification runs ~4.2 Hz against a 4.94 fps IP estimate. The loop
is fully serial: pick newest frame, RGB to BGR, crop + resize + convert, `req.infer()`
(HETERO:FPGA,CPU, so part of the graph runs on the CPU), post-process, write JSON. The
FPGA sits idle during the CPU stages.

**Goal.** Close the gap to the IP rate first (software), then decide on the backbone.

**Steps.**
1. Time the stages of one live iteration (preprocess, `infer()`, post-process) and
   record here. Check whether `infer()` itself is ~200 ms or the CPU stages are large.
2. Remove easy waste: the RGB to BGR `cvtColor` exists only because `classify()` takes
   BGR; feed RGB straight in for live frames.
3. Pipeline: two infer requests with `start_async()`; preprocess frame N+1 while frame N
   runs on the DLA. Pin the inference thread to the A55s (cpu0-1) so it does not steal
   from the display thread.
   Check: `infer_fps` in live.json near the `infer()`-only rate; display still ~28 fps.
4. Bigger lever, separate decision: a smaller backbone (ResNet-18 / MobileNet-class)
   retrained with the existing training pipeline. Faster inference AND a much smaller
   `graph.bin` (helps aspect 5). Needs accuracy re-check against the robust-retrain test
   sets. The FPGA arch cannot grow: M20K is 355 of 358 next to the camera IP (only
   reserve: OCM 32768 to 4096 frees 14 M20K).

**Rollback.** dla-server binary `.bak` on the board.

## 5. Model switch time

Status 2026-09-28: **largely solved by aspect 4 for fruit.** Uploading + deploying the
60 MB ResNet-18 fruit artifact with `artifacts/mender-deploy.sh` took **27 s** end to end
(board on direct Ethernet; graph import 8.5 s), against ~2-2.5 min for ResNet-50 over the
old DERP relay. Flag / imagenet (ResNet-50, ~141 MB graphs) not re-measured on Ethernet.

**Problem.** ~2.5 min per switch, measured when the download ran over the DERP relay.

**Steps.**
1. Re-measure one full deploy now that the board is on direct Ethernet; split into poll,
   download, reprogram, import. Check: new numbers recorded here.
2. Graph import (~62 s for 141 MB) scales with graph size: aspect 4 step 4 is the lever.
3. Poll is already 5 s; reprogram (~10 s) must stay (skip-reprogram hung the board once).
4. Optional, larger: keep every demo model's artifact cached on the board so a switch
   skips the download. Only worth it if step 1 still shows download as the big share.

## 6. Service robustness

Status 2026-09-28: **done.** Memory soak (20 min, ResNet-18 fruit live): dla-server RSS flat at
155 MB, available 268-282 MB, swap 52-54 MB (was 210 MB with the ResNet-50 imports).

- **Backend = systemd unit `lab-backend`** (PC, enabled at boot). Unit file + install lines in
  `~/mender/lab-backend/lab-backend.service`; Mender creds + `DEVICE_ID` in `lab-backend.env`
  next to it (mode 600, gitignored). `Restart=on-failure`: `kill -9` -> back in ~3 s.
  `artifacts/reset.sh` now stops/starts the unit (sudo, passwordless on this PC), reads creds
  from the env file, and passes `SESSION_SECONDS` via `systemctl set-environment`.
- **Shutdown hang fixed:** `--timeout-graceful-shutdown 3`; a restart with a live camera SSE
  stream open (1.6 MB streamed) took 0.2 s.
- **Board watchdog** `board/dla-watchdog.{sh,service,timer}` (installed + enabled, also in
  `board_setup.sh`): every 30 s, if `live.jpg`'s mtime does not change over 10 s, try-restart
  dla-server. Skips when dla-server is inactive, < 60 s old, in file-only mode (no live.jpg),
  or while a Mender module / `coredla-fpga-up.sh` runs. Tests: healthy -> untouched; SIGSTOPped
  dla-server -> restarted, live again at 9.2 Hz; two Mender model switches with the timer armed
  -> no restart. ustreamer not watched: it already reopens the camera itself.

**Steps.**
1. lab-backend as a systemd service on the PC: `EnvironmentFile=` with the `MENDER_*`
   variables (mode 600), `Restart=on-failure`. Check: `systemctl restart` brings the GUI back.
2. Fix the shutdown hang on open SSE streams (today a second SIGINT is needed): e.g.
   uvicorn `--timeout-graceful-shutdown 3`.
3. Board watchdog: a systemd timer that restarts `dla-server` when `live.jpg` is older
   than ~10 s while a camera model is staged and not importing, and ustreamer when
   `/state` reports `online: false` for ~30 s. Check: kill each process, watch it recover.
4. Memory: 210 MB already in swap at 683 MB total. Log dla-server RSS over a 1 h soak;
   look for growth.

**Rollback.** Disable the units; manual launch still works.

## 7. USB kernel options (optional)

Status 2026-09-28: **closed, not needed** (aspect 2 reached 29-30 fps). Kept for reference.

Untried levers from `docs/USB_WEBCAM_DWC2_FIFO.md`: dwc2 host descriptor DMA (hardware
supports it, currently off) and `iommu.passthrough=1`. Both need a kernel/bootargs change
and a >=15 min soak with the webcam attached (the SMMU wedge showed up anywhere from 38 s
to 532 s). Keep the current `Image` / dtb as rollback, and have serial access
(`/dev/ttyUSB0`) ready before rebooting.
