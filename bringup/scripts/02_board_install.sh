#!/usr/bin/env bash
# Install bitstream, devicetree, kernel modules, boot script and module config.
# Run ON THE BOARD as root:  sudo ./02_board_install.sh
# Reboot afterwards - the bitstream is loaded by u-boot, not by Linux.
set -euo pipefail
[ "$(id -u)" -eq 0 ] || { echo "run as root"; exit 1; }
SRC="$(cd "$(dirname "$0")/../prebuilt" && pwd)"
K=$(uname -r)                       # expect 6.12.11-gd7d192a9ddd9-dirty

mountpoint -q /mnt/fat || { mkdir -p /mnt/fat; mount /dev/mmcblk0p1 /mnt/fat; }

# FAT partition: back up whatever is there once, then overwrite
for f in golden_top.core.rbf socfpga_agilex5_de25_nano.dtb; do
  if [ -f "/mnt/fat/$f" ] && [ ! -f "/mnt/fat/$f.orig" ]; then
    cp -a "/mnt/fat/$f" "/mnt/fat/$f.orig"
  fi
  cp "$SRC/$f" "/mnt/fat/$f"
done
if [ -f /mnt/fat/boot.scr.uimg ] && [ ! -f /mnt/fat/boot.scr.uimg.bak ]; then
  cp -a /mnt/fat/boot.scr.uimg /mnt/fat/boot.scr.uimg.bak
fi
cp "$SRC/boot.scr.uimg" /mnt/fat/boot.scr.uimg

# kernel modules
install -D -m 644 "$SRC/modules/msgdma_userio.ko" "/lib/modules/$K/extra/msgdma_userio.ko"
install -D -m 644 "$SRC/modules/altera-msgdma.ko" "/lib/modules/$K/kernel/drivers/dma/altera-msgdma.ko"
depmod -a

# module load order + the UIO bind option
install -m 644 "$SRC/config/coredla-modprobe.conf"     /etc/modprobe.d/coredla.conf
install -m 644 "$SRC/config/coredla-modules-load.conf" /etc/modules-load.d/coredla.conf

# swap - 683 MB usable with mem=768M, dla_benchmark peaks ~475 MB RSS
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

sync
umount /mnt/fat
echo "installed for kernel $K - reboot now"
