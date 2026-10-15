# D6 CoreDLA latency on the DE25-Nano (2026-10-15; D6-dla-resnet18/runs.csv, D6-dla-resnet50/runs.csv; script run_D6dla.py, timer dla_bench/dla_bench.cpp)
Same method as the CPU baseline (D6-cpu-summary.md): C++ timer around one synchronous batch-1 infer() on a fixed random FP32 input, 20 warm-ups discarded, 150 timed runs, steady_clock, dla-server stopped during the run (restarted afterwards, active, 0 FATAL since). Graph imported as in dla-server (HETERO:FPGA,CPU; leading device name, then blob), arch AGX5_Small_k16c16_sb20480 (same file for both graphs), fabric = the CoreDLA design already loaded. ResNet-18 = fruit-v1 graph.bin, ResNet-50 = my-flags graph.bin (same files as the CPU IRs). Includes host-to-FPGA transfer and the CPU-side Softmax, as the live system does.
Cross-check: vendor `dla_benchmark -api sync -niter 20` on the flag (ResNet-18) graph reported mean latency 90.6 ms, IP duration 839.6 ms/20 = 42.0 ms per inference on the accelerator alone, 100 MHz.

| model | device | n | median ms | p95 ms | mean ms | SD ms | min | max | img/s (1/mean) |
|---|---|---|---|---|---|---|---|---|---|
| ResNet-18 | CoreDLA | 150 | 90.8 | 91.0 | 90.9 | 0.11 | 90.7 | 91.6 | 11.0 |
| ResNet-50 | CoreDLA | 150 | 235.9 | 236.4 | 235.9 | 0.25 | 235.6 | 237.3 | 4.24 |
| ResNet-18 | A76 1 thread (D6-cpu) | 150 | 104.4 | 109.7 | 105.0 | 2.0 | | | 9.52 |
| ResNet-50 | A76 1 thread (D6-cpu) | 150 | 314.0 | 320.2 | 314.8 | 2.7 | | | 3.18 |

Speed-up of CoreDLA over the A76 (median): ResNet-18 104.4/90.8 = 1.15x; ResNet-50 314.0/235.9 = 1.33x. The earlier "97 ms / 239 ms" (bake-off, different timer, no spread) is superseded; the live camera pipeline classifies about 9 times per second (also includes camera, resize and JPEG).
Feeds: Table V, VI-B, abstract ("no faster" -> "1.15 times faster"), VII-A, Conclusion.
