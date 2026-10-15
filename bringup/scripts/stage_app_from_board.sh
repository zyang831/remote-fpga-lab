#!/usr/bin/env bash
# Pull the ~/app runtime payload off a KNOWN-GOOD board into this release folder.
# The exact command that originally assembled /home/terasic/app was never recorded,
# so cloning a working board is the reliable way to obtain it.
# Usage: ./stage_app_from_board.sh [user@host]     (default terasic@coredla)
set -euo pipefail
TARGET="${1:-terasic@coredla}"
REL="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$REL/app-payload"
ssh "$TARGET" 'tar -C /home/terasic -cf - app' > "$REL/app-payload/app.tar"
ls -lh "$REL/app-payload/app.tar"
echo "Restore onto a new board with:  ssh <board> 'tar -C /home/terasic -xf -' < app-payload/app.tar"
