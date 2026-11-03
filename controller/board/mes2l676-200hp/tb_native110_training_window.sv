`timescale 1ns/1ps
// Coupled, unmodified vendor read-calibration/reset controllers. This checks
// the command quiet window; it does not model DQS or qualify hardware timing.
module tb_native110_training_window;
  reg clk = 0, rstn = 0, start = 0, debug_mode = 0;
  always #4.000 clk = ~clk;
  wire req, ack, train_rstn, gate_start, gate_move, rd_done;
  wire csn, rasn, casn, wen;
  wire [4:0] state;
  reg gate_pass = 0; reg retry_pending=0;
  always @(negedge train_rstn) if (rstn && start) retry_pending=1;
  integer reset_releases = 0, checked_reads = 0, retries = 0;
  real last_release_ns = -1, minimum_read_gap_ns = 1.0e9;
  ips2l_ddrphy_training_ctrl_v1_0 training (
    .ddrphy_sysclk(clk), .ddrphy_rst_n(rstn), .ddrphy_rst_req(req),
    .ddrphy_rst_ack(ack), .ddrphy_dqs_training_rstn(train_rstn)
  );
  ips2l_ddrphy_rdcal_v1_10 #(.MEM_ADDR_WIDTH(15), .MEM_DQ_WIDTH(32)) rdcal (
    .mc_wl(5'd6), .ddrphy_sysclk(clk), .ddrphy_rst_n(rstn),
    .rdcal_start(start), .rdcal_done(rd_done), .ddrphy_rst_req(req),
    .ddrphy_rst_ack(ack), .gatecal_start(gate_start),
    .gate_check_pass(gate_pass), .gate_adj_done(state==8),
    .gate_cal_error(1'b0), .gate_move_en(gate_move),
    .rddata_check_pass(1'b1), .adj_rdel_done(1'b1),
    .rdel_calib_done(1'b1), .rdel_calib_error(1'b0), .rdel_move_done(1'b1),
    .write_debug(1'b0), .dqgt_debug(debug_mode), .rdel_rd_cnt(8'd0),
    .dbg_rdcal(state), .rdcal_cs_n(csn), .rdcal_ras_n(rasn),
    .rdcal_cas_n(casn), .rdcal_we_n(wen)
  );
  always @(posedge train_rstn) begin
    if (rstn) begin
      reset_releases = reset_releases + 1;
      last_release_ns = $realtime;
      if (retry_pending) begin retries = retries + 1; retry_pending=0; end
    end
  end
  always @(negedge clk) begin
    if (rstn && !csn && rasn && !casn && wen) begin
      if (!train_rstn) $fatal(1, "Read command while training reset is asserted");
      if (last_release_ns >= 0) begin
        checked_reads = checked_reads + 1;
        if ($realtime-last_release_ns < minimum_read_gap_ns)
          minimum_read_gap_ns = $realtime-last_release_ns;
        if ($realtime-last_release_ns < 2.0*8.000)
          $fatal(1, "Insufficient reset release to read command gap");
      end
    end
  end
  task run_case(input bit debug_setting);
    integer baseline;
    begin
      @(negedge clk); rstn=0; start=0; gate_pass=0;
      repeat(5) @(negedge clk);
      debug_mode=debug_setting; rstn=1;
      repeat(5) @(negedge clk); start=1;
      baseline=checked_reads;
      $display("CASE_START debug=%b releases=%d retries=%d reads=%d",debug_setting,reset_releases,retries,checked_reads);
      wait(checked_reads >= baseline+32);
      $display("CASE_WINDOW debug=%b releases=%d retries=%d reads=%d",debug_setting,reset_releases,retries,checked_reads);
      if (!debug_setting) begin
        @(negedge clk); gate_pass=1;
        repeat(300) @(negedge clk);
      end else repeat(20) @(negedge clk);
    end
  endtask
  initial begin
    run_case(0); run_case(1);
    if (retries<8 || checked_reads<64) $fatal(1,"Insufficient coverage");
    $display("NATIVE110_TRAINING_COMMAND_WINDOW_PASS releases=%0d retries=%0d reads=%0d min_read_gap_ns=%0.6f PHY_STUB=1 BOARD_TEST=0",
             reset_releases,retries,checked_reads,minimum_read_gap_ns);
    $finish;
  end
  initial begin #200000; $display("AUDIT_TIMEOUT releases=%d retries=%d reads=%d",reset_releases,retries,checked_reads); $fatal(1,"Training command window timeout"); end
endmodule
