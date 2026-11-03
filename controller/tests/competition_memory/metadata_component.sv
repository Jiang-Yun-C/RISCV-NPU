module metadata_component(
 input wire clk,reset_n,valid,ready,
 input wire [31:0] a,b,input wire [63:0] tag,input wire [76:0] aux,
 output wire input_ready,output_valid,
 output wire [31:0] result,output wire [63:0] output_tag,output wire [76:0] output_aux
);
 wire [4:0] flags;
 nx_ce64_fp32_op #(.MUL(1),.PIPE_REGS(3),.AUX_W(77)) fp(
 .clock(clk),.reset_n,.a_i(a),.b_i(b),.tag_i(tag),.aux_i(aux),.valid_i(valid),.ready_o(input_ready),
 .result_o(result),.flags_o(flags),.tag_o(output_tag),.aux_o(output_aux),.valid_o(output_valid),.ready_i(ready));
endmodule
