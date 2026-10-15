# D10 video bandwidth (2026-10-15; D10-video/viewers.csv, nic.csv; script ../run_D10.py)
Method: 30 s per condition, viewers are threads on the lab PC pulling the stream, bytes counted at the client; NIC byte counters (eno1 = board cable, tailscale0 = overlay, lo) read before/after; board load average read over ssh. Board reached as `coredla` = tailscale address (WireGuard overlay over the direct cable). One run per condition (n=1, 30 s), so no spread; per-viewer rates were identical across viewers within 2%.

| view | viewers | Mbit/s per viewer (client side) | board->lab-PC Mbit/s (tailscale0 rx) | board load avg |
|---|---|---|---|---|
| idle (no viewer) | 0 | - | 0.04 | 2.37 -> 2.29 |
| classifier live view (backend SSE: JPEG frame + result, ~14 Hz) | 1 | 3.00 | 2.32 | 2.39 -> 2.40 |
| same | 5 | 3.06-3.07 | 11.7 | 2.45 -> 3.21 |
| webcam MJPEG (ustreamer, 640x480, direct from board) | 1 | 5.60 | 5.7 | 3.12 -> 2.74 |
| same | 5 | 5.60 each | 28.4 | 2.62 -> 2.93 |

Findings: bandwidth per viewer is constant and linear in viewers; the overlay adds no visible overhead beyond about 4% (client 5.6 Mbit/s vs 5.7 on the wire). Live view: each viewer opens its own ssh to the board (backend design), so board->server traffic is 2.3 Mbit/s per viewer and board load rises with viewers (2.4 to 3.2 with 5). Webcam: the browser pulls MJPEG straight from the board, so the board uplink carries 5.6 Mbit/s per viewer (28 Mbit/s for 5), well below the 1 Gbit/s cable but a limit for a Wi-Fi uplink (D14) or many viewers.
Caveats: viewers were co-located with the server, so these are payload rates, not a WAN test; server NIC egress for remote live viewers equals the client-side 3.0 Mbit/s plus TCP/TLS overhead (not measured). Frame rate not recorded in this run.
Feeds: VI-B (replaces the fps-only sentence) and the access argument in Section I.
