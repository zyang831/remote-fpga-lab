#!/bin/sh
# One-shot board install for Phase 0. Run as root ON THE BOARD from a dir
# holding every file in this mender/ directory plus ../prebuilt/boot.scr.uimg.
# Idempotent. Reboot afterwards (base dtb + boot script change).
set -eu
cd "$(dirname "$0")"

# 1. Mender client (mender-client4 = mender-auth + mender-update 5.x).
if ! command -v mender-update >/dev/null; then
    apt-get update
    apt-get install -y --no-install-recommends ca-certificates curl gnupg jq
    curl -fsSL https://downloads.mender.io/repos/debian/gpg > /etc/apt/trusted.gpg.d/mender.asc
    echo "deb [arch=$(dpkg --print-architecture)] https://downloads.mender.io/repos/device-components ubuntu/jammy/stable main" \
        > /etc/apt/sources.list.d/mender.list
    apt-get update
    # mender-setup postinst runs an interactive wizard unless mender.conf exists
    mkdir -p /etc/mender && install -m644 mender.conf /etc/mender/mender.conf
    apt-get install -y mender-client4
fi
install -m644 mender.conf /etc/mender/mender.conf
# Different server (replica host): MENDER_URL=https://<host>.<tailnet>.ts.net
[ -z "${MENDER_URL:-}" ] || sed -i "s|\"ServerURL\": \"[^\"]*\"|\"ServerURL\": \"$MENDER_URL\"|" /etc/mender/mender.conf
# U-Boot sets no ethaddr, so eth0's MAC (= Mender identity) is random each boot.
# Pin a random locally-administered MAC once (not machine-id: cloned SD cards
# share it); an existing pin is kept so the accepted identity never changes.
if [ ! -f /etc/systemd/network/10-eth0-mac.link ]; then
    mac=02$(od -An -N5 -tx1 /dev/urandom | tr -d ' \n' | sed 's/../:&/g')
    mkdir -p /etc/systemd/network
    printf '[Match]\nPath=platform-10810000.ethernet\n[Link]\nMACAddress=%s\n' "$mac" > /etc/systemd/network/10-eth0-mac.link
fi
mkdir -p /var/lib/mender
echo device_type=de25-nano > /var/lib/mender/device_type
install -m755 fpga-reconfig coredla-runtime coredla-model /usr/share/mender/modules/v3/

# 2. Reconfig plumbing: firmware pair, up script, boot service, udev.
install -m755 coredla-fpga-up.sh /usr/local/sbin/coredla-fpga-up.sh
install -m644 coredla-fpga.service /etc/systemd/system/coredla-fpga.service
install -m644 90-coredla.rules /etc/udev/rules.d/90-coredla.rules
install -m755 dla-watchdog.sh /usr/local/sbin/dla-watchdog.sh
install -m644 dla-watchdog.service dla-watchdog.timer /etc/systemd/system/
install -m755 fpga-stuck-detector.sh /usr/local/sbin/fpga-stuck-detector.sh
install -m644 fpga-stuck-detector.service /etc/systemd/system/
[ -f /lib/firmware/output_design.core.rbf ] || cp /mnt/fat/golden_top.core.rbf /lib/firmware/output_design.core.rbf
install -m644 overlay_dla.dtbo /lib/firmware/my_overlay.dtb
# Idle design: what boot and fpga-reconfig rollback program (coredla-model keeps it current).
[ -d /var/lib/dla/idle ] || { mkdir -p /var/lib/dla/idle; cp /lib/firmware/output_design.core.rbf /lib/firmware/my_overlay.dtb /var/lib/dla/idle/; }
# Watchdog fed by systemd, reboot 10 s after a panic (docs/OTA_HARDENING_PLAN.md step 1).
mkdir -p /etc/systemd/system.conf.d
install -m644 90-ota-watchdog.conf /etc/systemd/system.conf.d/90-ota-watchdog.conf
install -m644 90-ota-panic.conf /etc/sysctl.d/90-ota-panic.conf
# DLA nodes now live in the overlay; drivers bind when it is applied.
printf 'options uio_pdrv_genirq of_id=generic-uio\n' > /etc/modprobe.d/coredla.conf
printf 'uio_pdrv_genirq\n' > /etc/modules-load.d/coredla.conf
systemctl daemon-reload
systemctl enable coredla-fpga.service mender-authd mender-updated dla-watchdog.timer fpga-stuck-detector.service

# 2c. Phase 1: inference stack lands via coredla-runtime / coredla-model
# artifacts (artifacts/build-runtime.sh, build-model.sh); only the spool
# skeleton is made here. The lab backend drops images in as user terasic.
mkdir -p /var/lib/dla/spool/inbox /var/lib/dla/spool/done /var/lib/dla/spool/results
chown -R terasic /var/lib/dla/spool

# 2b. Tailscale must reach the server from the board: kernel TUN needs a working
# iptables, and this kernel has no nf_tables, so use the legacy backend.
if grep -q userspace-networking /etc/default/tailscaled; then
    update-alternatives --set iptables /usr/sbin/iptables-legacy
    update-alternatives --set ip6tables /usr/sbin/ip6tables-legacy
    sed -i 's/^FLAGS=.*/FLAGS=""/' /etc/default/tailscaled
    systemctl restart tailscaled
fi

# 3. Boot contract: base dtb without DLA nodes, FDT pinned below the DLA window.
for f in socfpga_agilex5_de25_nano.dtb boot.scr.uimg; do [ -f /mnt/fat/$f.pre-mender ] || cp /mnt/fat/$f /mnt/fat/$f.pre-mender; done
cp socfpga_agilex5_de25_nano.nodla.dtb /mnt/fat/socfpga_agilex5_de25_nano.dtb
cp boot.scr.uimg /mnt/fat/boot.scr.uimg
sync
echo "board_setup done - reboot now"
