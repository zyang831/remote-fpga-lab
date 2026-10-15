#!/bin/sh
# (Re)program the FPGA from /lib/firmware/output_design.core.rbf through the
# /lib/firmware/my_overlay.dtb configfs overlay, then load the fabric drivers.
#
# Removing the overlay unbinds the fabric drivers before the fabric goes
# away; the fpga-region driver programs the rbf and only then creates the
# overlay's child devices, so nothing touches 0x2000_0000+ mid-reconfig.
# Runs at boot (coredla-fpga.service) and from the fpga-reconfig Mender
# module. Exit non-zero = fabric not usable, caller must roll back.
set -e

OVL=/sys/kernel/config/device-tree/overlays/fpga-reconfig
STATE=/sys/class/fpga_manager/fpga0/state

# fpga-region probes late (after stratix10-svc brings up fpga0); an overlay
# applied before that is a plain DT edit and programs nothing.
i=0
while [ ! -d /sys/class/fpga_region/region0 ] && [ $i -lt 60 ]; do
    sleep 1; i=$((i + 1))
done
[ -d /sys/class/fpga_region/region0 ] || { echo "fpga-region never probed" >&2; exit 1; }

# dla-server holds the msgdma/uio devices open; stop it before the overlay
# (and with it the fabric drivers) is pulled out from under it.
systemctl stop dla-server.service 2>/dev/null || true
rm -f /var/lib/dla/spool/ready

# The SDM refuses a new RECONFIG for ~1 min after a failed one (truncated
# or rejected image), so a rollback right after a bad deploy needs retries.
try=0
while :; do
    [ -d "$OVL" ] && rmdir "$OVL"
    mkdir "$OVL"
    echo my_overlay.dtb > "$OVL/path" && break
    try=$((try + 1))
    [ $try -lt 4 ] || { echo "overlay apply failed after $try tries" >&2; exit 1; }
    sleep 30
done

i=0
while [ "$(cat $STATE)" != operating ] && [ $i -lt 60 ]; do
    sleep 1; i=$((i + 1))
done
[ "$(cat $STATE)" = operating ] || { echo "fpga0 state '$(cat $STATE)' != operating" >&2; exit 1; }
[ "$(cat $OVL/status)" = applied ] || { echo "overlay status '$(cat $OVL/status)' != applied" >&2; exit 1; }

# Drivers bind only if the overlay declared the DLA nodes (GHRD overlays have none).
modprobe uio_pdrv_genirq of_id=generic-uio
modprobe altera_msgdma
modprobe msgdma_userio

# DLA design + a staged model: bring the inference server back up. The
# caller (coredla-model module) waits for spool/ready if it needs to know.
if ls /dev/msgdma_coredla* >/dev/null 2>&1 && [ -f /var/lib/dla/model/graph.bin ] && [ -x /opt/dla/dla-server.sh ]; then
    systemctl start dla-server.service
fi
