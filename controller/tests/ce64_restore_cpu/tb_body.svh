  axi4_if #(.DATA_W(32),.ID_W(1)) imem(clk),dmem(clk);
  int unsigned seed=1,max_delay=0;
  longint unsigned cycles=0,retired=0;
  axi_sparse_mem #(.DATA_W(32),.ID_W(1),.BASE_ADDR(0),.SIZE_BYTES(64'h100000000)) i_memory
    (.clk,.reset_n(!reset),.random_delays(1'b0),.seed(seed),.max_delay,
     .inject_enable(1'b0),.inject_start(32'b0),.inject_end(32'b0),.inject_resp(2'b0),.bus(imem));
  axi_sparse_mem #(.DATA_W(32),.ID_W(1),.BASE_ADDR(0),.SIZE_BYTES(64'h100000000)) d_memory
    (.clk,.reset_n(!reset),.random_delays(1'b0),.seed(seed),.max_delay,
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
  typedef struct packed {logic [31:0] address;logic [2:0] size;} address_t;
  typedef struct packed {logic [31:0] data;logic [3:0] strobe;} data_t;
  address_t addresses[$],wa;
  data_t writes[$],wd;
  integer fd,trace_fd,retire_fd;
  logic [31:0] report_tag=0;
  initial begin
    clk=0;reset=1;timerInterrupt=0;externalInterrupt=0;softwareInterrupt=0;rom_data=0;
    fd=$fopen("cpu-output.csv","w");trace_fd=$fopen("transactions.csv","w");retire_fd=$fopen("retire.csv","w");
    $fwrite(fd,"cycle,mode,index,value\n");$fwrite(trace_fd,"cycle,channel,address,data,length\n");$fwrite(retire_fd,"cycle,pc,instruction\n");
    #1;i_memory.mem=d_memory.mem;
    #119;reset=0;
  end
  always #4 clk=~clk;
  always @(posedge clk)begin
    cycles<=cycles+1;
    if(cycles>2000000)$fatal(1,"CPU watchdog");
    if(rom_enable)for(integer i=0;i<4;i++)rom_data[8*i+:8]<=d_memory.mem.read_byte(64'(rom_address)+i);
    if(!reset)begin
      if(trace_retire)begin retired++;$fwrite(retire_fd,"%0d,%h,%h\n",cycles,trace_pc,trace_instruction);end
      if(dmem.awvalid&&dmem.awready)addresses.push_back('{dmem.awaddr,dmem.awsize});
      if(dmem.wvalid&&dmem.wready)writes.push_back('{dmem.wdata,dmem.wstrb});
      if(addresses.size()&&writes.size())begin
        wa=addresses.pop_front();wd=writes.pop_front();
        $fwrite(trace_fd,"%0d,W,%h,%h,%0d\n",cycles,wa.address,wd.data,wa.size);
        if(wa.address==32'h10000080)report_tag=wd.data;
        if(wa.address==32'h10000084)$fwrite(fd,"%0d,%0d,%0d,%h\n",cycles,report_tag[31:16],report_tag[15:0],wd.data);
        if(wa.address==32'h10000020)begin
          $fclose(fd);$fclose(trace_fd);$fclose(retire_fd);
          if(wd.data!==32'h600ce640)$fatal(1,"CPU exit %h",wd.data);
          $display("CE64_CPU_EXIT cycles=%0d retired=%0d",cycles,retired);$finish;
        end
      end
      if(dmem.arvalid&&dmem.arready)$fwrite(trace_fd,"%0d,R,%h,0,%0d\n",cycles,dmem.araddr,dmem.arlen);
    end
  end
