# Follow-up fixes after the first qsys-generate attempt on
# add_camera_capture_msgdma.tcl surfaced 4 real issues:
#  - cam_axi2avst.clk_reset (auto-split from the "clk" clock interface's
#    bundled reset_n port) was never connected to a reset source.
#  - csi2_dphy_sys_0.mipi_dphy_ref_clk_0 needs an explicit top-level export
#    (unlike conduits, clock sinks aren't auto-exported); matches the working
#    project's "CLOCK0_50_mipi_ref" export.
#  - cam_axi2avst.snk's tuser role was terminated (USE_TUSER 0) but the
#    source (csi2_dphy_sys_0) unconditionally drives an 8-bit tuser -- a
#    terminated port can't be driven, so it must be made connectable.
#
#   qsys-script --script=fix_camera_capture_wiring.tcl

package require -exact qsys 25.3

load_system qsys_top.qsys

add_connection rst_in.out_reset cam_axi2avst.clk_reset

add_interface CLOCK0_50_mipi_ref clock end
set_interface_property CLOCK0_50_mipi_ref EXPORT_OF csi2_dphy_sys_0.mipi_dphy_ref_clk_0

set_instance_parameter_value cam_axi2avst {USE_TUSER} {1}

save_system
