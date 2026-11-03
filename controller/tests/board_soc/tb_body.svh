  longint unsigned cycles=0,retired=0;
  axi4_if #(.DATA_W(32),.ID_W(1)) imem(clk),cpu_bus(clk),dmem(clk),imem_port(clk),dmem_port(clk);
  axi4_if #(.DATA_W(128),.ID_W(6)) native(clk),backend(clk),external_mem(clk),nmem(clk),arb_nmem(clk),model_nmem(clk);
  int unsigned seed=1,delay_limit=3,max_cycles=25000000;
  int test_mode=0;
  logic[31:0] injection_address=0,hold_address=0;
  bit head_run=0;
  logic owner,isolate,backend_idle,backend_error,clear_error,irq,backend_irq;
  logic[31:0] backend_fault,launches=0;
  logic negative_early=0,negative_stale=0;
  logic previous_irq=0;
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
  logic core_running=0;
  logic[63:0] irq_due=0;
  wire raw_backend_irq=halted&&!fault&&core_running;
  assign backend_irq=raw_backend_irq && test_mode!=1 && (test_mode!=2||(irq_due!=0&&cycles>=irq_due));
  logic prev_halted=0;
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
  axi4_if #(.DATA_W(32),.ID_W(1)) local_i(clk),local_d(clk);
  axi4_if #(.DATA_W(128),.ID_W(6)) local_n(clk);
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
  nx_soc_ddr_fabric #(.WRITE_DRAIN_CYCLES(8)) ddr_fabric(.clk,.reset_n(!reset),.ddr_init_done,
    .cpu_i(imem_port),.cpu_d(dmem_port),.coral(model_nmem),.local_i,.local_d,.local_n,
    .d_awaddr,.d_araddr,.d_awid,.d_arid,.d_awlen,.d_arlen,.d_awvalid,.d_arvalid,.d_awready,.d_arready,.d_wready,.d_wlast,
    .d_wdata,.d_wstrb,.d_rdata,.d_rid,.d_rvalid,.d_rlast,.fault(ddr_fault),.fault_reason(ddr_fault_reason),
    .cycles(ddr_cycles),.write_payload_bytes(ddr_write_bytes),.read_payload_bytes(ddr_read_bytes),.native_write_bytes,.native_read_bytes);
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
  always @(posedge clk) begin
    if(reset) begin injected_read<=0;injected_write<=0;end
    else begin
      if(nmem.arvalid && nmem.arready) injected_read<=test_mode==3 && nmem.araddr<=injection_address+15 && nmem.araddr>=injection_address;
      if(nmem.awvalid && nmem.awready) injected_write<=test_mode==4 && nmem.awaddr<=injection_address+15 && nmem.awaddr>=injection_address;
    end
  end
  logic[63:0] hold_until=0;
  assign arb_nmem.awvalid=external_mem.awvalid;assign external_mem.awready=arb_nmem.awready;
  assign arb_nmem.awaddr=external_mem.awaddr;assign arb_nmem.awid=external_mem.awid;
  assign arb_nmem.awlen=external_mem.awlen;assign arb_nmem.awsize=external_mem.awsize;assign arb_nmem.awburst=external_mem.awburst;
  assign arb_nmem.wvalid=external_mem.wvalid;assign external_mem.wready=arb_nmem.wready;
  assign arb_nmem.wdata=external_mem.wdata;assign arb_nmem.wstrb=external_mem.wstrb;assign arb_nmem.wlast=external_mem.wlast;
  assign external_mem.bvalid=arb_nmem.bvalid;
  assign arb_nmem.bready=external_mem.bready;
  assign external_mem.bresp=arb_nmem.bresp;assign external_mem.bid=arb_nmem.bid;
  assign arb_nmem.arvalid=external_mem.arvalid;assign external_mem.arready=arb_nmem.arready;
  assign arb_nmem.araddr=external_mem.araddr;assign arb_nmem.arid=external_mem.arid;
  assign arb_nmem.arlen=external_mem.arlen;assign arb_nmem.arsize=external_mem.arsize;assign arb_nmem.arburst=external_mem.arburst;
  assign external_mem.rvalid=arb_nmem.rvalid;assign arb_nmem.rready=external_mem.rready;
  assign external_mem.rdata=arb_nmem.rdata;assign external_mem.rid=arb_nmem.rid;assign external_mem.rresp=arb_nmem.rresp;assign external_mem.rlast=arb_nmem.rlast;
  assign model_nmem.awvalid=nmem.awvalid;assign nmem.awready=model_nmem.awready;
  assign model_nmem.awaddr=nmem.awaddr;assign model_nmem.awid=nmem.awid;
  assign model_nmem.awlen=nmem.awlen;assign model_nmem.awsize=nmem.awsize;assign model_nmem.awburst=nmem.awburst;
  assign model_nmem.wvalid=nmem.wvalid;assign nmem.wready=model_nmem.wready;
  assign model_nmem.wdata=nmem.wdata;assign model_nmem.wstrb=nmem.wstrb;assign model_nmem.wlast=nmem.wlast;
  assign nmem.bvalid=model_nmem.bvalid&&cycles>=hold_until;
  assign model_nmem.bready=nmem.bready&&cycles>=hold_until;
  assign nmem.bresp=injected_write ? 2'b11 : model_nmem.bresp;assign nmem.bid=model_nmem.bid;
  assign model_nmem.arvalid=nmem.arvalid;assign nmem.arready=model_nmem.arready;
  assign model_nmem.araddr=nmem.araddr;assign model_nmem.arid=nmem.arid;
  assign model_nmem.arlen=nmem.arlen;assign model_nmem.arsize=nmem.arsize;assign model_nmem.arburst=nmem.arburst;
  assign nmem.rvalid=model_nmem.rvalid;assign model_nmem.rready=nmem.rready;
  assign nmem.rdata=model_nmem.rdata;assign nmem.rid=model_nmem.rid;assign nmem.rresp=injected_read ? 2'b10 : model_nmem.rresp;assign nmem.rlast=model_nmem.rlast;
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
        if(wa.address==32'h20030000)begin core_running<=wd.data==0;if(wd.data==0)begin launches<=launches+1;irq_due<=0;end end
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
