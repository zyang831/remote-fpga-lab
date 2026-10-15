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
`evidence/` holds the exact scripts and our per-run CSVs and summaries (`evidence/data/`). Run the scripts from `evidence/` with the backend up and the board on the fruit classifier. Python 3.12 with `requests`; the scripts that talk to Mender (`run_D4.py`, `run_D8.py`) also import `httpx` from the backend's virtualenv (`PYTHONPATH=<backend venv>/lib/python3.12/site-packages`). Set `BOARD_SUDO` (board sudo password, never stored) for the scripts that stop services or restore the board. Edit the machine-specific paths at the top of each script (`/home/<user>/...`).

| experiment | script | our results |
|---|---|---|
| environment and board-PC clock offset | `harness.py env`, `harness.py offset` | `data/env.md` |
| model switch (40, fruit/flag) and bitstream (24, 6 designs) | `run_D2.py model 40`, `run_D2.py bit 24` | `data/D2-*` |
| stage breakdown (10 per type) | `run_D3.py model 10`, `run_D3.py bit 10`, `analyze_D3.py` | `data/D3-*`, `data/D3-summary.md` |
| upload rejection matrix | `run_D4.py all 3` | `data/D4-matrix`, `data/D4-summary.md` |
| flag mismatches, board vs CPU | `analyze_flags.py board|cpu|compare` (images in `data/flag-images`) | `data/D5-flag` |
| CPU baseline on the board | `cpu_bench/` (cross-compile with the Yocto SDK), `run_D6.py 150` | `data/D6-cpu*`, `data/D6-resources` |
| failure repeats (graph cut, release, stalled download) | `run_D8.py cut 5`, `run_D8.py release 10`, `run_D8.py stall 90` | `data/D8-*`, `data/D8-summary.md` |
| video bandwidth | `run_D10.py 30` | `data/D10-*` |

The bitstream paths in `run_D2.py`/`run_D3.py` point at our `.core.rbf` files; use your own designs (hashes of ours: `NOT_INCLUDED.md`). `run_D8.py stall` needs `sudo tc` on the lab PC's interface to the board and removes the throttle on exit. Expect your numbers to differ with network, board and Mender poll interval (5 s here); compare medians and ranges, not single runs. The earlier single-trial figures are in `docs/guides/PAPER_RESULTS_REPLICATION_GUIDE.md`.

## 4. Sanity checks
- Board shows up as a device in Mender; `systemctl is-active dla-server` is active and stays active for 10 minutes (we saw a crash loop every ~49 s when a stale model graph was installed; redeploying the model fixed it, cause not isolated).
- `curl localhost:8000/session/model` returns the model name and categories.
- A model switch via the web UI finishes in about 25-30 s on a direct link (median 27.2 s, n=40; see `evidence/data/D2-model/summary.md`).

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
