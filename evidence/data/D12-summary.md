# D12 server load with simulated devices (2026-10-15; D12-load/runs.csv, samples.csv; script ../run_D12.py)
No second DE25-Nano was available, so this is a SIMULATION: N software devices (own RSA key, device-auth request, accepted via the management API, then GET /deployments/next every 5 s with phase spread, like the real client) poll the Mender server while the one REAL board performs 4 model switches (fruit<->flag) per level. Server load = `docker stats` of all Mender containers on the lab PC (i9-14900K, 32 threads), sampled each ~1 s. Simulated devices never receive a deployment (device type sim-board) and were decommissioned afterwards (500/500).

| simulated devices | polls/s offered | n switches | switch median s | mean | range s | server CPU median (sum of container %, 1 core=100%) | max | server RAM MiB |
|---|---|---|---|---|---|---|---|---|
| 0 | 0 | 4 | 25.4 | 25.8 | 22.9-29.4 | 2.8 | 28.3 | 1388 |
| 50 | 10 | 4 | 28.4 | 28.8 | 22.9-35.7 | 5.7 | 32.3 | 1433 |
| 200 | 40 | 4 | 24.4 | 25.5 | 23.4-29.7 | 13.2 | 47.1 | 1437 |
| 500 | 100 | 4 | 26.5 | 26.8 | 20.9-33.4 | 24.9 | 53.4 | 1461 |

Poll latency from the simulated devices: median 4-5 ms, p95 5-9 ms, 0 errors in 27,357 polls (50/200/500 devices: 1,393 / 6,422 / 19,542 polls).
Findings: server CPU grows roughly linearly with device count (median sum of container CPU 2.8% of one core with none, 24.9% with 500 devices polling at 100 requests/s, about 22 points per 100 requests/s) and stays far below the machine's 32 threads; memory is flat (1.39 -> 1.46 GiB); the real board's switch time shows no systematic change (medians within the D2 spread of 23-38 s). So one lab PC is not the bottleneck at the scale of a lab (hundreds of polling devices). Not tested: simultaneous deployments to many devices (download load, s3/seaweedfs and bandwidth), real concurrent boards, the single-session lab backend queue (one student at a time by design).
Caveats: simulated clients do not download artifacts or send inventory; n=4 switches per level, so the switch-time comparison is weak evidence of no effect; load sampler adds docker stats CPU (~a few %).
Feeds: VII-C (limits) with the simulation labelled as such.
