// Real CE hierarchy; only the external MMIO master and DDR slave are fixtures.
module ce_component #(parameter bit ENHANCED=1)(
 input wire clk,reset_n,external_isolate,window_isolate,
 input wire mm_awvalid,mm_wvalid,mm_arvalid,
 input wire [31:0] mm_address,mm_write_data,
 output wire mm_awready,mm_wready,mm_arready,mm_bvalid,mm_rvalid,
 output wire [1:0] mm_bresp,mm_rresp,
 output wire [31:0] mm_read_data,
 output wire mem_awvalid,mem_wvalid,mem_arvalid,mem_bready,mem_rready,mem_wlast,
 output wire [31:0] mem_awaddr,mem_araddr,
 output wire [5:0] mem_awid,mem_arid,
 output wire [7:0] mem_awlen,mem_arlen,
 output wire [2:0] mem_awsize,mem_arsize,
 output wire [1:0] mem_awburst,mem_arburst,
 output wire [127:0] mem_wdata,
 output wire [15:0] mem_wstrb,
 input wire mem_awready,mem_wready,mem_arready,mem_bvalid,mem_rvalid,mem_rlast,
 input wire [5:0] mem_bid,mem_rid,
 input wire [1:0] mem_bresp,mem_rresp,
 input wire [127:0] mem_rdata,
 output wire idle,drained,quarantined
);
 axi4_if #(.DATA_W(128),.ID_W(6)) mmio(clk),memory(clk);
 assign mmio.awvalid=mm_awvalid;assign mmio.awaddr=mm_address;
 assign mmio.awid=0;assign mmio.awlen=0;assign mmio.awsize=2;assign mmio.awburst=1;
 assign mmio.wvalid=mm_wvalid;assign mmio.wdata=128'(mm_write_data)<<(32*mm_address[3:2]);
 assign mmio.wstrb=16'hf<<(4*mm_address[3:2]);assign mmio.wlast=1;assign mmio.bready=1;
 assign mmio.arvalid=mm_arvalid;assign mmio.araddr=mm_address;
 assign mmio.arid=0;assign mmio.arlen=0;assign mmio.arsize=2;assign mmio.arburst=1;assign mmio.rready=1;
 assign mm_awready=mmio.awready;assign mm_wready=mmio.wready;assign mm_arready=mmio.arready;
 assign mm_bvalid=mmio.bvalid;assign mm_bresp=mmio.bresp;
 assign mm_rvalid=mmio.rvalid;assign mm_rresp=mmio.rresp;assign mm_read_data=mmio.rdata[mm_address[3:2]*32+:32];
 assign mem_awvalid=memory.awvalid;assign mem_awaddr=memory.awaddr;assign mem_awid=memory.awid;
 assign mem_awlen=memory.awlen;assign mem_awsize=memory.awsize;assign mem_awburst=memory.awburst;
 assign mem_wvalid=memory.wvalid;assign mem_wdata=memory.wdata;assign mem_wstrb=memory.wstrb;assign mem_wlast=memory.wlast;
 assign mem_arvalid=memory.arvalid;assign mem_araddr=memory.araddr;assign mem_arid=memory.arid;
 assign mem_arlen=memory.arlen;assign mem_arsize=memory.arsize;assign mem_arburst=memory.arburst;
 assign mem_bready=memory.bready;assign mem_rready=memory.rready;
 assign memory.awready=mem_awready;assign memory.wready=mem_wready;assign memory.arready=mem_arready;
 assign memory.bvalid=mem_bvalid;assign memory.bid=mem_bid;assign memory.bresp=mem_bresp;
 assign memory.rvalid=mem_rvalid;assign memory.rid=mem_rid;assign memory.rresp=mem_rresp;
 assign memory.rdata=mem_rdata;assign memory.rlast=mem_rlast;
 wire irq,clear_guard_error,memory_w_capture;
 nx_ce64 #(.LONG_PV(ENHANCED),.HEAD_ARGMAX(ENHANCED)) dut(
 .clk,.platform_reset_n(reset_n),.external_isolate,.external_window_isolate(window_isolate),
 .startup_authorized(1'b0),.guard_idle(1'b1),.guard_fault(1'b0),
 .native_safely_drained(1'b1),.native_quarantined(1'b0),.visible_fault_address(32'b0),
 .mmio,.memory,.irq,.idle,.quarantined,.drained,.clear_guard_error,.memory_w_capture);
endmodule
