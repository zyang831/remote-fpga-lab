# Adds the licensed camera front end (MIPI D-PHY + CSI-2 RX + sensor I2C
# master) to qsys_top, unchanged from the proven working project
# (Unused/CoreDLA_GHRD, compiled 2026-08-27: 0 errors, timing met, 96% ALM).
# This is the front end shared by all three camera-pipeline options; only the
# post-CSI2 ISP block (added separately, see add_camera_capture_msgdma.tcl)
# differs for the Option B (no-VVP) rebuild.
#
#   qsys-script --script=add_camera_frontend.tcl

package require -exact qsys 25.3

load_system qsys_top.qsys

# csi2_dphy_sys is itself a Platform Designer system-as-component; its .qsys
# and generated ip/csi2_dphy_sys/* sub-IP were copied verbatim from the
# working project, so it resolves via the local IP search path unchanged.
add_instance csi2_dphy_sys_0 csi2_dphy_sys

add_instance cam_i2c_master altera_avalon_i2c
set_instance_parameter_value cam_i2c_master {USE_AV_ST} {0}
set_instance_parameter_value cam_i2c_master {FIFO_DEPTH} {4}
set_instance_parameter_value cam_i2c_master {clockRate} {100000000}

# Clocks/resets: everything on the single 100 MHz domain, same as the rest of
# qsys_top.
add_connection clk_100.out_clk csi2_dphy_sys_0.rx_axi4s_clk_bridge_in_clk
add_connection clk_100.out_clk cam_i2c_master.clock
add_connection rst_in.out_reset csi2_dphy_sys_0.reset_n_bridge_in_reset
add_connection rst_in.out_reset cam_i2c_master.reset_sink

# Control plane: both csi2_dphy_sys control interfaces + cam_i2c_master CSR
# on the HPS lightweight bridge, at the same offsets as the working project.
add_connection subsys_hps.lwhps2fpga csi2_dphy_sys_0.csi2_rx_avalon_mm_control_interface
set_connection_parameter_value \
    subsys_hps.lwhps2fpga/csi2_dphy_sys_0.csi2_rx_avalon_mm_control_interface \
    baseAddress {0x00022000}

add_connection subsys_hps.lwhps2fpga csi2_dphy_sys_0.mipi_dphy_axi_lite
set_connection_parameter_value \
    subsys_hps.lwhps2fpga/csi2_dphy_sys_0.mipi_dphy_axi_lite \
    baseAddress {0x00024000}

add_connection subsys_hps.lwhps2fpga cam_i2c_master.csr
set_connection_parameter_value \
    subsys_hps.lwhps2fpga/cam_i2c_master.csr \
    baseAddress {0x00025000}

save_system
