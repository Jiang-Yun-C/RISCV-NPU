// Two-state control proof on the direct datapath. No no-error or no-backpressure
// assumptions; arithmetic equivalence and the pipelined variant are unproven.
module formal_dot(input logic clock,reset_n,req_valid_i,rsp_ready_i,
    input logic [127:0] aq_i,wq_i,input logic [15:0] keep_i,
    input logic first_i,last_i,input logic [31:0] tag_i,epoch_i);
  logic req_ready_o,rsp_valid_o,bad_q_o,protocol_error_o,nonzero_a_o,nonzero_w_o;
  logic signed [31:0] dot_o;
  logic [31:0] tag_o,epoch_o;
  nx_ce64_dot16 #(.PIPE_PRODUCTS(0)) dut(.wq_raw_i(128'b0),.wq_raw_valid_i(1'b0),.wq_raw_other_i(128'b0),.wq_raw_bank_i(1'b0),.*);
  logic past_valid=0,pending=0;
  logic [31:0] active_tag=0,active_epoch=0,result_tag=0,result_epoch=0;
  always @(posedge clock) begin
    past_valid<=1;
    if(!reset_n)begin pending<=0;active_tag<=0;active_epoch<=0;result_tag<=0;result_epoch<=0;end
    else begin
      if(rsp_valid_o && rsp_ready_i)pending<=0;
      if(req_valid_i && req_ready_o)begin
        if(first_i)begin active_tag<=tag_i;active_epoch<=epoch_i;end
        if(last_i)begin
          pending<=1;result_tag<=first_i ? tag_i : active_tag;
          result_epoch<=first_i ? epoch_i : active_epoch;
        end
      end
    end
    if(past_valid && reset_n && $past(reset_n))begin
      assert(rsp_valid_o==pending);
      if(rsp_valid_o)begin assert(tag_o==result_tag);assert(epoch_o==result_epoch);end
      if($past(rsp_valid_o && !rsp_ready_i))begin
        assert(rsp_valid_o);
        assert({dot_o,tag_o,epoch_o,bad_q_o,protocol_error_o,nonzero_a_o,nonzero_w_o}==
               $past({dot_o,tag_o,epoch_o,bad_q_o,protocol_error_o,nonzero_a_o,nonzero_w_o}));
      end
    end
  end
endmodule
