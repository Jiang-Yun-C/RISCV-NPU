// The future tb_soc instantiates soc_core plus this environment at ext_mem.
// fpga_top instantiates the same soc_core plus the T23 DDR controller adapter.
module soc_memory_env #(parameter DATA_W=32, ID_W=4)
    (input logic clk, reset_n, random_delays,
     input int unsigned seed, max_delay,
     input logic inject_enable, input logic [31:0] inject_start, inject_end,
     input logic [1:0] inject_resp, axi4_if.slave ext_mem);
    axi_sparse_mem #(.DATA_W(DATA_W),.ID_W(ID_W)) memory
        (.clk,.reset_n,.random_delays,.seed,.max_delay,.inject_enable,.inject_start,.inject_end,
         .inject_resp,.bus(ext_mem));
endmodule
