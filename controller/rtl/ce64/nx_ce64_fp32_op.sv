// Compile vendor/registers.svh before vendor/fpnew_fma.sv in the filelist.
// Fixed operation removes the unused ISA/FMA operation network. Each output is
// an independently rounded binary32 result. There is no fused restore path.
module nx_ce64_fp32_op #(
  parameter bit MUL=1,
  parameter int PIPE_REGS=4,
  parameter int AUX_W=1
) (
  input logic clock,reset_n,
  input logic [31:0] a_i,b_i,
  input logic [63:0] tag_i,
  input logic [AUX_W-1:0] aux_i,
  input logic valid_i,
  output logic ready_o,
  output logic [31:0] result_o,
  output logic [4:0] flags_o,
  output logic [63:0] tag_o,
  output logic [AUX_W-1:0] aux_o,
  output logic valid_o,
  input logic ready_i
);
  logic [2:0][31:0] operands;
  assign operands[0]=MUL ? a_i : 32'h3f800000;
  assign operands[1]=MUL ? b_i : a_i;
  assign operands[2]=MUL ? 32'b0 : b_i;
  nx_ce64_fma_consumed #(.FpFormat(fpnew_pkg::FP32),.NumPipeRegs(PIPE_REGS),
    .PipeConfig(fpnew_pkg::DISTRIBUTED),.TagType(logic [63:0]),.AuxType(logic [AUX_W-1:0])) op (
    .clk_i(clock),.rst_ni(reset_n),.operands_i(operands),.is_boxed_i(3'b111),
    .rnd_mode_i(fpnew_pkg::RNE),.op_i(MUL ? fpnew_pkg::MUL : fpnew_pkg::ADD),
    .op_mod_i(1'b0),.tag_i(tag_i),.aux_i(aux_i),
    .in_valid_i(valid_i),.in_ready_o(ready_o),.flush_i(1'b0),
    .result_o,.status_o(flags_o),.tag_o,.aux_o,
    .out_valid_o(valid_o),.out_ready_i(ready_i),.reg_ena_i('0)
  );
endmodule

// Private CE sink-ready consumer; complete public source above is unchanged.
module nx_ce64_fp32_op_sink #(
  parameter bit MUL=1,
  parameter int PIPE_REGS=4,
  parameter int AUX_W=1
) (
  input logic clock,reset_n,
  input logic [31:0] a_i,b_i,
  input logic [63:0] tag_i,
  input logic [AUX_W-1:0] aux_i,
  input logic valid_i,
  output logic ready_o,
  output logic [31:0] result_o,
  output logic nonfinite_o,
  output logic [4:0] flags_o,
  output logic [63:0] tag_o,
  output logic [AUX_W-1:0] aux_o,
  output logic valid_o
);
  logic [2:0][31:0] operands;
  assign operands[0]=MUL ? a_i : 32'h3f800000;
  assign operands[1]=MUL ? b_i : a_i;
  assign operands[2]=MUL ? 32'b0 : b_i;
  nx_ce64_fma_ce_sink #(.FpFormat(fpnew_pkg::FP32),.NumPipeRegs(PIPE_REGS),
    .PipeConfig(fpnew_pkg::DISTRIBUTED),.TagType(logic [63:0]),.AuxType(logic [AUX_W-1:0])) op (
    .clk_i(clock),.rst_ni(reset_n),.operands_i(operands),.is_boxed_i(3'b111),
    .rnd_mode_i(fpnew_pkg::RNE),.op_i(MUL ? fpnew_pkg::MUL : fpnew_pkg::ADD),
    .op_mod_i(1'b0),.tag_i(tag_i),.aux_i(aux_i),
    .in_valid_i(valid_i),.in_ready_o(ready_o),.flush_i(1'b0),
    .result_o,.status_o(flags_o),.nonfinite_o,.tag_o,.aux_o,
    .out_valid_o(valid_o),.reg_ena_i('0)
  );
endmodule
