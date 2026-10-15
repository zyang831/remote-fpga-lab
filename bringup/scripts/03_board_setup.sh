#!/usr/bin/env bash
# Per-boot runtime setup. Run ON THE BOARD as the terasic user (sudo password: <BOARD_PASSWORD>).
# Also the recovery for a wedged DMA engine: reloads BOTH modules in dependency order.
set -euo pipefail
K=$(uname -r)
sudo rmmod msgdma_userio 2>/dev/null || true
sudo rmmod altera_msgdma 2>/dev/null || true
sudo modprobe altera_msgdma
sudo insmod "/lib/modules/$K/extra/msgdma_userio.ko"
sudo chmod 660 /dev/msgdma_coredla0 /dev/uio0
sudo chgrp terasic /dev/msgdma_coredla0 /dev/uio0
grep -q openvino_arm_cpu_plugin ~/app/plugins.xml ||
  sed -i 's/libopenvino_intel_cpu_plugin.so/libopenvino_arm_cpu_plugin.so/' ~/app/plugins.xml
swapon --show
ls -l /dev/uio0 /dev/msgdma_coredla0
