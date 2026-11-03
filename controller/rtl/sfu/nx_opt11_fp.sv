// One shared independently-rounded FP32 add/multiply pipeline.
module nx_opt11_fp (
  input wire clk,reset_n,start,multiply,
  input wire [31:0] a,b,
  output wire ready,valid,
  output wire [31:0] result
);
  wire [2:0][31:0] operands;
  assign operands[0]=multiply ? a : 32'h3f800000;
  assign operands[1]=multiply ? b : a;
  assign operands[2]=multiply ? 32'b0 : b;
  nx_ce64_fma_sfu_tagless #(.FpFormat(fpnew_pkg::FP32),.NumPipeRegs(4),
    .PipeConfig(fpnew_pkg::DISTRIBUTED)) arithmetic (
    .clk_i(clk),.rst_ni(reset_n),.operands_i(operands),.is_boxed_i(3'b111),
    .rnd_mode_i(fpnew_pkg::RNE),.op_i(multiply ? fpnew_pkg::MUL : fpnew_pkg::ADD),
    .op_mod_i(1'b0),
    .in_valid_i(start),.in_ready_o(ready),.flush_i(1'b0),.result_o(result),
    .status_o(),
    .out_valid_o(valid),.out_ready_i(1'b1),.reg_ena_i('0));
endmodule
