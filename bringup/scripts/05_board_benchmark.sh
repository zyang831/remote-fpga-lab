#!/usr/bin/env bash
# The qualified inference run. Run ON THE BOARD.
set -euo pipefail
export COREDLA_ROOT=/home/terasic/app
cd ~/app
./dla_benchmark.sh \
  -cm resnet-50-tf/resnet50_nosoftmax.bin \
  -arch_file resnet-50-tf/AGX5_Small_NoSoftmax.arch \
  -plugins ./plugins.xml \
  -i resnet-50-tf/images \
  -d HETERO:FPGA,CPU -niter 8 -api sync
