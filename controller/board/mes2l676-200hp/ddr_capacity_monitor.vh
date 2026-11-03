// Transmit-only telemetry; no asynchronous UART control/status bridge.
reg [31:0] board_wbeats, board_rbeats, board_awcount, board_arcount;
reg [31:0] board_max_awaddr, board_max_araddr;
wire [31:0] board_init_passes=capacity_verified_passes;
always @(posedge core_clk or negedge core_clk_rst_n) begin
  if (!core_clk_rst_n) begin
    board_wbeats<=0; board_rbeats<=0; board_awcount<=0; board_arcount<=0;
    board_max_awaddr<=0; board_max_araddr<=0;
  end else begin
    if (ddr_init_done && axi_wready) board_wbeats<=board_wbeats+1'b1;
    if (ddr_init_done && axi_rvalid) board_rbeats<=board_rbeats+1'b1;
    if (ddr_init_done && axi_awvalid && axi_awready) begin
      board_awcount<=board_awcount+1'b1;
      if ({4'b0,axi_awaddr}>board_max_awaddr) board_max_awaddr<={4'b0,axi_awaddr};
    end
    if (ddr_init_done && axi_arvalid && axi_arready) begin
      board_arcount<=board_arcount+1'b1;
      if ({4'b0,axi_araddr}>board_max_araddr) board_max_araddr<={4'b0,axi_araddr};
    end
  end
end
ddr_capacity_uart telemetry (
  .clk(core_clk), .rst_n(core_clk_rst_n), .flags(status_bus_80 | {28'd0,capacity_failed,capacity_masks_verified,capacity_full_verified,1'b0}),
  .errors(err_cnt), .write_beats(board_wbeats), .read_beats(board_rbeats),
  .aw_count(board_awcount), .ar_count(board_arcount),
  .max_awaddr(board_max_awaddr), .max_araddr(board_max_araddr),
  .init_passes(board_init_passes), .first_error_word_address(capacity_first_error_address),
  .phase_status(capacity_phase_status), .uart_txd(uart_txd)
);
