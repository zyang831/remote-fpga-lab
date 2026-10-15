# Replicating the remote FPGA lab

Start here. Details live in `docs/guides/`. Files that cannot be published are listed with hashes in `NOT_INCLUDED.md`; every such file has a rebuild path below. Secrets are never in this repository: see "Secrets".

## 1. What you need
Hardware: Terasic DE25-Nano (Agilex 5), microSD (32 GB or more), USB or MIPI camera as in the guides, lab PC (we used an i9-14900K, 62 GB, Ubuntu 24.04), Ethernet cable (direct link works; the Mender server is reached over Tailscale).
Licensed tools you obtain yourself: Quartus Prime Pro 25.3.1, Altera FPGA AI Suite 2025.3.1 (includes OpenVINO 2024.6 runtime and the Yocto SDK recipe), Terasic DE25-Nano resource package. Public: Mender server and client 5.1.0, Tailscale, Docker, Python 3.12.
Versions measured: see `evidence/data/env.md`.

## 2. Build order
1. **Fabric design.** Follow `docs/guides/DE25_COREDLA_RUNBOOK.md` Phase 1: take the Terasic GHRD, add the CoreDLA IP, camera front end and mSGDMA with `hardware/scripts/*.tcl` and `hardware/custom_ip/`, compile in Quartus. Output: `*.core.rbf` plus device-tree overlay `.dtbo` (sources in `board/overlay_*.dts`). Our design's file hashes: `NOT_INCLUDED.md`.
2. **SD image.** `docs/guides/SDCARD_IMAGE_GUIDE.md` and `STEP2_BSP_BUILD_GUIDE.md`; kernel patches in `bringup/patches/`, mSGDMA user-IO kernel module in `bringup/kernel-module/`, u-boot scripts in `bringup/boot/`.
3. **Runtime and model compiler.** `STEP3_RUNTIME_BUILD_GUIDE.md`, `YOCTO_SDK_BUILD_GUIDE.md`, then `dla-server/build.sh` (cross-compiles the inference server; needs the runtime package from step 3). The MMD patch against the vendor runtime is not published: apply the change described in RUNBOOK Phase 3 ("MMD: no device").
4. **Models.** `models/fruit-v1` and `models/flag` hold the OpenVINO IR (ResNet-18 weights, 16 and 31 classes) and `categories.txt`. Compile to the DLA with the AI Suite compiler (`artifacts/build-model.sh`, arch `AGX5_Small_k16c16_sb20480`, see NOT_INCLUDED.md). To train your own: `training/README.md`, `training/train.py`, `training/export.py`.
5. **Board services.** Copy `board/` units and scripts as in `STEP4_INFERENCE_GUIDE.md` and `board/board_setup.sh`: `coredla-fpga`, `dla-server`, `dla-watchdog`, Mender update modules `coredla-model`, `coredla-runtime`, `fpga-reconfig`, `mender.conf` (set your server URL).
6. **Mender + Tailscale.** `docs/guides/MENDER_OTA_TAILSCALE_GUIDE.md` (server, tenant-less open-source setup, client config, Tailscale auth keys). Build the first artifacts with `artifacts/deploy.sh`, `build-model.sh`.
7. **Lab backend.** `backend/`: Python 3.12 venv, `pip install fastapi uvicorn httpx python-multipart pillow`, copy `lab-backend.env.example` to `lab-backend.env`, fill it, install `lab-backend.service` (edit paths/user). Tests: `pytest backend/test_main.py`. Web UI is served by the backend on port 8000.

## 3. Reproduce the measurements
`evidence/` contains the exact scripts and our raw per-run CSVs (`evidence/data/*/runs.csv`). Run them from `evidence/` with the backend up and the board on the fruit classifier: `python3 harness.py env` (records environment), `python3 harness.py offset` (board-PC clock offset), `python3 run_D2.py model 40`, `python3 run_D2.py bit 24`, `python3 run_D3.py model 10`, `python3 analyze_D3.py model`; CPU baseline: build `evidence/cpu_bench` with the Yocto SDK (see `run_D6.py`), `python3 run_D6.py 150`; flag analysis: `analyze_flags.py board|cpu|compare` with images from `data/flag-images/`. Paths at the top of each script point at our machine layout (`/home/<user>/...`): edit them. The bitstream paths in `run_D2.py` need your own `.core.rbf` files (replace by your designs; the hashes of ours are in NOT_INCLUDED.md). Expected results with their spread: `evidence/data/*/summary*.md` and `docs/guides/PAPER_RESULTS_REPLICATION_GUIDE.md`. Your numbers will differ with network, board and poll interval; compare medians and ranges, not single runs.

## 4. Sanity checks
- Board shows up as a device in Mender; `systemctl is-active dla-server` is active and stays active for 10 minutes (we saw a crash loop every ~49 s when a stale model graph was installed; redeploying the model fixed it, cause not isolated).
- `curl localhost:8000/session/model` returns the model name and categories.
- A model switch via the web UI finishes in about 25-30 s on a direct link (median 27 s, n=40).

## 5. Secrets and local settings (not in the repository)
- `backend/lab-backend.env`: Mender URL, account, password, device ID. Template: `backend/lab-backend.env.example`.
- Board account password: the guides use a placeholder `<BOARD_PASSWORD>`. Our board image shipped with a weak default; set your own and use SSH keys.
- Tailscale auth key and Mender admin credentials: created in your own consoles (guide shows where); never commit them.
- Wi-Fi/eduroam credentials in `STEP5_WIFI_DONGLE_GUIDE.md` are placeholders.
- Our tailnet host names and IPs were replaced by `mender.example.ts.net` / `<TAILNET-IP>`.

## 6. Known gaps
- The compiled graphs, bitstreams, runtime libraries, architecture file and base SD image are not published (NOT_INCLUDED.md), so steps 1-3 need your licences and several hours of builds.
- The MMD patch to the vendor runtime is described, not published.
- Absolute paths of our lab PC remain in some scripts and notes.
- Raw board logs from the measurement runs are not published (they contain network identifiers); the per-run CSVs are.
