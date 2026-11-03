`timescale 1ns/1ps
// Independent timing model of RST_DELAY=2, CLK_DELAY=2 and the installed
// LOGOS2 CE capture on two falling edges. Input transitions include mid-cycle
// assertion and enable/test-enable changes; no output data is precomputed.
module tb_pango_clock_reset;
  reg clk=0,rst_n=0,enable=0,te=0;
  wire gated,rst_out;
  RstSync dut(.clk_i(clk),.rstn_i(rst_n),.clk_en(enable),.te,.clk_o(gated),.rstn_o(rst_out));
  reg [3:0] release_pipe=0;
  reg capture1=1,capture2=1;
  wire expected_ce=(enable&&release_pipe[3])||te;
  integer checks=0,pulses=0,assertions=0;
  reg [31:0] random_state=32'h51223a91;
  realtime pulse_start;
  reg saw_pulse=0;
  always #5 clk=~clk;
  always @(posedge clk or negedge rst_n)
    if(!rst_n)release_pipe<=0;
    else release_pipe<={release_pipe[2:0],1'b1};
  always @(negedge clk)begin capture1<=expected_ce;capture2<=capture1;end
  always @(posedge gated)begin pulse_start=$realtime;saw_pulse=1;pulses=pulses+1;end
  always @(negedge gated)if(saw_pulse)begin
    if($realtime-pulse_start!=5.0)$fatal(1,"runt clock pulse");
    saw_pulse=0;checks=checks+1;
  end
  task check;
    begin
      if(rst_out!==release_pipe[1])$fatal(1,"reset release pipeline mismatch");
      if(gated!==(clk&&capture2))$fatal(1,"CE latency mismatch");
      if(!rst_n&&rst_out!==0)$fatal(1,"asynchronous assertion failed");
      checks=checks+3;
    end
  endtask
  initial begin
    // Guarantee an explicit initial asynchronous assertion before release.
    #1;rst_n=1;#1;rst_n=0;
    for(integer i=0;i<10000;i=i+1)begin
      @(negedge clk);#2;
      random_state=random_state^(random_state<<13);
      random_state=random_state^(random_state>>17);
      random_state=random_state^(random_state<<5);
      if(i<12)begin enable=1;te=0;rst_n=i>=4;end
      else begin
        enable=random_state[0];te=random_state[1]&&random_state[2];
        if(random_state[7:3]==0)begin rst_n=0;assertions=assertions+1;end
        else if(random_state[3])rst_n=1;
      end
      #1;check();@(posedge clk);#1;check();
    end
    enable=0;te=0;repeat(8)begin @(negedge clk);#1;check();end
    if(gated!==0||pulses<1000||assertions<100)$fatal(1,"coverage/clock-stop failure");
    $display("T24_CLOCK_RESET_PASS checks=%0d pulses=%0d resets=%0d",checks,pulses,assertions);
    $finish;
  end
endmodule
