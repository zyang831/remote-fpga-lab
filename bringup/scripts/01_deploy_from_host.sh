#!/usr/bin/env bash
# Push the release payload to a DE25-Nano and install it. Run on the HOST.
# Usage: ./01_deploy_from_host.sh [user@host]      (default terasic@coredla)
set -euo pipefail
TARGET="${1:-terasic@coredla}"
REL="$(cd "$(dirname "$0")/.." && pwd)"

echo "== staging tarball =="
TAR=$(mktemp /tmp/coredla_deploy.XXXX.tar)
tar -cf "$TAR" -C "$REL" prebuilt scripts/02_board_install.sh scripts/03_board_setup.sh \
                          scripts/04_board_verify.sh scripts/05_board_benchmark.sh

echo "== copying to $TARGET:/tmp =="
scp "$TAR" "$TARGET:/tmp/coredla_deploy.tar"
rm -f "$TAR"

echo "== installing on board (sudo password: <BOARD_PASSWORD>) =="
ssh -t "$TARGET" 'rm -rf /tmp/coredla_deploy && mkdir -p /tmp/coredla_deploy &&
                  tar -xf /tmp/coredla_deploy.tar -C /tmp/coredla_deploy &&
                  chmod +x /tmp/coredla_deploy/scripts/*.sh &&
                  sudo /tmp/coredla_deploy/scripts/02_board_install.sh'

echo
echo "Board files installed. Still to do (large payload, not in this tarball):"
echo "  - copy model/resnet50_nosoftmax.bin + model/AGX5_Small_NoSoftmax.arch to ~/app/resnet-50-tf/"
echo "  - stage the ~/app runtime payload (see README 'Application payload')"
echo "Then reboot the board and run scripts/04_board_verify.sh on it."
