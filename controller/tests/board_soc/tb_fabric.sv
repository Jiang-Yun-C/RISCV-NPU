`timescale 1ns/1ps
module tb_fabric;
  logic clk=0, reset_n=0, ddr_init_done=0;
  always #5 clk=~clk;
  axi4_if #(.DATA_W(32),.ID_W(1)) cpu_i(clk),cpu_d(clk),local_i(clk),local_d(clk);
  axi4_if #(.DATA_W(128),.ID_W(6)) coral(clk),local_n(clk);
  wire [27:0] d_awaddr,d_araddr;
  wire [3:0] d_awid,d_arid,d_awlen,d_arlen;
  wire d_awvalid,d_arvalid,d_awready,d_arready,d_wready,d_wlast;
  wire [255:0] d_wdata,d_rdata;
  wire [31:0] d_wstrb;
  wire [3:0] d_rid;
  wire d_rvalid,d_rlast,fault;
  wire [3:0] fault_reason;
  wire [63:0] cycles,write_payload_bytes,read_payload_bytes,native_write_bytes,native_read_bytes;
  nx_soc_ddr_fabric #(.WRITE_DRAIN_CYCLES(8)) dut(.*);
  t24_native_memory_model memory(.clk,.reset_n,.d_awaddr,.d_araddr,.d_awid,.d_arid,.d_awlen,.d_arlen,
    .d_awvalid,.d_arvalid,.d_awready,.d_arready,.d_wready,.d_wlast,.d_wdata,.d_wstrb,.d_rdata,.d_rid,.d_rvalid,.d_rlast);
  axi_sparse_mem #(.DATA_W(32),.ID_W(1),.BASE_ADDR(0),.SIZE_BYTES(64'h100000000)) li
    (.clk,.reset_n,.random_delays(1'b0),.seed(32'd1),.max_delay(0),.inject_enable(1'b0),.inject_start(32'b0),.inject_end(32'b0),.inject_resp(2'b0),.bus(local_i));
  axi_sparse_mem #(.DATA_W(32),.ID_W(1),.BASE_ADDR(0),.SIZE_BYTES(64'h100000000)) ld
    (.clk,.reset_n,.random_delays(1'b0),.seed(32'd1),.max_delay(0),.inject_enable(1'b0),.inject_start(32'b0),.inject_end(32'b0),.inject_resp(2'b0),.bus(local_d));
  axi_sparse_mem #(.DATA_W(128),.ID_W(6),.BASE_ADDR(0),.SIZE_BYTES(64'h100000000)) ln
    (.clk,.reset_n,.random_delays(1'b0),.seed(32'd1),.max_delay(0),.inject_enable(1'b0),.inject_start(32'b0),.inject_end(32'b0),.inject_resp(2'b0),.bus(local_n));
  integer checks=0;
  initial begin $dumpfile("fabric.vcd");$dumpvars(0,tb_fabric); #2000000; $fatal(1,"fabric test timeout");end
  task automatic require(input bit yes,input string why);
    if(!yes)$fatal(1,"fabric checker: %s",why);checks++;
  endtask
  task automatic init_cpu_i;
    cpu_i.awvalid=0;cpu_i.wvalid=0;cpu_i.bready=0;cpu_i.arvalid=0;cpu_i.rready=0;
    cpu_i.awaddr=0;cpu_i.awid=0;cpu_i.awlen=0;cpu_i.awsize=0;cpu_i.awburst=1;
    cpu_i.wdata=0;cpu_i.wstrb=0;cpu_i.wlast=0;
    cpu_i.araddr=0;cpu_i.arid=0;cpu_i.arlen=0;cpu_i.arsize=0;cpu_i.arburst=1;
  endtask
  task automatic write_cpu_i(input logic[31:0] address,input integer size,len,id,tag,input bit early_last=0,input bit hold_b=0,input bit partial=0);
    logic [31:0] data;
    @(negedge clk);cpu_i.awaddr=address;cpu_i.awsize=3'(size);cpu_i.awlen=8'(len);cpu_i.awid=1'(id);cpu_i.awvalid=1;
    do @(posedge clk);while(!cpu_i.awready);
    @(negedge clk);cpu_i.awvalid=0;
    for(int beat=0;beat<=len;beat++)begin
      data=0;for(int i=0;i<4;i++)data[8*i+:8]=8'(tag+beat*4+i);
      cpu_i.wdata=data;cpu_i.wstrb=partial ? 4'd1 << address[1:0] : 4'((1<<4)-1);
      cpu_i.wlast=early_last ? beat==0 : beat==len;cpu_i.wvalid=1;
      do @(posedge clk);while(!cpu_i.wready);
      @(negedge clk);cpu_i.wvalid=0;
      repeat(2)@(negedge clk);
    end
    if(hold_b)begin
      wait(cpu_i.bvalid);require(cpu_i.bid==id && cpu_i.bresp==0,"held B identity");
    end else begin
      cpu_i.bready=1;do @(posedge clk);while(!cpu_i.bvalid);
      require(cpu_i.bid==id,"cpu_i B ID");require(cpu_i.bresp==(early_last ? 2 : 0),"cpu_i B status");
      @(negedge clk);cpu_i.bready=0;
    end
  endtask
  task automatic read_cpu_i(input logic[31:0] address,input integer size,len,id,tag);
    logic [31:0] expected;
    @(negedge clk);cpu_i.araddr=address;cpu_i.arsize=3'(size);cpu_i.arlen=8'(len);cpu_i.arid=1'(id);cpu_i.arvalid=1;
    do @(posedge clk);while(!cpu_i.arready);
    @(negedge clk);cpu_i.arvalid=0;
    for(int beat=0;beat<=len;beat++)begin
      repeat(3)@(negedge clk);cpu_i.rready=1;
      do @(posedge clk);while(!cpu_i.rvalid);
      expected=0;for(int i=0;i<4;i++)expected[8*i+:8]=8'(tag+beat*4+i);
      require(cpu_i.rid==id,"cpu_i R ID");require(cpu_i.rresp==0,"cpu_i R status");
      require(cpu_i.rlast==(beat==len),"cpu_i RLAST");require(cpu_i.rdata==expected,"cpu_i byte/lane/burst data");
      @(negedge clk);cpu_i.rready=0;
    end
  endtask
  task automatic init_cpu_d;
    cpu_d.awvalid=0;cpu_d.wvalid=0;cpu_d.bready=0;cpu_d.arvalid=0;cpu_d.rready=0;
    cpu_d.awaddr=0;cpu_d.awid=0;cpu_d.awlen=0;cpu_d.awsize=0;cpu_d.awburst=1;
    cpu_d.wdata=0;cpu_d.wstrb=0;cpu_d.wlast=0;
    cpu_d.araddr=0;cpu_d.arid=0;cpu_d.arlen=0;cpu_d.arsize=0;cpu_d.arburst=1;
  endtask
  task automatic write_cpu_d(input logic[31:0] address,input integer size,len,id,tag,input bit early_last=0,input bit hold_b=0,input bit partial=0);
    logic [31:0] data;
    @(negedge clk);cpu_d.awaddr=address;cpu_d.awsize=3'(size);cpu_d.awlen=8'(len);cpu_d.awid=1'(id);cpu_d.awvalid=1;
    do @(posedge clk);while(!cpu_d.awready);
    @(negedge clk);cpu_d.awvalid=0;
    for(int beat=0;beat<=len;beat++)begin
      data=0;for(int i=0;i<4;i++)data[8*i+:8]=8'(tag+beat*4+i);
      cpu_d.wdata=data;cpu_d.wstrb=partial ? 4'd1 << address[1:0] : 4'((1<<4)-1);
      cpu_d.wlast=early_last ? beat==0 : beat==len;cpu_d.wvalid=1;
      do @(posedge clk);while(!cpu_d.wready);
      @(negedge clk);cpu_d.wvalid=0;
      repeat(2)@(negedge clk);
    end
    if(hold_b)begin
      wait(cpu_d.bvalid);require(cpu_d.bid==id && cpu_d.bresp==0,"held B identity");
    end else begin
      cpu_d.bready=1;do @(posedge clk);while(!cpu_d.bvalid);
      require(cpu_d.bid==id,"cpu_d B ID");require(cpu_d.bresp==(early_last ? 2 : 0),"cpu_d B status");
      @(negedge clk);cpu_d.bready=0;
    end
  endtask
  task automatic read_cpu_d(input logic[31:0] address,input integer size,len,id,tag);
    logic [31:0] expected;
    @(negedge clk);cpu_d.araddr=address;cpu_d.arsize=3'(size);cpu_d.arlen=8'(len);cpu_d.arid=1'(id);cpu_d.arvalid=1;
    do @(posedge clk);while(!cpu_d.arready);
    @(negedge clk);cpu_d.arvalid=0;
    for(int beat=0;beat<=len;beat++)begin
      repeat(3)@(negedge clk);cpu_d.rready=1;
      do @(posedge clk);while(!cpu_d.rvalid);
      expected=0;for(int i=0;i<4;i++)expected[8*i+:8]=8'(tag+beat*4+i);
      require(cpu_d.rid==id,"cpu_d R ID");require(cpu_d.rresp==0,"cpu_d R status");
      require(cpu_d.rlast==(beat==len),"cpu_d RLAST");require(cpu_d.rdata==expected,"cpu_d byte/lane/burst data");
      @(negedge clk);cpu_d.rready=0;
    end
  endtask
  task automatic init_coral;
    coral.awvalid=0;coral.wvalid=0;coral.bready=0;coral.arvalid=0;coral.rready=0;
    coral.awaddr=0;coral.awid=0;coral.awlen=0;coral.awsize=0;coral.awburst=1;
    coral.wdata=0;coral.wstrb=0;coral.wlast=0;
    coral.araddr=0;coral.arid=0;coral.arlen=0;coral.arsize=0;coral.arburst=1;
  endtask
  task automatic write_coral(input logic[31:0] address,input integer size,len,id,tag,input bit early_last=0,input bit hold_b=0,input bit partial=0);
    logic [127:0] data;
    @(negedge clk);coral.awaddr=address;coral.awsize=3'(size);coral.awlen=8'(len);coral.awid=6'(id);coral.awvalid=1;
    do @(posedge clk);while(!coral.awready);
    @(negedge clk);coral.awvalid=0;
    for(int beat=0;beat<=len;beat++)begin
      data=0;for(int i=0;i<16;i++)data[8*i+:8]=8'(tag+beat*16+i);
      coral.wdata=data;coral.wstrb=partial ? 16'd1 << address[1:0] : 16'((1<<16)-1);
      coral.wlast=early_last ? beat==0 : beat==len;coral.wvalid=1;
      do @(posedge clk);while(!coral.wready);
      @(negedge clk);coral.wvalid=0;
      repeat(2)@(negedge clk);
    end
    if(hold_b)begin
      wait(coral.bvalid);require(coral.bid==id && coral.bresp==0,"held B identity");
    end else begin
      coral.bready=1;do @(posedge clk);while(!coral.bvalid);
      require(coral.bid==id,"coral B ID");require(coral.bresp==(early_last ? 2 : 0),"coral B status");
      @(negedge clk);coral.bready=0;
    end
  endtask
  task automatic read_coral(input logic[31:0] address,input integer size,len,id,tag);
    logic [127:0] expected;
    @(negedge clk);coral.araddr=address;coral.arsize=3'(size);coral.arlen=8'(len);coral.arid=6'(id);coral.arvalid=1;
    do @(posedge clk);while(!coral.arready);
    @(negedge clk);coral.arvalid=0;
    for(int beat=0;beat<=len;beat++)begin
      repeat(3)@(negedge clk);coral.rready=1;
      do @(posedge clk);while(!coral.rvalid);
      expected=0;for(int i=0;i<16;i++)expected[8*i+:8]=8'(tag+beat*16+i);
      require(coral.rid==id,"coral R ID");require(coral.rresp==0,"coral R status");
      require(coral.rlast==(beat==len),"coral RLAST");require(coral.rdata==expected,"coral byte/lane/burst data");
      @(negedge clk);coral.rready=0;
    end
  endtask
  initial begin
    integer fd;
    init_cpu_i();init_cpu_d();init_coral();
    repeat(4)@(negedge clk);reset_n=1;
    // Local access remains live before calibration.
    write_cpu_d(32'h10000040,2,0,1,19);
    read_cpu_d(32'h10000040,2,0,1,19);
    require(!ddr_init_done && !d_awvalid && !d_arvalid,"no native traffic before calibration");
    @(negedge clk);cpu_i.araddr=32'h80000000;cpu_i.arsize=2;cpu_i.arlen=0;cpu_i.arid=1;cpu_i.arvalid=1;
    repeat(12)begin @(posedge clk);require(!cpu_i.arready,"calibration blocks DDR acceptance");end
    @(negedge clk);reset_n=0;init_cpu_i();init_cpu_d();init_coral();
    repeat(4)@(negedge clk);reset_n=1;ddr_init_done=1;
    // Simultaneous CPU I/D/Coral requests, including cache bursts over 128-bit lanes.
    fork
      begin write_cpu_i(32'h80000104,2,15,1,31);read_cpu_i(32'h80000104,2,15,1,31);end
      begin write_cpu_d(32'hbffffc00,2,255,1,83);read_cpu_d(32'hbffffc00,2,255,1,83);end
      begin write_coral(32'h80002e00,4,31,37,149);read_coral(32'h80002e00,4,31,37,149);end
    join
    // Vex cached SIZE=2 byte writes normalize AW but retain all strobes.
    for(int lane=0;lane<16;lane++)begin
      write_cpu_d(32'h80004000+lane,2,0,1,213,0,0,1);
      require(memory.mem.read_byte(64'h80004000+lane)==8'(213+(lane%4)),"cached partial store byte");
    end
    // A backpressured Coral B must permit other masters and local accesses.
    write_coral(32'h80005000,4,0,41,61,0,1);
    fork
      read_cpu_i(32'h80000104,2,15,1,31);
      begin write_cpu_d(32'h10000044,2,0,1,23);read_cpu_d(32'h10000044,2,0,1,23);end
    join
    require(coral.bvalid && coral.bid==41 && coral.bresp==0,"held B stays stable while peers progress");
    @(negedge clk);coral.bready=1;@(posedge clk);@(negedge clk);coral.bready=0;
    // Malformed WLAST drains AWLEN beats and returns an error without deadlock.
    write_cpu_d(32'h80006000,2,2,1,17,1);
    write_cpu_d(32'h80006010,2,0,1,27);read_cpu_d(32'h80006010,2,0,1,27);
    require(!fault && write_payload_bytes>0 && read_payload_bytes>0,"adapter healthy and payload live");
    fd=$fopen("fabric-result.json","w");$fwrite(fd,"{\"status\":\"PASS\",\"checks\":%0d,\"native_checks\":%0d,\"board_qualified\":false}\n",checks,memory.native_checks);$fclose(fd);
    $display("T24_FABRIC_PASS checks=%0d native_checks=%0d",checks,memory.native_checks);$finish;
  end
endmodule
