# Replication guide: quantitative results of the final paper

Paper: *A Self-Standing Remote FPGA Laboratory Using Over-the-Air Updates, with an Edge AI Case Study* (`DRAFT.md`).
Written 2026-10-03 from the repository, the lab-backend repository, and the measurement notes. This guide says how each number in the paper was obtained and how an independent party can obtain a comparable one.

## 0. How to read this guide

- **Goal: same method, not same numbers.** Times depend on the network link, SD card, host PC and board unit. A replication is valid if the procedure is the same, the conditions in Section 3 are met, and the result falls inside the acceptance band given for each experiment. The bands are deliberately wide.
- Every experiment has: *claim* (what the paper says), *what is measured* (where the clock starts and stops), *procedure*, *acceptance*, *original evidence* (where our record lives), and *caveats*.
- Section 16 lists what is **not** reproducible from the repository, and where our own record is only a summary. Read it before treating a number as raw data.
- Paths are relative to `~/edge-ai-demo` (the "repo") unless prefixed `lab-backend/` (`~/mender/lab-backend`, its own git repository).

## 1. Result map

| # | Paper claim (section / table) | Experiment | n | Section here |
|---|---|---|---|---|
| 1 | Student bitstream programmed in 7.0–9.7 s, mean 8.9 (VI-A, Table IV) | E1 | 20 | 4 |
| 2 | Model switch 26–40 s, mean 29, all succeed (VI-A, Table IV) | E2 | 40 | 5 |
| 3 | Own model, upload to live 29–45 s, mean 32.6 (VI-A, Table IV) | E3 | 10 | 6 |
| 4 | Release with a 5-KB restore artifact: 25.6 and 26.1 s vs 59.9 MB / 26.3 s before (VI-A, Table IV) | E4 | 2 (+1 baseline) | 7 |
| 5 | Model with graph cut to 1 MB: failed in 14.3 s, previous model back (Table IV) | E5 | 1 | 8 |
| 6 | Garbage and 64-KiB bitstreams refused before Mender, HTTP 400 (Table IV) | E6 | 2 | 9 |
| 7 | ResNet-18 97 ms, about 9 Hz live; ResNet-50 239 ms, about 4 Hz (VI-B, Table V) | E7 | – | 10.1 |
| 8 | Board label equals CPU label on 50/50 fruit and 101/110 flag images (Table V) | E8 | 160 images | 10.2 |
| 9 | Notebook: starter 13/30 to 29/30 held-out photos (Table V) | E9 | 1 run | 10.3 |
| 10 | Five viewers, about 29 fps each, DLA 9–10 Hz (Table V) | E10 | 1 test | 10.4 |
| 11 | JTAG baseline: programmer 2 s (3 runs), tool run 36 s, board back 35 s after (VII-B) | E11 | 3 | 11 |
| 12 | 16 of 22 systems keep a host beside the board, 14 program through it; 0 of 22 use OTA (I, II, Table I) | E12 | 22 papers | 12 |
| 13 | Sizes and constants: artifacts 3.6 / about 60 / about 62 MB, student bitstreams 0.8–1.5 MB, 5,120 B restore, 20-min slot, 2-min no-show, 15-min deploy timeout, header + 1 MiB check (III, IV) | E13 | – | 13 |
| 14 | Figures quoted from other papers (Mender-FPGA 66 s / 29 MB, Kang 6–8 s, Ji 1.8–2.34x) | E14 | – | 14 |

## 2. Apparatus

### 2.1 Hardware (one station and one lab server)

| Item | Used by us |
|---|---|
| Board | Terasic DE25-Nano (Agilex 5 SoC, 2x Cortex-A55 + 2x Cortex-A76, 1 GB LPDDR4), microSD 59 GB, kernel arg `mem=768M` |
| Board uplink | Ethernet cable direct to the lab PC (NetworkManager "shared" profile, board 10.42.0.127). No Wi-Fi. |
| Camera | IMX519 on the MIPI connector; USB webcam (shows the LEDs) |
| Lab server | One PC running the lab backend, the Mender server (Docker), and (for E7 and E8) the cross-compiler and DLA compiler |
| JTAG (E11 only) | USB-Blaster on the board's onboard programmer, cable to the lab PC |
| Training GPU (E9 optional) | RTX 4080 (a CPU also works, slowly) |

A replication on a different Agilex 5 board, or on any SoC-FPGA board with a Linux that has the FPGA manager and FPGA region drivers, is acceptable for E1–E6 only if the payloads are replaced by equivalents for that board. E7–E10 need the CoreDLA design and therefore an Agilex 5 board.

### 2.2 Software versions we used

| Component | Version / source |
|---|---|
| Repo | `edge-ai-demo`, branch `master`, commit `2e809e8` (working tree also holds uncommitted paper files only) |
| lab-backend | commit `1cd01b9` (restore artifact, RBF pre-check, abort on timeout) |
| Board OS | Ubuntu 22.04.3, vendor kernel `6.12.11-gd7d192a9ddd9-dirty` (built 2026-09-27) |
| Mender | client 5.1.0 on the board (`mender-client4` package); server open-source in Docker, image tag `main` (version not pinned; do not compare against a specific release) |
| Update modules | `board/fpga-reconfig`, `board/coredla-model`, `board/coredla-runtime`; sha256 of the installed copies matched the repo on 2026-10-01 |
| CoreDLA arch | `AGX5_Small_k16c16_sb20480` (bitstream `board/dla_small_sb20480.core.rbf`, 3,747,840 B) |
| Compiler | Altera FPGA AI Suite 2025.3.1 (`dla_compiler`), OpenVINO 2024.6 on the server (`training/compile.sh` sources `/opt/intel/openvino_2024` and `/opt/altera/fpga_ai_suite_2025.3.1`) |
| Runtime artifact | `coredla-runtime-02530e18` |
| Notebook | OpenVINO below 2026.5, PyTorch; dataset Hugging Face "VinayHajare/Fruits-30" (Apache-2.0) |

### 2.3 What a third party must supply

The repository does not contain (gitignored): `*.rbf`, `*.bin`, `*.mender`, `build/`, `training/data/`, `training/runs/`. To replicate you must:

1. Obtain the CoreDLA reference design for the DE25-Nano and build `dla_small_sb20480.core.rbf` plus the overlay (`board/overlay_dla.dts`; `docs/CAMERA_MIGRATION_PLAN.md` has the build notes), or use any working CoreDLA Agilex 5 design with a camera path.
2. Supply **three student-style bitstreams**: fabric-only `.core.rbf` files for the board, each at least 1 MiB and starting with the 8 bytes `95 48 29 62 50 00 00 00`. We used `led-bouncing`, `led-johnson` and `ghrd` (artifact sizes 1,506,816 / 1,500,672 / 1,395,712 B). Any three valid designs of 0.8–1.5 MB will do. The device-tree overlay the lab applies with them is `lab-backend/assets/my_overlay.dtb` (source `board/overlay_ghrd.dts`).
3. Train, export and compile the three catalog models (E7–E8) with `training/` (`training/README.md` gives the order: `get_fruit.py`, `prepare.py`, `train.py`, `export.py`, `compile.sh`, `artifacts/build-model.sh`). Or substitute any three ResNet-18 classifiers exported with `training/export.py`.
4. Install the board image with `board/board_setup.sh` and the modules (do not re-run it on a board that already has the dwc2 FIFO kernel; see `docs/OTA_HARDENING_PLAN.md`, Rules).

## 3. Conditions that must hold for every timing experiment

Record these before starting; if one fails the run is not comparable.

1. Board on **direct Ethernet** to the lab PC (not a relay, VPN or Wi-Fi). Our earlier configuration over a Tailscale relay needed about 2.5 min per model switch and is not the paper's condition (Section VII-C).
2. The timing client runs **on the lab PC** and talks to `http://localhost:8000` (the backend), as the web page does.
3. Board idle on a catalog model (check below), exactly one session active, nobody else in the queue, no browser tab streaming the camera.
4. Mender device `accepted`, backend `GET /config` returns `"mender_problems": []`.
5. Health check ("classifier OK", our own definition): on the board `systemctl is-active dla-server` is `active`, `/var/lib/dla/spool/ready` exists, and `python3 training/board_check.py fruit` (fruit live) prints board = CPU top-1 for all images. During hardening we used a 5-image subset (`canada_00 germany_00 sweden_00 brazil_00 japan_00` converted to PNG when the flag model was live).
6. Board clock is not used for any measurement (no RTC). All durations are the client's wall clock, or Mender / backend log timestamps.

```bash
ssh terasic@coredla 'cat /var/lib/dla/model/name; systemctl is-active dla-server coredla-fpga; ls /var/lib/dla/spool/ready; cat /sys/class/fpga_manager/fpga0/state'
curl -s localhost:8000/config
```

Expected: model name, `active active`, the file `ready`, `operating`, and `mender_problems: []`.

## 4. E1: student bitstream programming time

**Claim.** 20 consecutive student-bitstream uploads, cycling three designs, all programmed, 7.0–9.7 s, mean 8.9 s, median 9.3 s.

**Measured.** Client wall clock from just before `POST /session/program` to the first poll (0.25-s interval) at which `/session/status` reports `program_state == "ok"`. The upload of the 1.4–1.5 MB file is inside the interval; the Mender poll wait (board polls every 5 s), the download, the install step and the fabric reconfiguration are all included.

**Procedure.**
1. Put the three `.core.rbf` files in `demo/webui/1-bitstream/` as `led-bouncing`, `led-johnson`, `ghrd` (or edit the list in the script).
2. `python3 Final_Paper/notes/measure_VI.py bit 20`
   The script joins the queue, acknowledges the session, and loops 20 times: pick the next file (round robin), POST it, poll, print `index file http-status result seconds`. It rejoins automatically if less than 120 s of the slot is left. It prints `n, min, mean, median, max` at the end.
3. Keep the full console output.

**Acceptance.** 20 of 20 `ok`. Min and max inside roughly 5–15 s on a direct link; mean within a few seconds of ours. The 5-s Mender poll interval alone adds up to 5 s, so a band of this width is expected. A run with a different `inventory_poll` or `update_poll_interval_seconds` in `/etc/mender/mender.conf` (ours: poll 5 s, `board/mender.conf`) is not comparable.

**Original evidence.** `notes/MEASURE_VI.md` (3-run trial 8.6 / 9.3 / 9.1 s, then the 20 runs). The per-run console output was not saved to a file; only the summary survives (Section 16).

**Caveats.** This is the student-visible time, not the pure reconfiguration time. The fabric configuration itself is a fraction of it.

## 5. E2: model switch time (40 alternating switches)

**Claim.** 40 alternating flag/fruit switches, all `ok`, 26–40 s each, mean 29 s. Polled every 2 s.

**Measured.** Client time from `POST /session/model` until `model_state` leaves `switching`. Includes: Mender poll, download of the 60 MB artifact, fabric reprogramming, DLA runtime start and graph import. The dominant part is the graph import by the on-board inference server (about 6–9 s for ResNet-18 plus start-up; see E4), not the transfer.

**Procedure.** One session with a long slot (we set `SESSION_SECONDS=3600` through `systemctl set-environment` and restarted `lab-backend`; undo afterwards). The first switch must target a model that is **not** already live, otherwise Mender answers "already installed" and the first run is a no-op.

```bash
B=localhost:8000
J=$(curl -s -XPOST $B/queue/join | python3 -c 'import sys,json;print(json.load(sys.stdin)["job_id"])'); curl -s -XPOST "$B/session/ack?job_id=$J"
sw(){ curl -s -XPOST "$B/session/model?job_id=$J" -H 'content-type: application/json' -d "{\"name\":\"$1\"}"; }
st(){ curl -s "$B/session/status?job_id=$J"; }
# live model must be 'fruit' now, so start with flag
for i in $(seq 20); do for m in flag fruit; do
  t=$(date +%s.%N); sw $m >/dev/null
  while st | grep -q '"model_state":"switching"'; do sleep 2; done
  echo "$m $(st | grep -o '"model_state":"[a-z]*"') $(echo "$(date +%s.%N) - $t" | bc)"
done; done | tee switch40.log
awk '{s+=$3; if(min==""||$3<min)min=$3; if($3>max)max=$3; if($2!~/ok/)bad++} END{print NR, min, s/NR, max, bad+0}' switch40.log
```

(The loop is the one in `docs/DEMO_STRESS_TEST_PLAN.md`, test ID 5; the timing wrapper is added here so the replication produces its own log.)

**Acceptance.** 40 of 40 `"model_state":"ok"`. Per-switch times about 20–45 s; mean about 25–35 s on a direct link. Afterwards the board shows no new `arm-smmu-v3 event` lines in `dmesg`, `dla-server` is active, and `check` in Section 3 passes.

**Original evidence.** `docs/DEMO_STRESS_TEST_PLAN.md`, Results, 2026-09-29, ID 5: "All 40 alternating flag/fruit switches succeeded: 26–40 s each, average 29 s." Individual times were not recorded in the repository (Section 16).

## 6. E3: own model, upload to live

**Claim.** 10 uploads of the notebook's fruit-v1 model under unique names: upload to live 45.4, 31.8, 31.8, 30.0, 31.0, 31.1, 31.7, 29.0, 32.8, 31.3 s; mean 32.6, median 31.5. The paper reports 29–45 s.

**Measured.** Client time from just before `POST /session/model/upload` to the moment `GET /session/model` returns the new model's name. It includes the server-side validation, CPU smoke test, `dla_compiler` run, artifact build, upload to Mender, deployment and the on-board import.

**Procedure.**
1. The upload payload is `models/fruit-v1/model.xml`, `model.bin`, `categories.txt` (the OpenVINO IR the notebook produces; the starter model is ResNet-18, 15 classes). To make your own, run the notebook (E9) and use its `fruit-demo/` output.
2. `python3 Final_Paper/notes/measure_VI.py up 10`
   Each iteration uploads under a new name `meas-<n>`, waits for `upload_state == ok` and `model_state == ok`, then polls `/session/model` every 0.5 s for the name, prints `deployed` and `live` seconds, deletes the model from the session, and continues. Final line: `upload to live (s): n= min= mean= median= max=`.

**Acceptance.** 10 of 10 live. Each time about 25–50 s; mean about 30–40 s. The first run may be slower than the rest (ours: 45.4 vs about 31 s; we did not test the cause, a cold compiler cache is the likely one).

**Original evidence.** `notes/MEASURE_VI.md`. A polling variant that read `/session/model` for release timing was discarded because that endpoint answers about 1 s after the finish while the classifier is still down.

**Caveat.** The model directory `models/meas-*`, its Mender artifacts and uploads accumulate on the lab server. Delete them after the run (`DELETE /session/model`), as we did.

## 7. E4: release with the restore artifact

**Claim.** After a session that loaded its own bitstream, release deploys a 5,120-byte restore artifact; the classifier was back 26.1 and 25.6 s after release. Before the change the release redeployed the 59,876,352-byte model artifact and took 26.3 s. We claim the size gain, not a time gain.

**Measured.** Release: from `POST /session/finish` (or slot end) until "classifier OK" (Section 3, item 5). Size: byte size of the artifact deployed by the release.

**Procedure.**
1. Fresh session. Program `ghrd.core.rbf` through `POST /session/program` (E1 procedure, one run). The classifier is now down.
2. `date +%s.%N; curl -XPOST "$B/session/finish?job_id=$J"`.
3. Poll the board until `systemctl is-active dla-server` is `active` and `/var/lib/dla/spool/ready` exists. Stop the clock.
4. In the Mender UI (Deployments) or via the management API, read the artifact the release deployed (`fpga-restore-v1`) and its size: `mender-artifact read build/fpga-restore-v1.mender` or the artifact list.
5. Repeat once more. For the "before" baseline, check out the lab-backend commit before `1cd01b9` (release then deploys the catalog model artifact) and repeat.

**Acceptance.** Release artifact is 5,120 B (the restore artifact holds only a marker file named `restore`; it is built once with `mender-artifact write module-image -T fpga-reconfig -t de25-nano -n fpga-restore-v1 -f restore`). Release time about 20–35 s, and about equal before and after on a direct link. A much longer release on a fast link means the module or board is in a different state; stop and check Section 3.

**Original evidence.** `docs/OTA_HARDENING_PLAN.md`, Step 0 (baseline 26.3 s, 59.9 MB) and Step 7 (26.1 and 25.6 s, 5,120 vs 59,876,352 B). Times came from the backend log; raw log lines are not archived.

## 8. E5: failed model install and rollback

**Claim.** A flag-model artifact whose `graph.bin` is cut to 1 MB fails to start; Mender marked the deployment `failure` after 14.3 s; the previous model (flag, 67 MB graph) was back and classifier OK. One trial.

**Procedure.**
1. Copy a catalog model directory, truncate its graph, build and deploy:
```bash
cp -r models/flag models/badgraph-1 && head -c 1048576 models/flag/graph.bin > models/badgraph-1/graph.bin
echo badgraph-1 > models/badgraph-1/name
./artifacts/build-model.sh badgraph-1
MENDER_USER=... MENDER_PASS=... ./artifacts/mender-deploy.sh build/coredla-model-badgraph-1-*.mender
```
   with the flag model live before the test.
2. `mender-deploy.sh` prints `finished in Ns: {...}`. The deployment statistics should show `failure: 1`. Time is the script's value to `finished` (3-s poll) or the server's deployment record (start to finish).
3. Check afterwards: `cat /var/lib/dla/model/name` is `flag`, `/var/lib/dla/idle/` is unchanged (the idle pair is written only after a successful install), `dla-server` active, `board_check.py flag` agrees.

**Acceptance.** Status `failure`, previous model live and functioning, no manual action. Time to failure about 10–30 s (ours 14.3 s). This is a single trial; repeat it 3 times for your own confidence, but do not describe the result as more than that.

**Original evidence.** `docs/OTA_HARDENING_PLAN.md`, Step 3 metric 3 (`coredla-model-badgraph-1`).

## 9. E6: refused bitstreams

**Claim.** A 64-KiB truncation of a valid bitstream and a 1.5-MiB random file are refused by the backend with HTTP 400 and never reach Mender.

**Procedure.** In an active session:
```bash
head -c 65536 demo/webui/1-bitstream/ghrd.core.rbf > trunc.rbf
head -c 1572864 /dev/urandom > garbage.rbf
for f in trunc.rbf garbage.rbf; do
  curl -s -o /dev/null -w "$f %{http_code}\n" -XPOST "$B/session/program?job_id=$J" -F bitstream=@$f
done
```
Expected: `400` twice, and no new deployment in the Mender server's list. The backend rule is in `lab-backend/config.py` (`RBF_MAGIC` header `9548296250000000`, `MIN_RBF_BYTES` 1 MiB, `MAX_RBF_BYTES` 8 MiB).

> **Warning, do not skip.** Never push `garbage.rbf` to the board through any route that bypasses the backend check (direct Mender deployment, `artifacts/deploy.sh`). On our board it wedged the FPGA manager and the Secure Device Manager; no software reset worked and only removing power recovered it (`docs/OTA_HARDENING_PLAN.md`, Steps 4 and 4b; paper Section VII-E). A 64-KiB truncation that bypasses the check programs "ok" and is not an error condition.

## 10. Edge AI results (E7 to E10)

All use the three catalog models trained and compiled with `training/` (Section 2.3, item 3) and deployed with `artifacts/mender-deploy.sh`. `models/<name>/cpu_reference.json` is created by `training/export.py` (top-5 per demo image on the OpenVINO CPU plugin).

### 10.1 E7: latency and live rate (ResNet-18 vs ResNet-50)

**Claim.** ResNet-18 about 97 ms per image on the accelerator, about 9 classifications per second live. ResNet-50 (the model it replaced) 239 ms, about 4 per second.

**Procedure.**
1. Deploy the model. Run `python training/board_check.py fruit` from `training/` (the board must be running that model and no session may use it). It sends each `demo-images/fruit/` image to the board's file inbox over ssh, and prints per image `latency_ms` and, at the end, `latency mean .. ms max .. ms`. `latency_ms` is the on-board time of the inference call (`dla-server/main.cpp`, results JSON), not the ssh round trip.
2. Live rate: join a session with the camera facing a screen, and read `infer_fps` from `live.json` on the board for about 30 s:
   `ssh terasic@coredla 'for i in 1 2 3 4 5 6; do cat /var/lib/dla/spool/results/live.json; sleep 5; done'`
   or read "DLA x Hz" in the web page. The picture rate (about 28 fps) is a separate number and is not the classification rate.
3. For ResNet-50, train and compile `--arch resnet50` (`train.py fruit --arch resnet50 ...`), build, deploy, and repeat. The ResNet-50 artifact `coredla-model-fruit-eec306c8` remains on our Mender server as rollback.

**Acceptance.** ResNet-18 latency about 90–105 ms, live about 8.5–10 Hz. ResNet-50 latency about 230–250 ms, live about 3.8–4.2 Hz. The ratio ResNet-50/ResNet-18 of about 2.4x is the robust finding.

**Original evidence.** `training/README.md` Results table (239 ms ResNet-50 fruit and flag; about 98 ms ResNet-18 fruit; about 96 ms ResNet-18 flag); `docs/DEMO_OPTIMIZATION_PLAN.md` aspect 4 (97 ms, 9.2 Hz; ResNet-50 245 ms, 3.9–4.0 Hz at the time of the bake-off). The paper's "97 ms" is the bake-off value (the training README gives 98 and 96 ms for the two catalog models). Quote a range rather than a single digit when you compare.

### 10.2 E8: board versus CPU labels

**Claim.** The board's top-1 label equals the OpenVINO CPU plugin's for 50 of 50 fruit images and 101 of 110 flag images. Accuracy against ground truth is deliberately not claimed (flag 79/110).

**Procedure.** For each catalog model `<name>` in {`fruit`, `flag`}, with that model live on the board:
```bash
cd training && python board_check.py fruit   # then: python board_check.py flag
```
The last line is `board == cpu top-1: A/N   board == filename truth: T/N   latency ...`. `A/N` is the claim (N = 50 and 110). The 110 flag images are the entries of `models/flag/cpu_reference.json` (`demo-images/flag/` also contains `SOURCES.md`; board_check only reads the files named in the reference).

**Acceptance.** `fruit` A/N of 49–50/50. `flag` A/N within a few images of 101/110; the disagreements are on low-margin images and the cause was not investigated by us, so we do not make claims about them. The CPU run itself must reproduce the stored reference: re-running the export on the CPU gives the same top-1 (the training README records "CPU == torch" 832/832 and 1483/1483 on validation). If you retrain, your models differ and your counts will too; the method (board versus CPU on identical preprocessed images) is what is being verified.

**Original evidence.** `training/README.md` Results table; `docs/MODEL_ROBUSTNESS_PLAN.md` ("board == CPU 50/50, truth 48/50; flag 101/110"); `docs/DEMO_OPTIMIZATION_PLAN.md` (ResNet-18: board == CPU 101/110, truth 79/110).

### 10.3 E9: notebook improvement (13/30 to 29/30)

**Claim.** In one recorded run, fine-tuning raised the starter model from 13 to 29 of 30 held-out photos (validation accuracy 40% to 88%).

**Procedure.**
1. Open the lab page, "Download the training notebook" (served as `training_demo.ipynb` with the server address as `LAB_URL`), or use `demo/training_demo.ipynb`. It is generated from `demo/make_notebook.py`.
2. Fresh working folder (no `data/`, `held-out/`, `fruit-v1.pt`, `fruit-demo/`). Run all cells. The notebook downloads Fruits-30, splits 80/20 per class into `data/train` and `data/val`, saves 2 photos per class (30 in total) to `held-out/`, downloads the starter weights `fruit-v1.pt` from the lab backend, scores the 30 held-out photos ("before"), fine-tunes (AdamW, backbone lr 1e-4, head lr 1e-3, cosine schedule, `EPOCHS = 8` in the notebook; the web notebook may differ, read the value in the cell), converts to OpenVINO with preprocessing and Softmax built in, scores the same 30 photos on the CPU ("after"), and writes `fruit-demo/`.
3. Record "before: A/30 after: B/30 (validation accuracy x -> y)", printed by the last scoring cell.

The starter model was produced with `training/train.py fruit-v1 --epochs 2 --no-sim` on the notebook's split (ResNet-18 default). Its checkpoint is `lab-backend/static/fruit-v1.pt`; its IR in `models/fruit-v1/` is the backend's upload reference.

**Acceptance.** "Before" is low (about 10–20 of 30) and "after" is clearly higher (above 25 of 30). The split is random per run unless seeded, so exact counts differ. Do not read this as an accuracy benchmark; it shows that the notebook improves the model and that the improved model can be uploaded.

**Original evidence.** `demo/RUNBOOK.md` and `docs/DEMO_OPTIMIZATION_PLAN.md` ("notebook 13/30 to 29/30 (val 40% to 88%)"). One run; no seed or run log is archived.

### 10.4 E10: five viewers

**Claim.** One test: five simultaneous live-view viewers each received about 29 frames per second while the accelerator classified 9–10 times per second.

**Procedure.** In an active session on a catalog model, open five clients on `GET /session/camera/stream` (server-sent events) for the same session. We used five browser tabs; five `curl -N` clients also work. Count events per client over at least 30 s. In parallel read `infer_fps` (E7 step 2) and on the board `top -bn1 | head -20` and `dmesg | grep -i oom`.

**Acceptance.** Each client about 25–30 frames per second, `infer_fps` unchanged from the single-viewer value, no OOM. We did not test more than five viewers.

**Original evidence.** `docs/DEMO_STRESS_TEST_PLAN.md`, ID 12 (also reports 190% CPU for `dla-server`, 5% per poller, 276 MB free). The exact client program is not archived.

## 11. E11: JTAG baseline (Section VII-B)

**Claim.** Programming the board over JTAG with the vendor programmer from a 3.3-MB whole-chip file: programmer operation 2 s in each of three runs, whole tool invocation 36 s, the ARM cores are reset, and the board answered over ssh again 35 s after programming ended (one precisely timed run). One further attempt failed with "Can't scan JTAG chain" right after a reboot.

**Procedure.** With the USB-Blaster cable on the lab PC and the board powered:
```bash
cd ~/quartus_projects/_ref_build_de25_camera_dla/CoreDLA_GHRD/output_files/
time quartus_pgm -c "DE25-Nano [1-11]" -m jtag -o "p;golden_top_hps_auto.sof"
```
Read the programmer's own timestamps from the log (1-s resolution) for the programming operation; `time` gives the tool invocation. For the ssh return time, poll `ssh terasic@coredla true` every second from the end of programming. Repeat 3 times; check the board is back on the classifier afterwards.

**Notes.** A plain `golden_top.sof` is refused by Quartus ("HPS is present but bootloader information is missing"); use the `_hps_auto` file, which is the same reference design built with the HPS-first option. The `.sof` is a whole-chip file and the OTA student payload is a fabric-only `.core.rbf`, so the two figures are indicative, not like for like (the paper says so). About 34 s of the 36 s is tool start-up, including a probe of a configured remote JTAG server.

**Acceptance.** Programmer operation of a few seconds, tool invocation a few tens of seconds, the HPS reset and the board reachable within about 1 minute.

**Original evidence.** `notes/MEASURE_VI.md`, "JTAG baseline". Log lines at 16:17:08–10, 16:22:27–29 and 16:24:15–17 (workstation clock).

## 12. E12: literature counts (Table I and the 16 of 22 / 14 of 22 claims)

This is a reading task, not a measurement.

1. The corpus: the 20 papers in `Remote FPGA Lab Papers/` numbered 02–18 and 20–22 (01 and 19 are the two review papers and are not rows; files 17 and 22 are the same system, FPGARLab, so the 20 papers give 19 systems), plus Young22, Samayoa23 and Ji26 added by the author for Table I (22 systems). Li23 is cited in text only (its online part is a simulation platform; remote board access is not described).
2. Definitions (from `notes/AUDIT_TABLE_I.md`): a **host** is a PC, VM, Raspberry Pi, MCU or Arduino board, or a server that the paper places between the user and the FPGA board in the laboratory. A system counts as "programs through the host" only when the paper states that the host's tools or hardware program the board.
3. For each paper, record: what machine sits beside the board, whether it is per board or shared, how the board is programmed, whether an OTA or update framework is mentioned, and whether students receive an accelerator workflow. Use the audit file as the worked example (a table of 19 rows, verbatim quotes of 25 words or fewer, "judgement" marks where an inference was made).
4. Counts: 16 of the first 19 keep a host beside the board and 14 of those program the board through it. The three added systems (Young22, Samayoa23, Ji26) have no per-board host, so 16 of 22 and 14 of 22. Zero of 22 mention OTA, Mender, SWUpdate or RAUC for design delivery (near misses are listed in the audit: future work in Kang, Di's RPyC bitstream push, and others).
5. Judgement calls an independent reader may decide differently: Yang (board count not stated), Cruz (unit count not stated), Lorens (garbled text), Oballe-Peinado (Raspberry Pi as programmer is inferred), and Chamunorwa and Jacobs (host present, programming path not stated). Flipping any of these changes the counts by at most one; the qualitative claim ("most keep a host") does not change.

**Acceptance.** A reader following the definitions gets 16 ± 1 of 22 and 14 ± 1 of 22, and 0 for OTA. Document any difference with the paper and its page.

## 13. E13: sizes and constants

| Value in paper | How to check |
|---|---|
| DLA bitstream artifact about 3.6 MB; model artifact about 60 MB; runtime about 62 MB | `ls -l build/*.mender` after `artifacts/build-model.sh`, `build-runtime.sh`. Ours: 3,584,512 B (DLA bitstream artifact), 59.8–62.4 MB (catalog models, ResNet-18), 62.6 MB (runtime) |
| Student artifacts 0.8–1.5 MB | `mender-artifact read` on artifacts built from your bitstreams; ours 0.77–1.5 MB. The paper's Table IV row says 1.4–1.5 MB for the three designs used in E1 |
| Restore artifact 5 KB (5,120 B) | E4 |
| RBF accepted only with header `95 48 29 62 50 00 00 00` and at least 1 MiB | `lab-backend/config.py`; E6 |
| Slot 20 min, no-show 2 min, deploy timeout 15 min, release retries 5 min | `lab-backend/config.py` (`SESSION_SECONDS` 1200, `ACK_GRACE_SECONDS` 120, `RELEASE_RETRIES` 10 x `RELEASE_RETRY_SECONDS` 30), 900-s deployment timeout is the default of `poll_until_finished` in `lab-backend/mender_client.py` |
| Mender poll 5 s, `ModuleTimeoutSeconds` 600 | `board/mender.conf` |
| Maximum classifier network | the backend compares the uploaded graph to `models/fruit-v1/model.xml` layer by layer (`lab-backend/model_upload.py`) |

Unit tests of the backend rules: `cd ~/mender/lab-backend && pytest` (3 test files, 26 checks at `1cd01b9`).

## 14. E14: numbers quoted from other papers

Check them in the cited PDFs (all in `Remote FPGA Lab Papers/`): Mender-FPGA (29 MB full image, 66 s over a 10 Mbps link, delta about 2 MB: Rathor and Sinha, iSES 2024); Kang and Luo (bitstream download 6–8 s for 2–3 MB, file 16); Ji et al. (programming latency 1.8–2.34 times lower than JTAG, 15 boards, 69 valid survey responses from 91 students). The paper makes no performance comparison with them (Mender-FPGA's figure is over 10 Mbps, ours over Ethernet), only a statement of order of magnitude for Kang and Luo.

## 15. Not reported in the paper (do not look for it)

Runtime install time (never timed), the 10-cycle soak, the forced-hang recovery test (Step 5), the watchdog and panic-reset times, the CoreDLA stall after about 622,000 frames, partial reconfiguration, and catalog accuracy against ground truth. Their records exist in `docs/OTA_HARDENING_PLAN.md` but the paper does not rely on them.

## 16. Provenance gaps and honest limits of this record

1. E1 and E3 have a measurement script (`notes/measure_VI.py`) and a summary (`notes/MEASURE_VI.md`); the raw console output was not saved. E3 individual times are listed in the note.
2. E2 (40 switches) is documented by one summary line in `docs/DEMO_STRESS_TEST_PLAN.md`. The per-switch times were not kept in the repository; the loop is reconstructed from the stress-test plan.
3. E4–E6 times come from the backend log and Mender deployment records on 2026-09-30 and 2026-10-01 (hardening runs, one to two trials each). The backend log `lab-backend/uvicorn.log` is not archived with the paper.
4. E7: the paper's 97 ms and 239 ms are the values recorded in the demo optimisation plan and training README. They are single board-side latency means, not distributions.
5. E9 and E10 are single runs with no archived seed or client script. They support "the pipeline works", not a statistic.
6. The "about 2.5 min" model switch of the earlier configuration (ResNet-50 over a relayed link) is from `docs/MENDER_FPGA_OTA_RESEARCH.md` and `docs/DEMO_OPTIMIZATION_PLAN.md`; it cannot be reproduced now that the board is on direct Ethernet and the catalog is ResNet-18.
7. Everything is for one board at one site. Variation between boards, SD cards, and users was not measured.

## 17. Cleanup after a replication

- `DELETE /session/model` for every `meas-*` and test model; delete `models/meas-*`, `models/badgraph-1`, their artifacts on the Mender server, and rejected uploads in `lab-backend/uploads/`.
- Unset `SESSION_SECONDS` (`sudo systemctl unset-environment SESSION_SECONDS && sudo systemctl restart lab-backend`).
- Restore the board to the catalog fruit model with `artifacts/mender-deploy.sh build/coredla-model-fruit-*.mender` (do not use `artifacts/reset.sh` as a health check: it stops the backend and wipes the queue), then run the Section 3 check.
- If the board was power-cycled, wait for `coredla-fpga` and `dla-server` to become active (about 2 min) before the next run.
