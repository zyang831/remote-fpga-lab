# D3 model stage medians (n=10 ok runs, warm-up excluded; generated)

| stage | n | median s | mean | min | max |
|---|---|---|---|---|---|
| t_request -> t_created | 10 | 0.61 | 0.59 | 0.21 | 0.82 |
| t_created -> pickup | 10 | 2.31 | 2.24 | 1.25 | 3.74 |
| pickup -> install_start | 10 | 5.16 | 5.12 | 4.57 | 5.88 |
| install_start -> overlay_removed | 10 | 1.80 | 2.63 | 0.58 | 9.37 |
| overlay_removed -> fabric_write | 10 | 0.28 | 1.25 | 0.00 | 4.06 |
| fabric_write -> drivers_loaded | 10 | 1.32 | 2.16 | 0.01 | 7.58 |
| drivers_loaded -> srv_started | 10 | 1.22 | 0.87 | -5.18 | 4.11 |
| srv_started -> srv_ready | 10 | 6.80 | 8.56 | 5.95 | 17.13 |
| srv_ready -> finished | 10 | 1.05 | 1.18 | 0.92 | 1.71 |
| finished -> t_ok | 10 | 0.94 | 1.07 | 0.56 | 2.06 |

Total request->ok: median 25.28, mean 25.68, min 23.03, max 30.79

Cumulative seconds since request (median [min-max]); markers can swap order (drivers_loaded vs srv_started: dla-server unit starts while drivers load), so read this table, not the consecutive diffs, for those two:

| marker | n | median | min | max |
|---|---|---|---|---|
| t_created | 10 | 0.6 | 0.2 | 0.8 |
| pickup | 10 | 3.0 | 1.5 | 4.0 |
| install_start | 10 | 7.9 | 6.0 | 9.3 |
| overlay_removed | 10 | 10.0 | 7.0 | 17.9 |
| fabric_write | 10 | 11.8 | 7.1 | 18.5 |
| drivers_loaded | 10 | 13.2 | 10.8 | 18.5 |
| srv_started | 10 | 15.1 | 12.0 | 18.8 |
| srv_ready | 10 | 23.0 | 21.0 | 29.2 |
| finished | 10 | 24.3 | 22.1 | 30.2 |
| t_ok | 10 | 25.3 | 23.0 | 30.8 |
