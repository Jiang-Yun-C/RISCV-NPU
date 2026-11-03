// OPT12 shares all OPT11 arithmetic; result RAM peeks take one clock.
module nx_opt11_group #(parameter integer LANES=2,parameter bit EXTERNAL_FP=0)(

  output wire shared_start,shared_multiply,
  output wire [31:0] shared_a,shared_b,
  input wire shared_ready,shared_valid,input wire [31:0] shared_result,
  input wire clk,reset_n,start,ack,input wire [6:0] length,
  input wire [3:0] mode,input wire quantize_result,pad_full,input wire [31:0] scalar,
  input wire load_valid,output wire load_ready,input wire [127:0] gate_data,up_data,
  output wire valid,idle,output reg error,input wire [5:0] peek,
  output wire [127:0] fp_data,output reg [127:0] q_data,
  output reg [31:0] scale,output reg [63:0] cycles
);
  localparam logic [5:0] IDLE=0,LOAD=1,CHECK=2,EXP=3,EXP_WAIT=4,ADD=5,ADD_WAIT=6,
    DIV=7,DIV_WAIT=8,MUL1=9,MUL1_WAIT=10,MUL2=11,MUL2_WAIT=12,
    SCALE=13,SCALE_WAIT=14,QUANT=15,QUANT_WAIT=16,ROUND=17,DONE=18,FETCH=19,
    TREE_A=20,TREE_A_WAIT=21,TREE_B=22,TREE_B_WAIT=23,TREE_OP=24,TREE_WAIT=25,
    TREE_WRITE=26,FINISH=27,QFETCH=28,QWAIT=29,
    N_DIV=30,N_DIV_WAIT=31,N_ADD=32,N_ADD_WAIT=33,N_SQRT=34,N_SQRT_WAIT=35,
    N_RECIP=36,N_RECIP_WAIT=37,N_WRITE=38,EXP_DRAIN=39;
  reg [5:0] state;
  reg [7:0] integers[0:63];
  reg [6:0] count,n,index,width,pair_index;
  reg [3:0] operation;
  reg do_quant,full_tree;
  // The input bank has settled in CHECK. Capture the sigmoid numerator choice
  // there, before the existing EXP/ADD work, rather than rereading all 31
  // fraction/exponent bits on the divider admission edge.
  reg gate_negative_nonzero;
  // CHECK already follows the synchronous bank read. Preserve that original
  // sample for the following EXP admission without adding a state or cycle.
  reg [31:0] exp_input_q;
  reg [31:0] factor,exponent_value,denominator,sigmoid,product,amax,quotient;
  reg [31:0] left_value,right_value,tree_result;
  wire [31:0] gate_banks[0:LANES-1],up_banks[0:LANES-1];
  // One-element mode0 lookahead. Current operands are held while the same
  // synchronous input-bank ports visit the next element. No bank duplication.
  reg [31:0] current_gate,current_up,next_exp_input,ahead_result;
  reg ahead_started,ahead_valid;
  wire prefetch_bank=operation==0 && index+1<n &&
      (state==EXP||state==EXP_WAIT||state==ADD||state==ADD_WAIT);
  wire [6:0] input_index=prefetch_bank ? index+7'd1 : index;
  wire [31:0] raw_gate=gate_banks[input_index%LANES],raw_up=up_banks[input_index%LANES];
  wire [31:0] gate_value=operation==0&&state!=CHECK ? current_gate : raw_gate;
  wire [31:0] up_value=operation==0&&state!=CHECK ? current_up : raw_up;
  genvar bank;
  generate for(bank=0;bank<LANES;bank=bank+1)begin:input_banks
    wire [$clog2(64/LANES)-1:0] address=state==LOAD ? $clog2(64/LANES)'(count/LANES) : $clog2(64/LANES)'(input_index/LANES);
    nx_opt11_bank #(.DEPTH(64/LANES)) gate_bank(.clk,.write(state==LOAD&&load_valid),.address,
      .data(count+bank<n ? gate_data[32*bank+:32] : 32'b0),.q(gate_banks[bank]));
    nx_opt11_bank #(.DEPTH(64/LANES)) up_bank(.clk,.write(state==LOAD&&load_valid),.address,
      .data(count+bank<n ? up_data[32*bank+:32] : 32'b0),.q(up_banks[bank]));
  end endgenerate
  wire ex_ready,ex_valid,dv_ready,dv_valid,fp_ready,fp_valid,sq_ready,sq_valid;
  wire [31:0] ex_result,dv_result,fp_result,sq_result,value_q;
  wire fp_start=(state==ADD||state==MUL1||state==MUL2||state==TREE_OP||state==N_ADD)&&fp_ready;
  wire dv_start=(state==DIV||state==SCALE||state==QUANT||state==N_DIV||state==N_RECIP)&&dv_ready;
  wire [31:0] fp_a=state==TREE_OP ? left_value : state==N_ADD ? product :
    state==ADD ? (operation==0 ? 32'h3f800000 : gate_value) : state==MUL1 ? gate_value : product;
  wire [31:0] fp_b=state==TREE_OP ? right_value : state==N_ADD ? 32'h358637bd :
    state==ADD ? (operation==0 ? exponent_value : up_value) : state==MUL2 ? up_value :
    operation==0 ? sigmoid : operation==4||operation==8 ? factor : operation==7 ? gate_value : up_value;
  wire [31:0] dv_a=state==SCALE ? amax : state==QUANT ? value_q :
    state==N_DIV ? gate_value : state==N_RECIP ? 32'h3f800000 :
    (gate_negative_nonzero ? exponent_value : 32'h3f800000);
  wire [31:0] dv_b=state==SCALE ? 32'h42fe0000 : state==QUANT ? scale :
    state==N_DIV ? up_value : state==N_RECIP ? product : denominator;
  // ADD_WAIT is deliberately used after the two bank-read/capture edges.
  // Even zero/subnormal/underflow fast exp responses have a stable next input.
  wire ahead_launch=operation==0 && state==ADD_WAIT && index+1<n &&
      !ahead_started && ex_ready;
  wire exp_start=(state==EXP && !ahead_started && ex_ready)||ahead_launch;
  nx_opt11_exp exp_core(.clk,.reset_n,.start(exp_start),
    .a(ahead_launch ? next_exp_input : exp_input_q),.ready(ex_ready),.valid(ex_valid),.result(ex_result));
  nx_opt11_div divider(.clk,.reset_n,.start(dv_start),.a(dv_a),.b(dv_b),.ready(dv_ready),.valid(dv_valid),.result(dv_result));
  assign shared_start=fp_start;assign shared_multiply=state==MUL1||state==MUL2;
  assign shared_a=fp_a;assign shared_b=fp_b;
  generate if(EXTERNAL_FP)begin
    assign fp_ready=shared_ready;assign fp_valid=shared_valid;assign fp_result=shared_result;
  end else begin
  nx_opt11_fp fp_core(.clk,.reset_n,.start(fp_start),.multiply(state==MUL1||state==MUL2),.a(fp_a),.b(fp_b),.ready(fp_ready),.valid(fp_valid),.result(fp_result));
  end endgenerate
  nx_opt12_sqrt sqrt_core(.clk,.reset_n,.start(state==N_SQRT&&sq_ready),.a(product),.ready(sq_ready),.valid(sq_valid),.result(sq_result));
  wire copy_write=state==CHECK&&index<64&&(index>=n||operation==1||operation==5||operation==6);
  wire result_write=(state==MUL1_WAIT&&(operation==3||operation==4||operation==7)||state==MUL2_WAIT||state==ADD_WAIT&&operation==2)&&fp_valid&&fp_result[30:23]!=255;
  wire memory_write=copy_write||result_write||state==TREE_WRITE||state==N_WRITE;
  wire [5:0] value_address=state==DONE ? peek :
    state==TREE_A||state==TREE_A_WAIT ? 6'(pair_index<<1) :
    state==TREE_B||state==TREE_B_WAIT ? 6'((pair_index<<1)+1) :
    state==TREE_WRITE ? pair_index[5:0] : state==N_WRITE ? 6'b0 : index[5:0];
  wire [31:0] memory_data=state==TREE_WRITE ? tree_result : state==N_WRITE ? product :
    copy_write ? (index>=n ? (operation==6 ? 32'hff800000 : 0) : gate_value) : fp_result;
  nx_opt11_bank #(.DEPTH(64)) result_bank(.clk,.write(memory_write),.address(value_address),.data(memory_data),.q(value_q));
  assign fp_data={96'b0,value_q};
  assign valid=state==DONE;assign idle=state==IDLE;assign load_ready=state==LOAD;
  reg [31:0] rounded_integer,magnitude;
  // The original QUANT_WAIT capture already separates divider result from
  // ROUND. Capture the shift/round predicates on that same edge so ROUND
  // does not include the exponent subtract and variable significand shift.
  // These metadata bits describe the simultaneously captured quotient.
  reg [31:0] round_magnitude;
  reg round_half,round_sticky;
  reg [23:0] significand;
  reg half_bit,sticky;
  integer sh;
  function automatic logic group_if_true(input logic value);
    begin if(value)group_if_true=1'b1;else group_if_true=1'b0;end
  endfunction
  function automatic logic half_from_shift(input logic[23:0] value,input integer shift);
    begin if(shift>=1&&shift<=24)half_from_shift=value[shift-1];else half_from_shift=1'b0;end
  endfunction
  wire[23:0] sticky_terms;
  genvar sticky_lane;
  generate for(sticky_lane=0;sticky_lane<24;sticky_lane=sticky_lane+1)begin:sticky_projection
    assign sticky_terms[sticky_lane]=group_if_true(integer'(sticky_lane)<sh-1) ? significand[sticky_lane] : 1'b0;
  end endgenerate
  wire[LANES-1:0] bad_load_terms;
  genvar load_lane;
  generate for(load_lane=0;load_lane<LANES;load_lane=load_lane+1)begin:load_error_projection
    assign bad_load_terms[load_lane]=group_if_true(count+integer'(load_lane)<n&&
      (gate_data[32*load_lane+23+:8]==255||((operation==0||operation==2||operation==3||operation==8||operation==9)&&up_data[32*load_lane+23+:8]==255)));
  end endgenerate
  always @*begin
    q_data=0;
    for(integer j=0;j<16;j=j+1)if(integer'(peek)+j<64)q_data[8*j+:8]=integers[peek+j];
    significand={dv_result[30:23]!=0,dv_result[22:0]};
    sh=150-integer'(dv_result[30:23]);half_bit=half_from_shift(significand,sh);sticky=|sticky_terms;
    magnitude=sh>=24 ? 0 : sh>=0 ? {8'b0,significand}>>sh : 127;
    rounded_integer=round_magnitude+(round_half&&(round_sticky||round_magnitude[0]));
    if(rounded_integer>127)rounded_integer=127;
  end
  function automatic [6:0] padded(input [6:0] len);
    begin padded=1;for(integer j=0;j<6;j=j+1)if(padded<len)padded=padded<<1;end
  endfunction
  function automatic greater(input [31:0] a,b);
    begin greater=(a[30:0]==0&&b[30:0]==0) ? !a[31] :
      a[31]!=b[31] ? !a[31] : a[31] ? a[30:0]<b[30:0] : a[30:0]>b[30:0];end
  endfunction
  always @(posedge clk or negedge reset_n)begin
    if(!reset_n)begin state<=IDLE;error<=0;count<=0;n<=0;index<=0;operation<=0;do_quant<=0;full_tree<=0;factor<=0;
      scale<=0;exponent_value<=0;denominator<=0;sigmoid<=0;product<=0;amax<=0;quotient<=0;
      round_magnitude<=0;round_half<=0;round_sticky<=0;gate_negative_nonzero<=0;exp_input_q<=0;
      current_gate<=0;current_up<=0;next_exp_input<=0;ahead_result<=0;ahead_started<=0;ahead_valid<=0;
      width<=0;pair_index<=0;left_value<=0;right_value<=0;tree_result<=0;end
    else begin
      if(state==CHECK&&operation==0)begin current_gate<=raw_gate;current_up<=raw_up;end
      if(prefetch_bank)next_exp_input<=raw_gate;
      if(ahead_launch)begin ahead_started<=1;ahead_valid<=0;end
      // A fast next exp may return during current div/mul. Retain it once.
      // EXP/EXP_WAIT consume in element order; neither divider nor FP reorders.
      if(ex_valid&&ahead_started)begin ahead_result<=ex_result;ahead_valid<=1;end
      if(state==CHECK)gate_negative_nonzero<=gate_value[31]&&gate_value[30:0]!=0;
      if(state==CHECK)exp_input_q<=gate_value;
      case(state)
        IDLE:if(start)begin ahead_started<=0;ahead_valid<=0;n<=length;count<=0;index<=0;amax<=0;scale<=0;operation<=mode;factor<=scalar;
          full_tree<=pad_full;error<=length==0||length>64||mode>9||((mode==4||mode==8)&&scalar[30:23]==255);do_quant<=mode<2||quantize_result;
          state<=length==0||length>64||mode>9 ? DONE : LOAD;end
        LOAD:if(load_valid)begin
          if(|bad_load_terms)error<=1;
          if(count+LANES>=64)begin index<=0;state<=FETCH;end else count<=count+LANES;
        end
        FETCH:state<=CHECK;
        CHECK:if(error)state<=DONE;
          else if(index>=n||operation==1||operation==5||operation==6)begin
            if(index==64)begin index<=0;
              if(operation==5||operation==6||operation==7)begin width<=full_tree ? 64 : padded(n);pair_index<=0;state<=TREE_A;end
              else state<=FINISH;
            end else begin
              if(index<n&&gate_value[30:0]>amax[30:0])amax<={1'b0,gate_value[30:0]};
              index<=index+1;state<=FETCH;
            end
          end else if(operation==9)state<=N_DIV;
          else state<=operation==0 ? EXP : operation==2 ? ADD : MUL1;
        EXP:if(ahead_started)begin
          if(ahead_valid||ex_valid)begin
            exponent_value<=ahead_valid ? ahead_result : ex_result;
            ahead_started<=0;ahead_valid<=0;state<=ADD;
          end else state<=EXP_WAIT;
        end else if(ex_ready)state<=EXP_WAIT;
        EXP_WAIT:if(ex_valid||ahead_valid)begin
          exponent_value<=ahead_valid ? ahead_result : ex_result;
          ahead_started<=0;ahead_valid<=0;state<=ADD;
        end
        ADD:if(fp_ready)state<=ADD_WAIT;
        ADD_WAIT:if(fp_valid)begin
          if(operation==0)begin denominator<=fp_result;state<=DIV;end
          else if(fp_result[30:23]==255)begin error<=1;state<=operation==0&&!ex_ready ? EXP_DRAIN : DONE;end
          else begin if(fp_result[30:0]>amax[30:0])amax<={1'b0,fp_result[30:0]};index<=index+1;state<=FETCH;end
        end
        DIV:if(dv_ready)state<=DIV_WAIT;
        DIV_WAIT:if(dv_valid)begin sigmoid<=dv_result;state<=MUL1;end
        MUL1:if(fp_ready)state<=MUL1_WAIT;
        MUL1_WAIT:if(fp_valid)begin
          if(fp_result[30:23]==255)begin error<=1;state<=operation==0&&!ex_ready ? EXP_DRAIN : DONE;end
          else if(operation==0||operation==8)begin product<=fp_result;state<=MUL2;end
          else begin if(fp_result[30:0]>amax[30:0])amax<={1'b0,fp_result[30:0]};index<=index+1;state<=FETCH;end
        end
        MUL2:if(fp_ready)state<=MUL2_WAIT;
        MUL2_WAIT:if(fp_valid)begin
          if(fp_result[30:23]==255)begin error<=1;state<=operation==0&&!ex_ready ? EXP_DRAIN : DONE;end
          else begin if(fp_result[30:0]>amax[30:0])amax<={1'b0,fp_result[30:0]};index<=index+1;state<=FETCH;end
        end
        TREE_A:if(width==1)state<=DONE;else state<=TREE_A_WAIT;
        TREE_A_WAIT:begin left_value<=value_q;state<=TREE_B;end
        TREE_B:state<=TREE_B_WAIT;
        TREE_B_WAIT:begin right_value<=value_q;state<=TREE_OP;end
        TREE_OP:if(operation==6)begin tree_result<=greater(left_value,right_value) ? left_value : right_value;state<=TREE_WRITE;end
          else if(fp_ready)state<=TREE_WAIT;
        TREE_WAIT:if(fp_valid)begin
          if(fp_result[30:23]==255)begin error<=1;state<=operation==0&&!ex_ready ? EXP_DRAIN : DONE;end
          else begin tree_result<=fp_result;state<=TREE_WRITE;end
        end
        TREE_WRITE:if(pair_index+1>=width>>1)begin width<=width>>1;pair_index<=0;state<=TREE_A;end
          else begin pair_index<=pair_index+1;state<=TREE_A;end
        FINISH:begin index<=0;state<=do_quant ? SCALE : DONE;end
        SCALE:if(amax==0)begin scale<=0;index<=0;state<=QFETCH;end else if(dv_ready)state<=SCALE_WAIT;
        SCALE_WAIT:if(dv_valid)begin scale<=dv_result<32'h00800000 ? 32'h00800000 : dv_result;index<=0;state<=QFETCH;end
        QFETCH:if(index==64)state<=DONE;else state<=QWAIT;
        QWAIT:state<=QUANT;
        QUANT:if(index>=n||scale==0)begin integers[index[5:0]]<=0;index<=index+1;state<=QFETCH;end else if(dv_ready)state<=QUANT_WAIT;
        QUANT_WAIT:if(dv_valid)begin
          quotient<=dv_result;round_magnitude<=magnitude;
          round_half<=half_bit;round_sticky<=sticky;state<=ROUND;
        end
        ROUND:begin integers[index[5:0]]<=quotient[31] ? 8'(-rounded_integer) : rounded_integer[7:0];index<=index+1;state<=QFETCH;end
        N_DIV:if(dv_ready)state<=N_DIV_WAIT;
        N_DIV_WAIT:if(dv_valid)begin product<=dv_result;state<=N_ADD;end
        N_ADD:if(fp_ready)state<=N_ADD_WAIT;
        N_ADD_WAIT:if(fp_valid)begin product<=fp_result;state<=N_SQRT;end
        N_SQRT:if(sq_ready)state<=N_SQRT_WAIT;
        N_SQRT_WAIT:if(sq_valid)begin product<=sq_result;state<=N_RECIP;end
        N_RECIP:if(dv_ready)state<=N_RECIP_WAIT;
        N_RECIP_WAIT:if(dv_valid)begin product<=dv_result;state<=N_WRITE;end
        N_WRITE:begin error<=product[30:23]==255;state<=DONE;end
        EXP_DRAIN:if(ex_ready)begin ahead_started<=0;ahead_valid<=0;state<=DONE;end
        DONE:if(ack)state<=IDLE;
        default:state<=IDLE;
      endcase
    end
  end
  // Field-local original IDLE/start clear and active-cycle increment.
  always @(posedge clk or negedge reset_n)begin
    if(!reset_n)cycles<=0;
    else if(state==IDLE&&start)cycles<=0;
    else if(state!=IDLE&&state!=DONE)cycles<=cycles+1;
  end
endmodule
