# D8 failure repeats (2026-10-15; D8-graphcut, D8-release, D8-stall; script ../run_D8.py)
Setup: direct cable, Mender via Tailscale, board on fruit (15 classes) before each test. Resolution 0.5 s (graph cut) / 0.5 s (state poll over a multiplexed ssh).

## Graph-cut model (flag/fruit graph.bin truncated to 1 MiB), deployed through Mender, n=5
Deployment status `failure` after: n=5 median 12.9, mean 12.1, SD 1.4, min 9.6, max 12.9 s (from deployment creation). Statistics each time: failure 1, success 0. Device phases: pending/downloading/installing then failure; install step ran about 8-11 s before the module reported failure.
Previous model (fruit) serving again (`dla-server` active, ready file, model name fruit) n=5 median 6.4, mean 8.0, SD 3.9, min 5.6, max 14.9 s after the failure status (the module's rollback restarts dla-server and re-imports the graph). 5/5 recovered with no manual action; exact one-sided 95% bound on failure-to-recover 45% (n small).
Note: the earlier single trial gave 14.3 s to failure; 5 repeats: 9.6-12.9 s.

## Release after own bitstream (ghrd.core.rbf programmed, then POST /session/finish), n=10
Classifier back (dla-server active + ready + fruit model) n=10 median 13.4, mean 14.8, SD 3.6, min 11.9, max 22.6 s after release. 10/10 recovered, bound 26%. While the own bitstream was loaded, dla-server was inactive in 10/10 (classifier down as designed). The release artifact is the 5,120-byte restore marker (no model download), so the time is the idle-design reprogram + dla-server start + graph import. The earlier two-run measurement with the same restore artifact (26.1 and 25.6 s, 2026-10-03, OTA_HARDENING_PLAN Step 7) is not reproduced: median is now 13.4 s. Difference unexplained (the Oct 3 runs were taken on a board whose dla-server was later found crash-looping; a different measurement end point is also possible). Use the new n=10.
Spread note: two slow runs (19.8, 22.6 s) with no failures; cause not examined.

## Stalled download (tc tbf 64 kbit/s on eno1 during a 60 MB model deployment), n=1
Device went pending (4.2 s after creation) and downloading (5.2 s); the board kept serving the old model throughout the stall (active ready fruit). After 90 s the deployment was aborted through the API (the call the backend makes after its own 900 s timeout; not waited here) and the throttle removed. Board client log: abort noticed at its next status update ("Deployment was aborted on the server"), deployment finished with status Failure locally about 10 s after the abort; Mender device status `aborted`. The old model was never interrupted (2.2 s state check), and the next two normal switches succeeded (flag 26.7 s, fruit 35.7 s). Throttle removed afterwards (qdisc back to fq_codel).
Caveats: single trial; the 900 s backend timeout and the board's 600 s module timeout were not waited out (abort at 90 s); the throttle also slowed the Tailscale control traffic, which is why `pending` took 4.2 s.
Feeds: Table IV failure rows and the "Two failure cases" paragraph.
