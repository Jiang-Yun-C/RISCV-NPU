// T25 digital board candidate. Physical SD pins and a new image are NOT qualified.
// Derived from the T24 board logic; preserves full-capacity/mask BIST and native1024.
// Complete digital board logic; the outer native200H shell supplies the
// unchanged vendor HMIC1.10/PHY/PLL and board pins. UART bootstrap is CPU code.
module nx_t25_board_logic #(
 parameter ROM_FILE="", UART_DIVISOR=1085, ENABLE_CE=1, LOCAL_READ_PIPELINE=1, ENABLE_REQUEST_PMU=1, LONG_PV=1, HEAD_ARGMAX=1
)(input wire clk,reset_n,ddr_init_done,uart_rxd,
 input wire sd_miso,
 output wire sd_sck,sd_mosi,sd_cs_n,
 input wire [31:0] phy_status,
 output wire led0,
 output wire [7:0] user_led_mask,user_led_value,
  output wire uart_txd,platform_reset_request,
 output wire [31:0] full_errors,full_passes,full_first_error,full_phase,
 output wire full_verified,masks_verified,full_failed,
 output wire [31:0] debug_address,debug_stalled,debug_reason,
 output wire [255:0] debug_expected,
 output wire [3:0] debug_beat,
  output wire [27:0] d_awaddr, d_araddr,
  output wire [3:0] d_awid, d_arid, d_awlen, d_arlen,
  output wire d_awvalid, d_arvalid,
  input wire d_awready, d_arready, d_wready, d_wlast,
  output wire [255:0] d_wdata,
  output wire [31:0] d_wstrb,
  input wire [255:0] d_rdata,
  input wire [3:0] d_rid,
  input wire d_rvalid, d_rlast);
 axi4_if #(.DATA_W(32),.ID_W(1)) local_i(clk),local_d(clk);
 axi4_if #(.DATA_W(128),.ID_W(6)) local_n(clk),auxiliary(clk),full_bus(clk),stress_bus(clk),pressure_source(clk);
 wire [31:0] rom_data,rom_address,exit_code,report_tag;
 wire rom_enable,trace_retire,owner,irq,backend_idle,ddr_fault,model_sealed,exited;
 wire [31:0] trace_pc;
 wire startup_authorized;
 wire [3:0] ddr_fault_reason;
 wire [63:0] ddr_cycles,ddr_write_bytes,ddr_read_bytes,native_write_bytes,native_read_bytes;
 wire [255:0] cpu_i_stats,cpu_d_stats,ce_stats,pressure_stats;
 wire native_quarantine_status;
 wire [31:0] selected_profile;
 wire [4095:0] telemetry;
 wire [2047:0] request_pmu_stats;
 assign telemetry={request_pmu_stats,pressure_stats,ce_stats,cpu_d_stats,cpu_i_stats,192'b0,
   native_read_bytes,native_write_bytes,ddr_read_bytes,ddr_write_bytes,ddr_cycles,
   28'b0,ddr_fault_reason,stress_workload,stress_first_error,stress_passes,stress_errors,stress_phase,
   full_first_error,full_passes,full_errors,full_phase,reference_ticks,phy_status,
   22'b0,model_sealed,backend_idle,owner,native_quarantine_status,ddr_fault,stress_failed,full_failed,masks_verified,full_verified,ddr_init_done,
   32'd2,32'h34364543};
 nx_ce64_bus_stats ps(.clk,.reset_n,.bus(stress_bus),.stats(pressure_stats));
 reg [63:0] reference_ticks;
 always @(posedge clk or negedge reset_n)if(!reset_n)reference_ticks<=0;else reference_ticks<=reference_ticks+1'b1;
 wire timerInterrupt,uartInterrupt;
 wire [191:0] debug_soc;
 wire [63:0] debug_local;
 // Kept through the qualified lowering flow, then connected by Fabric Inserter.
 // Exactly one observation-register cycle of latency on all 256 channels.
 (* keep=1, syn_keep=1, syn_preserve=1 *) reg [255:0] irq_debug_sample;
 always @(posedge clk) irq_debug_sample<={debug_local,debug_soc};
 wire full_stopped,stress_stopped,stress_failed,stress_verified,stress_masks;
 wire [31:0] stress_errors,stress_passes,stress_first_error,stress_phase,stress_address,stress_stalled,stress_reason,stress_workload,full_workload;
 wire [255:0] stress_expected;
 wire [3:0] stress_beat;
 wire [63:0] stress_workload_cycles,full_workload_cycles;
 wire platform_ready=full_stopped&&full_verified&&masks_verified&&!full_failed;
 nx_soc_ce64 #(.WRITE_DRAIN_CYCLES(1024),.ENABLE_TEST_CONTROL(1),.ENABLE_CE(ENABLE_CE),.ENABLE_REQUEST_PMU(ENABLE_REQUEST_PMU),.LONG_PV(LONG_PV),.HEAD_ARGMAX(HEAD_ARGMAX)) soc(
  .clk,.reset_n,.ddr_init_done,.timerInterrupt,.uartInterrupt,.model_sealed,.startup_authorized,.rom_data,.rom_enable,.rom_address,
  .trace_retire,.trace_pc,.debug_observe(debug_soc),.accel_owner(owner),.accel_irq(irq),.backend_idle_status(backend_idle),
  .cpu_i_stats,.cpu_d_stats,.ce_stats,.request_pmu_stats,.native_quarantine_status,
  .ddr_fault_status(ddr_fault),.local_i,.local_d,.local_n,.auxiliary,
  .d_awaddr,.d_araddr,.d_awid,.d_arid,.d_awlen,.d_arlen,.d_awvalid,.d_arvalid,.d_awready,.d_arready,
  .d_wready,.d_wlast,.d_wdata,.d_wstrb,.d_rdata,.d_rid,.d_rvalid,.d_rlast,
  .ddr_fault_reason,.ddr_cycles,.ddr_write_bytes,.ddr_read_bytes,.native_write_bytes,.native_read_bytes);
 nx_t25_local #(.ROM_FILE(ROM_FILE),.UART_DIVISOR(UART_DIVISOR),.LOCAL_READ_PIPELINE(LOCAL_READ_PIPELINE),.REQUEST_PMU(ENABLE_REQUEST_PMU)) peripherals(
  .sd_miso,.sd_sck,.sd_mosi,.sd_cs_n,.card_generation(32'd1),
  .startup_trace_retire(trace_retire),.startup_trace_pc(trace_pc),.startup_authorized,
  .clk,.reset_n,.ddr_init_done,.platform_ready,.telemetry,.platform_status({full_phase[15:0],stress_errors[7:0],3'b0,ddr_fault,stress_failed,full_failed,masks_verified,full_verified}),
  .uart_rx(uart_rxd),.uart_tx(uart_txd),.uart_interrupt(uartInterrupt),.timer_interrupt(timerInterrupt),.debug_observe(debug_local),.rom_enable,.rom_address,.rom_data,.model_sealed,.selected_profile,
  .led0,.user_led_mask,.user_led_value,.platform_reset_request,.exit_code,.report_tag,.exited,.local_i,.local_d,.local_n);
 nx_ce64_aux_mux platform_mux(.clk,.reset_n,.ce(full_bus),.aux(stress_bus),.memory(auxiliary),
   .ce_w_capture(1'b0),.memory_w_capture());
 ce64_axi_bist #(.WINDOW_BITS(30),.BASE_ADDRESS(32'h80000000)) capacity_bist(.clk,.rst_n(reset_n),.ddr_init_done,.fault(ddr_fault),.enable(!masks_verified),.stopped(full_stopped),
.s_awaddr(full_bus.awaddr),.s_araddr(full_bus.araddr),.s_awid(full_bus.awid),.s_arid(full_bus.arid),.s_awlen(full_bus.awlen),.s_arlen(full_bus.arlen),.s_awsize(full_bus.awsize),.s_arsize(full_bus.arsize),.s_awburst(full_bus.awburst),.s_arburst(full_bus.arburst),.s_awvalid(full_bus.awvalid),.s_arvalid(full_bus.arvalid),.s_wvalid(full_bus.wvalid),.s_wlast(full_bus.wlast),.s_bready(full_bus.bready),.s_rready(full_bus.rready),.s_wdata(full_bus.wdata),.s_wstrb(full_bus.wstrb),.s_awready(full_bus.awready),.s_arready(full_bus.arready),.s_wready(full_bus.wready),.s_bvalid(full_bus.bvalid),.s_rvalid(full_bus.rvalid),.s_rlast(full_bus.rlast),.s_bid(full_bus.bid),.s_rid(full_bus.rid),.s_bresp(full_bus.bresp),.s_rresp(full_bus.rresp),.s_rdata(full_bus.rdata),
 .errors(full_errors),.verified_passes(full_passes),.first_error_word_address(full_first_error),.full_range_verified(full_verified),.byte_masks_verified(masks_verified),.failed(full_failed),.phase_status(full_phase),.debug_address,.debug_stalled,.debug_reason,.debug_expected,.debug_beat,.workload(full_workload),.workload_cycles(full_workload_cycles));
 t25_pressure_gate #(.GAP_CYCLES(8192)) pressure_gate(.clk,.reset_n,.source_bus(pressure_source),.memory(stress_bus));
 ce64_axi_bist #(.WINDOW_BITS(24),.BASE_ADDRESS(32'had000000)) pressure_bist(.clk,.rst_n(reset_n),.ddr_init_done,.fault(ddr_fault),.enable(model_sealed&&platform_ready&&(selected_profile==2||selected_profile==3)),.stopped(stress_stopped),
.s_awaddr(pressure_source.awaddr),.s_araddr(pressure_source.araddr),.s_awid(pressure_source.awid),.s_arid(pressure_source.arid),.s_awlen(pressure_source.awlen),.s_arlen(pressure_source.arlen),.s_awsize(pressure_source.awsize),.s_arsize(pressure_source.arsize),.s_awburst(pressure_source.awburst),.s_arburst(pressure_source.arburst),.s_awvalid(pressure_source.awvalid),.s_arvalid(pressure_source.arvalid),.s_wvalid(pressure_source.wvalid),.s_wlast(pressure_source.wlast),.s_bready(pressure_source.bready),.s_rready(pressure_source.rready),.s_wdata(pressure_source.wdata),.s_wstrb(pressure_source.wstrb),.s_awready(pressure_source.awready),.s_arready(pressure_source.arready),.s_wready(pressure_source.wready),.s_bvalid(pressure_source.bvalid),.s_rvalid(pressure_source.rvalid),.s_rlast(pressure_source.rlast),.s_bid(pressure_source.bid),.s_rid(pressure_source.rid),.s_bresp(pressure_source.bresp),.s_rresp(pressure_source.rresp),.s_rdata(pressure_source.rdata),
 .errors(stress_errors),.verified_passes(stress_passes),.first_error_word_address(stress_first_error),.full_range_verified(stress_verified),.byte_masks_verified(stress_masks),.failed(stress_failed),.phase_status(stress_phase),.debug_address(stress_address),.debug_stalled(stress_stalled),.debug_reason(stress_reason),.debug_expected(stress_expected),.debug_beat(stress_beat),.workload(stress_workload),.workload_cycles(stress_workload_cycles));
endmodule
