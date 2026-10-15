# DE25 Nano Step 3: CoreDLA Runtime Cross-Build + Deploy — Manual Replication Guide

Cross-builds the userspace CoreDLA runtime (`dla_benchmark`, plugins,
streaming demo apps) for aarch64 using a Yocto Poky SDK toolchain, then
deploys it onto the board's manually-built rootfs (see
`STEP2_BSP_BUILD_GUIDE.md` — this is *not* a Yocto machine image, so none of
this happens automatically via a `.wic`/`create_hps_image.sh` flow).

Workspace: `$TOP=/home/<user>/coredla_work`, FPGA AI Suite install at
`/opt/altera/fpga_ai_suite_2025.3.1`, host OpenVINO 2024.6.0 at
`/opt/intel/openvino_2024`.

## Prerequisites

```bash
sudo apt-get install -y scons          # needed by OpenVINO's ARM ComputeLibrary cross-build
```

Host `cmake` (3.28.3 on Ubuntu 24.04) is too old for `runtime/CMakePresets.json`
(`"version": 10`, needs cmake >=3.31) but cmake >=4.0 dropped support for the
old `cmake_minimum_required` pins still used by
`coredla_device/mmd/hps_platform/CMakeLists.txt` (needs <4.0). Pin **3.31.x**
in an isolated venv rather than touching the system cmake:

```bash
python3 -m venv $TOP/runtime/.cmake_venv
$TOP/runtime/.cmake_venv/bin/pip install cmake==3.31.10
```

## 1. Build the Yocto Poky SDK (cross-compile toolchain)

Not a boot image — reuses Altera's `agilex5_mk_a5e065bb32aes1` Yocto machine
purely for its SDK output (matching Agilex5 silicon, board-agnostic
toolchain). Full pitfall chain (host glibc breaking `pseudo`, AppArmor
userns, dubious ownership, locale, root check, paste-kills-build) is in
`STEP2_BSP_BUILD_GUIDE.md`'s Yocto Poky SDK appendix — follow that section
end to end. Output lands at:

```
$TOP/de25_nano_bringup/yocto_sdk_build/build/tmp/deploy/sdk/poky-*-toolchain-5.1.4.sh
```

## 2. Install the SDK toolchain

**Do not** run the `poky-*.sh` installer directly with `-d`. Let
`build_hpspackages.sh` invoke `runtime/scripts/hps/setup_toolchain.sh`
itself (see step 3) — it installs the SDK *and* generates the required
`embedded_arm_sdk/cmake/embedded.arm.cmake` toolchain file in one step. If
you do run the installer manually (or `embedded_arm_sdk` already exists
without a `cmake/` subdir), regenerate the toolchain file:

```bash
cd $TOP/runtime
./scripts/hps/create_toolchain_file.sh embedded_arm_sdk   # safe to rerun, cheap
```

Symptom if skipped: CMake fails deep into the first sub-package build with
`Could not find toolchain file: .../embedded_arm_sdk/cmake/embedded.arm.cmake`.

## 3. Source the environment (every single build invocation)

`build_hpspackages.sh`/`build_runtime.sh -hps_platform` need `COREDLA_ROOT`
(from CoreDLA's `init_env.sh`), which in turn needs `INTEL_OPENVINO_DIR`
(host OpenVINO, sourced first):

```bash
source /opt/intel/openvino_2024/setupvars.sh
source /opt/altera/fpga_ai_suite_2025.3.1/dla/bin/init_env.sh
```

**Pitfall — shell state does not persist between separate tool/terminal
invocations, only cwd does (if you're driving this via an agent/script
runner).** Sourcing env vars in one call and running the build in the next
silently loses them. Symptom: `build_hpspackages.sh -s` fails on
`cp: cannot stat '/thirdparty/pugixml'` (empty `$COREDLA_ROOT` prefix),
which then cascades into a confusing CMake toolchain-file error on the next
package. Fix: bundle sourcing + build into one script and invoke that script
as a single command — see `.run_hpspackages.sh` / `.run_build_runtime.sh`
pattern below. Also: piping a `source` through `| tail` (or any pipe) runs
it in a subshell — the exports don't escape. Don't pipe a sourcing command.

## 4. Build HPS packages (OpenCV, OpenVINO, gflags, protobuf, boost, etc.)

```bash
cat > $TOP/runtime/.run_hpspackages.sh <<'EOF'
#!/bin/bash
source /opt/intel/openvino_2024/setupvars.sh
source /opt/altera/fpga_ai_suite_2025.3.1/dla/bin/init_env.sh
cd /home/<user>/coredla_work/runtime
exec ./build_hpspackages.sh -sb
EOF
chmod +x $TOP/runtime/.run_hpspackages.sh
$TOP/runtime/.run_hpspackages.sh > $TOP/de25_nano_bringup/hpspackages_build.log 2>&1
```

Long-running (~hours for OpenVINO). Watch for:

- **Missing `scons`** — OpenVINO configure fails with
  `Could not find SCONS using the following names: scons` while configuring
  ARM ComputeLibrary. Install it (Prerequisites) and rerun; already-built
  packages (opencv, gflags) are skipped on retry.

Output staged to `runtime/hps_packages/armcpu_package/`.

## 5. Build the runtime for the HPS platform

```bash
cat > $TOP/runtime/.run_build_runtime.sh <<'EOF'
#!/bin/bash
source /opt/intel/openvino_2024/setupvars.sh
source /opt/altera/fpga_ai_suite_2025.3.1/dla/bin/init_env.sh
export PATH=/home/<user>/coredla_work/runtime/.cmake_venv/bin:$PATH
cd /home/<user>/coredla_work/runtime
exec ./build_runtime.sh -hps_platform -hps_machine=agilex5_mk_a5e065bb32aes1
EOF
chmod +x $TOP/runtime/.run_build_runtime.sh
$TOP/runtime/.run_build_runtime.sh > $TOP/de25_nano_bringup/build_runtime.log 2>&1
```

Builds `dla_benchmark` + `libcoreDlaRuntimePlugin.so` /
`libcoreDLAHeteroPlugin.so` / `libhps_platform_mmd.so` / etc. Note:
`dla_aot_splitter` is deliberately **not** built here (host-only tool,
excluded via `if (NOT HPS_PLATFORM)` in `runtime/CMakeLists.txt`) — its
absence is expected, not a bug.

Output at `runtime/build_Release/`.

## 6. Stage the app directory

There's no `create_hps_image.sh`/`.wic` flow for this manual rootfs, but its
rsync file list (lines ~423-466 of `runtime/create_hps_image.sh`) is the
proven set of files to deploy — reuse it, just re-rooted. Vendor default is
`/home/root/app` (Yocto's default user); this rootfs's actual user is
`terasic` (UID 1000, see `STEP2_BSP_BUILD_GUIDE.md`), so target
`/home/terasic/app` instead.

```bash
RUNTIME_DIR=$TOP/runtime
RUNTIME_BUILD_DIR=$RUNTIME_DIR/build_Release
HPSPACKAGES_BUILD_DIR=$RUNTIME_DIR/hps_packages
COREDLA_ROOT=/opt/altera/fpga_ai_suite_2025.3.1/dla
ARM_ARCH=aarch64
APP_DIR=$TOP/de25_nano_bringup/rootfs_build/rootfs/home/terasic/app

sudo mkdir -p "$APP_DIR" "$APP_DIR/hetero_plugin" "$APP_DIR/compiled_result"
cd "$APP_DIR"

sudo rsync -a $RUNTIME_BUILD_DIR/dla_benchmark/dla_benchmark .
sudo rsync -a $HPSPACKAGES_BUILD_DIR/openvino/bin/$ARM_ARCH/Release/*.so* .
sudo rsync -a $RUNTIME_BUILD_DIR/common/format_reader/libformat_reader.so .
sudo rsync -a $RUNTIME_BUILD_DIR/coredla_device/mmd/hps_platform/libhps_platform_mmd.so .
sudo rsync -a $RUNTIME_BUILD_DIR/hetero_plugin/libcoreDLAHeteroPlugin.so . ./hetero_plugin/
sudo rsync -a $RUNTIME_BUILD_DIR/compiled_result/libdla_compiled_result.so . ./compiled_result/
sudo rsync -a $RUNTIME_BUILD_DIR/libcoreDlaRuntimePlugin.so .
sudo rsync -a $RUNTIME_BUILD_DIR/plugins.xml .
sudo rsync -a --exclude libopencv_highgui.so --exclude libopencv_core.so \
              --exclude libopencv_imgcodecs.so --exclude libopencv_imgproc.so \
              --exclude libopencv_videoio.so \
              $HPSPACKAGES_BUILD_DIR/armcpu_package/opencv/lib/*.so* .
sudo rsync -a $RUNTIME_BUILD_DIR/streaming/image_streaming_app/image_streaming_app .
sudo rsync -a $RUNTIME_BUILD_DIR/streaming/streaming_inference_app/streaming_inference_app .
sudo rsync -a $RUNTIME_DIR/streaming/runtime_scripts/run_image_stream.sh .
sudo rsync -a $RUNTIME_DIR/streaming/runtime_scripts/run_inference_stream.sh .
sudo rsync -a $RUNTIME_DIR/streaming/streaming_inference_app/categories.txt .
sudo rsync -a $COREDLA_ROOT/build_version.txt $COREDLA_ROOT/build_os.txt .

sudo sed -i "s/A10_Performance.arch/AGX5_Performance.arch/" ./run_inference_stream.sh
sudo chown -R 1000:1000 "$APP_DIR"
```

(`rsync -a` here needs `rsync` on the **host**, not the board — fine, this
step runs entirely on the build machine.)

## 7. Fix the glibc/loader mismatch (SDK toolchain vs. board rootfs)

`dla_benchmark` cross-built against the Yocto SDK requires `GLIBC_2.38`/
`GLIBCXX_3.4.32`+, but this board's Ubuntu-base 22.04.3 rootfs only ships
glibc 2.35. Running the binary directly fails immediately:

```
./dla_benchmark: /lib/aarch64-linux-gnu/libc.so.6: version `GLIBC_2.38' not found
```

**`LD_LIBRARY_PATH` alone does not fix this.** The ELF interpreter path
(`/lib/ld-linux-aarch64.so.1`) is baked into the binary at link time and the
kernel invokes *that* loader directly — before libc is even resolved — so
env vars can't redirect it. Fix: ship the SDK's own matching runtime libs
*and* its own loader alongside the app, then invoke every cross-built binary
explicitly through that loader:

```bash
SYSROOT=$TOP/runtime/embedded_arm_sdk/sysroots/armv8-2a-poky-linux
APP_DIR=$TOP/de25_nano_bringup/rootfs_build/rootfs/home/terasic/app
sudo mkdir -p "$APP_DIR/sdklibs"
for f in ld-linux-aarch64.so.1 libc.so.6 libm.so.6 libpthread.so.0 \
         librt.so.1 libdl.so.2 libgcc_s.so.1 libstdc++.so.6.0.33; do
  sudo cp -a "$SYSROOT/lib/$f" "$APP_DIR/sdklibs/" 2>/dev/null \
    || sudo cp -a "$SYSROOT/usr/lib/$f" "$APP_DIR/sdklibs/"
done
sudo ln -sf libstdc++.so.6.0.33 "$APP_DIR/sdklibs/libstdc++.so.6"
sudo chown -R 1000:1000 "$APP_DIR/sdklibs"
```

Invocation pattern (used in the patches below):

```bash
./sdklibs/ld-linux-aarch64.so.1 --library-path ./sdklibs:. ./dla_benchmark [args]
```

**Patches applied** (all tagged `ponytail:` noting the ceiling — real fix is
matching the board rootfs's glibc to the SDK's, not carrying `sdklibs/`
forever):

- `app/run_inference_stream.sh` — `LD_LIBRARY_PATH=./sdklibs:.` and the
  `streaming_inference_app` call now goes through
  `./sdklibs/ld-linux-aarch64.so.1 --library-path ./sdklibs:.`.
- `app/run_image_stream.sh` — same treatment for `image_streaming_app`.
- `app/dla_benchmark.sh` (new file) — thin wrapper so `dla_benchmark` itself
  doesn't need the incantation typed by hand:
  ```sh
  #! /bin/sh
  cd "$(dirname "$0")"
  exec ./sdklibs/ld-linux-aarch64.so.1 --library-path ./sdklibs:. ./dla_benchmark "$@"
  ```

Verify: `./dla_benchmark.sh --help` should print full usage with no
`version 'GLIBC_...' not found` errors.

## 8. Deploy to the live board

Board's minimal rootfs has no `rsync` — use `tar` over `ssh` instead:

```bash
cd $TOP/de25_nano_bringup/rootfs_build/rootfs/home/terasic/app
tar czf - . | ssh terasic@<board-host> 'mkdir -p ~/app && tar xzf - -C ~/app'
```

(Password auth: use `sshpass -p '<password>' ssh ...` / `sshpass -p ... tar czf - . | sshpass -p ... ssh ...` for one-off, non-interactive transfers — don't persist the password anywhere.)

Sanity check on-target:

```bash
ssh terasic@<board-host> 'cd ~/app && ./dla_benchmark.sh --help'
```

## Known gaps / not yet done

- No compiled model staged on the board. `run_inference_stream.sh` points at
  `/home/root/resnet-50-tf/...`, which doesn't exist on this rootfs (real
  path would be `/home/terasic/...`). Producing the compiled `.bin` +
  `.arch` and copying it over is the next milestone — running actual
  inference end-to-end.
- `de25_nano_bringup/rootfs_build/rootfs/` (the local staging tree used to
  bake `sdcard.img`) and the live board are now **out of sync** if you
  followed step 8 directly against the board rather than rebuilding
  `sdcard.img` first. If the SD card ever gets reflashed from
  `rootfs_build`, redo step 8 (the `app/` directory, including `sdklibs/`
  and the three patched scripts) or rebuild `sdcard.img` from the
  now-updated staging tree first.
