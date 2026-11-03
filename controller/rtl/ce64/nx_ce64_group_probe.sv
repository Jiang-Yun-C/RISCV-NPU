// One group in flight. Header is captured on first accepted beat; continuation
// header changes are ignored. dot protocol checks tag/epoch and beat framing.
module nx_ce64_group_probe #(parameter bit PARALLEL=0) (
  input logic clock,reset_n,req_valid_i,
  output logic req_ready_o,
  input logic [127:0] aq_i,wq_i,
  input logic [15:0] keep_i,
  input logic first_i,last_i,
  input logic [31:0] sa_i,sw_i,acc_i,tag_i,epoch_i,
  output logic rsp_valid_o,
  input logic rsp_ready_i,
  output logic signed [31:0] dot_o,
  output logic [31:0] p_o,v_o,partial_o,tag_o,epoch_o,
  output logic [3:0] status_o,
  output logic [4:0] flags_o
);
  import nx_ce64_math_pkg::*;
  logic sent_last;
  logic [31:0] sa_r,sw_r,acc_r;
  logic dot_ready,dv,fr,bad,proto,na,nw;
  logic signed [31:0] dot;
  logic [31:0] dt,de;
  logic [3:0] initial_status;
  assign req_ready_o=!sent_last && dot_ready;
  always_comb begin
    initial_status=OK;
    if(proto) initial_status=BAD_PROTOCOL;
    else if(!scale32(sa_r)||!scale32(sw_r)) initial_status=BAD_SCALE;
    else if(bad) initial_status=BAD_Q;
    else if((sa_r==0 && na)||(sw_r==0 && nw)) initial_status=ZERO_Q;
  end
  nx_ce64_dot16 dot_unit (
    .clock,.reset_n,.req_valid_i(req_valid_i && !sent_last),.req_ready_o(dot_ready),
    .aq_i,.wq_i,.keep_i,.first_i,.last_i,.tag_i,.epoch_i,
    .rsp_valid_o(dv),.rsp_ready_i(fr),.dot_o(dot),.tag_o(dt),.epoch_o(de),
    .bad_q_o(bad),.protocol_error_o(proto),.nonzero_a_o(na),.nonzero_w_o(nw));
  nx_ce64_fp32_restore #(.PARALLEL(PARALLEL)) restore (
    .clock,.reset_n,.req_valid_i(dv),.req_ready_o(fr),.dot_i(dot),.sa_i(sa_r),.sw_i(sw_r),.acc_i(acc_r),
    .tag_i(dt),.epoch_i(de),.status_i(initial_status),.rsp_valid_o,.rsp_ready_i,
    .p_o,.v_o,.partial_o,.tag_o,.epoch_o,.status_o,.flags_o);
  always_ff @(posedge clock or negedge reset_n) begin
    if(!reset_n) begin sent_last<=0;sa_r<=0;sw_r<=0;acc_r<=0;dot_o<=0;end
    else begin
      if(req_valid_i && req_ready_o) begin
        if(first_i) begin sa_r<=sa_i;sw_r<=sw_i;acc_r<=acc_i;end
        if(last_i) sent_last<=1;
      end
      if(dv && fr) dot_o<=dot;
      if(rsp_valid_o && rsp_ready_i) sent_last<=0;
    end
  end
endmodule
