#!/bin/bash
# Cross-compile dla-server for the DE25-Nano HPS with the same Yocto SDK and
# prebuilt OpenVINO/OpenCV that built dla_benchmark (RUNBOOK steps 10-12).
set -eu
RT=${RT:-$HOME/coredla_work/runtime}
cd "$(dirname "$0")"
export PATH=$RT/.cmake_venv/bin:$PATH
cmake -B build -G Ninja -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_TOOLCHAIN_FILE=$RT/embedded_arm_sdk/cmake/embedded.arm.cmake \
  -DOpenVINO_DIR=$RT/hps_packages/armcpu_package/runtime/cmake \
  -DOpenCV_DIR=$RT/hps_packages/armcpu_package/opencv/lib/cmake/opencv4 \
  -DDLA_PLUGIN_INC=/opt/altera/fpga_ai_suite_2025.3.1/dla/dla_plugin/inc \
  -DJPEG_LIB=$PWD/../build/runtime-libs/libjpeg.so.8  # the board rootfs's, fetched by build-runtime.sh
cmake --build build
ls -l build/dla-server
