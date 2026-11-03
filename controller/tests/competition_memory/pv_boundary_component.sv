// Targeted PV controller fixture. Real controller and original FP arithmetic;
// DMA responses, external memory and the synchronous scratch RAM are in C++.
module pv_boundary_component #(parameter integer MAX_LENGTH=512)(
 input logic clk,reset_n,submit,reset_grant,stop_new,abort_publish,
 input logic [1023:0] descriptor,
 input logic [63:0] run_limit,
 input logic dma_ready,dma_result_valid,dma_idle,transport_drained,
 input logic [1:0] dma_resp,
 input logic [127:0] ram_q,
 input logic window_valid,
 input logic [31:0] window_q,window_epoch,window_words,window_length,window_padded,
 input logic [63:0] window_session,window_sequence,
 output wire window_en,
 output wire [8:0] window_address,
 output wire dma_valid,dma_write,dma_result_ready,ram_en,completion_valid,
 output wire [31:0] dma_address,
 output wire [2:0] dma_size,
 output wire [4:0] dma_len,
 output wire [15:0] dma_scratch,ram_mask,
 output wire [11:0] ram_address,
 output wire [127:0] ram_data,
 output wire [1279:0] completion,
 output wire [511:0] perf
);
 wire fp_start,fp_multiply,fp_ready,fp_valid;
 wire [31:0] fp_a,fp_b,fp_result;
 nx_opt11_fp fp(.clk,.reset_n,.start(fp_start),.multiply(fp_multiply),
  .a(fp_a),.b(fp_b),.ready(fp_ready),.valid(fp_valid),.result(fp_result));
 nx_pv_control #(.MAX_LENGTH(MAX_LENGTH)) dut(.clk,.platform_reset_n(reset_n),
  .submit,.reset_grant,.stop_new,.abort_publish,.descriptor,.epoch(32'd1),
  .generation(32'd11),.first_fault_address(32'b0),.run_limit,.transport_drained,
  .native_quarantined(1'b0),.engine_idle(),.arithmetic_idle(),.scratch_idle(),
  .timeout_fault(),.call_fault(),.completion,.completion_valid,.completion_ready(1'b1),
  .perf,.dma_ready,.dma_result_valid,.dma_idle,.dma_resp,.dma_valid,.dma_write,
  .dma_result_ready,.dma_address,.dma_size,.dma_len,.dma_scratch,.dma_data(),.dma_mask(),
  .ram_en,.ram_address,.ram_mask,.ram_data,.ram_q,.fp_start,.fp_multiply,.fp_a,.fp_b,
  .fp_ready,.fp_valid,.fp_result,.resident_write_region(),.p_window_en(window_en),
  .p_window_address(window_address),.p_window_q(window_q),.p_window_epoch(window_epoch),
  .p_window_words(window_words),.p_window_len(window_length),.p_window_padded(window_padded),
  .p_window_session(window_session),.p_window_sequence(window_sequence),.p_window_valid(window_valid));
endmodule
