`timescale 1ns/1ps
`ifndef DUT_DATA_W
`define DUT_DATA_W 128
`endif
module tb_t23_board_bist;
  localparam DATA_W=`DUT_DATA_W;
  reg clk=0, rst_n=0; wire ddr_init_done;
  always #4 clk=~clk;
  wire [31:0] s_awaddr, s_araddr;
  wire [5:0] s_awid, s_arid;
  wire [7:0] s_awlen, s_arlen;
  wire [2:0] s_awsize, s_arsize;
  wire [1:0] s_awburst, s_arburst;
  wire s_awvalid, s_arvalid, s_wvalid, s_wlast;
  wire s_awready, s_arready, s_wready;
  wire [DATA_W-1:0] s_wdata;
  wire [DATA_W/8-1:0] s_wstrb;
  wire [5:0] s_bid, s_rid;
  wire [1:0] s_bresp, s_rresp;
  wire s_bvalid, s_rvalid, s_rlast;
  wire s_bready, s_rready;
  wire [DATA_W-1:0] s_rdata;
  wire [27:0] d_awaddr, d_araddr;
  wire [3:0] d_awid, d_arid, d_awlen, d_arlen;
  wire d_awvalid, d_arvalid;
  wire d_awready, d_arready, d_wready, d_wlast;
  wire [255:0] d_wdata;
  wire [31:0] d_wstrb;
  wire [255:0] d_rdata;
  wire [3:0] d_rid;
  wire d_rvalid, d_rlast;
  wire fault;
  wire [3:0] fault_reason;
  wire [63:0] cycles, write_payload_bytes, read_payload_bytes, native_write_bytes, native_read_bytes;
  nx_ddr_adapter #(.DATA_W(DATA_W), .WRITE_DRAIN_CYCLES(1024), .STALL_LIMIT(10000)) uut(.*);
  wire [3:0] adapter_state=uut.state;
  initial begin $dumpfile("native.vcd"); $dumpvars(0,tb_t23_board_bist); end
  wire [3:0] vendor_wid;
  ddr3_test controller(
    .ref_clk(clk),.resetn(rst_n),.ddr_init_done(ddr_init_done),
    .axi_awaddr(d_awaddr),.axi_awuser_ap(1'b1),.axi_awuser_id(d_awid),
    .axi_awlen(d_awlen),.axi_awready(d_awready),.axi_awvalid(d_awvalid),
    .axi_wdata(d_wdata),.axi_wstrb(d_wstrb),.axi_wready(d_wready),
    .axi_wusero_id(vendor_wid),.axi_wusero_last(d_wlast),
    .axi_araddr(d_araddr),.axi_aruser_ap(1'b1),.axi_aruser_id(d_arid),
    .axi_arlen(d_arlen),.axi_arready(d_arready),.axi_arvalid(d_arvalid),
    .axi_rdata(d_rdata),.axi_rid(d_rid),.axi_rlast(d_rlast),.axi_rvalid(d_rvalid),
    .apb_clk(clk),.apb_rst_n(rst_n),.apb_sel(1'b0),.apb_enable(1'b0),
    .apb_addr(8'd0),.apb_write(1'b0),.apb_wdata(16'd0)
  );
  GTP_GRS grs(.GRS_N(rst_n));

  wire [31:0] errors,verified_passes,first_error_word_address,phase_status,debug_address,debug_stalled,debug_reason,workload;
  wire full_range_verified,byte_masks_verified,failed;
  wire [255:0] debug_expected;wire [3:0] debug_beat;
  wire [63:0] workload_cycles;
  t23_axi_bist #(.WINDOW_BITS(12),.BANDWIDTH_CYCLES(20000),.STALL_LIMIT(1000000)) bist(.*);
  reg [6:0] modes_seen=0;
  integer masked_requests=0;
  always @(posedge clk) if(rst_n) begin
    modes_seen[workload]<=1;
    if(s_awvalid && s_awready && bist.phase==2) masked_requests=masked_requests+1;
    if(s_arvalid && s_arready && bist.phase==3 && (s_araddr!=32'h80000000 || s_arlen!=1))
      $fatal(1,"Mask readback must cover all 32 bytes, including the untouched half");
  end
  initial if($test$plusargs("CORRUPT_READ")) begin
    wait(workload==1 && s_rvalid);force s_rdata=128'd0;
  end
  initial if($test$plusargs("BAD_BRESP")) begin
    wait(s_bvalid);force s_bresp=2'b10;
  end
  initial if($test$plusargs("LOST_CALIBRATION")) begin
    wait(bist.state==2);force ddr_init_done=1'b0;
  end
  initial if($test$plusargs("CROSS_MASK_CORRUPT")) begin
    // Upper-half byte write must also preserve the entire lower half.
    wait(bist.phase==3 && bist.mask_index==16 && s_rvalid);force s_rdata=128'd0;
  end
  always @(posedge clk) if(rst_n && (failed || fault)) $fatal(1,"Board BIST failure reason=%0d adapter=%0d",debug_reason,fault_reason);
  initial begin
    repeat(20) @(negedge clk);rst_n=1;
    wait(verified_passes==2);
    if(!full_range_verified || !byte_masks_verified || errors!=0 || write_payload_bytes==0 || read_payload_bytes==0 || modes_seen!=127 || masked_requests!=64) $fatal(1,"Empty/incomplete BIST result");
    $display("T23_BOARD_BIST_PASS PASSES=%0d WP=%0d RP=%0d",verified_passes,write_payload_bytes,read_payload_bytes);$finish;
  end
  initial begin #10000000;$fatal(1,"Board BIST timeout");end
endmodule
