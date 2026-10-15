# DE25 Nano Step 2: HPS Linux BSP Build — Manual Replication Guide

Hybrid approach: Terasic's validated boot chain (ATF/U-Boot/kernel/rootfs) +
Altera's coredla devicetree patch (board-agnostic, Agilex5 SoC-level) +
Altera's Yocto layer reused only for its cross-compile SDK (not a full
custom machine port).

Workspace used below: `$TOP=/home/<user>/coredla_work/de25_nano_bringup`

## Prerequisites

```bash
sudo apt install aarch64-linux-gnu-gcc aarch64-linux-gnu-g++ device-tree-compiler \
  u-boot-tools bison flex swig python3 openssl bc qemu-user-static \
  gawk chrpath liblz4-tool   # gawk/chrpath/liblz4-tool needed later for Yocto SDK step
```

## 1. Clone Terasic repos (branch `de25_nano_revA_v1.0`)

```bash
mkdir -p $TOP && cd $TOP
git clone --depth 1 -b de25_nano_revA_v1.0 https://github.com/terasic/arm-trusted-firmware atf
git clone --depth 1 -b de25_nano_revA_v1.0 https://github.com/terasic/u-boot-socfpga u-boot
git clone --depth 1 -b de25_nano_revA_v1.0 https://github.com/terasic/linux-socfpga linux
```1
Note: `linux-socfpga` clone is ~2GB, can take a few minutes — don't let it get
killed by a short timeout.

## 2. Build ARM Trusted Firmware (bl31.bin)

```bash
cd $TOP/atf
export CROSS_COMPILE=aarch64-linux-gnu-
make -j$(nproc) PLAT=agilex5 bl31
# output: build/agilex5/release/bl31.bin
```

## 3. Apply the CoreDLA devicetree patch to the kernel

This patch ships with the FPGA AI Suite toolkit and targets the **base**
Agilex5 SoC dtsi (shared across all Agilex5 boards, not board-specific), so
it applies cleanly to Terasic's fork too:

```bash
cd $TOP/linux
git apply --check /opt/altera/fpga_ai_suite_2025.3.1/dla/hps/ed4/yocto/meta-altera-fpga-coredla/recipes-kernel/linux/files/coredla-agilex5-dts.patch
git apply /opt/altera/fpga_ai_suite_2025.3.1/dla/hps/ed4/yocto/meta-altera-fpga-coredla/recipes-kernel/linux/files/coredla-agilex5-dts.patch
```

**Confirmed bug (2026-07-21), not just a hypothetical gap:** this patch's
`coredla0@20014000` address is wrong for this board's actual
`qsys_top.qsys` layout. Root-caused via Platform Designer's exported address
map (`qsys_topaddress_map.amap`/`.csv`, Export → Address Map in Platform
Designer): `dla.csr_axi` actually sits at offset `0x0002_0000` within the
`subsys_hps.lwhps2fpga` window (range `0x800`, matching the IP's declared
11-bit `C_CSR_AXI_ADDR_WIDTH`), not `0x14000`. Since `lwhps2fpga`'s HPS-side
physical base on this board is `0x20000000` (confirmed by every other DLA
peripheral's address — `stream_controller0@20010000`,
`layout_transform0@20002000`, `msgdma@20000000`/`20001000` all sit in that
window), the correct physical address is **`0x20020000`**, not `0x20014000`.
This board has an existing `subsys_periph.pb_cpu_0_s0` peripheral (Terasic's
Nios V temp/power/fan monitor subsystem, predates the DLA IP integration)
occupying `0x0`–`0x1ffff` in that same window, pushing `dla.csr_axi` up to
`0x20000` instead of the generic patch's assumed `0x14000`. The stock patch
is a generic FPGA AI Suite example that doesn't know about board-specific
peripherals already occupying part of the bridge window.

**Symptom if not fixed:** boot succeeds, `/dev/uio0` binds fine (UIO doesn't
care what's actually at the address), but any real access to the DLA's CSR
registers hits `subsys_periph.pb_cpu_0`'s address space instead — silent,
plausible-looking garbage (some offsets alias, others read distinct-looking
values), not an obvious bus fault. Shows up downstream as
`CoreDlaDevice::CoreDlaDevice: Assertion 'numInstances_ >= 1' failed` in
`dla_benchmark`/`streaming_inference_app` — easy to misdiagnose as a
Platform Designer/qsys hardware bug (an earlier pass at this genuinely did,
see `STEP4_INFERENCE_GUIDE.md`). It is not — it's purely this devicetree
patch's address being stale for this board's specific integration.

**Fix:** after applying the patch, correct the `coredla0` node manually:
```bash
# in $TOP/linux/arch/arm64/boot/dts/intel/socfpga_agilex5.dtsi
# change:
#   coredla0@20014000 { ... reg = <0x20014000 0x00000400>; };
# to:
#   coredla0@20020000 { ... reg = <0x20020000 0x00000800>; };
```
Verify against your own project's exported address map before trusting
these exact values if your qsys layout differs — don't copy `0x20020000`
blindly, re-derive it the same way (Platform Designer → Export Address Map
→ find `dla.csr_axi`'s offset within `lwhps2fpga`, add the bridge's HPS-side
physical base). Rebuild just the dtb (`make dtbs`, seconds) and redeploy —
no kernel/U-Boot/bitstream rebuild needed for this fix.

## 4. Build the kernel

```bash
cd $TOP/linux
export ARCH=arm64
export CROSS_COMPILE=aarch64-linux-gnu-
make defconfig          # this fork's default defconfig already has
                         # CONFIG_ARCH_INTEL_SOCFPGA=y, CONFIG_FPGA_MGR_STRATIX10_SOC=m,
                         # CONFIG_FPGA_BRIDGE=m, CONFIG_UIO=m, CONFIG_UIO_PDRV_GENIRQ=m
make -j$(nproc) Image dtbs modules
# outputs: arch/arm64/boot/Image
#          arch/arm64/boot/dts/intel/socfpga_agilex5_de25_nano.dtb
```

**Pitfall — do NOT use `sudo` for `make modules`/`make Image` etc.** `sudo`
drops `ARCH`/`CROSS_COMPILE` unless you `sudo -E`, which silently makes the
build fall back to host x86_64 and corrupts `modpost` (you'll see undefined
x86-only symbols like `page_offset_base`). It also leaves root-owned files
in the tree that break subsequent non-root builds (`Error during sync of the configuration`). If that happens: `sudo chown -R $USER:$USER .` then
rebuild. Only use `sudo` for the final `modules_install` step (§8), which
just installs into a root-owned rootfs target directory.

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

No manual handoff-blob injection needed here — Terasic's board defconfig
already bakes in pinmux/clock/SDRAM config for the stock DE25 Nano HPS
subsystem. (Only relevant if your Platform Designer `hps_subsys.qsys`
diverges from Terasic's stock HPS config — this project's doesn't, since it
only added the DLA IP on the FPGA-fabric side.)

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

## 7. Build the boot script

```bash
cd $TOP && rm -rf uboot-script && mkdir uboot-script && cd uboot-script
wget https://releases.rocketboards.org/2023.12/qspi/agilex5/agilex5_uboot.txt -O uboot.txt
```

Edit `uboot.txt`'s `if test ${target} = "mmc0"; then ... fi` block to read:

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

(`mmcroot`, `kernel_addr_r`, `fdt_addr_r` are already defined as env
defaults in `include/configs/socfpga_soc64_common.h` — no need to set them.)

The doc's `uboot_script.its` URL 404s (rocketboards reorganized releases).
Use the standard non-FIT script wrapper instead — same result:

```bash
mkimage -A arm64 -O linux -T script -C none -a 0 -e 0 -n "DE25 Nano boot script" -d uboot.txt boot.scr.uimg
```

## 8. Install kernel modules into the rootfs

```bash
cd $TOP/linux
export ARCH=arm64
export CROSS_COMPILE=aarch64-linux-gnu-
sudo make -j$(nproc) modules_install INSTALL_MOD_PATH=$TOP/rootfs_build/rootfs
```

## 9. Assemble the SD card image

```bash
cd $TOP/rootfs_build
wget https://releases.rocketboards.org/release/2020.11/gsrd/tools/make_sdimage_p3.py
```

**Patch required:** this 2020-era script passes `-F 32` to `mkfs.vfat` as a
single argv token (`["-F 32","-I"]`), which modern dosfstools (4.2+)
rejects with `Bad FAT type : 32`. Fix line ~455:

```python
params = ["-F","32","-I"]   # was: ["-F 32","-I"]
```

```bash
mkdir -p fatfs
cp $TOP/u-boot/u-boot.itb fatfs/
cp $TOP/linux/arch/arm64/boot/Image fatfs/
cp $TOP/linux/arch/arm64/boot/dts/intel/socfpga_agilex5_de25_nano.dtb fatfs/
cp $TOP/uboot-script/boot.scr.uimg fatfs/

sudo python3 make_sdimage_p3.py -f \
  -P fatfs/*,num=1,format=fat32,size=500M \
  -P rootfs/*,num=2,format=ext3,size=5000M \
  -s 5500M \
  -n sdcard.img
```

Verify:

```bash
sudo losetup -Pf sdcard.img
LOOPDEV=$(sudo losetup -j sdcard.img | cut -d: -f1)
sudo mount ${LOOPDEV}p1 /mnt   # check u-boot.itb, Image, .dtb, boot.scr.uimg present
sudo umount /mnt
sudo mount ${LOOPDEV}p2 /mnt   # check standard rootfs tree + /lib/modules/<version>
sudo umount /mnt
sudo losetup -d $LOOPDEV
```

Result: `sdcard.img` (5.5G), ready to `dd` to a physical SD card (not done
here — that's a destructive write to a real device, do it deliberately).

---

## Appendix: Yocto Poky SDK (for Step 3's cross-compile toolchain, not the boot image)

Not required to boot the board — only needed later to cross-build the DLA
runtime (`build_hpspackages.sh`/`build_runtime.sh`) with a matching aarch64
sysroot. Reuses Altera's existing `agilex5_mk_a5e065bb32aes1` Yocto machine
purely for its SDK output (same Agilex5 silicon, board-agnostic toolchain) —
no new machine port needed.

```bash
mkdir -p $TOP/yocto_sdk_build
cd /opt/altera/fpga_ai_suite_2025.3.1/dla/hps/ed4/yocto
./run-build.sh -s -b $TOP/yocto_sdk_build agilex5_mk_a5e065bb32aes1
```

**Pitfall 1 — missing HOSTTOOLS.** First run fails with
`bb.fatal: required tools (HOSTTOOLS) appear unavailable in PATH`. On
Ubuntu 24.04 this is `gawk`, `chrpath`, `lz4c`:

```bash
sudo apt-get install -y gawk chrpath liblz4-tool
```

(If it hangs instead of erroring cleanly — check
`build/bitbake-cookerdaemon.log` for the actual traceback; the
`bitbake-layers` client can get stuck endlessly retrying a dead server
instead of surfacing the error. Kill it, `rm build/bitbake.lock build/bitbake.sock`, fix the real cause, retry.)

**Pitfall 2 — AppArmor blocks bitbake's user namespaces.** Ubuntu 24.04
restricts unprivileged `userns` by default
(`kernel.apparmor_restrict_unprivileged_userns=1`), which bitbake needs.
Don't just disable this system-wide — scope it to a dedicated python3
binary so the rest of the system keeps the hardening:

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

bitbake's `bin/bitbake*` scripts are all `#!/usr/bin/env python3`, and
`bitbake-worker`/`bitbake-server` are spawned via `subprocess.Popen([sys.executable, ...])`
— so putting the profiled interpreter first on `PATH` scopes the exemption
to this build's processes only, not every python3 invocation on the box.

**Long-running build note:** first bitbake parse + toolchain build easily
takes hours. If running it manually and want to keep going after closing
the terminal, use `setsid nohup ./run-build.sh ... > log 2>&1 < /dev/null & disown` so it survives the shell exiting.

**Pitfall 3 — host glibc 2.39 breaks `pseudo` (Ubuntu 24.04 host).** Running
`run-build.sh` directly on an Ubuntu 24.04.4 host (glibc 2.39) fails on
every `do_package` task with:

```
got *at() syscall for unknown directory, fd 4
unknown base path for fd 4, path bin
tar: ./usr/bin: Cannot mkdir: Bad address
```

Cause: `pseudo` 1.9.0+git (pinned by this Poky 5.1.4/"styhead" checkout)
can't handle glibc 2.39's `*at()` syscall behavior — the bundled
`glibc238.patch` only covers a separate `strtol` symbol issue, not this.
Not fixable by patching the recipe locally; fix is to build inside an
**Ubuntu 22.04 container** (glibc 2.35) instead of on the host:

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

If a previous host-side attempt already populated `build/tmp`,
`build/cache`, or `build/sstate-cache` before switching to the container,
wipe them first — reusing sstate/tmp built under the host's glibc 2.39
inside the glibc-2.35 container risks ABI-mismatched native tool binaries
and silent/near-instant task failures:

```bash
rm -rf $TOP/yocto_sdk_build/build/{tmp,cache,sstate-cache,bitbake-cookerdaemon.log}
```

**Pitfall 4 — git "dubious ownership" inside the container.** The
bind-mounted `layers/poky` (and `layers/meta-intel-fpga`) are owned by the
host UID, which doesn't match git's expectations inside the container:

```
fatal: detected dubious ownership in repository at '.../layers/poky'
```

Fix (per repo, run as whichever container user will run the build):

```bash
git config --global --add safe.directory $TOP/yocto_sdk_build/layers/poky
git config --global --add safe.directory $TOP/yocto_sdk_build/layers/meta-intel-fpga
```

**Pitfall 5 — missing `en_US.UTF-8` locale kills bitbake silently.** A
fresh `ubuntu:22.04` container has no locales generated. bitbake prints one
warning line (`Please make sure locale 'en_US.UTF-8' is available on your system`) and then **exits 1 with zero further output** — no error, no
traceback. Root cause: without a UTF-8 locale, Python's stdout falls back
to ASCII encoding, and a `UnicodeEncodeError` while bitbake tries to print
anything non-ASCII (including its own exception traceback) kills the
process without printing anything. Fix:

```bash
apt-get install -y locales
locale-gen en_US.UTF-8
export LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8
```

**Pitfall 6 — bitbake refuses to run as root.** Docker containers default
to root, but OE-core's sanity checker hard-fails:

```
ERROR: OE-core's config sanity checker detected a potential misconfiguration.
    Do not use Bitbake as root.
```

Create a non-root user matching the host UID (1000 for `fyp-student`) so
bind-mounted files keep correct ownership on the host side, then re-apply
Pitfall 4 and 5's fixes as that user (git config and locale are per-user):

```bash
useradd -m -u 1000 -s /bin/bash builder
chown -R 1000:1000 $TOP/yocto_sdk_build/layers $TOP/yocto_sdk_build/build
```

**Pitfall 7 — pasting the whole command block into an interactive shell
kills the build after a fraction of a second.** Pasting `su - builder`
followed by several more lines (git config, export, cd, `run-build.sh`) as
one block can cause the terminal to close stdin under the child process
right after bitbake launches — `bitbake-cookerdaemon.log` shows
`buildTargets` starting and the **client disconnecting ~0.3s later**
("No timeout, exiting"), with the build tree (`tmp/`) never even getting
created. Symptom looks identical to Pitfall 5 (fast return, no error) but
the cause is different — check `build/bitbake-cookerdaemon.log` for a
`buildTargets` / `Disconnecting Client` pair with a tiny time gap to tell
them apart. Fix: never paste-and-launch a multi-hour build into an
interactive shell. Launch it detached instead, immune to the terminal:

```bash
docker exec -d -u builder <container> bash -c "
  export LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8
  cd /opt/altera/fpga_ai_suite_2025.3.1/dla/hps/ed4/yocto
  ./run-build.sh -s -b $TOP/yocto_sdk_build agilex5_mk_a5e065bb32aes1 \
    > /home/builder/sdk_build.log 2>&1
"
```

Verify it's actually running (not just that the shell returned):

```bash
docker exec <container> ps aux | grep bitbake-server | grep -v grep
docker exec -u builder <container> tail -f /home/builder/sdk_build.log
```

Once done, the installer lands at `build/tmp/deploy/sdk/poky-*.sh` — copy
it into `runtime/` for `build_hpspackages.sh`/`setup_toolchain.sh` to pick
up.
