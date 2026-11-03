`timescale 1ns/1ps
module tb_t25_pressure_gate;
  reg clk=0,reset_n=0,enable=0,ddr_init_done=1,fault=0;
  always #4 clk=~clk;
  axi4_if #(.DATA_W(128),.ID_W(6)) source_bus(clk),memory(clk);
  t25_pressure_gate #(.GAP_CYCLES(8192)) gate(.clk,.reset_n,.source_bus,.memory);
  wire stopped,full_range_verified,byte_masks_verified,failed;
  wire [31:0] errors,verified_passes,first_error_word_address,phase_status,debug_address,debug_stalled,debug_reason,workload;
  wire [255:0] debug_expected;wire [3:0] debug_beat;
  wire [63:0] workload_cycles;
  ce64_axi_bist #(.WINDOW_BITS(12),.BASE_ADDRESS(32'had000000),.BANDWIDTH_CYCLES(20000),.STALL_LIMIT(1000000)) bist(
    .clk,.rst_n(reset_n),.ddr_init_done,.fault,.enable,.stopped,
    .s_awaddr(source_bus.awaddr),.s_araddr(source_bus.araddr),.s_awid(source_bus.awid),.s_arid(source_bus.arid),.s_awlen(source_bus.awlen),.s_arlen(source_bus.arlen),.s_awsize(source_bus.awsize),.s_arsize(source_bus.arsize),.s_awburst(source_bus.awburst),.s_arburst(source_bus.arburst),.s_awvalid(source_bus.awvalid),.s_arvalid(source_bus.arvalid),.s_wvalid(source_bus.wvalid),.s_wlast(source_bus.wlast),.s_bready(source_bus.bready),.s_rready(source_bus.rready),.s_wdata(source_bus.wdata),.s_wstrb(source_bus.wstrb),.s_awready(source_bus.awready),.s_arready(source_bus.arready),.s_wready(source_bus.wready),.s_bvalid(source_bus.bvalid),.s_rvalid(source_bus.rvalid),.s_rlast(source_bus.rlast),.s_bid(source_bus.bid),.s_rid(source_bus.rid),.s_bresp(source_bus.bresp),.s_rresp(source_bus.rresp),.s_rdata(source_bus.rdata),
    .errors,.verified_passes,.first_error_word_address,.full_range_verified,.byte_masks_verified,.failed,
    .phase_status,.debug_address,.debug_stalled,.debug_reason,.debug_expected,.debug_beat,.workload,.workload_cycles);
  reg [7:0] ram[0:4095];
  integer c=0,checks=0,launches=0,last_completion=-1000000,masked=0;
  reg [6:0] modes=0;
  reg writing=0,reading=0;
  reg [31:0] wa,ra;reg [7:0] wl,rl;reg [5:0] wi,ri;
  reg held_aw=0,held_ar=0,held_w=0,held_r=0;
  reg [50:0] aw_fields,ar_fields;reg [144:0] w_fields;reg [136:0] r_fields;
  assign memory.awready=reset_n&&!writing&&!reading&&!memory.bvalid&&(c%5==0);
  assign memory.arready=reset_n&&!writing&&!reading&&!memory.bvalid&&(c%7==0);
  assign memory.wready=writing&&(c%3!=0);
  integer i,lane;
  initial for(i=0;i<4096;i=i+1)ram[i]=0;
  always @(posedge clk)begin
    if(!reset_n)begin
      c<=0;checks<=0;launches<=0;last_completion<=-1000000;masked<=0;modes<=0;
      writing<=0;reading<=0;memory.bvalid<=0;memory.bresp<=0;memory.bid<=0;
      memory.rvalid<=0;memory.rdata<=0;memory.rresp<=0;memory.rid<=0;memory.rlast<=0;
      held_aw<=0;held_ar<=0;held_w<=0;held_r<=0;
    end else begin
      c<=c+1;checks<=checks+1;modes[workload]<=1;
      if(held_aw&&(!memory.awvalid||{memory.awaddr,memory.awid,memory.awlen,memory.awsize,memory.awburst}!==aw_fields))$fatal(1,"AW offer changed under backpressure");
      if(held_ar&&(!memory.arvalid||{memory.araddr,memory.arid,memory.arlen,memory.arsize,memory.arburst}!==ar_fields))$fatal(1,"AR offer changed under backpressure");
      if(held_w&&(!memory.wvalid||{memory.wdata,memory.wstrb,memory.wlast}!==w_fields))$fatal(1,"W offer changed under backpressure");
      if(held_r&&(!source_bus.rvalid||{source_bus.rdata,source_bus.rid,source_bus.rresp,source_bus.rlast}!==r_fields))$fatal(1,"R response changed while held");
      held_aw<=memory.awvalid&&!memory.awready;held_ar<=memory.arvalid&&!memory.arready;
      held_w<=memory.wvalid&&!memory.wready;held_r<=source_bus.rvalid&&!source_bus.rready;
      aw_fields<={memory.awaddr,memory.awid,memory.awlen,memory.awsize,memory.awburst};
      ar_fields<={memory.araddr,memory.arid,memory.arlen,memory.arsize,memory.arburst};
      w_fields<={memory.wdata,memory.wstrb,memory.wlast};r_fields<={source_bus.rdata,source_bus.rid,source_bus.rresp,source_bus.rlast};
      if(memory.awvalid&&memory.awready)begin
        if(c-last_completion<8192||writing||reading||memory.awaddr<32'had000000||memory.awaddr+16*(memory.awlen+1)>32'had001000||memory.awid!=61||memory.awsize!=4||memory.awburst!=1)$fatal(1,"AW range/rate/protocol");
        wa<=memory.awaddr;wl<=memory.awlen;wi<=memory.awid;writing<=1;launches<=launches+1;
        if(bist.phase==2)masked<=masked+1;
      end
      if(memory.wvalid&&memory.wready)begin
        if(memory.wlast!=(wl==0))$fatal(1,"Write beat count");
        for(lane=0;lane<16;lane=lane+1)if(memory.wstrb[lane])ram[(wa+lane)&4095]<=memory.wdata[lane*8+:8];
        if(wl==0)begin writing<=0;memory.bvalid<=1;memory.bid<=wi;memory.bresp<=$test$plusargs("BAD_BRESP") ? 2'b10 : 2'b00;end
        else begin wl<=wl-1;wa<=wa+16;end
      end
      if(memory.bvalid&&memory.bready)begin memory.bvalid<=0;last_completion<=c;end
      if(memory.arvalid&&memory.arready)begin
        if(c-last_completion<8192||writing||reading||memory.araddr<32'had000000||memory.araddr+16*(memory.arlen+1)>32'had001000||memory.arid!=43||memory.arsize!=4||memory.arburst!=1)$fatal(1,"AR range/rate/protocol");
        ra<=memory.araddr;rl<=memory.arlen;ri<=memory.arid;reading<=1;launches<=launches+1;
      end
      if(reading&&!memory.rvalid&&c%3==0)begin
        memory.rvalid<=1;memory.rid<=ri;memory.rresp<=0;memory.rlast<=rl==0;
        for(lane=0;lane<16;lane=lane+1)memory.rdata[lane*8+:8]<=ram[(ra+lane)&4095];
        if($test$plusargs("CORRUPT_READ")&&bist.phase==3&&bist.mask_index==16)memory.rdata[0]<=~ram[ra&4095][0];
      end
      if(memory.rvalid&&memory.rready)begin
        memory.rvalid<=0;
        if(rl==0)begin reading<=0;last_completion<=c;end
        else begin rl<=rl-1;ra<=ra+16;end
      end
      if(failed)$fatal(1,"BIST detected failure reason=%0d",debug_reason);
    end
  end
  initial if($test$plusargs("LOST_CALIBRATION"))begin wait(bist.state==2);ddr_init_done=0;end
  initial begin
    repeat(10)@(negedge clk);reset_n=1;
    repeat(200)begin @(negedge clk);if(memory.awvalid||memory.arvalid||memory.wvalid)$fatal(1,"Disabled pressure was not quiet");end
    enable=1;
    if(!$test$plusargs("BAD_BRESP")&&!$test$plusargs("CORRUPT_READ")&&!$test$plusargs("LOST_CALIBRATION"))begin
      wait(bist.state==2&&bist.beat==3);@(negedge clk);enable=0;
      wait(stopped);@(negedge clk);
      if(gate.state!=0||writing||reading||memory.awvalid||memory.arvalid||memory.wvalid||memory.bvalid||memory.rvalid)$fatal(1,"Pressure stop did not drain B/R");
      repeat(40)@(negedge clk);
      reset_n=0;enable=0;repeat(10)@(negedge clk);reset_n=1;enable=1;
    end
    wait(verified_passes==2);@(negedge clk);
    if(!full_range_verified||!byte_masks_verified||errors||modes!=127||masked!=64||launches<160)$fatal(1,"Incomplete masks/range/workload coverage");
    $display("T25_PRESSURE_GATE_PASS checks=%0d launches=%0d masks=%0d modes=%h gap=8192",checks,launches,masked,modes);$finish;
  end
  initial begin #40000000;$fatal(1,"Gate/BIST test timeout");end
endmodule
