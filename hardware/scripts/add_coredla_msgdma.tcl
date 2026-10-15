# Adds the Modular SGDMA the CoreDLA HPS MMD requires.
#
# The MMD refuses to enumerate a device unless /dev/msgdma_coredla<N> exists
# (mmd_device.h:51 bValid()), which needs an altr,socfpga-msgdma in the fabric
# driven by altera-msgdma + msgdma_userio.
#
#   qsys-script --script=add_coredla_msgdma.tcl
#
# Addresses match the devicetree:
#   csr              lwhps2fpga 0x21000 -> phys 0x20021000
#   descriptor_slave lwhps2fpga 0x21020 -> phys 0x20021020
#   csr_irq          f2h_irq0 line 3    -> GIC SPI 20
#
# The F2H base is SPI 17, not 16, so line N is SPI 17+N. Measured, not
# assumed: with this interrupt latched high, GICD_ISPENDR at 0x1d000200
# showed INTID 52 pending, and INTID = 32 + SPI. Matches the devicetree
# (interrupts = <0 20 4>) and /proc/interrupts (GICv3 52 Level).

package require -exact qsys 25.3

load_system qsys_top.qsys

add_instance coredla_msgdma altera_msgdma

# Memory-mapped to memory-mapped, 256-bit to match the DLA/f2sdram path.
set_instance_parameter_value coredla_msgdma {MODE} {0}
set_instance_parameter_value coredla_msgdma {DATA_WIDTH} {256}

# The Linux altera-msgdma driver writes a 32-byte struct msgdma_extended_desc
# (read_addr_hi/write_addr_hi included), so extended descriptors are mandatory.
set_instance_parameter_value coredla_msgdma {ENHANCED_FEATURES} {1}

# The driver polls MSGDMA_CSR_RESP_FILL_LEVEL in the CSR window and treats the
# separate response slave as optional; the devicetree declares csr+desc only.
set_instance_parameter_value coredla_msgdma {RESPONSE_PORT} {2}

# Bursting must stay off. These are Avalon-MM masters bridged to the AXI4
# f2sdram subordinate, and AXI forbids a burst crossing a 4 KB boundary while
# Avalon has no such rule -- the generated bridge does not split them. Measured
# on hardware with raw descriptors: a transfer starting at +0xF00 corrupts from
# exactly the 0x1000 boundary onward, while 4 KB-aligned transfers of the same
# length are clean. The DLA is unaffected because its port is AXI-native.
#
# ponytail: costs throughput (one transaction per 32-byte beat). Revisit by
# splitting descriptors at 4 KB in msgdma_userio, or by fixing the bridge, only
# once host<->DDR bandwidth actually matters.
set_instance_parameter_value coredla_msgdma {BURST_ENABLE} {0}
set_instance_parameter_value coredla_msgdma {STRIDE_ENABLE} {0}

# 1 MB, giving LENGTH_WIDTH = 21. This is the value in the bitstream that runs
# dla_benchmark end to end (output_files/golden_top.syn.rpt from the 2026-08-15
# 18:41 build), so keep it unless you are prepared to rebuild and requalify.
#
# It is safe only because msgdma_userio caps every descriptor well below it:
# msgdma_userio_xfer_sg() splits each sg entry at MSGDMA_USERIO_MAX_CHUNK
# (256 KB), and it is the sole consumer of this mSGDMA (devicetree binds only
# msgdma_coredla0 to it; the DLA's own DDR port is AXI-native and does not go
# through here). altera-msgdma will not protect you -- MSGDMA_MAX_TRANS_LEN is
# U32_MAX, so it emits one descriptor per sg entry at whatever length
# dma_map_sg produced. Drop the 256 KB cap on this hardware and an observed
# 2 MiB coalesced entry overflows 2^21 and truncates silently.
#
# History, so nobody re-derives it: this was briefly set to 2147483647 on the
# theory that a 2 MiB sg entry was failing because the length counter was too
# narrow. That was wrong -- the engine was wedged, and reloading altera-msgdma
# (not just msgdma_userio) fixed it at ~90 MB/s. The 2 GB compile was killed
# mid-synthesis and never produced a .sof, so that value was never on hardware.
#
# ponytail: 1 MB + the 256 KB software cap. If you ever want to remove the cap,
# widen this first, rebuild, and requalify -- in that order.
set_instance_parameter_value coredla_msgdma {MAX_BYTE} {1048576}
set_instance_parameter_value coredla_msgdma {DATA_FIFO_DEPTH} {64}
set_instance_parameter_value coredla_msgdma {DESCRIPTOR_FIFO_DEPTH} {128}

# Must be "Unaligned Accesses". The data path is 256-bit, so "Aligned Accesses"
# requires every address to be 32-byte aligned and silently drops the low
# address bits otherwise -- transfers still complete and raise no error, they
# just move the wrong bytes. Kernel buffers handed over by msgdma_userio are
# only 16-byte aligned in practice (observed 0x954b5650), so anything stricter
# than unaligned cannot work with the Linux driver.
set_instance_parameter_value coredla_msgdma {TRANSFER_TYPE} {Unaligned Accesses}

add_connection clk_100.out_clk coredla_msgdma.clock
add_connection rst_in.out_reset coredla_msgdma.reset_n

# Control plane: both slaves on the lightweight bridge, above the DLA CSR
# block, which ends at 0x207ff.
add_connection subsys_hps.lwhps2fpga coredla_msgdma.csr
set_connection_parameter_value subsys_hps.lwhps2fpga/coredla_msgdma.csr \
    baseAddress {0x00021000}
add_connection subsys_hps.lwhps2fpga coredla_msgdma.descriptor_slave
set_connection_parameter_value subsys_hps.lwhps2fpga/coredla_msgdma.descriptor_slave \
    baseAddress {0x00021020}

# Data plane: both masters onto the same F2SDRAM path the DLA uses. F2SDRAM is
# identity-mapped onto HPS physical addresses, so no offset is needed here --
# unlike the DLA, whose span extender applies WINDOW_BASE.
add_connection coredla_msgdma.mm_read subsys_hps.f2sdram_adapter_axi4_sub
set_connection_parameter_value \
    coredla_msgdma.mm_read/subsys_hps.f2sdram_adapter_axi4_sub \
    baseAddress {0x0000000000000000}
add_connection coredla_msgdma.mm_write subsys_hps.f2sdram_adapter_axi4_sub
set_connection_parameter_value \
    coredla_msgdma.mm_write/subsys_hps.f2sdram_adapter_axi4_sub \
    baseAddress {0x0000000000000000}

# Lines 0/1 are the peripheral PIOs, line 2 is dla.irq_level.
add_connection subsys_hps.f2h_irq0_in coredla_msgdma.csr_irq
set_connection_parameter_value \
    subsys_hps.f2h_irq0_in/coredla_msgdma.csr_irq irqNumber {3}

save_system
