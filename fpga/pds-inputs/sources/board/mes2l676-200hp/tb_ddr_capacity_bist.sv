`timescale 1ns/1ps
// Independent memory/byte enables and adverse ready/valid scheduling.
// Models controller transactions only, not DDR PHY/calibration or DRAM timing.
module capacity_fixture #(parameter ALIAS=0, CORRUPT=0, DROP_MASK=0)(
 input clk, rst_n,
 output failed, full_verified, masks_verified,
 output [31:0] passes, errors, first_error
);
 wire [27:0] awaddr, araddr;
 wire [3:0] awlen, arlen;
 wire awvalid, arvalid, awready, arready, wready;
 wire [255:0] wdata;
 wire [31:0] wstrb;
 reg [255:0] rdata;
 reg rvalid, rlast;
 integer ticks=0, wleft=0, rleft=0, wa=0, ra=0;
 reg [31:0] memory[0:1023];
 reg corrupted=0;
 integer i,j;
 wire [31:0] phase;
 assign awready=(ticks%3!=0 && wleft==0 && rleft==0);
 assign arready=(ticks%5!=0 && wleft==0 && rleft==0);
 assign wready=(wleft!=0 && ticks%4!=1);
 ddr_capacity_bist #(.MEM_SPACE_AW(10),.WRITE_DRAIN_CYCLES(3),.STALL_LIMIT(1000)) dut (
  .clk(clk),.rst_n(rst_n),.ddr_init_done(rst_n),
  .axi_awaddr(awaddr),.axi_araddr(araddr),.axi_awlen(awlen),.axi_arlen(arlen),
  .axi_awvalid(awvalid),.axi_arvalid(arvalid),.axi_awready(awready),.axi_arready(arready),
  .axi_wdata(wdata),.axi_wstrb(wstrb),.axi_wready(wready),.axi_wlast(wleft==1),
  .axi_rdata(rdata),.axi_rvalid(rvalid),.axi_rlast(rlast),.axi_rid(4'd0),
  .errors(errors),.verified_passes(passes),.first_error_word_address(first_error),
  .full_range_verified(full_verified),.byte_masks_verified(masks_verified),
  .phase_status(phase),.failed(failed)
 );
 initial begin rdata=0; rvalid=0; rlast=0; for(i=0;i<1024;i=i+1) memory[i]=0; end
 always @(posedge clk) begin
  if(!rst_n) begin ticks<=0; wleft<=0; rleft<=0; wa<=0; ra<=0; end
  else begin
   ticks<=ticks+1;
   if(awvalid && awready) begin wleft<=awlen+1; wa<=awaddr; end
   if(wready) begin
    for(i=0;i<8;i=i+1)
     for(j=0;j<4;j=j+1)
      if(wstrb[i*4+j] && !(DROP_MASK && wstrb!=32'hffffffff))
       memory[(wa+i)&(ALIAS ? 511 : 1023)][j*8+:8]<=wdata[(i*4+j)*8+:8];
    wa<=wa+8; wleft<=wleft-1;
   end
   if(arvalid && arready) begin rleft<=arlen+1; ra<=araddr; end
   if(rvalid) begin rleft<=rleft-1; ra<=ra+8; end
  end
 end
 always @(negedge clk) begin
  rvalid=0; rlast=0;
  if(rst_n && rleft!=0 && ticks%4!=2) begin
   for(i=0;i<8;i=i+1) rdata[i*32+:32]=memory[(ra+i)&(ALIAS ? 511 : 1023)];
   if(CORRUPT && !corrupted) begin rdata[0]=~rdata[0]; corrupted=1; end
   rvalid=1; rlast=(rleft==1);
  end
 end
 reg previous_aw_stall=0, previous_ar_stall=0;
 reg [27:0] saved_aw, saved_ar;
 reg [3:0] saved_awlen, saved_arlen;
 always @(posedge clk) if(rst_n) begin
  if(previous_aw_stall && (!awvalid || awaddr!=saved_aw || awlen!=saved_awlen))
   $fatal(1,"AW changed while stalled");
  if(previous_ar_stall && (!arvalid || araddr!=saved_ar || arlen!=saved_arlen))
   $fatal(1,"AR changed while stalled");
  previous_aw_stall<=awvalid && !awready; saved_aw<=awaddr; saved_awlen<=awlen;
  previous_ar_stall<=arvalid && !arready; saved_ar<=araddr; saved_arlen<=arlen;
 end
endmodule

module tb_ddr_capacity_bist;
 reg clk=0,rst_n=0;
 always #5 clk=~clk;
 wire [3:0] failed,full_verified,masks_verified;
 wire [31:0] passes[0:3],errors[0:3],first_error[0:3];
 capacity_fixture normal(clk,rst_n,failed[0],full_verified[0],masks_verified[0],passes[0],errors[0],first_error[0]);
 capacity_fixture #(.ALIAS(1)) alias_memory(clk,rst_n,failed[1],full_verified[1],masks_verified[1],passes[1],errors[1],first_error[1]);
 capacity_fixture #(.CORRUPT(1)) bad_read(clk,rst_n,failed[2],full_verified[2],masks_verified[2],passes[2],errors[2],first_error[2]);
 capacity_fixture #(.DROP_MASK(1)) bad_mask(clk,rst_n,failed[3],full_verified[3],masks_verified[3],passes[3],errors[3],first_error[3]);
 initial begin
  repeat(8) @(negedge clk);rst_n=1;
  wait(passes[0]==2); @(negedge clk);
  if(failed[0] || errors[0] || !full_verified[0] || !masks_verified[0]) $fatal(1,"Normal two-pass check failed");
  if(failed[3:1]!=3'b111 || errors[1]!=1 || errors[2]!=1 || errors[3]!=1)
   $fatal(1,"Adverse cases not detected");
  if(!full_verified[3] || masks_verified[3]) $fatal(1,"Selective mask fault coverage wrong");
  if(first_error[1]!=0 || first_error[2]!=0 || first_error[3]!=0) $fatal(1,"First error address wrong");
  $display("DDR_CAPACITY_BIST_PASS passes=%0d alias_detected=%0b corruption_detected=%0b mask_fault_detected=%0b MODEL_WORDS=1024 PHY_STUB=1 BOARD_TEST=0",passes[0],failed[1],failed[2],failed[3]);
  $finish;
 end
 initial begin #500000; $fatal(1,"Capacity BIST model timeout"); end
endmodule
