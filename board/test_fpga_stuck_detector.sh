#!/bin/sh
# Check fpga-stuck-detector.sh on any Linux box: no trigger while operating,
# sync then crash once fpga0 sits in write. Run: sh board/test_fpga_stuck_detector.sh
set -eu
d=$(mktemp -d); trap 'rm -rf "$d"' EXIT
det="$(dirname "$0")/fpga-stuck-detector.sh"

echo operating > "$d/state"; : > "$d/sysrq"
STATE="$d/state" SYSRQ="$d/sysrq" LIMIT=10 timeout 12 sh "$det" && exit 1 || true
[ ! -s "$d/sysrq" ] || { echo "FAIL: triggered while operating"; exit 1; }

echo write > "$d/state"
STATE="$d/state" SYSRQ="$d/sysrq" LIMIT=10 timeout 20 sh "$det"
[ "$(cat "$d/sysrq")" = "$(printf 's\nc')" ] || { echo "FAIL: sysrq got '$(cat "$d/sysrq")'"; exit 1; }
echo PASS
