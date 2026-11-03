`timescale 1ns/1ps
module reset_check #(parameter H=17)(output reg done=0);
  reg clk=0,rst_n=0,request=0,phase=0;
  wire old_hold,new_hold;
  integer checks=0,high_count=0;
  ce64_platform_reset_original #(.HOLD_CYCLES(H)) old_dut(clk,rst_n,request,old_hold);
  ce64_platform_reset #(.HOLD_CYCLES(H)) new_dut(clk,rst_n,request,new_hold);
  initial begin while(!done)begin #4;clk=~clk;end end
  always @(negedge clk)begin
    if(rst_n)begin
      checks++;
      if(old_hold!==new_hold || old_dut.remaining!==new_dut.remaining)
        $fatal(1,"reset equivalence H=%0d old=%0d new=%0d",H,old_hold,new_hold);
      if(phase&&new_hold)high_count++;
    end
  end
  initial begin
    repeat(4)@(negedge clk);rst_n=1;phase=1;request=1;
    repeat(4)@(negedge clk);request=0;
    repeat(H+10)@(negedge clk);phase=0;
    if(H>=17&&high_count!=H)$fatal(1,"independent hold duration H=%0d observed=%0d",H,high_count);
    request=1;repeat(8)@(negedge clk);rst_n=0;
    #1;if(new_hold!==0)$fatal(1,"asynchronous board reset");
    repeat(3)@(negedge clk);request=0;rst_n=1;
    repeat(100)@(negedge clk);
    $display("RESET_EQ_PASS H=%0d checks=%0d high=%0d",H,checks,high_count);done=1;
  end
endmodule
module tb_reset;
  wire [7:0] done;
  reset_check #(1) t0(done[0]);reset_check #(2) t1(done[1]);
  reset_check #(3) t2(done[2]);reset_check #(17) t3(done[3]);
  reset_check #(255) t4(done[4]);reset_check #(256) t5(done[5]);
  reset_check #(1024) t6(done[6]);reset_check #(125000000) t7(done[7]);
  initial begin wait(&done);$display("OPT10_R1_RESET_ALL_PASS");$finish;end
endmodule
