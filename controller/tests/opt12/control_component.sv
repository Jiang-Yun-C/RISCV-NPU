`timescale 1ns/1ps
module tb_opt12;
reg clk, platform_reset_n, submit, reset_grant, stop_new, abort_publish;
reg [1023:0] descriptor;
reg [31:0] epoch, generation, first_fault_address;
reg [63:0] run_limit;
reg transport_drained, native_quarantined;
wire engine_idle, arithmetic_idle, scratch_idle, timeout_fault, call_fault;
wire [1279:0] completion;
wire completion_valid;
reg completion_ready;
wire [511:0] perf;
reg dma_ready,dma_result_valid,dma_idle;
reg [1:0] dma_resp;
wire dma_valid,dma_write,dma_result_ready;
wire [31:0] dma_address;
wire [2:0] dma_size;
wire [4:0] dma_len;
wire [15:0] dma_scratch;
wire [127:0] dma_data;
wire [15:0] dma_mask;
wire ram_en;
wire [11:0] ram_address;
wire [15:0] ram_mask;
wire [127:0] ram_data;
reg [127:0] ram_q;
initial begin clk=0;platform_reset_n=0;submit=0;reset_grant=0;stop_new=0;abort_publish=0;descriptor=0;epoch=1;generation=1;first_fault_address=0;run_limit=1000000;transport_drained=1;native_quarantined=0;completion_ready=1;dma_ready=1;dma_result_valid=0;dma_idle=1;dma_resp=0;ram_q=0;end
always #4 clk=~clk;
wire [63:0] run_limit_next=run_limit;
nx_opt11_control dut(.*);
initial begin $dumpfile("component.vcd");$dumpvars(0,tb_opt12);#8000000;$fatal(1,"deadline");end
endmodule
