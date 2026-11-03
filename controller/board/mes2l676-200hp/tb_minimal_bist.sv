`timescale 1ns/1ps
// Controller test only. The stub does not qualify the physical PLL.
module pll_probe(input clkin1, input rst, output clkout0, output lock);
  assign clkout0 = clkin1;
  assign lock = !rst;
endmodule

module tb_minimal_bist;
  reg clk = 0, reset_n = 0;
  always #18.5185 clk = !clk;
  wire [7:0] normal_led, corrupt_led;
  wire normal_tx, corrupt_tx;
  localparam [9:0] UART_FRAME = {1'b1, 8'h55, 1'b0};
  minimal_bist normal(clk, reset_n, normal_led, normal_tx);
  minimal_bist corrupt(clk, reset_n, corrupt_led, corrupt_tx);
  integer cycles = 0;
  initial begin
    repeat (5) @(negedge clk);
    reset_n = 1;
    wait(corrupt.state == 1 && corrupt.addr == 0 && corrupt.phase == 0);
    @(negedge clk);
    corrupt.memory[17] = corrupt.memory[17] ^ 32'h00000001;
    wait(normal.done && corrupt.done);
    @(negedge clk);
    if (normal_led[7:1] !== 7'h53 || corrupt_led[7:1] !== 7'h57)
      $fatal(1, "BIST normal/corruption detection failed: %h %h", normal_led, corrupt_led);
    // A full UART frame is exactly 2340 cycles and contains 0x55, 8N1.
    wait(normal.bitpos == 0 && normal.baud == 0);
    @(negedge clk);
    for (integer bit_index = 0; bit_index < 10; bit_index++) begin
      if (normal_tx !== UART_FRAME[bit_index])
        $fatal(1, "UART frame mismatch at bit %0d", bit_index);
      repeat (234) @(negedge clk);
    end
    reset_n = 0;
    repeat (5) @(negedge clk);
    reset_n = 1;
    wait(normal.done && corrupt.done);
    @(negedge clk);
    if (normal.failed || corrupt.failed) $fatal(1, "Reset/retest failed");
    $display("MINIMAL_BIST_SIM_PASS normal, injected corruption, UART and reset/retest");
    $finish;
  end
  initial begin
    repeat (15000) @(posedge clk);
    $fatal(1, "BIST simulation timeout");
  end
endmodule
