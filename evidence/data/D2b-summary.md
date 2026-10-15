# D2b: deployment time with random inter-run gaps (2026-10-15; D2b-bit/runs.csv, D2b-model/runs.csv; script run_D2b.py)
Why: D2 spaced runs by 1 s, so each request hit the same phase of the board's 5 s Mender poll (21 of 24 bitstream runs at 9.0-9.3 s). D2b draws the gap before every run from uniform(0, 5) s (random.seed(1); gap values in D2b-bit.out / D2b-model.out), so the poll phase is random. Same backend API, same six bitstreams, same alternating flag/fruit models, 1 warm-up discarded, direct Ethernet link, board healthy before (dla-server active). Journal follower on the board during both series (D2b-journal-follow.txt): 0 FATAL lines; `FATAL` count since the repair (2026-10-15 06:14 UTC) also 0.

| series | n | ok | median s | mean s | SD s | min s | max s | p95 s |
|---|---|---|---|---|---|---|---|---|
| D2b bitstream (6 designs) | 24 | 24 | 7.05 | 7.30 | 1.81 | 4.28 | 10.82 | 9.07 |
| D2b model switch | 40 | 40 | 27.18 | 27.88 | 3.74 | 22.94 | 37.79 | 35.47 |
| D2 bitstream (1 s gap, phase-locked) | 24 | 24 | 9.31 | 8.96 | 0.75 | 7.04 | 9.32 | 9.32 |
| D2 model switch (1 s gap) | 40 | 40 | 27.21 | 27.69 | 3.89 | 23.18 | 37.79 | 35.74 |
| D3 bitstream (5 s gap, stage run) | 10 | 10 | 8.62 | 7.49 | 2.20 | 4.56 | 10.75 | 8.83 |

Exact one-sided 95% lower limit on success: 24/24 -> 88.3%; 40/40 -> 92.8%.
Findings: bitstream deployment varies 4.3-10.8 s (poll phase); the earlier 7.0-9.3 s understated the spread. Model switch unchanged (22.9-37.8 s, median 27.2): the 2 s grid does not matter. Longest operation in any series stays 45 s (own-model upload, 3 Oct). R3 (< 60 s) met in all runs.
Paper: Table III rows 1-2, abstract, VI-A, VII-A, Conclusion, Table I "This work".
