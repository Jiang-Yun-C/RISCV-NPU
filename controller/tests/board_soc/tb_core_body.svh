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
  wire ddr_init_done=!reset && cycles>=500;
  nx_soc_core #(.WRITE_DRAIN_CYCLES(8)) soc(.clk,.reset_n(!reset),.ddr_init_done,.timerInterrupt,
    .rom_data,.rom_enable,.rom_address,.trace_retire,.trace_pc,.accel_owner(owner),.accel_irq(irq),
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
  initial begin
    force soc.test_mode=test_mode;
    force soc.negative_early=negative_early;
    force soc.negative_stale=negative_stale;
    force soc.cycles=cycles;
    force soc.irq_due=irq_due;
  end
  t24_native_memory_model native_model(.clk,.reset_n(!reset),.d_awaddr,.d_araddr,.d_awid,.d_arid,.d_awlen,.d_arlen,
    .d_awvalid,.d_arvalid,.d_awready,.d_arready,.d_wready,.d_wlast,.d_wdata,.d_wstrb,.d_rdata,.d_rid,.d_rvalid,.d_rlast);
  wire [31:0] native_protocol_checks=native_model.native_checks;
  axi_sparse_mem #(.DATA_W(32),.ID_W(1),.BASE_ADDR(0),.SIZE_BYTES(64'h100000000)) i_memory
    (.clk,.reset_n(!reset),.random_delays(1'b1),.seed(seed^32'h49),.max_delay(delay_limit),
     .inject_enable(1'b0),.inject_start(32'b0),.inject_end(32'b0),.inject_resp(2'b0),.bus(local_i));
  axi_sparse_mem #(.DATA_W(32),.ID_W(1),.BASE_ADDR(0),.SIZE_BYTES(64'h100000000)) d_memory
    (.clk,.reset_n(!reset),.random_delays(1'b1),.seed(seed^32'h44),.max_delay(delay_limit),
     .inject_enable(1'b0),.inject_start(32'b0),.inject_end(32'b0),.inject_resp(2'b0),.bus(local_d));
  axi_sparse_mem #(.DATA_W(128),.ID_W(6),.BASE_ADDR(0),.SIZE_BYTES(64'h100000000)) n_memory
    (.clk,.reset_n(!reset),.random_delays(1'b1),.seed(seed^32'h4e),.max_delay(delay_limit),
     .inject_enable(1'b0),.inject_start(32'b0),.inject_end(32'b0),.inject_resp(2'b0),.bus(local_n));
  logic injected_read=0,injected_write=0;
  wire raw_bvalid=soc.ddr_fabric.rn.write_ddr ? soc.ddr_fabric.dn.bvalid : local_n.bvalid;
  wire [1:0] raw_bresp=soc.ddr_fabric.rn.write_ddr ? soc.ddr_fabric.dn.bresp : local_n.bresp;
  wire [1:0] raw_rresp=soc.ddr_fabric.rn.read_ddr ? soc.ddr_fabric.dn.rresp : local_n.rresp;
  initial begin
    force soc.nmem.rresp=injected_read ? 2'b10 : raw_rresp;
    force soc.nmem.bresp=injected_write ? 2'b11 : raw_bresp;
    force soc.nmem.bvalid=raw_bvalid && cycles>=hold_until;
    force soc.nmem.bready=soc.arb_nmem.bready && cycles>=hold_until;
  end
  always @(posedge clk) begin
    if(reset) begin injected_read<=0;injected_write<=0;end
    else begin
      if(nmem.arvalid&&nmem.arready) injected_read<=test_mode==3 && nmem.araddr<=injection_address+15 && nmem.araddr>=injection_address;
      if(nmem.awvalid&&nmem.awready) injected_write<=test_mode==4 && nmem.awaddr<=injection_address+15 && nmem.awaddr>=injection_address;
    end
  end
  logic completed=0,timed_out=0;
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
    clk=0;reset=1;softwareInterrupt=0;rom_data=0;
    if($value$plusargs("seed=%d",seed))begin end
    if($value$plusargs("max_delay=%d",delay_limit))begin end
    if($value$plusargs("max_cycles=%d",max_cycles))begin end
    head_run=$test$plusargs("head_run");
    held_reset=$test$plusargs("held_reset");negative_early=$test$plusargs("early_completion");negative_stale=$test$plusargs("stale_data");
    progress_fd=$fopen("progress.txt","w");
    fd=$fopen("cpu-output.txt","w");trace_fd=$fopen("transactions.csv","w");
    if(!fd||!trace_fd)$fatal(1,"cannot open observations");
    #1;i_memory.mem=d_memory.mem;n_memory.mem=d_memory.mem;native_model.mem=d_memory.mem;
    $dumpfile("cpu.vcd");$dumpvars(0,clk,reset,completed,owner,isolate,backend_idle,backend_error,irq,launches,
      backend.awvalid,backend.awready,backend.wvalid,backend.wready,backend.bvalid,backend.bready,
      backend.arvalid,backend.arready,backend.rvalid,backend.rready,report_count);
    $dumpvars(0,cpu_bus.awvalid,cpu_bus.awready,cpu_bus.awaddr,cpu_bus.wvalid,cpu_bus.wready,cpu_bus.wdata,cpu_bus.wstrb,cpu_bus.arvalid,cpu_bus.arready,cpu_bus.araddr,cpu_bus.arlen,cpu_bus.arsize,cpu_bus.rvalid,cpu_bus.rready,cpu_bus.rdata,cpu_bus.rresp,cpu_bus.rlast,core_running,halted,fault,trace_retire,trace_pc);
    $dumpvars(0,backend.awaddr,backend.awid,backend.awsize,backend.wdata,backend.wstrb,backend.bid,backend.bresp,backend.araddr,backend.arid,backend.arsize,backend.rid,backend.rdata,backend.rresp);
    $dumpvars(0,native_protocol_checks,ddr_init_done,ddr_fault,ddr_fault_reason,d_awaddr,d_araddr,d_awid,d_arid,d_awlen,d_arlen,
      d_awvalid,d_arvalid,d_awready,d_arready,d_wready,d_wlast,d_wdata,d_wstrb,d_rdata,d_rid,d_rvalid,d_rlast);
    #119;if(!held_reset)reset=0;
  end
  always #5 clk=~clk;
  always @(peek_address)begin
    #1;peek_value=0;for(int i=0;i<4;i++)peek_value[8*i+:8]=d_memory.mem.read_byte(64'(peek_address)+i);
  end
  always @(posedge clk)begin
    cycles<=cycles+1;
    if(cycles>=max_cycles)timed_out<=1;
    if(rom_enable)for(int i=0;i<4;i++)rom_data[8*i+:8]<=d_memory.mem.read_byte(64'(rom_address)+i);
    if(head_run&&cycles==2000000)$dumpoff;
    if(head_run&&core_running&&halted)$dumpon;
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
        $fwrite(trace_fd,"%0d,CW,%h,%h,%h,%0d\n",cycles,wa.address,wd.data,wd.strobe,owner);
        if(wa.address==32'h100000a0)test_mode=wd.data;
        if(wa.address==32'h100000a4)injection_address=wd.data;
        if(wa.address==32'h100000a8)hold_address=wd.data;
        if(wa.address==32'h20030000)begin if(wd.data==0)begin launches<=launches+1;irq_due<=0;end end
        if(wa.address==32'h10000080)report_tag=wd.data;
        if(wa.address==32'h10000084)begin
          $fwrite(fd,"%0d %0d %0d\n",report_tag[31:16],report_tag[15:0],wd.data);$fflush(fd);report_count++;
        end
        if(wa.address==32'h10000020)begin completed<=1;exit_code<=wd.data;end
      end
      if(cpu_bus.arvalid&&cpu_bus.arready)begin logged_cpu_read<=cpu_bus.araddr;logged_cpu_read_active<=cpu_bus.araddr>=32'hac100000&&cpu_bus.araddr<32'hac200000||cpu_bus.arlen!=0||cpu_bus.araddr==32'h20030008; if(cpu_bus.araddr>=32'hac100000&&cpu_bus.araddr<32'hac200000||cpu_bus.arlen!=0||cpu_bus.araddr==32'h20030008)$fwrite(trace_fd,"%0d,CR,%h,%h,%h,%0d\n",cycles,cpu_bus.araddr,cpu_bus.arlen,cpu_bus.arsize,owner);end
      if(cpu_bus.bvalid&&cpu_bus.bready)$fwrite(trace_fd,"%0d,CB,0,0,%h,%0d\n",cycles,cpu_bus.bresp,owner);
      if(cpu_bus.rvalid&&cpu_bus.rready&&logged_cpu_read_active)$fwrite(trace_fd,"%0d,CD,0,%h,%h,%0d\n",cycles,cpu_bus.rdata,cpu_bus.rresp,owner);
      if(native.awvalid&&native.awready)$fwrite(trace_fd,"%0d,SA,%h,0,%h,0\n",cycles,native.awaddr,native.awsize);
      if(native.wvalid&&native.wready)$fwrite(trace_fd,"%0d,SW,0,%h,%h,0\n",cycles,native.wdata,native.wstrb);
      if(backend.awvalid&&backend.awready)begin if(backend.awlen!=0||backend.awburst!=1)$fatal(1,"backend AW subset");end
      if(backend.arvalid&&backend.arready)begin if(backend.arlen!=0||backend.arburst!=1)$fatal(1,"backend AR subset");end
      if(backend.awvalid&&backend.awready)$fwrite(trace_fd,"%0d,NA,%h,%h,%h,%0d\n",cycles,backend.awaddr,backend.awid,backend.awsize,owner);
      if(backend.wvalid&&backend.wready)$fwrite(trace_fd,"%0d,NW,0,%h,%h,%0d\n",cycles,backend.wdata,backend.wstrb,owner);
      if(backend.bvalid&&backend.bready)$fwrite(trace_fd,"%0d,NB,0,%h,%h,%0d\n",cycles,backend.bid,backend.bresp,owner);
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
