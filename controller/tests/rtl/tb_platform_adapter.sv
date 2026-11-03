`timescale 1ns/1ps
// Only the PLL clock/lock environment is modeled. Both testers are real RTL.
// This stub makes no claim about analog PLL lock, PHY, or board timing.
module pll_probe(input clkin1, input rst, output clkout0, output lock);
  assign clkout0 = clkin1;
  assign lock = !rst;
endmodule

module tb_cpu;
  reg clk = 0, reset_n = 0, rst_n = 0, ddr_init_done = 0;
  wire [7:0] led;
  wire uart_tx;
  minimal_bist minimal(.sys_clk(clk), .reset_n(reset_n), .led(led), .uart_tx(uart_tx));
  wire [27:0] axi_awaddr, axi_araddr;
  wire [3:0] axi_awlen, axi_arlen;
  wire axi_awvalid, axi_arvalid;
  reg axi_awready = 0, axi_arready = 0, axi_wready = 0, axi_wlast = 0;
  wire [255:0] axi_wdata;
  wire [31:0] axi_wstrb;
  reg [255:0] axi_rdata = 0;
  reg axi_rvalid = 0, axi_rlast = 0;
  reg [3:0] axi_rid = 0;
  wire [31:0] errors, verified_passes, first_error_word_address, phase_status;
  wire full_range_verified, byte_masks_verified, failed;
  wire [31:0] debug_address, debug_drain, debug_stalled, debug_reason;
  wire [255:0] debug_expected;
  wire [3:0] debug_beat;
  // Reduced 4KiB window and guard are component parameters, not a board test.
  ddr_capacity_bist #(.MEM_SPACE_AW(10), .WRITE_DRAIN_CYCLES(8), .STALL_LIMIT(32)) ddr(.*);
  initial begin $dumpfile("cpu.vcd"); $dumpvars(0,tb_cpu); end
endmodule
