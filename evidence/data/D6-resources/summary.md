# D6 resources (Ticket 05, resource part only; CPU baseline NOT done, needs board)

Collected 2026-10-15, desk reads only.

## Which design
Deployed design = _ref_build, arch AGX5_Small_k16c16_sb20480. Evidence: board /lib/firmware rbf sha256 f1e4ab4d... = `/home/<user>/quartus_projects/_ref_build_de25_camera_dla/phase4/build_AGX5_Small_k16c16_sb20480/AGX5_Small_k16c16_sb20480.core.rbf` (sha256 f1e4ab4d29fd4a41ccad5dcaceeedd149cebed397127b5be3cb8341c9fa46cde, 3,747,840 B, 2026-09-22; board hash from legacy/WHY_LEGACY.md and docs/DECISIONS.md, not re-checked on board).
The phase4 `golden_top.fit.summary` and `golden_top.sta.summary` are byte-identical (cmp) to the copies in `/home/<user>/quartus_projects/_ref_build_de25_camera_dla/CoreDLA_GHRD/output_files/`, so all numbers below apply to the deployed design. Device: Agilex 5 A5EB013BB23BE4SCS, Quartus Prime Pro 25.3.1 Build 100, fit finished Tue 2026-09-22 16:20:07.
Scope caveat: numbers are for the WHOLE top (golden_top: HPS subsystem, MIPI/camera, msgDMA, CoreDLA), not the DLA alone. DLA-only hierarchy split not extracted.

## Numbers
Report dir O = `/home/<user>/quartus_projects/_ref_build_de25_camera_dla/CoreDLA_GHRD/output_files/` (all files dated 2026-09-22 16:20).

| Item | Used / available | Source |
|---|---|---|
| ALMs (logic utilization, needed) | 41,576 / 46,800 (89 %) | O/golden_top.fit.summary; O/golden_top.fit.rpt line 116 |
| ALMs used in final placement | 43,462.5 / 46,800 (92 %) | O/golden_top.fit.rpt line 7466 |
| Dedicated logic registers | 92,411 (fit.summary); 88,404 / 187,200 (47 %) in fit.rpt resource table | O/golden_top.fit.summary; fit.rpt line 7471 (figures differ; report both or use 88,404/187,200 with its denominator) |
| DSP blocks | 32 / 188 (17 %) | O/golden_top.fit.summary line 121; fit.rpt line 7475 |
| M20K RAM blocks | 355 / 358 (99 %) | O/golden_top.fit.summary ("Total RAM Blocks"); fit.rpt line 7474 |
| Block memory bits | 5,514,932 / 7,331,840 (75 %) | O/golden_top.fit.summary |
| PLLs | 3 / 11 | O/golden_top.fit.summary |

## Clock / fmax
- DLA clock: 100 MHz, shared. `coredla_work/de25_coredla_release/RUNBOOK.md` line 60: dla_clk/ddr_clk/irq_clk -> clk_100 ("the DLA gets no PLL of its own"); line 351 `dla_mmd_get_ml_frequency()` returns 100; line 4 and 570: measured "IP clock frequency 100.0000 MHz". RUNBOOK file dated 2026-08-20, i.e. measured on the earlier CoreDLA_GHRD bring-up, not re-measured on the 09-22 camera build. In golden_top.v, `pll_inst.outclk_0` drives `system_clk_100_internal` which feeds `soc_inst.clk_100_clk`.
- STA Fmax (O/golden_top.sta.rpt, "Fmax Summary", line ~721, 2026-09-22): `pll_inst|iopll_0_outclk0` 111.21 MHz (Slow fix4a 0C). Setup slack on that clock +1.008 ns (O/golden_top.sta.summary). That clock is the 100 MHz system clock by wiring; the sta report names only the PLL output, so the clk_100 = outclk0 mapping is inferred, not stated by the tool. Other domains: MIPI_FWD_CLK 141.32 MHz, mipi CORE_CLK 260.42 MHz, JTAG 20.12 MHz.
- All setup/hold/recovery/removal slacks non-negative (sta.summary): timing met at 100 MHz, margin ~11 % (111.21 vs 100).

## Power
No power estimate exists. No Power Analyzer report in output_files (grep: only the setting POWER_APPLY_THERMAL_MARGIN in flow.rpt). Board power sensor not queried (not allowed). Paper text: "not measured". Option for the human: run Quartus power analysis on the existing fit (CPU-light, no board) if a number is wanted.

## Open for the board session
CPU baseline (ResNet-18/50, A76) untouched. Ticket 05 box 2 (Quartus numbers) is satisfied by the table above; boxes 1 and 3 are not.
