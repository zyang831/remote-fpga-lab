# CoreDLA on DE25-Nano — Replication Runbook

Reproduces the configuration that ran `dla_benchmark` end-to-end on 2026-08-17
(8 iterations, 2.1033 FPS system / 4.3302 FPS per IP instance, IP clock 100.0000 MHz).

Host prerequisites (exact versions — the design was built and verified only with these):

| Component | Version | Path |
|---|---|---|
| Quartus Prime Pro | 25.3.1 Build 100 12/19/2025 SC Pro Edition | `/home/<user>/altera_pro/25.3.1/quartus` |
| FPGA AI Suite (CoreDLA) | `2025.3.1/20` | `/opt/altera/fpga_ai_suite_2025.3.1` |
| OpenVINO | 2024.6.0 | `/opt/intel/openvino_2024` → `openvino_2024.6.0` |
| Cross compiler | `aarch64-linux-gnu-gcc` 13.3.0 | system |

Target: DE25-Nano rev B, Agilex 5 `A5EB013BB23BE4SCS`, 1 GiB LPDDR4, SD boot only
(`/dev/mmcblk0p1` FAT32 boot, `/dev/mmcblk0p2` ext3 rootfs), console `ttyS0` @115200,
login `terasic` / `<BOARD_PASSWORD>`. JTAG is not used anywhere in this flow.

---

## Phase 1 — Integrate DLA IP into the DE25-Nano GHRD and build the bitstream

Working directory for the whole phase: `/home/<user>/quartus_projects/CoreDLA_GHRD`.

1. `[EXTERNAL STEP: base DE25-Nano GHRD Quartus project (repo commit d1d1727 "Base DE25 Nano GHRD") checked out at /home/<user>/quartus_projects/CoreDLA_GHRD, with golden_top.qpf/.qsf/golden_top.v, qsys_top.qsys, ghrd_timing.sdc, jtag.sdc, hps_subsys/ and tmp-clearbox/]`
2. `[EXTERNAL STEP: DE25-Nano_revB_v.1.0.0_ResourcePackage unpacked at /home/<user>/quartus_projects/DE25_Nano_Resource/ — step 22 needs its u-boot SPL hex]`
3. The project must live at exactly `/home/<user>/quartus_projects/CoreDLA_GHRD`: `IP_SEARCH_PATHS` in `golden_top.qsf` is absolute (`"/home/<user>/quartus_projects/CoreDLA_GHRD/ip/coredla_ip/**/*;/home/<user>/quartus_projects/CoreDLA_GHRD/ip/**/*;hps_subsys/ip/hps_subsys/**/*"`). `[VERIFY: whether IP_SEARCH_PATHS may be rewritten relative — open question, not resolved]`
4. ```bash
   export QUARTUS_ROOTDIR=/home/<user>/altera_pro/25.3.1/quartus
   export PATH=$QUARTUS_ROOTDIR/bin:$PATH
   source /opt/intel/openvino_2024/setupvars.sh
   source /opt/altera/fpga_ai_suite_2025.3.1/dla/setupvars.sh
   ```
5. ```bash
   cd /home/<user>/quartus_projects/CoreDLA_GHRD
   dla_create_ip \
     --arch /opt/altera/fpga_ai_suite_2025.3.1/dla/example_architectures/AGX5_Small_NoSoftmax.arch \
     --ip_dir /home/<user>/quartus_projects/CoreDLA_GHRD/ip/coredla_ip
   ```
   Produces `ip/coredla_ip/altera_ai_ip/` for arch `AGX5_Small_NoSoftmax_AGX5`
   (`K_VECTOR 16`, `C_VECTOR 16`, `NUM_LANES 1`, `NUM_INTERLEAVED_FEATURES 12`;
   CSR AXI 11-bit address / 32-bit data). Consumed by step 12.
6. ```bash
   mkdir -p ip
   cp /opt/altera/fpga_ai_suite_2025.3.1/dla/platform/agx5_soc_s2m/ip/{address_span_extender_axi_256_hw.tcl,address_span_extender_axi_256.v,f2sdram_adapter_256_hw.tcl,f2sdram_adapter_256.v} ip/
   ```
   `ip/f2sdram_adapter_256*` is never instantiated — copied for parity only.
7. Edit `ip/address_span_extender_axi_256.v`: add at line 19
   `parameter [32:0] WINDOW_BASE = 33'h0B0000000;` and make the address paths add it —
   `m0_araddr = {1'b0,s0_araddr} + WINDOW_BASE;` (line 100) and the identical `aw` form
   (line 110). Expose `WINDOW_BASE` in `ip/address_span_extender_axi_256_hw.tcl`.
   Gotcha: the vendor part is a pure zero-extender with no window register despite its name
   and its documentation; without this edit the DLA reads/writes physical `0x0` instead of
   the DDR carveout. `WINDOW_BASE` must stay equal to the devicetree `mem_start` (Phase 3
   step 3) and to `dla_mmd_get_ddr_size_per_instance()`'s base (Phase 3 step 9).
8. Open `qsys_top.qsys` in Platform Designer (`qsys-edit qsys_top.qsys`) and add:
   - `altera_ai_ip` instance named `dla`, `ARCH_OPTION = AGX5_Small_NoSoftmax_AGX5`
   - `address_span_extender_axi_256` instance named `address_span_extender_axi_256_0`
9. Wire, in Platform Designer:
   - `dla` `dla_clk` / `ddr_clk` / `irq_clk` → `clk_100` (100 MHz; the DLA gets no PLL of its own)
   - `dla_resetn` ← `rst_in`
   - `dla.csr_axi` → `subsys_hps.lwhps2fpga`, base `0x00020000`, size `0x800` (phys `0x2002_0000`)
   - `dla.ddr_axi` → `address_span_extender_axi_256_0.s0` (`0x0`–`0xFFFF_FFFF`)
   - `address_span_extender_axi_256_0.m0` → `subsys_hps.f2sdram_adapter_axi4_sub`
   - `dla.irq_level` → `subsys_hps.f2h_irq0_in` line 2
10. `ip/qsys_top/ocm.ip`: change `memorySize` `262144` → `32768`; keep the original as
    `ip/qsys_top/ocm.ip.pre-shrink`.
    Gotcha: the base GHRD already consumes 358/358 M20K, so the fitter fails with no M20K left
    before the DLA is even placed. The OCM is a JTAG/h2f debug scratchpad — no CoreDLA path
    touches it — and shrinking it frees 112 blocks.
11. `golden_top.qsf`: set `IP_SEARCH_PATHS` as in step 3 and add `IP_FILE` entries for
    `ip/qsys_top/qsys_top_address_span_extender_axi_256_0.ip` and
    `ip/qsys_top/qsys_top_ai_ip_0.ip`. Device stays `A5EB013BB23BE4SCS`, family `Agilex 5`,
    top entity `golden_top`. Do not add DLA-specific SDC — `ghrd_timing.sdc` and `jtag.sdc`
    are unchanged and sufficient.
12. Create `add_coredla_msgdma.tcl` in the project root with exactly:
    ```tcl
    package require -exact qsys 25.3
    load_system qsys_top.qsys
    add_instance coredla_msgdma altera_msgdma
    set_instance_parameter_value coredla_msgdma {MODE} {0}
    set_instance_parameter_value coredla_msgdma {DATA_WIDTH} {256}
    set_instance_parameter_value coredla_msgdma {ENHANCED_FEATURES} {1}
    set_instance_parameter_value coredla_msgdma {RESPONSE_PORT} {2}
    set_instance_parameter_value coredla_msgdma {BURST_ENABLE} {0}
    set_instance_parameter_value coredla_msgdma {STRIDE_ENABLE} {0}
    set_instance_parameter_value coredla_msgdma {MAX_BYTE} {1048576}
    set_instance_parameter_value coredla_msgdma {DATA_FIFO_DEPTH} {64}
    set_instance_parameter_value coredla_msgdma {DESCRIPTOR_FIFO_DEPTH} {128}
    set_instance_parameter_value coredla_msgdma {TRANSFER_TYPE} {Unaligned Accesses}
    add_connection clk_100.out_clk coredla_msgdma.clock
    add_connection rst_in.out_reset coredla_msgdma.reset_n
    add_connection subsys_hps.lwhps2fpga coredla_msgdma.csr              baseAddress 0x00021000
    add_connection subsys_hps.lwhps2fpga coredla_msgdma.descriptor_slave baseAddress 0x00021020
    add_connection coredla_msgdma.mm_read  subsys_hps.f2sdram_adapter_axi4_sub baseAddress 0x0
    add_connection coredla_msgdma.mm_write subsys_hps.f2sdram_adapter_axi4_sub baseAddress 0x0
    add_connection subsys_hps.f2h_irq0_in coredla_msgdma.csr_irq         irqNumber 3
    save_system
    ```
    Every value here is load-bearing:
    - No mSGDMA in the fabric at all ⇒ the MMD never enumerates (`mmd_device.h:51 bValid()`
      requires `/dev/msgdma_coredla<N>`) and asserts on `numInstances_`.
    - `TRANSFER_TYPE` must be `Unaligned Accesses`. Gotcha: with `Aligned Accesses` on a
      256-bit path the low address bits are silently dropped and transfers "succeed" while
      moving the wrong bytes (`msgdma_userio` buffers are only 16-byte aligned; a source at
      `0xb0001000` gave 32/32 bytes correct, the same +16 or +4 gave 0/32).
    - `BURST_ENABLE = 0`. Gotcha: the Avalon-MM masters are bridged to AXI4
      (`f2sdram_adapter_axi4_sub`); AXI forbids a burst crossing 4 KiB, Avalon has no such
      rule, and the generated bridge does not split. With bursts on, a transfer starting at
      `+0xF00` corrupts from `0x1000` onward.
    - `MAX_BYTE = 1048576` gives `LENGTH_WIDTH = 21`, i.e. a 1 MB hardware descriptor limit,
      which is what the qualified bitstream contains. It is safe only in combination with the
      256 KB software chunking in Phase 3 step 6 — remove the chunking and descriptors will
      exceed `LENGTH_WIDTH` and truncate silently. `MAX_BYTE = 2147483647` has never been
      built or qualified. `[VERIFY: whether MAX_BYTE = 2147483647 builds, fits and meets
      timing — its compile was killed mid-synthesis, no .sof exists]`
    - `irqNumber 3` on `f2h_irq0_in`. The F2H base is GIC **SPI 17**, so line 3 = **SPI 20**
      (INTID 52). Gotcha: guessing SPI 19 here produced a hard lockup and watchdog reset the
      moment the mSGDMA interrupt fired.
13. ```bash
    qsys-script --script=add_coredla_msgdma.tcl
    ```
    Gotcha: if you ever change mSGDMA parameters that alter the port list (`BURST_ENABLE` is
    one), editing `ip/qsys_top/qsys_top_coredla_msgdma.ip` by hand is not enough —
    `qsys_top.qsys` caches the generic component's port list and the compile dies with
    `Error (13305): can't find port "mm_read_burstcount"`. Use `remove_instance
    coredla_msgdma` and re-run this script. Value-only changes that touch no port
    (`MAX_BYTE` is one) may be substituted directly in the `.qsys` and `.ip`.
14. ```bash
    qsys-generate qsys_top.qsys --synthesis=VERILOG --quartus-project=golden_top.qpf \
      --search-path="ip/coredla_ip/**/*,ip/**/*,hps_subsys/ip/hps_subsys/**/*,\$"
    ```
    Produces `qsys_top/synth/qsys_top.v`. Consumed by step 21.
15. Confirm the generated wrapper before compiling: the `qsys_top_coredla_msgdma`
    instantiation must have **no** `mm_read_burstcount` / `mm_write_burstcount` ports,
    `csr_address` width 3, `descriptor_slave_writedata` 256-bit, `mm_read`/`mm_write` data
    256-bit with 32-bit addresses.
    Gotcha: `qsys-generate` has hung twice at 549 bytes of output at 0 % CPU (wedged JVM).
    Kill orphaned `qsys-generate`/`java` processes — they also block "Run task: IP Generation"
    inside a later `quartus_sh` run. If the previously emitted HDL already checks out, skip
    regeneration.
16. Confirm the built IRQ mapping in `qsys_top/synth/qsys_top.v` and
    `qsys_top/altera_irq_mapper_2001/synth/*.sv`: `sender_irq[0]=dipsw_pio`,
    `[1]=button_pio`, `[2]=dla.irq_level`, `[3]=coredla_msgdma`.
17. If a previous compile left a stale Quartus Pro database, move `dni/` aside (do not delete)
    and let it regenerate.
    Gotcha: a stale `dni/` pointing at a deleted `qdb/` aborts the compile before any stage
    with `Error (22912) … DDM_T::verify_token : Cannot identify the client`.
18. If you cleared build state with `rm -rf`, restore `tmp-clearbox/`: `git checkout -- tmp-clearbox`.
    Gotcha: unlike `qdb/`, `db/` and `incremental_db/`, `tmp-clearbox/` (78 `.tdf` files) is
    tracked in git and not gitignored; deleting it makes the DDM error above instant.
19. ```bash
    quartus_sh --flow compile golden_top > compile.log 2>&1
    ```
    Gotcha: never pipe this command (e.g. into `head`) — the pipe SIGPIPEs Quartus, `$?`
    reports the pipe's status, and a killed compile looks like exit 0 while the `.sof` stays
    stale. Redirect to a log and check the `.sof` timestamp.
20. Expected reports in `output_files/`: `golden_top.fit.summary` — ALM 35,054/46,800 (75 %),
    M20K 249/358 (70 %), DSP 32/188, PLL 2/11; `golden_top.sta.summary` — worst setup slack
    **+1.844** on `pll_inst|iopll_0_outclk0`, TNS 0.000, no violations.
21. Artifact: `output_files/golden_top.sof` (md5 of the qualified build
    `ecd331a8c550b5f5702cfd8c40a62a73`). Consumed by step 22 only.
22. ```bash
    quartus_pfg -c -o hps=on \
      -o hps_path=/home/<user>/quartus_projects/DE25_Nano_Resource/DE25-Nano_revB_v.1.0.0_ResourcePackage/Demonstration/SoC_FPGA/GHRD/software/u-boot/spl/u-boot-spl-dtb.hex \
      output_files/golden_top.sof output_files/golden_top.rbf
    ```
    Emits `output_files/golden_top.core.rbf` (3342336 B, md5 of the qualified build
    `e8870f9adbc459d07df904b60a78ada4`) plus `golden_top.hps.rbf` and
    `golden_top_hps_auto.sof`. **Only `golden_top.core.rbf` is deployed** — it is consumed by
    Phase 3 step 14. `golden_top_hps.jic` / QSPI / RSU are not part of this board's boot path.

**Phase 1 verification.** The mSGDMA parameters actually inside the bitstream must match the
tcl — read them out of the synthesis report that produced this `.sof`, not out of the sources:

```bash
grep -E 'BURST_ENABLE|STRIDE_ENABLE|UNALIGNED_ACCESSES_ENABLE|ENHANCED_FEATURES|RESPONSE_PORT|DATA_FIFO_DEPTH|DESCRIPTOR_FIFO_DEPTH|LENGTH_WIDTH' \
  output_files/golden_top.syn.rpt
```
Required: `BURST_ENABLE = 0`, `STRIDE_ENABLE = 0`, `UNALIGNED_ACCESSES_ENABLE = 1`,
`ENHANCED_FEATURES = 1`, `RESPONSE_PORT = 2`, `DATA_FIFO_DEPTH = 64`,
`DESCRIPTOR_FIFO_DEPTH = 128`, `LENGTH_WIDTH = 21`. Together with the step 20 fit/timing
numbers this proves the phase.

---

## Phase 2 — Create and flash the SD card image

The image is a **bare bootable baseline**: kernel, u-boot, Ubuntu rootfs. It contains no
bitstream, no CoreDLA device tree, no msgdma modules and no application payload — all of that
is layered on in Phase 3.

1. ```bash
   cd /home/<user>/coredla_work/de25_nano_bringup
   git clone -b de25_nano_revA_v1.0 https://github.com/terasic/linux-socfpga linux
   cd linux && git checkout d7d192a9d
   ```
   `d7d192a9d "add support for de25-nano"` — the kernel that reports
   `6.12.11-gd7d192a9ddd9-dirty` on the board. Every later step that references
   `$(uname -r)` on the board means this string.
2. `[VERIFY: kernel defconfig / base .config used for the DE25-Nano build — not recorded]`
3. ```bash
   cd /home/<user>/coredla_work/de25_nano_bringup/linux
   make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- -j$(nproc) Image
   ```
   Produces `arch/arm64/boot/Image` (46832128 B, md5 `063418677210af43027827d69a09910f`).
   Consumed by step 6 and, at boot, by the u-boot script from Phase 3 step 11.
4. `[EXTERNAL STEP: u-boot.itb for the DE25-Nano (1008304 B, md5 8cf307c866ab4c251327b5005f90a302) — its build is not recorded in the investigated tree]`
5. `[EXTERNAL STEP: Ubuntu 22.04 aarch64 root filesystem staged at de25_nano_bringup/rootfs_build/rootfs/ — origin not recorded. glibc is 2.35 there; this is why Phase 3 step 10 ships sdklibs/]`
6. Stage `de25_nano_bringup/rootfs_build/fatfs/` with `Image` (step 3), `u-boot.itb` (step 4),
   the stock `boot.scr.uimg` (1116 B, md5 `891271690f0d39fa26a98d74131451d4`) and
   `socfpga_agilex5_de25_nano.dtb`.
   Gotcha: the DTB that ends up in the baseline image is irrelevant and will be wrong — the
   stock Terasic CoreDLA demo DTB describes a different design (`coredla0@20014000`, msgdmas
   at `0x2000_0000`/`0x2000_1000`, plus `layout_transform0` and `stream_controller0`), and
   the staging tree has historically also held a pre-fix build. Phase 3 step 14 overwrites it
   on the card with the DTB built in Phase 3 step 4. Do not rely on `fatfs/`'s copy.
7. ```bash
   cd /home/<user>/coredla_work/de25_nano_bringup/rootfs_build
   sudo python3 make_sdimage_p3.py -f \
     -P fatfs/*,num=1,format=fat32,size=500M \
     -P rootfs/*,num=2,format=ext3,size=5000M \
     -s 5500M -n sdcard.img
   ```
   Produces `rootfs_build/sdcard.img`, 5767168000 B, 5500 MiB: p1 FAT32 500 M, p2 ext3 5000 M.
   This is the image that was flashed to the working board.
8. Write `sdcard.img` to the microSD card and insert it in the DE25-Nano.
   `[VERIFY: exact flashing command/device used — no flashing command survives in the host's history]`

**Phase 2 verification.** Loopback-mount the image read-only and check the two FAT files that
must be byte-exact, since everything else on p1 is replaced later:

```bash
sudo losetup -Pf --show -r sdcard.img          # e.g. /dev/loop7
sudo mount -o ro /dev/loop7p1 /mnt/img
md5sum /mnt/img/Image /mnt/img/boot.scr.uimg
sudo umount /mnt/img && sudo losetup -d /dev/loop7
```
Required: `Image` → `063418677210af43027827d69a09910f`, `boot.scr.uimg` →
`891271690f0d39fa26a98d74131451d4`. Confirm p2 mounts and holds
`/lib/modules/6.12.11-gd7d192a9ddd9-dirty/`.

---

## Phase 3 — Enable the runtime

### Host: kernel modules and device tree

1. Edit `de25_nano_bringup/linux/arch/arm64/boot/dts/intel/socfpga_agilex5.dtsi` and append
   (~line 1254) exactly:
   ```dts
   coredla_msgdma: msgdma@20021000 {
       status = "okay";
       compatible = "altr,socfpga-msgdma";
       reg = <0x20021000 0x00000020>, <0x20021020 0x00000020>;
       reg-names = "csr", "desc";
       interrupt-parent = <&intc>;
       interrupts = <0 20 4>;              /* SPI 20 */
       #dma-cells = <1>;
   };

   msgdma_coredla0 {
       status = "okay";
       compatible = "intel,msgdma-userio-1.0";
       #address-cells = <2>;
       mem_start = <0x00000000 0xB0000000>;
       mem_end   = <0x00000000 0xBFFFFFFF>;
       reg-names = "emif";
       dmas = <&coredla_msgdma 0>;
       dma-names = "rx-tx";
   };

   coredla0@20020000 {
       status = "okay";
       compatible = "generic-uio";
       reg = <0x20020000 0x00000800>;
   };
   ```
   Addresses are the LWH2F view: bridge base `0x2000_0000` + the Platform Designer offsets
   from Phase 1 (`0x20000` DLA CSR, `0x21000` mSGDMA CSR, `0x21020` descriptor slave).
   `mem_start`/`mem_end` are the 256 MB DLA carveout and must equal Phase 1 step 7's
   `WINDOW_BASE`.
   Gotcha: all five DLA nodes sit `+0xc000` above the stock Terasic demo map because this
   board's `lwhps2fpga` window already holds `subsys_periph.pb_cpu_0_s0` at `0x0`–`0x1FFFF`.
   `drivers/dma/altera-msgdma.c` itself is **not** modified.
2. ```bash
   cd /home/<user>/coredla_work/de25_nano_bringup/linux
   scripts/config --module CONFIG_ALTERA_MSGDMA
   scripts/config --module CONFIG_UIO_PDRV_GENIRQ
   make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- syncconfig
   ```
   Gotcha: `make syncconfig` is mandatory — `scripts/config` does not regenerate
   `include/config/auto.conf`, and without it the module build silently produces nothing.
3. ```bash
   make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- -j$(nproc) M=drivers/dma modules
   ```
   Produces `drivers/dma/altera-msgdma.ko`. Consumed by step 14.
   `[VERIFY: md5 of the altera-msgdma.ko actually loaded on the working board — the host tree
   holds 113136 B / md5 d241718f… but the board copy was never checksummed]`
4. ```bash
   make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- dtbs
   ```
   Produces `arch/arm64/boot/dts/intel/socfpga_agilex5_de25_nano.dtb`, 24826 B, md5
   `f432d939dcdab3e18cb4c8a8536ec828`. Consumed by step 14.
5. ```bash
   mkdir -p /home/<user>/coredla_work/de25_nano_bringup/msgdma_userio_module
   cp /opt/altera/fpga_ai_suite_2025.3.1/dla/hps/ed4/yocto/meta-altera-fpga-coredla/recipes-drivers/msgdma-userio/files/* \
      /home/<user>/coredla_work/de25_nano_bringup/msgdma_userio_module/
   ```
6. Patch `msgdma_userio_chr.c` (vendor file 13824 B → patched 17075 B): add
   `msgdma_userio_xfer_sg()` with `#define MSGDMA_USERIO_MAX_CHUNK (256 * 1024)`, per-sg-entry
   submit **and** wait, and an EMIF offset that advances per entry —
   `len = min_t(size_t, remaining, MSGDMA_USERIO_MAX_CHUNK)` (lines 254 / 297); route both the
   read path (line 374) and the write path (line 412) through it.
   Gotcha (two distinct bugs, one patch): `dmaengine_prep_slave_sg()` reuses `cfg->dst_addr`
   for every descriptor (`altera-msgdma.c:428`) — Altera assumes an SMMU coalesces the sg
   list, but this mSGDMA sits outside it, so round trips passed to 1 KB and failed from 4 KB
   up until each entry got its own advancing offset. And `msgdma_start_transfer()` issues only
   the head of `pending_list` plus its `tx_list`, so independently submitted descriptors are
   stranded and `dma_sync_wait` times out — hence submit-and-wait per entry, never batch.
   Gotcha: the 256 KB cap is also the only guard against over-length descriptors on the
   `MAX_BYTE = 1 MB` fabric — `altera-msgdma` will not split for you
   (`MSGDMA_MAX_TRANS_LEN = U32_MAX`, `altera-msgdma.c:26,424`) and a 2 MiB coalesced sg entry
   has been observed (`DMA Failed at sg entry 1/3 len=2097152`). Do not remove it.
7. ```bash
   cd /home/<user>/coredla_work/de25_nano_bringup/msgdma_userio_module
   make ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- \
        KERNEL_SRC=/home/<user>/coredla_work/de25_nano_bringup/linux modules
   ```
   Produces `msgdma_userio.ko`, 113712 B, md5 `abf501582ac08ff2ce377016bb4bf01f`.
   Consumed by step 14.

### Host: MMD, runtime and model

8. Working tree `/home/<user>/coredla_work` at commit `cd9e664` (the FPGA plugin build
   string on the board is `main-cd9e664793`). Environment:
   ```bash
   source /opt/intel/openvino_2024/setupvars.sh
   source /opt/altera/fpga_ai_suite_2025.3.1/dla/bin/init_env.sh
   cd /home/<user>/coredla_work && source ./coredla_work.sh
   ```
   `coredla_work.sh` gates on `build_version.txt` matching
   `/opt/altera/fpga_ai_suite_2025.3.1/dla/build_version.txt` — both must read `2025.3.1/20`.
9. Patch four files under `/home/<user>/coredla_work/runtime`:
   - `create_hps_image.sh` — add `agilex5_de25_nano` to the machine whitelist and usage text.
   - `CMakeLists.txt` — `agilex5_de25_nano` sets `-DHPS_AGX5`, plus a new block setting
     `-DHPS_DE25_NANO` for that machine only.
   - `coredla_device/mmd/hps_platform/host/acl_hps.cpp`, under `HPS_DE25_NANO`:
     `dla_mmd_get_ddr_size_per_instance()` returns `1ULL << 28` (256 MB, generic AGX5 default
     is `1ULL << 29` and runs the DDR window past the carveout into kernel memory);
     `dla_mmd_get_ml_frequency()` returns `100` (the DLA shares `clk_100`; leaving the 200 MHz
     assumption reports throughput at 2× the real rate); `dla_mmd_get_ddr_clock_freq()`
     returns `200`. Also return `-1` when the board-name list is empty (an empty list was
     being reported as success) and return `-1` — not `FAILURE`, which is `1` and passes
     `mmd_wrapper.cpp:47`'s `handle < 0` test — from a failed `aocl_mmd_open`.
     `[VERIFY: the real DE25-Nano LPDDR4 rate — 200 MHz is copied from the generic AGX5
     default and has never been read off the hardware; affects reported bandwidth only]`
   - `coredla_device/mmd/hps_platform/host/mmd_device.cpp` — derive the DMA device name with
     `glob("/dev/msgdma_coredla*")` instead of building it from the UIO index (CoreDLA is not
     always `uio0`), with an explicit `LOG_ERR` when nothing matches.
10. ```bash
    cd /home/<user>/coredla_work/runtime
    ./build_hpspackages.sh -sb
    ```
    Builds the ARM prerequisites into `runtime/hps_packages/armcpu_package/` (OpenCV 4.8.0,
    gflags 2.2.2, boost, pugixml). Consumed by step 12.
11. ```bash
    python3 -m venv /home/<user>/coredla_work/runtime/.cmake_venv
    /home/<user>/coredla_work/runtime/.cmake_venv/bin/pip install cmake==3.31.10
    ```
    Gotcha: system CMake 3.28.3 cannot read the v10 `CMakePresets.json`, and CMake 4.x rejects
    `cmake_minimum_required(VERSION 2.8.12)`. 3.31.10 is the version that works.
12. ```bash
    source /opt/intel/openvino_2024/setupvars.sh
    source /opt/altera/fpga_ai_suite_2025.3.1/dla/bin/init_env.sh
    export PATH=/home/<user>/coredla_work/runtime/.cmake_venv/bin:$PATH
    cd /home/<user>/coredla_work/runtime
    ./build_runtime.sh -hps_platform -hps_machine=agilex5_de25_nano
    ```
    Gotcha: `-hps_machine` must be `agilex5_de25_nano`. Any other value (e.g.
    `agilex5_mk_a5e065bb32aes1`) builds cleanly but never defines `-DHPS_DE25_NANO`, so the
    binary silently uses the generic AGX5 DDR size and clock from step 9.
    Produces `runtime/build_Release/coredla_device/mmd/hps_platform/libhps_platform_mmd.so`
    (md5 `1c0dbd3b7453c80ae9cd76a0e37d73de`) and
    `runtime/build_Release/dla_benchmark/dla_benchmark`. Both consumed by step 15.
    Expect `Warning: using polling instead of interrupts` in the build log —
    `OPT_RUNTIME_POLLING=true` is forced for `--hps_platform`, so the DLA's own UIO interrupt
    is never armed.
13. Compile the model:
    ```bash
    source /opt/intel/openvino_2024/setupvars.sh
    source /opt/altera/fpga_ai_suite_2025.3.1/dla/bin/init_env.sh
    cd /home/<user>/coredla_work/de25_nano_bringup/model_prep
    dla_compiler \
      --march /opt/altera/fpga_ai_suite_2025.3.1/dla/example_architectures/AGX5_Small_NoSoftmax.arch \
      --network-file models_ir/public/resnet-50-tf/FP32/resnet-50-tf.xml \
      --foutput-format dla_compiled_result --o compiled/resnet50.bin --fdisplay-device
    ```
    The IR comes from `omz_downloader` / `omz_converter` for `resnet-50-tf` in a venv with
    `openvino-dev==2024.6.0`. Produces `compiled/resnet50.bin`, 154273176 B, md5
    `a0b0d1feb678106106c3175184d1f89f` — this is the file that runs on the board, renamed to
    `resnet50_nosoftmax.bin`. Consumed by step 15 and Phase 4.
    (`compiled/resnet50_nofold.bin` — same command plus `--ffolding-option 0` — is for
    `streaming_inference_app` and was not used in the qualified run.)

### Board: deploy

Board is booted from the Phase 2 card; reach it over the serial console (`ttyS0`, 115200,
`terasic` / `<BOARD_PASSWORD>`) or `scp` if the network is up.

14. Copy `golden_top.core.rbf` (Phase 1 step 22), `socfpga_agilex5_de25_nano.dtb` (step 4),
    `msgdma_userio.ko` (step 7) and `altera-msgdma.ko` (step 3) to the board's `/tmp/`, then:
    ```bash
    K=6.12.11-gd7d192a9ddd9-dirty
    sudo mountpoint -q /mnt/fat || sudo mount /dev/mmcblk0p1 /mnt/fat
    [ -f /mnt/fat/golden_top.core.rbf.orig ] || sudo cp -a /mnt/fat/golden_top.core.rbf /mnt/fat/golden_top.core.rbf.orig
    [ -f /mnt/fat/socfpga_agilex5_de25_nano.dtb.orig ] || sudo cp -a /mnt/fat/socfpga_agilex5_de25_nano.dtb /mnt/fat/socfpga_agilex5_de25_nano.dtb.orig
    sudo cp /tmp/golden_top.core.rbf /mnt/fat/golden_top.core.rbf
    sudo cp /tmp/socfpga_agilex5_de25_nano.dtb /mnt/fat/socfpga_agilex5_de25_nano.dtb
    sudo install -m 644 /tmp/msgdma_userio.ko /lib/modules/$K/extra/msgdma_userio.ko
    sudo install -m 644 /tmp/altera-msgdma.ko /lib/modules/$K/kernel/drivers/dma/altera-msgdma.ko
    sudo depmod -a
    ```
    (If the network is down, ship each `.ko` as `base64 -w 76` streamed over the serial
    console into a board-side heredoc, `base64 -d`, then `md5sum`-verify before installing.)
15. Stage `/home/terasic/app` (≈513 MB): `dla_benchmark` and `libhps_platform_mmd.so` from
    step 12, `dla_benchmark.sh`, `plugins.xml`, the OpenVINO/OpenCV runtime libraries,
    `sdklibs/`, and `resnet-50-tf/` containing `resnet50_nosoftmax.bin` (= step 13's
    `compiled/resnet50.bin`), `AGX5_Small_NoSoftmax.arch` (copied from
    `/opt/altera/fpga_ai_suite_2025.3.1/dla/example_architectures/`) and `images/`.
    Gotcha: the board rootfs is Ubuntu 22.04 (glibc 2.35) while the Yocto-SDK-linked binaries
    need glibc 2.39, so `app/sdklibs/` must carry the SDK loader and libraries and the
    binaries must be launched through it —
    `./sdklibs/ld-linux-aarch64.so.1 --library-path ./sdklibs:. ./dla_benchmark`.
    `[EXTERNAL STEP: the Yocto ARM SDK at coredla_work/runtime/embedded_arm_sdk/sysroots/armv8-2a-poky-linux, source of sdklibs/ — its build is not reconstructable from the investigated tree]`
    `[VERIFY: the exact command that assembled and transferred the 513 MB /home/terasic/app payload]`
    `[VERIFY: provenance of the 10 input images in ~/app/resnet-50-tf/images (val_00000000.bmp …)]`
16. ```bash
    echo 'options uio_pdrv_genirq of_id=generic-uio' | sudo tee /etc/modprobe.d/coredla.conf
    printf 'uio_pdrv_genirq\naltera_msgdma\nmsgdma_userio\n' | sudo tee /etc/modules-load.d/coredla.conf
    ```
    Gotcha: without the `of_id=generic-uio` option `uio_pdrv_genirq` never binds
    `compatible = "generic-uio"` and the runtime fails with `Failed to open - /dev/uio0`.
    Load order matters: `uio_pdrv_genirq`, then `altera_msgdma`, then `msgdma_userio`.
17. Build and install the boot script that loads the bitstream. On the host:
    ```bash
    cd /home/<user>/coredla_work/de25_nano_bringup/uboot-script
    mkimage -A arm64 -O linux -T script -C none -n "DE25 Nano boot script" \
            -d boot_coredla.txt boot.scr.uimg
    ```
    `boot_coredla.txt` (1308 B) is the stock script with exactly two changes in the `mmc0`
    branch — the `fatload`/`fpga load` block placed **before** `bridge enable`, and `mem=768M`
    in `bootargs`:
    ```
    if test ${target} = "mmc0"; then
    	echo "Found kernel in mmc0";
    	mmc rescan;
    	if fatload mmc 0:1 0x90000000 golden_top.core.rbf; then
    		if fpga load 0 0x90000000 ${filesize}; then
    			echo "FPGA core configured";
    		else
    			echo "FPGA load FAILED - booting anyway";
    		fi;
    	else
    		echo "no golden_top.core.rbf - booting anyway";
    	fi;
    	bridge enable;
    	fatload mmc 0:1 ${kernel_addr_r} Image;
    	fatload mmc 0:1 ${fdt_addr_r} socfpga_agilex5_de25_nano.dtb;
    	setenv bootargs "console=ttyS0,115200 root=${mmcroot} rw rootwait mem=768M";
    	booti ${kernel_addr_r} - ${fdt_addr_r};
    	exit;
    fi
    ```
    Output is 1380 B (deployed md5 `57f6b60e99cb4409f9486e6b8e3d842d`; only the 64-byte uImage
    header's timestamp and CRCs vary between rebuilds).
    `mem=768M` is what puts the top 256 MB of the 1 GiB board at `0xB000_0000` for the DLA
    carveout; the kernel then owns up to `0xAFFF_FFFF` and sees 683 MB usable.
    Gotcha: do not use `uboot-script/uboot.txt` (1044 B) or its `boot.scr.uimg` — that is an
    unrelated `iommu.passthrough=on` experiment with no `fpga load` and no `mem=`.
18. Install it on the board, preserving the stock script:
    ```bash
    [ -f /mnt/fat/boot.scr.uimg.bak ] || sudo cp -a /mnt/fat/boot.scr.uimg /mnt/fat/boot.scr.uimg.bak
    sudo cp /tmp/boot.scr.uimg /mnt/fat/boot.scr.uimg
    sudo sync
    ```
19. ```bash
    sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
    sudo mkswap /swapfile && sudo swapon /swapfile
    echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
    ```
    Gotcha: with `mem=768M` only 683 MB is usable and `dla_benchmark` peaks around 475 MB RSS —
    without swap it gets OOM-killed.
20. ```bash
    sed -i "s/libopenvino_intel_cpu_plugin.so/libopenvino_arm_cpu_plugin.so/" ~/app/plugins.xml
    ```
    Gotcha: the shipped `plugins.xml` hardcodes the x86 CPU plugin.
21. ```bash
    sudo umount /mnt/fat && sudo reboot
    ```
    u-boot now does `fatload mmc 0:1 0x90000000 golden_top.core.rbf` → `fpga load 0 …` →
    `bridge enable` → load DTB → `booti`. The bitstream comes from the FAT partition, not from
    the FIT image, not from JTAG, not from the Linux fpga_manager.
22. After every boot or module reload:
    ```bash
    sudo rmmod msgdma_userio; sudo rmmod altera_msgdma
    sudo modprobe altera_msgdma
    sudo insmod /usr/lib/modules/$(uname -r)/extra/msgdma_userio.ko
    sudo chmod 660 /dev/msgdma_coredla0 /dev/uio0
    sudo chgrp terasic /dev/msgdma_coredla0 /dev/uio0
    ```
    Gotcha: reloading **both** modules in this dependency order is the recovery for a wedged
    DMA engine (`altera-msgdma 20021000.msgdma: dma_sync_wait: timeout!` → `DMA Failed at sg
    entry …` → a `WriteToDDR` assertion while loading the 150 MB weights). Once the engine
    stalls, `dmaengine_terminate_sync()` → `msgdma_reset()` does not recover `altera-msgdma`'s
    internal state, and even a 4 KB transfer then hangs the full 5 s timeout. What triggers
    the initial stall is unknown; the recovery is reliable.
    Gotcha: there is no udev rule — `/dev/uio0` and `/dev/msgdma_coredla0` come back root-only
    after every load, so the `chmod`/`chgrp` must be repeated each time.
    Gotcha: `/sys/class/fpga_manager/fpga0/state` reads `unknown` even with the fabric live,
    because u-boot's `fpga load` bypasses the Linux fpga_manager. Never gate on it.
    Gotcha: `/sys/class/uio/uio0/maps/map0/size` reads `0x1000`, not the DT's `0x800` — UIO
    rounds up to a page. Expected, not a fault.

**Phase 3 verification.** Read the DLA's CSR identity through the UIO node — this proves the
fabric is configured with *this* CoreDLA design and that the UIO binding, the address map and
the bitstream delivery path all work:

```bash
sudo python3 -c "
import mmap,os
f=os.open('/dev/uio0',os.O_RDONLY)
m=mmap.mmap(f,0x1000,prot=mmap.PROT_READ)
print(m[0x10:0x20]); print(m[0x30:0x50])"
```
Required: `b'2025.3.1/20\x00\x00\x00\x00\x00'` and `AGX5_Small_NoSoftmax`. Alongside it,
`cat /sys/class/uio/uio0/name` must print `coredla0@20020000`, `grep msgdma /proc/interrupts`
must show `GICv3  52 Level  20021000.msgdma` with a nonzero and rising count, and
`ls -l /dev/msgdma_coredla0` must show `crw-rw---- root terasic` (511:0).

---

## Phase 4 — Run the benchmark on the board

1. ```bash
   export COREDLA_ROOT=/home/terasic/app
   cd ~/app
   ```
2. ```bash
   ./dla_benchmark.sh \
     -cm resnet-50-tf/resnet50_nosoftmax.bin \
     -arch_file resnet-50-tf/AGX5_Small_NoSoftmax.arch \
     -plugins ./plugins.xml \
     -i resnet-50-tf/images \
     -d HETERO:FPGA,CPU -niter 8 -api sync
   ```
   Use `./plugins.xml` — the one edited in Phase 3 step 20. (Some in-tree documentation shows
   `-plugins ./plugins_arm.xml`; that is not what the qualified run used.)
   `Import model took` ≈ 76 s for the 154 MB compiled model — that is normal, not a hang.

**Phase 4 verification.** The run must reach `[Step 12/12] Dumping the output values` having
printed `Runtime arch check passed` and `Runtime build version check passed`, and its
`[Step 11/12]` statistics must match the qualified result on the IP-side figures, which are
fabric-determined and reproduce to four significant figures across runs:

```
count:             8 iterations
IP duration:       1847.4772 ms
IP throughput per instance: 4.3302 FPS
IP clock frequency measurement: 100.0000 MHz
number of hardware instances: 1
```
System-side figures move with host CPU scheduling (`system duration` 3776–3886 ms, `latency`
468–475 ms, `system throughput` 2.10–2.13 FPS). Afterwards, the `20021000.msgdma` count in
`/proc/interrupts` must have risen (≈3000 per 8-iteration run) and `dmesg` must contain no
`dma_sync_wait: timeout!`.
