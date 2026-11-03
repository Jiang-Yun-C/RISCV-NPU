`timescale 1ns/1ps
module tb_bulk_dma;
  reg clk=0;always #4 clk=~clk;
  reg reset_n=0,stop_new=0,command_valid=0,command_write=1;
  reg [31:0] command_address=0;
  reg [2:0] command_size=4;
  reg [4:0] command_len=0;
  reg [15:0] command_scratch=0,command_mask=16'hffff;
  reg [127:0] command_data=128'h0102030405060708090a0b0c0d0e0f10;
  wire command_ready,result_valid,idle,pending_offer,scratch_en;
  wire [1:0] result_resp;
  wire [31:0] result_address;
  wire [11:0] scratch_addr;
  wire [127:0] scratch_data,scratch_q;
  wire [15:0] scratch_mask;
  wire [63:0] read_bytes,write_bytes;
  reg result_ready=0,a_en=0;
  reg [11:0] a_addr;
  reg [15:0] a_we;
  reg [127:0] a_data;
  axi4_if #(.DATA_W(128),.ID_W(6)) bus(clk);
  nx_ce64_dma dut(.*);
  nx_ce64_scratch scratch(.clk,.a_en,.b_en(scratch_en),.a_addr,.b_addr(scratch_addr),.a_we,.b_we(scratch_mask),.a_data,.b_data(scratch_data),.a_q(),.b_q(scratch_q));
  integer ticks=0,checks=0,cases=0,aw_count=0,w_count=0,b_count=0,blocked_aw=0,blocked_w=0;
  reg aw_seen=0,responded=0;
  integer beats_seen=0,response_delay=0;
  reg [1:0] requested_resp=0;
  reg wrong_id=0;
  reg [31:0] held_aw;
  reg [7:0] held_len;
  reg [127:0] held_data;
  reg [15:0] held_mask;
  reg held_last;
  reg aw_stalled=0,w_stalled=0;
  function automatic [127:0] pattern(input integer position);
    pattern=128'h713fe1024a9b506ce47192a3150fed83 ^ (128'(position)*128'h01010101010101010101010101010101);
  endfunction
  assign bus.arready=0;assign bus.rvalid=0;assign bus.rdata=0;assign bus.rid=0;assign bus.rresp=0;assign bus.rlast=0;
  assign bus.awready=ticks%7==0;
  assign bus.wready=ticks%5==0||ticks%5==2;
  always @(posedge clk)begin
    ticks<=ticks+1;
    if(reset_n)begin
      if(a_en&&scratch_en)$fatal(1,"physical scratch collision");
      if(aw_stalled&&(!bus.awvalid||bus.awaddr!==held_aw||bus.awlen!==held_len))$fatal(1,"AW changed under backpressure");
      if(w_stalled&&(!bus.wvalid||bus.wdata!==held_data||bus.wstrb!==held_mask||bus.wlast!==held_last))$fatal(1,"W changed under backpressure");
      aw_stalled<=bus.awvalid&&!bus.awready;held_aw<=bus.awaddr;held_len<=bus.awlen;
      w_stalled<=bus.wvalid&&!bus.wready;held_data<=bus.wdata;held_mask<=bus.wstrb;held_last<=bus.wlast;
      if(aw_stalled)blocked_aw++;
      if(w_stalled)blocked_w++;
      if(bus.awvalid&&bus.awready)begin
        if(aw_seen||bus.awaddr!=command_address||bus.awlen!={3'b0,command_len}||bus.awsize!=command_size||bus.awburst!=1)$fatal(1,"AW identity");
        aw_seen=1;aw_count++;checks++;
      end
      if(bus.wvalid&&bus.wready)begin
        if(bus.wlast!=(beats_seen==command_len)||bus.wstrb!==command_mask)$fatal(1,"LEN/WLAST/mask");
        if(bus.wdata!==(command_scratch!=0 ? pattern(beats_seen) : command_data))$fatal(1,"independent scratch data beat=%0d actual=%h",beats_seen,bus.wdata);
        beats_seen++;w_count++;checks++;
      end
      if(aw_seen&&beats_seen==command_len+1&&!responded)begin
        response_delay++;
        if(response_delay==19)begin bus.bvalid<=1;bus.bresp<=requested_resp;bus.bid<=wrong_id?1:0;responded=1;end
      end
      if(bus.bvalid&&bus.bready)begin bus.bvalid<=0;b_count++;end
    end
  end
  task automatic run(input integer length,input bit buffered,input integer stop_at,input integer error_kind,input bit invalid);
    integer before_aw,before_w,before_b,age;
    reg [63:0] before_bytes;
    begin
      @(negedge clk);stop_new=0;command_address=32'hac001e00;command_len=5'(length-1);
      command_size=4;command_mask=16'hffff;command_scratch=buffered?16'hf000:0;
      requested_resp=error_kind==1?2:0;wrong_id=error_kind==2;
      if(invalid)begin
        case(error_kind)
          0:command_address=32'hac001ff0;
          1:command_scratch=16'hfff0;
          2:command_mask=16'hfffe;
          3:command_size=3;
        endcase
      end
      aw_seen=0;responded=0;beats_seen=0;response_delay=0;before_bytes=write_bytes;
      before_aw=aw_count;before_w=w_count;before_b=b_count;
      command_valid=1;while(!command_ready)@(negedge clk);
      @(negedge clk);command_valid=0;age=0;
      while(!result_valid&&age<1000)begin
        if(age==stop_at)stop_new=1;
        @(negedge clk);age++;
      end
      if(!result_valid||result_address!=command_address)$fatal(1,"missing exact completion");
      if(result_resp!==(invalid?2'd3:error_kind==2?2'd2:requested_resp))$fatal(1,"result status");
      if(invalid)begin
        if(aw_count!=before_aw||w_count!=before_w||b_count!=before_b)$fatal(1,"illegal command reached bus");
      end else if(aw_count!=before_aw+1||w_count!=before_w+length||b_count!=before_b+1)$fatal(1,"lost accepted quantum");
      if(write_bytes!=before_bytes+((!invalid&&error_kind==0)?length*16:0))$fatal(1,"success-only byte counter");
      // Hold completion without releasing the transaction, including STOP.
      repeat(5)begin @(negedge clk);if(!result_valid||idle||command_ready)$fatal(1,"completion dropped");end
      result_ready=1;@(negedge clk);result_ready=0;stop_new=0;@(negedge clk);
      if(!idle)$fatal(1,"drained recovery");cases++;checks++;
    end
  endtask
  initial begin
    bus.bvalid=0;bus.bresp=0;bus.bid=0;
    repeat(3)@(negedge clk);reset_n=1;
    for(integer i=0;i<32;i++)begin a_en=1;a_addr=12'hf00+12'(i);a_we=16'hffff;a_data=pattern(i);@(negedge clk);end
    a_en=0;a_we=0;
    for(integer length=1;length<=32;length++)begin
      run(length,1,-1,0,0);
      for(integer stop_at=0;stop_at<5;stop_at++)run(length,1,stop_at*17,0,0);
      run(length,1,-1,1,0);run(length,1,-1,2,0);
    end
    run(1,0,-1,0,0);
    for(integer error_kind=0;error_kind<4;error_kind++)run(2,1,-1,error_kind,1);
    if(blocked_aw==0||blocked_w==0)$fatal(1,"no backpressure tested");
    $display("BULK_DMA_PASS cases=%0d checks=%0d aw=%0d w=%0d b=%0d blocked_aw=%0d blocked_w=%0d",cases,checks,aw_count,w_count,b_count,blocked_aw,blocked_w);$finish;
  end
endmodule
