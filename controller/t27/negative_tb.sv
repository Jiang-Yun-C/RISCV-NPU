`timescale 1ns/1ps
module tb_cpu;
  parameter bit LOCAL_READ_PIPELINE=1, ENABLE_REQUEST_PMU=1, LONG_PV=1, HEAD_ARGMAX=1;
 bit negative_case=0;initial negative_case=$test$plusargs("negative_case");
logic  timerInterrupt;
logic  externalInterrupt;
logic  softwareInterrupt;
wire  trace_predictor_ready;
wire  rom_enable;
wire [31:0] rom_address;
logic [31:0] rom_data;
wire  iAxi_ar_valid;
logic  iAxi_ar_ready;
wire [31:0] iAxi_ar_payload_addr;
wire [7:0] iAxi_ar_payload_len;
wire [1:0] iAxi_ar_payload_burst;
wire [3:0] iAxi_ar_payload_cache;
wire [2:0] iAxi_ar_payload_prot;
logic  iAxi_r_valid;
wire  iAxi_r_ready;
logic [31:0] iAxi_r_payload_data;
logic [1:0] iAxi_r_payload_resp;
logic  iAxi_r_payload_last;
wire  dAxi_aw_valid;
logic  dAxi_aw_ready;
wire [31:0] dAxi_aw_payload_addr;
wire [7:0] dAxi_aw_payload_len;
wire [2:0] dAxi_aw_payload_size;
wire [3:0] dAxi_aw_payload_cache;
wire [2:0] dAxi_aw_payload_prot;
wire  dAxi_w_valid;
logic  dAxi_w_ready;
wire [31:0] dAxi_w_payload_data;
wire [3:0] dAxi_w_payload_strb;
wire  dAxi_w_payload_last;
logic  dAxi_b_valid;
wire  dAxi_b_ready;
logic [1:0] dAxi_b_payload_resp;
wire  dAxi_ar_valid;
logic  dAxi_ar_ready;
wire [31:0] dAxi_ar_payload_addr;
wire [7:0] dAxi_ar_payload_len;
wire [2:0] dAxi_ar_payload_size;
wire [3:0] dAxi_ar_payload_cache;
wire [2:0] dAxi_ar_payload_prot;
logic  dAxi_r_valid;
wire  dAxi_r_ready;
logic [31:0] dAxi_r_payload_data;
logic [1:0] dAxi_r_payload_resp;
logic  dAxi_r_payload_last;
wire  trace_retire;
wire [31:0] trace_pc;
wire [31:0] trace_instruction;
wire  trace_stall;
wire  trace_branch;
wire [31:0] trace_branch_pc;
wire  trace_mispredict;
logic  clk;
logic  reset;
// Simulation shell around the same core used by PDS; faults are testbench forces.
  longint unsigned cycles=0,retired=0;
  int unsigned seed=1,delay_limit=3,max_cycles=80000000;
  int test_mode=0;
  logic[31:0] injection_address=0,hold_address=0,launches=0;
  bit head_run=0;
  logic negative_early=0,negative_stale=0,previous_irq=0,prev_halted=0;
  logic[63:0] irq_due=0,hold_until=0;
  axi4_if #(.DATA_W(32),.ID_W(1)) imem(clk),cpu_bus(clk),dmem(clk),imem_port(clk),dmem_port(clk),local_i(clk),local_d(clk);
  axi4_if #(.DATA_W(128),.ID_W(6)) native(clk),backend(clk),external_mem(clk),nmem(clk),arb_nmem(clk),local_n(clk);
  axi4_if #(.DATA_W(128),.ID_W(6)) auxiliary(clk);
  assign auxiliary.awvalid=0;assign auxiliary.awaddr=0;assign auxiliary.awid=0;assign auxiliary.awlen=0;
  assign auxiliary.awsize=4;assign auxiliary.awburst=1;assign auxiliary.wvalid=0;assign auxiliary.wdata=0;
  assign auxiliary.wstrb=0;assign auxiliary.wlast=1;assign auxiliary.bready=1;
  assign auxiliary.arvalid=0;assign auxiliary.araddr=0;assign auxiliary.arid=0;assign auxiliary.arlen=0;
  assign auxiliary.arsize=4;assign auxiliary.arburst=1;assign auxiliary.rready=1;
  wire owner,isolate,backend_idle,backend_error,irq,backend_irq,halted,fault,wfi,core_running;
  wire[31:0] backend_fault;
  wire [27:0] d_awaddr,d_araddr;
  wire [3:0] d_awid,d_arid,d_awlen,d_arlen;
  wire d_awvalid,d_arvalid,d_awready,d_arready,d_wready,d_wlast;
  wire [255:0] d_wdata,d_rdata;
  wire [31:0] d_wstrb;
  wire [3:0] d_rid;
  wire d_rvalid,d_rlast,ddr_fault;
  wire [3:0] ddr_fault_reason;
  wire [63:0] ddr_cycles,ddr_write_bytes,ddr_read_bytes,native_write_bytes,native_read_bytes;
  wire [2047:0] request_pmu_stats;
  wire ddr_init_done=!reset && cycles>=500;
wire model_sealed,platform_reset_request;
wire board_tx;wire [31:0] board_exit,board_report;wire board_exited;
  nx_soc_ce64 #(.ENABLE_REQUEST_PMU(ENABLE_REQUEST_PMU),.LONG_PV(LONG_PV),.HEAD_ARGMAX(HEAD_ARGMAX),.WRITE_DRAIN_CYCLES(1024),.ENABLE_TEST_CONTROL(1)) soc(.clk,.reset_n(!reset),.ddr_init_done,.timerInterrupt,.model_sealed(model_sealed),.startup_authorized(1'b0),.auxiliary,
    .rom_data,.rom_enable,.rom_address,.trace_retire,.trace_pc,.request_pmu_stats,.accel_owner(owner),.accel_irq(irq),
    .backend_idle_status(backend_idle),.ddr_fault_status(ddr_fault),.local_i,.local_d,.local_n,
    .d_awaddr,.d_araddr,.d_awid,.d_arid,.d_awlen,.d_arlen,.d_awvalid,.d_arvalid,.d_awready,.d_arready,.d_wready,.d_wlast,
    .d_wdata,.d_wstrb,.d_rdata,.d_rid,.d_rvalid,.d_rlast,.ddr_fault_reason,.ddr_cycles,.ddr_write_bytes,.ddr_read_bytes,.native_write_bytes,.native_read_bytes);
  assign imem.awaddr=soc.imem.awaddr;
  assign imem.araddr=soc.imem.araddr;
  assign imem.awid=soc.imem.awid;
  assign imem.arid=soc.imem.arid;
  assign imem.bid=soc.imem.bid;
  assign imem.rid=soc.imem.rid;
  assign imem.awlen=soc.imem.awlen;
  assign imem.arlen=soc.imem.arlen;
  assign imem.awsize=soc.imem.awsize;
  assign imem.arsize=soc.imem.arsize;
  assign imem.awburst=soc.imem.awburst;
  assign imem.arburst=soc.imem.arburst;
  assign imem.bresp=soc.imem.bresp;
  assign imem.rresp=soc.imem.rresp;
  assign imem.awvalid=soc.imem.awvalid;
  assign imem.awready=soc.imem.awready;
  assign imem.wvalid=soc.imem.wvalid;
  assign imem.wready=soc.imem.wready;
  assign imem.wlast=soc.imem.wlast;
  assign imem.bvalid=soc.imem.bvalid;
  assign imem.bready=soc.imem.bready;
  assign imem.arvalid=soc.imem.arvalid;
  assign imem.arready=soc.imem.arready;
  assign imem.rvalid=soc.imem.rvalid;
  assign imem.rready=soc.imem.rready;
  assign imem.rlast=soc.imem.rlast;
  assign imem.wdata=soc.imem.wdata;
  assign imem.rdata=soc.imem.rdata;
  assign imem.wstrb=soc.imem.wstrb;
  assign cpu_bus.awaddr=soc.cpu_bus.awaddr;
  assign cpu_bus.araddr=soc.cpu_bus.araddr;
  assign cpu_bus.awid=soc.cpu_bus.awid;
  assign cpu_bus.arid=soc.cpu_bus.arid;
  assign cpu_bus.bid=soc.cpu_bus.bid;
  assign cpu_bus.rid=soc.cpu_bus.rid;
  assign cpu_bus.awlen=soc.cpu_bus.awlen;
  assign cpu_bus.arlen=soc.cpu_bus.arlen;
  assign cpu_bus.awsize=soc.cpu_bus.awsize;
  assign cpu_bus.arsize=soc.cpu_bus.arsize;
  assign cpu_bus.awburst=soc.cpu_bus.awburst;
  assign cpu_bus.arburst=soc.cpu_bus.arburst;
  assign cpu_bus.bresp=soc.cpu_bus.bresp;
  assign cpu_bus.rresp=soc.cpu_bus.rresp;
  assign cpu_bus.awvalid=soc.cpu_bus.awvalid;
  assign cpu_bus.awready=soc.cpu_bus.awready;
  assign cpu_bus.wvalid=soc.cpu_bus.wvalid;
  assign cpu_bus.wready=soc.cpu_bus.wready;
  assign cpu_bus.wlast=soc.cpu_bus.wlast;
  assign cpu_bus.bvalid=soc.cpu_bus.bvalid;
  assign cpu_bus.bready=soc.cpu_bus.bready;
  assign cpu_bus.arvalid=soc.cpu_bus.arvalid;
  assign cpu_bus.arready=soc.cpu_bus.arready;
  assign cpu_bus.rvalid=soc.cpu_bus.rvalid;
  assign cpu_bus.rready=soc.cpu_bus.rready;
  assign cpu_bus.rlast=soc.cpu_bus.rlast;
  assign cpu_bus.wdata=soc.cpu_bus.wdata;
  assign cpu_bus.rdata=soc.cpu_bus.rdata;
  assign cpu_bus.wstrb=soc.cpu_bus.wstrb;
  assign dmem.awaddr=soc.dmem.awaddr;
  assign dmem.araddr=soc.dmem.araddr;
  assign dmem.awid=soc.dmem.awid;
  assign dmem.arid=soc.dmem.arid;
  assign dmem.bid=soc.dmem.bid;
  assign dmem.rid=soc.dmem.rid;
  assign dmem.awlen=soc.dmem.awlen;
  assign dmem.arlen=soc.dmem.arlen;
  assign dmem.awsize=soc.dmem.awsize;
  assign dmem.arsize=soc.dmem.arsize;
  assign dmem.awburst=soc.dmem.awburst;
  assign dmem.arburst=soc.dmem.arburst;
  assign dmem.bresp=soc.dmem.bresp;
  assign dmem.rresp=soc.dmem.rresp;
  assign dmem.awvalid=soc.dmem.awvalid;
  assign dmem.awready=soc.dmem.awready;
  assign dmem.wvalid=soc.dmem.wvalid;
  assign dmem.wready=soc.dmem.wready;
  assign dmem.wlast=soc.dmem.wlast;
  assign dmem.bvalid=soc.dmem.bvalid;
  assign dmem.bready=soc.dmem.bready;
  assign dmem.arvalid=soc.dmem.arvalid;
  assign dmem.arready=soc.dmem.arready;
  assign dmem.rvalid=soc.dmem.rvalid;
  assign dmem.rready=soc.dmem.rready;
  assign dmem.rlast=soc.dmem.rlast;
  assign dmem.wdata=soc.dmem.wdata;
  assign dmem.rdata=soc.dmem.rdata;
  assign dmem.wstrb=soc.dmem.wstrb;
  assign imem_port.awaddr=soc.imem_port.awaddr;
  assign imem_port.araddr=soc.imem_port.araddr;
  assign imem_port.awid=soc.imem_port.awid;
  assign imem_port.arid=soc.imem_port.arid;
  assign imem_port.bid=soc.imem_port.bid;
  assign imem_port.rid=soc.imem_port.rid;
  assign imem_port.awlen=soc.imem_port.awlen;
  assign imem_port.arlen=soc.imem_port.arlen;
  assign imem_port.awsize=soc.imem_port.awsize;
  assign imem_port.arsize=soc.imem_port.arsize;
  assign imem_port.awburst=soc.imem_port.awburst;
  assign imem_port.arburst=soc.imem_port.arburst;
  assign imem_port.bresp=soc.imem_port.bresp;
  assign imem_port.rresp=soc.imem_port.rresp;
  assign imem_port.awvalid=soc.imem_port.awvalid;
  assign imem_port.awready=soc.imem_port.awready;
  assign imem_port.wvalid=soc.imem_port.wvalid;
  assign imem_port.wready=soc.imem_port.wready;
  assign imem_port.wlast=soc.imem_port.wlast;
  assign imem_port.bvalid=soc.imem_port.bvalid;
  assign imem_port.bready=soc.imem_port.bready;
  assign imem_port.arvalid=soc.imem_port.arvalid;
  assign imem_port.arready=soc.imem_port.arready;
  assign imem_port.rvalid=soc.imem_port.rvalid;
  assign imem_port.rready=soc.imem_port.rready;
  assign imem_port.rlast=soc.imem_port.rlast;
  assign imem_port.wdata=soc.imem_port.wdata;
  assign imem_port.rdata=soc.imem_port.rdata;
  assign imem_port.wstrb=soc.imem_port.wstrb;
  assign dmem_port.awaddr=soc.dmem_port.awaddr;
  assign dmem_port.araddr=soc.dmem_port.araddr;
  assign dmem_port.awid=soc.dmem_port.awid;
  assign dmem_port.arid=soc.dmem_port.arid;
  assign dmem_port.bid=soc.dmem_port.bid;
  assign dmem_port.rid=soc.dmem_port.rid;
  assign dmem_port.awlen=soc.dmem_port.awlen;
  assign dmem_port.arlen=soc.dmem_port.arlen;
  assign dmem_port.awsize=soc.dmem_port.awsize;
  assign dmem_port.arsize=soc.dmem_port.arsize;
  assign dmem_port.awburst=soc.dmem_port.awburst;
  assign dmem_port.arburst=soc.dmem_port.arburst;
  assign dmem_port.bresp=soc.dmem_port.bresp;
  assign dmem_port.rresp=soc.dmem_port.rresp;
  assign dmem_port.awvalid=soc.dmem_port.awvalid;
  assign dmem_port.awready=soc.dmem_port.awready;
  assign dmem_port.wvalid=soc.dmem_port.wvalid;
  assign dmem_port.wready=soc.dmem_port.wready;
  assign dmem_port.wlast=soc.dmem_port.wlast;
  assign dmem_port.bvalid=soc.dmem_port.bvalid;
  assign dmem_port.bready=soc.dmem_port.bready;
  assign dmem_port.arvalid=soc.dmem_port.arvalid;
  assign dmem_port.arready=soc.dmem_port.arready;
  assign dmem_port.rvalid=soc.dmem_port.rvalid;
  assign dmem_port.rready=soc.dmem_port.rready;
  assign dmem_port.rlast=soc.dmem_port.rlast;
  assign dmem_port.wdata=soc.dmem_port.wdata;
  assign dmem_port.rdata=soc.dmem_port.rdata;
  assign dmem_port.wstrb=soc.dmem_port.wstrb;
  assign native.awaddr=soc.native.awaddr;
  assign native.araddr=soc.native.araddr;
  assign native.awid=soc.native.awid;
  assign native.arid=soc.native.arid;
  assign native.bid=soc.native.bid;
  assign native.rid=soc.native.rid;
  assign native.awlen=soc.native.awlen;
  assign native.arlen=soc.native.arlen;
  assign native.awsize=soc.native.awsize;
  assign native.arsize=soc.native.arsize;
  assign native.awburst=soc.native.awburst;
  assign native.arburst=soc.native.arburst;
  assign native.bresp=soc.native.bresp;
  assign native.rresp=soc.native.rresp;
  assign native.awvalid=soc.native.awvalid;
  assign native.awready=soc.native.awready;
  assign native.wvalid=soc.native.wvalid;
  assign native.wready=soc.native.wready;
  assign native.wlast=soc.native.wlast;
  assign native.bvalid=soc.native.bvalid;
  assign native.bready=soc.native.bready;
  assign native.arvalid=soc.native.arvalid;
  assign native.arready=soc.native.arready;
  assign native.rvalid=soc.native.rvalid;
  assign native.rready=soc.native.rready;
  assign native.rlast=soc.native.rlast;
  assign native.wdata=soc.native.wdata;
  assign native.rdata=soc.native.rdata;
  assign native.wstrb=soc.native.wstrb;
  assign backend.awaddr=soc.backend.awaddr;
  assign backend.araddr=soc.backend.araddr;
  assign backend.awid=soc.backend.awid;
  assign backend.arid=soc.backend.arid;
  assign backend.bid=soc.backend.bid;
  assign backend.rid=soc.backend.rid;
  assign backend.awlen=soc.backend.awlen;
  assign backend.arlen=soc.backend.arlen;
  assign backend.awsize=soc.backend.awsize;
  assign backend.arsize=soc.backend.arsize;
  assign backend.awburst=soc.backend.awburst;
  assign backend.arburst=soc.backend.arburst;
  assign backend.bresp=soc.backend.bresp;
  assign backend.rresp=soc.backend.rresp;
  assign backend.awvalid=soc.backend.awvalid;
  assign backend.awready=soc.backend.awready;
  assign backend.wvalid=soc.backend.wvalid;
  assign backend.wready=soc.backend.wready;
  assign backend.wlast=soc.backend.wlast;
  assign backend.bvalid=soc.backend.bvalid;
  assign backend.bready=soc.backend.bready;
  assign backend.arvalid=soc.backend.arvalid;
  assign backend.arready=soc.backend.arready;
  assign backend.rvalid=soc.backend.rvalid;
  assign backend.rready=soc.backend.rready;
  assign backend.rlast=soc.backend.rlast;
  assign backend.wdata=soc.backend.wdata;
  assign backend.rdata=soc.backend.rdata;
  assign backend.wstrb=soc.backend.wstrb;
  assign external_mem.awaddr=soc.external_mem.awaddr;
  assign external_mem.araddr=soc.external_mem.araddr;
  assign external_mem.awid=soc.external_mem.awid;
  assign external_mem.arid=soc.external_mem.arid;
  assign external_mem.bid=soc.external_mem.bid;
  assign external_mem.rid=soc.external_mem.rid;
  assign external_mem.awlen=soc.external_mem.awlen;
  assign external_mem.arlen=soc.external_mem.arlen;
  assign external_mem.awsize=soc.external_mem.awsize;
  assign external_mem.arsize=soc.external_mem.arsize;
  assign external_mem.awburst=soc.external_mem.awburst;
  assign external_mem.arburst=soc.external_mem.arburst;
  assign external_mem.bresp=soc.external_mem.bresp;
  assign external_mem.rresp=soc.external_mem.rresp;
  assign external_mem.awvalid=soc.external_mem.awvalid;
  assign external_mem.awready=soc.external_mem.awready;
  assign external_mem.wvalid=soc.external_mem.wvalid;
  assign external_mem.wready=soc.external_mem.wready;
  assign external_mem.wlast=soc.external_mem.wlast;
  assign external_mem.bvalid=soc.external_mem.bvalid;
  assign external_mem.bready=soc.external_mem.bready;
  assign external_mem.arvalid=soc.external_mem.arvalid;
  assign external_mem.arready=soc.external_mem.arready;
  assign external_mem.rvalid=soc.external_mem.rvalid;
  assign external_mem.rready=soc.external_mem.rready;
  assign external_mem.rlast=soc.external_mem.rlast;
  assign external_mem.wdata=soc.external_mem.wdata;
  assign external_mem.rdata=soc.external_mem.rdata;
  assign external_mem.wstrb=soc.external_mem.wstrb;
  assign nmem.awaddr=soc.nmem.awaddr;
  assign nmem.araddr=soc.nmem.araddr;
  assign nmem.awid=soc.nmem.awid;
  assign nmem.arid=soc.nmem.arid;
  assign nmem.bid=soc.nmem.bid;
  assign nmem.rid=soc.nmem.rid;
  assign nmem.awlen=soc.nmem.awlen;
  assign nmem.arlen=soc.nmem.arlen;
  assign nmem.awsize=soc.nmem.awsize;
  assign nmem.arsize=soc.nmem.arsize;
  assign nmem.awburst=soc.nmem.awburst;
  assign nmem.arburst=soc.nmem.arburst;
  assign nmem.bresp=soc.nmem.bresp;
  assign nmem.rresp=soc.nmem.rresp;
  assign nmem.awvalid=soc.nmem.awvalid;
  assign nmem.awready=soc.nmem.awready;
  assign nmem.wvalid=soc.nmem.wvalid;
  assign nmem.wready=soc.nmem.wready;
  assign nmem.wlast=soc.nmem.wlast;
  assign nmem.bvalid=soc.nmem.bvalid;
  assign nmem.bready=soc.nmem.bready;
  assign nmem.arvalid=soc.nmem.arvalid;
  assign nmem.arready=soc.nmem.arready;
  assign nmem.rvalid=soc.nmem.rvalid;
  assign nmem.rready=soc.nmem.rready;
  assign nmem.rlast=soc.nmem.rlast;
  assign nmem.wdata=soc.nmem.wdata;
  assign nmem.rdata=soc.nmem.rdata;
  assign nmem.wstrb=soc.nmem.wstrb;
  assign arb_nmem.awaddr=soc.arb_nmem.awaddr;
  assign arb_nmem.araddr=soc.arb_nmem.araddr;
  assign arb_nmem.awid=soc.arb_nmem.awid;
  assign arb_nmem.arid=soc.arb_nmem.arid;
  assign arb_nmem.bid=soc.arb_nmem.bid;
  assign arb_nmem.rid=soc.arb_nmem.rid;
  assign arb_nmem.awlen=soc.arb_nmem.awlen;
  assign arb_nmem.arlen=soc.arb_nmem.arlen;
  assign arb_nmem.awsize=soc.arb_nmem.awsize;
  assign arb_nmem.arsize=soc.arb_nmem.arsize;
  assign arb_nmem.awburst=soc.arb_nmem.awburst;
  assign arb_nmem.arburst=soc.arb_nmem.arburst;
  assign arb_nmem.bresp=soc.arb_nmem.bresp;
  assign arb_nmem.rresp=soc.arb_nmem.rresp;
  assign arb_nmem.awvalid=soc.arb_nmem.awvalid;
  assign arb_nmem.awready=soc.arb_nmem.awready;
  assign arb_nmem.wvalid=soc.arb_nmem.wvalid;
  assign arb_nmem.wready=soc.arb_nmem.wready;
  assign arb_nmem.wlast=soc.arb_nmem.wlast;
  assign arb_nmem.bvalid=soc.arb_nmem.bvalid;
  assign arb_nmem.bready=soc.arb_nmem.bready;
  assign arb_nmem.arvalid=soc.arb_nmem.arvalid;
  assign arb_nmem.arready=soc.arb_nmem.arready;
  assign arb_nmem.rvalid=soc.arb_nmem.rvalid;
  assign arb_nmem.rready=soc.arb_nmem.rready;
  assign arb_nmem.rlast=soc.arb_nmem.rlast;
  assign arb_nmem.wdata=soc.arb_nmem.wdata;
  assign arb_nmem.rdata=soc.arb_nmem.rdata;
  assign arb_nmem.wstrb=soc.arb_nmem.wstrb;
  assign isolate=soc.isolate;
  assign backend_error=soc.backend_error;
  assign backend_irq=soc.backend_irq;
  assign halted=soc.halted;
  assign fault=soc.fault;
  assign wfi=soc.wfi;
  assign core_running=soc.core_running;
  assign backend_fault=soc.backend_fault;

  ce64_native_memory_model native_model(.seed(seed),.max_delay(delay_limit),.clk,.reset_n(!reset),.d_awaddr,.d_araddr,.d_awid,.d_arid,.d_awlen,.d_arlen,
    .d_awvalid,.d_arvalid,.d_awready,.d_arready,.d_wready,.d_wlast,.d_wdata,.d_wstrb,.d_rdata,.d_rid,.d_rvalid,.d_rlast);
  wire [31:0] native_protocol_checks=native_model.native_checks;
  axi4_if #(.DATA_W(32),.ID_W(1)) environment_unused(clk);
  axi_sparse_mem #(.DATA_W(32),.ID_W(1),.BASE_ADDR(0),.SIZE_BYTES(64'h100000000)) d_memory
    (.clk,.reset_n(!reset),.random_delays(1'b0),.seed(seed),.max_delay(0),
     .inject_enable(1'b0),.inject_start(32'b0),.inject_end(32'b0),.inject_resp(2'b0),.bus(environment_unused));
  assign environment_unused.awvalid=0;assign environment_unused.wvalid=0;assign environment_unused.arvalid=0;
  assign environment_unused.bready=1;assign environment_unused.rready=1;
  nx_ce64_local #(.UART_DIVISOR(2),.PRELOAD_MODE(1),.LOCAL_READ_PIPELINE(LOCAL_READ_PIPELINE),.REQUEST_PMU(ENABLE_REQUEST_PMU)) board_local(
    .clk,.reset_n(!reset),.ddr_init_done,.platform_ready(1'b1),.platform_status(32'b0),.telemetry({request_pmu_stats,2048'b0}),.uart_rx(1'b1),.uart_tx(board_tx),
    .rom_enable,.rom_address,.rom_data,.model_sealed,.platform_reset_request,
    .exit_code(board_exit),.report_tag(board_report),.exited(board_exited),.local_i,.local_d,.local_n);

  logic injected_read=0,injected_write=0;
  always @(posedge clk) begin
    if(reset) begin injected_read<=0;injected_write<=0;end
    else begin
      if(nmem.arvalid&&nmem.arready) injected_read<=test_mode==3 && nmem.araddr<=injection_address+15 && nmem.araddr>=injection_address;
      if(nmem.awvalid&&nmem.awready) injected_write<=test_mode==4 && nmem.awaddr<=injection_address+15 && nmem.awaddr>=injection_address;
    end
  end
  logic completed=0,timed_out=0;
  longint unsigned wave_until=0;logic[31:0] wave_launch=0;
  // Observe accepted writes and consumed B responses independently. Exit
  // MMIO acceptance can precede its real UART-serialized B completion.
  longint unsigned cpu_write_accepts=0,cpu_write_responses=0;
  logic[31:0] exit_code=0,report_tag=0;
  logic held_reset=0;
  int fd,trace_fd,progress_fd,report_count=0;
  typedef struct packed {logic[31:0] address;logic[2:0] size;} address_t;
  typedef struct packed {logic[31:0] data;logic[3:0] strobe;} data_t;
  address_t addresses[$],wa;data_t writes[$],wd;
  logic[31:0] peek_address=0,peek_value=0,logged_cpu_read=0;
  logic logged_cpu_read_active=0;
  assign externalInterrupt=irq;
  assign timerInterrupt=!reset && cycles[15:0]<16;
  initial begin
    clk=0;reset=1;softwareInterrupt=0;
    if($value$plusargs("seed=%d",seed))begin end
    if($value$plusargs("max_delay=%d",delay_limit))begin end
    if($value$plusargs("max_cycles=%d",max_cycles))begin end
    head_run=$test$plusargs("head_run");
    held_reset=$test$plusargs("held_reset");negative_early=$test$plusargs("early_completion");negative_stale=$test$plusargs("stale_data");
    progress_fd=$fopen("progress.txt","w");
    fd=$fopen("cpu-output.txt","w");trace_fd=$fopen("transactions.csv","w");
    if(!fd||!trace_fd)$fatal(1,"cannot open observations");
    #1;native_model.mem=d_memory.mem;
    #119;if(!held_reset)reset=0;
  end
  always #4 clk=~clk;
  // Observation only: diagnose actual protocol identities and private status.
  always @(posedge clk)if(!reset)begin
    if(soc.compute.ce.regs.do_write && soc.compute.ce.regs.wa==12'h020)
      $display("CE_DOORBELL cycle=%0d can_submit=%b platform_drained=%b bitmap=%h",cycles,soc.compute.ce.regs.can_submit,soc.compute.ce.drained,soc.compute.ce.regs.bitmap);
    if(soc.compute.ce.regs.submit)$display("CE_SUBMIT cycle=%0d epoch=%h generation=%h",cycles,soc.compute.ce.epoch,soc.compute.ce.generation);
    if(soc.compute.ce.control.linear_control.desc_done)$display("CE_DESCRIPTOR cycle=%0d status=%0d groups=%0d",cycles,soc.compute.ce.control.linear_control.desc_status,soc.compute.ce.control.linear_control.groups);
    if(soc.compute.ce.regs.publishing && soc.compute.ce.regs.publish_index==39)
      $display("CE_COMMIT cycle=%0d status=%0d rows=%0d tiles=%0d generation=%h",cycles,soc.compute.ce.control.linear_control.status,soc.compute.ce.control.linear_control.rows,soc.compute.ce.control.linear_control.tiles,soc.compute.ce.generation);
  end
  always @(peek_address)begin
    #1;peek_value=0;for(int i=0;i<4;i++)peek_value[8*i+:8]=d_memory.mem.read_byte(64'(peek_address)+i);
  end
  always @(posedge clk)begin
    cycles<=cycles+1;
    if(cycles>=max_cycles)timed_out<=1;

    if(cycles%1000000==0)begin $fwrite(progress_fd,"%0d %0d %0d\n",cycles,launches,report_count);$fflush(progress_fd);end
    if(!reset)begin
      if(trace_retire)retired<=retired+1;
      if((imem_port.arvalid&&imem_port.arready)+(dmem_port.arvalid&&dmem_port.arready)+(nmem.arvalid&&nmem.arready)>1)$fatal(1,"shared AR arbitration");
      if((imem_port.rvalid&&imem_port.rready)+(dmem_port.rvalid&&dmem_port.rready)+(nmem.rvalid&&nmem.rready)>1)$fatal(1,"shared R arbitration");
      previous_irq<=irq; prev_halted<=halted;
      if(halted&&!prev_halted)irq_due<=cycles+150000;
      if(irq&&!previous_irq)$fwrite(trace_fd,"%0d,IRQ,0,%h,%h,%0d\n",cycles,launches,test_mode,owner);
      if(arb_nmem.awvalid&&arb_nmem.awready&&arb_nmem.awaddr==hold_address&&test_mode==5) hold_until<=cycles+1000000;
      if(cpu_bus.awvalid&&cpu_bus.awready)addresses.push_back('{cpu_bus.awaddr,cpu_bus.awsize});
      if(cpu_bus.wvalid&&cpu_bus.wready)writes.push_back('{cpu_bus.wdata,cpu_bus.wstrb});
      if(addresses.size()&&writes.size())begin
        wa=addresses.pop_front();wd=writes.pop_front();
        cpu_write_accepts<=cpu_write_accepts+1;
        $fwrite(trace_fd,"%0d,CW,%h,%h,%h,%0d\n",cycles,wa.address,wd.data,wd.strobe,owner);
        if(wa.address==32'h100000a0)test_mode=wd.data;
        if(wa.address==32'h100000a4)injection_address=wd.data;
        if(wa.address==32'h100000a8)hold_address=wd.data;
        if(wa.address==32'h10003020)begin if(wd.data!=0)begin launches<=launches+1;irq_due<=0;end end
        if(wa.address==32'h10000080)report_tag=wd.data;
        if(wa.address==32'h10000084)begin
          $fwrite(fd,"%0d %0d %0d\n",report_tag[31:16],report_tag[15:0],wd.data);$fflush(fd);report_count++;
        end
        if(wa.address==32'h10000020)begin completed<=1;exit_code<=wd.data;end
      end
      if(cpu_bus.arvalid&&cpu_bus.arready)begin logged_cpu_read<=cpu_bus.araddr;logged_cpu_read_active<=cpu_bus.araddr>=32'hac100000&&cpu_bus.araddr<32'hb0000000||cpu_bus.arlen!=0||cpu_bus.araddr==32'h1000300c; if(cpu_bus.araddr>=32'hac100000&&cpu_bus.araddr<32'hb0000000||cpu_bus.arlen!=0||cpu_bus.araddr==32'h1000300c)$fwrite(trace_fd,"%0d,CR,%h,%h,%h,%0d\n",cycles,cpu_bus.araddr,cpu_bus.arlen,cpu_bus.arsize,owner);end
      if(cpu_bus.bvalid&&cpu_bus.bready)begin
        cpu_write_responses<=cpu_write_responses+1;
        $fwrite(trace_fd,"%0d,CB,0,0,%h,%0d\n",cycles,cpu_bus.bresp,owner);
      end
      if(cpu_bus.rvalid&&cpu_bus.rready&&logged_cpu_read_active)$fwrite(trace_fd,"%0d,CD,0,%h,%h,%0d\n",cycles,cpu_bus.rdata,cpu_bus.rresp,owner);
      if(native.awvalid&&native.awready)$fwrite(trace_fd,"%0d,SA,%h,0,%h,0\n",cycles,native.awaddr,native.awsize);
      if(native.wvalid&&native.wready)$fwrite(trace_fd,"%0d,SW,0,%h,%h,0\n",cycles,native.wdata,native.wstrb);
      if(backend.awvalid&&backend.awready)begin if(backend.awlen>31||backend.awburst!=1||(backend.awlen!=0&&backend.awsize!=4))$fatal(1,"backend AW subset");end
      if(backend.arvalid&&backend.arready)begin if(backend.arlen>31||backend.arburst!=1)$fatal(1,"backend AR subset");end
      if(backend.awvalid&&backend.awready)$fwrite(trace_fd,"%0d,BA,%h,%h,%h,%0d\n",cycles,backend.awaddr,backend.awlen,backend.awsize,owner);
      if(backend.awvalid&&backend.awready)$fwrite(trace_fd,"%0d,NA,%h,%h,%h,%0d\n",cycles,backend.awaddr,backend.awid,backend.awsize,owner);
      if(backend.wvalid&&backend.wready)$fwrite(trace_fd,"%0d,NW,0,%h,%h,%0d\n",cycles,backend.wdata,backend.wstrb,owner);
      if(backend.bvalid&&backend.bready)$fwrite(trace_fd,"%0d,NB,0,%h,%h,%0d\n",cycles,backend.bid,backend.bresp,owner);
      if(backend.arvalid&&backend.arready)$fwrite(trace_fd,"%0d,NL,%h,0,%h,%0d\n",cycles,backend.araddr,backend.arlen,owner);
      if(backend.arvalid&&backend.arready)$fwrite(trace_fd,"%0d,NR,%h,%h,%h,%0d\n",cycles,backend.araddr,backend.arid,backend.arsize,owner);
      if(backend.rvalid&&backend.rready)$fwrite(trace_fd,"%0d,ND,%h,%h,%h,%0d\n",cycles,backend.rid,backend.rdata,backend.rresp,owner);
      if(arb_nmem.awvalid&&arb_nmem.awready)$fwrite(trace_fd,"%0d,MA,%h,%h,%h,%0d\n",cycles,arb_nmem.awaddr,arb_nmem.awid,arb_nmem.awsize,owner);
      if(arb_nmem.bvalid&&arb_nmem.bready)$fwrite(trace_fd,"%0d,MB,0,%h,%h,%0d\n",cycles,arb_nmem.bid,arb_nmem.bresp,owner);
      if(!owner&&!backend_idle)$fwrite(trace_fd,"%0d,EARLY,0,0,0,0\n",cycles);
      if(completed)$fflush(trace_fd);
    end
  end
  assert property(@(posedge clk) disable iff(reset) cpu_bus.awvalid&&!cpu_bus.awready |=> cpu_bus.awvalid&&$stable({cpu_bus.awaddr,cpu_bus.awlen,cpu_bus.awsize})) else $fatal(1,"CPU AW stability");
  assert property(@(posedge clk) disable iff(reset) cpu_bus.wvalid&&!cpu_bus.wready |=> cpu_bus.wvalid&&$stable({cpu_bus.wdata,cpu_bus.wstrb,cpu_bus.wlast})) else $fatal(1,"CPU W stability");
  assert property(@(posedge clk) disable iff(reset) cpu_bus.arvalid&&!cpu_bus.arready |=> cpu_bus.arvalid&&$stable({cpu_bus.araddr,cpu_bus.arlen,cpu_bus.arsize})) else $fatal(1,"CPU AR stability");
  assert property(@(posedge clk) disable iff(reset) native.awvalid&&!native.awready |=> native.awvalid&&$stable({native.awaddr,native.awsize})) else $fatal(1,"native AW stability");
  assert property(@(posedge clk) disable iff(reset) native.wvalid&&!native.wready |=> native.wvalid&&$stable({native.wdata,native.wstrb})) else $fatal(1,"native W stability");
  assert property(@(posedge clk) disable iff(reset) backend.awvalid&&!backend.awready |=> backend.awvalid&&$stable({backend.awaddr,backend.awid})) else $fatal(1,"backend AW stability");
  assert property(@(posedge clk) disable iff(reset) backend.wvalid&&!backend.wready |=> backend.wvalid&&$stable({backend.wdata,backend.wstrb})) else $fatal(1,"backend W stability");
  assert property(@(posedge clk) disable iff(reset) external_mem.rvalid&&!external_mem.rready |=> external_mem.rvalid&&$stable({external_mem.rdata,external_mem.rresp})) else $fatal(1,"memory R stability");

// Passive observations. Arithmetic and native DMA remain the real DUT.
`define VC soc.compute.ce.control.vector_control
  int opt11_fd;
  longint unsigned measured_ticks=0,measured_load=0,measured_compute=0,measured_write=0;
  longint unsigned measured_read=0,measured_written=0,last_native_write=0;
  int read_size=0;
  initial opt11_fd=$fopen("vector.csv","w");
  always @(posedge clk)if(!reset)begin
    if(`VC.submit)begin
      measured_ticks=0;measured_load=0;measured_compute=0;measured_write=0;measured_read=0;measured_written=0;
    end
    if(!`VC.engine_idle&&!`VC.completion_valid)begin
      measured_ticks++;
      case(`VC.phase)1:measured_load++;2:measured_compute++;3:measured_write++;default:;endcase
    end
    if(soc.compute.ce.a_en&&soc.compute.ce.b_en)$fatal(1,"OPT12 single scratch port collision");
    if(backend.arvalid&&backend.arready)read_size=backend.arsize;
    if(soc.compute.ce.control.vector_selected)begin
      if(backend.rvalid&&backend.rready)measured_read+=1<<read_size;
      if(backend.wvalid&&backend.wready)measured_written+=$countones(backend.wstrb);
    end
    if(d_wready&&d_wlast)last_native_write=cycles;
    if(report_tag[15:0]==20)begin
      if(d_arvalid&&d_arready)$fwrite(opt11_fd,"NREAD,%0d,%0d,%0d\n",report_tag[31:16],(32'(d_arlen)+1)*32,owner);
      if(d_wready)$fwrite(opt11_fd,"NWRITE,%0d,%0d,%0d\n",report_tag[31:16],$countones(d_wstrb),owner);
    end
    if(backend.bvalid&&backend.bready&&backend.bresp==0)
      if(cycles-last_native_write<1024)$fatal(1,"OPT12 native drain shortened");
    if(`VC.dma_valid&&`VC.dma_ready)
      $fwrite(opt11_fd,"CMD,%0d,%0d,%0d,%h,%0d,%0d\n",cycles,launches,`VC.dma_write,`VC.dma_address,`VC.dma_size,`VC.dma_len);
    if(`VC.completion_valid&&`VC.completion_ready)begin
      $fwrite(opt11_fd,"COMPLETE,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d\n",cycles,launches,$signed(`VC.status),
        `VC.ticks,`VC.loads,`VC.computes,`VC.writes,`VC.read_bytes,`VC.write_bytes,
        measured_ticks,measured_load,measured_compute,measured_write,measured_read,measured_written);
      $fflush(opt11_fd);
    end
    if(completed)$fflush(opt11_fd);
  end
`undef VC


  integer fullgraph_linear_fd;
  longint unsigned fgt=0,fgl=0,fgc=0,fgw=0,fgr=0;
  initial fullgraph_linear_fd=$fopen("linear.csv","w");
  always @(posedge clk)if(!reset)begin
    if(soc.compute.ce.control.linear_control.submit)begin fgt=0;fgl=0;fgc=0;fgw=0;fgr=0;end
    if(!soc.compute.ce.control.linear_control.engine_idle&&!soc.compute.ce.control.linear_control.completion_valid)begin
      fgt++;
      case(soc.compute.ce.control.linear_control.phase)1:fgl++;2:fgc++;3:fgw++;default:;endcase
      if(soc.compute.ce.control.linear_control.restoring)fgr++;
    end
    if(soc.compute.ce.control.linear_control.completion_valid&&soc.compute.ce.control.linear_control.completion_ready)begin
      $fwrite(fullgraph_linear_fd,"LCOMPLETE,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d\n",cycles,launches,$signed(soc.compute.ce.control.linear_control.status),
        soc.compute.ce.control.linear_control.ticks,soc.compute.ce.control.linear_control.load_ticks,soc.compute.ce.control.linear_control.compute_ticks,soc.compute.ce.control.linear_control.write_ticks,soc.compute.ce.control.linear_control.restore_ticks,
        soc.compute.ce.control.linear_control.payload_read,soc.compute.ce.control.linear_control.payload_write,fgt,fgl,fgc,fgw,fgr);
      $fflush(fullgraph_linear_fd);
    end
  end


// Passive complete descriptor ledger. No DUT or producer proof is driven.
integer full169_launch_fd;
initial begin
  full169_launch_fd=$fopen("launches.csv","w");
  if(!full169_launch_fd)$fatal(1,"full169 launch ledger open");
end
always @(posedge clk) if(!reset) begin
  if(soc.compute.ce.submit) begin
    $fwrite(full169_launch_fd,"%0d,%h\n",cycles,soc.compute.ce.descriptor);
    $fflush(full169_launch_fd);
  end
end
final $fclose(full169_launch_fd);


  wire service_cpu_write_drained,service_backend_drained,service_ddr_drained,service_native_drained;
  wire [63:0] service_cpu_write_activity,service_backend_activity,service_ddr_activity,service_native_activity;
  nx_service_axi_observer #(.FILE("transport-cpu.csv"),.READS(0)) service_cpu_write_monitor(
    .clk,.reset,.cycles,.epoch(soc.compute.ce.epoch),.owner,.fault(ddr_fault),.bus(cpu_bus),
    .idle(service_cpu_write_drained),.activity(service_cpu_write_activity));
  nx_service_axi_observer #(.FILE("transport-backend.csv")) service_backend_monitor(
    .clk,.reset,.cycles,.epoch(soc.compute.ce.epoch),.owner,.fault(ddr_fault),.bus(backend),
    .idle(service_backend_drained),.activity(service_backend_activity));
  nx_service_axi_observer #(.FILE("transport-ddr.csv")) service_ddr_monitor(
    .clk,.reset,.cycles,.epoch(soc.compute.ce.epoch),.owner,.fault(ddr_fault),.bus(soc.ddr_fabric.memory),
    .idle(service_ddr_drained),.activity(service_ddr_activity));
  nx_service_native_observer service_native_monitor(
    .clk,.reset,.cycles,.epoch(soc.compute.ce.epoch),.owner,
    .awaddr(d_awaddr),.araddr(d_araddr),.awid(d_awid),.arid(d_arid),.awlen(d_awlen),.arlen(d_arlen),
    .awvalid(d_awvalid),.awready(d_awready),.arvalid(d_arvalid),.arready(d_arready),
    .wready(d_wready),.wlast(d_wlast),.rvalid(d_rvalid),.rlast(d_rlast),.rid(d_rid),
    .commit_fire(native_model.commit_due==1),
    .model_pending(native_model.writing||native_model.reading||native_model.commit_due!=0),
    .idle(service_native_drained),.activity(service_native_activity));
  wire service_transport_drained=service_cpu_write_drained&&service_backend_drained&&service_ddr_drained&&service_native_drained&&
    soc.compute.ce.dma_idle&&soc.compute.ce.transport_drained&&soc.native_safely_drained&&
    !soc.native_pending&&!soc.upstream_pending&&!ddr_fault&&!soc.native_quarantined&&(owner==0||(negative_case&&soc.isolate&&soc.compute.ce.drained));
  wire [63:0] service_transport_activity=service_cpu_write_activity+service_backend_activity+service_ddr_activity+service_native_activity;

  int unsigned lowest_sp=32'h30000;bit sp_seen=0;
  always @(posedge clk)if(!reset&&soc.cpu._zz_1&&soc.cpu.lastStageRegFileWrite_payload_address==2)begin
    if(!sp_seen)$display("SP_INIT cycle=%0d value=%h",cycles,soc.cpu.lastStageRegFileWrite_payload_data);
    if(soc.cpu.lastStageRegFileWrite_payload_data==32'h30000)sp_seen=1;
    if(sp_seen&&soc.cpu.lastStageRegFileWrite_payload_data<lowest_sp)lowest_sp=soc.cpu.lastStageRegFileWrite_payload_data;
    if(sp_seen&&(soc.cpu.lastStageRegFileWrite_payload_data<32'h22000||soc.cpu.lastStageRegFileWrite_payload_data>32'h30000))
      $fatal(1,"stack bounds");
  end
  task dump_region(input string name,input longint unsigned addr,input int length);
    integer f;f=$fopen(name,"wb");if(!f)$fatal(1,"dump open");
    for(int i=0;i<length;i++)$fwrite(f,"%c",d_memory.mem.read_byte(addr+i));
    $fclose(f);
  endtask
  integer terminal_fd,stable_count=0;
  longint unsigned last_activity=0,last_accepted=0,last_responses=0,stable_since=0;
  initial begin
    wait(completed||timed_out);#1;
    if(timed_out||exit_code!=0)$fatal(1,"guest incomplete or failed");
    dump_region("attention.bin",32'hac080000,4*896*4);
    dump_region("activation.bin",32'hac040000,4*4864*4);
    dump_region("Aq.bin",32'hba1c0000,4*4864);
    dump_region("Sa.bin",32'hba1c5000,4*304);
    dump_region("down.bin",32'hac060000,4*8*4);
    for(int i=1024;i<2048;i++)if(board_local.ram[i]!==32'ha5a5a5a5)$fatal(1,"guard changed");
    if(!sp_seen)$fatal(1,"no stack observation");
    forever begin
      @(posedge clk);#1;
      if(timed_out)$fatal(1,"terminal drain deadline");
      if(service_transport_drained&&cpu_write_accepts==cpu_write_responses)begin
        if(service_transport_activity==last_activity&&cpu_write_accepts==last_accepted&&cpu_write_responses==last_responses)stable_count++;
        else begin stable_count=0;stable_since=cycles;end
        if(stable_count>=4)begin
          if((owner&&!(negative_case&&soc.isolate&&soc.compute.ce.drained))||!backend_idle||ddr_fault)$fatal(1,"terminal state");
          terminal_fd=$fopen("terminal.json","w");
          $fwrite(terminal_fd,"{\"stable\":true,\"stage\":\"AFTER_ALL_TIME_ADVANCING_INSPECTION\",\"cycle\":%0d,\"accepted\":%0d,\"responses\":%0d,\"transport_activity\":%0d,\"transport_idle\":true,\"timed_out\":false,\"stable_since_cycle\":%0d,\"stable_cycles\":4,\"lowest_sp\":%0d,\"stack_peak_bytes\":%0d,\"guard_bytes\":4096,\"guard_pass\":true}\n",cycles,cpu_write_accepts,cpu_write_responses,service_transport_activity,stable_since,lowest_sp,32'h30000-lowest_sp);
          $fclose(terminal_fd);$display("M4_TERMINAL_PASS cycle=%0d",cycles);$finish;
        end
      end else begin stable_count=0;stable_since=cycles;end
      last_activity=service_transport_activity;last_accepted=cpu_write_accepts;last_responses=cpu_write_responses;
    end
  end

  integer pvfd;integer fp_pending_count=0;integer fp_peak=0;
  initial pvfd=$fopen("pv-events.csv","w");
  `define PC soc.compute.ce.control.pv_control
  `define DP soc.compute.ce.control
  always @(posedge clk)if(!reset)begin
    if(`PC.ram_en&&soc.compute.ce.b_en&&`DP.pv_selected)$fatal(1,"PV compute/DMA scratch collision");
    if(`PC.fp_start&&`DP.sf_start)$fatal(1,"FP owner collision");
    if(`DP.shared_main_fp.start)begin
      if(fp_pending_count!=0)$fatal(1,"FP more than one outstanding");
      fp_pending_count=fp_pending_count+1;fp_peak=1;
      $fwrite(pvfd,"REQ,%0d,%0d,%0d,%h,%h\n",cycles,`DP.pv_selected,`DP.shared_main_fp.multiply,`DP.shared_main_fp.a,`DP.shared_main_fp.b);
    end
    if(`DP.fp_valid)begin
      if(fp_pending_count!=1)$fatal(1,"FP orphan response");fp_pending_count=fp_pending_count-1;
      $fwrite(pvfd,"RSP,%0d,%0d,%h\n",cycles,`DP.pv_selected,`DP.fp_result);
    end
    if(`DP.pv_selected&&`PC.ram_en)$fwrite(pvfd,"RAM,%0d,%h,%h,%h\n",cycles,`PC.ram_address,`PC.ram_mask,`PC.ram_data);
    if(`DP.pv_selected&&`PC.completion_valid&&`PC.completion_ready)
      $fwrite(pvfd,"DONE,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d\n",cycles,soc.compute.ce.generation,`PC.status,`PC.ticks,`PC.loads,`PC.computes,`PC.writes,`PC.read_bytes,`PC.write_bytes);
    if(completed&&fp_pending_count)$fatal(1,"final FP pending");
  end

endmodule
// Passive accepted-work ledgers. No READY, VALID, reset, owner or data is driven.
module nx_service_axi_observer #(parameter string FILE="transport.csv",parameter READS=1)(
  input wire clk,reset,input wire [63:0] cycles,input wire [31:0] epoch,
  input wire owner,input wire fault,axi4_if bus,
  output wire idle,output reg [63:0] activity=0
);
  longint unsigned aw_count=0,b_count=0,ar_count=0,r_count=0,aw_beats=0,w_beats=0;
  reg [31:0] previous_epoch=0;
  reg epoch_seen=0,previous_fault=0,previous_reset=1;
  integer fd,increment;
  initial begin fd=$fopen(FILE,"w");if(!fd)$fatal(1,"transport log open");end
  assign idle=aw_count==b_count && aw_beats==w_beats && ar_count==r_count &&
    !bus.awvalid&&!bus.wvalid&&!bus.bvalid&&(!READS||(!bus.arvalid&&!bus.rvalid));
  always @(posedge clk)begin
    increment=0;
    if(reset)begin
      if(!previous_reset)begin
        $fwrite(fd,"%0d,RESET,0,0,0,0,0,0,%0d,%0d\n",cycles,epoch,owner);increment++;
      end
      previous_reset=1;
    end else begin
      previous_reset=0;
      if(!epoch_seen||epoch!=previous_epoch)begin
        $fwrite(fd,"%0d,EPOCH,0,0,0,0,0,0,%0d,%0d\n",cycles,epoch,owner);
        previous_epoch=epoch;epoch_seen=1;increment++;
      end
      if(fault!=previous_fault)begin
        $fwrite(fd,"%0d,FAULT,0,0,0,0,0,%0d,%0d,%0d\n",cycles,fault,epoch,owner);
        previous_fault=fault;increment++;
      end
      if(bus.awvalid&&bus.awready)begin
        aw_count<=aw_count+1;aw_beats<=aw_beats+int'(bus.awlen)+1;increment++;
        $fwrite(fd,"%0d,AW,%0d,%h,%0d,%0d,0,0,%0d,%0d\n",cycles,bus.awid,bus.awaddr,bus.awlen,bus.awsize,epoch,owner);
      end
      if(bus.wvalid&&bus.wready)begin
        w_beats<=w_beats+1;increment++;
        $fwrite(fd,"%0d,W,0,0,0,0,%0d,0,%0d,%0d\n",cycles,bus.wlast,epoch,owner);
      end
      if(bus.bvalid&&bus.bready)begin
        b_count<=b_count+1;increment++;
        $fwrite(fd,"%0d,B,%0d,0,0,0,0,%0d,%0d,%0d\n",cycles,bus.bid,bus.bresp,epoch,owner);
      end
      if(READS&&bus.arvalid&&bus.arready)begin
        ar_count<=ar_count+1;increment++;
        $fwrite(fd,"%0d,AR,%0d,%h,%0d,%0d,0,0,%0d,%0d\n",cycles,bus.arid,bus.araddr,bus.arlen,bus.arsize,epoch,owner);
      end
      if(READS&&bus.rvalid&&bus.rready)begin
        if(bus.rlast)r_count<=r_count+1;increment++;
        $fwrite(fd,"%0d,R,%0d,0,0,0,%0d,%0d,%0d,%0d\n",cycles,bus.rid,bus.rlast,bus.rresp,epoch,owner);
      end
    end
    activity<=activity+increment;
  end
  final $fclose(fd);
endmodule

// The native HMIC port has neither B nor RREADY. COMMIT comes from the exact
// digital memory model's delayed-write retirement, in addition to AXI readback.
module nx_service_native_observer #(parameter string FILE="transport-native.csv")(
  input wire clk,reset,input wire [63:0] cycles,input wire [31:0] epoch,
  input wire owner,input wire [27:0] awaddr,araddr,input wire [3:0] awid,arid,awlen,arlen,
  input wire awvalid,awready,arvalid,arready,wready,wlast,rvalid,rlast,
  input wire [3:0] rid,input wire commit_fire,model_pending,
  output wire idle,output reg [63:0] activity=0
);
  longint unsigned aw_count=0,commit_count=0,ar_count=0,r_count=0;
  integer fd,increment;
  initial begin fd=$fopen(FILE,"w");if(!fd)$fatal(1,"native transport log open");end
  assign idle=aw_count==commit_count && ar_count==r_count && !model_pending&&!awvalid&&!arvalid&&!rvalid;
  always @(posedge clk)if(!reset)begin
    increment=0;
    if(awvalid&&awready)begin
      aw_count<=aw_count+1;increment++;
      $fwrite(fd,"%0d,AW,%0d,%h,%0d,5,0,0,%0d,%0d\n",cycles,awid,32'h80000000+{awaddr,2'b0},awlen,epoch,owner);
    end
    if(wready)begin
      increment++;
      $fwrite(fd,"%0d,W,0,0,0,0,%0d,0,%0d,%0d\n",cycles,wlast,epoch,owner);
    end
    if(commit_fire)begin
      commit_count<=commit_count+1;increment++;
      $fwrite(fd,"%0d,COMMIT,0,0,0,0,0,0,%0d,%0d\n",cycles,epoch,owner);
    end
    if(arvalid&&arready)begin
      ar_count<=ar_count+1;increment++;
      $fwrite(fd,"%0d,AR,%0d,%h,%0d,5,0,0,%0d,%0d\n",cycles,arid,32'h80000000+{araddr,2'b0},arlen,epoch,owner);
    end
    if(rvalid)begin
      if(rlast)r_count<=r_count+1;increment++;
      $fwrite(fd,"%0d,R,%0d,0,0,0,%0d,0,%0d,%0d\n",cycles,rid,rlast,epoch,owner);
    end
    activity<=activity+increment;
  end
  final $fclose(fd);
endmodule

