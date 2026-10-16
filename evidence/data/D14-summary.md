# D14: Wi-Fi uplink series (2026-10-16, run 12:58-13:22 local; D14-wifi-model, D14-wifi-bit; script run_D2b.py with SERIES=D14-wifi)
Setup: USB AIC8800D80 adapter, webcam unplugged, Ethernet unplugged (eth0 DOWN), eduroam (WPA2 Enterprise, saved profile), board <WIFI-IP>, channel 116, nmcli rate 195 Mbit/s, signal 92-100 (nmcli %; `iw` not installed). Tailscale: direct via the Wi-Fi address (<WIFI-IP>), no relay, before and after (link.txt). Backend and Mender on the lab PC (PC on campus network; path is routed campus Wi-Fi, not a direct cable). Random 0-5 s gap (seed 1), 1 warm-up discarded, same bitstreams and alternating flag/fruit models as D2b.

| path / series | n | ok | median s | mean s | SD s | min s | max s | 95% lower limit on success |
|---|---|---|---|---|---|---|---|---|
| Wi-Fi bitstream (6 designs) | 18 | 18 | 7.05 | 7.63 | 1.51 | 4.53 | 10.82 | 84.7% |
| Wi-Fi model switch | 20 | 20 | 39.9 | 41.6 | 5.6 | 35.3 | 53.1 | 86.1% |
| Ethernet bitstream (D2b) | 24 | 24 | 7.05 | 7.30 | 1.81 | 4.28 | 10.82 | 88.3% |
| Ethernet model switch (D2b) | 40 | 40 | 27.18 | 27.88 | 3.74 | 22.94 | 37.79 | 92.8% |

Probe (net_probe.py, Tailscale address, RTT x20, TCP 10 s each way):
| label | RTT avg / max ms | PC->board Mbit/s | board->PC Mbit/s |
|---|---|---|---|
| direct Ethernet (D1-net) | 2.8 / 5.2 | 174.8 | 180.2 |
| Wi-Fi, start | 4.5 / 8.1 | 28.2 | 27.0 |
| Wi-Fi, end | 7.2 / 14.8 | 27.6 | 28.0 |

R3 (< 60 s): met in every Wi-Fi run (longest 53.1 s, model switch; 6 of 20 model switches over 45 s). Bitstream times equal the Ethernet ones (poll-bound). Model switch is 12.7 s slower at the median (60-MB download at about 28 Mbit/s through the Tailscale tunnel).
Crash follower: 1 `inference on FPGA did not complete` (jobs finished 100000, SEGV) at 12:58:50 local, within seconds of the series start (the warm-up switch, row 0); it follows an inference-server run that had reached exactly 100000 jobs. Series rows all ok. No further crash in the window. Journal: journal-follow.txt. Kernel log shows aic8800 debug lines only; no dropouts observed.
Not done: webcam stream (unplugged), warm-reboot adapter return, live-view D10 test.
Verdict for IV-A: "power cable plus network can be Wi-Fi" is now measured on eduroam: n = 18 and 20, no failures, R3 met. USB-hang reason for Ethernet-only still holds (webcam + adapter not retested).
