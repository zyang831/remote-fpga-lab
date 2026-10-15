# DE25 Nano SD card image — complete build guide

End-to-end replication of the bootable CoreDLA SD card image: BSP sources →
boot chain → rootfs → DLA-specific fixes → image assembly → flash.

Merges `STEP2_BSP_BUILD_GUIDE.md` (original BSP build) and
`SDCARD_IMAGE_CHANGES.md` (the post-bake deltas) into one sequence, in the
order you would actually run it. Both source docs remain for history.

Approach: Terasic's validated boot chain (ATF/U-Boot/kernel/rootfs) +
Altera's coredla devicetree patch (board-agnostic, Agilex5 SoC-level, with a
board-specific address correction) + Altera's Yocto layer reused only for its
cross-compile SDK, not a full custom machine port.

Workspace: `$TOP=/home/<user>/coredla_work/de25_nano_bringup`

## Images produced

| File | Built | State |
|---|---|---|
| `rootfs_build/sdcard.img` | 2026-07-20 | **Stale.** Steps 1–9 only. Boots, but wrong DLA addresses in dtb, no msgdma modules, no UIO fix, no `app/`. Kept for history. |
| `matt/sdcard_v1.img` | 2026-07-29 | **Current.** Full sequence below. Flash this one. |

Both 5500 MiB: FAT32 500M (boot) + ext3 5000M (rootfs, ~35% full).

---

## 0. Prerequisites

```bash
sudo apt install aarch64-linux-gnu-gcc aarch64-linux-gnu-g++ device-tree-compiler \
  u-boot-tools bison flex swig python3 openssl bc qemu-user-static \
  gawk chrpath liblz4-tool   # last three needed for the Yocto SDK (Appendix A)
```

## 1. Clone Terasic repos (branch `de25_nano_revA_v1.0`)

```bash
mkdir -p $TOP && cd $TOP
git clone --depth 1 -b de25_nano_revA_v1.0 https://github.com/terasic/arm-trusted-firmware atf
git clone --depth 1 -b de25_nano_revA_v1.0 https://github.com/terasic/u-boot-socfpga u-boot
git clone --depth 1 -b de25_nano_revA_v1.0 https://github.com/terasic/linux-socfpga linux
```

`linux-socfpga` is ~2 GB — don't let a short timeout kill the clone.

## 2. Build ARM Trusted Firmware (bl31.bin)

```bash
cd $TOP/atf
export CROSS_COMPILE=aarch64-linux-gnu-
make -j$(nproc) PLAT=agilex5 bl31
# output: build/agilex5/release/bl31.bin
```

## 3. Devicetree: apply the CoreDLA patch, then fix the addresses

The patch ships with the FPGA AI Suite toolkit and targets the **base**
Agilex5 SoC dtsi (shared across all Agilex5 boards), so it applies cleanly to
Terasic's fork:

```bash
cd $TOP/linux
git apply --check /opt/altera/fpga_ai_suite_2025.3.1/dla/hps/ed4/yocto/meta-altera-fpga-coredla/recipes-kernel/linux/files/coredla-agilex5-dts.patch
git apply       /opt/altera/fpga_ai_suite_2025.3.1/dla/hps/ed4/yocto/meta-altera-fpga-coredla/recipes-kernel/linux/files/coredla-agilex5-dts.patch
```

### 3a. The addresses in that patch are wrong for this board

Confirmed 2026-07-21, not hypothetical. Root-caused via Platform Designer's
exported address map (`qsys_topaddress_map.amap`/`.csv`, Export → Address Map).

This board has an existing `subsys_periph.pb_cpu_0_s0` peripheral (Terasic's
Nios V temp/power/fan monitor subsystem, predates the DLA IP integration)
occupying `0x0`–`0x1ffff` of the `subsys_hps.lwhps2fpga` window. That pushes
the entire DLA address block up by `0xc000` relative to the generic patch's
assumptions. `lwhps2fpga`'s HPS-side physical base on this board is
`0x20000000`.

Correct **all five** nodes in
`$TOP/linux/arch/arm64/boot/dts/intel/socfpga_agilex5.dtsi`:

| Node | Stock patch | This board |
|---|---|---|
| `msgdma` (DMA0) | `0x20000000` | `0x2000c000` |
| `msgdma` (DMA1) | `0x20001000` | `0x2000d000` |
| `layout_transform0` | `0x20002000` | `0x2000e000` |
| `stream_controller0` | `0x20010000` | `0x2001c000` |
| `coredla0` | `0x20014000`, size `0x400` | `0x20020000`, size `0x800` |

`coredla0` also gets the size corrected — `0x800` matches the IP's declared
11-bit `C_CSR_AXI_ADDR_WIDTH`. Both the node name and its `reg` need
changing:

```
coredla0@20020000 {
        status = "okay";
        compatible = "generic-uio";
        interrupts = <0 49 4>;
        reg = <0x20020000 0x00000800>;
};
```

**Symptom if not fixed:** boot succeeds, `/dev/uio0` binds fine (UIO doesn't
check what's actually at the address), but every CSR access lands in
`subsys_periph.pb_cpu_0`'s space instead — silent, plausible-looking garbage,
no bus fault. Surfaces downstream as
`CoreDlaDevice::CoreDlaDevice: Assertion 'numInstances_ >= 1' failed` in
`dla_benchmark`/`streaming_inference_app`, and is easy to misdiagnose as a
Platform Designer/qsys hardware bug (an earlier pass at this genuinely did —
see `STEP4_INFERENCE_GUIDE.md`). It is not; it is purely a stale devicetree
address.

**Don't copy these values blindly** if your qsys layout differs — re-derive
them the same way (Platform Designer → Export Address Map → find each DLA
component's offset within `lwhps2fpga`, add the bridge's HPS-side physical
base).

Fixing this later needs only `make dtbs` (seconds) plus a redeploy of the
`.dtb` — no kernel, U-Boot or bitstream rebuild.

## 4. Build the kernel

```bash
cd $TOP/linux
export ARCH=arm64
export CROSS_COMPILE=aarch64-linux-gnu-
make defconfig          # this fork's defconfig already has
                        # CONFIG_ARCH_INTEL_SOCFPGA=y, CONFIG_FPGA_MGR_STRATIX10_SOC=m,
                        # CONFIG_FPGA_BRIDGE=m, CONFIG_UIO=m, CONFIG_UIO_PDRV_GENIRQ=m
make -j$(nproc) Image dtbs modules
# outputs: arch/arm64/boot/Image
#          arch/arm64/boot/dts/intel/socfpga_agilex5_de25_nano.dtb
```

**Pitfall — never `sudo` a kernel build step.** `sudo` drops
`ARCH`/`CROSS_COMPILE` unless you use `sudo -E`, silently falling back to
host x86_64 and corrupting `modpost` (undefined x86-only symbols like
`page_offset_base`). It also leaves root-owned files that break later
non-root builds (`Error during sync of the configuration`). Recovery:
`sudo chown -R $USER:$USER .`, then rebuild. `sudo` is only for
`modules_install` (§9), which writes into a root-owned rootfs tree.

## 5. Build U-Boot

```bash
cd $TOP/u-boot
export ARCH=arm64
export CROSS_COMPILE=aarch64-linux-gnu-
make mrproper
make socfpga_agilex5_de25_nano_defconfig
ln -sf ../atf/build/agilex5/release/bl31.bin bl31.bin
make -j$(nproc)
# outputs: u-boot.itb, spl/u-boot-spl-dtb.hex
```

No manual handoff-blob injection: Terasic's board defconfig already bakes in
pinmux/clock/SDRAM for the stock DE25 Nano HPS subsystem. Only relevant if
your Platform Designer `hps_subsys.qsys` diverges from Terasic's stock HPS
config — this project's doesn't, it only added DLA IP on the fabric side.

## 6. Build the rootfs (Ubuntu 22.04 base + qemu-chroot)

```bash
mkdir -p $TOP/rootfs_build && cd $TOP/rootfs_build
wget -c https://cdimage.ubuntu.com/ubuntu-base/releases/22.04.3/release/ubuntu-base-22.04.3-base-arm64.tar.gz
mkdir -p rootfs
sudo tar -xzf ubuntu-base-22.04.3-base-arm64.tar.gz -C rootfs
sudo cp /usr/bin/qemu-aarch64-static rootfs/usr/bin/

# bind-mount for chroot
sudo mount -t proc /proc rootfs/proc
sudo mount -t sysfs /sys rootfs/sys
sudo mount -o bind /dev rootfs/dev
sudo mount -o bind /dev/pts rootfs/dev/pts
sudo cp /etc/resolv.conf rootfs/etc/resolv.conf

sudo chroot rootfs /bin/bash -c "export DEBIAN_FRONTEND=noninteractive; apt update && apt install apt-utils dialog --yes"
sudo chroot rootfs /bin/bash -c "export DEBIAN_FRONTEND=noninteractive; apt install language-pack-en-base sudo ssh net-tools ethtool iputils-ping rsyslog bash-completion vim-tiny kmod --yes"

# user + hostname
sudo chroot rootfs /bin/bash -c "
useradd terasic -m -s /bin/bash
echo terasic:<BOARD_PASSWORD> | chpasswd
addgroup terasic adm
addgroup terasic sudo
echo '127.0.0.1    localhost' >> /etc/hosts
echo 'de25-nano' > /etc/hostname
"

# network
sudo chroot rootfs /bin/bash -c "export DEBIAN_FRONTEND=noninteractive; apt install isc-dhcp-client network-manager --yes"
sudo mkdir -p rootfs/etc/NetworkManager/conf.d
printf '[keyfile]\nunmanaged-devices=*,except:type:wifi,except:type:gsm,except:type:cdma,except:type:ethernet\n' | sudo tee rootfs/etc/NetworkManager/conf.d/allow-ethernet.conf

# if apt gets interrupted mid-run, finish postinst before continuing:
sudo chroot rootfs /bin/bash -c "export DEBIAN_FRONTEND=noninteractive; dpkg --configure -a"

# unmount
sudo umount rootfs/dev/pts rootfs/dev rootfs/sys rootfs/proc
```

User `terasic` is UID 1000 — every later `chown` into the staging tree uses
`1000:1000`, not the host user.

## 7. Build the boot script

```bash
cd $TOP && rm -rf uboot-script && mkdir uboot-script && cd uboot-script
wget https://releases.rocketboards.org/2023.12/qspi/agilex5/agilex5_uboot.txt -O uboot.txt
```

Edit the `mmc0` branch of `uboot.txt` to:

```
if test ${target} = "mmc0"; then
	bridge enable;
	echo "Found kernel in mmc0";
	mmc rescan;
	fatload mmc 0:1 ${kernel_addr_r} Image;
	fatload mmc 0:1 ${fdt_addr_r} socfpga_agilex5_de25_nano.dtb;
	setenv bootargs "console=ttyS0,115200 root=${mmcroot} rw rootwait";
	booti ${kernel_addr_r} - ${fdt_addr_r};
	exit;
fi
```

(`mmcroot`, `kernel_addr_r`, `fdt_addr_r` are env defaults from
`include/configs/socfpga_soc64_common.h` — no need to set them.)

`bridge enable` opens the LWH2F bridges but does **not** configure the FPGA
fabric — see §13.

The vendor doc's `uboot_script.its` URL 404s (rocketboards reorganized
releases). Use the plain script wrapper, same result:

```bash
mkimage -A arm64 -O linux -T script -C none -a 0 -e 0 -n "DE25 Nano boot script" -d uboot.txt boot.scr.uimg
```

## 8. Stage the FAT (boot) partition

```bash
cd $TOP/rootfs_build && mkdir -p fatfs
cp $TOP/u-boot/u-boot.itb fatfs/
cp $TOP/linux/arch/arm64/boot/Image fatfs/
cp $TOP/linux/arch/arm64/boot/dts/intel/socfpga_agilex5_de25_nano.dtb fatfs/
cp $TOP/uboot-script/boot.scr.uimg fatfs/
```

**This copy is the step that got missed the first time.** The dtsi source had
the corrected addresses from §3a, but the built `.dtb` was never re-copied
into `fatfs/`, so the first image shipped the stale one. After any dtsi
change: `make dtbs`, re-copy, re-bake. Verify what you staged:

```bash
dtc -I dtb -O dts fatfs/socfpga_agilex5_de25_nano.dtb 2>/dev/null \
  | grep -E 'coredla0@|msgdma@200|stream_controller0@|layout_transform0@'
# expect: msgdma@2000c000, msgdma@2000d000, layout_transform0@2000e000,
#         stream_controller0@2001c000, coredla0@20020000
```

## 9. Stage the ext3 (rootfs) partition

### 9a. Kernel modules

```bash
cd $TOP/linux
export ARCH=arm64
export CROSS_COMPILE=aarch64-linux-gnu-
sudo make -j$(nproc) modules_install INSTALL_MOD_PATH=$TOP/rootfs_build/rootfs
```

### 9b. msgdma modules (not covered by `modules_install`)

`altera-msgdma.ko` isn't in the default module set, and `msgdma_userio.ko` is
this project's own out-of-tree driver — copy both in by hand and re-run
`depmod`:

```bash
KVER=6.12.11-gd7d192a9ddd9-dirty
MODDIR=$TOP/rootfs_build/rootfs/lib/modules/$KVER/kernel/drivers/dma
sudo cp $TOP/linux/drivers/dma/altera-msgdma.ko    $MODDIR/
sudo cp $TOP/msgdma_userio_module/msgdma_userio.ko $MODDIR/
sudo depmod -b $TOP/rootfs_build/rootfs $KVER
```

Load order matters: `altera-msgdma.ko` before `msgdma_userio.ko`.

### 9c. UIO bind fix

```bash
echo 'options uio_pdrv_genirq of_id=generic-uio' \
  | sudo tee $TOP/rootfs_build/rootfs/etc/modprobe.d/coredla-uio.conf
```

Without it `uio_pdrv_genirq` never binds the `compatible = "generic-uio"` DLA
nodes and the runtime dies at `Failed to open - /dev/uio0`.

### 9d. `app/` runtime payload (~513 MB)

Built by `STEP3_RUNTIME_BUILD_GUIDE.md` (§§5–7); staged into
`rootfs_build/rootfs/home/terasic/app`, which is what lands in the image:

- `dla_benchmark`, `streaming_inference_app`, `image_streaming_app`
- `libcoreDlaRuntimePlugin.so`, `libcoreDLAHeteroPlugin.so`,
  `libhps_platform_mmd.so`, `libdla_compiled_result.so`,
  `libformat_reader.so`, OpenVINO 2024.6 + OpenCV 4.8 libs, `plugins.xml`
- `sdklibs/` — the Yocto SDK's own loader + glibc 2.38 libs, because the
  board rootfs is Ubuntu 22.04 (glibc 2.35) while the cross-built binaries
  need `GLIBC_2.38`/`GLIBCXX_3.4.32`. `LD_LIBRARY_PATH` cannot fix this: the
  ELF interpreter path is baked in at link time and the kernel invokes that
  loader before libc is resolved. Every binary runs as
  `./sdklibs/ld-linux-aarch64.so.1 --library-path ./sdklibs:. ./dla_benchmark`
  — hence the patched `run_inference_stream.sh`, `run_image_stream.sh` and
  the `dla_benchmark.sh` wrapper.
- `resnet-50-tf/` — compiled models `resnet50_nosoftmax.bin`,
  `resnet50_softmax.bin` (147 MB each), `AGX5_Small_*.arch`, sample images

Everything under `app/` must end up `1000:1000` (`sudo chown -R 1000:1000`),
otherwise it's root-owned on the board and `terasic` can't run it.

## 10. Patch the image assembly script

```bash
cd $TOP/rootfs_build
wget https://releases.rocketboards.org/release/2020.11/gsrd/tools/make_sdimage_p3.py
```

This 2020-era script passes `-F 32` to `mkfs.vfat` as a single argv token,
which dosfstools 4.2+ rejects with `Bad FAT type : 32`. Fix line ~455:

```python
params = ["-F","32","-I"]   # was: ["-F 32","-I"]
```

## 11. Assemble the image

```bash
cd $TOP/rootfs_build
sudo python3 make_sdimage_p3.py -f \
  -P fatfs/*,num=1,format=fat32,size=500M \
  -P rootfs/*,num=2,format=ext3,size=5000M \
  -s 5500M \
  -n $TOP/matt/sdcard_v2.img
```

(Output path is deliberately not `rootfs_build/sdcard.img` — that name is the
stale 2026-07-20 baseline. `matt/sdcard_v1.img` is the current good image;
bump the version rather than overwriting a known-good one.)

## 12. Verify before flashing

```bash
IMG=$TOP/matt/sdcard_v2.img
sudo losetup -Pf $IMG; LOOP=$(sudo losetup -j $IMG | cut -d: -f1)

sudo mount -o ro ${LOOP}p1 /mnt
ls /mnt                                   # Image, u-boot.itb, boot.scr.uimg, .dtb
dtc -I dtb -O dts /mnt/socfpga_agilex5_de25_nano.dtb 2>/dev/null \
  | grep -E 'coredla0@|msgdma@200'        # expect the §8 addresses
sudo umount /mnt

sudo mount -o ro ${LOOP}p2 /mnt
cat /mnt/etc/modprobe.d/coredla-uio.conf
ls /mnt/lib/modules/*/kernel/drivers/dma/ | grep -i msgdma
ls /mnt/home/terasic/app | head
sudo umount /mnt

sudo losetup -d $LOOP
```

## 13. Flash

Destructive. Identify the SD card device with `lsblk` before and after
inserting the card — writing to the wrong `/dev/sdX` destroys that disk.

```bash
lsblk
sudo dd if=$TOP/matt/sdcard_v1.img of=/dev/sdX bs=4M status=progress conv=fsync
sync
```

---

## What the image still does NOT contain

Verified absent from `matt/sdcard_v1.img`:

**FPGA configuration.** No `.rbf` in `/lib/firmware`, no bitstream in the FAT
partition. The boot script's `bridge enable` opens the bridges, but nothing
configures the fabric, so on a cold boot any MMIO to `0x2000_0000+` aborts.
If `altera-msgdma` autoloads in that state it reads its CSR from the IRQ
handler during probe: `msgdma_irq_handler` → synchronous external abort →
kernel panic.

`boot_setup/` solves this (reconfigure via fpga_manager overlay, wait for
`state == operating`, only then `modprobe`) but was written after this image
was baked and never staged. To include it in the next bake:

```bash
R=$TOP/rootfs_build/rootfs
sudo cp $TOP/boot_setup/coredla-fpga-up.sh   $R/usr/local/sbin/
sudo cp $TOP/boot_setup/coredla-fpga.service $R/etc/systemd/system/
sudo ln -sf ../coredla-fpga.service \
  $R/etc/systemd/system/multi-user.target.wants/coredla-fpga.service
sudo cp <your>.core.rbf $R/lib/firmware/
```

Known mismatch to fix first: `coredla-fpga-up.sh` writes `my_overlay.dtb` to
the overlay path, but the repo ships `fpga_full.dtbo`. Reconcile the names or
the service fails on a fresh flash.

**WiFi driver** — AIC8800D80, see `STEP5_WIFI_DONGLE_GUIDE.md`. No `aic8800`
module in `/lib/modules`.

**Mender / Tailscale** — see `MENDER_OTA_TAILSCALE_GUIDE.md`.

## Drift warning

Work done directly on the live board over ssh never comes back to
`rootfs_build/rootfs`. Reflashing reverts anything applied only on-target —
`app/` updates, patched scripts, network config. Restage into the tree first,
or capture what the board has before you flash.

---

## Appendix A: Yocto Poky SDK (cross-compile toolchain)

Not needed to boot the board — needed to cross-build the DLA runtime
(`build_hpspackages.sh`/`build_runtime.sh`) against a matching aarch64
sysroot, which is what §9d's `app/` and `sdklibs/` come from. Reuses Altera's
existing `agilex5_mk_a5e065bb32aes1` Yocto machine purely for its SDK output
(same Agilex5 silicon, board-agnostic toolchain) — no machine port needed.

```bash
mkdir -p $TOP/yocto_sdk_build
cd /opt/altera/fpga_ai_suite_2025.3.1/dla/hps/ed4/yocto
./run-build.sh -s -b $TOP/yocto_sdk_build agilex5_mk_a5e065bb32aes1
```

**Pitfall 1 — missing HOSTTOOLS.** First run fails with
`bb.fatal: required tools (HOSTTOOLS) appear unavailable in PATH`. On Ubuntu
24.04 that's `gawk`, `chrpath`, `lz4c`:

```bash
sudo apt-get install -y gawk chrpath liblz4-tool
```

If it hangs instead of erroring cleanly, check
`build/bitbake-cookerdaemon.log` for the real traceback — `bitbake-layers`
can get stuck retrying a dead server instead of surfacing the error. Kill it,
`rm build/bitbake.lock build/bitbake.sock`, fix the cause, retry.

**Pitfall 2 — AppArmor blocks bitbake's user namespaces.** Ubuntu 24.04 sets
`kernel.apparmor_restrict_unprivileged_userns=1`, which bitbake needs. Scope
the exemption to a dedicated python3 instead of disabling it system-wide:

```bash
mkdir -p $TOP/yocto_sdk_build/priv-python3
cp $(readlink -f $(which python3)) $TOP/yocto_sdk_build/priv-python3/python3.12
ln -sf python3.12 $TOP/yocto_sdk_build/priv-python3/python3
chmod +x $TOP/yocto_sdk_build/priv-python3/python3.12
```

```
# /etc/apparmor.d/bitbake-priv-python3
abi <abi/4.0>,
include <tunables/global>

profile bitbake-priv-python3 <TOP>/yocto_sdk_build/priv-python3/python3.12 flags=(unconfined) {
  userns,
}
```

```bash
sudo apparmor_parser -r /etc/apparmor.d/bitbake-priv-python3
export PATH="$TOP/yocto_sdk_build/priv-python3:$PATH"   # before sourcing oe-init-build-env
```

bitbake's `bin/bitbake*` scripts are `#!/usr/bin/env python3`, and
`bitbake-worker`/`bitbake-server` spawn via
`subprocess.Popen([sys.executable, ...])` — so the profiled interpreter first
on `PATH` scopes the exemption to this build only.

**Pitfall 3 — host glibc 2.39 breaks `pseudo`.** On Ubuntu 24.04 every
`do_package` task fails:

```
got *at() syscall for unknown directory, fd 4
unknown base path for fd 4, path bin
tar: ./usr/bin: Cannot mkdir: Bad address
```

`pseudo` 1.9.0+git (pinned by this Poky 5.1.4/"styhead" checkout) can't
handle glibc 2.39's `*at()` behavior; the bundled `glibc238.patch` only
covers a separate `strtol` issue. Not fixable by patching the recipe — build
inside an **Ubuntu 22.04 container** (glibc 2.35):

```bash
docker run -it --rm \
  -v /opt/altera:/opt/altera:ro \
  -v $TOP:/home/<user>/coredla_work \
  ubuntu:22.04 bash
# inside container:
apt-get update && apt-get install -y gawk wget git diffstat unzip texinfo \
  gcc build-essential chrpath socat cpio python3 python3-pip python3-pexpect \
  xz-utils debianutils iputils-ping python3-git python3-jinja2 python3-subunit \
  zstd liblz4-tool file locales
```

If a host-side attempt already populated `build/tmp`, `build/cache` or
`build/sstate-cache`, wipe them before switching — reusing glibc-2.39 sstate
inside the 2.35 container risks ABI-mismatched native binaries and silent
task failures:

```bash
rm -rf $TOP/yocto_sdk_build/build/{tmp,cache,sstate-cache,bitbake-cookerdaemon.log}
```

**Pitfall 4 — git "dubious ownership" in the container.** Bind-mounted
`layers/poky` and `layers/meta-intel-fpga` are host-UID-owned:

```
fatal: detected dubious ownership in repository at '.../layers/poky'
```

Fix, as whichever container user runs the build:

```bash
git config --global --add safe.directory $TOP/yocto_sdk_build/layers/poky
git config --global --add safe.directory $TOP/yocto_sdk_build/layers/meta-intel-fpga
```

**Pitfall 5 — missing `en_US.UTF-8` locale kills bitbake silently.** A fresh
`ubuntu:22.04` has no locales generated. bitbake prints one warning
(`Please make sure locale 'en_US.UTF-8' is available on your system`) then
exits 1 with no further output: without a UTF-8 locale Python's stdout falls
back to ASCII, and a `UnicodeEncodeError` while printing anything non-ASCII
(including its own traceback) kills the process silently.

```bash
apt-get install -y locales
locale-gen en_US.UTF-8
export LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8
```

**Pitfall 6 — bitbake refuses to run as root.**

```
ERROR: OE-core's config sanity checker detected a potential misconfiguration.
    Do not use Bitbake as root.
```

Create a non-root user matching the host UID so bind-mounted files keep
correct host-side ownership, then re-apply Pitfalls 4 and 5 as that user
(git config and locale are per-user):

```bash
useradd -m -u 1000 -s /bin/bash builder
chown -R 1000:1000 $TOP/yocto_sdk_build/layers $TOP/yocto_sdk_build/build
```

**Pitfall 7 — pasting the command block into an interactive shell kills the
build instantly.** Pasting `su - builder` plus several more lines as one
block can close stdin under the child right after bitbake launches:
`bitbake-cookerdaemon.log` shows `buildTargets` then the client disconnecting
~0.3 s later ("No timeout, exiting"), with `tmp/` never created. Looks
identical to Pitfall 5 — tell them apart by that `buildTargets` /
`Disconnecting Client` pair. Launch detached instead:

```bash
docker exec -d -u builder <container> bash -c "
  export LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8
  cd /opt/altera/fpga_ai_suite_2025.3.1/dla/hps/ed4/yocto
  ./run-build.sh -s -b $TOP/yocto_sdk_build agilex5_mk_a5e065bb32aes1 \
    > /home/builder/sdk_build.log 2>&1
"
```

Verify it's actually running, not just that the shell returned:

```bash
docker exec <container> ps aux | grep bitbake-server | grep -v grep
docker exec -u builder <container> tail -f /home/builder/sdk_build.log
```

First parse + toolchain build takes hours. Outside docker, keep it alive
across terminal exit with
`setsid nohup ./run-build.sh ... > log 2>&1 < /dev/null & disown`.

Installer lands at `build/tmp/deploy/sdk/poky-*.sh` — copy it into `runtime/`
for `build_hpspackages.sh`/`setup_toolchain.sh` to pick up.
