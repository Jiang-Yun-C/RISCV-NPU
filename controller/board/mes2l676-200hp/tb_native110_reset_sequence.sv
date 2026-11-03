`timescale 1ns/1ps
// Audit vendor reset sequencing. No PHY or board calibration is simulated.
module tb_native110_reset_sequence #(
  parameter real RST_PERIOD_NS = 8.000
);
  reg rst_clk = 0, sysclk = 0, board_rstn = 0;
  always #(RST_PERIOD_NS/2.0) rst_clk = ~rst_clk;
  always #4.000 sysclk = ~sysclk;
  reg pll_lock = 0, dll_lock = 0, dll_ack = 0, cpd_done = 0;
  reg dbg_gate = 0, training_error = 0;
  wire dll_req, cpd_start, phy_pll_rst, dqs_rst, iol_rst, phy_rstn;
  wire [2:0] gates;
  wire [3:0] state;
  integer dqs_releases = 0, iol_releases = 0, gated_dqs_releases = 0;
  integer gate_age = 0, ack_delay = 0, cpd_delay = 0;
  real last_gated_release_ns = -1.0, min_gate_release_gap_ns = 1.0e9;
  ips2l_ddrphy_reset_ctrl_v1_3 reset_ctrl (
    .ddr_rstn(board_rstn), .rst_clk(rst_clk), .ddrphy_sysclk(sysclk),
    .dll_lock(dll_lock), .pll_lock(pll_lock),
    .dbg_gpll_scan_rst(1'b0), .dbg_gate_start(dbg_gate),
    .dbg_cpd_start(1'b0), .dbg_ddrphy_rst_n(1'b1),
    .rst_clk_adj_start(), .rst_clk_adj_done(1'b1), .tran_err_rst_cnt(),
    .ddrphy_init_fail(), .ddrphy_cpd_done(cpd_done),
    .training_error(training_error), .ddrphy_calib_done(1'b0),
    .ddrphy_cpd_start(cpd_start), .dll_update_req_rst_ctrl(dll_req),
    .dll_update_ack_rst_ctrl(dll_ack), .dll_tran_update_en(),
    .logic_rstn(), .phy_pll_rst(phy_pll_rst), .ddrphy_dll_rst_n(),
    .ddrphy_rst_n(phy_rstn), .ddrphy_iol_rst(iol_rst),
    .ddrphy_dqs_rst(dqs_rst), .ddrphy_ioclk_gate(gates),
    .debug_rst_state(state)
  );
  // Respond to DLL/CPD requests with deliberate delays.
  always @(negedge rst_clk) begin
    if (!board_rstn) begin
      dll_ack = 0; cpd_done = 0; ack_delay = 0; cpd_delay = 0;
    end else begin
      if (dll_req) begin
        ack_delay = ack_delay + 1;
        if (ack_delay >= 5) dll_ack = 1;
      end else begin dll_ack = 0; ack_delay = 0; end
      if (state == 9) begin
        cpd_delay = cpd_delay + 1;
        if (cpd_delay >= 8) cpd_done = 1;
      end else begin cpd_delay = 0; cpd_done = 0; end
    end
    if (gates == 3'b111) gate_age = gate_age + 1;
    else gate_age = 0;
  end
  always @(negedge dqs_rst) begin
    #0.001;
    if (board_rstn) begin
      dqs_releases = dqs_releases + 1;
      if (!phy_pll_rst) begin
        if (gates !== 3'b111 || gate_age < 3)
          $fatal(1, "DQS reset released with active/insufficiently gated PHY clocks");
        gated_dqs_releases = gated_dqs_releases + 1;
        last_gated_release_ns = $realtime;
      end
    end
  end
  always @(negedge iol_rst) begin
    #0.001;
    if (board_rstn) begin
      iol_releases = iol_releases + 1;
      if (!phy_pll_rst && (gates !== 3'b111 || gate_age < 3))
        $fatal(1, "IOL reset released with active/insufficiently gated PHY clocks");
      if (!phy_pll_rst) last_gated_release_ns = $realtime;
    end
  end
  always @(gates) begin
    if (gates != 3'b111 && last_gated_release_ns >= 0.0) begin
      if ($realtime-last_gated_release_ns < 3.0*RST_PERIOD_NS)
        $fatal(1,"PHY clocks resumed before bounded reset propagation window");
      if ($realtime-last_gated_release_ns < min_gate_release_gap_ns)
        min_gate_release_gap_ns = $realtime-last_gated_release_ns;
      last_gated_release_ns = -1.0;
    end
  end

  reg train_req = 0;
  wire train_ack, train_rstn;
  integer train_acks = 0, train_low_cycles = 0, train_pulses = 0;
  reg prev_train_ack = 0, prev_train_rstn = 0, train_running = 0;
  ips2l_ddrphy_training_ctrl_v1_0 training_ctrl (
    .ddrphy_sysclk(sysclk), .ddrphy_rst_n(phy_rstn),
    .ddrphy_rst_req(train_req), .ddrphy_rst_ack(train_ack),
    .ddrphy_dqs_training_rstn(train_rstn)
  );
  always @(negedge sysclk) begin
    if (!phy_rstn) begin
      train_low_cycles = 0; prev_train_ack = 0; prev_train_rstn = 0;
      train_running = 0;
    end else begin
      if (train_ack && prev_train_ack) $fatal(1, "Training ACK exceeds one cycle");
      if (train_ack) train_acks = train_acks + 1;
      if (!train_rstn && train_running) train_low_cycles = train_low_cycles + 1;
      if (train_rstn && !prev_train_rstn && train_running && train_low_cycles != 0) begin
        if (train_low_cycles != 3) $fatal(1, "Training reset pulse has wrong duration");
        train_pulses = train_pulses + 1;
        train_low_cycles = 0;
      end
      if (train_rstn) train_running = 1;
      prev_train_ack = train_ack; prev_train_rstn = train_rstn;
    end
  end
  task automatic training_request;
    integer old_acks;
    begin
      repeat (10) @(negedge sysclk);
      old_acks = train_acks;
      train_req = 1;
      repeat (15) @(negedge sysclk);
      train_req = 0;
      repeat (10) @(negedge sysclk);
      if (train_acks != old_acks + 1) $fatal(1, "Training request lost or duplicated");
    end
  endtask
  initial begin
    #100 board_rstn = 1;
    #100 pll_lock = 1;
    #170 dll_lock = 1;
    wait (phy_rstn); repeat (10) @(negedge sysclk);
    training_request(); training_request();
    // Exercise the supported debug gate/restart sequence.
    dbg_gate = 1; repeat (6) @(negedge rst_clk); dbg_gate = 0;
    wait (!phy_rstn); wait (phy_rstn);
    training_request();
    // Repeat power/reset sequencing while the controller had been running.
    board_rstn = 0; repeat (8) @(negedge rst_clk); board_rstn = 1;
    wait (phy_rstn); training_request();
    if (dqs_releases < 5 || iol_releases < 5 || gated_dqs_releases < 3 || train_pulses != 4)
      $fatal(1, "Insufficient reset/training sequence coverage");
    $display("NATIVE110_RESET_SEQUENCE_PASS dqs_releases=%0d iol_releases=%0d gated_dqs=%0d training_pulses=%0d min_release_to_ungate_ns=%0.3f",
      dqs_releases, iol_releases, gated_dqs_releases, train_pulses,min_gate_release_gap_ns);
    $finish;
  end
  initial begin #20000000; $fatal(1, "Vendor reset sequence timed out"); end
endmodule
