# Remote FPGA lab: OTA-updated CoreDLA classifier on a DE25-Nano

Code, configuration, models, data and measurement scripts for the paper's remote FPGA lab: a Terasic DE25-Nano board that students reprogram (bitstreams) and retrain (classifier models) over the network through Mender OTA updates, with a FastAPI lab backend and web UI.

**Start with [`docs/REPLICATION.md`](docs/REPLICATION.md).** Files that cannot be published (bitstreams, compiled graphs, vendor runtime, base SD image) are listed with hashes in [`docs/NOT_INCLUDED.md`](docs/NOT_INCLUDED.md), each with a rebuild path.

| folder | contents |
|---|---|
| `backend/` | lab backend (FastAPI, queue, Mender client, upload checks), web UI, tests, env template |
| `board/` | systemd units, Mender update modules, overlay sources, board setup |
| `dla-server/` | inference server source (C++, OpenVINO + CoreDLA) |
| `artifacts/` | build/deploy helpers for Mender artifacts |
| `hardware/` | Quartus/Platform Designer tcl scripts and our custom IP (MIPI front end, msgDMA wiring); the Terasic GHRD base is obtained separately |
| `bringup/` | board bring-up: SD image scripts, kernel module, kernel/u-boot patches |
| `models/`, `training/`, `data/` | ResNet-18 OpenVINO IR (fruit, flag), training scripts, flag test images with per-image licences |
| `evidence/` | measurement harness, run scripts and per-run CSVs behind the paper's tables |
| `docs/` | design notes, replication guides (`docs/guides/`) |

Licence: MIT for our code (`LICENSE`). Third-party material keeps its own licence (kernel module BSD-3-Clause, Linux patches GPL-2.0, flag images per `data/flag-images/SOURCES.md`, models derived from torchvision ResNet-18 weights). Not affiliated with or endorsed by Terasic, Altera or Mender; names are trademarks of their owners.

Paper-version snapshot: see `SNAPSHOT.md`.
