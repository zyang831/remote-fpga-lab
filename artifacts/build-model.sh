#!/bin/bash
# Build a coredla-model artifact from ../models/<name>/: ../build/coredla-model-<name>-<ver>.mender.
# Model dir: graph.bin (dla_compiler output), categories.txt, one *.arch, name.
# The DLA bitstream + overlay are the same for every model (arch fixed).
#   ./build-model.sh imagenet
set -eu
cd "$(dirname "$0")/.."
M=models/$1
RBF=${RBF:-board/dla_small_sb20480.core.rbf}
DTB=${DTB:-board/overlay_dla.dtbo}
for f in graph.bin categories.txt name; do [ -f "$M/$f" ] || { echo "missing $M/$f" >&2; exit 1; }; done
ARCH=$(ls "$M"/*.arch)
VER=$(cat "$M/graph.bin" "$M/categories.txt" "$ARCH" "$RBF" "$DTB" | sha256sum | cut -c1-8)
NAME=coredla-model-$1-$VER
STAGE=$(mktemp -d); trap 'rm -rf "$STAGE"' EXIT
cp "$RBF" "$STAGE/output_design.core.rbf"; cp "$DTB" "$STAGE/my_overlay.dtb"   # names fixed by the board module
mender-artifact write module-image -T coredla-model -t de25-nano -n "$NAME" -o build/$NAME.mender \
    -f "$STAGE/output_design.core.rbf" -f "$STAGE/my_overlay.dtb" \
    -f "$M/graph.bin" -f "$M/categories.txt" -f "$M/name" -f "$ARCH" >/dev/null
ls -l build/$NAME.mender
