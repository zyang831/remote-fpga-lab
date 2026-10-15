# D5 flag mismatches (2026-10-15; board.csv, cpu_cv.csv, cpu_pil.csv, per_image_cv.csv, per_image_pil.csv; script ../../analyze_flags.py)
Set: 110 flag images (31 classes), ground truth = filename prefix. Board: flag model live, 110 inferences via the dla-server inbox, per-image top-5. CPU: OpenVINO 2024.6 FP32 on the PC, same IR.
Two CPU references: `cv` = board's preprocessing re-implemented (centre square crop, cv2 INTER_LINEAR resize, no antialias, from dla-server/main.cpp); `pil` = the training-side PIL BILINEAR resize (antialiased) used for the original reference. Note: `cv` re-implements the board's preprocessing in code, it is not a tensor dump taken from the board.

| comparison | agree | mismatches | near-tie (margin<0.10) | real |
|---|---|---|---|---|
| board vs CPU-cv | 109/110 | 1 (australia_00, margins 0.014/0.007) | 1 | 0 |
| board vs CPU-pil | 101/110 | 9 | 6 | 3 (australia_02, brazil_02, switzerland_00) |

Top-1 vs ground truth: board 0.718 (79/110), CPU-cv 0.709, CPU-pil 0.782.

Finding: 8 of the 9 "flag mismatches" (101/110 agreement) vanish when the CPU reference uses the board's resize. The 9 were mainly a preprocessing difference between training/reference code and the board runtime (antialiased PIL downscale vs plain bilinear), not FPGA arithmetic. The one remaining difference is a near-tie (FP16 vs FP32 plausible). Board and CPU accuracy are equal within one image when preprocessing matches.
Implication for the paper: the board's 71.8% vs the reference 78.2% is a real accuracy loss (-6.4 points, 7 images) caused by the board's cheaper resize, not by the accelerator. Fix option (not done): antialiased downscale on the board; would restore reference accuracy. Precision (FP16 vs FP32) effect measured at 1/110 images.
Feeds: Table V rows and VI-B; remove "not examined" in VI-B and VII-C.
Caveat: FP16 vs FP32 not separated by a controlled FP16 CPU run; resize method not varied beyond these two variants.
