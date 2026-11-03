`timescale 1ns/1ps
module tb_local #(parameter bit FAST=1);
  logic clk=0,reset_n=0;
  always #5 clk=~clk;
  axi4_if #(.DATA_W(32),.ID_W(1)) ib(clk),db(clk);
  axi4_if #(.DATA_W(128),.ID_W(6)) nb(clk);
  logic rom_enable=0;logic [31:0] rom_address=0;
  wire [31:0] rom_data;
  wire uart_tx,model_sealed,platform_reset_request,exited;
  wire [31:0] selected_profile,exit_code,report_tag;
  nx_ce64_local #(.ROM_FILE("rom.hex"),.UART_DIVISOR(4),.PRELOAD_MODE(1),.LOCAL_READ_PIPELINE(FAST)) dut(
    .clk,.reset_n,.ddr_init_done(1'b1),.uart_rx(1'b1),.platform_ready(1'b1),.platform_status(32'h12345678),
    .telemetry(4096'b0),.uart_tx,.rom_enable,.rom_address,.rom_data,.model_sealed,.selected_profile,
    .platform_reset_request,.exit_code,.report_tag,.exited,.local_i(ib),.local_d(db),.local_n(nb));
  logic [31:0] expected[0:16383];
  longint cycles=0;
  int transactions=0,read_beats=0,stall_checks=0,seed=32'h1a2b3c4d;
  longint d_single_latency,i_single_latency,d_burst_span,i_burst_span;
  logic dh=0,ih=0;logic [34:0] dprev,iprev;
  always @(posedge clk)begin
    cycles<=cycles+1;
    if(reset_n)begin
      if(dh)begin if(!db.rvalid||{db.rlast,db.rresp,db.rdata}!==dprev)$fatal(1,"D response changed under backpressure");stall_checks<=stall_checks+1;end
      if(ih)begin if(!ib.rvalid||{ib.rlast,ib.rresp,ib.rdata}!==iprev)$fatal(1,"I response changed under backpressure");end
      dh<=db.rvalid&&!db.rready;ih<=ib.rvalid&&!ib.rready;
      dprev<={db.rlast,db.rresp,db.rdata};iprev<={ib.rlast,ib.rresp,ib.rdata};
    end else begin dh<=0;ih<=0;end
  end
  function automatic [31:0] reference_word(input [31:0] address);
    if(address>=32'h20000&&address<32'h30000)return expected[address[15:2]];
    if(address>=32'h10000&&address<32'h20000)return 32'h76540000^{18'b0,address[15:2]};
    return 0;
  endfunction
  task automatic reset;
    @(negedge clk);reset_n=0;ib.arvalid=0;db.arvalid=0;db.awvalid=0;db.wvalid=0;
    ib.rready=0;db.rready=0;db.bready=0;
    repeat(3)@(negedge clk);
    if(ib.rvalid||db.rvalid||db.bvalid)$fatal(1,"reset failed to abort responses");
    reset_n=1;repeat(2)@(negedge clk);
  endtask
  task automatic write_d(input [31:0] address,input [31:0] data,input [3:0] strb,input int ordering=0);
    bit awdone,wdone;int age;logic [1:0] resp;
    awdone=0;wdone=0;age=0;
    @(negedge clk);db.awaddr=address;db.awsize=2;db.awlen=0;db.awvalid=ordering!=1;
    db.wdata=data;db.wstrb=strb;db.wlast=1;db.wvalid=ordering!=2;db.bready=0;
    while(!awdone||!wdone)begin
      @(posedge clk);
      if(db.awvalid&&db.awready)awdone=1;
      if(db.wvalid&&db.wready)wdone=1;
      @(negedge clk);age++;
      db.awvalid=!awdone&&(ordering!=1||age>=3);
      db.wvalid=!wdone&&(ordering!=2||age>=3);
      if(age>100)$fatal(1,"write address/data timeout");
    end
    while(!db.bvalid)begin @(negedge clk);age++;if(age>120)$fatal(1,"B timeout");end
    resp=db.bresp;
    repeat(3)begin @(negedge clk);if(!db.bvalid||db.bresp!=resp)$fatal(1,"B changed under backpressure");end
    if(resp!=0)$fatal(1,"write error %x",address);
    db.bready=1;@(posedge clk);@(negedge clk);db.bready=0;
    if(address>=32'h20000&&address<32'h30000)
      for(int b=0;b<4;b++)if(strb[b])expected[address[15:2]][b*8+:8]=data[b*8+:8];
    transactions++;
  endtask
  task automatic read_d(input [31:0] address,input int beats=1,input int size=2,input bit stalls=0,
                         input int special=-1,output longint first,output longint span);
    int got,age;longint begin_cycle,last_cycle;logic [31:0] a,want;
    @(negedge clk);db.araddr=address;db.arlen=8'(beats-1);db.arsize=3'(size);db.arvalid=1;db.rready=0;
    do @(posedge clk);while(!db.arready);
    begin_cycle=cycles;@(negedge clk);db.arvalid=0;got=0;age=0;a=address;first=0;last_cycle=0;
    while(got<beats)begin
      db.rready=!stalls||((age*17+5)%7>=2);
      @(posedge clk);
      if(db.rvalid&&db.rready)begin
        if(got==0)first=cycles-begin_cycle;
        want=special<0 ? reference_word(a) : 32'(special);
        if(db.rdata!==want)$fatal(1,"D data mismatch addr=%x beat=%d got=%x expected=%x",a,got,db.rdata,want);
        if(db.rresp!==(size<=2?2'd0:2'd3)||db.rlast!==(got==beats-1))$fatal(1,"D response framing");
        got++;read_beats++;last_cycle=cycles;a=a+(32'd1<<size);
      end
      @(negedge clk);age++;if(age>5000)$fatal(1,"D read timeout address=%x got=%d age=%d ar_have=%b rvalid=%b ready=%b ra=%x",address,got,age,dut.ar_have,db.rvalid,db.rready,dut.ra);
    end
    span=last_cycle-begin_cycle;db.rready=0;transactions++;
  endtask
  task automatic read_i(input [31:0] address,input int beats=1,input int size=2,input bit stalls=0,
                         output longint first,output longint span);
    int got,age;longint begin_cycle,last_cycle;logic [31:0] a;
    @(negedge clk);ib.araddr=address;ib.arlen=8'(beats-1);ib.arsize=3'(size);ib.arvalid=1;ib.rready=0;
    do @(posedge clk);while(!ib.arready);
    begin_cycle=cycles;@(negedge clk);ib.arvalid=0;got=0;age=0;a=address;first=0;last_cycle=0;
    while(got<beats)begin
      ib.rready=!stalls||((age*13+3)%11>=3);
      @(posedge clk);
      if(ib.rvalid&&ib.rready)begin
        if(got==0)first=cycles-begin_cycle;
        if(ib.rdata!==reference_word(a))$fatal(1,"I data mismatch addr=%x beat=%d got=%x",a,got,ib.rdata);
        if(ib.rresp!==((a>=32'h10000&&a<32'h30000&&size==2)?2'd0:2'd3)||ib.rlast!==(got==beats-1))$fatal(1,"I response framing");
        got++;read_beats++;last_cycle=cycles;a=a+4;
      end
      @(negedge clk);age++;if(age>5000)$fatal(1,"I read timeout");
    end
    span=last_cycle-begin_cycle;ib.rready=0;transactions++;
  endtask
  task automatic same_address_write_read;
    @(negedge clk);db.awaddr=32'h20200;db.awsize=2;db.awlen=0;db.awvalid=1;
    db.wdata=32'hfedcba98;db.wstrb=15;db.wlast=1;db.wvalid=1;db.bready=0;
    @(posedge clk);if(!db.awready||!db.wready)$fatal(1,"collision setup not accepted");
    @(negedge clk);db.awvalid=0;db.wvalid=0;db.araddr=32'h20200;db.arlen=0;db.arsize=2;db.arvalid=1;db.rready=0;
    @(posedge clk);if(!db.arready)$fatal(1,"collision read not accepted");
    @(negedge clk);db.arvalid=0;db.bready=1;expected[128]=32'hfedcba98;
    while(!db.rvalid)@(negedge clk);
    if(db.rdata!==32'hfedcba98)$fatal(1,"D write-priority read saw stale/partial word");
    db.rready=1;@(negedge clk);db.rready=0;db.bready=0;transactions+=2;read_beats++;
  endtask
  task automatic write_while_read_held;
    logic [31:0] old_value;
    old_value=expected[127];
    @(negedge clk);db.araddr=32'h201fc;db.arlen=0;db.arsize=2;db.arvalid=1;db.rready=0;
    do @(posedge clk);while(!db.arready);
    @(negedge clk);db.arvalid=0;while(!db.rvalid)@(negedge clk);
    write_d(32'h201fc,32'h01234567,15,0);
    if(db.rdata!==old_value||!db.rvalid)$fatal(1,"write corrupted already-held read response");
    db.rready=1;@(negedge clk);db.rready=0;transactions++;read_beats++;
  endtask
  longint first,span,fi,si,fd,sd;
  initial begin
    ib.awvalid=0;ib.wvalid=0;ib.bready=1;ib.awaddr=0;ib.awlen=0;ib.awsize=2;ib.awburst=1;ib.awid=0;ib.wdata=0;ib.wstrb=0;ib.wlast=1;
    ib.arid=0;ib.arburst=1;ib.araddr=0;ib.arlen=0;ib.arsize=2;ib.arvalid=0;ib.rready=0;
    db.awid=0;db.awburst=1;db.awaddr=0;db.awlen=0;db.awsize=2;db.awvalid=0;db.wdata=0;db.wstrb=0;db.wlast=1;db.wvalid=0;db.bready=0;
    db.arid=0;db.arburst=1;db.araddr=0;db.arlen=0;db.arsize=2;db.arvalid=0;db.rready=0;
    nb.awid=0;nb.awaddr=0;nb.awlen=0;nb.awsize=4;nb.awburst=1;nb.awvalid=0;nb.wdata=0;nb.wstrb=0;nb.wlast=1;nb.wvalid=0;nb.bready=1;
    nb.arid=0;nb.araddr=0;nb.arlen=0;nb.arsize=4;nb.arburst=1;nb.arvalid=0;nb.rready=1;
    reset();
    for(int j=0;j<256;j++)write_d(32'h20000+32'(j*4),32'habcd0000^32'(j*139),15,j%3);
    for(int j=0;j<16;j++)write_d(32'h20000+32'(j*4),32'hf1e2d3c4^32'(j),4'(j),j%3);
    read_d(32'h20000,1,2,0,-1,d_single_latency,span);
    read_i(32'h20000,1,2,0,i_single_latency,span);
    read_d(32'h20000,8,2,0,-1,first,d_burst_span);
    read_i(32'h20000,8,2,0,first,i_burst_span);
    read_d(32'h20000,256,2,1,-1,first,span);
    read_i(32'h20000,256,2,1,first,span);
    read_d(32'h10000,32,2,1,-1,first,span);
    read_i(32'h10000,32,2,1,first,span);
    read_d(32'h20001,20,0,1,-1,first,span);
    read_d(32'h20002,20,1,1,-1,first,span);
    fork
      begin read_d(32'h20000,64,2,1,-1,fd,sd); end
      begin read_i(32'h20000,64,2,1,fi,si); end
    join
    // Concurrent reads and a separate byte-write exercise the shared D port.
    fork
      begin read_d(32'h20000,64,2,1,-1,fd,sd); end
      begin write_d(32'h203fc,32'hdeadbeef,4'b0101,0); end
    join
    read_d(32'h203fc,1,2,0,-1,first,span);
    same_address_write_read();write_while_read_held();
    read_d(32'h201fc,1,2,0,-1,first,span);
    read_d(32'h1fffc,2,2,1,-1,first,span);
    read_i(32'h1fffc,2,2,1,first,span);
    write_d(32'h2fffc,32'h89abcdef,15,0);
    read_d(32'h2fffc,2,2,1,-1,first,span);
    read_i(32'h2fffc,2,2,1,first,span);
    read_i(32'h40000,8,2,1,first,span);
    read_i(32'h10000,4,1,1,first,span);
    read_d(32'h20000,2,3,1,-1,first,span);
    read_d(32'h100000d0,1,2,0,32'h12345678,first,span);
    read_d(32'h100000b8,1,2,0,32'h3152504e,first,span);
    // Reset while responses are held. Arrays retain actual written contents.
    @(negedge clk);db.araddr=32'h20000;db.arlen=7;db.arsize=2;db.arvalid=1;db.rready=0;
    do @(posedge clk);while(!db.arready);
    @(negedge clk);db.arvalid=0;repeat(5)@(negedge clk);if(!db.rvalid)$fatal(1,"no response before reset");
    reset();read_d(32'h20000,8,2,1,-1,first,span);
    // Dedicated ROM port remains synchronous and holds while disabled.
    @(negedge clk);rom_address=32'h10028;rom_enable=1;
    @(negedge clk);if(rom_data!==32'h7654000a)$fatal(1,"TCM read mismatch");rom_enable=0;rom_address=32'h10080;
    repeat(3)begin @(negedge clk);if(rom_data!==32'h7654000a)$fatal(1,"TCM hold mismatch");end
    $display("RESULT {\"fast\":%0d,\"transactions\":%0d,\"read_beats\":%0d,\"stall_checks\":%0d,\"d_single_cycles\":%0d,\"i_single_cycles\":%0d,\"d_8beat_cycles\":%0d,\"i_8beat_cycles\":%0d}",FAST,transactions,read_beats,stall_checks,d_single_latency,i_single_latency,d_burst_span,i_burst_span);
    $finish;
  end
  initial begin #10000000;$fatal(1,"global timeout");end
endmodule
