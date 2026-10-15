# CoreDLA on DE25-Nano — Release Bundle

Two paths:

- **This README** — deploy the prebuilt, checksum-verified artifacts onto a DE25-Nano and run
  inference. No Quartus, no kernel build, no OpenVINO on the deploying machine.
- **[RUNBOOK.md](RUNBOOK.md)** — rebuild every artifact from a factory-fresh board and a fresh
  CoreDLA toolchain. Use it when the architecture, the mSGDMA parameters, the device tree or
  the runtime must change; the prebuilt files here are exactly what that runbook produces.

Everything shipped here was checksum-matched against the board that produced the qualified
result on 2026-08-17: **8 iterations, 2.1033 FPS system, 4.3302 FPS per IP instance, IP clock
100.0000 MHz, 1 hardware instance.**

---

## What is in the bundle

| Path                                          | What it is                                                                                                                                                          | Where it goes                                             |
| --------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------------- |
| `prebuilt/golden_top.core.rbf`              | FPGA bitstream: DE25-Nano GHRD + CoreDLA`AGX5_Small_NoSoftmax` + mSGDMA. md5 `e8870f9adbc459d07df904b60a78ada4`                                                 | SD FAT`/mnt/fat/`, loaded by u-boot `fpga load`       |
| `prebuilt/socfpga_agilex5_de25_nano.dtb`    | Device tree with the CoreDLA nodes at this design's addresses. md5`f432d939dcdab3e18cb4c8a8536ec828`                                                              | SD FAT`/mnt/fat/`                                       |
| `prebuilt/boot.scr.uimg`                    | u-boot script: loads the`.rbf` **before** `bridge enable`, sets `mem=768M`. md5 `57f6b60e99cb4409f9486e6b8e3d842d`                                    | SD FAT`/mnt/fat/` (stock kept as `boot.scr.uimg.bak`) |
| `prebuilt/boot_coredla.txt`                 | Source of the above. Rebuild with`mkimage -A arm64 -O linux -T script -C none -n "DE25 Nano boot script" -d boot_coredla.txt boot.scr.uimg`                       | —                                                        |
| `prebuilt/modules/msgdma_userio.ko`         | Patched char driver (per-sg-entry submit+wait, advancing EMIF offset, 256 KB chunking). md5`abf501582ac08ff2ce377016bb4bf01f`                                     | `/lib/modules/6.12.11-gd7d192a9ddd9-dirty/extra/`       |
| `prebuilt/modules/altera-msgdma.ko`         | Stock in-tree DMA engine, built as a module. md5`d241718fce700cdf4378ae9c5d119f2f`                                                                                | `/lib/modules/<K>/kernel/drivers/dma/`                  |
| `prebuilt/config/coredla-modprobe.conf`     | `options uio_pdrv_genirq of_id=generic-uio`                                                                                                                       | `/etc/modprobe.d/coredla.conf`                          |
| `prebuilt/config/coredla-modules-load.conf` | load order:`uio_pdrv_genirq`, `altera_msgdma`, `msgdma_userio`                                                                                                | `/etc/modules-load.d/coredla.conf`                      |
| `model/resnet50_nosoftmax.bin`              | Compiled resnet-50-tf for this architecture, 154273176 B. md5`a0b0d1feb678106106c3175184d1f89f`                                                                   | board`~/app/resnet-50-tf/`                              |
| `model/AGX5_Small_NoSoftmax.arch`           | Architecture file the runtime checks against the fabric                                                                                                             | board`~/app/resnet-50-tf/`                              |
| `app-parts/libhps_platform_mmd.so`          | MMD built for`-hps_machine=agilex5_de25_nano`. md5 `1c0dbd3b7453c80ae9cd76a0e37d73de`                                                                           | board`~/app/`                                           |
| `app-parts/dla_benchmark`                   | Benchmark binary from the same build                                                                                                                                | board`~/app/`                                           |
| `source/`                                   | `add_coredla_msgdma.tcl`, the `WINDOW_BASE`-patched span extender, the patched `msgdma_userio` sources, `socfpga_agilex5.dtsi.patch`, `runtime_mmd.patch` | inputs to RUNBOOK.md                                      |
| `scripts/`                                  | deploy / setup / verify / benchmark, see below                                                                                                                      | —                                                        |
| `MANIFEST.md5`                              | checksums of everything above —`md5sum -c MANIFEST.md5` from this directory                                                                                      | —                                                        |

Board facts assumed throughout: kernel `6.12.11-gd7d192a9ddd9-dirty`, user `terasic` password
`<BOARD_PASSWORD>`, hostname `de25-nano`, console `ttyS0` @ 115200, SD only (`/dev/mmcblk0p1` FAT32 boot,
`/dev/mmcblk0p2` ext3 rootfs).

---

## Prerequisites on the board

The bundle layers onto an already-bootable DE25-Nano: kernel `Image`, `u-boot.itb` and an
Ubuntu rootfs on the SD card, i.e. the baseline built in RUNBOOK.md Phase 2. It does **not**
contain a bootable SD image.

- Board already boots Linux to a login prompt from the SD card, running kernel
  `6.12.11-gd7d192a9ddd9-dirty` (`uname -r`). A different kernel means the shipped `.ko` files
  will not load — rebuild them via RUNBOOK.md Phase 3 steps 1-7.
- Network (`ssh`) reachable, or a serial console for the manual path below.

## Application payload (`~/app`) — read this before deploying

The 513 MB `/home/terasic/app` tree (launcher `dla_benchmark.sh`, `plugins.xml`, the
OpenVINO/OpenCV runtime libraries, and `sdklibs/` — the glibc 2.39 loader the Yocto-SDK-linked
binaries need on this glibc 2.35 Ubuntu rootfs) is **not** in this bundle; only the two
binaries in `app-parts/` are. `[VERIFY: the exact command that originally assembled and transferred /home/terasic/app was never recorded]`

Two ways to obtain it:

1. Clone it from a board that already works:
   ```bash
   ./scripts/stage_app_from_board.sh terasic@<known-good-board>
   ssh terasic@<new-board> 'tar -C /home/terasic -xf -' < app-payload/app.tar
   ```
2. Rebuild it on a host with the full toolchain — RUNBOOK.md Phase 3 steps 8-15, which also
   regenerates `app-parts/`'s two binaries.
   `[EXTERNAL STEP: the Yocto ARM SDK at coredla_work/runtime/embedded_arm_sdk/sysroots/armv8-2a-poky-linux, source of sdklibs/ — its build is not reconstructable from the investigated tree]`

Also not in the bundle: `[VERIFY: provenance of the 10 input images in ~/app/resnet-50-tf/images (val_00000000.bmp …) — 8 of them are used by the qualified run]`

---

## Deploy

```bash
md5sum -c MANIFEST.md5                       # from this directory
./scripts/01_deploy_from_host.sh terasic@coredla
```

`01_deploy_from_host.sh` tars `prebuilt/` plus the board scripts, copies it to the board's
`/tmp`, and runs `02_board_install.sh` there under sudo. That script:

- mounts `/dev/mmcblk0p1` at `/mnt/fat`, keeps one-time `.orig` / `.bak` backups of anything it
  replaces, then writes `golden_top.core.rbf`, `socfpga_agilex5_de25_nano.dtb`, `boot.scr.uimg`
- installs both `.ko` files for the running kernel and runs `depmod -a`
- writes `/etc/modprobe.d/coredla.conf` and `/etc/modules-load.d/coredla.conf`
- creates a 2 GB `/swapfile` and persists it in `/etc/fstab` — with `mem=768M` only 683 MB is
  usable and `dla_benchmark` peaks around 475 MB RSS, so without swap it is OOM-killed

Then stage the model and the runtime payload:

```bash
ssh terasic@coredla 'mkdir -p ~/app/resnet-50-tf'
scp model/resnet50_nosoftmax.bin model/AGX5_Small_NoSoftmax.arch terasic@coredla:~/app/resnet-50-tf/
scp app-parts/dla_benchmark app-parts/libhps_platform_mmd.so     terasic@coredla:~/app/
```

Reboot. u-boot does `fatload mmc 0:1 0x90000000 golden_top.core.rbf` → `fpga load 0 …` →
`bridge enable` → load the DTB → `booti`. The bitstream comes from the FAT partition — not from
the FIT image, not from JTAG, not from the Linux fpga_manager.

**No network?** Everything above works over the serial console too: `base64 -w 76 <file>` on the
host, stream the lines into a board-side heredoc, `base64 -d`, `md5sum`-verify against
`MANIFEST.md5`, then run `02_board_install.sh` by hand. That is how the original deployment was
done for the kernel modules.

## Per-boot setup

```bash
./scripts/03_board_setup.sh        # on the board
```

Reloads **both** modules in dependency order (`rmmod msgdma_userio` → `rmmod altera_msgdma` →
`modprobe altera_msgdma` → `insmod msgdma_userio.ko`), restores `chmod 660` / `chgrp terasic`
on `/dev/uio0` and `/dev/msgdma_coredla0`, and points `~/app/plugins.xml` at
`libopenvino_arm_cpu_plugin.so`.

Run this same script if DMA ever wedges — the symptom is
`altera-msgdma 20021000.msgdma: dma_sync_wait: timeout!` followed by `DMA Failed at sg entry …`
and a `WriteToDDR` assertion while the 150 MB weights load. Once the engine stalls,
`dmaengine_terminate_sync()` does not recover `altera-msgdma`'s internal state; reloading both
modules does. The permissions must be reapplied after every reload — there is no udev rule.

## Verify

```bash
./scripts/04_board_verify.sh       # on the board, exits non-zero on any failure
```

Checks the four gates that actually prove the fabric is the right one:

| Check                                        | Required                                                                |
| -------------------------------------------- | ----------------------------------------------------------------------- |
| `/sys/class/uio/uio0/name`                 | `coredla0@20020000`                                                   |
| `/dev/uio0` `+0x10` / `+0x30` via mmap | `2025.3.1/20` / `AGX5_Small_NoSoftmax`                              |
| `/proc/interrupts`                         | `GICv3  52 Level  20021000.msgdma` (INTID 52 = SPI 20)                |
| `/sys/class/uio/uio0/maps/map0/size`       | `0x1000` — UIO page-rounds the DT's `0x800`; expected, not a fault |

Do **not** gate on `/sys/class/fpga_manager/fpga0/state`: u-boot's `fpga load` bypasses the
Linux fpga_manager, so it reads `unknown` even with the fabric live.

## Run

```bash
./scripts/05_board_benchmark.sh    # on the board
```

Expect all 12 steps, `Runtime arch check passed`, `Runtime build version check passed`, and
`Import model took` ≈ 76 s (normal for the 154 MB compiled model, not a hang). The IP-side
figures are fabric-determined and reproduce to four significant figures:

```
count:             8 iterations
IP duration:       1847.4772 ms
IP throughput per instance: 4.3302 FPS
IP clock frequency measurement: 100.0000 MHz
number of hardware instances: 1
```

System-side figures move with host CPU scheduling: `system duration` 3776-3886 ms, `latency`
468-475 ms, `system throughput` 2.10-2.13 FPS. Afterwards the `20021000.msgdma` count in
`/proc/interrupts` must have risen (≈3000 per 8-iteration run) and `dmesg` must show no
`dma_sync_wait: timeout!`.

---

## Design values worth knowing before changing anything

| Item                          | Value                                                                                                                                               |
| ----------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| Device / family               | `A5EB013BB23BE4SCS`, Agilex 5                                                                                                                     |
| Toolchain                     | Quartus Prime Pro 25.3.1 Build 100, FPGA AI Suite`2025.3.1/20`, OpenVINO 2024.6.0                                                                 |
| DLA architecture              | `AGX5_Small_NoSoftmax_AGX5`, one instance, shares `clk_100` at 100 MHz                                                                          |
| DLA CSR                       | phys`0x2002_0000`, size `0x800` (LWH2F base `0x2000_0000` + `0x20000`)                                                                      |
| mSGDMA CSR / descriptor slave | phys`0x2002_1000` / `0x2002_1020`, 32 B each                                                                                                    |
| mSGDMA parameters             | `MODE 0`, `DATA_WIDTH 256`, `BURST_ENABLE 0`, `STRIDE_ENABLE 0`, `TRANSFER_TYPE Unaligned Accesses`, `MAX_BYTE 1048576`, FIFOs 64 / 128 |
| Software descriptor cap       | `MSGDMA_USERIO_MAX_CHUNK = 256 KB` — load-bearing on a 1 MB fabric, `altera-msgdma` never splits                                               |
| DLA DDR window                | `WINDOW_BASE = 33'h0B0000000`, `0xB000_0000`-`0xBFFF_FFFF` (256 MB)                                                                           |
| Kernel bootargs               | `console=ttyS0,115200 root=/dev/mmcblk0p2 rw rootwait mem=768M`                                                                                   |
| mSGDMA interrupt              | `f2h_irq0_in` line 3; F2H base is SPI **17**, so SPI 20 / INTID 52                                                                          |
| Fit                           | ALM 35,054/46,800 (75 %), M20K 249/358 (70 %), setup slack +1.844, 0 violations                                                                     |

`WINDOW_BASE`, the device tree's `mem_start`/`mem_end`, `mem=768M` and the MMD's
`dla_mmd_get_ddr_size_per_instance()` (`1ULL << 28`) all describe the same 256 MB carveout.
Change one and you must change all four — RUNBOOK.md Phase 1 step 7, Phase 3 steps 1 and 9,
Phase 3 step 17.

`[VERIFY: the real DE25-Nano LPDDR4 rate — dla_mmd_get_ddr_clock_freq() returns 200 MHz copied from the generic AGX5 default and has never been read off the hardware; affects reported bandwidth only]`

## Mender (Phase 0 of the edge-AI demo) — files in `~/edge-ai-demo/board/`

Adds live FPGA reprogramming over Mender to the CoreDLA SD. Installed on the
board by `board_setup.sh` (run as root with every file in `~/edge-ai-demo/board/` plus
`prebuilt/boot.scr.uimg` in one directory, then reboot). `mender/` below means that directory.

Boot contract after this (differs from the table above):

- **`mender/socfpga_agilex5_de25_nano.nodla.dtb`** replaces the FAT dtb. The three CoreDLA
  nodes are gone from the base tree; `intc` gets a `__symbols__` label so overlays can
  reference the GIC. Source: `mender/socfpga_agilex5_de25_nano.nodla.dts` (decompiled +
  edited; rebuild with `dtc -@ -I dts -O dtb`).
- **`prebuilt/boot.scr.uimg`** now sets `fdt_high 0xffffffffffffffff` so U-Boot leaves the
  FDT at `fdt_addr_r` (0x86000000, inside `mem=768M`). Without it U-Boot relocated the FDT
  to the top of RAM, inside the DLA's 0xB0000000-0xBFFFFFFF window, and every inference
  overwrote it — the live device tree was garbage after the first run (only noticed once a
  driver re-probed after a reconfig). md5 of the new script: `98507dab1a633cf05244499c42d8de5e`.
- **`mender/overlay_dla.dts`** (`/lib/firmware/my_overlay.dtb`): fpga-region overlay holding
  `firmware-name = "output_design.core.rbf"` **and** the three CoreDLA nodes as children.
  The kernel programs the rbf first and creates the children only on success, so
  `altera-msgdma` / `msgdma_userio` can never probe against a foreign or unconfigured fabric
  (they autoload via udev when the nodes appear; nothing in `modules-load.d` but
  `uio_pdrv_genirq`). `mender/overlay_ghrd.dts` is the same without children, for the idle GHRD.
- **`/usr/local/sbin/coredla-fpga-up.sh`**: waits for `fpga_region/region0`, removes and
  re-applies the overlay (unbinds drivers, reprograms — ~2.3 s — rebinds), retries up to 4×
  30 s apart because the SDM refuses a new RECONFIG for ~1 min after a failed one.
  Run at boot by `coredla-fpga.service` (so the deployed rbf, not the FAT one, is what runs)
  and by the Mender module.
- **`/usr/share/mender/modules/v3/fpga-reconfig`**: payload `output_design.core.rbf` +
  optional `my_overlay.dtb` → `/lib/firmware`, previous pair kept in
  `/var/lib/mender/fpga-reconfig.prev` for `ArtifactRollback`. `NeedsArtifactReboot: No`.
- `mender/90-coredla.rules`: `/dev/uio*` and `/dev/msgdma_coredla*` become group `terasic`
  0660 (replaces the chgrp in `scripts/03_board_setup.sh`).
- `mender/mender.conf`: `ServerURL https://mender.example.ts.net`, 30 s update poll.
  Device type `de25-nano`. Tailscale on the board runs in kernel-TUN mode with
  `iptables-legacy` (`update-alternatives`), the shipped userspace-networking mode could not
  resolve or reach the server.

Build an artifact (`-T` must stay `fpga-reconfig`, file names are fixed):

```bash
mender-artifact write module-image -T fpga-reconfig -t de25-nano -n <unique-name> \
  -o out.mender -f output_design.core.rbf -f my_overlay.dtb
```

Verified 2026-09-17 on `coredla`: GHRD → DLA → truncated rbf (fails, rolls back) with
`dla_benchmark` passing after each good state. Note the fabric currently on the FAT card is
`AGX5_Nano_k32c16_sb12883` (`resnet50_sb12883.bin`), not the `AGX5_Small_NoSoftmax` pair in
`model/`.
