`timescale 1ns/1ps
module tb_ddr_data_observer;
 reg clk=0,rstn=0,rvalid=0,wready=0;
 always #4 clk=~clk;
 reg [31:0] phase=0,address=0,drain=0;
 reg [255:0] expected=0,rdata=0,wdata=0;
 wire [2047:0] report;
 ddr_data_observer dut(.clk(clk),.rst_n(rstn),.flags(32'h1130),.errors(32'd0),
 .wbeats(32'd16),.rbeats(32'd1),.awcount(32'd1),.arcount(32'd1),
 .max_aw(32'd0),.max_ar(32'd0),.phase(phase),.address(address),
 .drain(drain),.stalled(32'd0),.reason(32'd4),.beat(4'd0),.rid(4'd0),
 .rvalid(rvalid),.rlast(1'b0),.wready(wready),.wlast(1'b0),.failed(1'b1),
 .expected(expected),.rdata(rdata),.wdata(wdata),.report(report));
 initial begin
  repeat(4) @(negedge clk);rstn=1;
  @(negedge clk);wready=1;wdata=256'habc;
  @(negedge clk);wready=0;phase=3;drain=1024;
  repeat(10) @(negedge clk);
  phase=1;address=128;
  @(negedge clk);phase=5;rvalid=1;expected=256'h123;rdata=256'h456;
  @(negedge clk);rvalid=0;expected=256'h999;rdata=256'haaa;wdata=256'hfff;
  repeat(4) @(negedge clk);
  if(report[17*32+:32]!=1024 || report[18*32+:32]!=10 || report[19*32+:32]!=128)
   $fatal(1,"First drain observation differs from input sequence");
  if(report[21*32+:256]!=256'h123 || report[29*32+:256]!=256'h456 || report[37*32+:256]!=256'habc)
   $fatal(1,"First data snapshots were overwritten");
  if(report[16*32+:32]!=15 || report[15*32+:32]!=4)
   $fatal(1,"Diagnostic context flags lost");
  $display("DDR_DATA_OBSERVER_PASS FIRST_SNAPSHOTS_RETAINED=1 PHY_STUB=1 BOARD_TEST=0");$finish;
 end
 initial begin #10000;$fatal(1,"Observer test timed out");end
endmodule
