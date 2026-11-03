`timescale 1ns/1ps
// Compare RTL and actual ADS netlist on the same first two bursts. No PHY.
module tb_ddr_capacity_gate_sequence;
  reg clk=0,rstn=0;
  always #4 clk=~clk;
  wire [27:0] awaddr,araddr;
  wire [3:0] awlen,arlen;
  wire awvalid,arvalid,wready;
  wire [255:0] wdata;
  wire [31:0] wstrb,errors,passes,first_error,phase;
  wire full_ok,masks_ok,failed;
  integer ticks=0,aw_count=0,wleft=0,wbeats=0,first_aw_tick=-1;
  assign wready=(wleft!=0);
  ddr_capacity_bist dut(
    .clk(clk),.rst_n(rstn),.ddr_init_done(rstn),
    .axi_awaddr(awaddr),.axi_araddr(araddr),.axi_awlen(awlen),.axi_arlen(arlen),
    .axi_awvalid(awvalid),.axi_arvalid(arvalid),.axi_awready(wleft==0),.axi_arready(1'b0),
    .axi_wdata(wdata),.axi_wstrb(wstrb),.axi_wready(wready),.axi_wlast(wleft==1),
    .axi_rdata(256'd0),.axi_rvalid(1'b0),.axi_rlast(1'b0),.axi_rid(4'd0),
    .errors(errors),.verified_passes(passes),.first_error_word_address(first_error),
    .full_range_verified(full_ok),.byte_masks_verified(masks_ok),.phase_status(phase),.failed(failed)
  );
  GTP_GRS grs(.GRS_N(rstn));
  integer lane;
  always @(posedge clk) if(rstn) begin
    ticks=ticks+1;
    if(failed) $fatal(1,"Sequence entered FAIL");
    if(awvalid && wleft==0) begin
      $display("AW_TRACE ticks=%d address=%h length=%d",ticks,awaddr,awlen);
      if(awaddr!=aw_count*128 || awlen!=15) $fatal(1,"ADS address/length mismatch");
      aw_count=aw_count+1;
      if(first_aw_tick<0) first_aw_tick=ticks;
      else begin
        if(ticks-first_aw_tick!=1042) $fatal(1,"ADS write/drain sequence interval mismatch: %d",ticks-first_aw_tick);
        $display("DDR_CAPACITY_GATE_SEQUENCE_PASS AW_INTERVAL_CYCLES=%d WRITE_BEATS=%d PHY_STUB=1 BOARD_TEST=0",ticks-first_aw_tick,wbeats);
        $finish;
      end
      wleft<=16;
    end
    if(wready) begin
      if(wstrb!==32'hffffffff) $fatal(1,"ADS strobe mismatch");
      for(lane=0;lane<8;lane=lane+1)
        if(wdata[lane*32+:32] !== ((wbeats*8+lane)^32'ha5a55a5a))
          $fatal(1,"ADS data mismatch beat=%d lane=%d actual=%h",wbeats,lane,wdata[lane*32+:32]);
      wleft<=wleft-1; wbeats=wbeats+1;
    end
  end
  initial begin repeat(10) @(negedge clk);rstn=1; end
  initial begin #12000; $fatal(1,"First two burst sequence timed out AW=%d W=%d phase=%h",aw_count,wbeats,phase); end
endmodule
