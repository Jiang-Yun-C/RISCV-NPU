`timescale 1ns/1ps
`ifndef DUT_DATA_W
`define DUT_DATA_W 128
`endif
module tb_cpu;
  localparam DATA_W=`DUT_DATA_W;
  reg clk=0, rst_n=0, ddr_init_done=0;
  reg [31:0] s_awaddr=0, s_araddr=0;
  reg [5:0] s_awid=0, s_arid=0;
  reg [7:0] s_awlen=0, s_arlen=0;
  reg [2:0] s_awsize=0, s_arsize=0;
  reg [1:0] s_awburst=1, s_arburst=1;
  reg s_awvalid=0, s_arvalid=0, s_wvalid=0, s_wlast=0;
  wire s_awready, s_arready, s_wready;
  reg [DATA_W-1:0] s_wdata=0;
  reg [DATA_W/8-1:0] s_wstrb=0;
  wire [5:0] s_bid, s_rid;
  wire [1:0] s_bresp, s_rresp;
  wire s_bvalid, s_rvalid, s_rlast;
  reg s_bready=0, s_rready=0;
  wire [DATA_W-1:0] s_rdata;
  wire [27:0] d_awaddr, d_araddr;
  wire [3:0] d_awid, d_arid, d_awlen, d_arlen;
  wire d_awvalid, d_arvalid;
  reg d_awready=0, d_arready=0, d_wready=0, d_wlast=0;
  wire [255:0] d_wdata;
  wire [31:0] d_wstrb;
  reg [255:0] d_rdata=0;
  reg [3:0] d_rid=0;
  reg d_rvalid=0, d_rlast=0;
  wire fault;
  wire [3:0] fault_reason;
  wire [63:0] cycles, write_payload_bytes, read_payload_bytes, native_write_bytes, native_read_bytes;
  nx_ddr_adapter #(.DATA_W(DATA_W), .WRITE_DRAIN_CYCLES(8), .STALL_LIMIT(48)) uut(.*);
  wire [3:0] adapter_state=uut.state;
  initial begin $dumpfile("cpu.vcd"); $dumpvars(0,tb_cpu); end
endmodule
