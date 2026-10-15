# Demo stress-test plan ("break it" before the live demo)

Status 2026-09-29: **safe set + ID 5 run** (results in §5); ID 4 soak, ID 6 and the destructive set still open. A test succeeds when it breaks something; each break
gets a fix or a written workaround in `demo/RUNBOOK.md` before demo day. Realistic failures only
(presenter, students, audience, network, power, hardware), no adversarial security hardening.

## 0. System map

- **Camera path:** IMX519 → camera ring at 0xB4000000 → dla-server. dla-server writes `live.jpg` at
  about 28 fps and `live.json` at about 9 Hz.
  - Every SSE viewer gets its own `ssh` connection plus a Python loop on the board that checks
    `live.jpg` every 10 ms.
  - lab-backend relays each frame as SSE to the browser.
- **Deploy path:** notebook (on the PC or a student laptop; it fetches `fruit-v1.pt` from the backend)
  → browser upload → `check_ir` → `build-user-model.sh` → Mender server (over Tailscale, needs the PC's
  internet) → board polls every 5 s → `coredla-model` → FPGA reprogram → graph import → `ready`.
- **Single points of failure:**
  - **Lab PC:** runs the backend, and it is the board's only uplink (eno1 NAT to eduroam).
  - **PC eduroam:** Mender, Tailscale control and NTP all depend on it.
  - **Hardware:** one Ethernet cable, one board, one camera ribbon.
  - **One queue coroutine:** it waits inside every deploy or build for up to 900 s. Nothing else runs
    meanwhile.
  - **In-memory state:** the queue, the uploaded-model catalog and `_live_model`.

## 1. Deliberate design choices (out of scope)

- One board, FIFO queue, in-memory state. A restart wipes the queue and any uploaded catalog entries
  (ponytail-noted).
- No auth. "Skip queue (demo)" is unauthenticated on purpose (ponytail-noted).
- `mem=768M`, no `camera_reserved`. The camera ring lives in the DLA window.
- Fixed catalog: fruit, flag and imagenet, all ResNet-18. Uploads must match `fruit-v1` layer for
  layer; only the FC size may differ.
- Every switch goes through Mender and always reprograms the FPGA. The skip-reprogram shortcut was
  reverted.
- Camera-only board demo: no photo upload, 480×270 live view, centre-square crop.
- Board uplink is Ethernet to the PC (NetworkManager profile `board-share`). The AIC8800 dongle is gone.
- `fruit-v1.pt` is hosted only by the lab backend.
- Timeouts: 20 min session slot, 120 s ack grace, 900 s deploy/build timeout.
- Accuracy is not a goal. Live-camera accuracy has not been measured. `fruit-demo` has no `none` class
  on purpose (it is a story point).
- The BOARD CAM (ustreamer) panel is cosmetic.
- dla-watchdog only restarts a dla-server whose picture has stalled. It skips deploys and the first
  60 s.

## 2. Test matrix (ranked by likelihood × impact)

Setup used by the rows below:

```bash
B=localhost:8000
J=$(curl -s -XPOST $B/queue/join | python3 -c 'import sys,json;print(json.load(sys.stdin)["job_id"])'); curl -s -XPOST "$B/session/ack?job_id=$J"
sw(){ curl -s -XPOST "$B/session/model?job_id=$J" -H 'content-type: application/json' -d "{\"name\":\"$1\"}"; }
st(){ curl -s "$B/session/status?job_id=$J"; }
slot(){ sudo systemctl set-environment SESSION_SECONDS=$1 && sudo systemctl restart lab-backend; }  # undo: unset-environment + restart
```

Monitors:

- **M1:** `ssh terasic@coredla 'tail -f ~/smmu_trace.log'`
- **M2:** `ssh terasic@coredla 'journalctl -f -u dla-server -u dla-watchdog'`
- **M3:** `journalctl -fu lab-backend` and `tail -f ~/mender/lab-backend/uvicorn.log`
- **GUI:** the "LIVE · n fps · DLA x Hz" tag

| ID | Component | Attack / scenario | How to run | Expected break | Detection | Sev | NEEDS-CONFIRMATION? |
|---|---|---|---|---|---|---|---|
| 1 | queue | RUNBOOK framing check leaves a session open. Presenter closes that tab and later joins from the projector browser. | Firefox: Join, close the tab without Release. Chrome: Join. | Chrome is queued at position 1 with an ETA of up to ~20 min. The ack was already sent, so the dead job keeps the board. | GUI position/ETA; `curl "$B/queue/status?job_id=…"` | H | No |
| 2 | network / students | Students open the UI or notebook over venue WiFi | Phone on eduroam: `curl -m5 http://<PC wls5f3 IP>:8000/config`, then open `/training_demo.ipynb` | eduroam client isolation blocks it, or the PC's DHCP IP has changed since the slides were made | HTTP code; `ip -4 a show wls5f3` | H | No |
| 3 | board link | Ethernet cable knocked out for 30 s while the live view runs | Pull the board's eth0 cable, or `sudo nmcli con down board-share`; restore after 30 s | Live view stays on "problem" long after the link returns: the ssh ControlMaster (ControlPersist 120, no ServerAliveInterval) hangs on a dead TCP connection | Seconds from replug to first new frame; `ssh -O check -S ~/mender/lab-backend/uploads/.ssh-* x`; M3 | H | No |
| 4 | board, long run | 2-h soak: MIPI live + BOARD CAM webcam + GUI tab open. Webcam+MIPI has only been soaked for 17 min. | `slot 10800`; join; leave the tab open; every 10 min: `ssh coredla 'free -m; df -h / /var; ps -o rss,pcpu,args -C python3,ustreamer'` | SMMU `event 0x10` wedge (seen at 532 s before), dropped frames, watchdog restarts, RSS creep, orphaned Python pollers on the board | M1 `smmu=`/`usb=` above 0; `journalctl -u dla-watchdog \| grep restarting`; GUI fps | H | No |
| 5 | deploy / FPGA | 40 back-to-back switches; each one reprograms the fabric and re-initialises the IMX519 | `slot 3600`; join; `for i in $(seq 20); do for m in flag fruit; do sw $m; while st \| grep -q switching; do sleep 2; done; st \| grep -o '"model_state":"[a-z]*"'; done; done` | `dla-server not ready after 180s`, `camera: frame N wait failed`, SMMU fault near a deploy (seen 2026-09-23/24), fd or memory leak | Count of `failed`; M1; M2 | H | No |
| 6 | PC uplink | PC eduroam drops, taking Mender, Tailscale control and NTP with it | `nmcli dev disconnect wls5f3` for 120 s during (a) idle live view, (b) `sw flag`, (c) a fruit-demo upload; then `nmcli con up eduroam` | (a) should survive over the direct 10.42.0.x link (verify). (b)/(c) either fail with an httpx error or hang until 900 s. | GUI model/upload error; M3 | H | No |
| 7 | queue loop | Cable pulled 5 s after clicking the flag chip; presenter presses Release at 1 min; cable back at 3 min | Click flag, pull the cable, press Release, replug | Mender download stalls (the resumer needs about 14 min to notice). The loop is stuck in `poll_until_finished` for up to 900 s, so Release and the slot timeout are ignored and all chips stay disabled. | GUI phase and busy seconds; Mender Deployments tab; `st` | H | No |
| 8 | PC lifecycle | PC reboot (update, or someone restarts it) | `sudo reboot` | lab-backend starts before Tailscale or eduroam is up. Preflight fails and the red banner stays until a manual restart. Board DHCP renew is slow. | `curl $B/config` → `mender_problems`; seconds to first live frame | H | **YES** |
| 9 | board lifecycle | Cold power cycle with PC eduroam off for the first 3 min | Unplug and replug board power with `wls5f3` down | The board has no RTC and no NTP yet, so Mender TLS fails ("certificate not yet valid"). The board does not check in and switches sit at `pending`. | `ssh coredla 'timedatectl; journalctl -u "mender*" -n 30'` | H | **YES** |
| 10 | Mender / module | Power cut during a model install | `sw flag`; cut power at "board installing" | `/var/lib/dla/model` half-copied; the ArtifactRollback path has never been exercised; no live view after boot | After boot: `cat /var/lib/dla/model/name; systemctl is-active dla-server`; Mender status | H | **YES** |
| 11 | backend state | Backend restart (crash or someone's `reset.sh`) after fruit-demo is live | Upload fruit-demo, then `sudo systemctl restart lab-backend` | "Session lost". The fruit-demo chip disappears while the board still runs it: nothing is highlighted and there is no way back to it without re-uploading. | GUI chips vs `curl $B/session/model` | M | No |
| 12 | viewers | Five viewers: presenter, projector tab (same localStorage job) and 3 more tabs; then a switch | Open 5 tabs on the active session, then `sw flag` | Each tab adds an ssh connection, a board Python poller and a 28 fps JPEG stream. That competes with dla-server (200 % CPU), so DLA Hz drops, or import hits OOM under 768M. | GUI "DLA x Hz"; `ssh coredla 'top -bn1 \| head -20; dmesg \| grep -i oom'` | M | No |
| 13 | notebook env | Student environments: (a) OV newer than the `<2026.5` pin already installed, (b) VS Code "base" conda kernel, (c) macOS arm64, (d) Windows CPU-only | Fresh venvs, Run All, upload `fruit-demo/` | Cell 1 does not downgrade an existing OV, so the IR differs ("layer … differs"). Spawn or pickle errors on macOS. CPU run is too slow. | Cell traceback; upload rejection text | M | No |
| 14 | notebook data | 20 students download Fruits-30 (~200 MB) at the same time | Laptop on eduroam with an empty `~/.cache/huggingface`; time the dataset cell and extrapolate ×20 | Dataset cell stalls for minutes, or Hugging Face returns 429 | Cell wall time; exception text | M | No |
| 15 | session slot | Slot expires mid-build | `slot 150`; join; upload fruit-demo at about 100 s | The model builds, the timeout wins before the queued switch, and the session ends mid-story | GUI end view; M3 "released … (timeout)" | M | No |
| 16 | backend + Mender | Backend restart mid-deploy | `sw flag`; at "board installing" run `sudo systemctl restart lab-backend` | Preflight aborts the in-progress deployment. dla-server may be left stopped, and the watchdog ignores inactive units. | Mender tab; `ssh coredla systemctl is-active dla-server` | M | **YES** |
| 17 | upload | Two uploads within the 3 s poll gap (second tab of the same job), same name | Tab A: upload fruit-demo. Tab B within 3 s: upload `models/fruit-v1/*` as fruit-demo. | `main.py` writes `models/fruit-demo/*` before `build_model` returns 409, so the running build reads a mixed xml/bin: compile fails or the wrong weights are deployed | Tab B 409; `md5sum models/fruit-demo/model.bin` | M | No |
| 18 | upload | Student names the upload `fruit-v1` (the starter's own name) | First `cp -a models/fruit-v1 ~/fruit-v1.bak`; then upload `fruit-demo/*` as `fruit-v1` | The name is not in BUILTIN_MODELS, so the upload overwrites the reference IR directory (`model.bin` is untracked). Later uploads are validated against the student's IR. | `git status models/fruit-v1`; md5 vs the backup | M | **YES** |
| 19 | watchdog | dla-server hangs with the process still alive | `ssh coredla 'echo 123 \| sudo -S systemctl kill -s STOP dla-server'` | Should recover in ~40 s (try-restart, then SIGKILL after 15 s). Break if it loops, or the fabric or camera fail to re-init. | M2 "live.jpg unchanged"; GUI recovery seconds | M | No |
| 20 | board lifecycle | Warm reboot (this used to kill USB) | `ssh coredla 'echo 123 \| sudo -S systemctl reboot'` | eth0, webcam or camera do not come back without a power cycle | `ping 10.42.0.127`; M1 boot id; unit states | M | **YES** |
| 21 | Program board | Truncated or wrong-family .rbf dropped in Board mode | `head -c 1M demo/webui/1-bitstream/ghrd.core.rbf > <scratch>/bad.core.rbf`; Program; then a model chip | Reconfig fails with the overlay half-applied, and a bridge access wedges the board. "Pick a model" may not restore it. | `program_state`; `ssh coredla cat /sys/class/fpga_manager/fpga0/state` | M | **YES** |
| 22 | camera hardware | Ribbon unseated in transport | Power off, unseat the IMX519 ribbon, boot | IMX519 init fails, then a watchdog/dla-server restart loop. The GUI only shows the generic "camera feed not running". | `journalctl -u dla-server \| grep -i imx519`; M2 | M | **YES** |
| 23 | upload input | `categories.txt` edited in Notepad: trailing blank line, UTF-8 BOM, 16 lines | Three uploads of fruit-demo with `printf '\n' >>`, a BOM prepended, one extra line | Blank line is rejected with a message students may not understand. BOM is accepted, so class 0 becomes `﻿apple`. | Upload error text; `curl $B/session/model` → `categories[0]` | L | No |

## 3. Accepted risks + demo-day runbook mitigations

- **Unauthenticated Skip queue:** any student with the web UI open for the notebook can press Join then
  Skip and take the board from the presenter. Give students the direct links
  `http://<pc>:8000/training_demo.ipynb` and `/fruit-v1.pt`, not the UI. The presenter can use Skip to
  recover from ID 1.
- **In-memory queue and catalog:** after any backend restart, rejoin and re-upload fruit-demo (about
  45 s). Keep the three files on the desktop.
- **Loop blocks during deploys:** a switch or upload stuck for more than 2 min (normally 25–45 s) will
  not respond to Release. Recovery is `sudo systemctl restart lab-backend`, then `./artifacts/reset.sh`.
  This recovery path is still unconfirmed until ID 16 is run.
- **`mem=768M` headroom:** mirror the projector display instead of opening a second tab. Cap viewers at
  the number ID 12 shows to be safe.
- **Session slot:** run `SESSION_SECONDS=3600 ./artifacts/reset.sh` before the demo. After the framing
  check, press Release. That also fixes ID 1.
- **`fruit-v1.pt` only on the lab host:** keep a copy on a USB stick for students' laptops.
- **PC is a single point of failure:** set PC power settings to never sleep. Do not touch eno1. Never
  plug a wall cable into eno1 while `board-share` is active.
- **No RTC:** before the demo, check `ssh coredla timedatectl` shows "synchronized: yes".
- **Hand-installed `/opt/dla`:** if the aspect-3 runtime is still hand-installed, do not deploy any
  `coredla-runtime` artifact before the demo. It would revert the pipelined display loop.
- **Unmeasured live accuracy and untested props:** rehearse under the venue lighting and choose 3 props
  per model that read reliably.
- **Webcam wedge (if ID 4 reproduces it):** unplug the webcam. BOARD CAM is cosmetic, and the uplink no
  longer goes through USB, so the MIPI path should be unaffected.

## 4. Execution order

- **Safe (run now; the board stays in service; start from the RUNBOOK "Before the session" state):**
  1, 2, 23, 17, 15, 11, 19, 12, 3, 6, 7, 13, 14. Run 7 last: if it hangs, restart lab-backend.
- **Soak (overnight):** 4 (extend to 8 h, with 3 viewer tabs from ID 12), then 5. Collect M1 and M2 logs
  in the morning.
- **Destructive (confirm each, one at a time, with serial console `/dev/ttyUSB0` attached; afterwards
  restore with `reset.sh`):**
  - 18: needs a backup first
  - 16
  - 20
  - 9
  - 8: the PC reboot takes the backend down
  - 21
  - 10: power cut mid-install
  - 22: power off before touching the ribbon

## 5. Results

(One line per test as it runs: date, ID, broke yes/no, what broke, fix or RUNBOOK workaround.)

Backend fixes below are in `~/mender/lab-backend` (`main.py`, `model_upload.py`, `test_main.py`), uncommitted.

- 2026-09-29, ID 1, **broke:** a second browser queues at position 1 with an ETA of 1192 s. Workaround:
  Skip (tested: the dead session is released and the new one goes live in under 3 s), or Release after
  the framing check (§3).
- 2026-09-29, ID 2, **broke (PC side, before any phone test):** ufw is active with default deny incoming.
  Only `tailscale0` and 22/tcp are allowed, so `:8000` cannot be reached from eduroam whatever the
  client isolation. The PC's eduroam IP is 10.192.57.64/21 (24 h DHCP lease). Fix (not applied; it
  opens the port to the venue network): `sudo ufw allow in on wls5f3 to any port 8000 proto tcp`.
  The phone test for eduroam client isolation still needs a person. If isolation blocks it, the USB
  stick (§3) is the fallback.
- 2026-09-29, ID 3, no break. `nmcli con down board-share` for 30 s. The link was back at 12:43:59 and
  frames resumed at 12:44:23 (24 s) on the same SSE stream, because the ssh ControlMaster survived.
  The first second after resume replayed 234 buffered frames (about 8 s of stale picture). A physical
  cable pull and outages longer than 30 s were not tested.
- 2026-09-29, ID 5, no break. All 40 alternating flag/fruit switches succeeded: 26–40 s each, average 29 s.
  Afterwards: smmu=0 usb=0, no watchdog restarts, no `wait failed` or `not ready`, dla-server active.
  Board available memory went from 285 to 262 MB, which may just be cache. Watch it in the ID 4 soak.
- 2026-09-29, ID 6, **not run:** `nmcli dev disconnect wls5f3` also cuts the remote (Tailscale)
  session that ran these tests, and if eduroam re-auth fails the PC is unreachable. Run it with
  someone at the PC.
- 2026-09-29, ID 7, **broke:** flag was already live, so the first run was a no-op (Mender reported
  already-installed). Rerun with `sw fruit`:
  - The link went down at 6 s, during "board downloading".
  - Release at 61 s was ignored. The phase stayed "board downloading" until the link returned at 181 s.
  - The board's http_resumer logged a read error 45 s after link-up and retried 60 s later.
  - Install finished at 311 s. Only then was the session released, 250 s after Release was pressed.
  - Longer outages run until the resumer gives up (10 retries) or the 900 s poll timeout.
  - Workaround: §3 ("Loop blocks during deploys").
  - Fix, not done because it changes queue semantics: run the deploy as a task that the loop races
    against `release_reason`/timeout, and abort the Mender deployment on cancel.
- 2026-09-29, ID 11, **broke as predicted** (accepted, §1). After a restart with user model t17 live,
  the catalog is back to fruit/flag/imagenet, the board still reports `t17`, and the old job_id
  returns 404. Workaround: rejoin and re-upload (§3).
- 2026-09-29, ID 12, no break. Five SSE viewers each got about 29 fps with DLA 9–10 Hz. On the board,
  dla-server used 190 % CPU and each poller 5 %; 19 % CPU was idle and 276 MB of memory was available.
  There was no OOM. A switch to flag with 5 viewers took 32 s, with about 15 s dark. All 5 board
  pollers exited when the viewers closed. 5 tabs is safe; more was not tried.
- 2026-09-29, ID 13: (a) confirmed by reading the code. The install cell only checks that `openvino`
  is importable, not that its version is `<2026.5`. It is latent: 2026.4.0 is the newest release on
  PyPI today. (b)–(d) need student laptops and were not run.
- 2026-09-29, ID 14, **likely break, not proven:** cold `snapshot_download` from the PC on eduroam
  fetched 206 MB in 468 files in 105 s. It is limited by requests (about 4.5 files/s), not bandwidth.
  20 students means 4 GB and about 9,400 anonymous Hugging Face requests from one NAT IP, so a 429 is
  plausible. Workaround: put the prepared `data/` folder (train/val split) on the USB stick with
  `fruit-v1.pt`. The notebook skips the download when `DATA/val` exists.
- 2026-09-29, ID 15, no break. The upload at 98 s into a 150 s slot was live at 128 s, with 20 s left
  (upload to live took about 30 s). An upload after about 120 s would lose to the timeout. The
  `expiring_soon` warning at 120 s covers this.
- 2026-09-29, ID 17, **broke, fixed:** tab B's upload got a 409, but it had already overwritten
  `models/t17/*`. The compiled `t17/graph.bin` was byte-identical to `fruit-v1/graph.bin`, so the
  rejected upload's weights were deployed silently. Fix in `main.py`:
  - read `model.bin` into memory;
  - then run the idle check, write the files and call `build_model()` with no `await` in between.
  - Rerun: B got a 409 and `t17/graph.bin` matched fruit-demo. Regression assertion added to
    `test_main.py`.
- 2026-09-29, ID 18, **broke (confirmed by accident), fixed:** a `test_main.py` run against the old
  `main.py` uploaded as `fruit-v1`.
  - It zeroed `models/fruit-v1/model.bin` and rewrote `name`.
  - Restored `model.bin` from a byte-identical copy (md5 `dde4e152…`, same as before the tests) and
    `name` from git.
  - Fix: `main.py` also refuses the reference directory's name. Live check: HTTP 400, reference md5
    unchanged.
- 2026-09-29, ID 19, no break. After SIGSTOP of dla-server at 12:37:22, frames resumed at 12:38:10
  (48 s) on the same stream. The watchdog did not loop.
- 2026-09-29, ID 23, **broke, fixed:**
  - A trailing blank line was rejected with "needs one non-empty label per line".
  - A BOM was accepted, with class 0 = `'﻿apple'`. `.strip()` in board_infer does not remove
    U+FEFF.
  - 16 lines were rejected with a clear message ("output is [1,15] but categories.txt has 16 lines").
  - Fix in `model_upload.read_categories`: `decode("utf-8-sig")` + `rstrip()`, plus a self-check
    assertion. Live recheck: blank-line upload built, BOM upload shows `'apple'`.
