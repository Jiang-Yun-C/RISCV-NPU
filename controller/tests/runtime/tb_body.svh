  // The two T04 AXI responders share one sparse backing store. This remains a
  // behavioral memory; instruction execution and every report come from RTL.
  axi4_if #(.DATA_W(32),.ID_W(1)) imem(clk),dmem(clk);
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
  assign dmem.awvalid=dAxi_aw_valid;assign dAxi_aw_ready=dmem.awready;
  assign dmem.awaddr=dAxi_aw_payload_addr;assign dmem.awlen=dAxi_aw_payload_len;
  assign dmem.awsize=dAxi_aw_payload_size;assign dmem.awid=0;assign dmem.awburst=1;
  assign dmem.wvalid=dAxi_w_valid;assign dAxi_w_ready=dmem.wready;
  assign dmem.wdata=dAxi_w_payload_data;assign dmem.wstrb=dAxi_w_payload_strb;assign dmem.wlast=dAxi_w_payload_last;
  assign dAxi_b_valid=dmem.bvalid;assign dmem.bready=dAxi_b_ready;assign dAxi_b_payload_resp=dmem.bresp;
  assign dmem.arvalid=dAxi_ar_valid;assign dAxi_ar_ready=dmem.arready;
  assign dmem.araddr=dAxi_ar_payload_addr;assign dmem.arlen=dAxi_ar_payload_len;
  assign dmem.arsize=dAxi_ar_payload_size;assign dmem.arid=0;assign dmem.arburst=1;
  assign dAxi_r_valid=dmem.rvalid;assign dmem.rready=dAxi_r_ready;
  assign dAxi_r_payload_data=dmem.rdata;assign dAxi_r_payload_resp=dmem.rresp;assign dAxi_r_payload_last=dmem.rlast;

  longint unsigned cycles=0,retired=0,axi_reads=0,axi_writes=0,protocol_checks=0;
  logic completed=0,timed_out=0,protection_error=0;
  logic [31:0] exit_code=0,report_tag=0;
  int report_count=0,fd,stack_fd;
  typedef struct packed {logic[31:0] address;logic[2:0] size;} address_t;
  typedef struct packed {logic[31:0] data;logic[3:0] strobe;logic last;} data_t;
  address_t addresses[$],wa;data_t writes[$],wd;
  logic [31:0] peek_address=0,peek_value=0;
  logic held_reset=0;
  initial begin
    clk=0;reset=1;timerInterrupt=0;externalInterrupt=0;softwareInterrupt=0;rom_data=0;
    if($value$plusargs("seed=%d",seed))begin end
    if($value$plusargs("max_delay=%d",delay_limit))begin end
    if($value$plusargs("max_cycles=%d",max_cycles))begin end
    held_reset=$test$plusargs("held_reset");
    fd=$fopen("cpu-output.txt","w");
    if(!fd)$fatal(1,"cannot open CPU observations");
    #1;i_memory.mem=d_memory.mem;
    $dumpfile("cpu.vcd");$dumpvars(0,clk,reset,trace_retire,trace_pc,trace_instruction,completed,report_count);
    #119;if(!held_reset)reset=0;
  end
  always #5 clk=~clk;
  always @(peek_address)begin
    #1;peek_value=0;
    for(int i=0;i<4;i++)peek_value[8*i+:8]=d_memory.mem.read_byte(64'(peek_address)+i);
  end
  always @(posedge clk)begin
    cycles<=cycles+1;
    if(cycles==10000)$dumpoff;
    if(cycles>=max_cycles)timed_out<=1;
    if(rom_enable)for(int i=0;i<4;i++)rom_data[8*i+:8]<=d_memory.mem.read_byte(64'(rom_address)+i);
    if(!reset)begin
      if(trace_retire)retired<=retired+1;
      axi_reads<=axi_reads+int'(imem.rvalid&&imem.rready)+int'(dmem.rvalid&&dmem.rready);
      if(imem.rvalid&&imem.rready&&imem.rresp!=0)$fatal(1,"I read error");
      if(dmem.rvalid&&dmem.rready&&dmem.rresp!=0)$fatal(1,"D read error");
      if(dmem.bvalid&&dmem.bready&&dmem.bresp!=0)$fatal(1,"D write error");
      if(dmem.awvalid&&dmem.awready)begin
        if(dmem.awlen!=0||dmem.awsize>2)$fatal(1,"unexpected CPU write burst/size");
        addresses.push_back('{dmem.awaddr,dmem.awsize});protocol_checks++;
      end
      if(dmem.wvalid&&dmem.wready)begin
        if(!dmem.wlast)$fatal(1,"CPU WLAST");
        writes.push_back('{dmem.wdata,dmem.wstrb,dmem.wlast});protocol_checks++;
      end
      if(addresses.size()&&writes.size())begin
        wa=addresses.pop_front();wd=writes.pop_front();axi_writes++;
        if(!(wa.address>=32'hb4000000&&wa.address<32'hb5000000)&&
           !(wa.address>=32'hb7ff0010&&wa.address<32'hb8000000)&&
           !(wa.address>=32'ha8000000&&wa.address<32'ha8f00000)&&
           !(wa.address>=32'hac000000&&wa.address<32'hafe3a980)&&
           !(wa.address>=32'h10000000&&wa.address<32'h10001000))protection_error<=1;
        if(wa.address==32'h10000080)begin
          if(wd.strobe!=15)$fatal(1,"partial report tag");report_tag=wd.data;
        end
        if(wa.address==32'h10000084)begin
          if(wd.strobe!=15)$fatal(1,"partial report value");
          $fwrite(fd,"%0d %0d %0d\n",report_tag[31:16],report_tag[15:0],wd.data);$fflush(fd);report_count++;
        end
        if(wa.address==32'h10000020)begin completed<=1;exit_code<=wd.data;end
      end
    end
  end
  // Channel stability is checked independently of the active T04 responders.
  assert property(@(posedge clk) disable iff(reset) dmem.awvalid&&!dmem.awready |=> dmem.awvalid&&$stable({dmem.awaddr,dmem.awlen,dmem.awsize})) else $fatal(1,"AW stability");
  assert property(@(posedge clk) disable iff(reset) dmem.wvalid&&!dmem.wready |=> dmem.wvalid&&$stable({dmem.wdata,dmem.wstrb,dmem.wlast})) else $fatal(1,"W stability");
  assert property(@(posedge clk) disable iff(reset) dmem.arvalid&&!dmem.arready |=> dmem.arvalid&&$stable({dmem.araddr,dmem.arlen,dmem.arsize})) else $fatal(1,"AR stability");
  assert property(@(posedge clk) disable iff(reset) imem.arvalid&&!imem.arready |=> imem.arvalid&&$stable({imem.araddr,imem.arlen})) else $fatal(1,"I AR stability");
