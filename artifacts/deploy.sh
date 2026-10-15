#!/bin/bash
# Build an fpga-reconfig artifact from <rbf> + <overlay.dtbo> and deploy it.
#   MENDER_USER=... MENDER_PASS=... ./deploy.sh board.rbf ../board/overlay_ghrd.dtbo [name]
set -eu
cd "$(dirname "$0")"
RBF=$1; DTB=$2; NAME=${3:-coredla-$(basename "$RBF" .rbf)-$(date +%Y%m%d-%H%M%S)}
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
cp "$RBF" "$TMP/output_design.core.rbf"; cp "$DTB" "$TMP/my_overlay.dtb"   # names fixed by the board module
mender-artifact write module-image -T fpga-reconfig -t de25-nano -n "$NAME" -o "$TMP/a.mender" \
    -f "$TMP/output_design.core.rbf" -f "$TMP/my_overlay.dtb" >/dev/null
./mender-deploy.sh "$TMP/a.mender"
