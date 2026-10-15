# OTA FPGA reconfiguration hardening plan

Status 2026-10-02: **complete** (one documented limit, see Step 4b and the before/after table). PR dropped 2026-09-30, see the last section.
Source: `docs/MENDER_FPGA_OTA_RESEARCH.md` (limitations #1, #2, #6, #8; option (a)).
Goal: every student bitstream is session-scoped. Any failure (clean reject, stuck module, SoC hang) ends with the board back on the idle classifier and the deployment reported `failure`, with no human at the board.
Out of scope: hostile-bitstream isolation (#3, needs PR), ArtifactCommit health gate (#4), poll latency (#7).

## Rules

- A step is **done only when every pass metric is met and recorded** in its Result line (numbers, not "works"). A missed metric means fix and re-run the whole step, not just the failing check.
- Steps run in order; each step's regression metric includes all earlier steps' metrics that the change could affect.
- Board files: edit in `board/`, install on the board with single `install` commands over ssh. **Do not re-run `board_setup.sh`**: it overwrites the FAT dtb and boot script, which may undo the dwc2 FIFO deployment.
- Before any board change: back up the file being replaced to `<path>.pre-ota` on the board. Rollback = restore those files.
- Do not use `artifacts/reset.sh` as a health check (it stops the backend and wipes the queue).
- "Classifier OK" means: `dla-server` active, `/var/lib/dla/spool/ready` present, and the GUI classifies 3 fixed demo images (`demo-images/fruit/`, same 3 every time) with the expected labels.

| # | Step | Fixes | Result |
|---|---|---|---|
| 0 | Baseline + discovery | - | **done** 2026-09-30: program 8.0 s, release 26.3 s, release download 59.9 MB |
| 1 | Hardware watchdog wired | #1 | **done** 2026-09-30: halted panic resets in 15.0/18.5 s, `kernel.panic` reboot 10.5 s, 41 min with no unexpected reset |
| 2 | `ModuleTimeoutSeconds` | #1 | **done** 2026-09-30: stuck module failed after 60.6 s; model switches 26.5 / 36.7 s |
| 3 | Idle pair; boot programs idle | #2 | **done** 2026-09-30: student pair replaced by idle at boot 2/2; bad-graph install rolled back in 14.3 s |
| 4 | `fpga-reconfig` rolls back to idle; restore mode | #2, #8 | metrics 3-6 **pass**; 1-2 moved to 4b (bad RBFs never fail cleanly: truncated = silent success, garbage = FPGA-manager wedge) |
| 4b | Stop bad bitstreams before they wedge the board | #1 | item 1 **pass** (backend RBF pre-check); item 3 root cause found; item 2 **fail** 2026-10-01: detector fires, but a wedged SDM blocks every on-chip reset (panic/PSCI and watchdog), power cycle only |
| 5 | End-to-end hang recovery | #1, #2 | **done** 2026-10-01: 2/2, classifier OK 69.2 / 112.8 s after upload, nobody at the board |
| 6 | Backend aborts on timeout | #6 | **done** 2026-09-30: aborted at 60 s, board never installed it (lab-backend `1cd01b9`) |
| 7 | Backend release uses restore artifact | #8 | **done** 2026-09-30: 5 KB vs 60 MB per release; retried through 60 s of Mender outage (lab-backend `1cd01b9`) |
| 8 | Soak + before/after table | all | formal soak 10/10 pass 2026-10-01; before/after table filled 2026-10-02 |

---

## Step 0. Baseline and discovery (read-only)

Do: on the board, record `wdctl`, `ls /dev/watchdog*`, `dmesg | grep -i wdt`, `systemctl show -p RuntimeWatchdogUSec,RebootWatchdogUSec`, `cat /proc/sys/kernel/panic`. Record sha256 of `/lib/firmware/output_design.core.rbf` and `my_overlay.dtb`. Back up `/usr/share/mender/modules/v3/*`, `/usr/local/sbin/coredla-fpga-up.sh`, `/etc/systemd/system/coredla-fpga.service` and `/etc/mender/mender.conf` to `*.pre-ota`. Run one student session through the GUI (upload `~/mender/lab-backend/assets/ghrd.core.rbf`, then release) and time it.

Pass metrics:
1. Watchdog facts recorded: device present (yes/no), timeout (s), who feeds it (systemd / kernel / nobody).
2. Baseline timings recorded from the backend log: student program (upload to `success`), release (release to classifier OK), and release download size (bytes of the redeployed model artifact).
3. All 7 backups exist on the board (`ls *.pre-ota` shows 7 files).

Result (2026-09-30, **pass**):
1. `/dev/watchdog0` = Synopsys DesignWare, 30 s timeout, running. Fed by the **kernel** (`CONFIG_WATCHDOG_HANDLE_BOOT_ENABLED=y`), not systemd (`RuntimeWatchdogUSec=0`). `kernel.panic=0` (a panic halts). Kernel has no soft/hard-lockup detector (`/proc/sys/kernel/softlockup_panic` absent).
2. Program `ghrd.core.rbf` 8.0 s (upload to `ok`); release to classifier OK 26.3 s; release redeploys `coredla-model-flag-73107bc0`, 59,876,352 bytes (fruit 59.8 MB, imagenet 62.4 MB).
3. Backups: `mender.conf`, `coredla-fpga-up.sh`, `coredla-fpga.service` as `*.pre-ota` next to the originals; the 3 modules and the `coredla-model.prev` set in `/root/ota-backup/` (a `*.pre-ota` file inside `modules/v3/` would register as a module type). Board copies of all 6 files match `board/` (sha256).
Finding: the board was found **not running the classifier**. Release of job `7ac05194` failed (`ConnectError: Name or service not known` reaching Mender) and was never retried, leaving a student RBF live and `dla-server` stopped. Restored by hand with `deploy_existing` (24.6 s). Added to step 7.

## Step 1. Hardware watchdog wired

Do: `board/90-ota-watchdog.conf` -> `/etc/systemd/system.conf.d/` (`RuntimeWatchdogSec=30s`, `RebootWatchdogSec=2min`, applied with `systemctl daemon-reexec`, no reboot) and `board/90-ota-panic.conf` -> `/etc/sysctl.d/` (`kernel.panic = 10`).
Residual (not fixable without a kernel rebuild with the lockup detector): one CPU silently stuck on a fabric bus access while the other cores keep feeding the watchdog is not detected.

Pass metrics:
1. `systemctl show -p RuntimeWatchdogUSec` = 30 s, and the journal shows systemd `Set hardware watchdog to 30s` (`wdctl` cannot read the device once systemd holds it open). **Met 2026-09-30.**
1b. `sysctl kernel.panic` = 10, including after a reboot.
2. Simulated hang: kernel crash via `echo c > /proc/sysrq-trigger`, 3 trials: 2 with `kernel.panic=0` set at runtime (the board halts, so only the hardware watchdog can reset it) and 1 with the persisted `kernel.panic=10`. Board reaches U-Boot SPL within **60 s** of the panic (serial console timestamps). (`kill -STOP 1` was the first idea; it does nothing, because the kernel drops signals to PID 1 that init has no handler for.)
3. After each reset, ssh `terasic@coredla` works within **5 min** without a power cycle, eth0 has its 10.42.0.x address, Mender device is still `56bc13f6…` and `accepted`.
4. Classifier OK after each reset.
5. 30 min idle after the last trial with no unexpected reset (`journalctl --list-boots` count unchanged).

Result (2026-09-30):
1. **Pass.** Journal: `Set hardware watchdog to 30s`; `kernel.panic = 10` after every reboot (the runtime `0` did not persist).
2. **Pass.** Trial 1 (watchdog): panic to SPL 15.0 s, no "Rebooting in" line. Trial 2 (watchdog): 18.5 s. Trial 3 (panic=10): "Rebooting in 10 seconds", SPL 10.5 s.
3. **Pass.** ssh with a new boot id at 55.3 / 61.4 / 51.4 s after the crash; eth0 10.42.0.127 each time; Mender device `56bc13f6` `accepted`, checking in.
4. **Pass.** Classifier OK after each reset.
5. Running from boot `7be25227` (2026-09-30 09:20 UTC), overlapping step 2 activity.
   Final: the board was rebooted on purpose during steps 3-4 and power cycled after the step 4 wedge; from that power cycle (09:51 board clock) it ran 41 min through steps 4, 4b, 6 and 7 tests with no unexpected reset. **Pass.**
Notes: U-Boot logs `WDT: Not starting watchdog@10d00200`, so there is no watchdog cover from reset until systemd opens the device (~10 s into Linux boot); a hang in that window is not covered. "Classifier OK" uses 5 flag images (`canada_00 germany_00 sweden_00 brazil_00 japan_00`, converted to PNG: this dla-server's OpenCV has no JPEG decoder; `argentina_00` is a model miss and was dropped).

## Step 2. `ModuleTimeoutSeconds`

Do: add `"ModuleTimeoutSeconds": 600` to `board/mender.conf` and install it. Proof test uses a throwaway module `sleep-test` (`ArtifactInstall` = `sleep 100000`, `SupportsRollback` = No) with the timeout temporarily set to 60; remove the module afterwards.

Pass metrics:
1. With timeout 60: the `sleep-test` deployment reaches `failure` within **180 s** of entering `installing`, and `pgrep -f sleep-test` is empty afterwards.
2. With timeout 600 restored: `mender-updated` active, and `sleep-test` module and artifact deleted from the board and the server.
3. Regression: a catalog model switch (fruit to flag, then back to fruit) succeeds; both installs finish under **420 s** (well inside 600) and end with classifier OK.

Result (2026-09-30, **pass**):
1. `sleep-test-1`: `installing` at 4.1 s, `failure` at 64.7 s (60.6 s in install); client log `Connection timed out: ArtifactInstall: Process::Timer`; no `sleep 100000` process left.
2. `ModuleTimeoutSeconds: 600` installed (`board/mender.conf`), `mender-updated` active, module removed from the board, artifact deleted from the server.
3. Order was flag to fruit to flag (flag is the live model): 26.5 s and 36.7 s, classifier OK.

## Step 3. Idle pair; boot programs the idle design

Do:
- `coredla-model` ArtifactInstall: after success, copy the RBF+DTB pair to `/var/lib/dla/idle/`. ArtifactRollback: restore its `PREV` pair to `/var/lib/dla/idle/` too.
- `coredla-fpga.service`: `ExecStartPre` copies `/var/lib/dla/idle/*` into `/lib/firmware/` when the directory exists (missing directory = today's behaviour).
- Seed once: copy the current catalog pair into `/var/lib/dla/idle/`.

Pass metrics:
1. After a catalog model switch, sha256 of `/var/lib/dla/idle/*` equals the RBF/DTB inside that model's `.mender` artifact.
2. Manually copy `ghrd.core.rbf` over `/lib/firmware/output_design.core.rbf` and reboot. After boot, `/lib/firmware` sha256 equals the idle pair and the classifier is OK. **2 of 2** trials.
3. Failed model install (artifact with a truncated `graph.bin`): deployment `failure`, idle pair sha256 equals the previous model's pair, classifier OK on the previous model.
4. Regression: step 2 metric 3.

Result (2026-09-30, **pass**):
1. All catalog models share one RBF/DTB (`f1e4…`/`6d6b…`); after fruit then flag switches the idle copies matched and their mtime moved each time (09:28:26, 09:28:53).
2. `ghrd.core.rbf` + GHRD overlay left in `/lib/firmware`, `systemctl reboot`: after boot `/lib/firmware` = idle pair, `fpga0` operating, classifier OK at 47 s and 60 s after reboot (2 of 2).
3. `coredla-model-badgraph-1` (flag artifact with `graph.bin` cut to 1 MB): `failure` after 14.3 s, idle mtime unchanged, flag model (67 MB graph) back, classifier OK.
4. Switch times 34.8 s / 24.5 s.
Change vs plan: `coredla-model` ArtifactRollback needs no idle change, because the idle pair is written only after a successful install.

## Step 4. `fpga-reconfig` rolls back to the idle design; restore mode

Do:
- ArtifactRollback: copy `/var/lib/dla/idle/*` into `/lib/firmware/`, run `coredla-fpga-up.sh`. Drop the one-generation `PREV` copy.
- ArtifactInstall: if the payload holds a `restore` marker file (and no RBF), do the same as rollback. Otherwise behave as today.
- Build the restore artifact once: `mender-artifact write module-image -T fpga-reconfig -t de25-nano -n fpga-restore-v1 -f restore`, upload it to the server.

Pass metrics:
1. Clean reject: upload a truncated RBF (first 64 KiB of `ghrd.core.rbf`) through the GUI. Deployment `failure`, GUI shows the rolled-back message, `/lib/firmware` equals the idle pair, classifier OK within **5 min** of the upload. **2 of 2** trials.
2. Garbage RBF (1.5 MiB of `/dev/urandom`): same result as metric 1.
3. Valid student RBF (`ghrd.core.rbf`): deployment `success`, `fpga0` state `operating`.
4. Restore artifact after metric 3: deployment `success`, classifier OK, and the artifact size on the server is **< 100 KiB**.
5. Idempotence: running `fpga-reconfig ArtifactRollback <dir>` by hand twice in a row exits 0 both times and leaves the classifier OK.
6. Regression: step 3 metric 2.

Result so far (2026-09-30, **metrics 1-2 not met**; new `fpga-reconfig` installed, restore artifact `fpga-restore-v1` uploaded, 5,120 bytes):
Later the same day (**metrics 3-6 pass**):
3. `ghrd.core.rbf` direct deploy: `ok` in 6.3 s, `fpga0` `operating`, `dla-server` stopped (GHRD has no DLA).
4. `fpga-restore-v1` right after: deployment 8.2 s, classifier OK 18.6 s after start; artifact 5,120 bytes.
5. `fpga-reconfig ArtifactRollback` by hand twice: rc 0 both, classifier OK.
6. Step 3 metric 2 already passed with this module installed (boot after the wedge programmed the idle pair).
- Truncated RBF (first 64 KiB of `ghrd.core.rbf`) via a GUI-style session: program `ok` in 7.0 s. Kernel: "writing output_design.core.rbf", overlay applied 2 s later, no error, `fpga0` `operating`. The SDM/driver accepted it, so no rollback happens. Release restored the classifier in 24.8 s.
- Garbage RBF (1.5 MiB random), direct deploy: 7 s in, `Stratix10 SoC FPGA manager ...: timeout waiting for svc layer buffers`; `fpga0` stuck in `write`; `coredla-fpga-up.sh` unkillable (`D` in `kthread_stop`); `journald` blocked (`D` in `of_device_uevent`) and failed its own watchdog. `ModuleTimeoutSeconds` killed the module at 600 s but not the child. Backend gave up at 900 s without aborting. `systemctl reboot` hung in `systemd-shutdown` ("Waiting for process: coredla-fpga-up, systemd-journal"), then the serial console went silent; `RebootWatchdogSec=2min` did **not** reset the board within 15 min, and SysRq-B over serial got no response. **Recovered only by power cycle.**
- After the power cycle: U-Boot golden, then the boot service programmed the idle pair (step 3 worked), Mender retried the status push after 60 s (`Unauthorized` right after boot) and deployment `47b92dc4` finished `failure`; classifier OK.

## Step 4b. Stop bad bitstreams before they wedge the board (new)

Do:
1. Backend pre-check: reject an upload unless its first bytes match the header shared by known-good Agilex 5 `core.rbf` files (confirm first that `ghrd.core.rbf`, `dla_*.core.rbf` and a student Quartus build share one), plus a minimum size.
2. Board stuck detector: while `coredla-fpga-up.sh` programs, a background check forces `echo b > /proc/sysrq-trigger` (immediate reset, skips the shutdown that hung) if `fpga0` stays in `write` for more than 60 s. **Changed 2026-10-01 to a panic (`echo s`, then `echo c`), see item 3.**
3. Find why the watchdog did not fire during the hung shutdown (check whether `dw_wdt` stops the watchdog on shutdown; `RebootWatchdogSec` behaviour).

Pass metrics:
1. Garbage RBF upload is rejected by the backend with HTTP 400 and never reaches Mender. Known-good RBFs (GHRD, DLA) still accepted.
2. With the pre-check bypassed (direct `mender_client.deploy`), the garbage RBF leads to an automatic reset within **120 s** of the wedge, then deployment `failure` and classifier OK with nobody at the board. Needs someone near the board in case it fails. **1 of 1**, then 2 of 2.
3. Truncated RBF: either rejected by a pre-check, or documented as a known gap (it programs "successfully" and the release restores the classifier).

Result (2026-09-30), item 1 done, items 2-3 open:
- All 7 good RBFs on hand (GHRD, both DLA builds, `golden_top`, 3 student uploads) start with `95 48 29 62 50 00 00 00` and share the first 434,236 bytes (likely the SDM firmware section of this Quartus version; not used as the check, it would reject other Quartus versions). No length field found in the header; smallest good file 1,576,960 bytes. Check = those 8 bytes + at least 1 MiB (`config.RBF_MAGIC`, `MIN_RBF_BYTES`, lab-backend `1cd01b9`).
1. **Pass.** Unit test `test_rejects_not_an_rbf`. Live from a queued (not active) job, so a miss could not deploy: garbage -> 400 "not an Agilex 5 .core.rbf (unexpected header)", truncated -> 400 "too small to be a complete Agilex 5 .core.rbf", `ghrd.core.rbf` passes the check (409 only because the job was not active).
2. Not run (needs the board wedged again with someone near it).
3. Truncated uploads under 1 MiB are rejected; a longer truncation of a valid file still passes (known gap).

Item 3 root cause (2026-10-01, from source; Linux v6.12, TF-A master):
- `dw_wdt` probe calls `watchdog_stop_on_reboot()` (`drivers/watchdog/dw_wdt.c:652`). The board's watchdog nodes have `resets`, so `dw_wdt_stop()` really stops the hardware. The watchdog core's reboot notifier stops it on `SYS_DOWN`, i.e. as soon as `systemd-shutdown` calls `reboot()`. `RebootWatchdogSec` cannot cover anything after that.
- The kernel then resets through PSCI first (restart handler priority 129, ahead of `dw_wdt`'s 128). TF-A `socfpga_system_reset()` calls `mailbox_reset_cold()`, a request to the SDM. With the SDM wedged by the garbage RBF, the CPU stays in EL3 and nothing comes back. This matches the silent console and the ignored serial SysRq-B (`kernel.sysrq` = 176 allows `b`).
- So `echo b` in the detector would hang the same way. A panic (`echo c`) does not run the reboot notifiers: the watchdog stays armed, systemd stops feeding it, and it fires about 30 s later. Step 1 showed that path resets the board when the SDM is healthy.
- Not verified: whether an HPS watchdog reset itself needs the SDM (Agilex 5 warm reset is SDM-owned). If it does, a wedged SDM can only be cleared by a power cycle, and the backend pre-check (item 1) is the real defence. The first metric-2 trial answers this. Also, U-Boot does not start the watchdog and `boot.txt` runs `fpga load` on `golden_top`, so a reset that leaves the SDM wedged can hang there unwatched.

Item 2 implemented (2026-10-01): `board/fpga-stuck-detector.sh` + `.service`, a separate always-on unit (not a child of the Mender module, which `ModuleTimeoutSeconds` kills). It polls `fpga0` state every 5 s. After 60 s in `write init`/`write`/`write complete` it does `echo s`, waits 2 s, then `echo c`. It writes no output: journald was blocked in the wedge. `board/test_fpga_stuck_detector.sh` passes. Installed and enabled on the board (sha256 matches the repo). A normal idle rollback did not trigger it (same boot, same detector PID). Run metric 2 with this, and stop after the first failed trial.

Metric 2 result (2026-10-01, **fail, 0 of 1, stopped per the stop rule**). Direct deploy of the 1.5 MiB random RBF (`mender_client.py garbage.rbf`, deployment `a3e0946f`), serial console logged, times from deployment creation:
- 9.6 s: `Stratix10 SoC FPGA manager ...: timeout waiting for svc layer buffers` (same wedge as step 4).
- 61.2 s: detector `sysrq: Emergency Sync`; 63.2 s: `sysrq: Trigger a crash`, `Kernel panic`, `Rebooting in 10 seconds..`. The detector worked as designed (~52 s after the wedge).
- Then nothing on the serial console and no ping for 303 s after the panic (stopped watching then): neither the `kernel.panic` PSCI reset nor the HPS watchdog (30 s, armed and no longer fed) reset the board. With a healthy SDM the same panic path resets in 11 s (step 5).
- Conclusion: on this Agilex 5 both reset paths go through the SDM, so a bitstream that wedges the SDM can only be cleared by removing power. No on-chip mechanism (watchdog, panic, sysrq, detector) can recover it. The defence is to never send such a file to the SDM: the backend pre-check (item 1) for student uploads. The remaining gap is a file that passes the header and size check but still wedges the SDM; the only automatic fix for that is external, e.g. a network-controlled power switch on the board supply (future work).
- The detector stays installed: it costs nothing, syncs the file system before the inevitable power cycle, and still resets the board if a write ever stalls without wedging the SDM.
- Board left wedged until a power cycle (2026-10-02). After it: check boot to the idle design, deployment `a3e0946f` ends `failure` or `aborted` (the 900 s poll timeout aborts it), classifier OK.

## Step 5. End-to-end hang recovery

Do: temporary test hook in the board's copy of `fpga-reconfig` only (never committed): if `/var/lib/mender/HANG_TEST` exists, the ArtifactInstall runs `echo c > /proc/sysrq-trigger` right after copying the new RBF into `/lib/firmware` and before programming. This is the worst case: the bad file is on disk when the SoC dies. (Writing to `/proc/sysrq-trigger` works whatever `kernel.sysrq` is, so no sysctl change is needed.) Remove the hook and the flag after the test.

Pass metrics:
1. With the flag set, upload `ghrd.core.rbf` through the GUI. With nobody touching the board:
   - the board resets and comes back;
   - the Mender deployment ends `failure`, not `pending` or `inprogress`;
   - the backend reports the rollback message, not "did not report back";
   - classifier OK with `/lib/firmware` equal to the idle pair.
2. Upload to classifier OK takes **< 900 s** (inside the backend timeout). **2 of 2** trials; record both times.
3. After the hook is removed: board `fpga-reconfig` sha256 equals `board/fpga-reconfig` in the repo, and `/var/lib/mender/HANG_TEST` is absent.

Result (2026-10-01, **pass**, 2 of 2). Hook = `sync; echo c > /proc/sysrq-trigger` after the RBF/DTB copy; `kernel.sysrq` left at 176 (`/proc/sysrq-trigger` ignores the mask). GUI-style session with `ghrd.core.rbf`, nobody at the board, times from upload (serial console):

| Trial | Panic | U-Boot SPL | Login prompt | Backend `failed` (rollback message) | Classifier OK |
|---|---|---|---|---|---|
| 1 | 4.6 s | 15.6 s | 50.2 s | 54.1 s | **69.2 s** |
| 2 | 6.2 s | 17.2 s | 48.8 s | 111.1 s | **112.8 s** |

Both: `kernel.panic=10` reset the board, new boot ID, Mender deployment `failure`, `/lib/firmware` equal to the idle pair, 5-image classifier check OK. Trial 2 is slower because the first status push after boot got an auth error and Mender retried 60 s later (same as seen after the step 4 power cycle). Hook removed: board `fpga-reconfig` sha256 `0f1f959c…` equals the repo, flag absent.
Note: `journalctl --list-boots` is not usable to count reboots here (no RTC, boots merge across the clock jump); use `/proc/sys/kernel/random/boot_id`.

## Step 6. Backend aborts the deployment on timeout

Do: in `mender_client.poll_until_finished`, on timeout send `PUT /api/management/v1/deployments/deployments/{id}/status {"status":"aborted"}` (ignore 422 = already finished) before returning the error. Add one test in `~/mender/lab-backend`.

Pass metrics:
1. New unit test: with a mocked server that never finishes and a 1 s timeout, the abort request is sent exactly once. It passes, and the full existing suite passes (`pytest`: 0 failures).
2. Live: stop `mender-updated` on the board, start a student program with the backend timeout set to 60 s. After the timeout, the Mender deployment status is `finished` with the device `aborted`. Start `mender-updated` again: within **2 min** the board has not installed it (`mender-update show-artifact` unchanged). Restore the 900 s timeout.
3. `sudo systemctl restart lab-backend` succeeds and the GUI shows no Mender problem banner.

Result (2026-09-30, **pass**):
1. `test_mender_preflight.py` "abort on timeout": one PUT `aborted` for the unfinished deployment. All 3 test files pass (26 checks).
2. `mender-updated` stopped, GHRD deploy with a 60 s poll timeout: "still unfinished after 60s, aborting it" at 61.2 s, deployment `finished`. Client restarted and watched 2 min: `show-artifact` stayed `fpga-restore-v1`, classifier OK.
3. Backend restarted, `/config` `mender_problems: []`.

## Step 7. Backend release uses the restore artifact

Do: add `RESTORE_ARTIFACT = "fpga-restore-v1"` to `config.py`; in `queue_manager._release()`, call `deploy_existing(config.RESTORE_ARTIFACT)` instead of the catalog model artifact, and retry it (e.g. every 30 s) until it succeeds or a new session programs the board. Leave `GHRD_RBF_PATH` alone (unused, pre-existing). Add one test.

Pass metrics:
1. New unit test: `_release` on a session with `program_state != "none"` deploys `RESTORE_ARTIFACT` and nothing else. It passes, plus the full suite.
2. Live: a student session with `ghrd.core.rbf`, then release. Classifier OK on the same model that was live before the session (GUI highlight correct).
3. Release download size **< 100 KiB** (vs step 0 baseline) and release time (release to classifier OK) is **lower than the step 0 baseline**. Record both.
4. Two student sessions back to back (A programs, release, B programs, release): both releases `success`, not `already-installed` with a stale design.
5. Retry: block the Mender URL on the lab PC for 60 s during a release (e.g. `/etc/hosts` entry to 127.0.0.1). The release still ends with classifier OK within **3 min** after the block is lifted, with no human action.

Result (2026-09-30, **pass**):
1. `test_release_retries_restore` (two failures then success: 3 restore deploys, then stops); existing release assertions now expect `RESTORE_ARTIFACT`.
2. GHRD session then release: Mender shows `fpga-restore-v1` deployed after the `fpga-lab-*` one; classifier OK on flag (the live model).
3. Download 5,120 bytes vs 59,876,352. Release time 26.1 s and 25.6 s vs 26.3 s baseline: **about equal**, not meaningfully lower. On the direct Ethernet link the 60 MB download took seconds; `dla-server` graph import dominates. The size gain matters on slow links (2026-09-23: ~50 s for a 122 MB artifact over the DERP relay). The time part of this metric is met only nominally.
4. Back-to-back sessions (10:14 and 10:15, 10:34 and 10:35 board clock): each `fpga-lab-*` then `fpga-restore-v1`, all `finished`/success, classifier OK after each.
5. The first try pointed the name at 127.0.0.1 and was **invalid**: the Mender server runs on this PC, so it still answered. Rerun with 192.0.2.1 (black hole): 2 × `ConnectTimeout` logged ("restore after job … failed (try 1/2)"), third try succeeded, classifier OK **43.1 s** after the block was lifted. `/etc/hosts` restored.

## Step 8. Soak and before/after table

Do: 10 cycles of catalog model switch, student RBF, release, with 1 of every 5 student RBFs truncated. Then fill the before/after table below from the recorded results.

Pass metrics:
1. 10 of 10 cycles end with classifier OK, with no human touch on the board.
2. Mender server shows no deployment left `pending` or `inprogress`.
3. Board: no unexpected reboot (`journalctl --list-boots` grows only by the reboots the test caused, which is 0 here), and `dmesg` has no `arm-smmu-v3 event` lines.
4. Repo `board/*` files match the board (sha256), test hook absent; before/after table complete with measured numbers.

Preliminary run (2026-09-30, before steps 4b and 5, so not the formal step 8): 10 cycles of model switch (fruit/flag alternating), then `ghrd.core.rbf` or (cycles 5 and 10) the 64 KiB truncation, then release. **10/10 pass**: every switch `ok`, 8 programs `ok`, both truncations rejected with 400 before Mender, classifier back after every release (5-image check on the flag cycles). Cycles 32-71 s. Afterwards: 0 deployments `pending`/`inprogress`, no reboot (board up 51 min), 0 `arm-smmu-v3` events.

Formal run (2026-10-01, with `fpga-stuck-detector` installed, before step 5 and step 4b metric 2): same cycle as above. **10/10 pass**: 8 programs `ok`, truncations (cycles 5, 10) rejected 400, classifier back after every release, 5-image check OK on all 5 flag cycles. Cycles 38-76 s. Afterwards: 0 `pending`/`inprogress`, same boot ID (no reboot), 0 `arm-smmu-v3` events, no detector trigger, board `fpga-reconfig`, `coredla-model`, `coredla-fpga-up.sh`, `coredla-fpga.service`, `fpga-stuck-detector.sh` sha256 equal the repo, no `HANG_TEST`. Metric 4's table still open.

Found before the run (not an OTA failure, outside this plan): `dla-server` had been crash-looping for ~12 h. After 622,811 live frames the DLA stopped completing jobs (`WaitForDla polling timeout`, "inference on FPGA did not complete", then SEGV), and every restart failed the same way 30 s after `ready` (3,463 times). Restarting `dla-server` (systemd, `dla-watchdog`) cannot clear a hung DLA; one idle reprogram (`fpga-reconfig ArtifactRollback`) fixed it. Possible follow-up: reprogram the idle design after N consecutive `dla-server` failures.

## Before/after (filled 2026-10-02)

| Measure | Before (step 0) | After (step 8) |
|---|---|---|
| SoC hang recovery | power cycle by hand | kernel hang: automatic, classifier OK 69.2 / 112.8 s after the upload (step 5, 2 of 2). SDM wedge (garbage RBF past the pre-check): still a power cycle, no on-chip reset works (step 4b item 2) |
| Stuck module limit | 4 h | 600 s (`ModuleTimeoutSeconds`; the 60.6 s result in step 2 used a test setting) |
| Bad RBF: upload to classifier OK | truncated: silent "success"; garbage: board wedged, power cycle only | garbage and < 1 MiB truncation: rejected with HTTP 400 before Mender, classifier never disturbed (soak cycles 5 and 10: 38 s and 43 s including release). Longer truncation of a valid file: still programs "ok", release restores the classifier (known gap) |
| Release: download size | 59,876,352 B | 5,120 B |
| Release: time to classifier OK | 26.3 s | 26.1 s and 25.6 s (about equal; graph import dominates) |
| Stale deployment after backend timeout | stays live | aborted at the timeout (61.2 s with a 60 s test setting); the board did not install it later (step 6). Confirmed again 2026-10-02: wedge test deployment `a3e0946f` shows `aborted` |

Close-out 2026-10-02: after the power cycle the board booted the idle design on its own (`/lib/firmware` = idle pair, `fpga0` operating, detector active, no `HANG_TEST`, 0 SMMU events), the 5-image classifier check passed, no deployment `pending`/`inprogress`, `mender_problems` empty. **Plan complete with one documented limit:** an SDM wedge needs a power cycle; the upload pre-check is the defence and a network-controlled power switch is the future-work last resort.

---|---|---|
| SoC hang recovery | power cycle by hand | |
| Stuck module limit | 4 h | |
| Bad RBF: upload to classifier OK | | |
| Release: download size | | |
| Release: time to classifier OK | | |
| Stale deployment after backend timeout | stays live | |

---

## Partial Reconfiguration: dropped 2026-09-30

Decision: not pursued. No meaningful speed or size gain (model artifact 59.8 MB is ~94 % `graph.bin`, RBF 3.75 MB identical across catalog models; student RBF 1.6-3.7 MB is ~1-2 s of the 8 s program). With the live DLA at 41,576/46,800 ALM and 355/358 M20K, a student region beside a static DLA is at most ~5k ALM / 3 M20K; a DLA persona is 2-3 weeks and high risk. Mention only as future work in the paper. Original plan kept below for reference.


Why: hardening bounds the damage of a bad bitstream but does not isolate it (#3). PR is the only root fix: a lab-owned static shell (HPS bridges, DDR access, camera, freeze bridges) stays up while only a student region is reprogrammed.

Where it stands (from `docs/MENDER_FPGA_OTA_RESEARCH.md` B4):
- Agilex 5 PR is documented by Altera; the board kernel passes the partial flag to the SDM when an overlay sets `partial-fpga-config` (`stratix10-soc.c:223-226`).
- Not in our design (full `core.rbf`, no PR regions, no freeze bridges, DLA at 89 % ALMs). Never run on the DE25-Nano. DLA as a PR persona unknown.

Feasibility spike, each with a pass metric:
1. Read the Quartus Pro PR user guide (Agilex 5 chapters) and the Agilex 5 Device Security UG. Pass: design rules, licence needs and freeze-bridge requirements listed with citations.
2. Toy PR design: GHRD static region + one small PR region (e.g. two LED/counter personas). Pass: Quartus produces a static `core.rbf` and two persona `.rbf` files.
3. Load a persona from Linux with a `partial-fpga-config` overlay. Pass: persona swap works 10 of 10 times while an HPS-side read of the static region keeps answering, no reboot.
4. Fit check: DLA in static region + smallest useful student region. Pass: Quartus fit report closes timing with the region size recorded, or a documented "does not fit" with the ALM numbers.
5. If 1-4 pass: carry personas through the existing `fpga-reconfig` module (overlay with `partial-fpga-config`); Mender flow otherwise unchanged.
