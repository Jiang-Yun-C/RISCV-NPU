// E0 streaming G64 dot. System reset discards local work; DMA reset/drain is
// intentionally outside this arithmetic-only component's qualification.
module nx_ce64_dot16 #(parameter bit PIPE_PRODUCTS=1, LATE_W_GATE=0, DUAL_W_PRODUCTS=0) (
  input logic clock,reset_n,req_valid_i,
  output logic req_ready_o,
  input logic [127:0] aq_i,wq_i,
  // Optional equivalent ungated W operand. wq_i remains the diagnostic
  // operand. When enabled it equals gate ? selected_raw_W : 0, where
  // selected_raw_W is raw_i, or bank ? raw_other_i : raw_i in dual mode.
  input logic [127:0] wq_raw_i,
  input logic wq_raw_valid_i,
  input logic [127:0] wq_raw_other_i,
  input logic wq_raw_bank_i,
  input logic [15:0] keep_i,
  input logic first_i,last_i,
  input logic [31:0] tag_i,epoch_i,
  output logic rsp_valid_o,
  input logic rsp_ready_i,
  output logic signed [31:0] dot_o,
  output logic [31:0] tag_o,epoch_o,
  output logic bad_q_o,protocol_error_o,nonzero_a_o,nonzero_w_o
);
  logic signed [15:0] raw_product[0:15],product[0:15];
  wire signed [15:0] raw_bank0_product[0:15],raw_bank1_product[0:15];
  wire signed [15:0] raw_zero_product[0:15];
  logic signed [16:0] sum1[0:7];
  logic signed [17:0] sum2[0:3];
  logic signed [18:0] sum3[0:1];
  logic signed [19:0] beat_sum;
  logic [4:0] raw_count,cnt;
  logic raw_bad,raw_a,raw_w,bad,na,nw,first,last,beat_valid,beat_ready;
  logic [15:0] keep;
  logic [31:0] tag,epoch;
  wire [4:0] count_chain [0:16];
  logic bad_chain [0:16], a_chain [0:16], w_chain [0:16];
  logic raw_w_bad_chain [0:16], unknown_w_bad_chain [0:16], unknown_w_chain [0:16];
  assign count_chain[0]=0;
  assign bad_chain[0]=0;
  assign a_chain[0]=0;
  assign w_chain[0]=0;
  assign raw_w_bad_chain[0]=0;
  assign unknown_w_bad_chain[0]=0;
  assign unknown_w_chain[0]=0;
  for(genvar i=0;i<16;i=i+1) begin: raw_prefix
    assign count_chain[i+1]=count_chain[i]+{4'b0,keep_i[i]};
    if(LATE_W_GATE)begin: late_w_diagnostic
      wire [7:0] selected_w=DUAL_W_PRODUCTS ?
        (wq_raw_bank_i ? wq_raw_other_i[8*i+:8] : wq_raw_i[8*i+:8]) : wq_raw_i[8*i+:8];
      // An unknown authorization merges each raw bit with zero. Preserve
      // that precise four-state operand for the otherwise unreachable case.
      wire [7:0] unknown_w=1'bx ? selected_w : 8'b0;
      always_comb begin
        if(keep_i[i])begin
          bad_chain[i+1]=bad_chain[i] || aq_i[8*i+:8]==8'h80;
          a_chain[i+1]=a_chain[i] || aq_i[8*i+:8]!=0;
          w_chain[i+1]=w_chain[i] || selected_w!=0;
          raw_w_bad_chain[i+1]=raw_w_bad_chain[i] || selected_w==8'h80;
          unknown_w_bad_chain[i+1]=unknown_w_bad_chain[i] || unknown_w==8'h80;
          unknown_w_chain[i+1]=unknown_w_chain[i] || unknown_w!=0;
        end else begin
          bad_chain[i+1]=bad_chain[i];a_chain[i+1]=a_chain[i];w_chain[i+1]=w_chain[i];
          raw_w_bad_chain[i+1]=raw_w_bad_chain[i];
          unknown_w_bad_chain[i+1]=unknown_w_bad_chain[i];unknown_w_chain[i+1]=unknown_w_chain[i];
        end
      end
    end else begin: original_w_diagnostic
    always_comb begin
      if(keep_i[i]) begin
        bad_chain[i+1]=bad_chain[i] || aq_i[8*i+:8]==8'h80 || wq_i[8*i+:8]==8'h80;
        a_chain[i+1]=a_chain[i] || aq_i[8*i+:8]!=0;
        w_chain[i+1]=w_chain[i] || wq_i[8*i+:8]!=0;
      end else begin
        bad_chain[i+1]=bad_chain[i];
        a_chain[i+1]=a_chain[i];
        w_chain[i+1]=w_chain[i];
      end
    end
    assign raw_w_bad_chain[i+1]=0;
    assign unknown_w_bad_chain[i+1]=0;
    assign unknown_w_chain[i+1]=0;
    end
  end
  assign raw_count=count_chain[16];
  assign raw_a=a_chain[16];
  if(LATE_W_GATE)begin: late_diagnostic_gate
    // Authorization follows the lane reductions, so its high fanout and
    // identity checks do not precede the 0x80/nonzero reduction chain.
    always_comb begin
      case(wq_raw_valid_i)
        1'b0:begin raw_bad=bad_chain[16];raw_w=0;end
        1'b1:begin raw_bad=bad_chain[16] || raw_w_bad_chain[16];raw_w=w_chain[16];end
        default:begin raw_bad=bad_chain[16] || unknown_w_bad_chain[16];raw_w=unknown_w_chain[16];end
      endcase
    end
  end else begin: original_diagnostic_gate
    assign raw_bad=bad_chain[16];assign raw_w=w_chain[16];
  end
  for(genvar i=0;i<16;i=i+1) begin: lane
    wire signed [7:0] a=aq_i[8*i+:8],w=wq_i[8*i+:8];
    if(LATE_W_GATE)begin: late_w_gate
      wire signed [7:0] raw_w=wq_raw_i[8*i+:8];
      wire signed [7:0] other_w=wq_raw_other_i[8*i+:8];
      wire signed [7:0] selected_w;
      wire signed [15:0] unmasked_product;
      if(DUAL_W_PRODUCTS)begin: bank_products
        wire signed [15:0] bank0_product=a*raw_w;
        wire signed [15:0] bank1_product=a*other_w;
        assign raw_bank0_product[i]=bank0_product;
        assign raw_bank1_product[i]=bank1_product;
        logic signed [15:0] selected_product;
        assign selected_w=wq_raw_bank_i ? other_w : raw_w;
        always_comb begin
          case(wq_raw_bank_i)
            1'b0:selected_product=bank0_product;
            1'b1:selected_product=bank1_product;
            // A ternary X/Z bank merges equal operand bits. Different
            // bytes leave an unknown bit, making the old multiply all X.
            default:selected_product=(raw_w===other_w) ? bank0_product : 16'bx;
          endcase
        end
        assign unmasked_product=selected_product;
      end else begin: one_bank_product
        assign selected_w=raw_w;
        assign unmasked_product=a*raw_w;
      end
      // Keep 0*A rather than literal zero: a four-state unknown A must
      // still produce an unknown product when authorization is false.
      wire signed [15:0] zero_product=a*8'sd0;
      assign raw_zero_product[i]=zero_product;
      logic signed [15:0] gated_product;
      always_comb begin
        case(wq_raw_valid_i)
          1'b0:gated_product=zero_product;
          1'b1:gated_product=unmasked_product;
          // For an X/Z gate the old operand is (X ? raw_w : 0).
          // It is zero only when every raw W bit is known zero;
          // otherwise multiplication has the original all-X result.
          default:gated_product=(selected_w===8'b0) ? zero_product : 16'bx;
        endcase
      end
      assign raw_product[i]=keep_i[i] ? gated_product : 16'sd0;
    end else begin: original_w_gate
      assign raw_product[i]=keep_i[i] ? a*w : 16'sd0;
    end
  end
  assign beat_ready=reset_n && (!rsp_valid_o || rsp_ready_i);
  if(PIPE_PRODUCTS) begin: pipe
    assign req_ready_o=reset_n && (!beat_valid || beat_ready);
    always_ff @(posedge clock or negedge reset_n) begin
      if(!reset_n) begin
        beat_valid<=0;cnt<=0;bad<=0;na<=0;nw<=0;first<=0;last<=0;
        keep<=0;tag<=0;epoch<=0;

      end else if(req_ready_o) begin
        beat_valid<=req_valid_i;
        if(req_valid_i) begin
          cnt<=raw_count;bad<=raw_bad;na<=raw_a;nw<=raw_w;
          first<=first_i;last<=last_i;keep<=keep_i;tag<=tag_i;epoch<=epoch_i;

        end
      end
    end
    if(LATE_W_GATE && DUAL_W_PRODUCTS)begin: stored_bank_products
      logic bank_q,gate_q;
      logic signed [15:0] bank0_q[0:15],bank1_q[0:15],zero_q[0:15];
      logic [15:0] same_q,zero0_q,zero1_q;
      always_ff @(posedge clock or negedge reset_n)begin
        if(!reset_n)begin
          bank_q<=0;gate_q<=0;same_q<=0;zero0_q<=0;zero1_q<=0;
          for(integer i=0;i<16;i++)begin bank0_q[i]<=0;bank1_q[i]<=0;zero_q[i]<=0;end
        end else if(req_ready_o && req_valid_i)begin
          bank_q<=wq_raw_bank_i;gate_q<=wq_raw_valid_i;
          for(integer i=0;i<16;i++)begin
            bank0_q[i]<=raw_bank0_product[i];bank1_q[i]<=raw_bank1_product[i];zero_q[i]<=raw_zero_product[i];
            same_q[i]<=(wq_raw_i[8*i+:8]===wq_raw_other_i[8*i+:8]);
            zero0_q[i]<=(wq_raw_i[8*i+:8]===8'b0);zero1_q[i]<=(wq_raw_other_i[8*i+:8]===8'b0);
          end
        end
      end
      for(genvar i=0;i<16;i++)begin: select_registered_product
        logic signed [15:0] selected_product,gated_product;
        logic selected_zero;
        always_comb begin
          case(bank_q)
            1'b0:begin selected_product=bank0_q[i];selected_zero=zero0_q[i];end
            1'b1:begin selected_product=bank1_q[i];selected_zero=zero1_q[i];end
            default:begin selected_product=same_q[i] ? bank0_q[i] : 16'bx;selected_zero=zero0_q[i]&&zero1_q[i];end
          endcase
          case(gate_q)
            1'b0:gated_product=zero_q[i];
            1'b1:gated_product=selected_product;
            default:gated_product=selected_zero ? zero_q[i] : 16'bx;
          endcase
        end
        assign product[i]=keep[i] ? gated_product : 16'sd0;
      end
    end else begin: original_product_registers
      always_ff @(posedge clock or negedge reset_n)begin
        if(!reset_n)for(integer i=0;i<16;i++)product[i]<=0;
        else if(req_ready_o && req_valid_i)for(integer i=0;i<16;i++)product[i]<=raw_product[i];
      end
    end
  end else begin: direct
    assign req_ready_o=beat_ready;
    assign beat_valid=req_valid_i;
    assign cnt=raw_count;assign bad=raw_bad;assign na=raw_a;assign nw=raw_w;
    assign first=first_i;assign last=last_i;assign keep=keep_i;
    assign tag=tag_i;assign epoch=epoch_i;
    for(genvar i=0;i<16;i=i+1) assign product[i]=raw_product[i];
  end
  for(genvar i=0;i<8;i=i+1) begin
    assign sum1[i]=$signed({product[2*i][15],product[2*i]})+
                   $signed({product[2*i+1][15],product[2*i+1]});
  end
  for(genvar i=0;i<4;i=i+1) begin
    assign sum2[i]=$signed({sum1[2*i][16],sum1[2*i]})+
                   $signed({sum1[2*i+1][16],sum1[2*i+1]});
  end
  for(genvar i=0;i<2;i=i+1) begin
    assign sum3[i]=$signed({sum2[2*i][17],sum2[2*i]})+
                   $signed({sum2[2*i+1][17],sum2[2*i+1]});
  end
  assign beat_sum=$signed({sum3[0][18],sum3[0]})+$signed({sum3[1][18],sum3[1]});
  logic active_r,bad_r,proto_r,na_r,nw_r;
  logic signed [31:0] acc_r,group_sum;
  logic [31:0] tag_r,epoch_r;
  logic [6:0] count_r,count_next;
  logic [2:0] beats_r,beats_next;
  logic bad_next,proto_next;
  always_comb begin
    count_next=(first ? 7'd0 : count_r)+{2'b0,cnt};
    beats_next=(first ? 3'd0 : beats_r)+3'd1;
    bad_next=(first ? 1'b0 : bad_r)|bad;
    proto_next=first ? active_r : (proto_r|!active_r);
    if(!first && (tag!=tag_r || epoch!=epoch_r)) proto_next=1;
    if(!last && keep!=16'hffff) proto_next=1;
    if(last && (keep==0 || (keep & (keep+16'd1))!=0)) proto_next=1;
    if(beats_next>4 || count_next>64 || (beats_next==4 && !last)) proto_next=1;
    group_sum=(first ? 32'sd0 : acc_r)+$signed({{12{beat_sum[19]}},beat_sum});
  end
  always_ff @(posedge clock or negedge reset_n) begin
    if(!reset_n) begin
      active_r<=0;bad_r<=0;proto_r<=0;na_r<=0;nw_r<=0;acc_r<=0;
      tag_r<=0;epoch_r<=0;count_r<=0;beats_r<=0;
      rsp_valid_o<=0;dot_o<=0;tag_o<=0;epoch_o<=0;
      bad_q_o<=0;protocol_error_o<=0;nonzero_a_o<=0;nonzero_w_o<=0;
    end else begin
      if(beat_valid && beat_ready && last) rsp_valid_o<=1;
      else if(rsp_valid_o && rsp_ready_i) rsp_valid_o<=0;
      if(beat_valid && beat_ready) begin
        active_r<=!last;acc_r<=group_sum;count_r<=count_next;beats_r<=beats_next;
        bad_r<=bad_next;proto_r<=proto_next;
        na_r<=(first ? 1'b0 : na_r)|na;nw_r<=(first ? 1'b0 : nw_r)|nw;
        if(first) begin tag_r<=tag;epoch_r<=epoch;end
        if(last) begin
          dot_o<=group_sum;tag_o<=first ? tag : tag_r;
          epoch_o<=first ? epoch : epoch_r;bad_q_o<=bad_next;protocol_error_o<=proto_next;
          nonzero_a_o<=(first ? 1'b0 : na_r)|na;
          nonzero_w_o<=(first ? 1'b0 : nw_r)|nw;
        end
      end
    end
  end
endmodule
