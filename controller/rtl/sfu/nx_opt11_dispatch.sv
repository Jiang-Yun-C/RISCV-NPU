module nx_opt11_dispatch #(parameter integer LANES=2,parameter bit SCRATCH_PREDICATES=0,parameter bit SCRATCH_SCALE_PREDICATES=0,parameter bit DEADLINE_CACHE=0,CROSS_GROUP_WRITE=1,AQSA_RESIDENT=1,W_PREFETCH=1,A_W_BANKED=1,AQSA_GROUP_HANDOFF=0,LONG_PV=0) (
  input logic clk, platform_reset_n, submit, reset_grant, stop_new, abort_publish,
  input wire resident_revoke,
  input wire scratch_b_en,
  input wire [11:0] scratch_b_address,
  input wire [15:0] scratch_b_mask,
  input logic startup_authorized,
  output logic [31:0] startup_status,
  input logic [1023:0] descriptor,
  input logic [31:0] epoch, generation, first_fault_address,
  input logic [63:0] run_limit,run_limit_next,
  input logic transport_drained, native_quarantined,
  output logic engine_idle, arithmetic_idle, scratch_idle, timeout_fault, call_fault,
  output logic [1279:0] completion,
  output logic completion_valid,
  input logic completion_ready,
  output logic [511:0] perf,
  input logic dma_ready,dma_result_valid,dma_idle,
  input logic [1:0] dma_resp,
  output logic dma_valid,dma_write,dma_result_ready,
  output logic [31:0] dma_address,
  output logic [2:0] dma_size,
  output logic [4:0] dma_len,
  output logic [15:0] dma_scratch,
  output logic [127:0] dma_data,
  output logic [15:0] dma_mask,
  output logic ram_en,
  output logic [11:0] ram_address,
  output logic [15:0] ram_mask,
  output logic [127:0] ram_data,
  output logic dma_w_capture,
  output logic dma_sw_capture,
  output logic dma_capture_bank,
  output logic capture_revoke,
  output logic [127:0] capture_owner,
  output logic [63:0] capture_command_tag,
  output logic [255:0] capture_command_scales,
  output logic [1:0] capture_release,
  output logic capture_peek_bank,
  output logic [4:0] capture_peek_beat,
  output logic [63:0] capture_peek_tag,
  input logic [127:0] capture_data,
  input logic [127:0] capture_raw_data,
  output wire [9:0] capture_raw_beats,
  input logic [255:0] capture_raw_banks,
  input logic [15:0] capture_mask,
  input logic [1:0] capture_held,
  input logic [1:0] capture_certificate,
  input logic [1:0] capture_bad,
  input logic [1:0] capture_result_seen,
  input logic [11:0] capture_counts,
  input logic capture_physical_idle,
  input logic capture_r_take,
  input logic [127:0] capture_r_data,
  input logic [5:0] capture_r_id,
  input logic [1:0] capture_r_resp,
  input logic capture_r_last,
  output wire p_window_en,
  output wire [8:0] p_window_address,
  input wire [31:0] p_window_q,p_window_epoch,p_window_words,p_window_len,p_window_padded,
  input wire [63:0] p_window_session,p_window_sequence,
  input wire p_window_valid,
  input logic [127:0] ram_q,
  input wire [15:0] ram_min80_q,ram_nonzero_q,
  input wire [15:0] ram_scale_zero_q,ram_scale_lo0_q,ram_scale_lo1_q
);

  reg vector_selected,startup_selected,pv_selected;
  wire sf_start,sf_mul,pv_start,pv_mul,fp_ready,fp_valid;
  reg fp_pending;
  wire fp_available=fp_ready&&!fp_pending;
  always @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)fp_pending<=0;
    else if(fp_valid)fp_pending<=0;
    else if(pv_selected ? pv_start : sf_start)fp_pending<=1;
  end
  wire [31:0] sf_a,sf_b,pv_a,pv_b,fp_result;
  nx_opt11_fp shared_main_fp(.clk,.reset_n(platform_reset_n),
    .start(pv_selected ? pv_start : sf_start),.multiply(pv_selected ? pv_mul : sf_mul),
    .a(pv_selected ? pv_a : sf_a),.b(pv_selected ? pv_b : sf_b),
    .ready(fp_ready),.valid(fp_valid),.result(fp_result));

  wire  startup_engine_idle;
  wire  startup_arithmetic_idle;
  wire  startup_scratch_idle;
  wire  startup_timeout_fault;
  wire  startup_call_fault;
  wire [1279:0] startup_completion;
  wire  startup_completion_valid;
  wire [511:0] startup_perf;
  wire  startup_dma_valid;
  wire  startup_dma_write;
  wire  startup_dma_result_ready;
  wire [31:0] startup_dma_address;
  wire [2:0] startup_dma_size;
  wire [4:0] startup_dma_len;
  wire [15:0] startup_dma_scratch;
  wire [127:0] startup_dma_data;
  wire [15:0] startup_dma_mask;
  wire  startup_ram_en;
  wire [11:0] startup_ram_address;
  wire [15:0] startup_ram_mask;
  wire [127:0] startup_ram_data;

  always @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)begin vector_selected<=0;startup_selected<=0;pv_selected<=0;end
    else if(submit)begin pv_selected<=descriptor[14*32+:32]==5;vector_selected<=descriptor[14*32+:32]==3;startup_selected<=descriptor[14*32+:32]==4;end
  end
  wire  linear_engine_idle,vector_engine_idle;
  wire  pv_engine_idle;
  assign engine_idle=pv_selected ? pv_engine_idle : startup_selected ? startup_engine_idle : vector_selected ? vector_engine_idle : linear_engine_idle;
  wire  linear_arithmetic_idle,vector_arithmetic_idle;
  wire  pv_arithmetic_idle;
  assign arithmetic_idle=!fp_pending&&(pv_selected ? pv_arithmetic_idle : startup_selected ? startup_arithmetic_idle : vector_selected ? vector_arithmetic_idle : linear_arithmetic_idle);
  wire  linear_scratch_idle,vector_scratch_idle;
  wire  pv_scratch_idle;
  assign scratch_idle=pv_selected ? pv_scratch_idle : startup_selected ? startup_scratch_idle : vector_selected ? vector_scratch_idle : linear_scratch_idle;
  wire  linear_timeout_fault,vector_timeout_fault;
  wire  pv_timeout_fault;
  assign timeout_fault=pv_selected ? pv_timeout_fault : startup_selected ? startup_timeout_fault : vector_selected ? vector_timeout_fault : linear_timeout_fault;
  wire  linear_call_fault,vector_call_fault;
  wire  pv_call_fault;
  assign call_fault=pv_selected ? pv_call_fault : startup_selected ? startup_call_fault : vector_selected ? vector_call_fault : linear_call_fault;
  wire  [1279:0] linear_completion,vector_completion;
  wire [1279:0] pv_completion;
  assign completion=pv_selected ? pv_completion : startup_selected ? startup_completion : vector_selected ? vector_completion : linear_completion;
  wire  linear_completion_valid,vector_completion_valid;
  wire linear_publication_phase;
  wire  pv_completion_valid;
  assign completion_valid=pv_selected ? pv_completion_valid : startup_selected ? startup_completion_valid : vector_selected ? vector_completion_valid : linear_completion_valid;
  wire  [511:0] linear_perf,vector_perf;
  wire [511:0] pv_perf;
  assign perf=pv_selected ? pv_perf : startup_selected ? startup_perf : vector_selected ? vector_perf : linear_perf;
  wire  linear_dma_valid,vector_dma_valid;
  wire  pv_dma_valid;
  assign dma_valid=pv_selected ? pv_dma_valid : startup_selected ? startup_dma_valid : vector_selected ? vector_dma_valid : linear_dma_valid;
  wire  linear_dma_write,vector_dma_write;
  wire  pv_dma_write;
  assign dma_write=pv_selected ? pv_dma_write : startup_selected ? startup_dma_write : vector_selected ? vector_dma_write : linear_dma_write;
  wire  linear_dma_result_ready,vector_dma_result_ready;
  wire  pv_dma_result_ready;
  assign dma_result_ready=pv_selected ? pv_dma_result_ready : startup_selected ? startup_dma_result_ready : vector_selected ? vector_dma_result_ready : linear_dma_result_ready;
  wire  [31:0] linear_dma_address,vector_dma_address;
  wire [31:0] pv_dma_address;
  assign dma_address=pv_selected ? pv_dma_address : startup_selected ? startup_dma_address : vector_selected ? vector_dma_address : linear_dma_address;
  wire  [2:0] linear_dma_size,vector_dma_size;
  wire [2:0] pv_dma_size;
  assign dma_size=pv_selected ? pv_dma_size : startup_selected ? startup_dma_size : vector_selected ? vector_dma_size : linear_dma_size;
  wire  [4:0] linear_dma_len,vector_dma_len;
  wire [4:0] pv_dma_len;
  assign dma_len=pv_selected ? pv_dma_len : startup_selected ? startup_dma_len : vector_selected ? vector_dma_len : linear_dma_len;
  wire  [15:0] linear_dma_scratch,vector_dma_scratch;
  wire [15:0] pv_dma_scratch;
  assign dma_scratch=pv_selected ? pv_dma_scratch : startup_selected ? startup_dma_scratch : vector_selected ? vector_dma_scratch : linear_dma_scratch;
  wire  [127:0] linear_dma_data,vector_dma_data;
  wire [127:0] pv_dma_data;
  assign dma_data=pv_selected ? pv_dma_data : startup_selected ? startup_dma_data : vector_selected ? vector_dma_data : linear_dma_data;
  wire  [15:0] linear_dma_mask,vector_dma_mask;
  wire [15:0] pv_dma_mask;
  assign dma_mask=pv_selected ? pv_dma_mask : startup_selected ? startup_dma_mask : vector_selected ? vector_dma_mask : linear_dma_mask;
  wire  linear_ram_en,vector_ram_en;
  wire  pv_ram_en;
  wire pv_resident_write;
  assign ram_en=pv_selected ? pv_ram_en : startup_selected ? startup_ram_en : vector_selected ? vector_ram_en : linear_ram_en;
  wire  [11:0] linear_ram_address,vector_ram_address;
  wire [11:0] pv_ram_address;
  assign ram_address=pv_selected ? pv_ram_address : startup_selected ? startup_ram_address : vector_selected ? vector_ram_address : linear_ram_address;
  wire  [15:0] linear_ram_mask,vector_ram_mask;
  wire [15:0] pv_ram_mask;
  assign ram_mask=pv_selected ? pv_ram_mask : startup_selected ? startup_ram_mask : vector_selected ? vector_ram_mask : linear_ram_mask;
  wire  [127:0] linear_ram_data,vector_ram_data;
  wire [127:0] pv_ram_data;
  assign ram_data=pv_selected ? pv_ram_data : startup_selected ? startup_ram_data : vector_selected ? vector_ram_data : linear_ram_data;
  // One-shot private Aq/Sa residency. Data remains in the original scratch;
  // these registers bind completed rows, never substitute for numeric checks.
  wire [31:0] resident_d[0:31];
  generate for(genvar ri=0;ri<32;ri++)begin:resident_descriptor_words
    assign resident_d[ri]=descriptor[ri*32+:32];
  end endgenerate
  // Exact 64-bit + tiny unsigned displacement, with a retained bit64.
  // Parallel byte carries keep the sequence-overflow/identity checks from
  // starting a full-width ripple chain in the one-shot authority decision.
  function automatic [64:0] resident_add_small(input logic [63:0] base,input logic [2:0] amount);
    logic [8:0] low;
    logic carry;
    begin
      case({^base,^amount})
        2'b00,2'b01,2'b10,2'b11:begin
          low={1'b0,base[7:0]}+{6'b0,amount};
          resident_add_small[7:0]=low[7:0];
          for(integer b=1;b<8;b++)begin
            carry=low[8];
            for(integer j=1;j<b;j++)carry=carry&&(&base[8*j+:8]);
            resident_add_small[8*b+:8]=base[8*b+:8]+8'(carry);
          end
          carry=low[8];
          for(integer j=1;j<8;j++)carry=carry&&(&base[8*j+:8]);
          resident_add_small[64]=carry;
        end
        default:resident_add_small={1'b0,base}+65'(amount);
      endcase
    end
  endfunction
  wire [1:0] offered_resident_row=resident_d[27][1:0];
  wire [2:0] offered_resident_rows={1'b0,resident_d[27][3:2]}+3'd1;
  wire [63:0] offered_resident_first={resident_d[30],resident_d[29]};
  wire [63:0] offered_resident_sequence={resident_d[13],resident_d[12]};
  wire [63:0] offered_resident_session={resident_d[11],resident_d[10]};
  wire [64:0] offered_resident_last=resident_add_small(offered_resident_first,offered_resident_rows);
  wire [32:0] offered_resident_aq={1'b0,resident_d[22]}-33'(offered_resident_row)*33'd4864;
  wire [32:0] offered_resident_sa={1'b0,resident_d[23]}-33'(offered_resident_row)*33'd304;
  wire [32:0] offered_resident_fp={1'b0,resident_d[31]}+33'(offered_resident_row)*33'd19456;
  wire resident_header=resident_d[0]==32'h34364543&&resident_d[1]==1&&resident_d[2]==128&&
    resident_d[3]==0&&resident_d[4]==epoch&&epoch!=0&&resident_d[5]==1&&
    resident_d[6]==0&&resident_d[7]==0&&resident_d[8]==32'h4c4e3135&&resident_d[9]==96&&
    offered_resident_session!=0&&offered_resident_first!=0&&!offered_resident_last[64]&&
    resident_d[25]==0&&resident_d[26]==0&&resident_d[28]==0;
  wire resident_fp_arena=resident_d[31][3:0]==0&&resident_d[31]>=32'hac000000&&
    ({1'b0,resident_d[31]}+33'(offered_resident_rows)*33'd19456)<=33'h0b4000000;
  wire resident_producer_shape=resident_header&&resident_fp_arena&&
    (resident_d[27]&32'hfffffff0)==32'ha3510000&&
    offered_resident_row<offered_resident_rows&&resident_d[14]==3&&
    resident_d[15]==1&&resident_d[16]==1&&resident_d[17]==4864&&resident_d[24]==0&&resident_d[21]==0&&
    {1'b0,resident_d[19]}==offered_resident_fp&&
    offered_resident_sequence==64'(resident_add_small(offered_resident_first,{1'b0,offered_resident_row}))&&
    !offered_resident_aq[32]&&!offered_resident_sa[32]&&
    offered_resident_aq[3:0]==0&&offered_resident_sa[3:0]==0&&
    offered_resident_aq>=33'h0ba000000&&offered_resident_sa>=33'h0ba000000&&
    offered_resident_aq+33'(offered_resident_rows)*33'd4864<=33'h0bc000000&&
    offered_resident_sa+33'(offered_resident_rows)*33'd304<=33'h0bc000000&&
    (offered_resident_aq+33'(offered_resident_rows)*33'd4864<=offered_resident_sa||
     offered_resident_sa+33'(offered_resident_rows)*33'd304<=offered_resident_aq);
  reg resident_live,resident_pending;
  reg [31:0] resident_epoch,resident_fp_base,resident_aq_base,resident_sa_base;
  reg [31:0] resident_pending_generation;
  reg [63:0] resident_session,resident_first;
  reg [2:0] resident_rows,resident_completed;
  reg [1:0] resident_pending_row;
  reg resident_vector_authorized,resident_linear_authorized;
  reg [1:0] resident_vector_row;
  // Keep the two actual late64-bit session equalities as exact byte trees.
  // No authority sample or completion/revoke decision is registered/delayed.
  (* keep=1, syn_keep=1 *) wire [7:0] resident_session_match_bytes;
  (* keep=1, syn_keep=1 *) wire [7:0] resident_retired_session_match_bytes;
  generate for(genvar rsb=0;rsb<8;rsb++)begin:resident_session_compare
    assign resident_session_match_bytes[rsb]=resident_session[8*rsb+:8]==offered_resident_session[8*rsb+:8];
    assign resident_retired_session_match_bytes[rsb]=vector_completion[10*32+8*rsb+:8]==resident_session[8*rsb+:8];
  end endgenerate
  wire resident_identity=resident_live&&resident_epoch==epoch&&(&resident_session_match_bytes)&&
    resident_first==offered_resident_first&&resident_rows==offered_resident_rows&&
    resident_fp_base==resident_d[31];
  wire resident_producer_match=resident_identity&&!resident_pending&&
    resident_completed=={1'b0,offered_resident_row}&&
    resident_aq_base==offered_resident_aq[31:0]&&resident_sa_base==offered_resident_sa[31:0];
  wire resident_producer_authorize=AQSA_RESIDENT&&!resident_revoke&&!reset_grant&&!abort_publish&&
    !native_quarantined&&resident_producer_shape&&
    !(AQSA_GROUP_HANDOFF&&(aqsa_foreign_write||scratch_b_en))&&
    (offered_resident_row==0||resident_producer_match);
  wire resident_consumer_shape=resident_header&&resident_fp_arena&&
    (resident_d[27]&32'hfffffff0)==32'ha3520000&&offered_resident_row==0&&
    resident_d[14]==2&&resident_d[15]==32'(offered_resident_rows)&&resident_d[17]==4864&&
    offered_resident_sequence==offered_resident_last[63:0];
  // Group certificates are derived from the actual single physical write
  // edges, not SFU result metadata. Four complete ordered Aq beats precede
  // the commit-last Sa word. The existing resident identity owns all groups;
  // no per-group payload, second scratch port or CE accumulator is added.
  reg [6:0] aqsa_group_count;
  reg [2:0] aqsa_beat_count;
  reg aqsa_bad,aqsa_nonzero,aqsa_min80,aqsa_consumer_live;
  wire [15:0] aqsa_row_a=16'(resident_pending_row)*16'd4864;
  wire [15:0] aqsa_row_s=16'h5000+16'(resident_pending_row)*16'd304;
  wire [15:0] aqsa_expected_a=aqsa_row_a+{3'b0,aqsa_group_count,6'b0}+16'(aqsa_beat_count)*16'd16;
  wire [15:0] aqsa_expected_s=aqsa_row_s+16'(aqsa_group_count)*16'd4;
  wire [15:0] aqsa_s_mask=16'h000f<<(aqsa_expected_s[3:0]);
  wire [31:0] aqsa_scale=vector_ram_data[aqsa_expected_s[3:0]*8+:32];
  wire aqsa_scale_legal=(aqsa_scale==0)||(!aqsa_scale[31]&&aqsa_scale[30:23]!=0&&aqsa_scale[30:23]!=255);
  wire aqsa_a_region=vector_ram_address<12'h4c0;
  wire aqsa_s_region=vector_ram_address>=12'h500&&vector_ram_address<12'h54c;
  wire aqsa_b_region=scratch_b_address<12'h4c0||(scratch_b_address>=12'h500&&scratch_b_address<12'h54c);
  wire aqsa_write=vector_selected&&vector_ram_en&&(|vector_ram_mask)&&(aqsa_a_region||aqsa_s_region);
  wire aqsa_beat=aqsa_write&&aqsa_a_region;
  wire aqsa_commit=aqsa_write&&aqsa_s_region;
  wire aqsa_context=resident_live&&resident_pending&&resident_vector_authorized&&
    generation==resident_pending_generation&&epoch==resident_epoch&&!stop_new&&!abort_publish&&
    !reset_grant&&!resident_revoke&&!native_quarantined&&!scratch_b_en;
  wire aqsa_beat_ok=aqsa_context&&aqsa_group_count<76&&aqsa_beat_count<4&&
    vector_ram_address==aqsa_expected_a[15:4]&&vector_ram_mask==16'hffff;
  wire aqsa_commit_ok=aqsa_context&&aqsa_group_count<76&&aqsa_beat_count==4&&
    vector_ram_address==aqsa_expected_s[15:4]&&vector_ram_mask==aqsa_s_mask&&
    aqsa_scale_legal&&!aqsa_min80&&(!(aqsa_scale==0)||!aqsa_nonzero);
  wire aqsa_group_publish=AQSA_GROUP_HANDOFF&&aqsa_commit&&aqsa_commit_ok&&!aqsa_bad;
  wire aqsa_row_check;
  wire aqsa_producer_fault=AQSA_GROUP_HANDOFF&&resident_pending&&
    (aqsa_bad||aqsa_foreign_write||(aqsa_row_check&&(aqsa_group_count!=76||aqsa_beat_count!=0)));
  // Evaluate each physical write region before selecting its one-bit result.
  // Late vector address arithmetic must not enter a non-vector consumer fault.
  // Preserve the original mux X/Z merging when any selector is unknown.
  wire aqsa_pv_write=pv_resident_write;
  wire aqsa_startup_write=(|startup_ram_mask)&&(startup_ram_address<12'h4c0||
    (startup_ram_address>=12'h500&&startup_ram_address<12'h54c));
  wire aqsa_linear_write=(|linear_ram_mask)&&(linear_ram_address<12'h4c0||
    (linear_ram_address>=12'h500&&linear_ram_address<12'h54c));
  logic aqsa_other_write;
  always_comb begin
    case(^{pv_selected,startup_selected,vector_selected})
      1'b0,1'b1:aqsa_other_write=!vector_selected&&
        (pv_selected ? aqsa_pv_write : startup_selected ? aqsa_startup_write : aqsa_linear_write);
      default:aqsa_other_write=!vector_selected&&(|ram_mask)&&
        (ram_address<12'h4c0||(ram_address>=12'h500&&ram_address<12'h54c));
    endcase
  end
  wire aqsa_foreign_write=(aqsa_write&&!resident_pending)||(scratch_b_en&&(|scratch_b_mask)&&aqsa_b_region)||aqsa_other_write;
  // The payload lifetime extends through every accepted arithmetic operation.
  // A drained controller completion proves the last-use endpoint; completion
  // bank/CPU ACK may follow later without needing the scratch operand bytes.
  wire aqsa_consumer_fault=AQSA_GROUP_HANDOFF&&aqsa_consumer_live&&!linear_publication_phase&&
    (aqsa_bad||aqsa_foreign_write);
  wire aqsa_group_complete=!AQSA_GROUP_HANDOFF||(!aqsa_bad&&aqsa_group_count==76&&aqsa_beat_count==0);
  always @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)begin
      aqsa_group_count<=0;aqsa_beat_count<=0;aqsa_bad<=0;aqsa_nonzero<=0;aqsa_min80<=0;aqsa_consumer_live<=0;
    end else if(reset_grant||resident_revoke||abort_publish||native_quarantined||
      (resident_live&&resident_epoch!=epoch)||(stop_new&&!engine_idle))begin
      aqsa_group_count<=0;aqsa_beat_count<=0;aqsa_bad<=1;aqsa_nonzero<=0;aqsa_min80<=0;aqsa_consumer_live<=0;
    end else if(submit)begin
      aqsa_consumer_live<=resident_consumer_authorize;
      if(resident_producer_authorize)begin
        aqsa_group_count<=0;aqsa_beat_count<=0;aqsa_nonzero<=0;aqsa_min80<=0;
        if(offered_resident_row==0)aqsa_bad<=0;
      end else if(!resident_consumer_authorize)begin
        aqsa_group_count<=0;aqsa_beat_count<=0;aqsa_bad<=1;
      end
    end else begin
      if(aqsa_consumer_live&&linear_completion_valid&&linear_arithmetic_idle&&dma_idle&&transport_drained)aqsa_consumer_live<=0;
      if(AQSA_GROUP_HANDOFF&&(resident_live||aqsa_consumer_live)&&aqsa_foreign_write)aqsa_bad<=1;
      if(AQSA_GROUP_HANDOFF&&resident_pending&&aqsa_write)begin
        if(aqsa_beat)begin
          if(!aqsa_beat_ok)aqsa_bad<=1;
          else begin
            aqsa_beat_count<=aqsa_beat_count+1'b1;
            for(integer ab=0;ab<16;ab++)begin
              if(vector_ram_data[8*ab+:8]==8'h80)aqsa_min80<=1;
              if(vector_ram_data[8*ab+:8]!=0)aqsa_nonzero<=1;
            end
          end
        end else if(!aqsa_commit_ok)aqsa_bad<=1;
        else begin aqsa_group_count<=aqsa_group_count+1'b1;aqsa_beat_count<=0;aqsa_min80<=0;aqsa_nonzero<=0;end
      end
    end
  end
  wire resident_consumer_authorize=AQSA_RESIDENT&&!resident_revoke&&!reset_grant&&!abort_publish&&
    !native_quarantined&&resident_consumer_shape&&resident_identity&&!resident_pending&&
    resident_completed==resident_rows&&aqsa_group_complete&&!(AQSA_GROUP_HANDOFF&&aqsa_foreign_write)&&resident_d[22]==resident_aq_base&&resident_d[23]==resident_sa_base;
  wire resident_vector_input=submit ? resident_producer_authorize : resident_vector_authorized;
  wire resident_linear_input=submit ? resident_consumer_authorize : resident_linear_authorized;
  wire [1:0] resident_row_input=submit ? offered_resident_row : resident_vector_row;
  wire resident_producer_retired=resident_pending&&vector_selected&&vector_completion_valid&&completion_ready;
  wire resident_producer_success=vector_completion[14*32+:32]==0&&vector_completion[15*32+:32]==1&&
    vector_completion[3*32+:32]==resident_epoch&&
    (&resident_retired_session_match_bytes)&&
    vector_completion[12*32+:64]==64'(resident_add_small(resident_first,{1'b0,resident_pending_row}))&&
    vector_completion[38*32+:32]==resident_pending_generation&&
    dma_idle&&transport_drained&&!native_quarantined&&aqsa_group_complete;
  // Owner0 release is intentionally absent: no engine may touch scratch in
  // that interval. True isolation/unsealing comes through resident_revoke.
  always @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)begin
      resident_live<=0;resident_pending<=0;resident_completed<=0;
      resident_pending_row<=0;resident_pending_generation<=0;
      resident_vector_authorized<=0;resident_linear_authorized<=0;resident_vector_row<=0;
    end else if(resident_revoke||reset_grant||abort_publish||native_quarantined||
      (resident_live&&resident_epoch!=epoch)||(stop_new&&!engine_idle))begin
      resident_live<=0;resident_pending<=0;resident_completed<=0;
      resident_vector_authorized<=0;resident_linear_authorized<=0;
    end else if(submit)begin
      resident_vector_authorized<=resident_producer_authorize;
      resident_linear_authorized<=resident_consumer_authorize;
      resident_vector_row<=offered_resident_row;
      if(resident_producer_authorize)begin
        if(offered_resident_row==0)begin
          resident_live<=1;resident_completed<=0;
        end
        resident_pending<=1;resident_pending_row<=offered_resident_row;resident_pending_generation<=generation;
      end else begin
        // Consumer authorization is latched above before the lease is spent.
        // Every other submission also destroys any previous scratch promise.
        resident_live<=0;resident_pending<=0;resident_completed<=0;
      end
    end else if(resident_producer_retired)begin
      resident_pending<=0;
      if(resident_producer_success)resident_completed<=resident_completed+3'd1;
      else begin resident_live<=0;resident_completed<=0;end
    end
  end

  // This immutable identity tuple is private while resident_live is clear.
  // Every row-zero submit captures it before a new lease can become live.
  // Unauthorized/revoked submits still clear live/pending/authority above;
  // a consumer samples the old tuple before spending that lease on this edge.
  // Keep the control priority intact without routing its fault cone to data CE.
  always @(posedge clk)begin
    if(submit&&offered_resident_row==0)begin
      resident_rows<=offered_resident_rows;
      resident_epoch<=epoch;resident_session<=offered_resident_session;resident_first<=offered_resident_first;
      resident_fp_base<=resident_d[31];resident_aq_base<=offered_resident_aq[31:0];resident_sa_base<=offered_resident_sa[31:0];
    end
  end

  nx_pv_control #(.MAX_LENGTH(LONG_PV ? 512 : 64)) pv_control(.resident_write_region(pv_resident_write),.p_window_en,.p_window_address,.p_window_q,.p_window_valid,
    .p_window_epoch,.p_window_words,.p_window_len,.p_window_padded,.p_window_session,.p_window_sequence,.submit(submit&&descriptor[14*32+:32]==5),.clk(clk),.platform_reset_n(platform_reset_n),.reset_grant(reset_grant),.stop_new(stop_new),.abort_publish(abort_publish),.descriptor(descriptor),.epoch(epoch),.generation(generation),.first_fault_address(first_fault_address),.run_limit(run_limit),.transport_drained(transport_drained),.native_quarantined(native_quarantined),.completion_ready(completion_ready),.dma_ready(dma_ready),.dma_result_valid(dma_result_valid),.dma_idle(dma_idle),.dma_resp(dma_resp),.ram_q(ram_q),.engine_idle(pv_engine_idle),.arithmetic_idle(pv_arithmetic_idle),.scratch_idle(pv_scratch_idle),.timeout_fault(pv_timeout_fault),.call_fault(pv_call_fault),.completion(pv_completion),.completion_valid(pv_completion_valid),.perf(pv_perf),.dma_valid(pv_dma_valid),.dma_write(pv_dma_write),.dma_result_ready(pv_dma_result_ready),.dma_address(pv_dma_address),.dma_size(pv_dma_size),.dma_len(pv_dma_len),.dma_scratch(pv_dma_scratch),.dma_data(pv_dma_data),.dma_mask(pv_dma_mask),.ram_en(pv_ram_en),.ram_address(pv_ram_address),.ram_mask(pv_ram_mask),.ram_data(pv_ram_data),.fp_start(pv_start),.fp_multiply(pv_mul),.fp_a(pv_a),.fp_b(pv_b),.fp_ready(fp_available&&pv_selected),.fp_valid(fp_valid&&pv_selected),.fp_result(fp_result));
  nx_ce64_control #(.A_W_BANKED(A_W_BANKED),.W_PREFETCH(W_PREFETCH),.W_SW_STREAM(1),.SCRATCH_PREDICATES(SCRATCH_PREDICATES),.SCRATCH_SCALE_PREDICATES(SCRATCH_SCALE_PREDICATES),.DEADLINE_CACHE(DEADLINE_CACHE)) linear_control(.publication_phase(linear_publication_phase),.resident_group_certified(AQSA_GROUP_HANDOFF&&resident_linear_input),.resident_certificate_fault(aqsa_consumer_fault),.resident_authorized(resident_linear_input),.clk(clk),.platform_reset_n(platform_reset_n),.submit(submit&&descriptor[14*32+:32]!=3&&descriptor[14*32+:32]!=4&&descriptor[14*32+:32]!=5),.reset_grant(reset_grant),.stop_new(stop_new),.abort_publish(abort_publish),.descriptor(descriptor),.epoch(epoch),.generation(generation),.first_fault_address(first_fault_address),.run_limit(run_limit),.run_limit_next(run_limit_next),.transport_drained(transport_drained),.native_quarantined(native_quarantined),.engine_idle(linear_engine_idle),.arithmetic_idle(linear_arithmetic_idle),.scratch_idle(linear_scratch_idle),.timeout_fault(linear_timeout_fault),.call_fault(linear_call_fault),.completion(linear_completion),.completion_valid(linear_completion_valid),.completion_ready(completion_ready),.perf(linear_perf),.dma_ready(dma_ready),.dma_result_valid(dma_result_valid),.dma_idle(dma_idle),.dma_resp(dma_resp),.dma_valid(linear_dma_valid),.dma_write(linear_dma_write),.dma_result_ready(linear_dma_result_ready),.dma_address(linear_dma_address),.dma_size(linear_dma_size),.dma_len(linear_dma_len),.dma_scratch(linear_dma_scratch),.dma_data(linear_dma_data),.dma_mask(linear_dma_mask),.ram_en(linear_ram_en),.ram_address(linear_ram_address),.ram_mask(linear_ram_mask),.ram_data(linear_ram_data),.ram_q(ram_q),.ram_min80_q,.ram_nonzero_q,.ram_scale_zero_q,.ram_scale_lo0_q,.ram_scale_lo1_q,.dma_w_capture(dma_w_capture),.dma_sw_capture(dma_sw_capture),.dma_capture_bank(dma_capture_bank),.capture_revoke(capture_revoke),.capture_owner(capture_owner),.capture_command_tag(capture_command_tag),.capture_command_scales(capture_command_scales),.capture_release(capture_release),.capture_peek_bank(capture_peek_bank),.capture_peek_beat(capture_peek_beat),.capture_peek_tag(capture_peek_tag),.capture_data(capture_data),.capture_raw_data(capture_raw_data),.capture_raw_beats(capture_raw_beats),.capture_raw_banks(capture_raw_banks),.capture_mask(capture_mask),.capture_held(capture_held),.capture_certificate(capture_certificate),.capture_bad(capture_bad),.capture_result_seen(capture_result_seen),.capture_counts(capture_counts),.capture_physical_idle(capture_physical_idle),.capture_r_take(capture_r_take),.capture_r_data(capture_r_data),.capture_r_id(capture_r_id),.capture_r_resp(capture_r_resp),.capture_r_last(capture_r_last));
  nx_opt11_control #(.CROSS_GROUP_WRITE(CROSS_GROUP_WRITE),.EXTERNAL_FP(1),.LANES(LANES),.DEADLINE_CACHE(DEADLINE_CACHE)) vector_control(.resident_row_check(aqsa_row_check),.resident_certificate_fault(aqsa_producer_fault),.resident_authorized(resident_vector_input),.resident_row(resident_row_input),.shared_start(sf_start),.shared_multiply(sf_mul),.shared_a(sf_a),.shared_b(sf_b),.shared_ready(fp_available&&!pv_selected),.shared_valid(fp_valid&&!pv_selected),.shared_result(fp_result),.clk(clk),.platform_reset_n(platform_reset_n),.submit(submit&&descriptor[14*32+:32]==3),.reset_grant(reset_grant),.stop_new(stop_new),.abort_publish(abort_publish),.descriptor(descriptor),.epoch(epoch),.generation(generation),.first_fault_address(first_fault_address),.run_limit(run_limit),.run_limit_next(run_limit_next),.transport_drained(transport_drained),.native_quarantined(native_quarantined),.engine_idle(vector_engine_idle),.arithmetic_idle(vector_arithmetic_idle),.scratch_idle(vector_scratch_idle),.timeout_fault(vector_timeout_fault),.call_fault(vector_call_fault),.completion(vector_completion),.completion_valid(vector_completion_valid),.completion_ready(completion_ready),.perf(vector_perf),.dma_ready(dma_ready),.dma_result_valid(dma_result_valid),.dma_idle(dma_idle),.dma_resp(dma_resp),.dma_valid(vector_dma_valid),.dma_write(vector_dma_write),.dma_result_ready(vector_dma_result_ready),.dma_address(vector_dma_address),.dma_size(vector_dma_size),.dma_len(vector_dma_len),.dma_scratch(vector_dma_scratch),.dma_data(vector_dma_data),.dma_mask(vector_dma_mask),.ram_en(vector_ram_en),.ram_address(vector_ram_address),.ram_mask(vector_ram_mask),.ram_data(vector_ram_data),.ram_q(ram_q));
  nx_startup_zero #(.DEADLINE_CACHE(DEADLINE_CACHE)) startup_control(.clk(clk),.platform_reset_n(platform_reset_n),.startup_authorized,.startup_status,.submit(submit&&descriptor[14*32+:32]==4),.reset_grant(reset_grant),.stop_new(stop_new),.abort_publish(abort_publish),.descriptor(descriptor),.epoch(epoch),.generation(generation),.first_fault_address(first_fault_address),.run_limit(run_limit),.run_limit_next(run_limit_next),.transport_drained(transport_drained),.native_quarantined(native_quarantined),.engine_idle(startup_engine_idle),.arithmetic_idle(startup_arithmetic_idle),.scratch_idle(startup_scratch_idle),.timeout_fault(startup_timeout_fault),.call_fault(startup_call_fault),.completion(startup_completion),.completion_valid(startup_completion_valid),.completion_ready(completion_ready),.perf(startup_perf),.dma_ready(dma_ready),.dma_result_valid(dma_result_valid),.dma_idle(dma_idle),.dma_resp(dma_resp),.dma_valid(startup_dma_valid),.dma_write(startup_dma_write),.dma_result_ready(startup_dma_result_ready),.dma_address(startup_dma_address),.dma_size(startup_dma_size),.dma_len(startup_dma_len),.dma_scratch(startup_dma_scratch),.dma_data(startup_dma_data),.dma_mask(startup_dma_mask),.ram_en(startup_ram_en),.ram_address(startup_ram_address),.ram_mask(startup_ram_mask),.ram_data(startup_ram_data),.ram_q(ram_q));
endmodule

// Internal startup-only physical zero/write/readback controller. All public
// operators retain their existing validators and the single DMA/scratch port.
module nx_startup_zero #(parameter bit DEADLINE_CACHE=0)(
  input logic clk,platform_reset_n,submit,reset_grant,stop_new,abort_publish,
  input logic startup_authorized,
  input logic [1023:0] descriptor,
  input logic [31:0] epoch,generation,first_fault_address,
  input logic [63:0] run_limit,run_limit_next,
  input logic transport_drained,native_quarantined,
  output logic engine_idle,arithmetic_idle,scratch_idle,timeout_fault,call_fault,
  output logic [1279:0] completion,
  output logic completion_valid,
  input logic completion_ready,
  output logic [511:0] perf,
  output logic [31:0] startup_status,
  input logic dma_ready,dma_result_valid,dma_idle,
  input logic [1:0] dma_resp,
  output logic dma_valid,dma_write,dma_result_ready,
  output logic [31:0] dma_address,
  output logic [2:0] dma_size,
  output logic [4:0] dma_len,
  output logic [15:0] dma_scratch,
  output logic [127:0] dma_data,
  output logic [15:0] dma_mask,
  output logic ram_en,
  output logic [11:0] ram_address,
  output logic [15:0] ram_mask,
  output logic [127:0] ram_data,
  input logic [127:0] ram_q
);
  // Preserve the original four-state !=0 truth value while exposing
  // sixteen short comparisons to synthesis. No metadata RAM, port or cycle.
  (* keep=1,syn_keep=1 *) wire [15:0] verify_nonzero_bytes;
  generate for(genvar zb=0;zb<16;zb++)begin:startup_zero_compare
    assign verify_nonzero_bytes[zb]=(ram_q[8*zb+:8]!=8'b0);
  end endgenerate
  wire verify_nonzero=|verify_nonzero_bytes;
  typedef enum logic [3:0] {IDLE,VALIDATE,PLAN,FILL,WRITE_REQ,WRITE_WAIT,
      READ_REQ,READ_WAIT,VERIFY_REQ,VERIFY_WAIT,VERIFY_CHECK,NEXT,DRAIN,PUBLISH,DONE} state_t;
  state_t state;
  logic [31:0] d[0:31];
  function automatic logic startup_static_bad(input logic [1023:0] desc);
    logic [31:0] w[0:31];
    begin
      for(integer j=0;j<32;j++)w[j]=desc[32*j+:32];
      startup_static_bad=w[0]!=32'h34364543||w[1]!=1||w[2]!=128||w[3]!=0||w[5]!=1||w[6]!=0||w[7]!=0||w[8]!=32'h4c4e3135||w[9]!=96||
             (w[10]|w[11])==0||(w[12]|w[13])==0||w[14]!=4||w[15]!=1||w[16]!=1||w[18]!=0||(w[20]|w[21]|w[22]|w[23]|w[24]|w[26]|w[27]|w[28]|w[29]|w[30]|w[31])!=0;
    end
  endfunction
  logic startup_static_bad_q;

  logic signed [31:0] status,effective_status;
  logic [3:0] next_region;
  logic closed,attempt_failed,authority_live;
  logic [31:0] bound_epoch;
  logic [63:0] bound_session,bound_sequence;
  // Match metadata is captured with d[10:11] and maintained on every
  // bound_session update. Four-state != is intentional, including d!=d.
  logic session_bad,session_capture;
  always @* begin
    session_capture=0;
    case((stop_new||timeout_fault||!authority_live||abort_publish)&&!engine_idle&&state!=DRAIN&&state!=PUBLISH)
      1'b1:;
      default:begin
        case(state)
          IDLE,DONE:if(submit)session_capture=1;
          default:;
        endcase
      end
    endcase
  end
  // Same capture edge as bound_sequence; no sequence increment on VALIDATE.
  logic [63:0] bound_sequence_next;
  // Capture the wrap predicate on every original bound-sequence write edge.
  // Logical equality deliberately preserves four-state X/Z behavior.
  logic sequence_max;
  logic [31:0] cursor,remaining;
  logic [9:0] quantum_bytes;
  logic [5:0] word_index;
  logic [63:0] ticks,loads,writes,computes,read_bytes,write_bytes;
  wire [63:0] ticks_next;
  logic ticks_clear,ticks_enable,deadline_ge;
  wire deadline_expired=DEADLINE_CACHE ? deadline_ge : (run_limit!=0&&ticks>=run_limit);
  always_comb begin
    ticks_clear=0;ticks_enable=0;
    if((stop_new||timeout_fault||!authority_live||abort_publish)&&!engine_idle&&state!=DRAIN&&state!=PUBLISH)begin
      if(!engine_idle&&state!=PUBLISH)ticks_enable=1;
    end else case(state)
      IDLE,DONE:begin
        if(submit)ticks_clear=1;
        else if(!engine_idle&&state!=PUBLISH)ticks_enable=1;
      end
      default:if(!engine_idle&&state!=PUBLISH)ticks_enable=1;
    endcase
  end
  generate if(DEADLINE_CACHE)begin:cached_deadline
    nx_ce64_phase_counter64 #(.WHOLE_X_PROPAGATION(1)) counter(.clk,.reset_n(platform_reset_n),
      .clear(ticks_clear),.enable(ticks_enable),.value(ticks),.value_next(ticks_next));
    always_ff @(posedge clk or negedge platform_reset_n)begin
      if(!platform_reset_n)deadline_ge<=0;
      else deadline_ge<=(run_limit_next!=0&&ticks_next>=run_limit_next);
    end
  end else begin:original_deadline
    assign ticks_next=ticks;
    always_comb deadline_ge=1'b0;
  end endgenerate
  logic [31:0] expected_base,expected_bytes;
  logic [31:0] page_left,planned_bytes;
  always @* begin
    case(startup_authorized)
      1'b1:authority_live=1;
      default:authority_live=0;
    endcase
    expected_base=0;expected_bytes=0;
    case(next_region)
      0:begin expected_base=32'ha8000000;expected_bytes=15728640;end
      1:begin expected_base=32'hac000000;expected_bytes=835072;end
      2:begin expected_base=32'hac0cc000;expected_bytes=607744;end
      3:begin expected_base=32'hba100000;expected_bytes=77824;end
      4:begin expected_base=32'hba120000;expected_bytes=607744;end
      5:begin expected_base=32'hba1c0000;expected_bytes=19456;end
      6:begin expected_base=32'hba1c5000;expected_bytes=1216;end
      default:;
    endcase
    page_left=4096-{20'b0,cursor[11:0]};
    planned_bytes=remaining>512 ? 512 : remaining;
    if(planned_bytes>page_left)planned_bytes=page_left;
  end
  assign startup_status={25'b0,next_region,!authority_live,closed,authority_live&&!closed};
  assign engine_idle=state==IDLE||state==DONE;
  assign arithmetic_idle=1;
  assign scratch_idle=state!=FILL&&state!=VERIFY_REQ&&state!=VERIFY_WAIT&&state!=VERIFY_CHECK;
  assign timeout_fault=!engine_idle&&state!=DRAIN&&state!=PUBLISH&&deadline_expired;
  assign call_fault=0;
  always @* begin
    effective_status=status;
    if(status==0)begin
      if(deadline_expired)effective_status=-7;
      else if(!authority_live)effective_status=-10;
      else if(stop_new||abort_publish)effective_status=-11;
    end
  end
  assign completion_valid=state==PUBLISH;
  assign dma_valid=(state==WRITE_REQ||state==READ_REQ)&&!stop_new&&!timeout_fault&&authority_live;
  assign dma_write=state==WRITE_REQ;
  assign dma_result_ready=1;
  assign dma_address=cursor;
  assign dma_size=4;
  assign dma_len=5'((quantum_bytes>>4)-1);
  assign dma_scratch=16'hf000;
  assign dma_data=0;
  assign dma_mask=state==WRITE_REQ ? 16'hffff : 0;
  assign ram_en=state==FILL||state==VERIFY_REQ;
  assign ram_address=12'hf00+12'(word_index);
  assign ram_mask=state==FILL ? 16'hffff : 0;
  assign ram_data=0;
  assign perf={64'b0,writes,computes,loads,ticks,read_bytes,write_bytes};
  always @* begin
    completion={32'(generation),32'(generation),32'd0,32'd0,32'd0,32'(effective_status),64'(ticks-loads-computes-writes),64'(writes),64'(computes),64'(loads),64'(ticks),64'(write_bytes),64'(read_bytes),32'd0,32'd0,32'(1),32'(1),32'(effective_status==0),32'(effective_status),32'(d[13]),32'(d[12]),32'(d[11]),32'(d[10]),32'(104),32'(32'h4c4e3135),32'(native_quarantined ? 1 : 0),32'(first_fault_address),32'd0,32'(2),32'(epoch),32'(160),32'(1),32'(32'h52364543)};
  end
    // Source-derived local NBA priority trees; all RHSs use the original old state.
  state_t state_next;
  always @* begin
    if(reset_grant)begin
      state_next=IDLE;
    end else begin
      if((stop_new||timeout_fault||!authority_live||abort_publish)&&!engine_idle&&state!=DRAIN&&state!=PUBLISH)begin
        state_next=DRAIN;
      end else begin
        case(state)
          IDLE,DONE:begin
            if(submit)begin
              state_next=VALIDATE;
            end else begin
              state_next=state;
            end
          end
          VALIDATE:begin
            if(!authority_live||closed||attempt_failed||next_region>=7||
             startup_static_bad_q||d[4]!=epoch||epoch==0||
             
             d[17]!=expected_bytes||d[19]!=expected_base||
             
             d[25]!={28'b0,next_region}||
             (next_region==0 ? {d[13],d[12]}!=1 :
                (bound_epoch!=epoch||session_bad||sequence_max||{d[13],d[12]}!=bound_sequence_next)))begin
              state_next=DRAIN;
            end else begin
              state_next=PLAN;
            end
          end
          PLAN:begin
            state_next=FILL;
          end
          FILL:begin
            if(word_index+1==(quantum_bytes>>4))begin
              state_next=WRITE_REQ;
            end else begin
              state_next=state;
            end
          end
          WRITE_REQ:begin
            if(dma_valid&&dma_ready)begin
              state_next=WRITE_WAIT;
            end else begin
              state_next=state;
            end
          end
          WRITE_WAIT:begin
            if(dma_result_valid)begin
              if(dma_resp!=0)begin
                state_next=DRAIN;
              end else begin
                state_next=READ_REQ;
              end
            end else begin
              state_next=state;
            end
          end
          READ_REQ:begin
            if(dma_valid&&dma_ready)begin
              state_next=READ_WAIT;
            end else begin
              state_next=state;
            end
          end
          READ_WAIT:begin
            if(dma_result_valid)begin
              if(dma_resp!=0)begin
                state_next=DRAIN;
              end else begin
                state_next=VERIFY_REQ;
              end
            end else begin
              state_next=state;
            end
          end
          VERIFY_REQ:begin
            state_next=VERIFY_WAIT;
          end
          VERIFY_WAIT:begin
            state_next=VERIFY_CHECK;
          end
          VERIFY_CHECK:begin
            if(verify_nonzero)begin
              state_next=DRAIN;
            end else begin
              if(word_index+1==(quantum_bytes>>4))begin
                state_next=NEXT;
              end else begin
                state_next=VERIFY_REQ;
              end
            end
          end
          NEXT:begin
            if(remaining==32'(quantum_bytes))begin
              state_next=DRAIN;
            end else begin
              state_next=PLAN;
            end
          end
          DRAIN:begin
            if(dma_idle&&transport_drained)begin
              state_next=abort_publish ? DONE : PUBLISH;
            end else begin
              state_next=state;
            end
          end
          PUBLISH:begin
            if(completion_ready)begin
              state_next=DONE;
            end else begin
              state_next=state;
            end
          end
          default:begin
            state_next=DRAIN;
          end
        endcase
      end
    end
  end

  always @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)state<=IDLE;
    else state<=state_next;
  end

  always @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)begin
      status<=0;
    end else begin
      if(reset_grant)begin
        status<=0;
      end else begin
        if((stop_new||timeout_fault||!authority_live||abort_publish)&&!engine_idle&&state!=DRAIN&&state!=PUBLISH)begin
          status<=timeout_fault ? -7 : (!authority_live ? -10 : -11);
        end else begin
          case(state)
            IDLE,DONE:begin
              if(submit)begin
                status<=0;
              end
            end
            VALIDATE:begin
              if(!authority_live||closed||attempt_failed||next_region>=7||
             startup_static_bad_q||d[4]!=epoch||epoch==0||
             
             d[17]!=expected_bytes||d[19]!=expected_base||
             
             d[25]!={28'b0,next_region}||
             (next_region==0 ? {d[13],d[12]}!=1 :
                (bound_epoch!=epoch||session_bad||sequence_max||{d[13],d[12]}!=bound_sequence_next)))begin
                status<=-4;
              end
            end
            WRITE_WAIT:begin
              if(dma_result_valid)begin
                if(dma_resp!=0)begin
                  status<=-8;
                end
              end
            end
            READ_WAIT:begin
              if(dma_result_valid)begin
                if(dma_resp!=0)begin
                  status<=-8;
                end
              end
            end
            VERIFY_CHECK:begin
              if(verify_nonzero)begin
                status<=-8;
              end
            end
            default:begin
              ;
            end
          endcase
        end
      end
    end
  end

  always @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)begin
      next_region<=0;
    end else begin
      if(reset_grant)begin
        if(!closed)begin
          next_region<=0;
        end else begin
          case((stop_new||timeout_fault||!authority_live||abort_publish)&&!engine_idle&&state!=DRAIN&&state!=PUBLISH)
            1'b1:;
            default:begin
              case(state)
                PUBLISH:begin
                  if(completion_ready)begin
                    if(effective_status==0)begin
                      next_region<=next_region+1'b1;
                    end
                  end
                end
                default:begin
                  ;
                end
              endcase
            end
          endcase
        end
      end else begin
        case((stop_new||timeout_fault||!authority_live||abort_publish)&&!engine_idle&&state!=DRAIN&&state!=PUBLISH)
          1'b1:;
          default:begin
            case(state)
              PUBLISH:begin
                if(completion_ready)begin
                  if(effective_status==0)begin
                    next_region<=next_region+1'b1;
                  end
                end
              end
              default:begin
                ;
              end
            endcase
          end
        endcase
      end
    end
  end

  always @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)begin
      closed<=0;
    end else begin
      case((stop_new||timeout_fault||!authority_live||abort_publish)&&!engine_idle&&state!=DRAIN&&state!=PUBLISH)
        1'b1:;
        default:begin
          case(state)
            PUBLISH:begin
              if(completion_ready)begin
                if(effective_status==0)begin
                  if(next_region==6)begin
                    closed<=1;
                  end
                end
              end
            end
            default:begin
              ;
            end
          endcase
        end
      endcase
    end
  end

  always @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)begin
      attempt_failed<=0;
    end else begin
      if(reset_grant)begin
        attempt_failed<=0;
      end else begin
        if((stop_new||timeout_fault||!authority_live||abort_publish)&&!engine_idle&&state!=DRAIN&&state!=PUBLISH)begin
          attempt_failed<=1;
        end else begin
          case(state)
            VALIDATE:begin
              if(!authority_live||closed||attempt_failed||next_region>=7||
             startup_static_bad_q||d[4]!=epoch||epoch==0||
             
             d[17]!=expected_bytes||d[19]!=expected_base||
             
             d[25]!={28'b0,next_region}||
             (next_region==0 ? {d[13],d[12]}!=1 :
                (bound_epoch!=epoch||session_bad||sequence_max||{d[13],d[12]}!=bound_sequence_next)))begin
                attempt_failed<=1;
              end
            end
            WRITE_WAIT:begin
              if(dma_result_valid)begin
                if(dma_resp!=0)begin
                  attempt_failed<=1;
                end
              end
            end
            READ_WAIT:begin
              if(dma_result_valid)begin
                if(dma_resp!=0)begin
                  attempt_failed<=1;
                end
              end
            end
            VERIFY_CHECK:begin
              if(verify_nonzero)begin
                attempt_failed<=1;
              end
            end
            PUBLISH:begin
              if(completion_ready)begin
                case(effective_status==0)
                  1'b1:;
                  default:begin
                    attempt_failed<=1;
                  end
                endcase
              end
            end
            default:begin
              ;
            end
          endcase
        end
      end
    end
  end

  always @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)begin
      bound_epoch<=0;
    end else begin
      if(reset_grant)begin
        if(!closed)begin
          bound_epoch<=0;
        end else begin
          case((stop_new||timeout_fault||!authority_live||abort_publish)&&!engine_idle&&state!=DRAIN&&state!=PUBLISH)
            1'b1:;
            default:begin
              case(state)
                VALIDATE:begin
                  case(!authority_live||closed||attempt_failed||next_region>=7||
             startup_static_bad_q||d[4]!=epoch||epoch==0||
             
             d[17]!=expected_bytes||d[19]!=expected_base||
             
             d[25]!={28'b0,next_region}||
             (next_region==0 ? {d[13],d[12]}!=1 :
                (bound_epoch!=epoch||session_bad||sequence_max||{d[13],d[12]}!=bound_sequence_next)))
                    1'b1:;
                    default:begin
                      if(next_region==0)begin
                        bound_epoch<=epoch;
                      end
                    end
                  endcase
                end
                default:begin
                  ;
                end
              endcase
            end
          endcase
        end
      end else begin
        case((stop_new||timeout_fault||!authority_live||abort_publish)&&!engine_idle&&state!=DRAIN&&state!=PUBLISH)
          1'b1:;
          default:begin
            case(state)
              VALIDATE:begin
                case(!authority_live||closed||attempt_failed||next_region>=7||
             startup_static_bad_q||d[4]!=epoch||epoch==0||
             
             d[17]!=expected_bytes||d[19]!=expected_base||
             
             d[25]!={28'b0,next_region}||
             (next_region==0 ? {d[13],d[12]}!=1 :
                (bound_epoch!=epoch||session_bad||sequence_max||{d[13],d[12]}!=bound_sequence_next)))
                  1'b1:;
                  default:begin
                    if(next_region==0)begin
                      bound_epoch<=epoch;
                    end
                  end
                endcase
              end
              default:begin
                ;
              end
            endcase
          end
        endcase
      end
    end
  end

  always @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)begin
      bound_session<=0;session_bad<=0;
    end else begin
      if(session_capture)session_bad<=(descriptor[10*32+:64]!=bound_session);
      if(reset_grant)begin
        if(!closed)begin
          bound_session<=0;
          session_bad<=session_capture ? (descriptor[10*32+:64]!=64'd0) : ({d[11],d[10]}!=64'd0);
        end else begin
          case((stop_new||timeout_fault||!authority_live||abort_publish)&&!engine_idle&&state!=DRAIN&&state!=PUBLISH)
            1'b1:;
            default:begin
              case(state)
                VALIDATE:begin
                  case(!authority_live||closed||attempt_failed||next_region>=7||
             startup_static_bad_q||d[4]!=epoch||epoch==0||
             
             d[17]!=expected_bytes||d[19]!=expected_base||
             
             d[25]!={28'b0,next_region}||
             (next_region==0 ? {d[13],d[12]}!=1 :
                (bound_epoch!=epoch||session_bad||sequence_max||{d[13],d[12]}!=bound_sequence_next)))
                    1'b1:;
                    default:begin
                      if(next_region==0)begin
                        bound_session<={d[11],d[10]};
                        session_bad<=({d[11],d[10]}!={d[11],d[10]});
                      end
                    end
                  endcase
                end
                default:begin
                  ;
                end
              endcase
            end
          endcase
        end
      end else begin
        case((stop_new||timeout_fault||!authority_live||abort_publish)&&!engine_idle&&state!=DRAIN&&state!=PUBLISH)
          1'b1:;
          default:begin
            case(state)
              VALIDATE:begin
                case(!authority_live||closed||attempt_failed||next_region>=7||
             startup_static_bad_q||d[4]!=epoch||epoch==0||
             
             d[17]!=expected_bytes||d[19]!=expected_base||
             
             d[25]!={28'b0,next_region}||
             (next_region==0 ? {d[13],d[12]}!=1 :
                (bound_epoch!=epoch||session_bad||sequence_max||{d[13],d[12]}!=bound_sequence_next)))
                  1'b1:;
                  default:begin
                    if(next_region==0)begin
                      bound_session<={d[11],d[10]};
                        session_bad<=({d[11],d[10]}!={d[11],d[10]});
                    end
                  end
                endcase
              end
              default:begin
                ;
              end
            endcase
          end
        endcase
      end
    end
  end

  always @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)begin
      bound_sequence<=0;bound_sequence_next<=64'd1;sequence_max<=0;
    end else begin
      if(reset_grant)begin
        if(!closed)begin
          bound_sequence<=0;bound_sequence_next<=64'd1;sequence_max<=0;
        end else begin
          case((stop_new||timeout_fault||!authority_live||abort_publish)&&!engine_idle&&state!=DRAIN&&state!=PUBLISH)
            1'b1:;
            default:begin
              case(state)
                PUBLISH:begin
                  if(completion_ready)begin
                    if(effective_status==0)begin
                      bound_sequence<={d[13],d[12]};bound_sequence_next<={d[13],d[12]}+64'd1;sequence_max<=({d[13],d[12]}==64'hffffffffffffffff);
                    end
                  end
                end
                default:begin
                  ;
                end
              endcase
            end
          endcase
        end
      end else begin
        case((stop_new||timeout_fault||!authority_live||abort_publish)&&!engine_idle&&state!=DRAIN&&state!=PUBLISH)
          1'b1:;
          default:begin
            case(state)
              PUBLISH:begin
                if(completion_ready)begin
                  if(effective_status==0)begin
                    bound_sequence<={d[13],d[12]};bound_sequence_next<={d[13],d[12]}+64'd1;sequence_max<=({d[13],d[12]}==64'hffffffffffffffff);
                  end
                end
              end
              default:begin
                ;
              end
            endcase
          end
        endcase
      end
    end
  end

  always @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)begin
      cursor<=0;
    end else begin
      case((stop_new||timeout_fault||!authority_live||abort_publish)&&!engine_idle&&state!=DRAIN&&state!=PUBLISH)
        1'b1:;
        default:begin
          case(state)
            VALIDATE:begin
              case(!authority_live||closed||attempt_failed||next_region>=7||
             startup_static_bad_q||d[4]!=epoch||epoch==0||
             
             d[17]!=expected_bytes||d[19]!=expected_base||
             
             d[25]!={28'b0,next_region}||
             (next_region==0 ? {d[13],d[12]}!=1 :
                (bound_epoch!=epoch||session_bad||sequence_max||{d[13],d[12]}!=bound_sequence_next)))
                1'b1:;
                default:begin
                  cursor<=expected_base;
                end
              endcase
            end
            NEXT:begin
              case(remaining==32'(quantum_bytes))
                1'b1:;
                default:begin
                  cursor<=cursor+quantum_bytes;
                end
              endcase
            end
            default:begin
              ;
            end
          endcase
        end
      endcase
    end
  end

  always @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)begin
      remaining<=0;
    end else begin
      case((stop_new||timeout_fault||!authority_live||abort_publish)&&!engine_idle&&state!=DRAIN&&state!=PUBLISH)
        1'b1:;
        default:begin
          case(state)
            VALIDATE:begin
              case(!authority_live||closed||attempt_failed||next_region>=7||
             startup_static_bad_q||d[4]!=epoch||epoch==0||
             
             d[17]!=expected_bytes||d[19]!=expected_base||
             
             d[25]!={28'b0,next_region}||
             (next_region==0 ? {d[13],d[12]}!=1 :
                (bound_epoch!=epoch||session_bad||sequence_max||{d[13],d[12]}!=bound_sequence_next)))
                1'b1:;
                default:begin
                  remaining<=expected_bytes;
                end
              endcase
            end
            NEXT:begin
              case(remaining==32'(quantum_bytes))
                1'b1:;
                default:begin
                  remaining<=remaining-quantum_bytes;
                end
              endcase
            end
            default:begin
              ;
            end
          endcase
        end
      endcase
    end
  end

  always @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)begin
      quantum_bytes<=0;
    end else begin
      case((stop_new||timeout_fault||!authority_live||abort_publish)&&!engine_idle&&state!=DRAIN&&state!=PUBLISH)
        1'b1:;
        default:begin
          case(state)
            PLAN:begin
              quantum_bytes<=10'(planned_bytes);
            end
            default:begin
              ;
            end
          endcase
        end
      endcase
    end
  end

  always @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)begin
      word_index<=0;
    end else begin
      case((stop_new||timeout_fault||!authority_live||abort_publish)&&!engine_idle&&state!=DRAIN&&state!=PUBLISH)
        1'b1:;
        default:begin
          case(state)
            PLAN:begin
              word_index<=0;
            end
            FILL:begin
              if(word_index+1==(quantum_bytes>>4))begin
                word_index<=0;
              end else begin
                word_index<=word_index+1'b1;
              end
            end
            READ_WAIT:begin
              if(dma_result_valid)begin
                case(dma_resp!=0)
                  1'b1:;
                  default:begin
                    word_index<=0;
                  end
                endcase
              end
            end
            VERIFY_CHECK:begin
              case(verify_nonzero)
                1'b1:;
                default:begin
                  case(word_index+1==(quantum_bytes>>4))
                    1'b1:;
                    default:begin
                      word_index<=word_index+1'b1;
                    end
                  endcase
                end
              endcase
            end
            default:begin
              ;
            end
          endcase
        end
      endcase
    end
  end

  generate if(!DEADLINE_CACHE)begin:original_ticks
  always @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)begin
      ticks<=0;
    end else begin
      if((stop_new||timeout_fault||!authority_live||abort_publish)&&!engine_idle&&state!=DRAIN&&state!=PUBLISH)begin
        if(!engine_idle&&state!=PUBLISH)begin
          ticks<=ticks+1;
        end
      end else begin
        case(state)
          IDLE,DONE:begin
            if(submit)begin
              ticks<=0;
            end else begin
              if(!engine_idle&&state!=PUBLISH)begin
                ticks<=ticks+1;
              end
            end
          end
          default:begin
            if(!engine_idle&&state!=PUBLISH)begin
              ticks<=ticks+1;
            end
          end
        endcase
      end
    end
  end

  end endgenerate

  always @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)begin
      loads<=0;
    end else begin
      if((stop_new||timeout_fault||!authority_live||abort_publish)&&!engine_idle&&state!=DRAIN&&state!=PUBLISH)begin
        if(!engine_idle&&state!=PUBLISH)begin
          case(state==WRITE_REQ||state==WRITE_WAIT)
            1'b1:;
            default:begin
              if(state==READ_REQ||state==READ_WAIT)begin
                loads<=loads+1;
              end
            end
          endcase
        end
      end else begin
        case(state)
          IDLE,DONE:begin
            if(submit)begin
              loads<=0;
            end else begin
              if(!engine_idle&&state!=PUBLISH)begin
                case(state==WRITE_REQ||state==WRITE_WAIT)
                  1'b1:;
                  default:begin
                    if(state==READ_REQ||state==READ_WAIT)begin
                      loads<=loads+1;
                    end
                  end
                endcase
              end
            end
          end
          default:begin
            if(!engine_idle&&state!=PUBLISH)begin
              case(state==WRITE_REQ||state==WRITE_WAIT)
                1'b1:;
                default:begin
                  if(state==READ_REQ||state==READ_WAIT)begin
                    loads<=loads+1;
                  end
                end
              endcase
            end
          end
        endcase
      end
    end
  end

  always @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)begin
      writes<=0;
    end else begin
      if((stop_new||timeout_fault||!authority_live||abort_publish)&&!engine_idle&&state!=DRAIN&&state!=PUBLISH)begin
        if(!engine_idle&&state!=PUBLISH)begin
          if(state==WRITE_REQ||state==WRITE_WAIT)begin
            writes<=writes+1;
          end
        end
      end else begin
        case(state)
          IDLE,DONE:begin
            if(submit)begin
              writes<=0;
            end else begin
              if(!engine_idle&&state!=PUBLISH)begin
                if(state==WRITE_REQ||state==WRITE_WAIT)begin
                  writes<=writes+1;
                end
              end
            end
          end
          default:begin
            if(!engine_idle&&state!=PUBLISH)begin
              if(state==WRITE_REQ||state==WRITE_WAIT)begin
                writes<=writes+1;
              end
            end
          end
        endcase
      end
    end
  end

  always @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)begin
      computes<=0;
    end else begin
      if((stop_new||timeout_fault||!authority_live||abort_publish)&&!engine_idle&&state!=DRAIN&&state!=PUBLISH)begin
        if(!engine_idle&&state!=PUBLISH)begin
          case(state==WRITE_REQ||state==WRITE_WAIT)
            1'b1:;
            default:begin
              case(state==READ_REQ||state==READ_WAIT)
                1'b1:;
                default:begin
                  if(state==FILL||state==VERIFY_REQ||state==VERIFY_WAIT||state==VERIFY_CHECK)begin
                    computes<=computes+1;
                  end
                end
              endcase
            end
          endcase
        end
      end else begin
        case(state)
          IDLE,DONE:begin
            if(submit)begin
              computes<=0;
            end else begin
              if(!engine_idle&&state!=PUBLISH)begin
                case(state==WRITE_REQ||state==WRITE_WAIT)
                  1'b1:;
                  default:begin
                    case(state==READ_REQ||state==READ_WAIT)
                      1'b1:;
                      default:begin
                        if(state==FILL||state==VERIFY_REQ||state==VERIFY_WAIT||state==VERIFY_CHECK)begin
                          computes<=computes+1;
                        end
                      end
                    endcase
                  end
                endcase
              end
            end
          end
          default:begin
            if(!engine_idle&&state!=PUBLISH)begin
              case(state==WRITE_REQ||state==WRITE_WAIT)
                1'b1:;
                default:begin
                  case(state==READ_REQ||state==READ_WAIT)
                    1'b1:;
                    default:begin
                      if(state==FILL||state==VERIFY_REQ||state==VERIFY_WAIT||state==VERIFY_CHECK)begin
                        computes<=computes+1;
                      end
                    end
                  endcase
                end
              endcase
            end
          end
        endcase
      end
    end
  end

  always @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)begin
      read_bytes<=0;
    end else begin
      case((stop_new||timeout_fault||!authority_live||abort_publish)&&!engine_idle&&state!=DRAIN&&state!=PUBLISH)
        1'b1:;
        default:begin
          case(state)
            IDLE,DONE:begin
              if(submit)begin
                read_bytes<=0;
              end
            end
            READ_WAIT:begin
              if(dma_result_valid)begin
                case(dma_resp!=0)
                  1'b1:;
                  default:begin
                    read_bytes<=read_bytes+quantum_bytes;
                  end
                endcase
              end
            end
            default:begin
              ;
            end
          endcase
        end
      endcase
    end
  end

  always @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)begin
      write_bytes<=0;
    end else begin
      case((stop_new||timeout_fault||!authority_live||abort_publish)&&!engine_idle&&state!=DRAIN&&state!=PUBLISH)
        1'b1:;
        default:begin
          case(state)
            IDLE,DONE:begin
              if(submit)begin
                write_bytes<=0;
              end
            end
            WRITE_WAIT:begin
              if(dma_result_valid)begin
                case(dma_resp!=0)
                  1'b1:;
                  default:begin
                    write_bytes<=write_bytes+quantum_bytes;
                  end
                endcase
              end
            end
            default:begin
              ;
            end
          endcase
        end
      endcase
    end
  end

  always @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)begin
      for(integer i=0;i<32;i=i+1)d[i]<=0;
      startup_static_bad_q<=1'b1;
    end else begin
      case((stop_new||timeout_fault||!authority_live||abort_publish)&&!engine_idle&&state!=DRAIN&&state!=PUBLISH)
        1'b1:;
        default:begin
          case(state)
            IDLE,DONE:begin
              if(submit)begin
                for(integer i=0;i<32;i=i+1)d[i]<=descriptor[i*32+:32];
                startup_static_bad_q<=startup_static_bad(descriptor);
              end
            end
            default:begin
              ;
            end
          endcase
        end
      endcase
    end
  end
endmodule

// Private PV descriptor opcode 5. Serial DMA and one synchronous compute
// scratch port. Length <=64 retains the original layout/window ABI. Longer
// calls use padded P at 0x0000, a 16-dimension V tile at 0x4000, a complete
// <=512-product reduction at 0xc000, and Y at 0xf000. Four V tiles read each
// needed FP32 V element once. No new tensor RAM and no altered sum order.
module nx_pv_control #(parameter integer MAX_LENGTH=64)(
 output logic resident_write_region,
 output wire p_window_en,
 output wire [8:0] p_window_address,
 input wire [31:0] p_window_q,p_window_epoch,p_window_words,p_window_len,p_window_padded,
 input wire [63:0] p_window_session,p_window_sequence,
 input wire p_window_valid,
 input logic clk,platform_reset_n,submit,reset_grant,stop_new,abort_publish,
 input logic [1023:0] descriptor,input logic [31:0] epoch,generation,first_fault_address,
 input logic [63:0] run_limit,input logic transport_drained,native_quarantined,
 output wire engine_idle,arithmetic_idle,scratch_idle,timeout_fault,call_fault,
 output logic [1279:0] completion,output wire completion_valid,input logic completion_ready,
 output wire [511:0] perf,input logic dma_ready,dma_result_valid,dma_idle,
 input logic [1:0] dma_resp,output wire dma_valid,dma_write,dma_result_ready,
 output logic [31:0] dma_address,output wire [2:0] dma_size,
 output logic [4:0] dma_len,output logic [15:0] dma_scratch,
 output wire [127:0] dma_data,output wire [15:0] dma_mask,
 output wire ram_en,output wire [11:0] ram_address,
 output logic [15:0] ram_mask,output logic [127:0] ram_data,input logic [127:0] ram_q,
 output wire fp_start,fp_multiply,output wire [31:0] fp_a,fp_b,
 input logic fp_ready,fp_valid,input logic [31:0] fp_result
);
 typedef enum logic [4:0] {IDLE,CHECK,READ_P,READ_P_WAIT,READ_V,READ_V_WAIT,
   A_REQ,A_WAIT,B_REQ,B_WAIT,FP_SEND,FP_WAIT,WORK,PAD,OUT,
   WRITE_Y,WRITE_Y_WAIT,DRAIN,PUBLISH,DONE,
   CHECK_ENDS,CHECK_RANGE,CHECK_FINAL,PREP_P,PREP_V,PREP_Y} state_t;
 state_t state;
 logic [31:0] d[0:31];logic signed [31:0] status;
 logic [31:0] left,right,value;
 logic [6:0] h,dim;
 logic [9:0] t,width,row;
 logic [5:0] dim_base;
 logic tree_mode;logic [13:0] offset;
 logic [7:0] v_offset;
 logic [63:0] ticks,loads,computes,writes,read_bytes,write_bytes;
 wire active=!(state==IDLE||state==DONE||state==PUBLISH);
 assign engine_idle=state==IDLE||state==DONE;
 assign arithmetic_idle=fp_ready;
 assign scratch_idle=!ram_en;
 assign timeout_fault=active&&state!=DRAIN&&run_limit!=0&&ticks>=run_limit;
 assign call_fault=0;assign completion_valid=state==PUBLISH;
 assign dma_result_ready=1;assign dma_size=4;assign dma_data=0;assign dma_mask=16'hffff;
 assign dma_valid=(state==READ_P||state==READ_V||state==WRITE_Y)&&!stop_new&&!timeout_fault&&!abort_publish;
 assign dma_write=state==WRITE_Y;
 wire long_pv_calc=d[17]>64;
 wire [9:0] p_stride_calc=long_pv_calc ? 10'(d[25]) : 10'd64;
 (* syn_preserve = 1 *) logic runtime_long_pv;
 (* syn_preserve = 1 *) logic [9:0] runtime_p_stride;
 wire long_pv=runtime_long_pv;
 wire [9:0] p_stride=runtime_p_stride;
 (* syn_dspstyle = "logic" *) wire [14:0] p_bytes_calc=15'(d[24]*32'(p_stride_calc)*4);
 // CHECK captures the exact span before any accepted DMA command. Reuse
 // that job-stable value on the running command/retirement path.
 wire [14:0] p_bytes=check_p_bytes;
 wire [11:0] y_bytes=12'(d[24]<<8);
 wire [14:0] transfer_bytes=(state==WRITE_Y||state==WRITE_Y_WAIT||state==PREP_Y)?{3'b0,y_bytes}:p_bytes;
 wire [14:0] remaining_bytes=transfer_bytes-{1'b0,offset};
 wire [31:0] transfer_address=(state==WRITE_Y||state==WRITE_Y_WAIT||state==PREP_Y?d[19]:d[18])+{18'b0,offset};
 wire [12:0] page_remaining=13'd4096-{1'b0,transfer_address[11:0]};
 wire [14:0] bounded_chunk=remaining_bytes>512?15'd512:remaining_bytes;
 // Both layouts accept 16-byte-aligned Y, and the short layout also accepts
 // 16-byte-aligned external P. Every command must stop at the current page.
 wire [14:0] chunk={2'b0,page_remaining}<bounded_chunk?{2'b0,page_remaining}:bounded_chunk;
 // A short V row may start at any legal 16-byte boundary. Preserve that ABI
 // by splitting its 256 bytes across pages, advancing scratch within the row.
 // Long V tiles are already page-safe by alignment, so they stay one command.
 wire [8:0] v_row_bytes=long_pv?9'd64:9'd256;
 wire [8:0] v_remaining=v_row_bytes-{1'b0,v_offset};
 wire [31:0] v_transfer_address=d[20]+32'(row)*d[26]+
   (long_pv?32'(dim_base)*4:32'd0)+{24'b0,v_offset};
 wire [12:0] v_page_remaining=13'd4096-{1'b0,v_transfer_address[11:0]};
 wire [8:0] v_chunk={4'b0,v_remaining}>v_page_remaining?9'(v_page_remaining):v_remaining;
 (* syn_preserve = 1 *) logic [31:0] command_address_q;
 (* syn_preserve = 1 *) logic [15:0] command_scratch_q;
 (* syn_preserve = 1 *) logic [4:0] command_len_q;
 logic [14:0] command_bytes_q;
 // PREP captures the complete command before valid can reach DMA legality.
 // Inactive payload need not reset: each request state is entered only from
 // its PREP state. Cancellation still wins in the original control block.
 always @(posedge clk)begin
   if(state==CHECK)begin runtime_long_pv<=long_pv_calc;runtime_p_stride<=p_stride_calc;end
   case(state)
     PREP_P:begin
       command_address_q<=transfer_address;command_scratch_q<={2'b0,offset};
       command_len_q<=5'((chunk>>4)-1);command_bytes_q<=chunk;
     end
     PREP_V:begin
       command_address_q<=v_transfer_address;
       command_scratch_q<=(long_pv?16'h4000+16'(row<<6):16'h0700+16'(row<<8))+16'(v_offset);
       command_len_q<=5'((v_chunk>>4)-1);command_bytes_q<={6'b0,v_chunk};
     end
     PREP_Y:begin
       command_address_q<=transfer_address;command_scratch_q<=16'hf000+{2'b0,offset};
       command_len_q<=5'((chunk>>4)-1);command_bytes_q<=chunk;
     end
     default:;
   endcase
 end
 always_comb begin dma_address=command_address_q;dma_scratch=command_scratch_q;dma_len=command_len_q;end
 (* syn_dspstyle = "logic" *) wire [13:0] p_word_base=14'(h)*14'(p_stride);
 logic [13:0] word_index;
 always_comb begin
   if(state==A_REQ||state==A_WAIT)word_index=tree_mode?
     (long_pv?14'd12288:14'd4544)+14'(t<<1):p_word_base+14'(t);
   else if(state==B_REQ||state==B_WAIT)word_index=tree_mode?
     (long_pv?14'd12289:14'd4545)+14'(t<<1):
     long_pv?14'd4096+14'(t<<4)+14'(dim[3:0]):14'd448+14'(t<<6)+14'(dim);
   else if(state==OUT)word_index=14'd15360+14'(h<<6)+dim;
   else word_index=(long_pv?14'd12288:14'd4544)+14'(t);
   ram_mask=0;ram_data=0;
   if(state==WORK||state==PAD||state==OUT)begin
     ram_mask=16'hf<<(word_index[1:0]*4);
     ram_data={96'b0,state==PAD?32'b0:value}<<(word_index[1:0]*32);
   end
 end
 wire local_p=d[27]==1;
 assign p_window_en=state==A_REQ&&!tree_mode&&local_p&&!stop_new&&!timeout_fault&&!abort_publish;
 assign p_window_address=9'((h<<6)+t);
 assign ram_en=(state==A_REQ&&(!local_p||tree_mode))||state==B_REQ||state==WORK||state==PAD||state==OUT;
 assign ram_address=word_index[13:2];
 // q retains the carry from h+dim[6]; OUT wraps modulo the original14bits.
 wire [7:0] resident_out_q={1'b0,h}+{7'b0,dim[6]};
 always_comb begin
   case(^{state,t,h,dim})
     1'b0,1'b1:begin
       resident_write_region=0;
       if(state==WORK||state==PAD)resident_write_region=1;
       else if(state==OUT)resident_write_region=
         (resident_out_q>=16&&resident_out_q<92)||
         (resident_out_q>=96&&resident_out_q<100)||
         (resident_out_q==100&&dim[5:0]<48);
     end
     default:resident_write_region=(|ram_mask)&&
       (ram_address<12'h4c0||(ram_address>=12'h500&&ram_address<12'h54c));
   endcase
 end

 assign fp_start=state==FP_SEND&&fp_ready&&!stop_new&&!timeout_fault&&!abort_publish&&left[30:23]!=255&&right[30:23]!=255;
 assign fp_multiply=!tree_mode;assign fp_a=left;assign fp_b=right;
 // Check the full descriptor shape before using bounded span arithmetic.  The
 // original 64-bit product is exactly (len << 9) - 256 for every legal shape:
 // 1 <= len <= MAX_LENGTH and stride == 512. Illegal operands are rejected separately,
 // so no truncated product can make an out-of-range descriptor acceptable.
 logic [7:0] check_parts;
 logic [3:0] range_parts;
 logic [10:0] check_y_bytes;
 (* syn_preserve = 1 *) logic [14:0] check_p_bytes;
 logic [18:0] check_v_bytes;
 logic [32:0] check_p_end,check_y_end,check_v_end;
 wire [31:0] final_status=status!=0?status:timeout_fault?32'(-7):stop_new||abort_publish?32'(-11):0;
 assign perf={64'b0,writes,computes,loads,ticks,read_bytes,write_bytes};
 always_comb completion={32'(generation),32'(generation),32'd0,32'd0,32'd0,final_status,
   64'(ticks-loads-computes-writes),writes,computes,loads,ticks,write_bytes,read_bytes,
   32'd0,32'd0,32'd1,32'd1,32'(final_status==0),final_status,
   d[13],d[12],d[11],d[10],32'd104,32'h4c4e3135,
   32'(native_quarantined),first_fault_address,32'd0,32'd2,epoch,32'd160,32'd1,32'h52364543};
 always_ff @(posedge clk or negedge platform_reset_n)begin
  if(!platform_reset_n)begin
   state<=IDLE;status<=0;ticks<=0;loads<=0;computes<=0;writes<=0;read_bytes<=0;write_bytes<=0;
   h<=0;dim<=0;dim_base<=0;t<=0;width<=0;row<=0;offset<=0;v_offset<=0;tree_mode<=0;left<=0;right<=0;value<=0;
   check_parts<=0;range_parts<=0;check_y_bytes<=0;check_p_bytes<=0;check_v_bytes<=0;
   check_p_end<=0;check_y_end<=0;check_v_end<=0;
   for(integer i=0;i<32;i++)d[i]<=0;
  end else if(reset_grant)begin state<=IDLE;status<=0;end
  else begin
   if(active)begin
    ticks<=ticks+1;
    if(state==READ_P||state==READ_P_WAIT||state==READ_V||state==READ_V_WAIT)loads<=loads+1;
    else if(state==WRITE_Y||state==WRITE_Y_WAIT)writes<=writes+1;
    else if(state>=A_REQ&&state<=OUT)computes<=computes+1;
   end
   if((stop_new||timeout_fault||abort_publish)&&active&&state!=DRAIN)begin
     status<=timeout_fault?-7:-11;state<=DRAIN;
   end else case(state)
    IDLE,DONE:if(submit&&!stop_new)begin
     for(integer i=0;i<32;i++)d[i]<=descriptor[32*i+:32];
     status<=0;ticks<=0;loads<=0;computes<=0;writes<=0;read_bytes<=0;write_bytes<=0;
     offset<=0;v_offset<=0;row<=0;h<=0;dim<=0;dim_base<=0;t<=0;tree_mode<=0;state<=CHECK;
    end
    CHECK:begin
     // Capture identity and P-window authority at the original CHECK cycle.
     // Each predicate group ends at a register; address sums are separate.
     check_parts[0]<=d[0]==32'h34364543&&d[1]==1&&d[2]==128&&d[3]==0;
     check_parts[1]<=d[4]==epoch&&epoch!=0&&d[5]==1&&d[6]==0&&d[7]==0;
     check_parts[2]<=d[8]==32'h4c4e3135&&d[9]==96&&
       (d[10]|d[11])!=0&&(d[12]|d[13])!=0;
     check_parts[3]<=d[14]==5&&d[15]==1&&d[16]==1&&d[17]>=1&&d[17]<=MAX_LENGTH;
     check_parts[4]<=d[24]>=1&&d[24]<=7&&d[25]>=d[17]&&d[25]<=MAX_LENGTH&&
       (d[25]&(d[25]-1))==0&&d[26]==512;
     check_parts[5]<=(d[21]|d[22]|d[23]|d[28]|d[29]|d[30]|d[31])==0&&d[27]<=1;
     check_parts[6]<=d[19][3:0]==0&&d[20][3:0]==0&&(local_p||d[18][3:0]==0)&&
       (!long_pv_calc||(d[20][7:0]==0&&d[18][8:0]==0));
     check_parts[7]<=!local_p||(d[17]<=64&&d[18]==0&&p_window_valid&&p_window_epoch==d[4]&&
       p_window_session=={d[11],d[10]}&&p_window_sequence=={d[13],d[12]}&&
       p_window_words==(d[24]<<6)&&p_window_len==d[17]&&p_window_padded==d[25]);
     check_y_bytes<={d[24][2:0],8'b0};
     check_p_bytes<=p_bytes_calc;
     check_v_bytes<={d[17][9:0],9'b0}-19'd256;
     state<=CHECK_ENDS;
    end
    CHECK_ENDS:begin
     // A 33-bit sum retains the carry out of the complete 32-bit base.  These
     // spans are used only after all full-width shape predicates have passed.
     check_p_end<={1'b0,d[18]}+{18'b0,check_p_bytes};
     check_y_end<={1'b0,d[19]}+{22'b0,check_y_bytes};
     check_v_end<={1'b0,d[20]}+{14'b0,check_v_bytes};
     if(!(&check_parts))begin status<=-4;state<=DRAIN;end
     else state<=CHECK_RANGE;
    end
    CHECK_RANGE:begin
     range_parts[0]<=(d[19]>=32'hac000000&&check_y_end<=33'h0b4000000)||
       (d[19]>=32'hba000000&&check_y_end<=33'h0bc000000);
     range_parts[1]<=d[20]>=32'ha8000000&&check_v_end<=33'h0a8f00000;
     range_parts[2]<=local_p||
       (d[18]>=32'hac000000&&check_p_end<=33'h0b4000000)||
       (d[18]>=32'hba000000&&check_p_end<=33'h0bc000000);
     range_parts[3]<=local_p||!({1'b0,d[18]}<check_y_end&&{1'b0,d[19]}<check_p_end);
     state<=CHECK_FINAL;
    end
    CHECK_FINAL:if(!(&range_parts))begin status<=-4;state<=DRAIN;end
      else state<=local_p?PREP_V:PREP_P;
    PREP_P:state<=READ_P;
    PREP_V:state<=READ_V;
    PREP_Y:state<=WRITE_Y;
    READ_P:if(dma_valid&&dma_ready)state<=READ_P_WAIT;
    READ_P_WAIT:if(dma_result_valid)begin
     if(dma_resp!=0)begin status<=-11;state<=DRAIN;end else begin
      read_bytes<=read_bytes+64'(command_bytes_q);
      if(offset+command_bytes_q==p_bytes)begin offset<=0;state<=PREP_V;end
      else begin offset<=offset+command_bytes_q;state<=PREP_P;end
     end
    end
    READ_V:if(dma_valid&&dma_ready)state<=READ_V_WAIT;
    READ_V_WAIT:if(dma_result_valid)begin
     if(dma_resp!=0)begin status<=-11;state<=DRAIN;end else begin
      read_bytes<=read_bytes+64'(command_bytes_q);
      if({1'b0,v_offset}+9'(command_bytes_q)==v_row_bytes)begin
       v_offset<=0;
       if(row+1==d[17])state<=A_REQ;
       else begin row<=row+1;state<=PREP_V;end
      end else begin v_offset<=v_offset+8'(command_bytes_q);state<=PREP_V;end
     end
    end
    A_REQ:state<=A_WAIT;
    A_WAIT:begin left<=local_p&&!tree_mode?p_window_q:ram_q[word_index[1:0]*32+:32];state<=B_REQ;end
    B_REQ:state<=B_WAIT;
    B_WAIT:begin right<=ram_q[word_index[1:0]*32+:32];state<=FP_SEND;end
    FP_SEND:if(left[30:23]==255||right[30:23]==255)begin status<=-9;state<=DRAIN;end
      else if(fp_start)state<=FP_WAIT;
    FP_WAIT:if(fp_valid)begin
     if(fp_result[30:23]==255)begin status<=-9;state<=DRAIN;end
     else begin value<=fp_result;state<=WORK;end
    end
    WORK:if(tree_mode)begin
     if(t+1==width)begin t<=0;width<=width>>1;state<=width==1?OUT:A_REQ;end
     else begin t<=t+1;state<=A_REQ;end
    end else if(t+1==d[17])begin
     if(d[17]<d[25])begin t<=t+1;state<=PAD;end
     else begin t<=0;width<=10'(d[25]>>1);tree_mode<=1;state<=d[25]==1?OUT:A_REQ;end
    end else begin t<=t+1;state<=A_REQ;end
    PAD:if(t+1==d[25])begin t<=0;width<=10'(d[25]>>1);tree_mode<=1;state<=A_REQ;end else t<=t+1;
    OUT:begin
     t<=0;tree_mode<=0;
     if(long_pv&&dim[3:0]==15)begin
      if(h+1==d[24])begin
       h<=0;
       if(dim==63)begin offset<=0;state<=PREP_Y;end
       else begin dim<=dim+1;dim_base<=6'(dim+1);row<=0;state<=PREP_V;end
      end else begin h<=h+1;dim<={1'b0,dim_base};state<=A_REQ;end
     end else if(dim==63)begin
      dim<=0;h<=h+1;
      if(h+1==d[24])begin offset<=0;state<=PREP_Y;end else state<=A_REQ;
     end else begin dim<=dim+1;state<=A_REQ;end
    end
    WRITE_Y:if(dma_valid&&dma_ready)state<=WRITE_Y_WAIT;
    WRITE_Y_WAIT:if(dma_result_valid)begin
     if(dma_resp!=0)begin status<=-11;state<=DRAIN;end else begin
      write_bytes<=write_bytes+64'(command_bytes_q);
      if({1'b0,offset}+command_bytes_q=={3'b0,y_bytes})state<=DRAIN;
      else begin offset<=offset+command_bytes_q;state<=PREP_Y;end
     end
    end
    DRAIN:if(dma_idle&&transport_drained&&fp_ready)state<=abort_publish?DONE:PUBLISH;
    PUBLISH:if(completion_ready)state<=DONE;
    default:begin status<=-11;state<=DRAIN;end
   endcase
  end
 end
endmodule
