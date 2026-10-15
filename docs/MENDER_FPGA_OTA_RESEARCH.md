# Mender OTA for FPGA reconfiguration on Agilex 5: mechanism, limits of the current design, alternatives

Scope: Mender OSS Deployments (server 4.1.x, client `mender-client4` 5.x) as used to reprogram the DE25-Nano (A5EB013BB23BE4SR1) fabric; Agilex 5 configuration mechanisms; limitations of this repo's architecture; better options. Research date 2026-09-30. Read-only: nothing was run on the board or the Mender server; nothing committed.
Rules: primary sources only (Mender docs/source, Altera docs, kernel.org, the board's own kernel tree, local code). Anything not confirmed at a primary source is tagged **UNVERIFIED**. Where a web page was read through a summarising fetch tool, the quote is short and the URL is given so it can be re-read.

Paths abbreviated: `LAB=~/mender/lab-backend`, `BRD=~/edge-ai-demo/board`, `SRV=~/mender/mender-server` (local OSS server checkout, commit b4d4770b), `KRN=~/coredla_work/de25_nano_bringup/linux` (source of the kernel running on the board, `git d7d192a9d "add support for de25-nano"`, 6.12.x), `MEM=~/.claude/projects/-home-fyp-student-edge-ai-demo/memory` (operator notes, not primary evidence for vendor behaviour; used only for observed board facts).

## Sources (keys used below)

Mender:
- [M1] Update Modules v3 file API: https://github.com/mendersoftware/mender/blob/master/Documentation/update-modules-v3-file-api.md
- [M2] Create a custom Update Module: https://docs.mender.io/artifact-creation/create-a-custom-update-module
- [M3] State scripts: https://docs.mender.io/artifact-creation/state-scripts
- [M4] Configuration options: https://docs.mender.io/client-installation/configuration-file/configuration-options
- [M5] Polling intervals: https://docs.mender.io/client-installation/configuration/polling-intervals
- [M6] Artifact format: https://docs.mender.io/overview/artifact
- [M7] Sign and verify: https://docs.mender.io/artifact-creation/sign-and-verify
- [M8] Standalone deployment: https://docs.mender.io/artifact-creation/standalone-deployment
- [M9] Delta update: https://docs.mender.io/overview/delta-update
- [M10] mender-connect: https://docs.mender.io/add-ons/mender-connect
- [M11] Client source: `src/mender-update/cli/cli.cpp`, `src/mender-update/daemon/states.hpp` in https://github.com/mendersoftware/mender
- [M12] mender-connect source `session/menderclient.go`: https://github.com/mendersoftware/mender-connect
- [M13] Device authentication: https://docs.mender.io/overview/device-authentication
- [M14] Introduction (modes, A/B vs Update Modules): https://docs.mender.io/overview/introduction
- [M15] Customize the update process: https://docs.mender.io/overview/customize-the-update-process
- [M16] Server source (local): `SRV/backend/services/{deployments,deviceconnect}`, `SRV/docker-compose.yml`

Altera / kernel:
- [A1] Agilex 5 Configuration Overview: https://docs.altera.com/r/docs/813773/25.3.1/device-configuration-user-guide-agilextm-5-fpgas-and-socs/agilextm-5-configuration-overview
- [A2] 2.3.5 Partial Reconfiguration: https://docs.altera.com/r/docs/813773/26.1/device-configuration-user-guide-agilextm-5-fpgas-and-socs/partial-reconfiguration
- [A3] Summary of Agilex 5 configuration features: https://docs.altera.com/r/docs/813773/26.1.1/device-configuration-user-guide-agilex-5-fpgas-and-socs/summary-of-agilex-5-configuration-features
- [A4] "Specifying Boot Order for Agilex 5 SoC Devices": https://www.intel.com/content/www/us/en/docs/programmable/813773/24-1/specifying-boot-order-for-soc-devices.html (page fetch redirects to a 404 redirector; text taken from the search-result excerpt of this page)
- [A5] RSU section, same guide: https://docs.altera.com/r/docs/813773/25.3.1/device-configuration-user-guide-agilextm-5-fpgas-and-socs/remote-system-update-rsu
- [A6] SoC HPS RSU example (E-Series Premium kit): https://altera-fpga.github.io/rel-24.3.1/embedded-designs/agilex-5/e-series/premium/rsu/ug-rsu-agx5e-soc/
- [A7] SoC fabric configuration from Linux (Agilex 7 example, same mechanism): https://altera-fpga.github.io/rel-24.3.1/embedded-designs/agilex-7/f-series/soc/fabric-config/ug-linux-fabric-config-agx7f-soc/ and https://www.rocketboards.org/foswiki/Documentation/Agilex7ConfiguringFPGAFabricFromLinux
- [A8] Agilex 5 E-Series Premium GHRD Linux boot examples (U-Boot `fpga load` / `bridge enable`): https://altera-fpga.github.io/rel-25.1/embedded-designs/agilex-5/e-series/premium/boot-examples/ug-linux-boot-agx5e-premium/
- [A9] DE25-Nano User Manual, 2025-09-05: https://mm.digikey.com/Volume0/opasdata/d220001/medias/docus/7704/P0804.pdf (text read via pdftotext; section 3.1/3.2, feature list p.5)
- [A10] Agilex 5 Device Configuration UG, "Device Security" chapter list: https://docs.altera.com/r/docs/813773/26.1/device-configuration-user-guide-agilextm-5-fpgas-and-socs/device-security (details live in Device Security UG, item 815428, not read)
- [K1] FPGA region DT binding: https://www.kernel.org/doc/Documentation/devicetree/bindings/fpga/fpga-region.txt
- [K2] FPGA region / manager API: https://docs.kernel.org/driver-api/fpga/fpga-region.html , https://docs.kernel.org/driver-api/fpga/fpga-mgr.html
- [K3] Board kernel tree (local): `KRN/drivers/fpga/stratix10-soc.c`, `KRN/drivers/firmware/stratix10-svc.c`, `KRN/drivers/fpga/of-fpga-region.c`, `KRN/arch/arm64/boot/dts/intel/socfpga_agilex5.dtsi`, `KRN/.config`
- [K4] Agilex5 FPGA configuration + partial reconfiguration patch series (Adrian Ng Ho Yin, 2026-06): read via the mirror https://ratatoskr.run/linux-devicetree/2026/06/17161273/t (lore.kernel.org returned an anti-bot block). Mirror, not the primary archive.

---

## Part A. Mender Deployments as it applies to FPGA

### A1. Lifecycle and client state machine
- Client daemon (`mender-update daemon`) states in source: Init, Idle, ScheduleNextPoll, PollForDeployment, SubmitInventory, UpdateDownload (+DownloadCancel), UpdateInstall, UpdateCheckReboot, UpdateReboot, UpdateVerifyReboot, UpdateBeforeCommit, UpdateCommit, UpdateAfterCommit, UpdateCheckRollback, UpdateRollback, UpdateRollbackReboot, UpdateVerifyRollbackReboot, UpdateRollbackSuccessful, UpdateFailure, UpdateSaveProvides, UpdateCleanup, EndOfDeployment; status reports use `SendStatusUpdateState` (ignore-failure or retry-then-fail). [M11 states.hpp]
- State-script view of the same machine: Idle, Sync, Download, ArtifactInstall, ArtifactReboot, ArtifactCommit, ArtifactRollback, ArtifactRollbackReboot, ArtifactFailure, each with Enter/Leave/Error. Normal order Idle -> Sync -> Download -> ArtifactInstall -> ArtifactReboot -> ArtifactCommit -> Idle. [M3]
- Server-side per-device statuses: pending, downloading, installing, rebooting, pause_before_*, success, failure, aborted, already-installed, noartifact, decommissioned. `SRV/backend/services/deployments/model/device_deployment.go:46-59`.
- Power loss / spontaneous reboot: "Mender will transition into an error state, such as ArtifactRollback or ArtifactFailure"; an error state repeats until it completes uninterrupted, so modules must be idempotent. [M2]

### A2. Update Modules v3 API (what a module can declare)
- Calls, one process per state, argv = `<State> <file-tree-dir>`; exit 0 = success, non-zero triggers the failure states; unknown calls must print nothing and exit 0. [M1]
- Order: [ProvidePayloadFileSizes] -> Download (or DownloadWithFileSizes) -> ArtifactInstall -> [NeedsArtifactReboot -> ArtifactReboot -> ArtifactVerifyReboot] -> ArtifactCommit -> Cleanup. Failure: ArtifactRollback (only if SupportsRollback != No and ArtifactInstall has started) -> [ArtifactRollbackReboot -> ArtifactVerifyRollbackReboot] -> ArtifactFailure -> Cleanup. [M1]
- `SupportsRollback` Yes/No; `NeedsArtifactReboot` No/Automatic/Yes (`Automatic` = Mender does one reboot itself). [M1]
- `ArtifactCommit` "must be used to remove/disable automatic rollback mechanisms ... makes the update permanent"; if it fails, ArtifactRollback and ArtifactFailure run. [M1] This is the only hook where a post-install health probe can still trigger rollback.
- `Download` may stream (`stream-next` named pipe + `streams/`); "must not install the update in the final location during Download, because checksums are not verified until after the streaming stage". Default: files are stored first under `files/`. [M1]
- `ModuleTimeoutSeconds` default 4 h; SIGTERM, SIGKILL one minute later. State scripts: `StateScriptTimeoutSeconds` 3600 s, `StateScriptRetryTimeoutSeconds` 1800 s; exit 21 = retry-later; exit 1 = abort + rollback. [M4], [M3]

### A3. Delivery model: poll only
- All client/server communication is client-initiated; no inbound port on the device. Defaults `UpdatePollIntervalSeconds` 1800, `InventoryPollIntervalSeconds` 28800; more frequent polling = more server load. [M5]
- `RetryPollIntervalSeconds`: values under 60 are ignored (60 s used), exponential back-off doubling every three failures up to the configured maximum. [M4] Our `RetryPollIntervalSeconds: 30` (`BRD/mender.conf:5`) therefore behaves as 60 s.
- Device fetches work at `GET /device/deployments/next` (`SRV/backend/services/deployments/docs/devices_api.yml:45`, route `api/http/routing.go:80`).
- Server-triggered early poll exists in the OSS server tree: `POST /api/management/v1/deviceconnect/devices/{id}/check-update` -> 202, or 409 "Device not connected"; it sends a `MenderClientCheckUpdate` websocket message. `SRV/backend/services/deviceconnect/docs/management_api.yml:56-77`, `api/http/router.go:53-54,111`, `api/http/management.go:768-805`. The device side (mender-connect) receives it and runs `mender-update check-update` as a subprocess. [M12] The CLI describes `check-update` as "Force update check". [M11 cli.cpp]
  - deviceconnect is in the base (non-enterprise) compose file: `SRV/docker-compose.yml:125-155`. mender-connect is Apache-2.0; docs classify Remote Terminal / File Transfer / Port Forward as the "Troubleshoot add-on" (plan-gated on hosted Mender) while "Mender Client integration" is not gated. [M10]
  - Creating a deployment does not trigger it: the only caller of the check-update route in the server tree is the device-configuration workflow (`SRV/backend/services/workflows/worker/workflows/deploy_device_configuration.json:27-31`). A caller (our backend) must hit the route explicitly.
  - **UNVERIFIED**: mender-connect is installed and connected on the board. `BRD/board_setup.sh:12-19` installs only the `mender-client4` package and enables `mender-authd`/`mender-updated` (`:37`); whether that package pulls in mender-connect was not checked.
- Remote terminal / file transfer / port forwarding ride the same websocket; not needed for OTA.

### A4. Authentication and identity
- Device sends identity attributes + public key; server issues a JWT after the auth set is accepted (manual accept, preauthorize, or mTLS). A changed identity or key creates a new auth set that needs a new acceptance. [M13]
- Our identity is the MAC (`mac=`). Observed: random eth0 MAC each boot created a new pending device and deployments to the old id hung `pending` (MEM `board-and-backend-access.md`, fixed 2026-09-22 by `10-eth0-mac.link`). Backend `preflight()` re-points `DEVICE_ID` at the single live accepted device and aborts leftover deployments (`LAB/mender_client.py:172-206`).

### A5. Artifacts
- Format: uncompressed tar `.mender` with name, version, compatible device types, checksums; optional signature; `Provides`/`Depends`; "ensures that the same Artifact is not deployed twice in a row" (name check); downloads can resume with HTTP range requests. [M6]
- `module-image` payload type = "Update Module" route; `-T` must equal the module filename in `/usr/share/mender/modules/v3`; `-f` repeatable. [M2] Alternative is dual rootfs A/B with bootloader flags. [M14]
- Size: server `max_image_size` default 10 GiB (`SRV/backend/services/deployments/config/config.go:47-48`); presigned download URL lifetime `download_expire_seconds` 900 s default (`:60-61`). Client-side download retries: `RetryDownloadCount` default 10, 60 s apart, not configurable. [M4]
- Signing: `mender-artifact write ... -k private.key` or `mender-artifact sign`; client enforces with `ArtifactVerifyKey(s)`; "If the ArtifactVerifyKey(s) option is set and Artifacts are not signed or the verification fails, the Mender Client will abort the update process"; verification is client-side only. [M7], [M4]
- Delta updates: "available in the Mender Enterprise plan and partially in Mender Professional"; server-side generation supports `rootfs-image` (from search-result text of docs.mender.io delta pages). [M9] Not applicable to a 3.6 MB RBF module artifact and not in OSS.

### A6. Standalone vs daemon
- Standalone: `mender-update install <URI|file>` then `commit` / `rollback`; requires stopping and disabling `mender-updated`; some states are omitted and state scripts behave differently. [M8], [M14] **UNVERIFIED**: daemon and standalone cannot be mixed on one device; docs say to stop the daemon.

### A7. Abort / stall behaviour
- Server abort (`PUT /deployments/{id}/status {"status":"aborted"}`) is rejected when the deployment already finished (422). `SRV/backend/services/deployments/api/http/api_deployments.go:1360-1385`. A device learns of an abort when its next status report returns 409 (`ErrDeploymentAborted`, `:1532-1533`); client has `UpdateDownloadCancelState`. [M11 states.hpp] **UNVERIFIED**: what the client does when the abort arrives while a module is inside ArtifactInstall (it cannot preempt a running module process per [M1]; only ModuleTimeoutSeconds kills it).
- Stalled download: docs give retry count, not a stall timeout. [M4] Observed ~14 min to detect a stalled download on a 110 KB/s link (MEM `board-and-backend-access.md`, 2026-09-23). Mechanism inside `http_resumer`: **UNVERIFIED** (source file not readable at the guessed path).

### A8. OSS vs Enterprise items relevant here
- Enterprise-only per docs: delta update server generation, Mender Orchestrator. [M9], [M14] Synchronized updates / pause states were removed in client 4.0. [M15]
- Full OSS/Enterprise feature matrix: **UNVERIFIED** (docs server overview has no comparison list; `SRV/docker-compose.enterprise.yml` exists separately).

---

## Part B. Agilex 5 configuration mechanisms

### B1. Schemes and the SDM
- Every Agilex 5 device has an SDM that manages configuration and security. Schemes: Avalon-ST (x8 dedicated SDM pins, x16 via GPIO), JTAG (highest priority, overrides MSEL), CvP (SoC: only in FPGA-first mode), Active Serial normal and fast (quad SPI flash, 3/4-byte addressing). RSU: "available in all active schemes with quad SPI flash". PR: "supported across all configuration schemes". [A1], [A3]
- SoC boot order is either FPGA First (SDM configures fabric, then HPS SDRAM pins, loads FSBL, releases HPS; "FPGA First option does not allow FPGA reconfiguration by using HPS") or HPS First (SDM configures HPS SDRAM pins, loads FSBL, releases HPS; HPS later configures FPGA I/O and fabric; "Early I/O Release"; INIT_DONE waits for HPS software). [A4] HPS-first is therefore a precondition for the Linux/U-Boot reprogram path.
- HPS-driven configuration: HPS software sends RECONFIG / data-submit / status mailbox commands to the SDM through the service layer (SMC to ATF). Kernel side: `stratix10-soc` FPGA manager, `COMMAND_RECONFIG`, `COMMAND_RECONFIG_DATA_SUBMIT`, `COMMAND_RECONFIG_STATUS`. `KRN/drivers/fpga/stratix10-soc.c:216-262,305,349,401`. Timeouts: request 5 s, buffer 5 s (`KRN/include/linux/firmware/intel/stratix10-svc-client.h:75-76`); `write_complete` note "time taken to process this is close to 600ms" (`stratix10-soc.c:388-392`); overlay `config-complete-timeout-us = 30000000` (`BRD/overlay_dla.dts:20`).
- Two-phase HPS-first bitstreams: `quartus_pfg -c -o hps=on -o hps_path=<u-boot-spl-dtb.hex> x.sof x.rbf` emits `x.hps.rbf` (periphery + HPS, phase 1, flash/SDM) and `x.core.rbf` (fabric, phase 2, loaded by U-Boot or Linux). [A7], [A8]; local usage `~/coredla_work/RUNBOOK.md:164-171` ("Only golden_top.core.rbf is deployed"; QSPI/RSU not in this board's boot path).

### B2. DE25-Nano specifics
- Device A5EB013BB23BE4SR1 (130K LE), **128 Mbit** ASx4 QSPI flash, on-board USB-Blaster III (JTAG), 1 GB LPDDR4 for HPS. MSEL via SW5: `001` AS Fast (default, "FPGA configured from QSPI Flash, pre-programmed with a default configuration"), `111` JTAG. Manual says power-on configuration comes "from QSPI Flash or the HPS". [A9] §3.1-3.2, feature list.
- Our boot flow: U-Boot loads `golden_top.core.rbf` from FAT and runs `fpga load 0 ...`, `bridge enable`, then boots Linux with `mem=768M` (`BRD/boot.txt:6-19`). If `fpga load` fails it boots anyway (`boot.txt:10`). Same pattern as Altera's `fpga load 0 ${loadaddr} ${filesize};bridge enable`. [A8]
- **UNVERIFIED**: what phase-1 image is in the QSPI and that MSEL/QSPI is HPS-first as shipped (not read from the board).

### B3. Linux FPGA Manager / fpga-region / DT overlay
- Board kernel: `svc` node `intel,agilex5-svc` with `fpga-mgr` (`intel,agilex5-soc-fpga-mgr`) and a base `fpga-region` (`KRN/arch/arm64/boot/dts/intel/socfpga_agilex5.dtsi:219-249`); SMMU-mapped service buffers (`altr,smmu_enable_quirk`, `iommus = <&smmu 10>`, `:223-226`), `KRN/drivers/firmware/stratix10-svc.c:3503-3551`. Config: `CONFIG_FPGA_MGR_STRATIX10_SOC=m`, `CONFIG_FPGA_REGION=m`, `CONFIG_FPGA_BRIDGE=m`, `CONFIG_SOCFPGA_FPGA_BRIDGE` not set, `CONFIG_OF_OVERLAY=y`, `CONFIG_OF_CONFIGFS=y`, `CONFIG_INTEL_STRATIX10_RSU=m` (`KRN/.config:9983-9993,2243-2244,1975`); `ARM_SMMU_V3=y`, `IOMMU_DEFAULT_DMA_STRICT=y` (`:8616-8633`).
- Why the SMMU is in the path: the SDM addresses only a 512 MB window while Agilex 5 DDR starts at 0x8000_0000, so the service driver maps buffers through the SMMU into that window (29-bit DMA mask) [K4]; matching code in the board kernel above. (Patch series text via mirror; the driver code is the primary evidence.)
- Overlay mechanics (same as Agilex 7 example): put `core.rbf` in `/lib/firmware`; overlay fragment on the fpga-region with `firmware-name` and `config-complete-timeout-us`; `mkdir /sys/kernel/config/device-tree/overlays/N; echo x.dtb > .../path`; `rmdir` removes it. [A7] Removing the overlay removes child nodes and, per binding, "the FPGA Region will disable the bridges" if bridges are listed. [K1]
- Overlay properties recognised by the board's `of-fpga-region.c:230-241`: `authenticate-fpga-config` (authenticate only, other flags ignored), `partial-fpga-config`, `external-fpga-config`, `encrypted-fpga-config`, `fpga-bridges` (`:109-118`). The FPGA manager sends the partial flag to the SDM only if `partial-fpga-config` is set (`stratix10-soc.c:223-226`).
- Kernel doc on bridges: "During programming, transactions through those connections must be stopped and the connections must be held at a fixed logic level. This can be achieved by FPGA Bridges that exist on the FPGA fabric prior to the partial reconfiguration." [K1] Manager sequence: write_init -> write -> write_complete; states include `operating`, `write error`. [K2]
- Our overlays list **no** `fpga-bridges` (`BRD/overlay_dla.dts:15-21`, `BRD/overlay_ghrd.dts:5-11`) and the kernel has no SoCFPGA bridge driver enabled, so Linux does not freeze HPS-to-fabric bridges during a reprogram. The vendor U-Boot path does `bridge enable` after load (and Altera's Linux example text says "bridges must be disabled before fabric configuration, then re-enabled" for the U-Boot script). [A7], [A8] Vendor Linux example overlay also has no `fpga-bridges`, so this is vendor-typical; the risk is real but unproven here.

### B4. Partial Reconfiguration (PR)
- Documented as supported on Agilex 5: "reconfigure a portion of the FPGA dynamically, while the remaining FPGA design continues to function", personas per region. [A2], [A1]. Design/flow details are in the Quartus Pro "User Guide: Partial Reconfiguration", which lists Agilex 7, Agilex 5 and Agilex 3 (search result of altera.com guide index; page itself returned 403). PR user guide chapters (static region, PR region, freeze bridge, personas) **not read**.
- Linux path: board kernel driver maps `FPGA_MGR_PARTIAL_RECONFIG` to the SDM partial-reconfig flag (`stratix10-soc.c:223-226`). A 2026-06 patch series "enables FPGA configuration and partial reconfiguration on Agilex5" (fpga-mgr + separate fpga-region nodes, SMMU-remapped buffers). [K4] Merge status upstream: **UNVERIFIED**.
- Constraints from the kernel side: persona boundary must match the region; traffic through the boundary must be stopped and held while programming, by bridges that live in the static fabric. [K1]
- **UNVERIFIED**: PR flow tested on A5EB013B / DE25-Nano; whether the FPGA AI Suite DLA IP can be a PR persona. Only hint in the local FPGA AI Suite 2025.3.1 tree is "Partial Reconfiguration Safe" IP-XACT metadata on reset-handler IP (`/opt/altera/fpga_ai_suite_2025.3.1/dla/platform/agx5_soc_m2m/ip/ed_synth_reset_handler.ip`); no PR flow or persona is documented there.

### B5. Remote System Update (RSU)
- "You can store multiple application images and a single factory image in the configuration device" (ASx4 flash). If an application image errors, "the SDM firmware locates the next application image or reverts to the factory image". Reconfiguration is started by an SDM command via the Mailbox Client IP (fabric) or by HPS software. [A5]
- Altera SoC example on the 2 Gbit flash of the Premium kit: BOOT_INFO 2.1 MB, FACTORY_IMAGE 7 MB, three 16 MB application slots, SPT/CPB 64 KB each; SDM retries an image up to `max_retry` (3) on watchdog timeout, then next priority, then factory; up to seven application partitions at initial image creation. [A6]
- Driving from HPS: U-Boot `rsu list|slot_load|slot_program_buf|status_log|slot_erase|notify`; Linux `rsu_client` + LIBRSU + `CONFIG_INTEL_STRATIX10_RSU`. **"On Linux, [slot_load] only takes effect on the next reboot command."** `rsu notify` tells the SDM the HPS is alive to feed the RSU watchdog. [A6] Board kernel has the RSU driver as a module (`KRN/.config:1975`, `KRN/drivers/firmware/stratix10-rsu.c`).
- Fit on this board: the example layout needs > 9 MB before any application slot; DE25-Nano flash is 16 MiB. **UNVERIFIED** whether a custom smaller layout holding a factory image plus one application image with a 3.3-3.6 MB `core` bitstream is feasible; note that in HPS-first the fabric bitstream is not what the SDM loads from flash (RSU covers what the SDM configures from QSPI). That last point is an inference from [A4], not a quoted statement.
- Flash endurance for per-session writes: **UNVERIFIED** (part datasheet not read).

### B6. Security: signing, encryption, bad bitstream
- Agilex 5 SDM provides authentication and AES-256 encryption of user images, JTAG disable, side-channel protection [A10]; a technology brief lists SHA-384, ECDSA 256/384, PUF-protected key storage (search-result text of Altera brief; details in Device Security UG 815428, **not read**).
- Board kernel exposes a pre-check: overlay property `authenticate-fpga-config` -> `FPGA_MGR_BITSTREAM_AUTHENTICATE` "do FPGA bitstream authentication only" -> `COMMAND_AUTHENTICATE_BITSTREAM` "makes sure a signed bitstream has valid signatures before committing it to device" (`KRN/include/linux/fpga/fpga-mgr.h:75`, `stratix10-svc-client.h:63-66`, `of-fpga-region.c:225-235`).
- **UNVERIFIED**: whether this DE25-Nano SDM enforces signed bitstreams (dev boards are normally unfused; not read from the board) and SDM behaviour on an unsigned or wrong-device bitstream beyond the local observation below.
- Observed locally: after a failed RECONFIG (truncated/rejected image) the SDM refuses a new RECONFIG for about a minute (comment and 4x30 s retry loop, `BRD/coredla-fpga-up.sh:28-38`).
- Reconfiguration time: no vendor figure found. Measured: about 10 s reprogram (MEM `board-and-backend-access.md`); 4.9-19.7 s install+verify (`~/mender/MVP Web UI.MD:42`).

### B7. Consequences of reprogramming the core while Linux runs (HPS-first)
- HPS SDRAM pins and FSBL are configured by the SDM before the fabric [A4], so HPS DDR is not touched by a core reload. What sits behind the fabric is: the H2F/LWH2F bridges (Linux driver probes at 0x2000_0000+), f2sdram, interrupts SPI 20, camera D-PHY, user pins.
- Local evidence of the hazard: `altera-msgdma` probing an absent fabric "msgdma_irq_handler -> synchronous external abort -> kernel panic" (quoted in `docs/EDGE_AI_DEMO_RESEARCH.md:36-40` from `SDCARD_IMAGE_CHANGES.md:124-130`). Current mitigation: stop `dla-server`, remove overlay (unbinds fabric drivers) before programming (`BRD/coredla-fpga-up.sh:23-38`).
- Camera D-PHY/CSI-2 after warm Linux reconfig was a listed hardware risk (`docs/CAMERA_MIGRATION_PLAN.md:141`); later verified working by the user (MEM `camera-migration-plan.md`).
- SMMU: a distinct dwc2 SMMU fault (StreamID 6) wedges USB and network on this board (MEM `usb-webcam-dropouts.md`); the SDM service layer uses SMMU stream 10 in the same SMMU (`socfpga_agilex5.dtsi:223`). Whether a wedge can corrupt the reconfig path: **UNVERIFIED** (shared hardware, no evidence of interaction).

---

## Part C. Current architecture, verified against code

Flow (all confirmed in code): browser -> `POST /session/program` (extension `.rbf` and size <= 8 MiB only; `LAB/main.py:63-75`, `LAB/config.py:16`) -> queue loop (`LAB/queue_manager.py:305-333`) -> `mender_client.deploy` (`LAB/mender_client.py:227-252`): `mender-artifact write module-image -T fpga-reconfig -t de25-nano -f output_design.core.rbf -f my_overlay.dtb` (`:82-91`, DTB fixed at `LAB/assets/my_overlay.dtb`, `config.py:20`) -> upload -> `POST /deployments` for one device id (`:122-129`) -> poll every 2 s up to 900 s (`:138-166`) -> board module.

Facts checked against the task summary:
- `fpga-reconfig` declares `NeedsArtifactReboot: No`, `SupportsRollback: Yes`, implements ArtifactInstall and ArtifactRollback only; no ArtifactCommit, ArtifactFailure or Cleanup case (`BRD/fpga-reconfig:16-32`). Same in `coredla-model` (`:27-54`) and `coredla-runtime` (`:34-56`).
- ArtifactInstall backs up the current pair to `/var/lib/mender/fpga-reconfig.prev` (`rm -rf` first, one generation only, `fpga-reconfig:21-22`), copies the payload into `/lib/firmware`, calls `coredla-fpga-up.sh`. Success = fpga0 `state == operating` within 60 s and overlay `status == applied` (`coredla-fpga-up.sh:40-45`); nothing checks that the design works.
- ArtifactRollback copies the previous pair back and reprograms; fails if no previous pair exists (`fpga-reconfig:27-31`). The "previous pair" is whatever the previous deployment left there, not a fixed known-good image.
- **Correction to the summary**: the idle design is not a "ghrd" RBF. `_release()` redeploys the catalog `coredla-model` artifact (`queue_manager.py:291-302`, `config.MODEL_CATALOG[_live_model]`), and only if the session programmed its own RBF. `config.GHRD_RBF_PATH` (`config.py:21`) is defined but unused. That release deploy is a **second full Mender deployment** (poll wait + download of the ~100+ MB model artifact + reprogram + `dla-server` graph import), issued after the student's slot ends.
- Model artifacts carry RBF + DTB + graph + labels + arch (`BRD/coredla-model:2-7,31-43`), so every model switch also reprograms the fabric; a skip-reprogram variant was tried and reverted on 2026-09-23 after a board hang (MEM `board-and-backend-access.md`; root cause unresolved).
- Board Mender config: `UpdatePollIntervalSeconds 5`, `InventoryPollIntervalSeconds 28800`, `RetryPollIntervalSeconds 30`, `RetryPollCount 10`; **no** `ArtifactVerifyKey`, no `ModuleTimeoutSeconds` (`BRD/mender.conf:1-7`), so defaults apply (4 h module timeout [M4]). Artifacts built without `-k` (`mender_client.py:82-91`, `artifacts/*.sh`), so nothing is signed.
- Boot: U-Boot programs `golden_top.core.rbf` from FAT (`boot.txt:6-9`), then Linux runs `coredla-fpga.service` -> `coredla-fpga-up.sh` at every boot (`BRD/coredla-fpga.service:1-12`), which programs whatever is currently `/lib/firmware/output_design.core.rbf`. That is the *last deployed* bitstream, possibly a student's.
- `dla-watchdog.sh` only try-restarts `dla-server` on a stale `live.jpg` and stands down during Mender modules (`BRD/dla-watchdog.sh:10-23`); it is not an FPGA-level fallback.
- Timing (MEM 2026-09-23/28): poll wait now <= 5 s (was 15 s at a 30 s interval), ~50 s download of a 122 MB artifact through a Tailscale DERP relay (direct path later achieved by wiring the board to the PC), ~10 s reprogram, ~62 s graph import; ~2.5 min per model switch on the old link.
- Queue serialises sessions in memory; a backend restart forgets `_live_model` and the queue (`queue_manager.py:61-63`; systemd unit `lab-backend`).
- Uploaded bitstreams are untrusted student input: no header/magic check, no auth on the routes (`main.py:63-75`; `skip()` is documented as unauthenticated preemption, `queue_manager.py:201-212`).

---

## Part D. Analysis

### D1. Limitations, ranked by severity
"Origin" = Mender (M), Agilex 5 (A), this implementation (I).

1. **A bad or hostile bitstream can hang the SoC, and nothing in the OTA path can recover it.** What: a user RBF is programmed live with HPS-fabric bridges neither frozen nor reset (B3), while Linux, the DLA driver stack and the camera rely on that fabric. Evidence: overlays have no `fpga-bridges` (`BRD/overlay_dla.dts:15-21`); Linux path has no bridge disable while U-Boot's does [A8]; msgdma abort-panic precedent (B7). If the box hangs inside ArtifactInstall the module cannot report; Mender only kills a module after `ModuleTimeoutSeconds`, default 4 h, unset here (`BRD/mender.conf`), while the backend gives up at 900 s (`mender_client.py:165-166`). Recovery today is an operator power cycle (MEM; remote booth has no power switch, `docs/DEMO_DIAGRAMS.md` section 2). Impact: lab down until someone is at the board. Origin: A + I (M supplies no watchdog for hangs).
2. **The rollback target is not a known-good design, and reboot re-applies the culprit.** Rollback restores "previous deployment's" pair (`fpga-reconfig:21-31`), one generation; `coredla-fpga.service` re-programs `/lib/firmware/output_design.core.rbf` at each boot (`coredla-fpga.service:9`), which after a failed/hung install is the new (bad) file because it is copied before programming (`fpga-reconfig:23`). By code reading the boot-time step can re-trigger the fault before Mender's rollback runs. Not reproduced. The FAT `golden_top.core.rbf` (`boot.txt:6`, `board_setup.sh:31`) is the real known-good and is not used as the rollback target. Origin: I.
3. **Untrusted student bitstreams run with full fabric privileges; no validation, signing, or auth.** Arbitrary logic can drive board pins, hold bridges, flood f2sdram, and, if a fabric master reaches DDR unfiltered, read or overwrite kernel memory. Evidence: extension + size check only (`main.py:67-70`); unsigned artifacts and no `ArtifactVerifyKey` (`mender.conf`); unauthenticated routes (`main.py`, `queue_manager.py:201-204`). SDM authentication exists in silicon [A10] but enforcement on this board is **UNVERIFIED**; SMMU coverage of fabric-originated DMA is **UNVERIFIED**. Related: anyone able to create Mender deployments controls the board as root through `coredla-runtime`, which unpacks a tarball over `/opt/dla` and installs a systemd unit (`BRD/coredla-runtime:43-44`), and `my_overlay.dtb` is applied as a root DT overlay (`fpga-reconfig:24`). Origin: I, with A (no per-design isolation without PR).
4. **Install success means "configured", not "working"; no post-install health gate.** `ArtifactCommit` is not implemented (`fpga-reconfig:16-32`), so a design that programs but crashes the driver stack is reported success (`mender_client.py:157-160`). Model artifacts do have a readiness gate (`coredla-model:44-45`, up to 180 s). A generic gate for arbitrary student RBFs is hard, because probing an unknown fabric address can itself abort the bus (B7). Origin: I (Mender offers the hook, [M1]).
5. **The SDM lockout makes rollback slow and fragile.** After a rejected/truncated RBF the SDM refuses RECONFIG for about a minute, so rollback needs up to 4 tries x 30 s (`coredla-fpga-up.sh:28-38`). A wrong-type RBF (e.g. not an HPS-first `core` image, or wrong device) is only discovered on the board, after upload and download. Origin: A (behaviour) + I (no pre-check).
6. **Timeout/abort mismatch leaves stale deployments.** On the 900 s timeout the backend returns an error but never aborts the deployment (`mender_client.py:138-166`), so a slow board may install later, during the next student's slot; abort is only observed at the device's next status report (409, `api_deployments.go:1532-1533`); stalled-download detection took ~14 min observed (MEM); presigned URL lifetime is 900 s (`config.go:60-61`, interplay with slow links **UNVERIFIED**). `preflight()` only cleans at backend startup (`mender_client.py:197-203`). Origin: I + M.
7. **Latency floor set by polling and by a heavyweight per-reprogram pipeline.** Poll interval 5 s (~2.5 s mean wait), server-driven early poll not wired up; each student reprogram = build artifact subprocess + HTTP upload + create deployment + 2 s status polling + ~10 s program. Model switch adds tens of seconds of download over the relay. Origin: M (poll-only [M5]) + I. Note the RBF-only path is small (3-4 MB); the biggest user-visible waits are model artifacts and the release redeploy.
8. **Every session that programs its own RBF costs a second full deployment on release** (`queue_manager.py:298-301`), during which the next student may already be active; the board is unusable until graph import completes (~1-2 min). Origin: I.
9. **State drift and bookkeeping.** Mender tracks one `artifact_name` (last installed of any module type); `_live_model` is in memory (`queue_manager.py:61-63`); hand-installed runtime made Mender's belief wrong (MEM `camera-migration-plan.md`); each program uploads a uniquely named artifact that is never deleted (`deploy()` has no cleanup; names must be unique, `queue_manager.py:218-219`); the uploaded `.rbf` file stays in `uploads/` on success (`main.py:72-74`). Origin: I + M.
10. **Identity and network fragility.** MAC identity changes create pending devices and hung deployments (A4); no RTC so the clock is wrong after a power cycle until NTP (MEM); warm reboot can kill the WiFi dongle and leave the board off Tailscale (MEM); single lab PC hosts server, backend and uplink (`docs/DEMO_DIAGRAMS.md` section 2). TLS-time interaction with the Mender client is **UNVERIFIED**. Origin: M (identity) + I + environment.
11. **Kernel, DTB and boot script are outside OTA and rollback.** They are hand-edited on the FAT partition with `.pre-*` backups (MEM `usb-webcam-dropouts.md`, `BRD/board_setup.sh:54-57`); there is no rootfs A/B, so a bad module install can only roll back what the module saved. Origin: I (Mender supports A/B for Debian-family images per [M14]; whether it fits this SD-card image is **UNVERIFIED**).
12. **SMMU/service-layer shared fate.** FPGA programming goes through SMMU-mapped SDM buffers (B3); the board has a known SMMU wedge (dwc2). No evidence of interaction, but a wedge that also blocks the SDM mailbox would leave OTA reprogram impossible. **UNVERIFIED.** Origin: A.
13. **Design coupling of RBF and model.** Model artifacts carry the RBF, so every switch reprograms; skipping when the RBF is unchanged was unstable (hang after a skip-path deploy; cause unresolved). Origin: I.

Not limitations (checked): server artifact cap is 10 GiB, far above the 8 MiB RBF cap (`config.go:47-48`); Mender's checksum verification protects transport integrity [M6]; rollback machinery works as designed when the module returns non-zero.

### D2. Alternatives, each against D1

(a) **Keep Mender modules, harden them.** Cheapest, fixes most.
- Add `ModuleTimeoutSeconds` (e.g. 300 s; note SIGTERM then SIGKILL after 60 s [M4]; a process stuck in an uninterruptible bus stall may not die) so a hung module reaches ArtifactRollback/Failure instead of waiting 4 h. Fixes #1 partly, #6.
- Make the rollback target and boot target the FAT golden: keep a read-only golden RBF+overlay, roll back to it, and have `coredla-fpga.service` program the golden/idle design, not "the last deployed" file; treat student RBFs as session-scoped candidates promoted only on ArtifactCommit. Fixes #2. Because U-Boot already loads golden at every boot (`boot.txt:6-9`), the boot service can simply skip a student RBF.
- Add an `ArtifactCommit` health check where a design-specific probe exists (models: already `wait_ready`); for arbitrary RBFs, at least confirm HPS responsiveness without touching unknown fabric addresses. Fixes #4 partly.
- Add `fpga-bridges`/bridge quiesce in the Linux path if the fabric contains freeze bridges; today it does not (B3). **UNVERIFIED** effect on the hang risk.
- Sign artifacts (`mender-artifact -k`, `ArtifactVerifyKey`) [M7]: protects against a compromised/misconfigured server or MITM, and gives a key to gate `coredla-runtime`. It does **not** vet RBF content (the backend is the signer). Fixes #3 only for the supply-chain half.
- Backend hygiene: abort the deployment on timeout, delete used artifacts, auth on routes, reject RBFs early (size, plus a compatibility check if a documented header exists; none found, **UNVERIFIED**), unlink uploads. Fixes #6, #9, part of #3, #5.
- Optional: call `POST /deviceconnect/devices/{id}/check-update` after creating the deployment (needs mender-connect on the board, **UNVERIFIED**) so polling can be relaxed without latency; with a 5 s poll the gain is about 2.5 s on average. Low value.
- Cost: small, all inside existing files. Residual: a truly hostile bitstream still runs unconfined (#3).

(b) **RSU flash A/B (factory + application images), driven from a Mender module.**
- Solves "device always comes back": SDM watchdog + retry then factory fallback [A6]; needs the HPS to feed `rsu notify` or the SDM reloads. Does not sandbox the design.
- Poor fit for reprogramming per student session: Linux `slot_load` takes effect on the next reboot [A6] (reboot in the loop, tens of seconds, and a lab-side power/USB fragility already seen after warm reboots, MEM); flash writes per session (endurance **UNVERIFIED**); the DE25-Nano flash is 16 MiB vs the Altera example layout (~9+ MB before slots); in HPS-first the fabric image is not RSU-managed (inference, B5). Good only for the OS-level "phase 1" image, which we do not change.
- Verdict: not recommended for the session path; consider only as a safety net for the first-stage image.

(c) **Partial Reconfiguration: static shell + student persona.** Best long-term isolation.
- Agilex 5 documents PR [A1][A2]; kernel path exists for it (partial flag; series pending upstream [K4]); freeze bridges in the static region address "traffic must be stopped" [K1]. HPS, DDR, camera, DLA infrastructure, pins stay up; students cannot touch anything outside their region; a failed persona load leaves the static region running (behaviour on failure **UNVERIFIED**). Persona bitstreams are smaller and faster to load (**UNVERIFIED**, no vendor figure).
- Cost: large. The lab must own the static shell and give students a PR-aware Quartus project or make the lab compile persona sources itself; students must respect region boundary ports; the DLA as PR persona is **UNVERIFIED**, and the 130K LE device has little room for both a DLA and a shell (the current DLA uses 89 % of ALMs, `MEM camera-migration-plan.md` phase 4). Not tested on this board.
- Verdict: the only option that addresses #1 and #3 at the root. Present it as the target architecture and future work; do not promise it for this project without a feasibility spike (PR flow on A5EB013B, then a toy persona through `partial-fpga-config`).

(d) **Bypass Mender for the FPGA reprogram; direct authenticated agent on the board.**
- Removes the poll wait (<= 5 s) and the artifact build/upload step; loses Mender's auth, TLS identity, rollback state machine, audit trail, deployment status; adds an inbound listener on the board (Tailscale-only would limit exposure). Mean latency saving is a few seconds against an ~10 s reprogram and a 1-2 min model import. Does not fix #1-#5 by itself.
- Verdict: not worth it. If latency is the concern, use the check-update trigger in (a).

(e) **Separate bitstream and model artifacts / overlays only.**
- Already two module types plus runtime; but model artifacts still carry the RBF (`coredla-model:31,40-41`). Splitting "fabric" (rare) from "graph" (frequent, no reprogram) shrinks model downloads and removes the second full reprogram on release when the DLA design is unchanged. The one skip-reprogram trial hung the board (cause unresolved, MEM), so gate this on finding that cause. Fixes #8, #13 partly.
- Overlay-only updates (no bitstream) are not possible when the fabric changes.

(f) **Other options found in primary docs.**
- Mender standalone `mender-update install` from a board-side agent: keeps artifact verification and module rollback semantics but requires stopping the daemon [M8]; conflicts with the managed flow for models. **UNVERIFIED** that both can coexist.
- Bitstream pre-authentication via `authenticate-fpga-config` (board kernel): a cheap two-step "authenticate then program" that rejects unsigned/wrongly signed images before they touch the fabric, but only meaningful if the SDM enforces signatures, which is **UNVERIFIED** here; needs a signing key held by the lab (fits with lab-side compile in (c)).
- Delta updates: Enterprise/Professional, rootfs-image only; irrelevant to a 3.6 MB RBF [M9].
- RAUC/SWUpdate comparison: not evaluated (no primary source read); out of scope.

### D3. Recommendation
1. Now (days): implement (a): `ModuleTimeoutSeconds`, golden-based rollback and golden-only boot programming, abort-on-timeout, artifact/upload cleanup, auth on backend routes, artifact signing for `coredla-runtime`. This turns #1/#2/#6/#9 from open-ended failures into bounded ones and needs no new architecture.
2. Next (weeks): split fabric vs model (e), only after the skip-reprogram hang is explained; measure with the existing timing points.
3. Long term: run a PR feasibility spike (c) and present it as the isolation answer; keep Mender as the transport (Update Module + `ArtifactCommit` health gate), because Mender's rollback, identity and audit remain useful whichever bitstream format is deployed.
4. Do not switch to RSU (b) or bypass Mender (d).
Tradeoff to state honestly in the paper: with arbitrary student RBFs on a shared full-core design, an unconfined bitstream is inherent, and Mender cannot fix it; only PR (or lab-side compilation) can. Timeouts and golden rollback bound the damage but do not remove it.

### D4. What to do next for the paper
- Reproduce and time one deliberately bad RBF (truncated file, wrong-device file) to document the observed failure and recovery path (needs a lab session; this research did not touch the board).
- Read the two documents not fetched: Quartus Pro "User Guide: Partial Reconfiguration" (Agilex 5 chapters) and "Device Security User Guide: Agilex 5" (item 815428); and the Agilex 5 HPS RSU guide; upgrade the UNVERIFIED items below.
- Check on the board: `systemctl list-unit-files | grep -i connect`, hardware watchdog config, `/proc/config.gz` for `INTEL_STRATIX10_RSU` and SoCFPGA bridge, and whether the SDM is in a secured mode. (Read-only; not done here.)
- Add a small measured table: poll wait, upload, download, program, import for RBF-only vs model artifacts.
- Cite Altera pages by version (25.3.1 / 26.1) and the kernel commit `d7d192a9d` for driver behaviour.

### D5. UNVERIFIED items (collected)
1. mender-connect installed/connected on the board; `check-update` end to end on client 5.x.
2. Whether self-hosted OSS Mender licensing/terms cover the Troubleshoot-classed features (code is present in the OSS repo); full OSS-vs-Enterprise matrix.
3. Client behaviour if a module hangs beyond `ModuleTimeoutSeconds` (D-state); handling of an abort while inside ArtifactInstall; exact `http_resumer` stall detection (14 min is an observation).
4. Daemon and standalone modes coexisting on one device.
5. PR end to end on A5EB013B/DE25-Nano; upstream merge status of the Agilex5 PR patch series; DLA/FPGA AI Suite as a PR persona; PR failure behaviour and persona load time.
6. Whether this SDM enforces signed bitstreams; SDM behaviour on unsigned/incompatible RBF beyond the ~1 min lockout; SMMU coverage of fabric-originated DMA.
7. QSPI contents and HPS-first configuration as shipped on DE25-Nano; feasibility of an RSU layout in 16 MiB; RSU vs HPS-first scope; flash endurance.
8. Vendor reconfiguration time figures; which HPS peripherals depend on core I/O on this board.
9. Interaction between the SMMU wedge and the SDM service-layer path; TLS-time impact of no RTC on Mender.
10. Hardware watchdog configuration on the board (the phase-6 note mentions a watchdog reboot, MEM `camera-migration-plan.md`, config not read).
11. Whether an RBF header can be validated host-side (no public format found).
12. Quartus PR guide device table for Agilex 5 (read only via search result listing).

---

## Glossary
- **SDM**: Secure Device Manager, the hard controller that configures the device, holds keys, runs RSU decisions.
- **HPS**: Hard Processor System (Cortex-A55/A76). **HPS First / FPGA First**: boot order; HPS First lets HPS load the fabric later.
- **RBF**: raw binary bitstream; `core.rbf` = fabric part, `hps.rbf` = periphery/HPS part in the HPS-first split (`quartus_pfg -o hps=on`).
- **FPGA Manager / fpga-region / bridge**: Linux frameworks to program the FPGA, bind a DT subtree to a region, and freeze/enable HPS-fabric buses.
- **DT overlay / configfs**: runtime device-tree patch applied via `/sys/kernel/config/device-tree/overlays`.
- **PR / persona**: partial reconfiguration; an alternative implementation loaded into one region while the static region runs.
- **RSU**: remote system update; factory + application images in QSPI flash with SDM fallback.
- **AS / ASx4, JTAG, Avalon-ST, CvP**: active serial from quad-SPI flash, debug/programming port, passive streaming, PCIe-based configuration.
- **SMMU**: ARM system MMU; here also maps the SDM service-layer buffers.
- **Update Module / module-image**: Mender's script-based installer type and the artifact payload type that uses it.
- **ArtifactCommit / ArtifactRollback**: Mender states that make an install permanent / undo it.
- **DERP**: Tailscale relay used when no direct path exists.
