`timescale 1ns/1ps
module tb_coral;
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
  wire rlast,mawvalid,marvalid,mwvalid;
  integer cycle=0, phase=0, trace_fd, result_fd;
  integer seed=1;
  reg [31:0] rng=1;
  string image_path;
  reg [127:0] image_words[0:2559];
  reg [127:0] value;
  reg [31:0] entry=0;
  integer start_cycle, halt_cycle;
  integer hold_reset=0;

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
    // T06 programs reside entirely in TCM. Any external access is a test error.
    // This guard does not qualify an external memory path or model its timing.
    .io_axi_master_write_addr_ready(1'b0), .io_axi_master_write_addr_valid(mawvalid),
    .io_axi_master_write_data_ready(1'b0), .io_axi_master_write_data_valid(mwvalid),
    .io_axi_master_write_resp_valid(1'b0), .io_axi_master_write_resp_bits_id(6'b0),
    .io_axi_master_write_resp_bits_resp(2'b11),
    .io_axi_master_read_addr_ready(1'b0), .io_axi_master_read_addr_valid(marvalid),
    .io_axi_master_read_data_valid(1'b0), .io_axi_master_read_data_bits_id(6'b0),
    .io_axi_master_read_data_bits_data(128'b0), .io_axi_master_read_data_bits_resp(2'b11),
    .io_axi_master_read_data_bits_last(1'b1)
  );

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
    if(cycle>250000) $fatal(1,"T06_TIMEOUT");
    if(resetn) begin
      if(mawvalid || marvalid || mwvalid) $fatal(1,"UNEXPECTED_EXTERNAL_ACCESS");
      if(phase>=2 && fault !== 0) $fatal(1,"CORE_FAULT");
      if(b_stalled && {bvalid,bid,bresp} !== {1'b1,b_saved}) $fatal(1,"B_UNSTABLE");
      if(r_stalled && {rvalid,rid,rresp,rlast,rdata} !== {1'b1,r_saved}) $fatal(1,"R_UNSTABLE");
      b_stalled <= bvalid && !bready; b_saved <= {bid,bresp};
      r_stalled <= rvalid && !rready; r_saved <= {rid,rresp,rlast,rdata};
      $fdisplay(trace_fd,"%0d,%0d,%b,%b,%08x,%b,%b,%032x,%04x,%b,%b,%02x,%b,%b,%08x,%b,%b,%032x,%02x,%b,%b,%b",cycle,phase,
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
    trace_fd=$fopen("bus.csv","w");
    $fdisplay(trace_fd,"cycle,phase,awvalid,awready,awaddr,wvalid,wready,wdata,wstrb,bvalid,bready,bidresp,arvalid,arready,araddr,rvalid,rready,rdata,ridresp,rlast,halted,fault");
    result_fd=$fopen("dtcm.hex","w");
    $dumpfile("coral.vcd"); $dumpvars(1,tb_coral);
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
    $display("T06_EXECUTED seed=%0d entry=%08x cycles=%0d halted=1 fault=0",seed,entry,halt_cycle-start_cycle);
    $finish;
  end
endmodule
