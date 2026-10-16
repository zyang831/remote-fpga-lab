# D15: own-model upload to live, re-run (2026-10-16, 13:34-13:43 local; D15-ownmodel/runs.csv, D15-ownmodel.out; script run_D15.py)
Method as MEASURE_VI.md line 6: fruit-v1 IR (model.xml, model.bin, categories.txt), unique names d15-*, POST upload until /session/model reports the new name, backend API as the web page, server clock; random 0-5 s gap (seed 1), 1 warm-up discarded (41.7 s). Direct Ethernet (Tailscale direct 10.42.0.127; Wi-Fi dongle also attached but unused). Board healthy before (dla-server active). Journal follower on the board for the whole series: D15-ownmodel/journal-follow.txt, 0 FATAL / "did not complete" lines.

| series | n | ok | median s | mean s | SD s | min s | max s | 95% lower limit on success |
|---|---|---|---|---|---|---|---|---|
| D15 own model, upload to live (16 Oct) | 10 | 10 | 33.6 | 35.4 | 4.9 | 29.3 | 44.7 | 74.1% |
| earlier series (3 Oct, crash day, no journal) | 10 | 10 | 31.5 | 32.6 | n/a | 29.0 | 45.4 | n/a |

Result: reproduced. Range 29.3-44.7 s (old 29-45), median 33.6 s (old 31.5), no crash during the series, R3 (< 60 s) met. Longest operation 44.7 s.
Cleanup: board switched to fruit at the end (confirmed live: fruit, dla-server active); test models deleted via the API (d15-28760 left over from the aborted run deleted separately: 200).
Aborted attempt (data/D15-aborted/): a hung shell command launched the series twice, so two copies ran concurrently for 2 rows (35.6 s, 35.4 s, ok) before both were stopped (SIGINT, cleanups ran); those rows are NOT in the D15 series. A second restart-count scan was cancelled.
Paper: abstract, Introduction (29--45 s still holds), Table IV row 3 (n = 10, 29--45 s, median 33.6, mean 35.4), VI-A ("dates from an earlier day" sentence out), VII-A, VII-C (exception clause out), Conclusion.
