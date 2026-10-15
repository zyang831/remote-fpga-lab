#!/bin/bash
# models/<name>/model.xml -> models/<name>/graph.bin with the FPGA AI Suite
# compiler for the board's arch, then sanity-check the placement report.
#   ./compile.sh fruit
set -eu
cd "$(dirname "$0")/../models/$1"
DLA_ARCH=${DLA_ARCH:-../imagenet/AGX5_Small_k16c16_sb20480.arch}
[ -f "$(basename "$DLA_ARCH")" ] || { rm -f ./*.arch; cp "$DLA_ARCH" .; }   # exactly one .arch per model dir
set +u; source /opt/intel/openvino_2024/setupvars.sh >/dev/null; source /opt/altera/fpga_ai_suite_2025.3.1/dla/bin/init_env.sh >/dev/null; set -u
rm -rf dlac-report && mkdir dlac-report && cd dlac-report
dla_compiler --march "../$(basename "$DLA_ARCH")" --network-file ../model.xml \
    --foutput-format dla_compiled_result --o ../graph.bin --fdisplay-device 2>&1 | tail -15
cd ..
echo "--- layers not on FPGA:"
awk -F, 'NR>1 && $2!="FPGA"' dlac-report/*_dla_layer_device.csv
N_CPU=$(awk -F, 'NR>1 && $2!="FPGA" && $3!="Result"' dlac-report/*_dla_layer_device.csv | wc -l)
[ "$N_CPU" -le 1 ] || { echo "more than the softmax landed on the CPU" >&2; exit 1; }
echo "--- ddr:"; cat dlac-report/ddr_buffer_info_*.txt
head -c 16 graph.bin | tr '\0' '\n' | head -1 | grep -qx "HETERO:FPGA,CPU" || { echo "graph.bin device header wrong" >&2; exit 1; }
N=$(wc -l < categories.txt)
grep -q "<dim>$N</dim>" model.xml || { echo "model.xml has no [1,$N] tensor" >&2; exit 1; }
ls -l graph.bin
