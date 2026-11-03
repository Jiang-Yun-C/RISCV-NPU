`timescale 1ns/1ps
module tb_platform_reset;
  logic ref_clk=0,board_reset_n=0,core_request=0;wire hold_reset;
  always #4 ref_clk=~ref_clk;
  ce64_platform_reset #(.HOLD_CYCLES(17)) dut(.*);
  integer checks=0;
  task tick;@(posedge ref_clk);#1;endtask
  task check(input bit yes);checks++;if(!yes)$fatal(1,"platform reset synchronization/hold");endtask
  initial begin
    repeat(3)tick();check(!hold_reset);
    #2;board_reset_n=1;repeat(3)tick();check(!hold_reset);
    #2;core_request=1;tick();check(!hold_reset);tick();check(!hold_reset);tick();check(hold_reset);
    #2;core_request=0;
    repeat(16)begin tick();check(hold_reset);end
    tick();check(!hold_reset);repeat(4)tick();check(!hold_reset);
    #2;core_request=1;repeat(3)tick();check(hold_reset);
    #2;board_reset_n=0;#1;check(!hold_reset);
    $display("CE64_PLATFORM_RESET_PASS checks=%0d",checks);$finish;
  end
endmodule
