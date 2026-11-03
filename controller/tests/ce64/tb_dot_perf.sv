`timescale 1ns/1ps
module tb_dot_perf;
  parameter bit PIPE_PRODUCTS=1;
  logic clock=0,reset_n=0,req_valid_i=0,req_ready_o,rsp_valid_o,rsp_ready_i=1;
  logic [127:0] aq_i=0,wq_i={16{8'h01}};
  logic [15:0] keep_i='1;
  logic first_i=0,last_i=0;
  logic [31:0] tag_i=0,epoch_i=7,tag_o,epoch_o;
  logic signed [31:0] dot_o;
  logic bad_q_o,protocol_error_o,nonzero_a_o,nonzero_w_o;
  nx_ce64_dot16 #(.PIPE_PRODUCTS(PIPE_PRODUCTS)) dut(.wq_raw_i(128'b0),.wq_raw_valid_i(1'b0),.wq_raw_other_i(128'b0),.wq_raw_bank_i(1'b0),.*);
  always #4 clock=~clock;
  integer accepted=0,received=0,first_cycle=-1,last_cycle=0,now_cycle;
  integer last_beat[0:255];
  initial begin
    repeat(4)@(negedge clock);reset_n=1;
    while(received<256)begin
      @(negedge clock);
      req_valid_i=accepted<1024;
      first_i=accepted%4==0;last_i=accepted%4==3;tag_i=accepted/4;
      aq_i={16{8'(integer'(accepted/4%127)-63)}};
      @(posedge clock);now_cycle=integer'($time/8);
      if(req_valid_i && req_ready_o)begin
        if(first_cycle<0)first_cycle=now_cycle;
        if(last_i)last_beat[accepted/4]=now_cycle;
        last_cycle=now_cycle;accepted++;
      end
      if(rsp_valid_o && rsp_ready_i)begin
        if(tag_o!==32'(received) || epoch_o!==7 || dot_o!==32'((received%127-63)*64) || bad_q_o || protocol_error_o)
          $fatal(1,"dot throughput arithmetic or identity");
        if(now_cycle-last_beat[received]!=(PIPE_PRODUCTS ? 2 : 1))$fatal(1,"dot intrinsic latency");
        received++;
      end
      if(now_cycle>3000)$fatal(1,"dot throughput timeout");
    end
    if(last_cycle-first_cycle!=1023)$fatal(1,"input throughput not 1 beat/cycle");
    $display("CE64_DOT_PERF_PASS pipeline=%0d groups=256 group_II=4 beat_II=1 last_to_consumer=%0d acceptance_span=1023",PIPE_PRODUCTS,PIPE_PRODUCTS ? 2 : 1);$finish;
  end
endmodule
