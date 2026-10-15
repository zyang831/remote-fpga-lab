// Always-ready, frame-aligned gate between csi2_rx and the capture mSGDMA.
//
// NOTE: the module name is historical -- it began life as a pure tuser strip.
// It still presents a master with no tuser port (which is why the downstream
// axist_to_avst_adapter accepts it), but it now also gates on tuser instead of
// discarding it. Ports are unchanged, so the Qsys wiring is untouched.
//
// Why always-ready: csi2_rx's video output is an Intel VVP "simple" interface,
// a real-time source that cannot be stalled. Any beat we fail to accept is
// lost inside the IP, which keeps emitting frame structure with zero-filled
// payload -- measured on hardware as ~1 good line per frame with the other
// ~1079 lines exactly zero. Terasic's own non-VVP reference for this exact
// camera (MIPI_RTL/AXI_Stream_Analyze.v) ties tready high permanently for the
// same reason. A slow sink is handled by dropping whole frames, never by
// backpressuring the camera.
//
// tuser[1:0] encoding (from MIPI_RTL/AXI_Stream_Analyze.v, which cites Intel's
// video-packets spec):
//   2'b10  first beat of a metadata packet (image info, or end of field)
//   2'b01  first beat of the FIRST video line of a frame
//   2'b00  every other beat -- payload, and the first beat of lines 1..N-1
// tlast ends each packet, i.e. each video line -- NOT each frame.
//
// Metadata packets are dropped, so the DMA receives pure pixel data and a
// captured frame is exactly width*height*2 bytes beginning at a frame
// boundary, rather than an arbitrary window containing image-info headers.

module cam_axi4s_tuser_strip (
	input  wire        clk,
	input  wire        reset_n,

	input  wire [63:0] s_tdata,
	input  wire        s_tvalid,
	output wire        s_tready,
	input  wire        s_tlast,
	input  wire [7:0]  s_tuser,

	output wire [63:0] m_tdata,
	output wire        m_tvalid,
	input  wire        m_tready,
	output wire        m_tlast
);

	// Never backpressure a source that cannot be stalled.
	assign s_tready = 1'b1;

	localparam [1:0] ST_IDLE  = 2'd0,
	                 ST_META  = 2'd1,
	                 ST_VIDEO = 2'd2;

	reg [1:0] state;
	reg       fwd;          // committed to forwarding the current frame

	wire beat         = s_tvalid;                        // s_tready is 1
	wire is_meta_head = beat && (s_tuser[1:0] == 2'b10);
	wire is_vid_head  = beat && (s_tuser[1:0] == 2'b01);
	wire is_body      = beat && (s_tuser[1:0] == 2'b00);

	// Pixel payload: the frame's opening beat, or body beats once inside a
	// frame. Body beats while a metadata packet is open are not payload.
	wire vid_payload  = is_vid_head || (is_body && (state == ST_VIDEO));

	// m_tvalid must not depend on m_tready: an AXI sink is permitted to wait
	// for valid before asserting ready, which would form a combinational loop.
	assign m_tvalid = vid_payload && (is_vid_head || fwd);
	assign m_tdata  = s_tdata;
	assign m_tlast  = s_tlast;

	always @(posedge clk or negedge reset_n) begin
		if (!reset_n) begin
			state <= ST_IDLE;
			fwd   <= 1'b0;
		end else if (beat) begin
			// Packet tracking. A video packet's tlast ends a LINE, not the
			// frame: lines 1..N-1 arrive as body beats, and the frame closes
			// only at the next metadata (end-of-field) packet.
			if (is_meta_head)
				state <= s_tlast ? ST_IDLE : ST_META;
			else if (is_vid_head)
				state <= ST_VIDEO;
			else if (is_body && (state == ST_META) && s_tlast)
				state <= ST_IDLE;

			// Forwarding commitment. Starting a frame the sink cannot take
			// would emit a torn one, so commit only if it is ready; if it
			// stalls mid-frame the beat is already gone, so abandon this
			// frame and wait for the next frame start.
			if (is_meta_head)
				fwd <= 1'b0;
			else if (is_vid_head)
				fwd <= m_tready;
			else if (vid_payload && fwd && !m_tready)
				fwd <= 1'b0;
		end
	end

endmodule
