#!/bin/sh
# OTA hardening step 4b: reset the board when an FPGA reprogram wedges the SDM
# (garbage RBF: "timeout waiting for svc layer buffers", fpga0 stuck in write,
# unkillable writer, journald blocked). A good program leaves the write states
# in <10 s.
#
# Panic, not reboot or sysrq-b: those reset through PSCI, which asks the
# (wedged) SDM to do it, and an orderly reboot also stops the HPS watchdog
# (dw_wdt stop_on_reboot). After a panic the watchdog stays armed and fires
# once systemd stops feeding it. Logs nothing: the journal may be blocked.
STATE=${STATE:-/sys/class/fpga_manager/fpga0/state}
SYSRQ=${SYSRQ:-/proc/sysrq-trigger}
LIMIT=${LIMIT:-60}

n=0
while :; do
    s=
    read -r s < "$STATE" 2>/dev/null
    case "$s" in
        "write init"|write|"write complete") n=$((n + 5)) ;;
        *) n=0 ;;
    esac
    if [ $n -ge "$LIMIT" ]; then
        echo s >> "$SYSRQ"   # emergency sync, queued, does not block
        sleep 2
        echo c >> "$SYSRQ"
        exit 0
    fi
    sleep 5
done
