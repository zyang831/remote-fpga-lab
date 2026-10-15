# USB webcam fix: dwc2 host FIFO kernel patch

Status 2026-09-28: **working, with the WiFi dongle removed.** New kernel + dtb boot
(backups `*.pre-dwc2fifo` kept). With webcam + dongle on the hub it still failed (see
"Test result 2026-09-28"); with the board on Ethernet and the webcam alone on the USB port
it passed a 17 min soak (see "Test result 2: webcam alone").
Follow-up done: `ustreamer` enabled at boot, ustreamer/:8080 checks restored in
`artifacts/reset.sh` and `demo/RUNBOOK.md`. Overnight soak not run.

## Problem recap

- Board has one USB host controller in use: dwc2 `usb@10b00000` (dwc3 `usb1@11000000` is
  disabled). Webcam and WiFi dongle share the FE1.1s hub behind it. A different hub does
  not help: every device funnels through dwc2's single root port and FIFO.
- **Symptom 1, no frames:** uvcvideo logs ~450/s `USB isochronous frame lost (-63)`.
  `-63` is `-ENOSR`, set by dwc2 on `DWC2_HC_XFER_FRAME_OVERRUN` for an IN channel
  (`drivers/usb/dwc2/hcd_intr.c`): the isochronous transfer did not finish in its
  microframe. ustreamer gets no good frames, times out, reopens (647 restarts / 13 min).
- **Symptom 2, USB wedge:** `arm-smmu-v3 event 0x10`, StreamID 6 (dwc2), then
  `uvcvideo -110`, AIC8800 command timeouts, WiFi/Tailscale gone. Only a power cycle
  recovers. Webcam traffic is the trigger (see `docs/CAMERA_MIGRATION_PLAN.md`).

## Root cause of symptom 1 (confirmed on board via debugfs)

```
hw_params: rx_fifo_size 8192, host_nperio_tx_fifo_size 8192, host_perio_tx_fifo_size 8192
hw_params: total_fifo_size 8064
params:    host_rx_fifo_size 532, host_nperio_tx_fifo_size 256, host_perio_tx_fifo_size 768
```

The FIFO size registers reset to 8192 words each, which oversubscribes the 8064-word FIFO
RAM. `dwc2_calculate_dynamic_fifo()` (`hcd.c`) sees that and falls back to "Method 2"
minimum sizes: RX FIFO 532 words = 2128 B. The webcam always selects Alt 11 =
3 x 1020 B per microframe (3060 B), which does not fit, so transfers overrun.

Per-SoC dwc2 params never apply because the Agilex5 device tree lists the controller as
plain `compatible = "snps,dwc2"`. Agilex7 dtsi uses
`"intel,socfpga-agilex-hsotg", "snps,dwc2"`, which selects
`dwc2_set_socfpga_agilex_params()`.

## The fix

1. **Kernel** (`drivers/usb/dwc2/params.c`, `dwc2_set_socfpga_agilex_params`): set host
   FIFOs explicitly, RX 4096 / non-periodic TX 1024 / periodic TX 1024 words
   (6144 of 8064).
2. **Device tree:** usb0 compatible becomes
   `"intel,socfpga-agilex-hsotg", "snps,dwc2"` so the kernel uses those params. This also
   applies the existing Agilex settings `power_down = NONE`, `no_clock_gating = true`
   (same as Agilex7).

Either file rolled back alone is harmless: new dtb + old kernel = old FIFOs; old dtb +
new kernel = old FIFOs.

```diff
--- a/drivers/usb/dwc2/params.c
+++ b/drivers/usb/dwc2/params.c
@@ static void dwc2_set_socfpga_agilex_params(struct dwc2_hsotg *hsotg)
 	p->power_down = DWC2_POWER_DOWN_PARAM_NONE;
 	p->no_clock_gating = true;
+	/*
+	 * GRXFSIZ/GNPTXFSIZ/HPTXFSIZ reset to 8192 each, which oversubscribes
+	 * the 8064-word SPRAM, so dwc2 falls back to minimum FIFOs (RX 532).
+	 * That RX FIFO cannot hold a 3x1024 high-bandwidth isoc microframe and
+	 * UVC webcams hit frame overrun (-ENOSR). Size explicitly: 6144/8064.
+	 */
+	p->host_rx_fifo_size = 4096;
+	p->host_nperio_tx_fifo_size = 1024;
+	p->host_perio_tx_fifo_size = 1024;
 }
```

### Build provenance

- Kernel source for the running kernel: `~/coredla_work/de25_nano_bringup/linux`
  (its pre-patch Image md5 `063418677210af43027827d69a09910f` = the board's FAT `Image`).
  `~/de25-nano.sdmmc/linux-socfpga` is a different build, do not use it.
- Config = board's `/proc/config.gz` exactly (the tree's previous `.config` is kept as
  `.config.pre-dwc2fifo`; only difference was `CONFIG_ALTERA_MSGDMA=m`).
- Build: `ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- make -j32 Image` (~2 min).
  Release string stays `6.12.11-gd7d192a9ddd9-dirty`, so the modules already on the board
  (`uvcvideo`, `aic8800`, ...) load unchanged. No module reinstall.
- dtb = the board's deployed dtb (md5 `b77eaeb130c242593c57c745daebbb0f`, edited after
  build, so NOT the tree's dtb) with one change:
  `fdtput -t s <dtb> /soc@0/usb@10b00000 compatible intel,socfpga-agilex-hsotg snps,dwc2`

Staged in `~/coredla_work/de25_nano_bringup/boot_setup/dwc2fifo/`:

| File | md5 |
|------|-----|
| `Image` | `484f6ea918276264f3d097c3cef5d61e` |
| `socfpga_agilex5_de25_nano.dtb` | `ec4a409701dc76b715039bbb0ca1996e` |
| `dwc2-host-fifo.patch` | `d2f0ca847bb65c8edfd25776ddcfa0c2` |

## Deploy procedure (in the lab)

Before starting: serial console cable on the dev machine (`/dev/ttyUSB0`, 115200), webcam
at hand. The webcam must be attached **from boot**: the earlier SMMU faults only
reproduced that way.

1. Copy files to the board and verify checksums:
   ```
   D=~/coredla_work/de25_nano_bringup/boot_setup/dwc2fifo
   scp $D/Image $D/socfpga_agilex5_de25_nano.dtb terasic@coredla:/tmp/
   ssh terasic@coredla 'md5sum /tmp/Image /tmp/socfpga_agilex5_de25_nano.dtb'
   ```
   Must match the table above.
2. Back up the current boot files and install the new ones (FAT partition `mmcblk0p1`):
   ```
   ssh -t terasic@coredla 'sudo sh -c "
     mount /dev/mmcblk0p1 /mnt/b &&
     cp /mnt/b/Image /mnt/b/Image.pre-dwc2fifo &&
     cp /mnt/b/socfpga_agilex5_de25_nano.dtb /mnt/b/socfpga_agilex5_de25_nano.dtb.pre-dwc2fifo &&
     cp /tmp/Image /tmp/socfpga_agilex5_de25_nano.dtb /mnt/b/ &&
     sync && md5sum /mnt/b/Image /mnt/b/socfpga_agilex5_de25_nano.dtb* ; umount /mnt/b"'
   ```
3. `ssh terasic@coredla sudo poweroff`, wait for it to halt, plug the webcam into the hub,
   then **power cycle** (not a warm reboot: warm reboot can leave the WiFi dongle dead).
4. Confirm the new kernel and FIFOs:
   ```
   ssh -t terasic@coredla 'uname -v; sudo sh -c "
     mount -t debugfs none /sys/kernel/debug 2>/dev/null;
     grep fifo_size /sys/kernel/debug/usb/10b00000.usb/params | head -3;
     head -3 /sys/kernel/debug/usb/10b00000.usb/fifo"'
   ```
   Expect `host_rx_fifo_size : 4096` and `RXFIFO: Size 4096`. `uname -v` shows today's
   build date. WiFi/Tailscale must be up (you just ssh'd in).
5. Start the webcam stream for the test and turn on uvcvideo frame tracing:
   ```
   ssh -t terasic@coredla 'sudo sh -c "
     echo 0x80 > /sys/module/uvcvideo/parameters/trace; systemctl start ustreamer"'
   ```
6. Soak **at least 15 min** (fault latency has ranged 38-715 s; a short clean run proves
   nothing). Check every few minutes:
   ```
   ssh terasic@coredla 'curl -s localhost:8080/state | grep -o "\"captured_fps\": *[0-9]*";
     dmesg | grep -c "frame lost"; dmesg | grep -c "smmu-v3.*event";
     tail -1 ~/smmu_trace.log'
   ```
   Also open `http://coredla:8080/` and confirm live video, not the NO SIGNAL placeholder.

## Pass / fail

| Result | Meaning | Next |
|--------|---------|------|
| captured_fps ~30, `frame lost` ~0, 0 SMMU events, WiFi up for 15+ min | Both symptoms fixed | Enable ustreamer at boot (`systemctl enable ustreamer`), restore ustreamer/:8080 checks in `artifacts/reset.sh` + `demo/RUNBOOK.md`, soak overnight |
| `frame lost` still climbing, no SMMU | FIFO helped not enough, overrun from interrupt latency | Second patch: enable host descriptor DMA (`dma_desc_enable`), so the controller schedules isochronous transfers without per-microframe interrupts |
| Video OK but SMMU `event 0x10` + WiFi drop | Symptom 1 fixed, wedge is a separate dwc2/SMMU bug | Debug with `CONFIG_USB_DWC2_DEBUG` / `iommu.passthrough=1` as a diagnostic; meanwhile unplug webcam |
| Board does not come back on the network | Boot or USB failure | Serial console, see rollback |

Turn tracing back off after the test: `echo 0 > /sys/module/uvcvideo/parameters/trace`.

## Test result 2026-09-28

Power cycled with webcam attached from boot. Kernel `#3 ... Sep 27`, debugfs
`host_rx_fifo_size 4096` / `RXFIFO: Size 4096` (step 4 passed). WiFi up.

- **Symptom 1 improved, not fixed.** ustreamer (asks 15 fps) got 7-10 fps at start
  (was 0), then decayed to 0 and reopen-looped within ~4 min. `-63` still ~270/s.
  Not caused by uvc tracing (trace off: no change) or CPU load (dla-server stopped,
  fresh ustreamer: 2-7 fps). dwc2 IRQ ~10k/s all on CPU0, CPU0 41 % busy.
- **Symptom 2 reproduced at 532 s:** SMMU `event 0x10` StreamID 6, IOVA `0xfeb2070c`;
  then `dwc2 AHB ERROR, Channel 9` on a CONTROL OUT to the webcam (dev 4,
  `hctsiz 0x600fff7d` = garbage length); SMMU `event 0x13` at `0xfff73f70` (setup DMA);
  `uvcvideo ... probe control : -110` every 6 s; AIC8800 `cmd_mgr_queue cmd timed-out`
  at 626 s; board off Tailscale while nmcli still says connected. Serial console hung
  on `systemctl stop ustreamer`.
- Hardware supports descriptor DMA (`hw_params dma_desc_enable 1`, currently off).

Pass/fail rows 2 and 3 both apply: the bigger FIFO is kept (harmless, gives partial
frames) but the webcam still cannot share dwc2 with the WiFi dongle.

**Decision 2026-09-28: stop here.** Webcam unplugged, new kernel kept, ustreamer stays
disabled. USB webcam on dwc2 is a dead end for the demo; the MIPI camera path is the
camera. Untried levers if this is ever reopened: descriptor DMA, `iommu.passthrough=1`
diagnostic.

## Test result 2: webcam alone (2026-09-28)

Setup: board `eth0` cabled directly to the lab PC `eno1`; the PC shares its eduroam WiFi
over it (NetworkManager profile `board-share`, `ipv4.method shared`, board gets 10.42.0.x).
AIC8800 dongle and FE1.1s hub removed; webcam plugged straight into the board's USB port
(hot-plugged, high speed).

17 min soak, ustreamer 640x480 MJPEG (HW fps coerced 15 -> 20): `online` throughout,
captured_fps 10-11, 0 SMMU events, 0 `AHB ERROR`, 0 uvc `-110`, 1 ustreamer start (no
reopen loop). `frame lost (-63)` total 795 over the run (~0.8/s, was ~270/s with the dongle).

Conclusion: the dongle sharing dwc2 was the co-factor for both the overruns and the wedge.
The FIFO patch alone was not enough; FIFO patch + webcam alone on dwc2 works. The board's
uplink no longer depends on USB, so a wedge would only kill the camera, not the network.

## Rollback

**Board reachable over ssh:**
```
ssh -t terasic@coredla 'sudo sh -c "
  mount /dev/mmcblk0p1 /mnt/b &&
  cp /mnt/b/Image.pre-dwc2fifo /mnt/b/Image &&
  cp /mnt/b/socfpga_agilex5_de25_nano.dtb.pre-dwc2fifo /mnt/b/socfpga_agilex5_de25_nano.dtb &&
  sync; umount /mnt/b"'
```
then power cycle. Expected md5 after restore: `Image` `063418677210af43027827d69a09910f`,
dtb `b77eaeb130c242593c57c745daebbb0f`.

**Kernel does not boot:** on the serial console, press a key during U-Boot autoboot, then
run the same steps as `board/boot.txt` with the backup files:
```
fatload mmc 0:1 0x90000000 golden_top.core.rbf
fpga load 0 0x90000000 ${filesize}
bridge enable
fatload mmc 0:1 ${kernel_addr_r} Image.pre-dwc2fifo
fatload mmc 0:1 ${fdt_addr_r} socfpga_agilex5_de25_nano.dtb.pre-dwc2fifo
setenv fdt_high 0xffffffffffffffff
setenv bootargs "console=ttyS0,115200 root=/dev/mmcblk0p2 rw rootwait mem=768M"
booti ${kernel_addr_r} - ${fdt_addr_r}
```
Once in Linux, do the ssh rollback above so the next boot is also the old kernel.

**Webcam wedged USB (WiFi gone) after the fix:** unplug the webcam, `systemctl disable --now ustreamer`
over serial, power cycle.

## Self-sustaining lab note

The dwc2/SMMU wedge can only be cleared by a power cycle. If the webcam stays in the
setup, a remotely switchable smart plug on the board's supply is the only remote recovery
path that needs nothing but power.

## Follow-up 2026-09-28: 10 fps was ustreamer, not USB

The 10-11 fps above was self-inflicted: `--desired-fps=15` on a camera that only offers
30/25/20 fps. uvcvideo was completing ~30 frames/s with almost no lost packets. The board
override now uses `--desired-fps=30`: 28-30 fps captured, 10 min soak clean. Details in
`docs/DEMO_OPTIMIZATION_PLAN.md` aspect 2.
