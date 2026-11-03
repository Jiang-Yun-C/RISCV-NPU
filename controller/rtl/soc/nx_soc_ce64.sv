// Synthesizable CPU/Coral compute and native DDR boundary, core clock domain.
// Local device/ROM ports, PLL and physical HMIC PHY are connected by the board shell.
module nx_soc_ce64 #(parameter WRITE_DRAIN_CYCLES=1024, ENABLE_TEST_CONTROL=0, ENABLE_CE=1,CROSS_GROUP_WRITE=1,AQSA_RESIDENT=1,W_PREFETCH=1,A_W_BANKED=1,ENABLE_REQUEST_PMU=1,parameter bit LONG_PV=1,HEAD_ARGMAX=1)(
  input wire clk, reset_n, ddr_init_done, timerInterrupt, uartInterrupt, model_sealed, startup_authorized,
  input wire [31:0] rom_data,
  output wire rom_enable,
  output wire [31:0] rom_address,
  output wire trace_retire,
  output wire [191:0] debug_observe,
  output wire [31:0] trace_pc,
  output wire accel_owner, accel_irq, backend_idle_status, ddr_fault_status,
  output wire [255:0] cpu_i_stats,cpu_d_stats,ce_stats,
  output wire [2047:0] request_pmu_stats,
  output wire native_quarantine_status,
  axi4_if.master local_i, local_d, local_n,
  axi4_if.slave auxiliary,
  output wire [27:0] d_awaddr, d_araddr,
  output wire [3:0] d_awid, d_arid, d_awlen, d_arlen,
  output wire d_awvalid, d_arvalid,
  input wire d_awready, d_arready, d_wready, d_wlast,
  output wire [255:0] d_wdata,
  output wire [31:0] d_wstrb,
  input wire [255:0] d_rdata,
  input wire [3:0] d_rid,
  input wire d_rvalid, d_rlast,
  output wire [3:0] ddr_fault_reason,
  output wire [63:0] ddr_cycles, ddr_write_bytes, ddr_read_bytes, native_write_bytes, native_read_bytes);
  wire reset=!reset_n;
  wire softwareInterrupt=1'b0;
  wire [31:0] test_mode;
  wire negative_early=0, negative_stale=0;
  wire [63:0] cycles;
  logic [31:0] test_mode_reg,injection_address,hold_address;
  logic [63:0] test_cycles,irq_due_reg;
  wire  externalInterrupt;
  wire  trace_predictor_ready;
  wire  iAxi_ar_valid;
  wire  iAxi_ar_ready;
  wire [31:0] iAxi_ar_payload_addr;
  wire [7:0] iAxi_ar_payload_len;
  wire [1:0] iAxi_ar_payload_burst;
  wire [3:0] iAxi_ar_payload_cache;
  wire [2:0] iAxi_ar_payload_prot;
  wire  iAxi_r_valid;
  wire  iAxi_r_ready;
  wire [31:0] iAxi_r_payload_data;
  wire [1:0] iAxi_r_payload_resp;
  wire  iAxi_r_payload_last;
  wire  dAxi_aw_valid;
  wire  dAxi_aw_ready;
  wire [31:0] dAxi_aw_payload_addr;
  wire [7:0] dAxi_aw_payload_len;
  wire [2:0] dAxi_aw_payload_size;
  wire [3:0] dAxi_aw_payload_cache;
  wire [2:0] dAxi_aw_payload_prot;
  wire  dAxi_w_valid;
  wire  dAxi_w_ready;
  wire [31:0] dAxi_w_payload_data;
  wire [3:0] dAxi_w_payload_strb;
  wire  dAxi_w_payload_last;
  wire  dAxi_b_valid;
  wire  dAxi_b_ready;
  wire [1:0] dAxi_b_payload_resp;
  wire  dAxi_ar_valid;
  wire  dAxi_ar_ready;
  wire [31:0] dAxi_ar_payload_addr;
  wire [7:0] dAxi_ar_payload_len;
  wire [2:0] dAxi_ar_payload_size;
  wire [3:0] dAxi_ar_payload_cache;
  wire [2:0] dAxi_ar_payload_prot;
  wire  dAxi_r_valid;
  wire  dAxi_r_ready;
  wire [31:0] dAxi_r_payload_data;
  wire [1:0] dAxi_r_payload_resp;
  wire  dAxi_r_payload_last;
  wire [31:0] trace_instruction;
  wire  trace_stall;
  wire  trace_branch;
  wire [31:0] trace_branch_pc;
  wire  trace_mispredict;
  wire trace_trap;
  wire [31:0] trace_cause,trace_trap_pc,trace_mtval,trace_mepc;
  T09Cpu cpu(.*);
  axi4_if #(.DATA_W(32),.ID_W(1)) imem(clk),cpu_bus(clk),dmem(clk),imem_port(clk),dmem_port(clk);
  axi4_if #(.DATA_W(128),.ID_W(6)) native(clk),backend(clk),external_mem(clk),nmem(clk),arb_nmem(clk);
  logic owner,isolate,backend_idle,backend_error,clear_error,irq,backend_irq;
  logic[31:0] backend_fault;
  nx_ce64_bridge bridge(.clk,.reset_n(!reset),.model_sealed,.backend_idle(backend_idle||negative_early),
    .backend_error,.backend_irq,.backend_fault_address(backend_fault),.owner,.isolate,
    .clear_backend_error(clear_error),.irq,.cpu(cpu_bus),.memory(dmem),.coral(native));
  wire ce_clear_guard;
  wire ce_w_capture,combined_w_capture;
  nx_ce64_guard guard(.clk,.reset_n(!reset),.isolate(isolate||!owner),.clear_error(clear_error||ce_clear_guard),
    .idle(guard_idle),.error(backend_error),.fault_address(backend_fault),.upstream(backend),.downstream(external_mem));
  nx_ce64_bus_stats cs(.clk,.reset_n,.bus(backend),.stats(ce_stats));
  wire halted,fault,wfi;
  wire native_pending,upstream_pending,native_safely_drained,native_quarantined,ce_quarantined,ce_drained,ce_idle,guard_idle;
  wire[2:0] awprot,arprot;
  wire awlock,arlock;
  wire[3:0] awcache,arcache,awqos,arqos,awregion,arregion;
  logic core_running;
  wire[63:0] irq_due;
  assign test_mode=ENABLE_TEST_CONTROL?test_mode_reg:32'd0;
  assign cycles=ENABLE_TEST_CONTROL?test_cycles:64'd0;
  assign irq_due=ENABLE_TEST_CONTROL?irq_due_reg:64'd0;
  wire ce_irq;
  wire raw_backend_irq=ce_irq||backend_error||ce_quarantined||native_quarantined;
  assign backend_irq=raw_backend_irq && test_mode!=1 && (test_mode!=2||(irq_due!=0&&cycles>=irq_due));
  logic prev_halted;
  assign halted=ce_idle;
  assign fault=ce_quarantined;
  assign wfi=0;
  assign backend_idle=ce_idle && guard_idle && !native_quarantined;
  axi4_if #(.DATA_W(128),.ID_W(6)) ce_mmio(clk);
  nx_ce64_mmio_fault #(.ENABLE(ENABLE_TEST_CONTROL)) mmio_fault(.clk,.reset_n,.stale(negative_stale),.upstream(native),.downstream(ce_mmio));
  generate if(ENABLE_CE)begin:compute
  nx_ce64 #(.LONG_PV(LONG_PV),.HEAD_ARGMAX(HEAD_ARGMAX),.A_W_BANKED(A_W_BANKED),.W_PREFETCH(W_PREFETCH),.AQSA_RESIDENT(AQSA_RESIDENT),.CROSS_GROUP_WRITE(CROSS_GROUP_WRITE)) ce(.clk,.platform_reset_n(reset_n),.startup_authorized,.external_isolate(isolate||!owner||!model_sealed),
    .external_window_isolate(isolate||!model_sealed),
    .guard_idle,.guard_fault(backend_error),.native_safely_drained,.native_quarantined,
    .visible_fault_address(backend_fault),.mmio(ce_mmio),.memory(backend),
    .irq(ce_irq),.idle(ce_idle),.quarantined(ce_quarantined),.drained(ce_drained),.clear_guard_error(ce_clear_guard),
    .memory_w_capture(ce_w_capture));
  end else begin:cpu_ddr_only
    nx_ce64_disabled no_ce(.clk,.reset_n,.bus(ce_mmio));
    assign ce_irq=0;assign ce_idle=1;assign ce_quarantined=0;
    assign ce_drained=native_safely_drained;assign ce_clear_guard=0;
    assign ce_w_capture=0;
    assign backend.awvalid=0;assign backend.wvalid=0;assign backend.arvalid=0;
    assign backend.bready=1;assign backend.rready=1;
    assign backend.awaddr=0;assign backend.awid=0;assign backend.awlen=0;assign backend.awsize=0;assign backend.awburst=1;
    assign backend.wdata=0;assign backend.wstrb=0;assign backend.wlast=1;
    assign backend.araddr=0;assign backend.arid=0;assign backend.arlen=0;assign backend.arsize=0;assign backend.arburst=1;
  end endgenerate
  nx_shared_memory_arbiter fabric(.clk,.reset_n(!reset),.up_i(imem),.up_d(dmem),.up_n(arb_nmem),.dn_i(imem_port),.dn_d(dmem_port),.dn_n(nmem));
  axi4_if #(.DATA_W(128),.ID_W(6)) test_nmem(clk);
  axi4_if #(.DATA_W(128),.ID_W(6)) combined_nmem(clk);
  nx_soc_test_response #(.ENABLE_TEST_CONTROL(ENABLE_TEST_CONTROL)) test_response(.clk,.reset_n,.mode(test_mode),.injection_address,.hold_address,.cycles,
      .upstream(nmem),.downstream(test_nmem));
  nx_ce64_aux_mux auxiliary_mux(.clk,.reset_n,.ce(test_nmem),.aux(auxiliary),.memory(combined_nmem),
    .ce_w_capture,.memory_w_capture(combined_w_capture));
  nx_ce64_ddr_fabric #(.WRITE_DRAIN_CYCLES(WRITE_DRAIN_CYCLES),.W_READ_OVERLAP(1)) ddr_fabric(.clk,.reset_n(!reset),.ddr_init_done,
    .coral_w_capture(combined_w_capture),
    .cpu_i(imem_port),.cpu_d(dmem_port),.coral(combined_nmem),.local_i,.local_d,.local_n,
    .d_awaddr,.d_araddr,.d_awid,.d_arid,.d_awlen,.d_arlen,.d_awvalid,.d_arvalid,.d_awready,.d_arready,.d_wready,.d_wlast,
    .d_wdata,.d_wstrb,.d_rdata,.d_rid,.d_rvalid,.d_rlast,.native_pending,.upstream_pending,.safely_drained(native_safely_drained),.quarantined(native_quarantined),.fault(ddr_fault),.fault_reason(ddr_fault_reason),
    .cpu_i_stats,.cpu_d_stats,.cycles(ddr_cycles),.write_payload_bytes(ddr_write_bytes),.read_payload_bytes(ddr_read_bytes),.native_write_bytes,.native_read_bytes);
  assign native_quarantine_status=native_quarantined;
  assign arb_nmem.awaddr=external_mem.awaddr;
  assign arb_nmem.awid=external_mem.awid;
  assign arb_nmem.awlen=external_mem.awlen;
  assign arb_nmem.awsize=external_mem.awsize;
  assign arb_nmem.awburst=external_mem.awburst;
  assign arb_nmem.awvalid=external_mem.awvalid;
  assign arb_nmem.wdata=external_mem.wdata;
  assign arb_nmem.wstrb=external_mem.wstrb;
  assign arb_nmem.wlast=external_mem.wlast;
  assign arb_nmem.wvalid=external_mem.wvalid;
  assign arb_nmem.bready=external_mem.bready;
  assign arb_nmem.araddr=external_mem.araddr;
  assign arb_nmem.arid=external_mem.arid;
  assign arb_nmem.arlen=external_mem.arlen;
  assign arb_nmem.arsize=external_mem.arsize;
  assign arb_nmem.arburst=external_mem.arburst;
  assign arb_nmem.arvalid=external_mem.arvalid;
  assign arb_nmem.rready=external_mem.rready;
  assign external_mem.awready=arb_nmem.awready;
  assign external_mem.wready=arb_nmem.wready;
  assign external_mem.bid=arb_nmem.bid;
  assign external_mem.bresp=arb_nmem.bresp;
  assign external_mem.bvalid=arb_nmem.bvalid;
  assign external_mem.arready=arb_nmem.arready;
  assign external_mem.rid=arb_nmem.rid;
  assign external_mem.rdata=arb_nmem.rdata;
  assign external_mem.rresp=arb_nmem.rresp;
  assign external_mem.rlast=arb_nmem.rlast;
  assign external_mem.rvalid=arb_nmem.rvalid;
  assign imem.awvalid=0;assign imem.awaddr=0;assign imem.awid=0;assign imem.awlen=0;
  assign imem.awsize=2;assign imem.awburst=1;assign imem.wvalid=0;assign imem.wdata=0;
  assign imem.wstrb=0;assign imem.wlast=0;assign imem.bready=1;
  assign imem.arvalid=iAxi_ar_valid;assign iAxi_ar_ready=imem.arready;
  assign imem.araddr=iAxi_ar_payload_addr;assign imem.arlen=iAxi_ar_payload_len;
  assign imem.arid=0;assign imem.arsize=2;assign imem.arburst=iAxi_ar_payload_burst;
  assign iAxi_r_valid=imem.rvalid;assign imem.rready=iAxi_r_ready;
  assign iAxi_r_payload_data=imem.rdata;assign iAxi_r_payload_resp=imem.rresp;assign iAxi_r_payload_last=imem.rlast;
  assign cpu_bus.awvalid=dAxi_aw_valid;assign dAxi_aw_ready=cpu_bus.awready;
  assign cpu_bus.awaddr=dAxi_aw_payload_addr;assign cpu_bus.awlen=dAxi_aw_payload_len;
  assign cpu_bus.awsize=dAxi_aw_payload_size;assign cpu_bus.awid=0;assign cpu_bus.awburst=1;
  assign cpu_bus.wvalid=dAxi_w_valid;assign dAxi_w_ready=cpu_bus.wready;
  assign cpu_bus.wdata=dAxi_w_payload_data;assign cpu_bus.wstrb=dAxi_w_payload_strb;assign cpu_bus.wlast=dAxi_w_payload_last;
  assign dAxi_b_valid=cpu_bus.bvalid;assign cpu_bus.bready=dAxi_b_ready;assign dAxi_b_payload_resp=cpu_bus.bresp;
  assign cpu_bus.arvalid=dAxi_ar_valid;assign dAxi_ar_ready=cpu_bus.arready;
  assign cpu_bus.araddr=dAxi_ar_payload_addr;assign cpu_bus.arlen=dAxi_ar_payload_len;
  assign cpu_bus.arsize=dAxi_ar_payload_size;assign cpu_bus.arid=0;assign cpu_bus.arburst=1;
  assign dAxi_r_valid=cpu_bus.rvalid;assign cpu_bus.rready=dAxi_r_ready;
  assign dAxi_r_payload_data=cpu_bus.rdata;assign dAxi_r_payload_resp=cpu_bus.rresp;assign dAxi_r_payload_last=cpu_bus.rlast;

  generate if(ENABLE_REQUEST_PMU)begin:request_observer
    nx_ce64_request_pmu pmu(.clk,.reset_n,.retire(trace_retire),.execute_stall(trace_stall),
      .branch(trace_branch),.mispredict(trace_mispredict),.control(local_d),
      .cpu_i(imem),.cpu_d(cpu_bus),.ce(backend),.snapshot(request_pmu_stats));
  end else begin:no_request_observer
    assign request_pmu_stats=2048'b0;
  end endgenerate

  assign externalInterrupt=irq||uartInterrupt;
  // Passive observation: data refers to this core-clock cycle. CSR mtval is
  // the registered prior entry value on the trace_trap pulse (updated next edge).
  wire [31:0] debug_flags={9'b0,trace_instruction==32'h30200073,
    native_pending,upstream_pending,native_safely_drained,native_quarantined,
    ce_quarantined,ce_idle,backend_error,guard_idle,isolate,owner,ce_irq,
    dAxi_b_payload_resp,dAxi_b_valid&&dAxi_b_ready,
    dAxi_w_valid&&dAxi_w_ready,dAxi_aw_valid&&dAxi_aw_ready,
    trace_trap,trace_retire,timerInterrupt,uartInterrupt,irq,externalInterrupt};
  assign debug_observe={debug_flags,trace_cause,dAxi_aw_payload_addr,
    trace_mtval,trace_trap_pc,trace_pc};
  assign accel_owner=owner; assign accel_irq=irq;
  assign backend_idle_status=backend_idle; assign ddr_fault_status=ddr_fault;
  wire ddr_fault;
  logic aw_seen, w_seen;
  logic [31:0] control_address, control_data;
  always_ff @(posedge clk) begin
    if(!reset_n)begin test_cycles<=0;test_mode_reg<=0;injection_address<=0;hold_address<=0;irq_due_reg<=0;prev_halted<=0;end
    else begin
      test_cycles<=test_cycles+1;prev_halted<=halted;
      if(halted&&!prev_halted)irq_due_reg<=test_cycles+64'd150000;
      if(aw_seen&&w_seen)begin
        if(control_address==32'h100000a0)test_mode_reg<=control_data;
        if(control_address==32'h100000a4)injection_address<=control_data;
        if(control_address==32'h100000a8)hold_address<=control_data;
        if(control_address==32'h10003020)irq_due_reg<=0;
      end
    end
  end
  always_ff @(posedge clk) begin
    if(!reset_n) begin aw_seen<=0;w_seen<=0;control_address<=0;control_data<=0;core_running<=0;end
    else begin
      if(cpu_bus.awvalid && cpu_bus.awready) begin aw_seen<=1;control_address<=cpu_bus.awaddr;end
      if(cpu_bus.wvalid && cpu_bus.wready) begin w_seen<=1;control_data<=cpu_bus.wdata;end
      if(aw_seen && w_seen) begin
        if(control_address==32'h10003020) core_running<=1;
        aw_seen<=0;w_seen<=0;
      end
    end
  end
endmodule
