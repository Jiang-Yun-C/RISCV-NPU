module minimal_bist(input sys_clk, input reset_n, output [7:0] led, output uart_tx);
  wire clk, locked;
  pll_probe pll(.clkin1(sys_clk), .rst(!reset_n), .clkout0(clk), .lock(locked));
  reg [2:0] release_reset = 0;
  always @(posedge clk or negedge locked)
    if (!locked) release_reset <= 0;
    else release_reset <= {release_reset[1:0],1'b1};
  wire ready = release_reset[2];
  reg [25:0] ticks = 0;
  reg [7:0] addr = 0;
  reg [2:0] state = 0;
  reg phase = 0, done = 0, failed = 0;
  (* syn_ramstyle = "block_ram" *) reg [31:0] memory [0:255];
  reg [31:0] rd;
  wire [31:0] pattern = {addr, ~addr, addr ^ 8'h5a, addr ^ 8'ha5} ^ {32{phase}};
  always @(posedge clk) begin
    if (ready && state == 0) memory[addr] <= pattern;
    rd <= memory[addr];
  end
  always @(posedge clk) begin
    if (!ready) begin ticks<=0; addr<=0; state<=0; phase<=0; done<=0; failed<=0; end
    else begin
      ticks <= ticks + 1'b1;
      case (state)
        0: if (addr == 255) begin addr<=0; state<=1; end else addr<=addr+1'b1;
        1: state<=2;
        2: begin
          if (rd !== pattern) failed<=1;
          if (addr == 255) begin
            addr<=0;
            if (phase) begin done<=1; state<=3; end
            else begin phase<=1; state<=0; end
          end else begin addr<=addr+1'b1; state<=1; end
        end
        3: state<=3;
      endcase
    end
  end
  // Known output identity 0xa in led[7:4]; observe via SAMPLE and physical LEDs.
  assign led = {4'ha, failed, done, locked, ticks[24]};
  // Repeating 0x55, 115200 8N1 from the 27MHz PLL output (234 cycles/bit).
  reg [7:0] baud = 0;
  reg [3:0] bitpos = 0;
  always @(posedge clk) begin
    if (!ready) begin baud<=0; bitpos<=0; end
    else if (baud==233) begin baud<=0; bitpos<=bitpos==9 ? 0 : bitpos+1'b1; end
    else baud<=baud+1'b1;
  end
  wire [9:0] uart_frame = {1'b1,8'h55,1'b0};
  assign uart_tx = ready ? uart_frame[bitpos] : 1'b1;
endmodule
