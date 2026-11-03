`timescale 1ns/1ps
module tb_opt11;
  reg clk=0;always #4 clk=~clk;
  reg reset_n=0,start=0,ack=0,quantize_only=0,load_valid=0;
  reg [6:0] length=64;
  reg [127:0] gate_data=0,up_data=0;
  reg [5:0] peek=0;
  wire load_ready,valid,idle,error;
  wire [127:0] fp_data,q_data;
  wire [31:0] scale;
  wire [63:0] cycles;
  nx_opt11_group #(.LANES(`OPT11_LANES)) dut(.*);
  reg unit_start=0;
  reg [31:0] unit_a=0,unit_b=0;
  wire exp_ready,exp_valid,div_ready,div_valid;
  wire [31:0] exp_result,div_result;
  nx_opt11_exp exp_unit(.clk,.reset_n,.start(unit_start),.a(unit_a),.ready(exp_ready),.valid(exp_valid),.result(exp_result));
  nx_opt11_div div_unit(.clk,.reset_n,.start(unit_start),.a(unit_a),.b(unit_b),.ready(div_ready),.valid(div_valid),.result(div_result));
  initial begin
    $dumpfile("component.vcd");$dumpvars(1,tb_opt11);
    #800000;$dumpoff;
    #199999200000;$fatal(1,"OPT11 component simulation deadline");
  end
endmodule
