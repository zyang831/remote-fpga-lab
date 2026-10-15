# DE25 Nano SD card image — changes on top of the Step 2 baseline

`STEP2_BSP_BUILD_GUIDE.md` §9 documents how the *first* image was assembled.
It does not document what was changed afterwards. This file covers that
delta.

## Which image is which

| File | Built | State |
|---|---|---|
| `rootfs_build/sdcard.img` | 2026-07-20 | **Stale baseline.** Step 2 §9 output. Wrong DLA addresses in dtb, no msgdma modules, no UIO modprobe fix, no `app/`. Boots, but no working DLA. |
| `matt/sdcard_v1.img` | 2026-07-29 20:54 | **Current.** Baseline + the four deltas below. Originally written as `matt/sdcard.img`, renamed since. |

Both are 5500 MiB, same partition layout (FAT32 500M + ext3 5000M, ext3
partition 35% full). Nothing in the repo says which one is canonical —
`matt/sdcard_v1.img` is.

## Delta 1 — dtb: all five DLA nodes moved +0xc000

Step 2 §3 documents only `coredla0` moving `0x20014000` → `0x20020000`. The
real fix shifted **every** DLA node in `socfpga_agilex5.dtsi` by the same
`0xc000`, because the whole DLA address block sits above this board's
existing `subsys_periph.pb_cpu_0_s0` peripheral in the `lwhps2fpga` window:

| Node | Stock patch | This board |
|---|---|---|
| `msgdma` (DMA0) | `0x20000000` | `0x2000c000` |
| `msgdma` (DMA1) | `0x20001000` | `0x2000d000` |
| `layout_transform0` | `0x20002000` | `0x2000e000` |
| `stream_controller0` | `0x20010000` | `0x2001c000` |
| `coredla0` | `0x20014000` (`0x400`) | `0x20020000` (`0x800`) |

The kernel source tree already had all five correct before this session —
the fix had simply never been propagated into the image. `make dtbs` +
copy into `rootfs_build/fatfs/` was the whole change.

## Delta 2 — UIO bind fix

`/etc/modprobe.d/coredla-uio.conf`:

```
options uio_pdrv_genirq of_id=generic-uio
```

Without it `uio_pdrv_genirq` never binds the `compatible = "generic-uio"`
DLA nodes, and the runtime fails at `Failed to open - /dev/uio0`.
Referenced in `STEP4_INFERENCE_GUIDE.md:191-193` as something that "should
persist"; this is where it got persisted.

## Delta 3 — msgdma kernel modules staged

Neither module is built by the plain `make modules` of Step 2 §4 into the
right place, so both were copied in by hand and `depmod` re-run:

```bash
KVER=6.12.11-gd7d192a9ddd9-dirty
MODDIR=rootfs_build/rootfs/lib/modules/$KVER/kernel/drivers/dma
sudo cp linux/drivers/dma/altera-msgdma.ko            $MODDIR/
sudo cp msgdma_userio_module/msgdma_userio.ko         $MODDIR/
sudo depmod -b rootfs_build/rootfs $KVER
```

Load order matters: `altera-msgdma.ko` before `msgdma_userio.ko`.

## Delta 4 — `app/` runtime payload (513 MB)

`/home/terasic/app`, staged from the Step 3 build outputs:

- `dla_benchmark`, `streaming_inference_app`, `image_streaming_app`
- `libcoreDlaRuntimePlugin.so`, `libcoreDLAHeteroPlugin.so`,
  `libhps_platform_mmd.so`, OpenVINO 2024.6 + OpenCV 4.8 shared libs,
  `plugins.xml`
- `sdklibs/` — glibc 2.39 loader + libs from the Yocto SDK sysroot, the
  workaround for the board rootfs (Ubuntu 22.04, glibc 2.35) being older
  than what the SDK links against. Binaries run via
  `./sdklibs/ld-linux-aarch64.so.1 --library-path ./sdklibs:. ./dla_benchmark`
  (see `STEP3_RUNTIME_BUILD_GUIDE.md` §§ on `sdklibs`).
- `resnet-50-tf/` — compiled models `resnet50_nosoftmax.bin`,
  `resnet50_softmax.bin` (147 MB each), `AGX5_Small_*.arch`, sample images

## Rebuilding the image from the staging tree

The staging tree (`rootfs_build/fatfs`, `rootfs_build/rootfs`) already
contains all four deltas, so a rebake is just Step 2 §9 with a new output
path:

```bash
cd rootfs_build
sudo python3 make_sdimage_p3.py -f \
  -P fatfs/*,num=1,format=fat32,size=500M \
  -P rootfs/*,num=2,format=ext3,size=5000M \
  -s 5500M \
  -n ../matt/sdcard_v2.img
```

Verify before flashing:

```bash
IMG=matt/sdcard_v2.img
sudo losetup -Pf $IMG; LOOP=$(sudo losetup -j $IMG | cut -d: -f1)
sudo mount -o ro ${LOOP}p1 /mnt   # Image, u-boot.itb, boot.scr.uimg, .dtb
dtc -I dtb -O dts /mnt/socfpga_agilex5_de25_nano.dtb | grep -E 'coredla0@|msgdma@200'
sudo umount /mnt
sudo mount -o ro ${LOOP}p2 /mnt   # modprobe.d/coredla-uio.conf, app/, *msgdma*.ko
sudo umount /mnt; sudo losetup -d $LOOP
```

Flash (destructive — confirm the device with `lsblk` before and after
inserting the card; writing to the wrong `/dev/sdX` destroys that disk):

```bash
sudo dd if=matt/sdcard_v1.img of=/dev/sdX bs=4M status=progress conv=fsync
sync
```

## Still NOT in the image

Verified absent from `matt/sdcard_v1.img`:

- **FPGA configuration.** No `.rbf` in `/lib/firmware`, no bitstream in the
  FAT partition. The boot script's `bridge enable` opens the bridges but
  nothing configures the fabric, so on a cold boot MMIO to `0x2000_0000+`
  aborts. `boot_setup/coredla-fpga.service` + `coredla-fpga-up.sh` +
  `fpga_full.dtbo` exist in the repo to solve exactly this (reconfig via
  fpga_manager overlay, wait for `state == operating`, only then modprobe)
  but were written after this image was baked and were never installed into
  the staging rootfs. Consequence if you autoload `altera-msgdma` without
  them: `msgdma_irq_handler` reads its CSR at probe → synchronous external
  abort → kernel panic.
  To include them next rebake:

  ```bash
  R=rootfs_build/rootfs
  sudo cp boot_setup/coredla-fpga-up.sh  $R/usr/local/sbin/
  sudo cp boot_setup/coredla-fpga.service $R/etc/systemd/system/
  sudo ln -sf ../coredla-fpga.service \
    $R/etc/systemd/system/multi-user.target.wants/coredla-fpga.service
  sudo cp <your>.core.rbf $R/lib/firmware/
  ```

  Note `coredla-fpga-up.sh` writes `my_overlay.dtb` to the overlay path —
  make sure that name matches whatever dtbo you actually ship.
- **WiFi driver** (`STEP5_WIFI_DONGLE_GUIDE.md`, AIC8800D80). No `aic8800`
  module in `/lib/modules`.
- **Mender / Tailscale** (`MENDER_OTA_TAILSCALE_GUIDE.md`).

## Drift warning

Work done directly on the live board over ssh does not come back to
`rootfs_build/rootfs`. Reflashing from either image reverts anything that
was only ever applied on-target. Before flashing, check whether the board
has state (`app/` updates, patched scripts, network config) that needs
restaging first.
