# D6 CPU baseline on the DE25-Nano HPS (2026-10-15; generated from D6-cpu-*/runs.csv)

OpenVINO 2024.6 ARM CPU plugin, FP32 IR, batch 1, sync infer, random input, 20 warm-up + 150 timed runs per row, `taskset` pinned (A76 = cpu2-3, A55 = cpu0-1), dla-server stopped during the runs (restarted after), PERFORMANCE_MODE=LATENCY. ResNet-18 = fruit-v1 IR, ResNet-50 = my-flags IR (latency independent of weights). Timer: evidence/cpu_bench (C++, cross-compiled; vendor dla_benchmark cannot run CPU models: runtime built without JIT). No cpufreq governor exposed on the board; power not measured (no sensor found).

| model | core | threads | n | median ms | p95 ms | mean ms | SD ms | img/s (1/mean) |
|---|---|---|---|---|---|---|---|---|
| resnet18 | A55 | 1 | 150 | 380.3 | 391.7 | 381.9 | 3.9 | 2.62 |
| resnet18 | A55 | 2 | 150 | 330.5 | 338.0 | 331.3 | 2.7 | 3.02 |
| resnet18 | A76 | 1 | 150 | 104.4 | 109.7 | 105.0 | 2.0 | 9.52 |
| resnet18 | A76 | 2 | 150 | 104.0 | 108.2 | 104.4 | 1.7 | 9.58 |
| resnet50 | A55 | 1 | 150 | 1530.6 | 1560.8 | 1535.2 | 13.2 | 0.65 |
| resnet50 | A55 | 2 | 150 | 1315.3 | 1335.0 | 1318.8 | 8.4 | 0.76 |
| resnet50 | A76 | 1 | 150 | 314.0 | 320.2 | 314.8 | 2.7 | 3.18 |
| resnet50 | A76 | 2 | 150 | 315.1 | 321.4 | 315.6 | 2.0 | 3.17 |

Observation: a second thread gives no speed-up on A76 (ARM plugin ran effectively single-threaded); A55 gains ~13% with 2 threads. Compare with FPGA latency from Table V (CoreDLA, same ResNet-18) when writing V-B. Licence note: see availability.md (AI Suite s.4(a)(v)); user clearing with Altera supervisor.
