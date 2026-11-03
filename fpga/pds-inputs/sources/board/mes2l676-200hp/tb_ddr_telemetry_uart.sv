`timescale 1ns/1ps
module tb_ddr_telemetry_uart;
  reg clk=0, rstn=0;
  always #1 clk=~clk;
  wire tx;
  reg [31:0] count=0;
  always @(posedge clk) if(rstn) count<=count+1'b1; else count<=0;
  ddr_telemetry_uart #(.BIT_TICKS(814),.FRAME_GAP(100)) dut (
    .clk(clk),.rst_n(rstn),.uart_txd(tx), .flags(32'h01020304),
    .errors(32'h12345678), .write_beats(count), .read_beats(32'd5678),
    .aw_count(32'd90), .ar_count(32'd123), .max_awaddr(32'h0fffff80),
    .max_araddr(32'h01234560), .init_passes(32'd1)
  );
  integer frame_number,i,b;
  reg [7:0] data;
  initial begin
    repeat(4) @(negedge clk); rstn=1;
    for(frame_number=0;frame_number<2;frame_number=frame_number+1) begin
      $write("TELEMETRY_FRAME ");
      for(i=0;i<56;i=i+1) begin
        @(negedge tx); #814;
        if(tx!==0) $fatal(1,"Invalid UART start bit");
        for(b=0;b<8;b=b+1) begin #1628; data[b]=tx; end
        #1628; if(tx!==1) $fatal(1,"Invalid UART stop bit");
        $write("%02x",data);
      end
      $write("\n");
    end
    $display("DDR_TELEMETRY_UART_PASS frames=2 format=115200_8N1_nominal_CORE93M75 BOARD_TEST=0");
    $finish;
  end
  initial begin #2000000; $fatal(1,"UART telemetry timeout"); end
endmodule
