`timescale 1ns/1ps
module tb_external;
  reg clk=0; always #5 clk=~clk;
  reg resetn=0;
  wire halted, fault, wfi;
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
  integer cycle=0, phase=0, trace_fd, result_fd;
  integer seed=1;
  reg [31:0] rng=1;
  string image_path;
  reg [127:0] image_words[0:2559];
  reg [127:0] value;
  reg [31:0] entry=0;
  integer start_cycle, halt_cycle;
  integer hold_reset=0;

  axi4_if #(.DATA_W(128),.ID_W(6)) bus(clk);
  wire [2:0] awprot,arprot;
  wire awlock,arlock;
  wire [3:0] awcache,arcache,awqos,arqos,awregion,arregion;
  bit random_delays=0;
  int unsigned max_delay=3;
  integer max_cycles=100000000,ext_fd;
  axi_sparse_mem #(.DATA_W(128),.ID_W(6),.TIMING_CONTROL(1)) memory
    (.clk,.reset_n(resetn),.random_delays,.seed,.max_delay,
     .inject_enable(1'b0),.inject_start(32'b0),.inject_end(32'b0),.inject_resp(2'b0),.bus);

  wire [31:0] ext_araddr=bus.araddr;
  wire [31:0] ext_awaddr=bus.awaddr;
  wire [127:0] ext_wdata=bus.wdata;
  wire [127:0] ext_rdata=bus.rdata;
  wire [15:0] ext_wstrb=bus.wstrb;
  wire [0:0] ext_arvalid=bus.arvalid;
  wire [0:0] ext_arready=bus.arready;
  wire [0:0] ext_awvalid=bus.awvalid;
  wire [0:0] ext_awready=bus.awready;
  wire [0:0] ext_wvalid=bus.wvalid;
  wire [0:0] ext_wready=bus.wready;
  wire [0:0] ext_bvalid=bus.bvalid;
  wire [0:0] ext_bready=bus.bready;
  wire [0:0] ext_rvalid=bus.rvalid;
  wire [0:0] ext_rready=bus.rready;

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


  longint ar_count=0,r_count=0,aw_count=0,w_count=0,b_count=0;
  longint read_bytes=0,write_bytes=0,ar_stall=0,r_stall=0,aw_stall=0,w_stall=0,b_stall=0;
  longint pending_read_cycles=0,pending_write_cycles=0;
  integer first_request=-1,last_response=-1;
  reg [4:0] stalled=0;
  reg [66:0] ar_saved,aw_saved;
  reg [144:0] w_saved;
  reg [136:0] mr_saved;
  reg [7:0] mb_saved;
  wire [66:0] ar_payload={bus.araddr,bus.arid,bus.arlen,bus.arsize,bus.arburst,arprot,arlock,arcache,arqos,arregion};
  wire [66:0] aw_payload={bus.awaddr,bus.awid,bus.awlen,bus.awsize,bus.awburst,awprot,awlock,awcache,awqos,awregion};
  always @(posedge clk) if(resetn) begin
    if(phase==2 && cycle==start_cycle+3000) $dumpoff;
    if (stalled[0] && (!bus.arvalid || ar_payload!==ar_saved)) $fatal(1,"EXT_AR_UNSTABLE");
    if (stalled[1] && (!bus.awvalid || aw_payload!==aw_saved)) $fatal(1,"EXT_AW_UNSTABLE");
    if (stalled[2] && (!bus.wvalid || {bus.wdata,bus.wstrb,bus.wlast}!==w_saved)) $fatal(1,"EXT_W_UNSTABLE");
    if (stalled[3] && (!bus.rvalid || {bus.rid,bus.rresp,bus.rlast,bus.rdata}!==mr_saved)) $fatal(1,"EXT_R_UNSTABLE");
    if (stalled[4] && (!bus.bvalid || {bus.bid,bus.bresp}!==mb_saved)) $fatal(1,"EXT_B_UNSTABLE");
    stalled<={bus.bvalid&&!bus.bready,bus.rvalid&&!bus.rready,bus.wvalid&&!bus.wready,bus.awvalid&&!bus.awready,bus.arvalid&&!bus.arready};
    ar_saved<=ar_payload; aw_saved<=aw_payload; w_saved<={bus.wdata,bus.wstrb,bus.wlast};
    mr_saved<={bus.rid,bus.rresp,bus.rlast,bus.rdata}; mb_saved<={bus.bid,bus.bresp};
    if (bus.arvalid && {arprot,arlock,arcache,arqos,arregion}!==16'h4000) $fatal(1,"EXT_AR_ATTRIBUTES");
    if (bus.awvalid && {awprot,awlock,awcache,awqos,awregion}!==16'h4000) $fatal(1,"EXT_AW_ATTRIBUTES");
    ar_stall+=bus.arvalid&&!bus.arready; r_stall+=bus.rvalid&&!bus.rready;
    aw_stall+=bus.awvalid&&!bus.awready; w_stall+=bus.wvalid&&!bus.wready; b_stall+=bus.bvalid&&!bus.bready;
    pending_read_cycles+=(ar_count>r_count); pending_write_cycles+=(aw_count>b_count);
    if ((bus.arvalid||bus.awvalid) && first_request<0) first_request=cycle;
    if (bus.arvalid && bus.arready) begin
      ar_count++; read_bytes+=(1<<bus.arsize)*(bus.arlen+1);
      $fdisplay(ext_fd,"%0d,AR,%08x,%02x,%02x,%x,%x,0,0,0,0",cycle,bus.araddr,bus.arid,bus.arlen,bus.arsize,bus.arburst);
    end
    if (bus.awvalid && bus.awready) begin
      aw_count++;
      $fdisplay(ext_fd,"%0d,AW,%08x,%02x,%02x,%x,%x,0,0,0,0",cycle,bus.awaddr,bus.awid,bus.awlen,bus.awsize,bus.awburst);
    end
    if (bus.wvalid && bus.wready) begin
      w_count++; write_bytes+=$countones(bus.wstrb);
      $fdisplay(ext_fd,"%0d,W,0,0,0,0,0,%032x,%04x,%x,0",cycle,bus.wdata,bus.wstrb,bus.wlast);
    end
    if (bus.rvalid && bus.rready) begin
      r_count++; last_response=cycle;
      $fdisplay(ext_fd,"%0d,R,0,%02x,0,0,0,%032x,0,%x,%x",cycle,bus.rid,bus.rdata,bus.rlast,bus.rresp);
    end
    if (bus.bvalid && bus.bready) begin
      b_count++; last_response=cycle;
      $fdisplay(ext_fd,"%0d,B,0,%02x,0,0,0,0,0,0,%x",cycle,bus.bid,bus.bresp);
    end
  end
  task write_metrics();
    integer fd;
    fd=$fopen("metrics.json","w");
    $fdisplay(fd,"{\"start_cycle\":%0d,\"halt_cycle\":%0d,\"cycles\":%0d,\"first_request\":%0d,\"last_response\":%0d,",start_cycle,halt_cycle,halt_cycle-start_cycle,first_request,last_response);
    $fdisplay(fd,"\"ar\":%0d,\"r\":%0d,\"aw\":%0d,\"w\":%0d,\"b\":%0d,\"read_bytes\":%0d,\"write_bytes\":%0d,",ar_count,r_count,aw_count,w_count,b_count,read_bytes,write_bytes);
    $fdisplay(fd,"\"ar_stall\":%0d,\"r_stall\":%0d,\"aw_stall\":%0d,\"w_stall\":%0d,\"b_stall\":%0d,\"pending_read_cycles\":%0d,\"pending_write_cycles\":%0d}",ar_stall,r_stall,aw_stall,w_stall,b_stall,pending_read_cycles,pending_write_cycles);
    $fclose(fd);
  endtask

  function automatic integer delay_ticks();
    rng = rng ^ (rng << 13); rng = rng ^ (rng >> 17); rng = rng ^ (rng << 5);
    return rng % 4;
  endfunction

  // Drive on falling edges; observe every handshake on rising edges.
  task automatic write_bus(input [31:0] addr, input [127:0] data,
                           input [15:0] strb, input [2:0] size);
    @(negedge clk);
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

  reg b_stalled=0,r_stalled=0;
  reg [7:0] b_saved;
  reg [136:0] r_saved;
  always @(posedge clk) begin
    cycle <= cycle+1;
    if(cycle>max_cycles) $fatal(1,"T07_TIMEOUT");
    if(resetn) begin
      if(phase>=2 && fault !== 0) $fatal(1,"CORE_FAULT");
      if(b_stalled && {bvalid,bid,bresp} !== {1'b1,b_saved}) $fatal(1,"B_UNSTABLE");
      if(r_stalled && {rvalid,rid,rresp,rlast,rdata} !== {1'b1,r_saved}) $fatal(1,"R_UNSTABLE");
      b_stalled <= bvalid && !bready; b_saved <= {bid,bresp};
      r_stalled <= rvalid && !rready; r_saved <= {rid,rresp,rlast,rdata};
      if (phase != 2) $fdisplay(trace_fd,"%0d,%0d,%b,%b,%08x,%b,%b,%032x,%04x,%b,%b,%02x,%b,%b,%08x,%b,%b,%032x,%02x,%b,%b,%b",cycle,phase,
        awvalid,awready,awaddr,wvalid,wready,wdata,wstrb,bvalid,bready,{bid,bresp},
        arvalid,arready,araddr,rvalid,rready,rdata,{rid,rresp},rlast,halted,fault);
    end
  end

  initial begin
    if(!$value$plusargs("image=%s",image_path)) $fatal(1,"MISSING_IMAGE");
    if(!$value$plusargs("entry=%h",entry)) $fatal(1,"MISSING_ENTRY");
    if($value$plusargs("seed=%d",seed)) begin end
    if($value$plusargs("hold_reset=%d",hold_reset)) begin end
    rng=seed;
    if($value$plusargs("max_cycles=%d",max_cycles)) begin end
    if($value$plusargs("random_delays=%d",random_delays)) begin end
    if($value$plusargs("max_delay=%d",max_delay)) begin end
    ext_fd=$fopen("external.csv","w");
    $fdisplay(ext_fd,"cycle,ch,addr,id,len,size,burst,data,strb,last,resp");
    trace_fd=$fopen("bus.csv","w");
    $fdisplay(trace_fd,"cycle,phase,awvalid,awready,awaddr,wvalid,wready,wdata,wstrb,bvalid,bready,bidresp,arvalid,arready,araddr,rvalid,rready,rdata,ridresp,rlast,halted,fault");
    result_fd=$fopen("dtcm.hex","w");
    $dumpfile("coral.vcd");
    $readmemh(image_path,image_words);
    repeat(10) @(negedge clk);
    resetn=1;
    repeat(10) @(negedge clk);
    phase=1;
    for(integer i=0;i<2560;i=i+1) begin
      write_bus(i<512 ? i*16 : 'h10000+(i-512)*16,image_words[i],16'hffff,4);
    end
    // Verify the entire uploaded program/data through the same subordinate port.
    for(integer i=0;i<2560;i=i+1) begin
      read_bus(i<512 ? i*16 : 'h10000+(i-512)*16,4,value);
      if(value !== image_words[i]) $fatal(1,"LOAD_READBACK_MISMATCH index=%0d",i);
    end
    write_bus('h30004,{64'b0,entry,32'b0},16'h00f0,2);
    read_bus('h30004,2,value);
    if(value[63:32] !== entry) $fatal(1,"ENTRY_READBACK_MISMATCH");
    $dumpvars(1,tb_external);
    phase=2;
    start_cycle=cycle;
    if(!hold_reset) write_bus('h30000,0,16'h000f,2);
    wait(halted === 1'b1);
    @(negedge clk); halt_cycle=cycle;
    if(fault !== 0) $fatal(1,"HALTED_WITH_FAULT");
    phase=3;
    read_bus('h30008,2,value);
    if(value[95:64] !== 1) $fatal(1,"STATUS_MISMATCH");
    for(integer i=0;i<2048;i=i+1) begin
      read_bus('h10000+i*16,4,value);
      $fdisplay(result_fd,"%032x",value);
    end
    $fclose(result_fd); $fclose(trace_fd);
    if(memory.w_out || memory.r_out || bus.bvalid || bus.rvalid) $fatal(1,"EXTERNAL_NOT_DRAINED");
    write_metrics();
    $fclose(ext_fd);
    $display("T07_EXECUTED seed=%0d entry=%08x cycles=%0d halted=1 fault=0",seed,entry,halt_cycle-start_cycle);
    $finish;
  end
endmodule
