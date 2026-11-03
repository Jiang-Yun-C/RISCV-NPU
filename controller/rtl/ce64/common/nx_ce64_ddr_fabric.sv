// Common digital SoC-to-HMIC boundary. PLL/PHY and local devices are external.
module nx_ce64_ddr_fabric #(
  parameter WRITE_DRAIN_CYCLES=1024, STALL_LIMIT=65536,
  parameter bit W_READ_OVERLAP=0
)(input logic clk, reset_n, ddr_init_done,
  input wire coral_w_capture,
  axi4_if.slave cpu_i, cpu_d, coral,
  axi4_if.master local_i, local_d, local_n,
  output wire [27:0] d_awaddr, d_araddr,
  output wire [3:0] d_awid, d_arid, d_awlen, d_arlen,
  output wire d_awvalid, d_arvalid,
  input wire d_awready, d_arready, d_wready, d_wlast,
  output wire [255:0] d_wdata,
  output wire [31:0] d_wstrb,
  input wire [255:0] d_rdata,
  input wire [3:0] d_rid,
  input wire d_rvalid, d_rlast,
  output wire native_pending,upstream_pending,safely_drained,quarantined,
  output wire [255:0] cpu_i_stats,cpu_d_stats,
  output wire fault,
  output wire [3:0] fault_reason,
  output wire [63:0] cycles, write_payload_bytes, read_payload_bytes, native_write_bytes, native_read_bytes);
  axi4_if #(.DATA_W(32),.ID_W(1)) di(clk), dd(clk);
  axi4_if #(.DATA_W(128),.ID_W(6)) dn(clk), memory(clk);
  nx_axi_ddr_route ri(.clk,.reset_n,.upstream(cpu_i),.local_bus(local_i),.ddr_bus(di));
  nx_axi_ddr_route rd(.clk,.reset_n,.upstream(cpu_d),.local_bus(local_d),.ddr_bus(dd));
  nx_axi_ddr_route rn(.clk,.reset_n,.upstream(coral),.local_bus(local_n),.ddr_bus(dn));
  nx_ce64_bus_stats #(.DATA_W(32)) is(.clk,.reset_n,.bus(di),.stats(cpu_i_stats));
  nx_ce64_bus_stats #(.DATA_W(32)) ds(.clk,.reset_n,.bus(dd),.stats(cpu_d_stats));
  wire memory_w_capture;
  nx_axi_ddr_mux mux(.clk,.reset_n,.cpu_i(di),.cpu_d(dd),.coral(dn),.memory,
    .coral_w_capture,.memory_w_capture);
  nx_ce64_ddr_adapter #(.DATA_W(128),.ID_W(6),.WRITE_DRAIN_CYCLES(WRITE_DRAIN_CYCLES),
    .STALL_LIMIT(STALL_LIMIT),.W_READ_OVERLAP(W_READ_OVERLAP)) adapter(
    .clk,.rst_n(reset_n),.ddr_init_done,.s_capture_read(memory_w_capture),
    .s_awaddr(memory.awaddr),.s_awid(memory.awid),.s_awlen(memory.awlen),.s_awsize(memory.awsize),.s_awburst(memory.awburst),.s_awvalid(memory.awvalid),.s_awready(memory.awready),
    .s_wdata(memory.wdata),.s_wstrb(memory.wstrb),.s_wlast(memory.wlast),.s_wvalid(memory.wvalid),.s_wready(memory.wready),
    .s_bid(memory.bid),.s_bresp(memory.bresp),.s_bvalid(memory.bvalid),.s_bready(memory.bready),
    .s_araddr(memory.araddr),.s_arid(memory.arid),.s_arlen(memory.arlen),.s_arsize(memory.arsize),.s_arburst(memory.arburst),.s_arvalid(memory.arvalid),.s_arready(memory.arready),
    .s_rdata(memory.rdata),.s_rid(memory.rid),.s_rresp(memory.rresp),.s_rvalid(memory.rvalid),.s_rlast(memory.rlast),.s_rready(memory.rready),
    .d_awaddr,.d_araddr,.d_awid,.d_arid,.d_awlen,.d_arlen,.d_awvalid,.d_arvalid,.d_awready,.d_arready,.d_wready,.d_wlast,.d_wdata,.d_wstrb,
    .d_rdata,.d_rid,.d_rvalid,.d_rlast,.native_pending,.upstream_pending,.safely_drained,.quarantined,.fault,.fault_reason,.cycles,.write_payload_bytes,.read_payload_bytes,.native_write_bytes,.native_read_bytes);
endmodule
