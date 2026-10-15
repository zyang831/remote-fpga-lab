#!/bin/sh
# Restart dla-server when its live picture stalls while the process stays up (the
# capture thread gives up after a DMA timeout: "camera: frame N wait failed, live
# view stopped"). Run by dla-watchdog.timer. Only ever restarts a dla-server that is
# already running (try-restart), never during a reconfig or Mender install (those
# stop/start it themselves and the fabric may not be the DLA), never in file-only
# mode (no live.jpg), never in its first minute (graph import). Staleness = mtime
# unchanged over 10 s, not an age: the board has no RTC and NTP jumps the clock.
LIVE=/var/lib/dla/spool/results/live.jpg
busy() { pgrep -f '/usr/share/mender/modules/v3/|coredla-fpga-up.sh' >/dev/null; }
busy && exit 0
systemctl is-active -q dla-server || exit 0
up_us=$(systemctl show dla-server -p ActiveEnterTimestampMonotonic --value)
now_s=$(cut -d. -f1 /proc/uptime)
[ $((now_s - up_us / 1000000)) -ge 60 ] || exit 0
m1=$(stat -c %y "$LIVE" 2>/dev/null) || exit 0
sleep 10
m2=$(stat -c %y "$LIVE" 2>/dev/null) || exit 0
[ "$m1" = "$m2" ] || exit 0
busy && exit 0
systemctl is-active -q dla-server || exit 0
echo "live.jpg unchanged for 10 s, restarting dla-server"
systemctl try-restart dla-server
