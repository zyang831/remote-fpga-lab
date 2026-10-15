# Yocto Poky SDK Build — End-to-End Guide

Source: consolidated from `STEP2_BSP_BUILD_GUIDE.md` Appendix, this device
(host Ubuntu 24.04.4, kernel 6.17.0-1032-oem).

## Goal

Cross-compile toolchain (`poky-*-toolchain-5.1.4.sh`) for
`agilex5_mk_a5e065bb32aes1`, needed by
`build_hpspackages.sh`/`build_runtime.sh -hps_platform`. Reuses Altera's
Yocto layer purely for SDK output — no full machine port.

## Prerequisites

```bash
sudo apt-get install -y gawk chrpath liblz4-tool
```

## Step 1 — AppArmor fix (do this first, before any bitbake invocation)

Ubuntu 24.04 sets `kernel.apparmor_restrict_unprivileged_userns=1`, blocks
bitbake's userns. Don't disable system-wide — scope exemption to a dedicated
python3 copy:

```bash
TOP=/home/<user>/coredla_work/de25_nano_bringup
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
export PATH="$TOP/yocto_sdk_build/priv-python3:$PATH"   # before oe-init-build-env
```

## Step 2 — build inside Ubuntu 22.04 container (glibc mismatch)

Host glibc 2.39 breaks `pseudo` 1.9.0+git's `*at()` syscall handling (`got
*at() syscall for unknown directory`/`Cannot mkdir: Bad address` on every
`do_package`). Fix: build inside glibc 2.35 container.

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

If host-side attempt already populated `build/tmp`/`build/cache`/
`build/sstate-cache` before switching to container, wipe first (ABI mismatch
risk):

```bash
rm -rf $TOP/yocto_sdk_build/build/{tmp,cache,sstate-cache,bitbake-cookerdaemon.log}
```

## Step 3 — non-root build user (bitbake refuses root)

```bash
useradd -m -u 1000 -s /bin/bash builder
chown -R 1000:1000 $TOP/yocto_sdk_build/layers $TOP/yocto_sdk_build/build
```

## Step 4 — per-user fixes, as `builder`

Git dubious-ownership:

```bash
git config --global --add safe.directory $TOP/yocto_sdk_build/layers/poky
git config --global --add safe.directory $TOP/yocto_sdk_build/layers/meta-intel-fpga
```

Locale (missing UTF-8 kills bitbake silently — exit 1, zero output, no
traceback):

```bash
apt-get install -y locales
locale-gen en_US.UTF-8
export LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8
```

## Step 5 — launch build detached

Never paste a multi-line block into an interactive shell — kills the build
~0.3s in, terminal closes stdin under bitbake.

```bash
docker exec -d -u builder <container> bash -c "
  export LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8
  cd /opt/altera/fpga_ai_suite_2025.3.1/dla/hps/ed4/yocto
  ./run-build.sh -s -b $TOP/yocto_sdk_build agilex5_mk_a5e065bb32aes1 \
    > /home/builder/sdk_build.log 2>&1
"
```

Verify actually running (not just shell return):

```bash
docker exec <container> ps aux | grep bitbake-server | grep -v grep
docker exec -u builder <container> tail -f /home/builder/sdk_build.log
```

Takes hours (first parse + full toolchain build).

## Step 6 — confirm success

```bash
ls -la $TOP/yocto_sdk_build/build/tmp/deploy/sdk/*.sh
```

Presence of
`poky-glibc-x86_64-coredla-image-armv8-2a-agilex5_mk_a5e065bb32aes1-toolchain-5.1.4.sh`
(~200MB) = proof `do_populate_sdk` succeeded, every recipe including
`nativesdk-pseudo` passed `do_package`.

## Step 7 — install SDK, hand off to runtime build

Let `build_hpspackages.sh` invoke `scripts/hps/setup_toolchain.sh` itself —
don't run `poky-*.sh -d embedded_arm_sdk` manually, it skips generating
`embedded_arm_sdk/cmake/embedded.arm.cmake` which
`build_hpspackages.sh`/`build_runtime.sh` hard-require via `TOOLCHAIN_FILE`.
If already done manually and missing that file:

```bash
runtime/scripts/hps/create_toolchain_file.sh embedded_arm_sdk
```

## Gotchas not in the pitfall list above (from Step 3 cross-build)

- Bash tool / any non-persistent shell: `source` env script and run build
  must be same command (`&&` chain or wrapper script) — separate calls lose
  exported vars.
- `COREDLA_ROOT` (from
  `/opt/altera/fpga_ai_suite_2025.3.1/dla/bin/init_env.sh`) requires
  `INTEL_OPENVINO_DIR` (from `/opt/intel/openvino_2024/setupvars.sh`)
  sourced first — missing it fails silently on `cp: cannot stat
  '/thirdparty/pugixml'`, cascades to confusing gflags CMake error.
- cmake: host 3.28.3 too old for `CMakePresets.json` (needs ≥3.31), but
  ≥4.0 breaks `hps_platform/CMakeLists.txt`'s old `cmake_minimum_required`
  pins. Sweet spot 3.31.x via venv:
  `python3 -m venv runtime/.cmake_venv && .cmake_venv/bin/pip install cmake==3.31.10`,
  prepend to `PATH`.
- `scons` needed for ARM ComputeLibrary in OpenVINO cross-build:
  `sudo apt-get install -y scons`.

Root doc: `STEP2_BSP_BUILD_GUIDE.md` — pitfalls 1–7 in Appendix section,
exact line refs there if diffing against another device's run.
