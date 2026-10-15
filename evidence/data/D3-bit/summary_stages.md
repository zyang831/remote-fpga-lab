# D3 bit stage medians (n=10 ok runs, warm-up excluded; generated)

| stage | n | median s | mean | min | max |
|---|---|---|---|---|---|
| t_request -> t_created | 10 | 0.52 | 0.53 | 0.42 | 0.61 |
| t_created -> pickup | 10 | 3.53 | 2.63 | 0.01 | 4.87 |
| pickup -> fabric_write | 10 | 0.56 | 0.59 | 0.47 | 0.77 |
| fabric_write -> finished | 10 | 2.66 | 2.65 | 2.58 | 2.73 |
| finished -> t_ok | 10 | 0.92 | 1.10 | 0.16 | 2.15 |

Total request->ok: median 8.62, mean 7.49, min 4.56, max 10.75

Cumulative seconds since request (median [min-max]); markers can swap order (drivers_loaded vs srv_started: dla-server unit starts while drivers load), so read this table, not the consecutive diffs, for those two:

| marker | n | median | min | max |
|---|---|---|---|---|
| t_created | 10 | 0.5 | 0.4 | 0.6 |
| pickup | 10 | 4.0 | 0.5 | 5.4 |
| fabric_write | 10 | 4.6 | 1.0 | 5.9 |
| finished | 10 | 7.2 | 3.7 | 8.6 |
| t_ok | 10 | 8.6 | 4.6 | 10.7 |
