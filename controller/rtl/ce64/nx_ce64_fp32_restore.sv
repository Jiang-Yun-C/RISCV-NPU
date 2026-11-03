// PARALLEL=0: one shared multiplier and one adder, one group in flight.
// PARALLEL=1: independent p/v stages and an ordered elastic add stage. acc_i
// is supplied by the caller; dependent groups must wait for prior partial.
module nx_ce64_fp32_restore #(parameter bit PARALLEL=0) (
  input logic clock,reset_n,req_valid_i,
  output logic req_ready_o,
  input logic signed [31:0] dot_i,
  input logic [31:0] sa_i,sw_i,acc_i,tag_i,epoch_i,
  input logic [3:0] status_i,
  output logic rsp_valid_o,
  input logic rsp_ready_i,
  output logic [31:0] p_o,v_o,partial_o,tag_o,epoch_o,
  output logic [3:0] status_o,
  output logic [4:0] flags_o
);
  import nx_ce64_math_pkg::*;
  if(!PARALLEL) begin: serial
    typedef enum logic [3:0] {IDLE,M1I,M1W,M2I,M2W,ADDI,ADDW,OUT} state_t;
    state_t state;
    logic [31:0] cast_r,sa_r,sw_r,acc_r,p_r,v_r;
    logic [63:0] identity;
    logic [3:0] status_r;
    logic [4:0] flags_r,mflags,aflags;
    logic mr,mv,ar,av;
    logic [31:0] mresult,aresult;
    assign req_ready_o=reset_n && state==IDLE;
    assign rsp_valid_o=state==OUT;
    nx_ce64_fp32_op #(.MUL(1)) mul (
      .clock,.reset_n,.a_i(state==M1I ? cast_r : p_r),.b_i(state==M1I ? sa_r : sw_r),
      .tag_i(identity),.aux_i(1'b0),.valid_i(state==M1I || state==M2I),.ready_o(mr),
      .result_o(mresult),.flags_o(mflags),.tag_o(),.aux_o(),.valid_o(mv),
      .ready_i(state==M1W || state==M2W)
    );
    nx_ce64_fp32_op #(.MUL(0)) add (
      .clock,.reset_n,.a_i(acc_r),.b_i(v_r),.tag_i(identity),.aux_i(1'b0),
      .valid_i(state==ADDI),.ready_o(ar),.result_o(aresult),.flags_o(aflags),
      .tag_o(),.aux_o(),.valid_o(av),.ready_i(state==ADDW)
    );
    always_ff @(posedge clock or negedge reset_n) begin
      if(!reset_n) begin
        state<=IDLE;cast_r<=0;sa_r<=0;sw_r<=0;acc_r<=0;p_r<=0;v_r<=0;
        identity<=0;status_r<=0;flags_r<=0;
        p_o<=0;v_o<=0;partial_o<=0;tag_o<=0;epoch_o<=0;status_o<=0;flags_o<=0;
      end else case(state)
        IDLE: if(req_valid_i) begin
          cast_r<=cast_dot(dot_i);sa_r<=sa_i;sw_r<=sw_i;acc_r<=acc_i;
          identity<={epoch_i,tag_i};flags_r<=0;
          status_r<=status_i!=OK ? status_i : input_status(dot_i,sa_i,sw_i,acc_i);
          state<=M1I;
        end
        M1I: if(mr) state<=M1W;
        M1W: if(mv) begin
          p_r<=mresult;flags_r<=mflags;
          if(status_r==OK && !finite32(mresult)) status_r<=NONFINITE_P;
          state<=M2I;
        end
        M2I: if(mr) state<=M2W;
        M2W: if(mv) begin
          v_r<=mresult;flags_r<=flags_r|mflags;
          if(status_r==OK && !finite32(mresult)) status_r<=NONFINITE_V;
          state<=ADDI;
        end
        ADDI: if(ar) state<=ADDW;
        ADDW: if(av) begin
          p_o<=p_r;v_o<=v_r;partial_o<=aresult;
          epoch_o<=identity[63:32];tag_o<=identity[31:0];flags_o<=flags_r|aflags;
          status_o<=status_r==OK && !finite32(aresult) ? NONFINITE_SUM : status_r;
          state<=OUT;
        end
        OUT: if(rsp_ready_i) state<=IDLE;
        default: state<=IDLE;
      endcase
    end
  end else begin: pipeline
    typedef struct packed {logic [31:0] sw,acc;logic [3:0] status;} m1_aux_t;
    typedef struct packed {logic [31:0] acc,p;logic [3:0] status;logic [4:0] flags;} m2_aux_t;
    typedef struct packed {logic [31:0] p,v;logic [3:0] status;logic [4:0] flags;} add_aux_t;
    m1_aux_t input_aux,aux1;
    m2_aux_t next2,aux2;
    add_aux_t next3,aux3;
    logic in_valid,r1,v1,r2,v2,r3;
    logic [31:0] cast_r,sa_r,p,v;
    logic [63:0] identity,t1,t2,t3;
    logic [4:0] f1,f2,f3;
    assign req_ready_o=reset_n && (!in_valid || r1);
    always_ff @(posedge clock or negedge reset_n) begin
      if(!reset_n) begin in_valid<=0;cast_r<=0;sa_r<=0;identity<=0;input_aux<='0;end
      else if(req_ready_o) begin
        in_valid<=req_valid_i;
        if(req_valid_i) begin
          cast_r<=cast_dot(dot_i);sa_r<=sa_i;identity<={epoch_i,tag_i};
          input_aux<='{sw:sw_i,acc:acc_i,status:(status_i!=OK ? status_i : input_status(dot_i,sa_i,sw_i,acc_i))};
        end
      end
    end
    assign next2='{acc:aux1.acc,p:p,status:(aux1.status==OK && !finite32(p) ? NONFINITE_P : aux1.status),flags:f1};
    assign next3='{p:aux2.p,v:v,status:(aux2.status==OK && !finite32(v) ? NONFINITE_V : aux2.status),flags:(aux2.flags|f2)};
    nx_ce64_fp32_op #(.MUL(1),.AUX_W($bits(m1_aux_t))) m1 (
      .clock,.reset_n,.a_i(cast_r),.b_i(sa_r),.tag_i(identity),.aux_i(input_aux),
      .valid_i(in_valid),.ready_o(r1),.result_o(p),.flags_o(f1),.tag_o(t1),.aux_o(aux1),.valid_o(v1),.ready_i(r2));
    nx_ce64_fp32_op #(.MUL(1),.AUX_W($bits(m2_aux_t))) m2 (
      .clock,.reset_n,.a_i(p),.b_i(aux1.sw),.tag_i(t1),.aux_i(next2),
      .valid_i(v1),.ready_o(r2),.result_o(v),.flags_o(f2),.tag_o(t2),.aux_o(aux2),.valid_o(v2),.ready_i(r3));
    nx_ce64_fp32_op #(.MUL(0),.AUX_W($bits(add_aux_t))) add (
      .clock,.reset_n,.a_i(aux2.acc),.b_i(v),.tag_i(t2),.aux_i(next3),
      .valid_i(v2),.ready_o(r3),.result_o(partial_o),.flags_o(f3),.tag_o(t3),.aux_o(aux3),.valid_o(rsp_valid_o),.ready_i(rsp_ready_i));
    assign p_o=aux3.p;assign v_o=aux3.v;
    assign tag_o=t3[31:0];assign epoch_o=t3[63:32];assign flags_o=aux3.flags|f3;
    assign status_o=aux3.status==OK && !finite32(partial_o) ? NONFINITE_SUM : aux3.status;
  end
endmodule
