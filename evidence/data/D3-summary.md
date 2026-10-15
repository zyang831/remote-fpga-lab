# D3 stage breakdown (2026-10-15; generated tables in D3-model/summary_stages.md and D3-bit/summary_stages.md)
Method: per run, PC phase events (backend status poll 0.1 s) + board journal markers (Mender client, kernel, systemd, dla-server), board clock offset +0.009 s subtracted. n=10 per type, 1 flagged warm-up each, 0 failures. Model: alternating fruit/flag (~60 MB graph). Bitstream: led-bouncing/led-johnson/ghrd (1.5-1.7 MB).
"First inference" was not measured separately: dla-server "ready" (graph imported, input accepted) is the last marker; the camera loop starts about 0.2 s later.

## Model switch, median seconds since request (total 25.3 s, range 23.0-30.8)
request->deployment created 0.6 | ->client picks up 3.0 (poll wait, 5 s poll) | ->install script starts 7.9 (artifact download ~5 s) | ->old overlay removed 10.0 | ->fabric reprogrammed 11.8 | ->drivers loaded 13.2 | ->dla-server started 15.1 | ->ready 23.0 (graph import 6-17 s) | ->Mender finished 24.3 | ->backend sees ok 25.3.
Shares of the median total: delivery to board (request->install start) 31%; unbind/reprogram/drivers (install start->drivers) 21%; dla-server start + graph import (->ready) 31%; Mender finish + status 6%+4%.
Verdict on "import dominates": NOT supported. Graph import is the largest single stage (srv_started->ready median 6.8 s, up to 17 s) but about a quarter of the total; delivery (poll wait + 60 MB download) and fabric/driver reconfiguration are of similar size. Reword to "no single stage dominates; import is the largest".
Variable stage: install start->old overlay removed (0.6-9.4 s) = waiting for dla-server to stop/unbind.

## Bitstream (student LED design), median seconds since request (total 8.6 s, range 4.6-10.7)
created 0.5 | client pickup 4.0 (0.5-5.4: poll wait is uniform up to the 5 s poll interval) | fabric write 4.6 (pickup->write 0.56 s) | Mender finished 7.2 (fabric write->finished 2.66 s, constant) | ok 8.6.
So 4.0 of 8.6 s is waiting for the client's next poll; the programming itself is about 0.6 s of install work. This explains the near-quantised D2 times (7.0 / 9.1-9.3 s). Lowering UpdatePollIntervalSeconds would cut the median proportionally (not tested).

Caveats: dla-server unit "Started" can precede driver "probe success" (drivers_loaded and srv_started swap in 3 of 10 runs); cumulative table is the reliable one. Backend phase labels lag the board by about 1 s. Direct cable, Mender via Tailscale direct path.
Feeds: new stage table / stacked bar in VI-A; replaces the two-run argument.
