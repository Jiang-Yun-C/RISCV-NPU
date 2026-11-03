`timescale 1ns/1ps
module tb_dot;
  parameter bit PIPE_PRODUCTS=1;
  logic clock=0,reset_n=0,req_valid_i=0,req_ready_o,rsp_valid_o,rsp_ready_i=0;
  logic [127:0] aq_i=0,wq_i=0;
  logic [15:0] keep_i=0;
  logic first_i=0,last_i=0;
  logic [31:0] tag_i=0,epoch_i=0,tag_o,epoch_o;
  logic signed [31:0] dot_o;
  logic bad_q_o,protocol_error_o,nonzero_a_o,nonzero_w_o;
  nx_ce64_dot16 #(.PIPE_PRODUCTS(PIPE_PRODUCTS)) dut(.wq_raw_i(128'b0),.wq_raw_valid_i(1'b0),.wq_raw_other_i(128'b0),.wq_raw_bank_i(1'b0),.*);
  always #4 clock=~clock;
  logic [511:0] a,w;
  logic [31:0] sa,sw,acc,dot,p,v,y;
  logic [3:0] status;
  logic [4:0] flags;
  integer fd,n,count,len,offset,beat_count,cycle=0,last_cycle,min_latency=9999,max_latency=0;
  string file;
  task automatic beat(input bit f,l,input logic [15:0] k,input logic [31:0] t,e);
    @(negedge clock);first_i=f;last_i=l;keep_i=k;tag_i=t;epoch_i=e;req_valid_i=1;
    do @(posedge clock);while(!req_ready_o);
    last_cycle=cycle;
    @(negedge clock);req_valid_i=0;
  endtask
  task automatic expect_protocol(input bit expected);
    do @(negedge clock);while(!rsp_valid_o);
    if(protocol_error_o!==expected)$fatal(1,"protocol checker got=%0d expected=%0d",protocol_error_o,expected);
    rsp_ready_i=1;@(negedge clock);rsp_ready_i=0;
  endtask
  initial begin
    if(!$value$plusargs("vectors=%s",file))$fatal(1,"vectors missing");
    fd=$fopen(file,"r");if(!fd)$fatal(1,"input missing");
    repeat(4)@(negedge clock);reset_n=1;count=0;
    while(!$feof(fd))begin
      n=$fscanf(fd,"%d %h %h %h %h %h %h %h %h %h %h %h\n",len,a,w,sa,sw,acc,dot,p,v,y,status,flags);
      if(n==-1)break;
      if(n!=12)$fatal(1,"bad vector");
      for(offset=0;offset<len;offset=offset+16)begin
        aq_i=a[offset*8+:128];wq_i=w[offset*8+:128];beat_count=len-offset<16 ? len-offset : 16;
        beat(offset==0,offset+16>=len,16'hffff>>(16-beat_count),count,32'h641);
      end
      do @(negedge clock);while(!rsp_valid_o);
      if(dot_o!==dot || protocol_error_o!==0 || tag_o!==32'(count) || epoch_o!==32'h641)$fatal(1,"dot mismatch %0d",count);
      if(bad_q_o!==(status==7))$fatal(1,"bad-q mismatch %0d",count);
      if(cycle-last_cycle<min_latency)min_latency=cycle-last_cycle;
      if(cycle-last_cycle>max_latency)max_latency=cycle-last_cycle;
      repeat(count%71==0 ? 40 : 1)begin
        @(negedge clock);if(!rsp_valid_o || dot_o!==dot)$fatal(1,"dot blocked stability");
      end
      rsp_ready_i=1;@(negedge clock);rsp_ready_i=0;count++;
    end
    aq_i=0;wq_i=0;
    beat(0,1,1,1,1);expect_protocol(1); // missing FIRST
    beat(1,1,16'h0005,1,1);expect_protocol(1); // non-prefix tail
    beat(1,0,16'hffff,1,1);beat(0,1,1,2,1);expect_protocol(1); // tag change
    beat(1,0,16'hffff,1,1);beat(0,1,1,1,2);expect_protocol(1); // epoch change
    beat(1,0,1,1,1);beat(0,1,1,1,1);expect_protocol(1); // partial non-last
    beat(1,0,16'hffff,1,1);repeat(3)beat(0,0,16'hffff,1,1);beat(0,1,1,1,1);expect_protocol(1); // oversized
    beat(1,1,1,1,1);expect_protocol(0); // re-synchronization
    if(count<1000)$fatal(1,"empty test");
    $display("CE64_DOT_PASS pipeline=%0d groups=%0d protocol_cases=7 last_to_valid_min=%0d last_to_valid_max=%0d",PIPE_PRODUCTS,count,min_latency,max_latency);$finish;
  end
  always @(posedge clock)begin cycle++;if(cycle>2000000)$fatal(1,"watchdog");end
endmodule
