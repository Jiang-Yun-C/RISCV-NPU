// Synthesizable CPU/Coral compute and native DDR boundary, core clock domain.
// Local device/ROM ports, PLL and physical HMIC PHY are connected by the board shell.
module nx_soc_core #(parameter WRITE_DRAIN_CYCLES=1024, ENABLE_TEST_CONTROL=0)(
  input wire clk, reset_n, ddr_init_done, timerInterrupt,
  input wire [31:0] rom_data,
  output wire rom_enable,
  output wire [31:0] rom_address,
  output wire trace_retire,
  output wire [31:0] trace_pc,
  output wire accel_owner, accel_irq, backend_idle_status, ddr_fault_status,
  axi4_if.master local_i, local_d, local_n,
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
  T09Cpu cpu(.*);
  axi4_if #(.DATA_W(32),.ID_W(1)) imem(clk),cpu_bus(clk),dmem(clk),imem_port(clk),dmem_port(clk);
  axi4_if #(.DATA_W(128),.ID_W(6)) native(clk),backend(clk),external_mem(clk),nmem(clk),arb_nmem(clk);
  logic owner,isolate,backend_idle,backend_error,clear_error,irq,backend_irq;
  logic[31:0] backend_fault;
  nx_accel_bridge bridge(.clk,.reset_n(!reset),.backend_idle(backend_idle||negative_early),
    .backend_error,.backend_irq,.backend_fault_address(backend_fault),.owner,.isolate,
    .clear_backend_error(clear_error),.irq,.cpu(cpu_bus),.memory(dmem),.coral(native));
  nx_accel_guard guard(.clk,.reset_n(!reset),.isolate(isolate||!owner),.clear_error,
    .idle(backend_idle),.error(backend_error),.fault_address(backend_fault),.upstream(backend),.downstream(external_mem));
  wire halted,fault,wfi;
  wire[127:0] native_read_data;
  assign native.rdata=negative_stale&&native.araddr==32'h10110 ? native_read_data ^ 128'd1 : native_read_data;
  wire[2:0] awprot,arprot;
  wire awlock,arlock;
  wire[3:0] awcache,arcache,awqos,arqos,awregion,arregion;
  logic core_running;
  wire[63:0] irq_due;
  assign test_mode=ENABLE_TEST_CONTROL?test_mode_reg:32'd0;
  assign cycles=ENABLE_TEST_CONTROL?test_cycles:64'd0;
  assign irq_due=ENABLE_TEST_CONTROL?irq_due_reg:64'd0;
  wire raw_backend_irq=halted&&!fault&&core_running;
  assign backend_irq=raw_backend_irq && test_mode!=1 && (test_mode!=2||(irq_due!=0&&cycles>=irq_due));
  logic prev_halted;
  `CORAL_TOP coral (
    .io_aclk(clk), .io_aresetn(!reset), .io_te(1'b0),
    .io_irq(1'b0), .io_timer_irq(1'b0), .io_software_irq(1'b0), .io_boot_addr(32'b0),
    .io_halted(halted), .io_fault(fault), .io_wfi(wfi),
    .io_dm_req_valid(1'b0), .io_dm_req_bits_address(32'b0),
    .io_dm_req_bits_data(32'b0), .io_dm_req_bits_op(2'b0), .io_dm_rsp_ready(1'b1),
    .io_axi_slave_write_addr_valid(native.awvalid), .io_axi_slave_write_addr_ready(native.awready),
    .io_axi_slave_write_addr_bits_addr(native.awaddr), .io_axi_slave_write_addr_bits_prot(3'b0),
    .io_axi_slave_write_addr_bits_id(native.awid), .io_axi_slave_write_addr_bits_len(8'b0),
    .io_axi_slave_write_addr_bits_size(native.awsize), .io_axi_slave_write_addr_bits_burst(2'd1),
    .io_axi_slave_write_addr_bits_lock(1'b0), .io_axi_slave_write_addr_bits_cache(4'b0),
    .io_axi_slave_write_addr_bits_qos(4'b0), .io_axi_slave_write_addr_bits_region(4'b0),
    .io_axi_slave_write_data_valid(native.wvalid), .io_axi_slave_write_data_ready(native.wready),
    .io_axi_slave_write_data_bits_data(native.wdata), .io_axi_slave_write_data_bits_strb(native.wstrb),
    .io_axi_slave_write_data_bits_last(1'b1),
    .io_axi_slave_write_resp_ready(native.bready), .io_axi_slave_write_resp_valid(native.bvalid),
    .io_axi_slave_write_resp_bits_resp(native.bresp), .io_axi_slave_write_resp_bits_id(native.bid),
    .io_axi_slave_read_addr_valid(native.arvalid), .io_axi_slave_read_addr_ready(native.arready),
    .io_axi_slave_read_addr_bits_addr(native.araddr), .io_axi_slave_read_addr_bits_prot(3'b0),
    .io_axi_slave_read_addr_bits_id(native.arid), .io_axi_slave_read_addr_bits_len(8'b0),
    .io_axi_slave_read_addr_bits_size(native.arsize), .io_axi_slave_read_addr_bits_burst(2'd1),
    .io_axi_slave_read_addr_bits_lock(1'b0), .io_axi_slave_read_addr_bits_cache(4'b0),
    .io_axi_slave_read_addr_bits_qos(4'b0), .io_axi_slave_read_addr_bits_region(4'b0),
    .io_axi_slave_read_data_ready(native.rready), .io_axi_slave_read_data_valid(native.rvalid),
    .io_axi_slave_read_data_bits_data(native_read_data), .io_axi_slave_read_data_bits_resp(native.rresp),
    .io_axi_slave_read_data_bits_id(native.rid), .io_axi_slave_read_data_bits_last(native.rlast),
    .io_axi_master_write_addr_ready(backend.awready),
    .io_axi_master_write_addr_valid(backend.awvalid),
    .io_axi_master_write_addr_bits_addr(backend.awaddr),
    .io_axi_master_write_addr_bits_prot(awprot),
    .io_axi_master_write_addr_bits_id(backend.awid),
    .io_axi_master_write_addr_bits_len(backend.awlen),
    .io_axi_master_write_addr_bits_size(backend.awsize),
    .io_axi_master_write_addr_bits_burst(backend.awburst),
    .io_axi_master_write_addr_bits_lock(awlock),
    .io_axi_master_write_addr_bits_cache(awcache),
    .io_axi_master_write_addr_bits_qos(awqos),
    .io_axi_master_write_addr_bits_region(awregion),
    .io_axi_master_write_data_ready(backend.wready),
    .io_axi_master_write_data_valid(backend.wvalid),
    .io_axi_master_write_data_bits_data(backend.wdata),
    .io_axi_master_write_data_bits_strb(backend.wstrb),
    .io_axi_master_write_data_bits_last(backend.wlast),
    .io_axi_master_write_resp_ready(backend.bready),
    .io_axi_master_write_resp_valid(backend.bvalid),
    .io_axi_master_write_resp_bits_id(backend.bid),
    .io_axi_master_write_resp_bits_resp(backend.bresp),
    .io_axi_master_read_addr_ready(backend.arready),
    .io_axi_master_read_addr_valid(backend.arvalid),
    .io_axi_master_read_addr_bits_addr(backend.araddr),
    .io_axi_master_read_addr_bits_prot(arprot),
    .io_axi_master_read_addr_bits_id(backend.arid),
    .io_axi_master_read_addr_bits_len(backend.arlen),
    .io_axi_master_read_addr_bits_size(backend.arsize),
    .io_axi_master_read_addr_bits_burst(backend.arburst),
    .io_axi_master_read_addr_bits_lock(arlock),
    .io_axi_master_read_addr_bits_cache(arcache),
    .io_axi_master_read_addr_bits_qos(arqos),
    .io_axi_master_read_addr_bits_region(arregion),
    .io_axi_master_read_data_ready(backend.rready),
    .io_axi_master_read_data_valid(backend.rvalid),
    .io_axi_master_read_data_bits_id(backend.rid),
    .io_axi_master_read_data_bits_data(backend.rdata),
    .io_axi_master_read_data_bits_resp(backend.rresp),
    .io_axi_master_read_data_bits_last(backend.rlast)
  );
  nx_shared_memory_arbiter fabric(.clk,.reset_n(!reset),.up_i(imem),.up_d(dmem),.up_n(arb_nmem),.dn_i(imem_port),.dn_d(dmem_port),.dn_n(nmem));
  axi4_if #(.DATA_W(128),.ID_W(6)) test_nmem(clk);
  nx_soc_test_response #(.ENABLE_TEST_CONTROL(ENABLE_TEST_CONTROL)) test_response(.clk,.reset_n,.mode(test_mode),.injection_address,.hold_address,.cycles,
      .upstream(nmem),.downstream(test_nmem));
  nx_soc_ddr_fabric #(.WRITE_DRAIN_CYCLES(WRITE_DRAIN_CYCLES)) ddr_fabric(.clk,.reset_n(!reset),.ddr_init_done,
    .cpu_i(imem_port),.cpu_d(dmem_port),.coral(test_nmem),.local_i,.local_d,.local_n,
    .d_awaddr,.d_araddr,.d_awid,.d_arid,.d_awlen,.d_arlen,.d_awvalid,.d_arvalid,.d_awready,.d_arready,.d_wready,.d_wlast,
    .d_wdata,.d_wstrb,.d_rdata,.d_rid,.d_rvalid,.d_rlast,.fault(ddr_fault),.fault_reason(ddr_fault_reason),
    .cycles(ddr_cycles),.write_payload_bytes(ddr_write_bytes),.read_payload_bytes(ddr_read_bytes),.native_write_bytes,.native_read_bytes);
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

  assign externalInterrupt=irq;
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
        if(control_address==32'h20030000&&control_data==0)irq_due_reg<=0;
      end
    end
  end
  always_ff @(posedge clk) begin
    if(!reset_n) begin aw_seen<=0;w_seen<=0;control_address<=0;control_data<=0;core_running<=0;end
    else begin
      if(cpu_bus.awvalid && cpu_bus.awready) begin aw_seen<=1;control_address<=cpu_bus.awaddr;end
      if(cpu_bus.wvalid && cpu_bus.wready) begin w_seen<=1;control_data<=cpu_bus.wdata;end
      if(aw_seen && w_seen) begin
        if(control_address==32'h20030000) core_running<=control_data==0;
        aw_seen<=0;w_seen<=0;
      end
    end
  end
endmodule
