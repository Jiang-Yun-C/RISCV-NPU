`timescale 1ns/1ps
// Audit the actual protected native CPD controller, with synthetic PLL/phase
// responses. This is a controller settling-window check, not hard-PHY timing.
module tb_native110_cpd_window;
  reg clk=0, rstn=0, start=0, phase_up=0, locked=0, dps_done=0;
  reg offset_adj=0, offset_dir=0;
  reg [9:0] offset=0;
  always #4 clk=~clk;
  wire cpd_rstn, done, dps_en, dps_dir;
  wire [3:0] state;
  wire [9:0] dir0_count, dir1_count;
  integer releases=0, moves=0, acknowledgements=0;
  real last_release=-1, minimum_decision_gap=1.0e9;
  ips2l_ddrphy_cpd_ctrl_v1_3 dut (
    .dps_clk(clk),.ddr_rstn(rstn),.ddrphy_cpd_start(start),
    .ddrphy_cpd_up_dnb(phase_up),.ddrphy_cpd_lock(locked),
    .gpll_dps_done(dps_done),.ddrphy_cpd_rstn(cpd_rstn),
    .ddrphy_cpd_done(done),.gpll_dps_en(dps_en),.gpll_dps_dir(dps_dir),
    .debug_cpd_offset_adj(offset_adj),.debug_cpd_offset_dir(offset_dir),
    .debug_cpd_offset(offset),.debug_cpd_state(state),
    .debug_dps_cnt_dir0(dir0_count),.debug_dps_cnt_dir1(dir1_count)
  );
  always @(posedge cpd_rstn) if(rstn) begin
    releases=releases+1; last_release=$realtime;
  end
  always @(posedge dps_en) if(rstn) begin
    moves=moves+1;
    if(last_release>=0) begin
      if($realtime-last_release < minimum_decision_gap)
        minimum_decision_gap=$realtime-last_release;
      if($realtime-last_release < 16)
        $fatal(1,"CPD phase decision before bounded reset settling window");
    end
  end
  always @(posedge done) if(rstn && last_release>=0) begin
    if($realtime-last_release < 16)
      $fatal(1,"CPD completion before bounded reset settling window");
    acknowledgements=acknowledgements+1;
  end
  integer response_age=0;
  reg response_pending=0;
  always @(posedge dps_en) if(rstn) begin response_pending=1; response_age=0; end
  always @(negedge clk) begin
    if(!rstn) begin response_age=0; dps_done=0; response_pending=0; end
    else if(response_pending) begin
      response_age=response_age+1;
      if(response_age==12) dps_done=1;
      if(response_age==16) begin dps_done=0; response_pending=0; end
    end
    // A synthetic phase indication changes between adjustment iterations;
    // the real hard macro remains outside this controller audit.
    if(!cpd_rstn) phase_up=~dps_dir;
  end
  task run_case(input bit direction);
    integer baseline_moves;
    begin
      @(negedge clk); rstn=0; start=0; locked=0; offset_adj=0;
      repeat(6) @(negedge clk); rstn=1; phase_up=direction;
      repeat(6) @(negedge clk); baseline_moves=moves; start=1;
      $display("CPD_CASE_START direction=%b",direction);
      wait(moves>=baseline_moves+3);
      @(negedge clk); locked=1; phase_up=0;
      wait(done);
      repeat(20) @(negedge clk);
      offset_dir=direction; offset=3; offset_adj=1;
      repeat(6) @(negedge clk); offset_adj=0;
      wait(!done); wait(done);
      repeat(20) @(negedge clk);
    end
  endtask
  initial begin
    run_case(0); run_case(1);
    if(releases<2 || moves<12 || acknowledgements<4)
      $fatal(1,"Insufficient CPD reset/phase coverage");
    $display("NATIVE110_CPD_WINDOW_PASS releases=%d moves=%d completions=%d min_release_to_decision_ns=%0.3f BOARD_TEST=0",releases,moves,acknowledgements,minimum_decision_gap);
    $finish;
  end
  initial begin #1000000; $display("CPD_TIMEOUT state=%d releases=%d moves=%d completions=%d",state,releases,moves,acknowledgements); $fatal(1,"CPD controller audit timed out"); end
endmodule
