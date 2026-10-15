# Section VI re-measure (2026-10-03)

Script: `notes/measure_VI.py` (`python3 measure_VI.py bit 20`, `up 10`). Board on direct Ethernet to the lab PC; backend API as the web page uses it; client wall clock, 0.25-s poll.

- Student bitstream (led-bouncing, led-johnson, ghrd, cycled), n=20: 8.6/9.3/9.1 in a 3-run trial, then 20 runs 7.0-9.7 s, mean 8.9, median 9.3; 20/20 ok. Artifact sizes (mender-artifact, my_overlay.dtb): 1,506,816 / 1,500,672 / 1,395,712 B.
- Own-model upload (fruit-v1 IR, unique names), upload to live, n=10: 45.4, 31.8, 31.8, 30.0, 31.0, 31.1, 31.7, 29.0, 32.8, 31.3 s; mean 32.6, median 31.5.
- Discarded: a release probe polling /session/model (answers ~1 s after finish while the classifier is down).
- Cleanup: 10 meas-* models (IR, build, Mender artifacts) deleted via API, 26 test RBFs removed from uploads/, board back on fruit.

## JTAG baseline (2026-10-03, for VII-B)

`quartus_pgm -c "DE25-Nano [1-11]" -m jtag -o "p;golden_top_hps_auto.sof"` (3.33 MB, the CoreDLA reference design `~/quartus_projects/_ref_build_de25_camera_dla/CoreDLA_GHRD/output_files/`; plain `golden_top.sof` is refused: "HPS is present but bootloader information is missing"). Programmer operation 2 s in each of 3 successful runs (log has 1-s resolution; 16:17:08-10, 16:22:27-29, 16:24:15-17); whole tool invocation 36 s (about 34 s is tool startup, including the probe of a configured remote JTAG server). One attempt failed with "Can't scan JTAG chain" right after a reboot (retry worked). Each successful JTAG configuration reset the HPS: ssh and dla-server came back on their own, 35 s after the programming ended (n=1 timed precisely; the first run needed about 1 min by coarse polling). Board back on fruit, fpga0 operating, no power cycle needed. The OTA student bitstreams are fabric-only `.core.rbf` files; a JTAG `.sof` is a whole-chip file for an HPS-first design, so the two are not the same payload.
