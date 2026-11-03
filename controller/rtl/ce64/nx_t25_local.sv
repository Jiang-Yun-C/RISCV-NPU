// T25 candidate local devices: retain the qualified CE local bus/UART/RAM,
// add the T18 SPI protocol, and drive the SoC model guard from the SD seal.
// Card-present polarity/pins are deliberately outside this digital boundary.
module nx_t25_local #(
  parameter ROM_FILE="", UART_DIVISOR=250, LOCAL_READ_PIPELINE=1, REQUEST_PMU=1
)(
  input wire clk,reset_n,ddr_init_done,uart_rx,platform_ready,
  input wire [31:0] platform_status,card_generation,
  input wire startup_trace_retire,
  input wire [31:0] startup_trace_pc,
  output wire startup_authorized,
  input wire [4095:0] telemetry,
  output wire led0,
  output wire [7:0] user_led_mask,user_led_value,
  output wire uart_tx,
  output wire uart_interrupt,timer_interrupt,
  output wire [63:0] debug_observe,
  input wire rom_enable,
  input wire [31:0] rom_address,
  output wire [31:0] rom_data,
  output wire model_sealed,
  output wire [31:0] selected_profile,
  output wire platform_reset_request,
  output wire [31:0] exit_code,report_tag,
  output wire exited,
  input wire sd_miso,
  output wire sd_sck,sd_cs_n,sd_mosi,
  axi4_if.slave local_i,local_d,local_n
);
  axi4_if #(.DATA_W(32),.ID_W(1)) devices(clk),spi_bus(clk);
  wire unused_uart_model_seal;
  wire [31:0] sd_ready,boot_error,boot_done,selftest,directory_count;
  wire sd_ready_one;
  // B/R completion retains the destination selected by the actual AW/AR;
  // a W offer before AW is held, and no held response changes its target.
  t17_uart_router #(.MMIO_BASE(32'h10002000)) spi_router(
    .clk,.reset(!reset_n),.cpu_bus(local_d),.memory_bus(devices),.uart_bus(spi_bus));
  t18_spi #(.EXPOSE_BOOT_STATUS(1)) sd(
    .clk,.reset(!reset_n),.miso(sd_miso),.card_generation,
    .ddr_ready(ddr_init_done&&platform_ready),.sck(sd_sck),.cs_n(sd_cs_n),.mosi(sd_mosi),
    .model_ready(sd_ready),.model_ready_one(sd_ready_one),.boot_error,.boot_done,.selftest,.directory_count,.bus(spi_bus));
  // The diagnostic UART loader's seal cannot authorize the T25 application.
  // The authenticated SD loader publishes only after all package checks/fences.
  assign model_sealed=sd_ready_one;
  // One physical boot capability. Only actual ROM execution plus the first
  // SD publication can grant it before the first non-ROM retirement. CPU
  // descriptor fields and the constant card_generation cannot grant/reopen it.
  reg startup_loader_seen,startup_left_loader,startup_publication_seen;
  reg startup_granted,startup_revoked;
  wire startup_pc_in_rom=startup_trace_pc>=32'h00010000&&startup_trace_pc<32'h00020000;
  assign startup_authorized=startup_granted&&!startup_revoked&&sd_ready_one&&ddr_init_done&&platform_ready;
  always @(posedge clk or negedge reset_n)begin
    if(!reset_n)begin
      startup_loader_seen<=0;startup_left_loader<=0;startup_publication_seen<=0;
      startup_granted<=0;startup_revoked<=0;
    end else begin
      if(startup_trace_retire)begin
        if(startup_pc_in_rom)startup_loader_seen<=1;
        else startup_left_loader<=1;
      end
      if(!startup_publication_seen&&sd_ready_one)begin
        startup_publication_seen<=1;
        if(startup_loader_seen&&!startup_left_loader&&ddr_init_done&&platform_ready&&
           (!startup_trace_retire||startup_pc_in_rom))startup_granted<=1;
        else startup_revoked<=1;
      end
      if(startup_granted&&(!sd_ready_one||!ddr_init_done||!platform_ready))startup_revoked<=1;
    end
  end
  nx_ce64_local #(.ROM_FILE(ROM_FILE),.UART_DIVISOR(UART_DIVISOR),.PRELOAD_MODE(0),.LOCAL_READ_PIPELINE(LOCAL_READ_PIPELINE),.REQUEST_PMU(REQUEST_PMU)) core(
    .clk,.reset_n,.ddr_init_done,.uart_rx,.platform_ready,.platform_status,.telemetry,.uart_tx,.uart_interrupt,.timer_interrupt,.debug_observe,
    .rom_enable,.rom_address,.rom_data,.model_sealed(unused_uart_model_seal),.selected_profile,
    .led0,.user_led_mask,.user_led_value,.platform_reset_request,.exit_code,.report_tag,.exited,.local_i,.local_d(devices),.local_n);
endmodule
