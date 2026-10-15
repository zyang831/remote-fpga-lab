package require -exact qsys 25.3

set_module_property NAME cam_axi4s_tuser_strip
set_module_property DESCRIPTION "Always-ready, frame-aligned AXI4-Stream gate for csi2_rx: never backpressures the camera, drops metadata packets, and forwards whole frames only. Still presents a master with no tuser port. Name is historical."
set_module_property VERSION 1.0
set_module_property GROUP "Basic Functions/Bridges and Adaptors/AXI Streaming"
set_module_property DISPLAY_NAME "Camera AXI4-Stream tuser Strip"
set_module_property AUTHOR "Project-local"
set_module_property INSTANTIATE_IN_SYSTEM_MODULE true
set_module_property ELABORATION_CALLBACK elaborate

add_fileset quartus_synth QUARTUS_SYNTH do_synth
set_fileset_property quartus_synth TOP_LEVEL cam_axi4s_tuser_strip
add_fileset quartus_sim SIM_VERILOG do_synth
set_fileset_property quartus_sim TOP_LEVEL cam_axi4s_tuser_strip

proc do_synth {output_name} {
    add_fileset_file cam_axi4s_tuser_strip.sv SYSTEM_VERILOG PATH cam_axi4s_tuser_strip.sv
}

proc elaborate {} {
    add_interface clock clock end
    add_interface_port clock clk clk Input 1

    add_interface reset reset end
    add_interface_port reset reset_n reset_n Input 1
    set_interface_property reset associatedClock clock

    add_interface s axi4stream subordinate
    add_interface_port s s_tdata  tdata  Input  64
    add_interface_port s s_tvalid tvalid Input  1
    add_interface_port s s_tready tready Output 1
    add_interface_port s s_tlast  tlast  Input  1
    add_interface_port s s_tuser  tuser  Input  8
    set_interface_property s associatedClock clock
    set_interface_property s associatedReset reset

    add_interface m axi4stream start
    add_interface_port m m_tdata  tdata  Output 64
    add_interface_port m m_tvalid tvalid Output 1
    add_interface_port m m_tready tready Input  1
    add_interface_port m m_tlast  tlast  Output 1
    set_interface_property m associatedClock clock
    set_interface_property m associatedReset reset
}
