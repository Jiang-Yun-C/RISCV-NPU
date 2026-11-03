// Keep the existing independent traffic counters; replace only their UART.
wire [2047:0] phy_report;
ddr_phy_observer phy_observer (
  .clk(core_clk), .rst_n(core_clk_rst_n), .flags(status_bus_80),
  .errors({24'b0,err_cnt}), .write_beats(board_wbeats), .read_beats(board_rbeats),
  .aw_count(board_awcount), .ar_count(board_arcount), .calib(debug_calib_ctrl),
  .aux(status_bus_8a), .slice_status(dbg_slice_status),
  .slice_state(dbg_slice_state), .slice_data(debug_data), .report(phy_report)
);
ddr_phy_uart phy_uart (
  .clk(core_clk), .rst_n(core_clk_rst_n), .report(phy_report), .uart_txd(uart_txd)
);
