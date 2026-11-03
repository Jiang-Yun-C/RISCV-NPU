`timescale 1ns/1ps
module tb_pmu #(parameter integer WIDTH=64);
  logic clk=0,reset_n=0;
  always #5 clk=~clk;
  axi4_if #(.DATA_W(32),.ID_W(1)) control(clk),ib(clk),db(clk);
  axi4_if #(.DATA_W(128),.ID_W(6)) cb(clk);
  logic retire=0,execute_stall=0,branch=0,mispredict=0;
  wire [2047:0] snap;
  nx_ce64_request_pmu #(.COUNTER_WIDTH(WIDTH)) dut(.clk,.reset_n,.retire,.execute_stall,.branch,.mispredict,.control,.cpu_i(ib),.cpu_d(db),.ce(cb),.snapshot(snap));
  longint unsigned reference[0:23];
  bit ref_active=0,events=0;
  int phase=0,tick=0,read_size=2,ce_size=4,checks=0;
  longint unsigned maximum;
  always @(negedge clk)begin
    if(!reset_n)begin phase=0;tick=0;end else begin phase=(phase+1)%6;tick++;end
    retire=events&&(tick%3!=0);execute_stall=events&&(tick%5<2);
    branch=events&&(tick%7==0);mispredict=events&&(tick%14==0);
    ib.arvalid=events&&(phase==0||phase==1);ib.arready=phase==1;
    ib.rvalid=events&&(phase==2||phase==3);ib.rready=phase==3;ib.rresp=(tick%30==3)?2:0;ib.rlast=1;ib.arsize=2;
    db.arvalid=events&&(phase==0||phase==1);db.arready=phase==1;
    db.arsize=3'((tick/6)%3);db.rvalid=events&&(phase==2||phase==3);db.rready=phase==3;db.rresp=0;db.rlast=1;
    db.awvalid=events&&(phase==3||phase==4);db.awready=phase==4;
    db.wvalid=events&&phase==5;db.wready=1;db.wstrb=4'(tick);db.wlast=1;
    db.bvalid=events&&phase==0;db.bready=1;db.bresp=(tick%24==0)?2:0;
    cb.arvalid=events&&(phase==0||phase==1);cb.arready=phase==1;cb.arsize=4;
    cb.rvalid=events&&(phase==2||phase==3);cb.rready=phase==3;cb.rresp=0;cb.rlast=1;
    cb.awvalid=events&&(phase==3||phase==4);cb.awready=phase==4;
    cb.wvalid=events&&phase==5;cb.wready=1;cb.wstrb=16'(tick*931);cb.wlast=1;
    cb.bvalid=events&&phase==0;cb.bready=1;cb.bresp=0;
  end
  // Independent handshake/accounting oracle, with unbounded 64-bit totals in
  // the reduced-width overflow test. Only the DUT saturates before capture.
  always @(posedge clk)begin
    if(!reset_n)begin for(int j=0;j<24;j++)reference[j]=0;read_size=2;ce_size=4;end
    else begin
      if(ref_active)begin
        reference[0]++;
        if(retire)reference[1]++;
        if(execute_stall)reference[2]++;
        if(branch)reference[3]++;
        if(branch&&mispredict)reference[4]++;
        if(ib.arvalid&&ib.arready)reference[5]++;
        if(ib.rvalid&&ib.rready)begin reference[6]++;reference[7]+=4;if(ib.rresp!=0)reference[23]++;end
        if(ib.arvalid&&!ib.arready)reference[8]++;
        if(db.arvalid&&db.arready)reference[9]++;
        if(db.rvalid&&db.rready)begin reference[10]++;reference[11]+=64'(1)<<read_size;if(db.rresp!=0)reference[23]++;end
        if(db.awvalid&&db.awready)reference[12]++;
        if(db.wvalid&&db.wready)begin reference[13]++;for(int j=0;j<4;j++)if(db.wstrb[j])reference[14]++;end
        if((db.arvalid&&!db.arready)||(db.awvalid&&!db.awready))reference[15]++;
        if(cb.arvalid&&cb.arready)reference[16]++;
        if(cb.rvalid&&cb.rready)begin reference[17]++;reference[18]+=64'(1)<<ce_size;if(cb.rresp!=0)reference[23]++;end
        if(cb.awvalid&&cb.awready)reference[19]++;
        if(cb.wvalid&&cb.wready)begin reference[20]++;for(int j=0;j<16;j++)if(cb.wstrb[j])reference[21]++;end
        if((cb.arvalid&&!cb.arready)||(cb.awvalid&&!cb.awready))reference[22]++;
        if(db.bvalid&&db.bready&&db.bresp!=0)reference[23]++;
        if(cb.bvalid&&cb.bready&&cb.bresp!=0)reference[23]++;
      end
      if(db.arvalid&&db.arready)read_size=int'(db.arsize);
      if(cb.arvalid&&cb.arready)ce_size=int'(cb.arsize);
    end
  end
  task automatic control_write(input [31:0] address,input [31:0] value,input [3:0] strobes=15,input [1:0] response=0,input int skew=0);
    @(negedge clk);control.awaddr=address;control.awsize=2;control.awlen=0;control.awvalid=0;control.awready=1;
    control.wdata=value;control.wstrb=strobes;control.wlast=1;control.wvalid=0;control.wready=1;
    if(skew==1)begin control.wvalid=1;@(negedge clk);control.wvalid=0;control.awvalid=1;@(negedge clk);control.awvalid=0;end
    else begin control.awvalid=1;@(negedge clk);control.awvalid=0;control.wvalid=1;@(negedge clk);control.wvalid=0;end
    control.bvalid=1;control.bresp=response;control.bready=0;
    repeat(3)@(negedge clk);control.bready=1;
    @(posedge clk);#1;
    if(response==0&&strobes==15&&address==32'h100000b4)begin
      if(value==1&&!ref_active)begin ref_active=1;for(int j=0;j<24;j++)reference[j]=0;end
      if(value==3&&ref_active)ref_active=0;
      if(value==4&&!ref_active)for(int j=0;j<24;j++)reference[j]=0;
    end
    @(negedge clk);control.bvalid=0;control.bready=0;
  endtask
  task automatic verify(input [31:0] tag,input bit running);
    bit ov;longint unsigned want;
    #1;ov=0;
    if(snap[31:0]!=32'h3152504e||(snap[47:32]&16'h2)!=2||snap[32]!=running||snap[95:64]!=tag)$fatal(1,"snapshot metadata mismatch");
    for(int j=0;j<24;j++)begin
      want=reference[j]>maximum?maximum:reference[j];
      if(reference[j]>maximum)ov=1;
      if(snap[128+j*64+:64]!==want)$fatal(1,"counter %0d got=%0d expected=%0d",j,snap[128+j*64+:64],want);
    end
    if(snap[36]!==ov)$fatal(1,"overflow flag mismatch");checks++;
  endtask
  logic [2047:0] held;
  longint unsigned expected_saved[0:23];
  initial begin
    maximum=WIDTH==64?64'hffffffffffffffff:(64'd1<<WIDTH)-1;
    control.awvalid=0;control.wvalid=0;control.bvalid=0;control.bready=0;control.awready=0;control.wready=0;
    control.awaddr=0;control.awsize=2;control.awlen=0;control.wdata=0;control.wstrb=0;control.wlast=1;control.bresp=0;
    repeat(4)@(negedge clk);reset_n=1;
    control_write(32'h100000b4,3);if(!snap[34]||snap[33])$fatal(1,"STOP while idle was accepted");
    control_write(32'h100000b4,4);if(snap[34]||snap[33])$fatal(1,"CLEAR did not reset status");
    control_write(32'h100000b0,32'h12345678,15,0,1);
    control_write(32'h100000b4,1,15,2);if(snap[32])$fatal(1,"failed MMIO response started window");
    control_write(32'h100000b4,1,3,0);if(snap[32]||!snap[34])$fatal(1,"partial write accepted");
    control_write(32'h100000b4,4);
    control_write(32'h100000b0,32'h12345678);
    events=1;control_write(32'h100000b4,1);
    repeat(70)@(negedge clk);
    // Capture counts include the B-commit edge but the observer keeps running.
    control_write(32'h100000b4,2);
    // The task returns one half-cycle after capture; no further edge counted.
    verify(32'h12345678,1);held=snap;
    repeat(30)@(negedge clk);
    if(snap[2047:64]!==held[2047:64])$fatal(1,"frozen counters changed during active counting");
    control_write(32'h100000b0,32'hfeedface);
    control_write(32'h100000b4,1);if(!snap[34])$fatal(1,"active START not rejected");
    repeat(300)@(negedge clk);
    control_write(32'h100000b4,3);verify(32'h12345678,0);held=snap;
    repeat(40)@(negedge clk);if(snap!==held)$fatal(1,"STOP did not freeze all state");
    control_write(32'h100000b4,4);
    control_write(32'h100000b0,32'h89abcdef);
    control_write(32'h100000b4,1);control_write(32'h100000b4,3);verify(32'h89abcdef,0);
    control_write(32'h100000b4,1);
    control_write(32'h100000b4,4);if(!snap[32]||!snap[34])$fatal(1,"active CLEAR was accepted");
    // Test-only state deposit reaches the 32-bit sequence limit without four
    // billion commands. This is not used by any workload/performance harness.
    @(negedge clk);dut.snapshot_sequence=32'hffffffff;#1;held=snap;
    control_write(32'h100000b4,2);
    if(!snap[32]||!snap[34]||snap[2047:64]!==held[2047:64])$fatal(1,"exhausted sequence captured or wrapped");
    control_write(32'h100000b4,3);
    if(snap[32]||!snap[34]||snap[2047:64]!==held[2047:64])$fatal(1,"exhausted sequence STOP did not release window");
    control_write(32'h100000b4,4);
    if(snap[127:32]!=96'h000000000000000000010000)$fatal(1,"sequence exhaustion recovery failed");
    // Reset discards all intervals and read sizes, even with live event input.
    @(negedge clk);reset_n=0;ref_active=0;repeat(3)@(negedge clk);reset_n=1;#1;
    if(snap[127:32]!=96'h000000000000000000010000)$fatal(1,"reset metadata mismatch");
    for(int j=0;j<24;j++)if(snap[128+j*64+:64]!=0)$fatal(1,"reset counter mismatch");
    $display("RESULT {\"counter_width\":%0d,\"snapshots_checked\":%0d,\"counters_per_snapshot\":24,\"negative_cases\":7,\"status\":\"PASS\"}",WIDTH,checks);
    $finish;
  end
  initial begin #1000000;$fatal(1,"global timeout");end
endmodule
