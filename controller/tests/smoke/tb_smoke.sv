`timescale 1ns/1ps
module tb_smoke;
  reg clk = 0;
  reg reset = 1;
  reg [31:0] value = 0;
  reg [31:0] seed;
  integer cycles = 0;
  always #5 clk = ~clk;
  always @(posedge clk) begin
    if (reset) value <= seed;
    else begin
      value <= value + 32'd3;
      cycles <= cycles + 1;
    end
  end
  initial begin
    if (!$value$plusargs("seed=%d", seed)) $fatal(1, "missing seed");
    $dumpfile("smoke.vcd");
    $dumpvars(0, tb_smoke);
    repeat (2) @(negedge clk);
    reset = 0;
    repeat (8) @(negedge clk);
    if (cycles != 8 || value !== seed + 32'd24) $fatal(1, "counter mismatch");
    $display("T01_VCS_PASS seed=%0d cycles=%0d value=%0d", seed, cycles, value);
    $finish;
  end
  initial begin
    #1000;
    $fatal(1, "watchdog expired");
  end
endmodule
