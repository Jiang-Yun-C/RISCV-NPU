`timescale 1ns/1ps
`ifndef DUT_DATA_W
`define DUT_DATA_W 128
`endif
module tb_native110_ddr_adapter;
  localparam DATA_W=`DUT_DATA_W;
  reg clk=0, rst_n=0; wire ddr_init_done;
  always #4 clk=~clk;
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
  wire d_awready, d_arready, d_wready, d_wlast;
  wire [255:0] d_wdata;
  wire [31:0] d_wstrb;
  wire [255:0] d_rdata;
  wire [3:0] d_rid;
  wire d_rvalid, d_rlast;
  wire fault;
  wire [3:0] fault_reason;
  wire [63:0] cycles, write_payload_bytes, read_payload_bytes, native_write_bytes, native_read_bytes;
  nx_ddr_adapter #(.DATA_W(DATA_W), .WRITE_DRAIN_CYCLES(64), .STALL_LIMIT(10000)) uut(.*);
  wire [3:0] adapter_state=uut.state;
  initial begin $dumpfile("native.vcd"); $dumpvars(0,tb_native110_ddr_adapter); end
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
  reg [7:0] golden [0:4095];
  integer check_count=0, native_writes=0, native_reads=0;
  integer k, fd;
  always @(posedge clk) if(rst_n) begin
    if(fault) $fatal(1,"Adapter fault reason %0d",fault_reason);
    if(adapter_state==5 && d_wready) native_writes=native_writes+1;
    if(adapter_state==8 && d_rvalid) native_reads=native_reads+1;
  end
  task write_pattern(input integer offset, count, sz, seed);
    integer beat, lane, index;
    begin
      @(negedge clk);
      s_awaddr=32'h80000000+offset; s_awlen=count-1; s_awsize=sz; s_awid=61; s_awvalid=1;
      do @(posedge clk); while(!s_awready);
      @(negedge clk); s_awvalid=0;
      for(beat=0;beat<count;beat=beat+1) begin
        s_wdata=0; s_wstrb=0;
        for(lane=0;lane<(1<<sz);lane=lane+1) begin
          index=(offset+(beat<<sz)+lane)%16;
          golden[offset+(beat<<sz)+lane]=(offset+(beat<<sz)+lane)^seed;
          s_wdata[index*8+:8]=golden[offset+(beat<<sz)+lane];
          s_wstrb[index]=1;
        end
        s_wlast=beat==count-1; s_wvalid=1;
        do @(posedge clk); while(!s_wready);
        @(negedge clk); s_wvalid=0;
        repeat(beat%3) @(negedge clk);
      end
      wait(s_bvalid);
      repeat(5) @(negedge clk);
      if(s_bresp!=0 || s_bid!=61) $fatal(1,"Write visibility/ID failure");
      check_count=check_count+1;
      s_bready=1; @(negedge clk); s_bready=0;
    end
  endtask
  task read_pattern(input integer offset, count, sz);
    integer beat, lane, index;
    reg [127:0] expected;
    begin
      @(negedge clk);
      s_araddr=32'h80000000+offset; s_arlen=count-1; s_arsize=sz; s_arid=43; s_arvalid=1;
      do @(posedge clk); while(!s_arready);
      @(negedge clk); s_arvalid=0;
      for(beat=0;beat<count;beat=beat+1) begin
        wait(s_rvalid); @(negedge clk);
        repeat(beat%4) @(negedge clk);
        expected=0;
        for(lane=0;lane<(1<<sz);lane=lane+1) begin
          index=(offset+(beat<<sz)+lane)%16;
          expected[index*8+:8]=golden[offset+(beat<<sz)+lane];
        end
        if(s_rdata!==expected || s_rresp!=0 || s_rid!=43 || s_rlast!=(beat==count-1))
          $fatal(1,"Native adapter read mismatch beat=%0d actual=%h expected=%h",beat,s_rdata,expected);
        check_count=check_count+4;
        s_rready=1; @(negedge clk); s_rready=0;
      end
    end
  endtask
  initial begin
    for(k=0;k<4096;k=k+1) golden[k]=0;
    repeat(20) @(negedge clk); rst_n=1;
    wait(ddr_init_done);
    write_pattern(0,256,4,8'h5a);
    read_pattern(0,256,4);
    write_pattern(16,33,4,8'hc3); // native 16 + 1 burst split
    read_pattern(16,33,4);
    for(k=0;k<32;k=k+1) write_pattern(k,1,0,8'ha5);
    read_pattern(0,32,0);
    read_pattern(0,256,4); // all untouched bytes remain valid
    if(native_writes!=177 || native_reads!=451 || write_payload_bytes!=4656 || read_payload_bytes!=8752)
      $fatal(1,"Native adapter payload/accounting mismatch W=%0d R=%0d wp=%0d rp=%0d",native_writes,native_reads,write_payload_bytes,read_payload_bytes);
    check_count=check_count+4;
    fd=$fopen("native-result.json","w");
    $fwrite(fd,"{\"status\":\"PASS\",\"checks\":%0d,\"native_write_beats\":%0d,\"native_read_beats\":%0d,\"phy_stub\":true,\"model_bytes\":4096}\n",check_count,native_writes,native_reads);
    $fclose(fd);
    $display("T23_NATIVE_CONTROLLER_ADAPTER_PASS CHECKS=%0d PHY_STUB=1 BOARD_TEST=0",check_count);
    $finish;
  end
  initial begin #2000000; $fatal(1,"Native adapter simulation timeout"); end
endmodule
