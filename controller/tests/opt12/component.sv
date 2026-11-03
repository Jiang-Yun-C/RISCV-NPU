`timescale 1ns/1ps
module tb_opt12;
  reg clk=0;always #4 clk=~clk;
  reg reset_n=0,start=0,ack=0,quantize_result=0,pad_full=0,load_valid=0;
  reg [3:0] mode=0;reg [31:0] scalar=0;reg [6:0] length=64;
  reg [127:0] gate_data=0,up_data=0;reg [5:0] peek=0;
  wire load_ready,valid,idle,error;wire [127:0] fp_data,q_data;
  wire [31:0] scale;wire [63:0] cycles;
  nx_opt11_group #(.LANES(`OPT12_LANES)) dut(.*);
  reg unit_start=0;reg [31:0] unit_a=0;
  wire sqrt_ready,sqrt_valid;wire [31:0] sqrt_result;
  nx_opt12_sqrt sqrt_unit(.clk,.reset_n,.start(unit_start),.a(unit_a),.ready(sqrt_ready),.valid(sqrt_valid),.result(sqrt_result));
  initial begin $dumpfile("component.vcd");$dumpvars(1,tb_opt12);
    #800000;$dumpoff;#199999200000;$fatal(1,"OPT12 simulation deadline");end
endmodule
