`timescale 1ns/1ps
module tb_t23_startup_reset;
 reg clk=0,rst_n=0;wire ready;
 always #10 clk=~clk;
 t23_startup_reset #(.HOLD_CYCLES(7)) dut(.*);
 integer i;
 task release_and_check;
  begin
   @(negedge clk);rst_n=1;
   for(i=0;i<6;i=i+1)begin @(negedge clk);if(ready)$fatal(1,"Early startup release");end
   @(negedge clk);if(!ready)$fatal(1,"Missing bounded startup release");
   repeat(25)begin @(negedge clk);if(!ready)$fatal(1,"Startup release wrapped or glitched");end
  end
 endtask
 initial begin
  repeat(3)@(negedge clk);release_and_check;
  #3;rst_n=0;#1;if(ready)$fatal(1,"Asynchronous KEY0 assertion ignored");
  repeat(10)begin @(negedge clk);if(ready)$fatal(1,"Release during held reset");end
  release_and_check;
  $display("T23_STARTUP_RESET_PASS TWO_RELEASES_AND_ASYNC_RESTART");$finish;
 end
 initial begin #10000;$fatal(1,"Startup reset timeout");end
endmodule
