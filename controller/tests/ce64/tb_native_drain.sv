`timescale 1ns/1ps
module tb_native_drain;
  logic clk=0,rst_n=0,ddr_init_done=0;
  always #4 clk=~clk;
  logic [31:0] s_awaddr=0,s_araddr=0;
  logic [5:0] s_awid=3,s_arid=3,s_bid,s_rid;
  logic [7:0] s_awlen=0,s_arlen=0;
  logic [2:0] s_awsize=4,s_arsize=4;
  logic [1:0] s_awburst=1,s_arburst=1,s_bresp,s_rresp;
  logic s_awvalid=0,s_arvalid=0,s_awready,s_arready;
  logic [127:0] s_wdata=128'hf012345678abcdef012345678abcdef0,s_rdata;
  logic [15:0] s_wstrb=16'hffff;
  logic s_wvalid=0,s_wlast=1,s_wready,s_bvalid,s_rvalid,s_rlast,s_bready=0,s_rready=0;
  wire [27:0] d_awaddr,d_araddr;
  wire [3:0] d_awid,d_arid,d_awlen,d_arlen;
  wire d_awvalid,d_arvalid,d_awready,d_arready,d_wready,d_wlast;
  wire [255:0] d_wdata;
  wire [31:0] d_wstrb;
  logic [255:0] d_rdata;
  logic [3:0] d_rid;
  logic d_rvalid=0,d_rlast=0;
  wire fault,quarantined,native_pending,upstream_pending,safely_drained;
  wire [3:0] fault_reason;
  wire [63:0] cycles,write_payload_bytes,read_payload_bytes,native_write_bytes,native_read_bytes;
  nx_ce64_ddr_adapter #(.STALL_LIMIT(8),.WRITE_DRAIN_CYCLES(1024)) dut(.*);
  logic block_aw=0,block_ar=0,bad_last=0,bad_id=0;
  logic bad_data=0,bad_unmasked_data=0;
  integer response_delay=1,rleft=0,rbase=0,rbeat=0,rlen=0,wbase=0,wbeat=0,wlen=0;
  logic reading=0,writing=0;
  logic [255:0] mem [0:31];
  integer checks=0,cases=0;
  assign d_awready=!block_aw&&!writing;
  assign d_arready=!block_ar&&!reading;
  assign d_wready=writing;
  assign d_wlast=writing&&wbeat==wlen;
  always @(posedge clk) begin
    if(!rst_n)begin reading<=0;writing<=0;d_rvalid<=0;d_rid<=0;d_rlast<=0;d_rdata<=0;end
    else begin
      d_rvalid<=0;
      if(d_awvalid&&d_awready)begin writing<=1;wbase<=(d_awaddr>>3)&31;wlen<=d_awlen;wbeat<=0;end
      if(writing)begin
        for(integer j=0;j<32;j=j+1)if(d_wstrb[j])mem[(wbase+wbeat)&31][j*8+:8]<=d_wdata[j*8+:8];
        if(wbeat==wlen)writing<=0;else wbeat<=wbeat+1;
      end
      if(d_arvalid&&d_arready)begin reading<=1;rbase<=(d_araddr>>3)&31;rlen<=d_arlen;rbeat<=0;rleft<=response_delay;end
      if(reading)begin
        if(rleft!=0)rleft<=rleft-1;
        else begin
          d_rvalid<=1;d_rid<=bad_id ? 1 : 0;d_rlast<=rbeat==rlen || (bad_last&&rbeat==0);
          d_rdata<=mem[(rbase+rbeat)&31] ^
            ((bad_data&&rbeat==rlen) ? 256'd1 : 256'd0) ^
            (bad_unmasked_data ? (256'd1<<200) : 256'd0);
          if(rbeat==rlen)reading<=0;else begin rbeat<=rbeat+1;rleft<=0;end
        end
      end
    end
  end
  task automatic check(input bit condition,input string description);
    checks=checks+1;if(!condition)$fatal(1,"%s",description);
  endtask
  task automatic tick;
    @(posedge clk);#1;
  endtask
  task automatic platform_reset;
    @(negedge clk);rst_n=0;ddr_init_done=0;
    s_awvalid=0;s_arvalid=0;s_wvalid=0;s_bready=0;s_rready=0;
    block_aw=0;block_ar=0;bad_last=0;bad_id=0;response_delay=1;
    bad_data=0;bad_unmasked_data=0;s_wstrb=16'hffff;s_wlast=1;
    repeat(4)tick();@(negedge clk);rst_n=1;ddr_init_done=1;
    repeat(4)tick();check(!quarantined&&safely_drained,"platform reset establishes fresh calibration epoch");cases=cases+1;
  endtask
  task automatic write_offer;
    @(negedge clk);s_awaddr=32'h80000000;s_awlen=0;s_awsize=4;s_awvalid=1;
    while(!s_awready)@(negedge clk);tick();
    @(negedge clk);s_awvalid=0;s_wvalid=1;
    while(!s_wready)@(negedge clk);tick();
    @(negedge clk);s_wvalid=0;
  endtask
  task automatic read_offer(input logic [7:0] len);
    @(negedge clk);s_araddr=32'h80000000;s_arlen=len;s_arsize=4;s_arvalid=1;
    while(!s_arready)@(negedge clk);tick();
    @(negedge clk);s_arvalid=0;
  endtask
  task automatic write_burst;
    @(negedge clk);s_awaddr=32'h80000000;s_awlen=31;s_awsize=4;s_awvalid=1;
    while(!s_awready)@(negedge clk);tick();
    @(negedge clk);s_awvalid=0;s_wvalid=1;
    for(integer i=0;i<32;i=i+1)begin
      s_wlast=i==31;
      while(!s_wready)@(negedge clk);tick();@(negedge clk);
    end
    s_wvalid=0;s_wlast=1;
  endtask
  task automatic consume_b(input logic [1:0] expected);
    while(!s_bvalid)tick();check(s_bresp==expected&&s_bid==3,"complete write response identity");
    @(negedge clk);s_bready=1;tick();@(negedge clk);s_bready=0;
  endtask
  task automatic consume_r(input integer count,input logic [1:0] expected);
    for(integer i=0;i<count;i=i+1)begin
      while(!s_rvalid)tick();check(s_rresp==expected&&s_rid==3&&s_rlast==(i==count-1),"LEN-complete AXI R drain");
      @(negedge clk);s_rready=1;tick();@(negedge clk);s_rready=0;
    end
  endtask
  logic reset_request=0,reset_grant,coordinator_stop,coordinator_drained,coordinator_quarantine,coordinator_fault;
  logic [31:0] first_fault;
  nx_ce64_fault coordinator(.clk,.platform_reset_n(rst_n),.isolate_request(1'b0),.reset_request,
    .run_timeout(1'b0),.guard_fault(1'b0),.dma_fault(1'b0),.native_quarantined(quarantined),
    .visible_fault_address(32'h80000000),.dma_idle(!upstream_pending),.guard_idle(!upstream_pending),
    .native_safely_drained(safely_drained),.arithmetic_idle(1'b1),.scratch_idle(1'b1),.commit_idle(1'b1),
    .stop_new(coordinator_stop),.drained(coordinator_drained),.reset_grant,
    .quarantined(coordinator_quarantine),.faulted(coordinator_fault),.first_fault_address(first_fault));
  logic [127:0] held_r;
  logic [1:0] held_resp;
  logic held_last;
  initial begin
    for(integer i=0;i<32;i=i+1)mem[i]=256'(i);
    platform_reset();write_offer();consume_b(0);tick();
    check(native_write_bytes==32&&native_read_bytes==32,"write drain and masked native readback at 1024 cycles");
    check(safely_drained&&!fault,"normal transaction fully drains");
    platform_reset();block_aw=1;write_offer();while(!d_awvalid)tick();
    repeat(14)begin check(d_awvalid&&d_awaddr==0&&d_awlen==0,"native offered AW survives timeout");tick();end
    check(quarantined&&native_pending&&!s_bvalid,"timeout cannot synthesize a false native drain");
    block_aw=0;consume_b(2);tick();check(!safely_drained&&quarantined,"consumed B does not release quarantine");
    reset_request=1;repeat(6)begin tick();check(!reset_grant,"soft reset denied after uncertain native timeout");end reset_request=0;
    platform_reset();block_ar=1;read_offer(0);while(!d_arvalid)tick();
    repeat(14)begin check(d_arvalid&&d_araddr==0&&d_arlen==0,"offered AR survives timeout");tick();end
    block_ar=0;consume_r(1,2);check(quarantined&&!safely_drained,"late AR/R stays quarantined");
    platform_reset();response_delay=30;read_offer(3);
    repeat(15)begin tick();check(!s_rvalid,"native late response cannot be discarded behind an early AXI error");end
    check(quarantined&&native_pending,"late native read recorded as pending");consume_r(4,2);
    check(native_read_bytes==64&&!safely_drained,"all native LEN beats consumed before error response");
    platform_reset();bad_last=1;read_offer(3);consume_r(4,2);
    check(native_read_bytes==64&&quarantined,"early RLAST never cancels remaining native beats");
    platform_reset();bad_id=1;read_offer(3);consume_r(4,2);
    check(native_read_bytes==64&&fault_reason==4&&quarantined,"wrong RID drains but retains platform quarantine");
    platform_reset();ddr_init_done=0;repeat(4)tick();ddr_init_done=1;repeat(4)tick();
    check(quarantined&&!s_awready&&!s_arready&&!safely_drained,"idle calibration loss cannot resume on level reassertion");
    platform_reset();force d_rvalid=1;tick();release d_rvalid;tick();
    check(quarantined&&!safely_drained,"unowned late response after epoch is quarantined");
    platform_reset();write_offer();while(!s_bvalid)tick();held_resp=s_bresp;
    ddr_init_done=0;repeat(5)begin tick();check(s_bvalid&&s_bresp==held_resp&&s_bid==3,"held B is immutable on calibration loss");end
    consume_b(0);check(quarantined&&!safely_drained,"held B consumption never authorizes reset after calibration loss");
    platform_reset();read_offer(0);while(!s_rvalid)tick();held_r=s_rdata;held_resp=s_rresp;held_last=s_rlast;
    ddr_init_done=0;repeat(5)begin tick();check(s_rvalid&&s_rdata==held_r&&s_rresp==held_resp&&s_rlast==held_last,"held R is immutable on calibration loss");end
    consume_r(1,0);check(quarantined&&!safely_drained,"held R ownership retained");
    platform_reset();bad_unmasked_data=1;write_offer();consume_b(0);tick();
    check(!fault&&safely_drained,"registered readback ignores unmasked bytes");
    platform_reset();bad_data=1;write_burst();consume_b(2);tick();
    check(native_write_bytes==512&&native_read_bytes==512,"last-beat mismatch drains full 512-byte LEN");
    check(fault_reason==6&&quarantined&&!safely_drained,"final comparison retires before B and preserves quarantine");
    $display("CE64_NATIVE_DRAIN_PASS cases=%0d checks=%0d",cases,checks);$finish;
  end
  initial begin #400000;$fatal(1,"native safety test watchdog");end
endmodule
