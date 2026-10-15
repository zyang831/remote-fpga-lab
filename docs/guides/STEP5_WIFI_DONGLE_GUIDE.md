# STEP 5: USB WiFi Dongle Bring-Up (AIC8800D80)

Manual replication guide for enabling WiFi on DE25-Nano via USB dongle.
Tested on board-01, kernel `6.12.11-gd7d192a9ddd9-dirty`, Ubuntu 22.04 aarch64.

## 0. Background

The dongle (chipset AIC8800D80) ships pretending to be a USB CD-ROM/mass-storage
device (Windows driver installer). Windows silently sends a vendor command to
flip it into real WiFi mode; Linux never does, so it just sits there as a fake
CD-ROM. There is no mainline kernel driver for this chip — it needs an
out-of-tree module.

Identify the dongle first:

```bash
lsusb
# Bus 001 Device 002: ID a69c:5723 aicsemi Aic MSC   <- fake CD-ROM mode
```

If the VID:PID differs from `a69c:5723`, search `"<vid>" "<pid>" aic8800 wifi
dongle linux` before assuming the steps below apply verbatim — mode-switch
commands and target PIDs vary by chip sub-variant (D80 vs DC vs M40, etc).

## 1. Install tools on the board

```bash
sudo apt update
sudo apt install -y usb-modeswitch usbutils sg3-utils eject build-essential git dkms
```

## 2. Mode-switch the dongle to WiFi mode

```bash
sudo usb_modeswitch -v a69c -p 5723 -KQ
sleep 4
lsusb
# Bus 001 Device 003: ID a69c:8d80 aicsemi AIC Wlan   <- now in WiFi mode
```

Note: a raw `sg_raw` vendor SCSI command (`fd 00 00 ... f2` sent to `/dev/sda`)
is documented for the *1111:1111* AIC8800 bootloader variant and does **not**
work on the `a69c:5723` variant (returns "Invalid command operation code").
Use `usb_modeswitch -K` instead — confirmed working.

This mode-switch does not survive power loss / replug — see step 6 for making
it automatic.

## 3. Get a kernel source tree that matches the board's running kernel

The driver is a kernel module — it must be built against the **exact** source
tree used to build the board's running kernel, matching `uname -r`. Do not use
`apt install linux-headers-generic` — that installs a generic Ubuntu kernel's
headers, which is a different kernel than the board is actually running.

Check where the board's own kernel source tree is:

```bash
ls -la /lib/modules/$(uname -r)/build
```

On board-01 this symlink points to
`/home/<user>/coredla_work/de25_nano_bringup/linux` — a path that only
exists on the build workstation, not on the board itself (the kernel was
cross-built there and only the compiled kernel/modules were deployed). That
tree's git commit (`git log -1`) matches the `-g<hash>` suffix in `uname -r`,
and it already has `.config`, `Module.symvers`, `vmlinux`, `System.map` in
place from the original build — everything needed for an out-of-tree module
build, no rebuild required.

If you're on a different board/setup where this symlink is valid on the board
itself, you can build natively on-device instead of cross-compiling (skip to
step 4B).

## 4A. Cross-compile the driver on the workstation (what was done)

On the workstation (not the board), with the matching kernel source tree at
`$KDIR`:

```bash
# One-time: cross toolchain
sudo apt install -y crossbuild-essential-arm64   # provides aarch64-linux-gnu-gcc

git clone https://github.com/Xanderful/aic8800d80.git
cd aic8800d80/drivers/aic8800

KDIR=/home/<user>/coredla_work/de25_nano_bringup/linux
make KDIR=$KDIR ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu-
```

**If modpost fails** with a wall of undefined cfg80211 symbols:

```
ERROR: modpost: "cfg80211_scan_done" [.../aic8800_fdrv.ko] undefined!
```

the kernel tree's top-level `Module.symvers` was written before the wireless
modules were built, so it lists no `cfg80211` exports (`grep -c cfg80211
$KDIR/Module.symvers` returns 0) even though `net/wireless/cfg80211.ko` is
sitting right there. `CONFIG_MODVERSIONS` is off in this tree, so the CRCs are
all zero and a symbol list is enough — generate one from the built module and
hand it to the build:

```bash
aarch64-linux-gnu-nm $KDIR/net/wireless/cfg80211.ko \
  | sed -n 's/.* __ksymtab_//p' | sort -u \
  | awk '{printf "0x00000000\t%s\tcfg80211\tEXPORT_SYMBOL\t\n", $1}' > /tmp/cfg80211.symvers

make KDIR=$KDIR ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu- \
     KBUILD_EXTRA_SYMBOLS=/tmp/cfg80211.symvers
```

Don't reach for `KBUILD_MODPOST_WARN=1` instead — it builds, but the module
then records no `depends:` line, so `modprobe` won't pull in `cfg80211` first.
With the symvers file, `modinfo` shows `depends: cfg80211,aic_load_fw`.

**If the build fails** with something like:

```
error: too few arguments to function 'cfg80211_cac_event'
```

this board's kernel tree has a newer `cfg80211_cac_event()` signature (extra
`link_id` param) than its `6.12.x` version number suggests — a vendor SoC
backport ahead of its declared kernel version. The upstream driver repo only
adds that param when `LINUX_VERSION_CODE >= KERNEL_VERSION(6, 15, 0)`, which
is false for `6.12.11`, so the guard misfires. Fix (in
`drivers/aic8800/aic8800_fdrv/rwnx_radar.c`): find the two occurrences of

```c
#if LINUX_VERSION_CODE >= KERNEL_VERSION(6, 15, 0)
                   , 0
#endif
```

(inside the two `cfg80211_cac_event(...)` calls) and change the guard to
`#if 1` so the extra `, 0` argument is always included. Re-run `make`. Verify
the actual signature in your tree first with:

```bash
grep -A4 "void cfg80211_cac_event" $KDIR/include/net/cfg80211.h
```

If it doesn't take `link_id`, don't apply this patch — the build error would
be something else.

### REQUIRED second patch — RX buffer-pool leak (or WiFi dies ~72s after connecting)

The build above succeeds and the dongle will associate + get DHCP, but with
the stock source the **data path goes dead ~72 seconds after connecting**: the
link still shows `connected`, TX keeps working, but nothing is received —
`ping` gives `Destination Host Unreachable`, `ip neigh` for the gateway goes
`FAILED`, and `dmesg` floods with `rxbuff list is empty` / `failed to alloc
rxbuff`. This is a driver bug, not an AP or signal problem, and it must be
patched or the dongle is useless as an uplink.

Cause: the driver is built with `CONFIG_PREALLOC_RX_SKB=y` (a fixed 1000-buffer
RX pool). In `drivers/aic8800/aic8800_fdrv/aicwf_txrxif.c`, function
`aicwf_process_rxframes()`, the USB-aggregation branch bails on a routine
`if (pkt_len > 1600)` condition with `return -EBADE`, which aborts the whole
receive-queue drain while the USB completion path keeps taking buffers from the
pool — the pool empties in ~72s and RX stops permanently.

Fix — change that `return -EBADE;` to `break;`:

```c
                if (pkt_len > 1600) {
                    AICWFDBG(LOGERROR, "%s pkt_len > 1600, drop rest of buffer\r\n", __func__);
                    break;      /* was: aicwf_prealloc_rxbuff_free(...); atomic_dec(...); return -EBADE; */
                }
```

`break` exits the inner subframe loop; the existing end-of-loop
`aicwf_prealloc_rxbuff_free()` then returns the buffer to the pool and the
outer loop keeps draining. Keep `CONFIG_PREALLOC_RX_SKB=y` — do **not** try to
fix this by setting it to `n`: the driver's non-prealloc RX path is broken for
the 8800D80 and firmware init then fails with `err_lmac_reqs` / `errno -110`
and no interface is created at all.

### REQUIRED third patch — buffer walker runs past the end of the URB data

Symptom: `dmesg` fills with `aicwf_process_rxframes pkt_len > 1600, drop rest
of buffer` even on a healthy link, and (with the RX patch above) each one costs
you the remaining subframes in that buffer.

Cause: the prealloc RX buffers are 20 KB each, and `aicwf_usb_rx_complete()`
records how much the URB actually delivered in `buffer->len` — but
`buffer->end` is set once, at submit time, to `data + 20480`. The subframe
walker `aicwf_another_ptk_1()` only stops at `buffer->end`, so after the last
real subframe it keeps reading into whatever the previous packet left in that
buffer (nothing memsets it between uses) and parses a stale length. Most of the
time that garbage length trips the `> 1600` check.

Fix — bound the walk by the data the URB actually wrote:

```c
    if(read == NULL || read >= buffer->end) {
        return false;
    }

    /* URB wrote only buffer->len bytes; the rest of the 20K buffer is stale
     * data from a previous packet. Stop at the end of real data, not at the
     * end of the allocation, or the walker parses garbage lengths. */
    if(buffer->len && read >= buffer->start + buffer->len) {
        return false;
    }
```

With this in place the `pkt_len > 1600` line stops appearing at all — on
de25-nano a 95-packet ping plus a 4000-packet full-MTU flood produced zero of
them (it was 23 per connection attempt before).

### Shortcut: apply both patches from the saved patch file

All three patches (the `cfg80211_cac_event` guard, the RX pool fix and the
walker bound) are captured in
`de25_nano_bringup/aic8800d80-de25nano.patch`. From a fresh clone:

```bash
git clone https://github.com/Xanderful/aic8800d80.git
cd aic8800d80
git apply /home/<user>/coredla_work/de25_nano_bringup/aic8800d80-de25nano.patch
cd drivers/aic8800
make KDIR=$KDIR ARCH=arm64 CROSS_COMPILE=aarch64-linux-gnu-
```

(Re-verify the `cfg80211_cac_event` signature as above if the kernel tree
changed — the patch assumes the backported `link_id` signature.)

Output: `aic_load_fw/aic_load_fw.ko` and `aic8800_fdrv/aic8800_fdrv.ko`
(ELF aarch64, confirm with `file *.ko`). Confirm the RX fix made it in:
`aarch64-linux-gnu-strings aic8800_fdrv/aic8800_fdrv.ko | grep "drop rest of buffer"`.

## 4B. Or build natively on the board

If `/lib/modules/$(uname -r)/build` is valid on the board itself:

```bash
git clone https://github.com/Xanderful/aic8800d80.git
cd aic8800d80
make
```

Apply the same `rwnx_radar.c` patch from step 4A if the same build error
occurs.

## 5. Deploy modules + firmware to the board

If the board has no network yet (fresh bring-up, no Ethernet carrier), you can
push the whole payload down the serial console instead of `scp` — roughly
11 KB/s, so a stripped, gzipped payload is worth the trouble:

```bash
# workstation: strip debug info and pack modules + firmware + udev rule
aarch64-linux-gnu-strip --strip-debug aic8800_fdrv.ko aic_load_fw.ko   # 2.5M -> 707K
tar czf aicpkg.tgz aic8800_fdrv.ko aic_load_fw.ko aic8800D80/ aic.rules  # ~1 MB
```

Then, on the console (`stty -echo` first, or the board echoes every byte back
and halves your throughput):

```
stty -echo; base64 -d > /tmp/aicpkg.tgz
<stream base64 here, then Ctrl-D>
stty echo; md5sum /tmp/aicpkg.tgz
```

Drive it from a short pyserial script with `xonxoff=True` and compare the md5
against the host's. At 115200 the ~1.4 MB of base64 takes about two minutes;
send it in slices if your tooling caps command runtime. Unpack into `/tmp` on
the board and continue with the install commands below.

With networking available, from the workstation:

```bash
KVER=6.12.11-gd7d192a9ddd9-dirty   # match the board's `uname -r`

scp drivers/aic8800/aic_load_fw/aic_load_fw.ko \
    drivers/aic8800/aic8800_fdrv/aic8800_fdrv.ko \
    terasic@board-01:/tmp/
scp -r fw/aic8800D80 terasic@board-01:/tmp/aic8800D80_fw
scp tools/aic.rules terasic@board-01:/tmp/aic.rules
```

On the board:

```bash
KVER=$(uname -r)
MODDIR=/lib/modules/$KVER/kernel/drivers/net/wireless/aic8800
sudo mkdir -p $MODDIR
sudo install -m 644 /tmp/aic_load_fw.ko /tmp/aic8800_fdrv.ko $MODDIR/

sudo mkdir -p /lib/firmware/aic8800D80
sudo cp -r /tmp/aic8800D80_fw/* /lib/firmware/aic8800D80/

sudo cp /tmp/aic.rules /etc/udev/rules.d/aic.rules
sudo udevadm control --reload-rules
sudo depmod -a $KVER
```

## 6. Load the driver and confirm the interface

```bash
sudo modprobe aic_load_fw
sudo modprobe aic8800_fdrv
sleep 3
lsmod | grep aic
ip link   # look for wlx<mac>, e.g. wlx6c1ff78b5bf8
```

Check `dmesg | tail -40` for firmware load messages
(`AICWFDBG(LOGINFO) ...`) and interface creation
(`New interface create wlan0` → renamed to `wlx<mac>`).

## 7. Connect to WiFi

```bash
sudo nmcli device wifi list ifname wlx<mac>
sudo nmcli device wifi connect "<SSID>" password "<password>" ifname wlx<mac>
ip -4 addr show wlx<mac>
ping -c3 -I wlx<mac> 8.8.8.8
```

**Verify the data path holds — don't trust a 3-ping.** The RX-leak symptom
(above) only appears ~72s in, so a quick ping right after connecting passes
even on the broken driver. Confirm a patched build with a sustained test and a
clean pool:

```bash
ping -I wlx<mac> -c 100 -i 1 <gateway-ip>        # expect 0% loss across ~100s
ip neigh show <gateway-ip> dev wlx<mac>          # expect REACHABLE, not FAILED
sudo dmesg | grep -c "rxbuff list is empty"      # expect 0
```

### WPA-Enterprise (eduroam) instead of a PSK

`nmcli device wifi connect` can't express an 802.1X profile; build it with
`con add`:

```bash
sudo nmcli con add type wifi ifname wlx<mac> con-name eduroam ssid eduroam \
     wifi-sec.key-mgmt wpa-eap \
     802-1x.eap peap 802-1x.phase2-auth mschapv2 \
     802-1x.identity '<user>@university.example' \
     802-1x.password '<password>' 802-1x.password-flags 0 \
     connection.autoconnect yes
sudo nmcli con up eduroam
```

Two things bite here:

- **`802-1x.password-flags 0` is mandatory.** Without it NetworkManager marks
  the password as agent-owned, and on a headless board there is no agent, so
  activation dies with `Secrets were required, but not provided` even though
  `nmcli --show-secrets con show eduroam` displays the password you just set.
- **Don't set an anonymous identity** on Monash eduroam. With
  `802-1x.anonymous-identity <user>@example.edu` the RADIUS server
  answers the very first EAP-Response/Identity with EAP-Failure — before any
  TLS — and NetworkManager reports it as a missing-secrets failure, which sends
  you hunting in the wrong place. Clearing it (`802-1x.anonymous-identity ""`)
  so the real identity is used as the outer identity connects immediately.

When an enterprise association fails, read the supplicant, not NetworkManager:

```bash
sudo wpa_cli -p /run/wpa_supplicant log_level DEBUG
sudo nmcli con up eduroam
sudo journalctl -u wpa_supplicant -n 300 --no-pager | grep -iE "EAP-|EAPOL|TLS"
```

`EAP: Received EAP-Failure` right after the identity response means the RADIUS
server rejected the identity/realm; silence after `CTRL-EVENT-EAP-STARTED`
means EAPOL frames aren't crossing the air at all (that one *is* a driver
problem). Note also that `rx_packets` on the netdev stays at 0 during EAP even
when EAPOL frames are arriving fine — don't use it to judge whether the RX path
works until the link is actually up.

## 8. Make it survive reboot / replug

The dongle resets to fake-CD-ROM mode every time it loses power (reboot,
unplug/replug). The `/etc/udev/rules.d/aic.rules` file installed in step 5
handles this automatically going forward — it matches the dongle's
mass-storage PID (`a69c:5723` for this unit; also covers `5721`/`572c` for
other variants) and runs `eject /dev/%k`, which re-triggers the same mode
switch as `usb_modeswitch -K` did manually in step 2.

If the board has no network to `apt install eject` (as on de25-nano), call
`usb_modeswitch` from the rule instead — it sends the same SCSI eject:

```
# /etc/udev/rules.d/aic.rules
KERNEL=="sd*", ATTRS{idVendor}=="a69c", ATTRS{idProduct}=="5723", ENV{UDISKS_IGNORE}="1", RUN+="/usr/sbin/usb_modeswitch -v a69c -p 5723 -K"
```

Otherwise the upstream rule needs the `eject` package (step 1). No further action
needed — module autoload happens via the standard USB modalias match against
`aic8800_fdrv.ko`'s device table, picked up by `depmod` in step 5.

Verify persistence by rebooting the board and checking:

```bash
lsusb                 # should show a69c:8d80 directly, no manual modeswitch
ip link                # wlx<mac> should be present
nmcli device status    # should reconnect automatically if using nmcli's saved connection
```

## Notes / gotchas

- Interface name is `wlx<mac>`, not renamed — the upstream `aic.rules` only
  renames the CUDY WU900's `368b:8d81` ID to `wlan_cudy`; our `a69c:8d80` ID
  isn't covered, so it keeps the udev default `wlx<mac>` name.
- `CONFIG_CHR_DEV_SG` is not enabled in this board's kernel, so `/dev/sg*`
  doesn't exist — irrelevant once `usb_modeswitch -K` is used instead of raw
  `sg_raw` (see step 2 note).
- If the board's kernel gets rebuilt/updated, re-check the
  `cfg80211_cac_event` signature (step 4A) before assuming the same patch
  still applies.
- **Firmware init wedge (`-110`) needs a physical power-cycle to clear.** The
  dongle firmware sometimes wedges at probe: `dmesg` shows `err_lmac_reqs` →
  `aicwf_rwnx_usb_platform_init err -110` → `probe ... failed with error -110`
  and no `wlx<mac>` interface appears. This state persists across a warm
  `sudo reboot` and across software USB re-enumeration (`echo 0/1 >
  /sys/bus/usb/devices/<port>/authorized`, driver `unbind`/`bind`, `rmmod`/
  `modprobe`) — because none of those cut USB VBUS. **Only a physical
  unplug/replug of the dongle (or a full board power-off) recovers it.** There
  is no `uhubctl` / software port-power control on this board. This is a
  separate issue from the RX-leak patch and is still open — it limits
  unattended *self-recovery*, not steady-state throughput.
- **`amsdu_rx_max=0` is pinned on de25-nano** via
  `/etc/modprobe.d/aic8800.conf`. It was set while chasing the `pkt_len > 1600`
  drops and made no measurable difference (the walker-bound patch is what fixed
  those), but it is the parameter set the board was validated with, so it stays
  until someone retests the default (`2`) under load.
- **Board 02 (`de25-nano`) status, 2026-08-24:** built and deployed over the
  serial console with no Ethernet, joined `eduroam` (5 GHz, 802.1X
  PEAP/MSCHAPv2), `10.192.28.247/21`. Sustained test: 95 pings to the gateway
  at 1 s intervals, 0% loss (well past the ~72 s point where the unpatched
  driver dies), then 4000 packets of `ping -f -s 1472`, 0% loss, with zero
  `rxbuff` and zero `pkt_len > 1600` lines in `dmesg`. The reboot/replug
  persistence path (udev rule) has not been exercised on this board yet.
- **RX-leak patch is mandatory (step 4A, second patch).** A driver built from
  stock source associates but silently loses the receive path ~72s later; it is
  not optional. See `de25_nano_bringup/aic8800d80-de25nano.patch`.
