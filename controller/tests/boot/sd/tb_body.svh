  // The two T04 AXI responders share one sparse backing store. This remains a
  // behavioral memory; instruction execution and every report come from RTL.
  axi4_if #(.DATA_W(32),.ID_W(1)) imem(clk),dmem(clk);
  axi4_if #(.DATA_W(32),.ID_W(1)) cpu_bus(clk),uart_bus(clk),downstream(clk),spi_bus(clk);
  int unsigned seed=1,delay_limit=3,max_cycles=100000000;
  logic random_delays=1;
  axi_sparse_mem #(.DATA_W(32),.ID_W(1),.BASE_ADDR(0),.SIZE_BYTES(64'h100000000)) i_memory
    (.clk,.reset_n(!reset),.random_delays,.seed(seed^32'h49),.max_delay(delay_limit),
     .inject_enable(1'b0),.inject_start(32'b0),.inject_end(32'b0),.inject_resp(2'b0),.bus(imem));
  axi_sparse_mem #(.DATA_W(32),.ID_W(1),.BASE_ADDR(0),.SIZE_BYTES(64'h100000000)) d_memory
    (.clk,.reset_n(!reset),.random_delays,.seed(seed^32'h44),.max_delay(delay_limit),
     .inject_enable(1'b0),.inject_start(32'b0),.inject_end(32'b0),.inject_resp(2'b0),.bus(dmem));
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


  // VPI drives the host source; an SV edge drives the physical UART pin.
  // The passive monitor samples that pin without VPI edge callbacks.
  logic host_rx=1,uart_rx=1;wire uart_tx;
  always @(negedge clk)uart_rx<=host_rx;
  logic [31:0] app_signature,app_data_signature,source_mode,fault_code;
  logic [31:0] boot_mode=0,preload_bytes=0;
  t17_uart_router router(.clk,.reset,.cpu_bus,.memory_bus(downstream),.uart_bus);
  t17_uart_router #(.MMIO_BASE(32'h10002000)) spi_router(.clk,.reset,.cpu_bus(downstream),.memory_bus(dmem),.uart_bus(spi_bus));
  logic host_miso=1,spi_miso=1; wire spi_sck,spi_cs,spi_mosi;
  logic [31:0] card_generation=0,model_ready,boot_error,boot_done,selftest,directory_count;
  longint unsigned cycles=0,retired=0;
  int unsigned ddr_delay=1000;logic ddr_block=0;wire ddr_ready=!ddr_block&&cycles>=ddr_delay;
  always @(negedge clk)spi_miso<=host_miso;
  t18_spi spi(.clk,.reset,.miso(spi_miso),.card_generation,.ddr_ready,
    .sck(spi_sck),.cs_n(spi_cs),.mosi(spi_mosi),.model_ready,.boot_error,.boot_done,.selftest,.directory_count,.bus(spi_bus));
  integer spi_fd;integer spi_bits=0;logic [7:0] pin_tx=0,pin_rx=0;
  always @(posedge spi_sck)begin
    pin_tx={pin_tx[6:0],spi_mosi};pin_rx={pin_rx[6:0],spi_miso};spi_bits=spi_bits+1;
    if(spi_bits==8)begin $fwrite(spi_fd,"%0d,S,%0d,%0d,%0d\n",cycles,pin_tx,pin_rx,spi_cs);spi_bits=0;end
  end
  always @(posedge spi_cs or negedge spi_cs)begin spi_bits=0;pin_tx=0;pin_rx=0;end
  t17_uart uart(.clk,.reset,.rx(uart_rx),.tx(uart_tx),.boot_mode,.preload_bytes,
               .app_signature,.app_data_signature,.source_mode,.fault_code,.bus(uart_bus));
  logic timed_out=0,capture=0,captured=0,flush_trace=0;
  logic [31:0] peek_address=0,peek_value=0;
  integer trace_fd,initial_fd,final_fd,boot_bytes;
  string boot_file,app_file,test_mode;
  logic held_reset=0;string snapshot;integer snapshot_fd;logic [31:0] capture_id=0;
  initial begin
    clk=0;reset=1;timerInterrupt=0;externalInterrupt=0;softwareInterrupt=0;rom_data=0;
    if($value$plusargs("seed=%d",seed))begin end
    if($value$plusargs("max_delay=%d",delay_limit))begin end
    if($value$plusargs("max_cycles=%d",max_cycles))begin end
    if($value$plusargs("ddr_delay=%d",ddr_delay))begin end
    if(!$value$plusargs("boot=%s",boot_file)||!$value$plusargs("boot_bytes=%d",boot_bytes))$fatal(1,"boot ROM missing");
    if(boot_bytes<=0||boot_bytes>65536)$fatal(1,"boot ROM range");
    if(!$value$plusargs("mode=%s",test_mode))$fatal(1,"explicit boot mode required");
    held_reset=$test$plusargs("held_reset");
    spi_fd=$fopen("spi.csv","w");$fwrite(spi_fd,"cycle,kind,a,b,c\n");
    trace_fd=$fopen("transactions.csv","w");
    $fwrite(trace_fd,"cycle,kind,a,b,c\n");
    #1;i_memory.mem=d_memory.mem;
    d_memory.mem.load_bin(boot_file,64'h10000,64'(boot_bytes));
    if(test_mode!="PROTOCOL_BOOT"||$test$plusargs("app=")||$test$plusargs("model="))$fatal(1,"SD PROTOCOL_BOOT forbids app/model preload");
    initial_fd=$fopen("initial.bin","wb");
    for(int i=0;i<65536;i++)$fwrite(initial_fd,"%c",d_memory.mem.read_byte(64'hb4000000+i));
    for(int i=0;i<131072;i++)$fwrite(initial_fd,"%c",d_memory.mem.read_byte(64'h80000000+i));
    for(int i=0;i<128;i++)$fwrite(initial_fd,"%c",d_memory.mem.read_byte(64'hb8000000+i));
    $fclose(initial_fd);
    $display("T18 LOAD_SOURCE=%s boot_bytes=%0d application_preloaded=%0d",test_mode,boot_bytes,preload_bytes);
    $dumpfile("cpu.vcd");$dumpvars(0,spi_sck,spi_cs,spi_mosi,spi_miso,reset,model_ready,boot_error,boot_done);
    #119;if(!held_reset)reset=0;
  end
  always #5 clk=~clk;
  always @(peek_address)begin
    #1;peek_value=0;
    for(int i=0;i<4;i++)peek_value[8*i+:8]=d_memory.mem.read_byte(64'(peek_address)+i);
  end
  always @(posedge clk)begin
    cycles<=cycles+1;
    if(cycles>=max_cycles)timed_out<=1;
    if(rom_enable)for(int i=0;i<4;i++)rom_data[8*i+:8]<=d_memory.mem.read_byte(64'(rom_address)+i);
    if(!reset)begin
      if(trace_retire)begin
        retired<=retired+1;
        if((trace_pc>=32'hb4000000&&trace_pc<32'hb4010000)||trace_instruction==32'h0000100f||trace_instruction==32'h0000500f)
          $fwrite(trace_fd,"%0d,T,%0d,%0d,0\n",cycles,trace_pc,trace_instruction);
      end
      if(cpu_bus.awvalid&&cpu_bus.awready)$fwrite(trace_fd,"%0d,DA,%0d,%0d,%0d\n",cycles,cpu_bus.awaddr,cpu_bus.awlen,cpu_bus.awsize);
      if(cpu_bus.wvalid&&cpu_bus.wready)$fwrite(trace_fd,"%0d,DW,%0d,%0d,%0d\n",cycles,cpu_bus.wdata,cpu_bus.wstrb,cpu_bus.wlast);
      if(cpu_bus.bvalid&&cpu_bus.bready)$fwrite(trace_fd,"%0d,DB,%0d,0,0\n",cycles,cpu_bus.bresp);
      if(cpu_bus.arvalid&&cpu_bus.arready)$fwrite(trace_fd,"%0d,DR,%0d,%0d,%0d\n",cycles,cpu_bus.araddr,cpu_bus.arlen,cpu_bus.arsize);
      if(cpu_bus.rvalid&&cpu_bus.rready)$fwrite(trace_fd,"%0d,DD,%0d,%0d,%0d\n",cycles,cpu_bus.rdata,cpu_bus.rresp,cpu_bus.rlast);
      if(imem.arvalid&&imem.arready)$fwrite(trace_fd,"%0d,IA,%0d,%0d,2\n",cycles,imem.araddr,imem.arlen);
      if(imem.rvalid&&imem.rready)$fwrite(trace_fd,"%0d,IR,%0d,%0d,%0d\n",cycles,imem.rdata,imem.rresp,imem.rlast);
    end
    if(flush_trace)$fflush(trace_fd);
    if(cycles==2000000)$dumpoff;
    if(!capture)captured<=0;
    if(capture&&!captured)begin
      $fflush(trace_fd);$fflush(spi_fd);
      snapshot=$sformatf("snapshot-%0d.bin",capture_id);snapshot_fd=$fopen(snapshot,"wb");
      for(int i=0;i<65536;i++)$fwrite(snapshot_fd,"%c",d_memory.mem.read_byte(64'hb4000000+i));
      for(int i=0;i<131072;i++)$fwrite(snapshot_fd,"%c",d_memory.mem.read_byte(64'h80000000+i));
      for(int i=0;i<128;i++)$fwrite(snapshot_fd,"%c",d_memory.mem.read_byte(64'hb8000000+i));
      $fclose(snapshot_fd);captured<=1;$dumpflush;
      snapshot=$sformatf("stack-%0d.bin",capture_id);snapshot_fd=$fopen(snapshot,"wb");
      for(int i=0;i<32768;i++)$fwrite(snapshot_fd,"%c",d_memory.mem.read_byte(64'h28000+i));
      $fclose(snapshot_fd);
    end
  end
  assert property(@(posedge clk) disable iff(reset) cpu_bus.arvalid&&!cpu_bus.arready |=> cpu_bus.arvalid&&$stable({cpu_bus.araddr,cpu_bus.arlen,cpu_bus.arsize})) else $fatal(1,"cpu_bus ar stability");
  assert property(@(posedge clk) disable iff(reset) cpu_bus.rvalid&&!cpu_bus.rready |=> cpu_bus.rvalid&&$stable({cpu_bus.rdata,cpu_bus.rresp,cpu_bus.rlast})) else $fatal(1,"cpu_bus r stability");
  assert property(@(posedge clk) disable iff(reset) cpu_bus.awvalid&&!cpu_bus.awready |=> cpu_bus.awvalid&&$stable({cpu_bus.awaddr,cpu_bus.awlen,cpu_bus.awsize})) else $fatal(1,"cpu_bus aw stability");
  assert property(@(posedge clk) disable iff(reset) cpu_bus.wvalid&&!cpu_bus.wready |=> cpu_bus.wvalid&&$stable({cpu_bus.wdata,cpu_bus.wstrb,cpu_bus.wlast})) else $fatal(1,"cpu_bus w stability");
  assert property(@(posedge clk) disable iff(reset) cpu_bus.bvalid&&!cpu_bus.bready |=> cpu_bus.bvalid&&$stable({cpu_bus.bresp})) else $fatal(1,"cpu_bus b stability");
  assert property(@(posedge clk) disable iff(reset) imem.arvalid&&!imem.arready |=> imem.arvalid&&$stable({imem.araddr,imem.arlen,imem.arsize})) else $fatal(1,"imem ar stability");
  assert property(@(posedge clk) disable iff(reset) imem.rvalid&&!imem.rready |=> imem.rvalid&&$stable({imem.rdata,imem.rresp,imem.rlast})) else $fatal(1,"imem r stability");
