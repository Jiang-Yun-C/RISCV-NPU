  longint unsigned cycles=0,retired=0;
  axi4_if #(.DATA_W(32),.ID_W(1)) imem(clk),cpu_bus(clk),dmem(clk);
  axi4_if #(.DATA_W(128),.ID_W(6)) native(clk),backend(clk),external_mem(clk),nmem(clk);
  int unsigned seed=1,delay_limit=3,max_cycles=1500000;
  int test_mode=0;
  logic owner,isolate,backend_idle,backend_error,clear_error,irq,backend_irq;
  logic[31:0] backend_fault,launches;
  logic negative_early=0,negative_stale=0;
  logic previous_irq=0;
  nx_accel_bridge bridge(.clk,.reset_n(!reset),.backend_idle(backend_idle||negative_early),
    .backend_error,.backend_irq,.backend_fault_address(backend_fault),.owner,.isolate,
    .clear_backend_error(clear_error),.irq,.cpu(cpu_bus),.memory(dmem),.coral(native));
  nx_accel_guard guard(.clk,.reset_n(!reset),.isolate(isolate||!owner),.clear_error,
    .idle(backend_idle),.error(backend_error),.fault_address(backend_fault),.upstream(backend),.downstream(external_mem));
  coral_transaction_endpoint endpoint(.clk,.reset_n(!reset),.mode(test_mode),.cycle(cycles[31:0]),
    .interrupt(backend_irq),.launches,.stale_data(negative_stale),.slave(native),.master(backend));
  axi_sparse_mem #(.DATA_W(32),.ID_W(1),.BASE_ADDR(0),.SIZE_BYTES(64'h100000000)) i_memory
    (.clk,.reset_n(!reset),.random_delays(1'b1),.seed(seed^32'h49),.max_delay(delay_limit),
     .inject_enable(1'b0),.inject_start(32'b0),.inject_end(32'b0),.inject_resp(2'b0),.bus(imem));
  axi_sparse_mem #(.DATA_W(32),.ID_W(1),.BASE_ADDR(0),.SIZE_BYTES(64'h100000000)) d_memory
    (.clk,.reset_n(!reset),.random_delays(1'b1),.seed(seed^32'h44),.max_delay(delay_limit),
     .inject_enable(1'b0),.inject_start(32'b0),.inject_end(32'b0),.inject_resp(2'b0),.bus(dmem));
  axi_sparse_mem #(.DATA_W(128),.ID_W(6),.BASE_ADDR(0),.SIZE_BYTES(64'h100000000)) n_memory
    (.clk,.reset_n(!reset),.random_delays(1'b1),.seed(seed^32'h4e),.max_delay(delay_limit),
     .inject_enable(test_mode==4||test_mode==9),
     .inject_start(test_mode==9?32'hac000000:32'hba000000),
     .inject_end(test_mode==9?32'hac00003f:32'hba00003f),.inject_resp(2'b10),.bus(nmem));
  logic[63:0] hold_until=0;
  assign nmem.awvalid=external_mem.awvalid;assign external_mem.awready=nmem.awready;
  assign nmem.awaddr=external_mem.awaddr;assign nmem.awid=external_mem.awid;
  assign nmem.awlen=external_mem.awlen;assign nmem.awsize=external_mem.awsize;assign nmem.awburst=external_mem.awburst;
  assign nmem.wvalid=external_mem.wvalid;assign external_mem.wready=nmem.wready;
  assign nmem.wdata=external_mem.wdata;assign nmem.wstrb=external_mem.wstrb;assign nmem.wlast=external_mem.wlast;
  assign external_mem.bvalid=nmem.bvalid&&cycles>=hold_until;
  assign nmem.bready=external_mem.bready&&cycles>=hold_until;
  assign external_mem.bresp=nmem.bresp;assign external_mem.bid=nmem.bid;
  assign nmem.arvalid=external_mem.arvalid;assign external_mem.arready=nmem.arready;
  assign nmem.araddr=external_mem.araddr;assign nmem.arid=external_mem.arid;
  assign nmem.arlen=external_mem.arlen;assign nmem.arsize=external_mem.arsize;assign nmem.arburst=external_mem.arburst;
  assign external_mem.rvalid=nmem.rvalid;assign nmem.rready=external_mem.rready;
  assign external_mem.rdata=nmem.rdata;assign external_mem.rid=nmem.rid;assign external_mem.rresp=nmem.rresp;assign external_mem.rlast=nmem.rlast;
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
  int fd,trace_fd,report_count=0;
  typedef struct packed {logic[31:0] address;logic[2:0] size;} address_t;
  typedef struct packed {logic[31:0] data;logic[3:0] strobe;} data_t;
  address_t addresses[$],wa;data_t writes[$],wd;
  logic[31:0] peek_address=0,peek_value=0;
  assign externalInterrupt=irq;
  initial begin
    clk=0;reset=1;timerInterrupt=0;softwareInterrupt=0;rom_data=0;
    if($value$plusargs("seed=%d",seed))begin end
    if($value$plusargs("max_delay=%d",delay_limit))begin end
    if($value$plusargs("max_cycles=%d",max_cycles))begin end
    held_reset=$test$plusargs("held_reset");negative_early=$test$plusargs("early_completion");negative_stale=$test$plusargs("stale_data");
    fd=$fopen("cpu-output.txt","w");trace_fd=$fopen("transactions.csv","w");
    if(!fd||!trace_fd)$fatal(1,"cannot open observations");
    #1;i_memory.mem=d_memory.mem;n_memory.mem=d_memory.mem;
    $dumpfile("cpu.vcd");$dumpvars(0,clk,reset,completed,owner,isolate,backend_idle,backend_error,irq,launches,
      backend.awvalid,backend.awready,backend.wvalid,backend.wready,backend.bvalid,backend.bready,
      backend.arvalid,backend.arready,backend.rvalid,backend.rready,report_count);
    $dumpvars(0,backend.awaddr,backend.awid,backend.awsize,backend.wdata,backend.wstrb,backend.bid,backend.bresp,backend.araddr,backend.arid,backend.arsize,backend.rdata,backend.rresp);
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
    if(!reset)begin
      if(trace_retire)retired<=retired+1;
      previous_irq<=irq;
      if(irq&&!previous_irq)$fwrite(trace_fd,"%0d,IRQ,0,%h,%h,%0d\n",cycles,launches,test_mode,owner);
      if(nmem.awvalid&&nmem.awready&&nmem.awaddr==32'hba00003c&&(test_mode==1||test_mode==10))
        hold_until<=cycles+(test_mode==1?6000:40000);
      if(cpu_bus.awvalid&&cpu_bus.awready)addresses.push_back('{cpu_bus.awaddr,cpu_bus.awsize});
      if(cpu_bus.wvalid&&cpu_bus.wready)writes.push_back('{cpu_bus.wdata,cpu_bus.wstrb});
      if(addresses.size()&&writes.size())begin
        wa=addresses.pop_front();wd=writes.pop_front();
        $fwrite(trace_fd,"%0d,CW,%h,%h,%h,%0d\n",cycles,wa.address,wd.data,wd.strobe,owner);
        if(wa.address==32'h100000a0)test_mode=wd.data;
        if(wa.address==32'h10000080)report_tag=wd.data;
        if(wa.address==32'h10000084)begin
          $fwrite(fd,"%0d %0d %0d\n",report_tag[31:16],report_tag[15:0],wd.data);$fflush(fd);report_count++;
        end
        if(wa.address==32'h10000020)begin completed<=1;exit_code<=wd.data;end
      end
      if(cpu_bus.arvalid&&cpu_bus.arready)$fwrite(trace_fd,"%0d,CR,%h,%h,%h,%0d\n",cycles,cpu_bus.araddr,cpu_bus.arlen,cpu_bus.arsize,owner);
      if(cpu_bus.bvalid&&cpu_bus.bready)$fwrite(trace_fd,"%0d,CB,0,0,%h,%0d\n",cycles,cpu_bus.bresp,owner);
      if(cpu_bus.rvalid&&cpu_bus.rready)$fwrite(trace_fd,"%0d,CD,0,%h,%h,%0d\n",cycles,cpu_bus.rdata,cpu_bus.rresp,owner);
      if(native.awvalid&&native.awready)$fwrite(trace_fd,"%0d,SA,%h,0,%h,0\n",cycles,native.awaddr,native.awsize);
      if(native.wvalid&&native.wready)$fwrite(trace_fd,"%0d,SW,0,%h,%h,0\n",cycles,native.wdata,native.wstrb);
      if(backend.awvalid&&backend.awready)$fwrite(trace_fd,"%0d,NA,%h,%h,%h,%0d\n",cycles,backend.awaddr,backend.awid,backend.awsize,owner);
      if(backend.wvalid&&backend.wready)$fwrite(trace_fd,"%0d,NW,0,%h,%h,%0d\n",cycles,backend.wdata,backend.wstrb,owner);
      if(backend.bvalid&&backend.bready)$fwrite(trace_fd,"%0d,NB,0,%h,%h,%0d\n",cycles,backend.bid,backend.bresp,owner);
      if(backend.arvalid&&backend.arready)$fwrite(trace_fd,"%0d,NR,%h,%h,%h,%0d\n",cycles,backend.araddr,backend.arid,backend.arsize,owner);
      if(backend.rvalid&&backend.rready)$fwrite(trace_fd,"%0d,ND,0,%h,%h,%0d\n",cycles,backend.rdata,backend.rresp,owner);
      if(nmem.awvalid&&nmem.awready)$fwrite(trace_fd,"%0d,MA,%h,%h,%h,%0d\n",cycles,nmem.awaddr,nmem.awid,nmem.awsize,owner);
      if(nmem.bvalid&&nmem.bready)$fwrite(trace_fd,"%0d,MB,0,%h,%h,%0d\n",cycles,nmem.bid,nmem.bresp,owner);
      if(!owner&&!backend_idle)$fwrite(trace_fd,"%0d,EARLY,0,0,0,0\n",cycles);
      $fflush(trace_fd);
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
  // Component coverage is separate from real firmware execution above.
  axi4_if #(.DATA_W(128),.ID_W(6)) probe_up(clk),probe_down(clk);
  logic probe_reset_n=0,probe_isolate=0,probe_clear=0,probe_idle,probe_error;
  logic[31:0] probe_fault;
  nx_accel_guard component_guard(.clk,.reset_n(probe_reset_n),.isolate(probe_isolate),.clear_error(probe_clear),
    .idle(probe_idle),.error(probe_error),.fault_address(probe_fault),.upstream(probe_up),.downstream(probe_down));
  axi_sparse_mem #(.DATA_W(128),.ID_W(6),.BASE_ADDR(0),.SIZE_BYTES(64'h100000000)) probe_memory
    (.clk,.reset_n(probe_reset_n),.random_delays(1'b1),.seed(seed^32'h50),.max_delay(delay_limit),
     .inject_enable(1'b0),.inject_start(32'b0),.inject_end(32'b0),.inject_resp(2'b0),.bus(probe_down));
