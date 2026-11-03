`timescale 1ns/1ps
module tb_ddr_phy_observer;
  reg clk=0, rst_n=0;
  always #5 clk=~clk;
  reg [31:0] flags=32'h130, errors=0, wb=0, rb=0, aw=0, ar=0, aux=32'hab012345;
  reg [29:0] calib=0;
  reg [67:0] status=0;
  reg [87:0] slice_state=88'h123456789abcde;
  reg [263:0] data=264'h123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef;
  wire [2047:0] report;
  wire tx;
  ddr_phy_observer obs(clk,rst_n,flags,errors,wb,rb,aw,ar,calib,aux,status,slice_state,data,report);
  ddr_phy_uart #(.BIT_TICKS(8),.FRAME_GAP(80)) uart(clk,rst_n,report,tx);
  integer fd, n=0, k;
  reg [7:0] byte_value;
  initial begin
    fd=$fopen("phy-uart.bin","wb");
    wait(rst_n);
    while(n<520) begin
      @(negedge tx);
      repeat(4) @(posedge clk);
      if(tx!==0) $fatal(1,"UART start");
      for(k=0;k<8;k=k+1) begin repeat(8) @(posedge clk); byte_value[k]=tx; end
      repeat(8) @(posedge clk);
      if(tx!==1) $fatal(1,"UART stop");
      $fwrite(fd,"%c",byte_value); n=n+1;
    end
    $fclose(fd); $display("PHY_UART_COMPLETE"); $finish;
  end
  initial begin
    repeat(3) @(negedge clk); rst_n=1;
    repeat(4) @(negedge clk); calib=(30'd1<<26);
    repeat(4) @(negedge clk); calib=(30'd3<<26)|(30'd8<<13);
    repeat(4) @(negedge clk); status[34]=1; // lane 2 gate error, one-cycle pulse
    @(negedge clk); status=0; calib=0; flags=32'h01000130;
    repeat(4) @(negedge clk);
    if(report[13*32]!==1 || report[12*32+:14]!==14'h40) $fatal(1,"Lost one-cycle fault");
    if(report[16*32+:30]!==((30'd3<<26)|(30'd8<<13))) $fatal(1,"Wrong first FSM");
    if(report[18*32+34]!==1 || report[17*32+:32]!==aux) $fatal(1,"Wrong first snapshot");
    if(report[24*32+:264]!==data || report[21*32+:88]!==slice_state) $fatal(1,"Wrong lane snapshot");
    // Emulate a subsequent retry with another fault: preserve the first, OR masks.
    calib=(30'd3<<26)|(30'd19<<13)|30'd1; status[50]=1;
    @(negedge clk); calib=0; status=0; flags=32'h60000130;
    repeat(4) @(negedge clk);
    if(report[12*32+:14]!==14'h3440) $fatal(1,"Wrong accumulated faults");
    if(report[16*32+:30]!==((30'd3<<26)|(30'd8<<13))) $fatal(1,"First fault overwritten by retry");
    if(!report[10*32+1] || !report[10*32+3] || !report[11*32+8] || !report[11*32+19]) $fatal(1,"Missing visited states");
    $display("PHY_OBSERVER_RETENTION_PASS");
  end
  initial begin #1000000; $fatal(1,"UART timeout"); end
endmodule
