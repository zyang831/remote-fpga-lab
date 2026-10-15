#!/usr/bin/env bash
# Prove the fabric, the UIO binding and the IRQ wiring are live. Run ON THE BOARD.
# Never gate on /sys/class/fpga_manager/fpga0/state - u-boot's `fpga load` bypasses it
# and it always reads `unknown`.
set -uo pipefail
fail=0
chk() { printf '%-28s %s\n' "$1" "$2"; [ "$2" = "$3" ] || { echo "  EXPECTED: $3"; fail=1; }; }

chk "uio0 name" "$(cat /sys/class/uio/uio0/name)" "coredla0@20020000"
chk "uio0 map0 size" "$(cat /sys/class/uio/uio0/maps/map0/size)" "0x0000000000001000"

ID=$(sudo python3 -c "
import mmap,os
f=os.open('/dev/uio0',os.O_RDONLY); m=mmap.mmap(f,0x1000,prot=mmap.PROT_READ)
print(m[0x10:0x20].rstrip(b'\x00').decode(), m[0x30:0x50].rstrip(b'\x00').decode())")
chk "DLA CSR identity" "$ID" "2025.3.1/20 AGX5_Small_NoSoftmax"

IRQ=$(grep -c '20021000.msgdma' /proc/interrupts)
chk "msgdma IRQ bound" "$IRQ" "1"
grep '20021000.msgdma' /proc/interrupts || true

[ -c /dev/msgdma_coredla0 ] || { echo "/dev/msgdma_coredla0 missing"; fail=1; }
exit $fail
