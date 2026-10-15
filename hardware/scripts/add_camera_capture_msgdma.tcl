# Option B camera capture path: replaces the licensed-but-unavailable VVP ISP
# (demosaic/pip_conv/pixel_adapter/vfb, IP-VVP eval-only) with a plain mSGDMA
# in Streaming-to-Memory-Mapped mode, writing the raw CSI-2 Bayer stream
# straight to a DDR ring buffer. Debayer/resize/normalize move to software on
# the HPS. Run add_camera_frontend.tcl first.
#
# csi2_dphy_sys_0 exports its CSI-2 RX output as AXI4-Stream (tdata[63:0],
# tvalid, tready, tlast, tuser[7:0] -- confirmed from csi2_dphy_sys_bb.v, no
# tkeep/tid/tdest wires). altera_msgdma's ST sink is Avalon-ST, so a generic
# altera/axi_st/axist_to_avst_adapter bridges the two -- unlicensed, no
# device restriction, distinct from the VVP-suite "video" cores.
#
# tuser (frame-start marker) is dropped at the bridge (USE_TUSER 0) rather
# than folded into the data path: folding it in would make the Avalon-ST data
# word 64+8=72 bits, which isn't in altera_msgdma's DATA_WIDTH ALLOWED_RANGES
# {8 16 32 64 128 256 ...}. Framing is recovered in software instead: cam_msgdma
# runs in plain (non-packet) mode with one fixed-length descriptor per frame
# (frame_bytes known from sensor resolution), so each descriptor lands exactly
# one frame at a fixed ring-buffer stride -- no on-wire frame marker needed.
#
#   qsys-script --script=add_camera_capture_msgdma.tcl

package require -exact qsys 25.3

load_system qsys_top.qsys

add_instance cam_axi2avst axist_to_avst_adapter
set_instance_parameter_value cam_axi2avst {NUM_OF_TRANSMITTERS} {1}
set_instance_parameter_value cam_axi2avst {AXI_TDATA_WIDTH} {64}
set_instance_parameter_value cam_axi2avst {USE_TLAST} {1}
set_instance_parameter_value cam_axi2avst {USE_TUSER} {0}
set_instance_parameter_value cam_axi2avst {USE_TID} {0}
set_instance_parameter_value cam_axi2avst {USE_TKEEP} {0}
set_instance_parameter_value cam_axi2avst {CONNECTIVITY_TYPE} {2}

add_instance cam_msgdma altera_msgdma

# Streaming to Memory-Mapped: raw byte stream in, write-only MM master out.
set_instance_parameter_value cam_msgdma {MODE} {2}
set_instance_parameter_value cam_msgdma {DATA_WIDTH} {64}
set_instance_parameter_value cam_msgdma {ENHANCED_FEATURES} {1}
set_instance_parameter_value cam_msgdma {RESPONSE_PORT} {2}

# Same reasoning as coredla_msgdma (add_coredla_msgdma.tcl): this master is
# bridged to the AXI4 f2sdram subordinate, and AXI forbids a burst crossing a
# 4 KB boundary while Avalon has no such rule -- keep bursting off.
set_instance_parameter_value cam_msgdma {BURST_ENABLE} {0}
set_instance_parameter_value cam_msgdma {STRIDE_ENABLE} {0}
set_instance_parameter_value cam_msgdma {MAX_BYTE} {2147483647}
set_instance_parameter_value cam_msgdma {DATA_FIFO_DEPTH} {64}
set_instance_parameter_value cam_msgdma {DESCRIPTOR_FIFO_DEPTH} {128}
set_instance_parameter_value cam_msgdma {TRANSFER_TYPE} {Unaligned Accesses}

# Clocks: single 100 MHz domain, same as the rest of qsys_top.
add_connection clk_100.out_clk cam_axi2avst.clk
add_connection clk_100.out_clk cam_msgdma.clock
add_connection rst_in.out_reset cam_msgdma.reset_n

# Data plane: csi2_dphy_sys_0's AXI4-Stream video output -> bridge -> mSGDMA
# streaming sink -> f2sdram (same path coredla_msgdma and, before it, vvp's
# vfb used -- shared arbitrated slave, baseAddress 0 = identity-mapped DDR).
add_connection csi2_dphy_sys_0.csi2_rx_video_streaming_interface_0 cam_axi2avst.snk
add_connection cam_axi2avst.src cam_msgdma.st_sink

add_connection cam_msgdma.mm_write subsys_hps.f2sdram_adapter_axi4_sub
set_connection_parameter_value \
    cam_msgdma.mm_write/subsys_hps.f2sdram_adapter_axi4_sub \
    baseAddress {0x0000000000000000}

# Control plane: reuse the address slot vvp_system's mm_bridge_control_s0
# used (0x00023000), now free.
add_connection subsys_hps.lwhps2fpga cam_msgdma.descriptor_slave
set_connection_parameter_value \
    subsys_hps.lwhps2fpga/cam_msgdma.descriptor_slave \
    baseAddress {0x00023000}
add_connection subsys_hps.lwhps2fpga cam_msgdma.csr
set_connection_parameter_value \
    subsys_hps.lwhps2fpga/cam_msgdma.csr \
    baseAddress {0x00023020}

# Line 3 is coredla_msgdma's csr_irq; next free line.
add_connection subsys_hps.f2h_irq0_in cam_msgdma.csr_irq
set_connection_parameter_value \
    subsys_hps.f2h_irq0_in/cam_msgdma.csr_irq irqNumber {4}

save_system
