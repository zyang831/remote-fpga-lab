# D2 bitstream programming, 6 designs (generated from runs.csv, 2026-10-15)
n=24 (+1 flagged warm-up 11.4 s excluded), 4 runs per design, failures 0, exact one-sided 95% failure bound 11.7%.
All: median 9.3 s, mean 9.0, SD 0.75, min 7.0, max 9.3. Designs (sha256 in runs.csv): led-bouncing, led-johnson, ghrd, edge-ai-dla (CoreDLA, 3.6 MB), CoreDLA_NoSoftmax, CoreDLA_Softmax.
Note: times are nearly quantised (21 of 24 at 9.0-9.3 s, 3 at 7.0 s); consistent with the board's 5 s Mender poll interval plus fixed install steps. Stage table (ticket 03) should confirm.
Feeds: Table IV (bitstream row: now 6 designs, n=24 vs earlier 3 designs), VI-A. Under the 60 s bar.
Combined n=64 runs, 0 failures: bound 4.6% (compute if pooled claim wanted).
