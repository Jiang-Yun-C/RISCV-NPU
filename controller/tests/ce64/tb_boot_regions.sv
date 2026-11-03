`timescale 1ns/1ps
module tb_boot_regions;
  logic clk=0,reset_n=0,model_sealed=0;
  always #4 clk=~clk;
  axi4_if #(.DATA_W(32),.ID_W(1)) cpu(clk),memory(clk);
  axi4_if #(.DATA_W(128),.ID_W(6)) coral(clk);
  wire owner,isolate,clear_backend_error,irq;
  nx_ce64_bridge dut(.clk,.reset_n,.model_sealed,.backend_idle(1'b1),.backend_error(1'b0),
    .backend_irq(1'b0),.backend_fault_address(32'b0),.owner,.isolate,.clear_backend_error,.irq,.cpu,.memory,.coral);
  int writes=0,reads=0,checks=0;
  assign memory.awready=!memory.bvalid;
  assign memory.wready=!memory.bvalid;
  assign memory.bid=0;assign memory.bresp=0;
  assign memory.arready=!memory.rvalid;
  assign memory.rid=0;assign memory.rdata=32'h12345678;assign memory.rlast=1;assign memory.rresp=0;
  assign coral.awready=1;assign coral.wready=1;assign coral.bid=0;assign coral.bresp=0;assign coral.bvalid=0;
  assign coral.arready=1;assign coral.rid=0;assign coral.rdata=0;assign coral.rlast=1;assign coral.rresp=0;assign coral.rvalid=0;
  always @(posedge clk)begin
    if(!reset_n)begin memory.bvalid<=0;memory.rvalid<=0;end
    else begin
      if(memory.wvalid&&memory.wready)begin writes<=writes+1;memory.bvalid<=1;end
      else if(memory.bvalid&&memory.bready)memory.bvalid<=0;
      if(memory.arvalid&&memory.arready)begin reads<=reads+1;memory.rvalid<=1;end
      else if(memory.rvalid&&memory.rready)memory.rvalid<=0;
    end
  end
  task automatic write(input logic[31:0] address,value,input bit reject,input int forwarded);
    bit aw,w;int before_count;logic[1:0] response;
    aw=0;w=0;before_count=writes;
    @(negedge clk);cpu.awaddr=address;cpu.wdata=value;cpu.awvalid=1;cpu.wvalid=1;
    while(!aw||!w)begin
      @(posedge clk);if(cpu.awvalid&&cpu.awready)aw=1;if(cpu.wvalid&&cpu.wready)w=1;
      @(negedge clk);if(aw)cpu.awvalid=0;if(w)cpu.wvalid=0;
    end
    while(!cpu.bvalid)@(negedge clk);
    response=cpu.bresp;
    repeat(3)begin @(negedge clk);assert(cpu.bvalid&&cpu.bresp==response)else $fatal(1,"held B changed");checks++;end
    assert((response!=0)==reject)else $fatal(1,"wrong write policy addr=%h resp=%h",address,response);checks++;
    assert(writes==before_count+forwarded)else $fatal(1,"rejected write reached memory addr=%h",address);checks++;
    cpu.bready=1;@(negedge clk);cpu.bready=0;
  endtask
  task automatic read_tokenizer;
    int before_count;before_count=reads;
    @(negedge clk);cpu.araddr=32'hb8000000;cpu.arvalid=1;
    do @(posedge clk);while(!cpu.arready);
    @(negedge clk);cpu.arvalid=0;
    while(!cpu.rvalid)@(negedge clk);
    assert(cpu.rresp==0&&cpu.rdata==32'h12345678&&reads==before_count+1)else $fatal(1,"tokenizer read rejected");checks++;
    cpu.rready=1;@(negedge clk);cpu.rready=0;
  endtask
  initial begin
    cpu.awaddr=0;cpu.awid=0;cpu.awlen=0;cpu.awsize=2;cpu.awburst=1;cpu.awvalid=0;
    cpu.wdata=0;cpu.wstrb=15;cpu.wlast=1;cpu.wvalid=0;cpu.bready=0;
    cpu.araddr=0;cpu.arid=0;cpu.arlen=0;cpu.arsize=2;cpu.arburst=1;cpu.arvalid=0;cpu.rready=0;
    repeat(4)@(negedge clk);reset_n=1;
    write(32'h80000000,1,0,1);
    write(32'hb8000000,2,0,1);write(32'hb9fffffc,3,0,1);read_tokenizer();
    write(32'h10000100,1,0,0);assert(owner)else $fatal(1,"owner not acquired");checks++;
    write(32'hb8000000,4,1,0);write(32'h80000000,5,1,0);
    write(32'h10000100,0,0,0);assert(!owner)else $fatal(1,"owner not released");checks++;
    @(negedge clk);model_sealed=1;
    write(32'hb8000000,6,1,0);write(32'hb9fffffc,7,1,0);write(32'h80000000,8,1,0);read_tokenizer();
    @(negedge clk);reset_n=0;model_sealed=0;repeat(4)@(negedge clk);reset_n=1;
    write(32'hb8000000,9,0,1);
    $display("T25_BOOT_REGIONS_PASS checks=%0d writes=%0d reads=%0d",checks,writes,reads);$finish;
  end
  initial begin #100000;$fatal(1,"test timeout");end
endmodule
