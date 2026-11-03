`timescale 1ns/1ps
module tb_cpu;
 reg clk=0; always #5 clk=~clk;
 reg resetn=0;
 wire halted,fault,wfi;
 reg awvalid=0,wvalid=0,bready=0,arvalid=0,rready=0;
 wire awready,wready,bvalid,arready,rvalid;
 reg [31:0] awaddr=0,araddr=0;
 reg [2:0] awsize=4,arsize=4;
 reg [127:0] wdata=0;
 reg [15:0] wstrb=0;
 wire [127:0] rdata;
 wire [1:0] bresp,rresp;
 wire [5:0] bid,rid;
 wire rlast;
 wire [2:0] awprot,arprot;
 wire awlock,arlock;
 wire [3:0] awcache,arcache,awqos,arqos,awregion,arregion;
 integer cycle=0,seed=1;
 reg [31:0] rng=1;
 reg random_delays=1;
 int unsigned max_delay=7;
 integer max_cycles=20000000;
 reg inject_enable=0;
 reg [31:0] inject_start=0,inject_end=0;
 reg [1:0] inject_resp=2;
 reg isolate=1,clear_error=0,counter_clear=1;
 wire guard_idle,guard_error;
 wire [31:0] fault_address;
 axi4_if #(.DATA_W(128),.ID_W(6)) bus(clk),external_bus(clk);
 nx_accel_guard guard(.clk,.reset_n(resetn),.isolate,.clear_error,.idle(guard_idle),.error(guard_error),.fault_address,.upstream(bus),.downstream(external_bus));
 axi_sparse_mem #(.DATA_W(128),.ID_W(6),.TIMING_CONTROL(1)) memory
  (.clk,.reset_n(resetn),.random_delays,.seed,.max_delay,.inject_enable,.inject_start,.inject_end,.inject_resp,.bus(external_bus));
 wire [63:0] counter_cycles,counter_read,counter_write,counter_read_wait,counter_write_wait;
 wire [63:0] counter_ar,counter_r,counter_aw,counter_w,counter_b;
 nx_stream_counters counters(.clk,.reset_n(resetn),.clear(counter_clear),.bus,
  .cycles(counter_cycles),.read_bytes(counter_read),.write_bytes(counter_write),
  .read_wait(counter_read_wait),.write_wait(counter_write_wait),.ar_count(counter_ar),
  .r_count(counter_r),.aw_count(counter_aw),.w_count(counter_w),.b_count(counter_b));
 reg booted=0,timed_out=0;
 reg [2:0] command=0;
 reg [31:0] command_address=0;
 reg [127:0] command_data=0,reply_data=0;
 reg [15:0] command_strobe=16'hffff;
 reg [2:0] command_size=4;
 reg command_done=0;
 reg [127:0] image_words[0:2559];
 reg [127:0] value;
 string image_path;
 integer fd;
 integer boot_cycle=0;
 reg core_running=0;
  `CORAL_TOP dut (
    .io_aclk(clk), .io_aresetn(resetn), .io_te(1'b0),
    .io_irq(1'b0), .io_timer_irq(1'b0), .io_software_irq(1'b0), .io_boot_addr(32'b0),
    .io_halted(halted), .io_fault(fault), .io_wfi(wfi),
    .io_dm_req_valid(1'b0), .io_dm_req_bits_address(32'b0),
    .io_dm_req_bits_data(32'b0), .io_dm_req_bits_op(2'b0), .io_dm_rsp_ready(1'b1),
    .io_axi_slave_write_addr_valid(awvalid), .io_axi_slave_write_addr_ready(awready),
    .io_axi_slave_write_addr_bits_addr(awaddr), .io_axi_slave_write_addr_bits_prot(3'b0),
    .io_axi_slave_write_addr_bits_id(6'd3), .io_axi_slave_write_addr_bits_len(8'b0),
    .io_axi_slave_write_addr_bits_size(awsize), .io_axi_slave_write_addr_bits_burst(2'd1),
    .io_axi_slave_write_addr_bits_lock(1'b0), .io_axi_slave_write_addr_bits_cache(4'b0),
    .io_axi_slave_write_addr_bits_qos(4'b0), .io_axi_slave_write_addr_bits_region(4'b0),
    .io_axi_slave_write_data_valid(wvalid), .io_axi_slave_write_data_ready(wready),
    .io_axi_slave_write_data_bits_data(wdata), .io_axi_slave_write_data_bits_strb(wstrb),
    .io_axi_slave_write_data_bits_last(1'b1),
    .io_axi_slave_write_resp_ready(bready), .io_axi_slave_write_resp_valid(bvalid),
    .io_axi_slave_write_resp_bits_resp(bresp), .io_axi_slave_write_resp_bits_id(bid),
    .io_axi_slave_read_addr_valid(arvalid), .io_axi_slave_read_addr_ready(arready),
    .io_axi_slave_read_addr_bits_addr(araddr), .io_axi_slave_read_addr_bits_prot(3'b0),
    .io_axi_slave_read_addr_bits_id(6'd5), .io_axi_slave_read_addr_bits_len(8'b0),
    .io_axi_slave_read_addr_bits_size(arsize), .io_axi_slave_read_addr_bits_burst(2'd1),
    .io_axi_slave_read_addr_bits_lock(1'b0), .io_axi_slave_read_addr_bits_cache(4'b0),
    .io_axi_slave_read_addr_bits_qos(4'b0), .io_axi_slave_read_addr_bits_region(4'b0),
    .io_axi_slave_read_data_ready(rready), .io_axi_slave_read_data_valid(rvalid),
    .io_axi_slave_read_data_bits_data(rdata), .io_axi_slave_read_data_bits_resp(rresp),
    .io_axi_slave_read_data_bits_id(rid), .io_axi_slave_read_data_bits_last(rlast),
    .io_axi_master_write_addr_ready(bus.awready),
    .io_axi_master_write_addr_valid(bus.awvalid),
    .io_axi_master_write_addr_bits_addr(bus.awaddr),
    .io_axi_master_write_addr_bits_prot(awprot),
    .io_axi_master_write_addr_bits_id(bus.awid),
    .io_axi_master_write_addr_bits_len(bus.awlen),
    .io_axi_master_write_addr_bits_size(bus.awsize),
    .io_axi_master_write_addr_bits_burst(bus.awburst),
    .io_axi_master_write_addr_bits_lock(awlock),
    .io_axi_master_write_addr_bits_cache(awcache),
    .io_axi_master_write_addr_bits_qos(awqos),
    .io_axi_master_write_addr_bits_region(awregion),
    .io_axi_master_write_data_ready(bus.wready),
    .io_axi_master_write_data_valid(bus.wvalid),
    .io_axi_master_write_data_bits_data(bus.wdata),
    .io_axi_master_write_data_bits_strb(bus.wstrb),
    .io_axi_master_write_data_bits_last(bus.wlast),
    .io_axi_master_write_resp_ready(bus.bready),
    .io_axi_master_write_resp_valid(bus.bvalid),
    .io_axi_master_write_resp_bits_id(bus.bid),
    .io_axi_master_write_resp_bits_resp(bus.bresp),
    .io_axi_master_read_addr_ready(bus.arready),
    .io_axi_master_read_addr_valid(bus.arvalid),
    .io_axi_master_read_addr_bits_addr(bus.araddr),
    .io_axi_master_read_addr_bits_prot(arprot),
    .io_axi_master_read_addr_bits_id(bus.arid),
    .io_axi_master_read_addr_bits_len(bus.arlen),
    .io_axi_master_read_addr_bits_size(bus.arsize),
    .io_axi_master_read_addr_bits_burst(bus.arburst),
    .io_axi_master_read_addr_bits_lock(arlock),
    .io_axi_master_read_addr_bits_cache(arcache),
    .io_axi_master_read_addr_bits_qos(arqos),
    .io_axi_master_read_addr_bits_region(arregion),
    .io_axi_master_read_data_ready(bus.rready),
    .io_axi_master_read_data_valid(bus.rvalid),
    .io_axi_master_read_data_bits_id(bus.rid),
    .io_axi_master_read_data_bits_data(bus.rdata),
    .io_axi_master_read_data_bits_resp(bus.rresp),
    .io_axi_master_read_data_bits_last(bus.rlast)
  );
  function automatic integer delay_ticks();
    rng = rng ^ (rng << 13); rng = rng ^ (rng >> 17); rng = rng ^ (rng << 5);
    return rng % 4;
  endfunction

  // Drive on falling edges; observe every handshake on rising edges.
  task automatic write_bus(input [31:0] addr, input [127:0] data,
                           input [15:0] strb, input [2:0] size);
    @(negedge clk);
    if(addr=='h30000)core_running=data[31:0]==0;
    awaddr=addr; awsize=size; wdata=data; wstrb=strb;
    fork
      begin
        repeat(delay_ticks()) @(negedge clk);
        awvalid=1;
        do @(posedge clk); while (awready !== 1'b1);
        @(negedge clk); awvalid=0;
      end
      begin
        repeat(delay_ticks()) @(negedge clk);
        wvalid=1;
        do @(posedge clk); while (wready !== 1'b1);
        @(negedge clk); wvalid=0;
      end
    join
    repeat(delay_ticks()) @(negedge clk);
    bready=1;
    do @(posedge clk); while (bvalid !== 1'b1);
    if (bresp !== 0 || bid !== 3) $fatal(1,"BAD_WRITE_RESPONSE");
    @(negedge clk); bready=0;
  endtask

  task automatic read_bus(input [31:0] addr, input [2:0] size, output [127:0] data);
    @(negedge clk); araddr=addr; arsize=size;
    repeat(delay_ticks()) @(negedge clk);
    arvalid=1;
    do @(posedge clk); while (arready !== 1'b1);
    @(negedge clk); arvalid=0;
    repeat(delay_ticks()) @(negedge clk);
    rready=1;
    do @(posedge clk); while (rvalid !== 1'b1);
    if (rresp !== 0 || rid !== 5 || rlast !== 1) $fatal(1,"BAD_READ_RESPONSE");
    if ($isunknown(rdata)) $fatal(1,"UNKNOWN_READ_DATA");
    data=rdata;
    @(negedge clk); rready=0;
  endtask

 always @(posedge clk) begin
  cycle<=cycle+1;
  if(booted && cycle==boot_cycle+20000)$dumpoff;
  if(cycle>=max_cycles)timed_out<=1;
  if(resetn && !counter_clear) begin
   if(bus.arvalid&&bus.arready)$fdisplay(fd,"%0d,AR,%08x,%x,%x,%x,%x,0,0,0,0",cycle,bus.araddr,bus.arid,bus.arlen,bus.arsize,bus.arburst);
   if(bus.awvalid&&bus.awready)$fdisplay(fd,"%0d,AW,%08x,%x,%x,%x,%x,0,0,0,0",cycle,bus.awaddr,bus.awid,bus.awlen,bus.awsize,bus.awburst);
   if(bus.wvalid&&bus.wready)$fdisplay(fd,"%0d,W,0,0,0,0,0,%032x,%04x,%x,0",cycle,bus.wdata,bus.wstrb,bus.wlast);
   if(bus.rvalid&&bus.rready)$fdisplay(fd,"%0d,R,0,%x,0,0,0,%032x,0,%x,%x",cycle,bus.rid,bus.rdata,bus.rlast,bus.rresp);
   if(bus.bvalid&&bus.bready)$fdisplay(fd,"%0d,B,0,%x,0,0,0,0,0,0,%x",cycle,bus.bid,bus.bresp);
  end
 end
 // Detect every stalled-channel payload change independently of the scoreboard.
 reg [4:0] stalled=0;
 reg [52:0] saved_ar,saved_aw;
 reg [144:0] saved_w;
 reg [136:0] saved_r;
 reg [7:0] saved_b;
 integer protocol_checks=0,protocol_error=0;
 always @(posedge clk)if(resetn)begin
  protocol_checks+=1;
  if(core_running && stalled[0]&&(!bus.arvalid||{bus.araddr,bus.arid,bus.arlen,bus.arsize,bus.arburst}!==saved_ar))protocol_error=1;
  if(core_running && stalled[1]&&(!bus.awvalid||{bus.awaddr,bus.awid,bus.awlen,bus.awsize,bus.awburst}!==saved_aw))protocol_error=1;
  if(core_running && stalled[2]&&(!bus.wvalid||{bus.wdata,bus.wstrb,bus.wlast}!==saved_w))protocol_error=1;
  if(core_running && stalled[3]&&(!bus.rvalid||{bus.rid,bus.rresp,bus.rlast,bus.rdata}!==saved_r))protocol_error=1;
  if(core_running && stalled[4]&&(!bus.bvalid||{bus.bid,bus.bresp}!==saved_b))protocol_error=1;
  stalled<=core_running?{bus.bvalid&&!bus.bready,bus.rvalid&&!bus.rready,bus.wvalid&&!bus.wready,bus.awvalid&&!bus.awready,bus.arvalid&&!bus.arready}:0;
  saved_ar<={bus.araddr,bus.arid,bus.arlen,bus.arsize,bus.arburst};
  saved_aw<={bus.awaddr,bus.awid,bus.awlen,bus.awsize,bus.awburst};
  saved_w<={bus.wdata,bus.wstrb,bus.wlast};saved_r<={bus.rid,bus.rresp,bus.rlast,bus.rdata};saved_b<={bus.bid,bus.bresp};
 end
 initial begin
  if(!$value$plusargs("image=%s",image_path))$fatal(1,"MISSING_IMAGE");
  if($value$plusargs("seed=%d",seed))begin end
  if($value$plusargs("max_cycles=%d",max_cycles))begin end
  if($value$plusargs("max_delay=%d",max_delay))begin end
  rng=seed;
  fd=$fopen("transactions.csv","w");
  $fdisplay(fd,"cycle,ch,addr,id,len,size,burst,data,strb,last,resp");
  $dumpfile("cpu.vcd");$dumpvars(0,clk,resetn,counter_clear,booted,halted,fault,isolate,guard_idle,guard_error,cycle);$dumpvars(0,bus.awvalid,bus.awready,bus.awaddr,bus.awid,bus.awlen,bus.awsize,bus.awburst,bus.wvalid,bus.wready,bus.wdata,bus.wstrb,bus.wlast,bus.bvalid,bus.bready,bus.bid,bus.bresp,bus.arvalid,bus.arready,bus.araddr,bus.arid,bus.arlen,bus.arsize,bus.arburst,bus.rvalid,bus.rready,bus.rid,bus.rdata,bus.rlast,bus.rresp);
  $readmemh(image_path,image_words);
  repeat(10)@(negedge clk);resetn=1;
  repeat(10)@(negedge clk);
  for(integer i=0;i<2560;i++)begin
   write_bus(i<512?i*16:'h10000+(i-512)*16,image_words[i],16'hffff,4);
  end
  // Read back all ITCM, private ABI, and the entire DTCM allocation before use.
  for(integer i=0;i<2560;i++)begin
   read_bus(i<512?i*16:'h10000+(i-512)*16,4,value);
   if(value!==image_words[i])$fatal(1,"MICROPROGRAM_UPLOAD_MISMATCH");
  end
  boot_cycle=cycle;booted=1;
  forever begin
   wait(command!=0);
   if(command==1)write_bus(command_address,command_data,command_strobe,command_size);
   if(command==2)read_bus(command_address,command_size,reply_data);
   if(command==3)begin $fflush(fd);end
   command_done=1;wait(command==0);command_done=0;
  end
 end
endmodule
