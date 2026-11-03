  // The two T04 AXI responders share one sparse backing store. This remains a
  // behavioral memory; instruction execution and every report come from RTL.
  axi4_if #(.DATA_W(32),.ID_W(1)) imem(clk),dmem(clk);
  axi4_if #(.DATA_W(32),.ID_W(1)) cpu_bus(clk),uart_bus(clk);
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
  t17_uart_router router(.clk,.reset,.cpu_bus,.memory_bus(dmem),.uart_bus);
  localparam integer UART_DIVISOR=`OPT06_UART_DIVISOR;
  t17_uart #(.DIVISOR(UART_DIVISOR)) uart(.clk,.reset,.rx(uart_rx),.tx(uart_tx),.boot_mode,.preload_bytes,
               .app_signature,.app_data_signature,.source_mode,.fault_code,.bus(uart_bus));

  longint unsigned cycles=0,retired=0;
  logic timed_out=0,flush_trace=0;
  integer trace_fd;string image_plan;
  initial begin
    clk=0;reset=1;timerInterrupt=0;externalInterrupt=0;softwareInterrupt=0;rom_data=0;
    if($value$plusargs("seed=%d",seed))begin end
    if($value$plusargs("max_delay=%d",delay_limit))begin end
    if($value$plusargs("max_cycles=%d",max_cycles))begin end
    if(!$value$plusargs("image_plan=%s",image_plan))$fatal(1,"image plan required");
    trace_fd=$fopen("uart-writes.csv","w");
    #1;i_memory.mem=d_memory.mem;
    $dumpfile("cpu.vcd");$dumpvars(0,uart_rx,uart_tx,reset,app_signature,fault_code);
    #119;if(!$test$plusargs("held_reset"))reset=0;
  end
  always #5 clk=~clk;
  always @(posedge clk)begin
    cycles<=cycles+1;if(cycles>=max_cycles)timed_out<=1;
    if(rom_enable)for(int i=0;i<4;i++)rom_data[8*i+:8]<=d_memory.mem.read_byte(64'(rom_address)+i);
    if(!reset)begin
      if(trace_retire)retired<=retired+1;
      if(uart.tx_valid)$fwrite(trace_fd,"%0d,%0d\n",cycles,uart.tx_data);
    end
    if(flush_trace)begin $fflush(trace_fd);$dumpflush;end
  end
  assert property(@(posedge clk) disable iff(reset) cpu_bus.arvalid&&!cpu_bus.arready |=> cpu_bus.arvalid&&$stable({cpu_bus.araddr,cpu_bus.arlen,cpu_bus.arsize})) else $fatal(1,"cpu_bus ar stability");
  assert property(@(posedge clk) disable iff(reset) cpu_bus.rvalid&&!cpu_bus.rready |=> cpu_bus.rvalid&&$stable({cpu_bus.rdata,cpu_bus.rresp,cpu_bus.rlast})) else $fatal(1,"cpu_bus r stability");
  assert property(@(posedge clk) disable iff(reset) cpu_bus.awvalid&&!cpu_bus.awready |=> cpu_bus.awvalid&&$stable({cpu_bus.awaddr,cpu_bus.awlen,cpu_bus.awsize})) else $fatal(1,"cpu_bus aw stability");
  assert property(@(posedge clk) disable iff(reset) cpu_bus.wvalid&&!cpu_bus.wready |=> cpu_bus.wvalid&&$stable({cpu_bus.wdata,cpu_bus.wstrb,cpu_bus.wlast})) else $fatal(1,"cpu_bus w stability");
  assert property(@(posedge clk) disable iff(reset) cpu_bus.bvalid&&!cpu_bus.bready |=> cpu_bus.bvalid&&$stable({cpu_bus.bresp})) else $fatal(1,"cpu_bus b stability");
  assert property(@(posedge clk) disable iff(reset) imem.arvalid&&!imem.arready |=> imem.arvalid&&$stable({imem.araddr,imem.arlen,imem.arsize})) else $fatal(1,"imem ar stability");
  assert property(@(posedge clk) disable iff(reset) imem.rvalid&&!imem.rready |=> imem.rvalid&&$stable({imem.rdata,imem.rresp,imem.rlast})) else $fatal(1,"imem r stability");

  // Passive physical-pin decoder. Cocotb reads these observations, never DUT
  // results or generated tokens. Framing faults are counted and must be zero.
  integer tx_count=0,tx_framing_errors=0;
  reg [7:0] tx_bytes[0:149999];
  longint unsigned tx_cycles[0:149999];
  initial begin : passive_uart
    reg [7:0] value;longint unsigned first;
    wait(!reset);
    forever begin
      @(negedge uart_tx);first=cycles;
      #(UART_DIVISOR*5);if(uart_tx!==0)tx_framing_errors++;
      for(int bit_index=0;bit_index<8;bit_index++)begin #(UART_DIVISOR*10);value[bit_index]=uart_tx;end
      #(UART_DIVISOR*10);if(uart_tx!==1)tx_framing_errors++;
      if(tx_count>=150000)$fatal(1,"UART monitor capacity");
      tx_bytes[tx_count]=value;tx_cycles[tx_count]=first;tx_count++;
    end
  end

  integer rx_count=0,rx_framing_errors=0;
  reg [7:0] rx_bytes[0:255];
  longint unsigned rx_cycles[0:255];
  initial begin : passive_rx
    reg [7:0] value;longint unsigned first;wait(!reset);
    forever begin
      @(negedge uart_rx);first=cycles;#(UART_DIVISOR*5);if(uart_rx!==0)rx_framing_errors++;
      for(int bit_index=0;bit_index<8;bit_index++)begin #(UART_DIVISOR*10);value[bit_index]=uart_rx;end
      #(UART_DIVISOR*10);if(uart_rx!==1)rx_framing_errors++;
      if(rx_count>=256)$fatal(1,"RX monitor capacity");rx_bytes[rx_count]=value;rx_cycles[rx_count]=first;rx_count++;
    end
  end
