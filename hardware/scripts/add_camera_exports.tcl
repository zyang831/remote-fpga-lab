# Top-level exports for the camera pins. Conduits from a sub-instance are not
# auto-exported -- without these the D-PHY lanes, OCT reference and sensor I2C
# pads generate cleanly but never reach an FPGA pin. Names match the working
# project (Unused/CoreDLA_GHRD) so golden_top.v's port list is unchanged.
# CLOCK0_50_mipi_ref (the fifth export) is already in place.
#
#   qsys-script --quartus-project=golden_top --rev=golden_top \
#       --search-path="custom_ip/cam_axi4s_tuser_strip,$" \
#       --script=add_camera_exports.tcl

package require -exact qsys 25.3

load_system qsys_top.qsys

add_interface CAM_mipi_dphy_LINK0_dphy_io conduit end
set_interface_property CAM_mipi_dphy_LINK0_dphy_io EXPORT_OF \
    csi2_dphy_sys_0.mipi_dphy_LINK0_dphy_io

add_interface CAM_mipi_dphy_rzq conduit end
set_interface_property CAM_mipi_dphy_rzq EXPORT_OF csi2_dphy_sys_0.mipi_dphy_rzq

# Debug/observation bus on the D-PHY; reg_dout_i is tied off in golden_top.v.
add_interface mipi_dphy_reg_bus_unused conduit end
set_interface_property mipi_dphy_reg_bus_unused EXPORT_OF \
    csi2_dphy_sys_0.mipi_dphy_reg_bus

add_interface CAM_I2C_pads conduit end
set_interface_property CAM_I2C_pads EXPORT_OF cam_i2c_master.i2c_serial

save_system
