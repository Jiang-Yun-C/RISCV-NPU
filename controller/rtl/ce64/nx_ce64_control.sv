// OPT10-R1: synchronous scratch bypass and validated group cache.
// CE64-S0 transport-compatible candidate: sequential rows and unchanged
// arithmetic. Each write remains one fully buffered DMA beat. These two
// independently removable transport optimizations require new qualification;
// they do not inherit the original bitstream's board acceptance.
module nx_ce64_control #(
  parameter bit SW_SCALE_BURST=1,
  parameter bit M1_OUTPUT_PACK=1,
  parameter bit M4_OUTPUT_PACK=1,
  parameter bit SA_SCALE_BURST=1,
  parameter bit WEIGHT_ROW_BURST=1,
  parameter bit SCRATCH_RESPONSE_BYPASS=1,
  parameter bit WEIGHT_GROUP_CACHE=1,
  parameter bit PIPELINED_RESTORE=1,
  parameter bit STREAM_GROUP_READS=1,
  parameter bit BULK_OUTPUT_BURST=1,
  parameter bit INLINE_M1_RESTORE=1,
  parameter bit BOUNDARY_SCRATCH_PREFETCH=1,
  parameter bit W_SW_STREAM=0,
  parameter bit W_PREFETCH=1,
  parameter bit A_W_BANKED=1,
  parameter bit SCRATCH_PREDICATES=0,
  parameter bit SCRATCH_SCALE_PREDICATES=0,
  parameter bit DEADLINE_CACHE=0
) (
  input logic clk, platform_reset_n, submit, reset_grant, stop_new, abort_publish,
  input wire resident_authorized,
  input wire resident_group_certified,resident_certificate_fault,
  input logic [1023:0] descriptor,
  input logic [31:0] epoch, generation, first_fault_address,
  input logic [63:0] run_limit,run_limit_next,
  input logic transport_drained, native_quarantined,
  output logic engine_idle, arithmetic_idle, scratch_idle, timeout_fault, call_fault,
  output logic [1279:0] completion,
  output logic completion_valid,
  output wire publication_phase,
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
  input logic [127:0] ram_q,
  input wire [15:0] ram_min80_q,ram_nonzero_q,
  input wire [15:0] ram_scale_zero_q,ram_scale_lo0_q,ram_scale_lo1_q
);
  import nx_ce64_math_pkg::*;
  typedef enum logic [6:0] {
    IDLE,DESC_START,DESC_WAIT,PRELOAD_A,PRELOAD_SA,VALIDATE_SA,VALIDATE_A,
    ROW_BEGIN,ROW_SW,ROW_BIAS,BIAS_CHECK,WEIGHT_SCALE,WEIGHT_LOAD,WEIGHT_CHECK,
    DOT_A,DOT_W,DOT_SEND,DOT_WAIT,DOT_SAVE,RESTORE_BEGIN,RESTORE_DOT,RESTORE_SA,
    RESTORE_SW,FP_SEND,FP_WAIT,AUDIT_SAVE,BIAS_BEGIN,BIAS_SEND,BIAS_WAIT,
    OUTPUT_BEGIN,OUTPUT_WRITE,AUDIT_BEGIN,AUDIT_WRITE,ROW_END,
    RAM_REQ,RAM_WAIT,DMA_REQ,DMA_WAIT,RAM_WRITE,DRAIN,PUBLISH,DONE,
    OUTPUT_PACK_TAIL,ROW_WEIGHT_LOAD,OUTPUT_M4_FLUSH,OUTPUT_M4_TAIL,FP_ROW_DRAIN,
    BULK_STORE,BULK_NEXT,BULK_FLUSH,BULK_TAIL_WRITE,INLINE_FP_SEND,INLINE_FP_DRAIN,STREAM_SW_BEGIN,STREAM_SW_WAIT,STREAM_W_WAIT,BANK_FP_SEND,BANK_FP_DRAIN,BULK_TAIL_CAPTURE
  } state_t;
  state_t state,return_state,write_return;
  wire submit_safe;
  wire fp_response_error,abort_now,dot_request_valid,fp_request_valid,bias_request_valid;
  logic [31:0] d [0:31];
  logic [1023:0] active_descriptor;
  logic desc_done,desc_busy;
  logic signed [31:0] desc_raw_status,desc_status,status;
  logic resident_group_active;
  wire certificate_fault=resident_certificate_fault===1'b1;
  always_ff @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)resident_group_active<=0;
    else if(reset_grant)resident_group_active<=0;
    else if((state==IDLE||state==DONE)&&submit_safe&&!stop_new&&!fp_response_error)
      resident_group_active<=resident_authorized===1'b1&&resident_group_certified===1'b1;
  end
  logic resident_active;
  always_ff @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)resident_active<=0;
    else if(reset_grant)resident_active<=0;
    else if((state==IDLE||state==DONE)&&submit_safe&&!stop_new&&!fp_response_error)
      resident_active<=resident_authorized===1'b1;
  end
  // A private resident marker never falls back to stale DDR data.
  always_comb desc_status=desc_raw_status!=0 ? desc_raw_status :
    (d[27]!=0&&!resident_active ? -32'sd1 : 32'sd0);
  logic [31:0] desc_diagnostic,desc_groups,desc_padded_k;
  // Used only after validation: G<=76, PK<=4864, mt<=4. Keep the full
  // 64-bit range checker, but do not infer unconstrained 32x32 address trees.
  wire [6:0] groups=desc_groups[6:0];
  wire [12:0] padded_k=desc_padded_k[12:0];
  logic [6:0][63:0] spans;
  nx_ce64_desc validate(.clk,.reset_n(platform_reset_n),.start(state==DESC_START&&!abort_now&&!abort_publish),
    .descriptor(active_descriptor),.expected_epoch(epoch),.done(desc_done),.busy(desc_busy),
    .status(desc_raw_status),.diagnostic(desc_diagnostic),.groups(desc_groups),.padded_k(desc_padded_k),.spans);
  logic [9:0] mb;
  logic [17:0] row;
  logic [2:0] mt,token,beat;
  logic [6:0] g;
  logic [15:0] offset;
  logic [31:0] count,transfer_count;
  logic [31:0] aq_base,sa_base,w_base,sw_base,bias_base,y_base,audit_cursor;
  logic [31:0] rows,tiles,bias_value,sa_value,sw_value,dot_value;
  // Capture the zero predicate on the same edge as its scale.  Keeping it
  // separate prevents the payload RAM read from feeding the weight-error
  // reduction and status enable in one cycle.  Logical equality retains X.
  logic sw_value_zero;
  // Preserve the zero comparison beside each Sa capture. The inline cache's
  // data register can be absorbed into its synchronous RAM read port; keeping
  // the predicate as independently stored metadata avoids a 32-bit read-side
  // equality feeding the activation-error reduction in that same cycle.
  logic sa_value_zero;
  logic [31:0] y [0:3];
  // Only a complete M1 call without audit may delay its scalar writes.
  // M4 has a separate per-token pack; audit remains immediately visible.
  wire pack_m1_output=M1_OUTPUT_PACK && d[15]==1 && d[28]==0;
  // Four token-local 16B accumulators. Only aligned rows are packed;
  // arbitrary strides/audit retain the scalar path. One DMA at a time.
  wire pack_m4_output=M4_OUTPUT_PACK && d[15]>1 && d[28]==0 && d[24][3:0]==0;
  logic [127:0] m4_data [0:3];
  logic [31:0] m4_address [0:3];
  logic [2:0] m4_count,m4_tail;
  logic [127:0] output_pack_data;
  wire bulk_output=BULK_OUTPUT_BURST&&d[28]==0&&(d[15]==1||d[24][3:0]==0);
  logic [7:0] bulk_count,bulk_rows;
  logic [9:0] bulk_offset;
  logic [31:0] bulk_base[0:3];
  wire [31:0] bulk_remaining=((32'(bulk_rows)<<2)-32'(bulk_offset))&32'hfffffff0;
  wire [31:0] bulk_limited=bulk_remaining>512?32'd512:bulk_remaining;
  wire [31:0] bulk_page_left=32'd4096-((bulk_base[token]+32'(bulk_offset))&32'd4095);
  wire [31:0] bulk_bytes=bulk_limited>bulk_page_left?bulk_page_left:bulk_limited;
  // Burst admission only needs min(remaining,512,page_left)>=16.
  // Evaluate this predicate directly, without serial page subtraction/min.
  // Keep the original relational result for all four-state input encodings.
  wire bulk_shape_known=((bulk_rows^bulk_rows)===8'b0)&&
    ((bulk_offset^bulk_offset)===10'b0)&&
    ((bulk_base[token]^bulk_base[token])===32'b0);
  wire [10:0] bulk_difference={1'b0,bulk_rows,2'b0}-{1'b0,bulk_offset};
  wire [11:0] bulk_page_address=bulk_base[token][11:0]+12'(bulk_offset);
  wire bulk_can_burst=bulk_shape_known ?
    ((bulk_difference[10] || (|bulk_difference[9:4])) &&
      ((bulk_page_address[11:4]!=8'hff) || (bulk_page_address[3:0]==0))) :
    (bulk_bytes>=16);
  logic [31:0] output_pack_address;
  logic [2:0] output_pack_count,output_pack_tail;
  // Consume the synchronous SRAM response directly after RAM_REQ.
  logic [127:0] activation_data,weight_data;
  wire [127:0] scratch_read_data;
  wire [127:0] weight_check_data,restore_sw_data,restore_sw_raw_data;
  // Validated weights: four registers, no additional SRAM port or DMA overlap.
  logic [127:0] weight_group [0:3];
  wire [15:0] weight_local_base=WEIGHT_ROW_BURST ? 16'h8000+16'(g*64) : 16'h8000;
  logic [15:0] local_read_address,local_write_address,local_write_mask;
  logic [127:0] local_write_data;
  // Classify each byte window before selecting its one-bit result. The
  // original 32-bit payload selection still feeds the numeric registers.
  // Explicit X padding matches an out-of-range variable part-select, and an
  // unknown byte index yields X in both formulations; no alignment premise.
  wire [151:0] read_scale_windows={24'bx,scratch_read_data};
  wire [18:0] read_scale_zeros={3'bx,ram_scale_zero_q};
  wire [18:0] read_scale_lo0={3'bx,ram_scale_lo0_q};
  wire [18:0] read_scale_lo1={3'bx,ram_scale_lo1_q};
  wire [15:0] read_scale_by_byte;
  generate for(genvar scale_byte=0;scale_byte<16;scale_byte++)begin: scale_window_predicates
    if(SCRATCH_SCALE_PREDICATES && SCRATCH_RESPONSE_BYPASS)begin: cached_byte_classification
      // exp[0] is the preceding byte's sign bit. The high byte has two
      // preclassified normal-scale results, one for each value of exp[0].
      // Ternary merge is exact for X/Z exp[0]; no alignment premise is used.
      assign read_scale_by_byte[scale_byte]=(&read_scale_zeros[scale_byte+:4]) ||
        (read_scale_windows[(scale_byte+2)*8+7] ?
          read_scale_lo1[scale_byte+3] : read_scale_lo0[scale_byte+3]);
    end else begin: original_word_classification
      assign read_scale_by_byte[scale_byte]=scale32(read_scale_windows[scale_byte*8+:32]);
    end
  end endgenerate
  // Scale validation is consumed only in VALIDATE_SA and WEIGHT_SCALE.
  // Both are synchronous scratch responses, independent of a Sw revoke.
  wire read_scale_valid=read_scale_by_byte[local_read_address[3:0]];
  logic [1:0] phase;
  logic restoring;
  logic fp_abort_pending;
  logic [63:0] ticks,load_ticks,compute_ticks,write_ticks,restore_ticks;
  wire [63:0] ticks_next;
  logic deadline_ge;
  wire deadline_expired=DEADLINE_CACHE ? deadline_ge : (run_limit!=0 && ticks>=run_limit);
  logic [63:0] payload_read,payload_write;
  // Parallel byte carries keep a late completion/abort predicate out of
  // a 64-bit ripple chain. This is the same modulo-2^64 sum for every
  // 32-bit quantum; no bound on the counter or increment is assumed.
  function automatic [63:0] payload_add(input logic [63:0] prior,input logic [31:0] amount);
    logic [8:0] sums[0:7];
    logic [7:0] carries;
    logic term;
    begin
      if(((prior^prior)!==64'b0)||((amount^amount)!==32'b0))begin
        // A Verilog wide add propagates any X/Z through the entire word.
        payload_add=prior+amount;
      end else begin
        for(integer b=0;b<8;b++)begin
          if(b<4)sums[b]={1'b0,prior[8*b+:8]}+{1'b0,amount[8*b+:8]};
          else sums[b]={1'b0,prior[8*b+:8]};
        end
        carries=0;
        for(integer b=1;b<8;b++)begin
          for(integer j=0;j<b;j++)begin
            term=sums[j][8];
            for(integer k=j+1;k<b;k++)term=term&&(&sums[k][7:0]);
            carries[b]=carries[b]||term;
          end
        end
        for(integer b=0;b<8;b++)payload_add[8*b+:8]=sums[b][7:0]+8'(carries[b]);
      end
    end
  endfunction
  logic cmd_write;
  logic [31:0] cmd_address;
  logic [2:0] cmd_size;
  logic [4:0] cmd_len;
  logic [15:0] cmd_scratch,cmd_mask;
  logic [127:0] cmd_data;
  logic [31:0] chunk_bytes;
  logic [6:0] group_elements;
  logic [31:0] valid_lanes;
  wire [6:0] lanes_remaining=group_elements-{beat,4'b0};
  logic [31:0] index;
  logic bad_activation,bad_weight;
  logic [15:0] dot_keep;
  logic dot_ready,dot_valid,dot_live,dot_bad,dot_protocol,nonzero_a,nonzero_w;
  logic signed [31:0] dot_result;
  logic [31:0] dot_tag,dot_epoch;
  logic fp_ready,fp_valid,fp_idle;
  logic run_active;
  wire state_idle=state==IDLE || state==DONE;
  logic bias_ready,bias_valid,bias_live;
  wire fp_raw_valid,fp_raw_idle,bias_raw_valid;
  wire [31:0] fp_raw_p,fp_raw_v,fp_raw_partial,fp_raw_tag,fp_raw_epoch,bias_raw_result;
  wire [1:0] fp_raw_context;
  wire fp_raw_last,bias_raw_aux;
  wire [3:0] fp_raw_status;
  wire [4:0] fp_raw_flags,bias_raw_flags;
  wire [63:0] bias_raw_tag;
  logic fp_serial_bad_q,fp_stream_bad_q,fp_bank_bad_q,fp_unexpected_q,bias_bad_q;
  logic fp_cancel_q,bias_cancel_q,fp_stream_q,fp_bank_q;
  logic [2:0] fp_token_q,bias_token_q;
  logic [31:0] fp_dot_q;
  wire response_pending=fp_raw_valid||fp_valid||bias_raw_valid||bias_valid;
  wire response_accept_idle=fp_raw_idle&&!response_pending&&!bias_live;
  assign submit_safe=submit&&response_accept_idle&&!run_active&&!fp_abort_pending&&!reset_grant;
  wire submit_collision=submit&&!submit_safe;
  wire submit_collision_job=submit_collision&&state_idle&&!run_active&&!reset_grant;
  wire response_cancel_now=!run_active||reset_grant||stop_new||timeout_fault||fp_abort_pending||
      certificate_fault||fp_response_error;
  assign fp_idle=fp_raw_idle&&!fp_raw_valid&&!fp_valid;
  wire fp_stream_response=fp_valid&&fp_stream_q;
  wire fp_bank_response=fp_valid&&fp_bank_q;
  wire fp_serial_response_bad=fp_serial_bad_q||fp_cancel_q||response_cancel_now;
  wire bias_response_bad=bias_bad_q||bias_cancel_q||response_cancel_now;
  logic [31:0] fp_p,fp_v,fp_partial,fp_tag,fp_epoch;
  // Preserve the raw-time byte epoch checks. Their verdict is registered
  // atomically with the complete response before any control consumes it.
  (* keep=1, syn_keep=1 *) wire [3:0] fp_epoch_byte_match;
  generate for(genvar eb=0;eb<4;eb++)begin:response_epoch_compare
    assign fp_epoch_byte_match[eb]=fp_raw_epoch[8*eb+:8]==epoch[8*eb+:8];
  end endgenerate
  wire fp_raw_epoch_bad=!(&fp_epoch_byte_match);
  logic fp_last;
  // These descriptor-only predicates are captured in the very same reset
  // and accepted-submit branches as d[]. No preparation window is required.
  logic descriptor_no_audit_q,descriptor_inline_restore_q,descriptor_bank_rows_q;
  wire stream_restore=PIPELINED_RESTORE && descriptor_no_audit_q;
  wire inline_restore=INLINE_M1_RESTORE&&PIPELINED_RESTORE&&descriptor_inline_restore_q;
  logic [31:0] m1_sa_cache[0:75];
  logic m1_sa_zero_cache[0:75];
  logic [75:0] m1_sa_valid;
  logic [6:0] fp_expected_group;
  logic [3:0] fp_status;
  logic [4:0] fp_flags;
  logic [31:0] bias_result;
  logic [4:0] bias_flags;
  logic [63:0] bias_tag;
  logic bias_aux;
  wire stream_group=STREAM_GROUP_READS && SCRATCH_RESPONSE_BYPASS && WEIGHT_GROUP_CACHE;
  wire weight_read_next=stream_group && state==WEIGHT_CHECK && !abort_now && (beat+1)*16<group_elements;
  wire activation_read_next=stream_group && state==DOT_A && dot_request_valid && dot_ready && (beat+1)*16<group_elements;
  // Only the M1/no-audit stream can consume these reads next cycle. The
  // last weight predicate is still checked before any DOT request is offered.
  // Reading a validated Aq address speculatively has no publication effect.
  wire boundary_prefetch=BOUNDARY_SCRATCH_PREFETCH&&stream_group&&inline_restore;
  wire first_a_read=boundary_prefetch&&state==WEIGHT_CHECK&&!abort_now&&
      (beat+1)*16>=group_elements;
  logic stream_active;
  // Priority5: the A side is the existing synchronous scratch port and the W
  // side is the independently clocked certified ping/pong read port. M2-M4
  // consumes both directly, rather than copying W into registers before DOT.
  // The four token outputs of the SAME N row are interleaved group-major.
  wire bank_active=A_W_BANKED&&W_PREFETCH&&stream_active&&descriptor_bank_rows_q;
  logic [1:0] bank_response_context;
  logic [6:0] bank_expected[0:3];
  // Private response metadata advances atomically with the corresponding
  // ordered group. Legal M2-M4 calls have G<=76, so G*M+context <= 307.
  // Keeping this tag next to the group removes a multiply/add from the
  // immediate bad-response -> abort/revoke/completion control cone.
  logic [8:0] bank_expected_tag[0:3];
  logic [31:0] bank_sa_cache[0:303];
  logic [303:0] bank_sa_valid;
  wire [8:0] bank_sa_index=9'(address_mul_u3(32'(groups),token)+32'(g));
  // Compare all independent contexts before selecting one predicate bit.
  // A packed unknown context selects X exactly like the old unknown tag word.
  (* keep=1, syn_keep=1 *) wire [3:0] bank_tag_low_match;
  (* keep=1, syn_keep=1 *) wire [2:0] bank_tag_high_match;
  generate for(genvar btc=0;btc<4;btc++)begin:bank_tag_compare
    // Include the older validated response consumed on this same edge.
    wire advance=fp_bank_response&&!fp_bank_bad_q&&bank_response_context==2'(btc);
    wire [8:0] expected=bank_expected_tag[btc]+(advance?9'(mt):9'b0);
    assign bank_tag_low_match[btc]=fp_raw_tag[8:0]==expected;
  end endgenerate
  assign bank_tag_high_match[0]=fp_raw_tag[16:9]==0;
  assign bank_tag_high_match[1]=fp_raw_tag[24:17]==0;
  assign bank_tag_high_match[2]=fp_raw_tag[31:25]==0;
  wire bank_raw_tag_bad=!(&bank_tag_high_match)||!bank_tag_low_match[fp_raw_context];
  wire bank_raw_advance=fp_bank_response&&!fp_bank_bad_q&&bank_response_context==fp_raw_context;
  wire [6:0] bank_raw_expected=bank_expected[fp_raw_context]+7'(bank_raw_advance);
  wire fp_raw_nonfinite=!finite32(fp_raw_p)||!finite32(fp_raw_v)||!finite32(fp_raw_partial);
  wire bank_raw_response_bad=fp_raw_status!=0||fp_raw_nonfinite||fp_raw_epoch_bad||
    bank_raw_tag_bad||fp_raw_context>=mt||bank_raw_expected>=groups||
    fp_raw_last!=(bank_raw_expected+1==groups);
  wire bank_response_bad=fp_bank_bad_q;
  wire bank_all_restored=bank_expected[0]==groups&&
    (mt<2||bank_expected[1]==groups)&&(mt<3||bank_expected[2]==groups)&&
    (mt<4||bank_expected[3]==groups);
  wire counter_clear;
  wire next_sw_read=!stream_active&&boundary_prefetch&&state==INLINE_FP_SEND&&fp_ready&&
      fp_request_valid&&g+7'd1<groups;

  // This path is enabled only after the original descriptor validator succeeds.
  logic [31:0] stream_epoch,stream_generation;
  wire stream_identity_bad=stream_active&&(epoch!==stream_epoch||generation!==stream_generation);
  wire stream_eligible=W_SW_STREAM&&(inline_restore||(W_PREFETCH&&stream_restore&&descriptor_bank_rows_q))&&stream_group&&WEIGHT_ROW_BURST&&bulk_output&&d[17][5:0]==0&&d[18][5:0]==0;
  wire [127:0] stream_owner={d[13],d[12],d[11],d[10]};
  wire sw_start_ready,sw_fragment_ready,sw_active,sw_bad,sw_certificate,sw_fragment_pending;
  wire [8:0] sw_filled;
  wire [17:0] sw_first_row;
  wire [2:0] sw_rows;
  wire [6:0] sw_groups;
  wire [127:0] sw_owner;
  wire [31:0] sw_epoch,sw_generation;
  // Descriptor validation proves N<=151936 before this stream can start.
  // The extra bit preserves the old unsigned-underflow/cap behavior too.
  wire [18:0] stream_rows_left={1'b0,d[16][17:0]}-{1'b0,row};
  // Dropped upper bits must not hide an unknown or out-of-range descriptor.
  wire stream_rows_shape_known=((d[16]^d[16])===32'b0)&&(d[16][31:18]===14'b0);
  wire [2:0] stream_rows_plan=!stream_rows_shape_known ? 3'd0 :
      (stream_rows_left>19'd4 ? 3'd4 : stream_rows_left[2:0]);
  // ROW_BEGIN and ROW_WEIGHT_LOAD precede a new Sw block start. Prepare
  // its row count in those existing cycles, before the Sw word-count
  // product/start legality check; no stream state or handshake is delayed.
  logic [2:0] stream_rows;
  always_ff @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)stream_rows<=0;
    else stream_rows<=stream_rows_plan;
  end
  // The Sw block captures this count at sw_start.  Using that register here
  // removes live row subtraction/multiplication from the DMA request cone.
  // Filling holds row fixed; subsequent rows reuse a completed certificate.
  wire [8:0] sw_total_words;
  wire sw_start=stream_active&&state==STREAM_SW_BEGIN&&row[1:0]==0&&sw_start_ready&&!abort_now;
  wire [31:0] sw_address=sw_base+32'(sw_filled)*4;
  wire [8:0] sw_left=sw_total_words-sw_filled;
  wire [8:0] sw_offer_plan_filled_words,sw_offer_plan_total_words;
  wire [31:0] sw_offer_plan_address=sw_base+32'(sw_offer_plan_filled_words)*4;
  wire [8:0] sw_offer_plan_left=sw_offer_plan_total_words-sw_offer_plan_filled_words;
  logic [2:0] sw_command_size_plan;
  logic [5:0] sw_command_beats_plan;
  logic [8:0] sw_command_words_plan;
  wire [4:0] sw_line_bytes=5'd16-{1'b0,sw_offer_plan_address[3:0]};
  wire [2:0] sw_line_words=sw_line_bytes[4:2];
  wire [5:0] sw_full_beats=sw_offer_plan_left[8:2]>7'd32 ? 6'd32 : sw_offer_plan_left[7:2];
  // A burst is at most 32 aligned 16-byte beats.  Only the final 512
  // bytes of a 4-KiB page can reduce that limit.
  wire [5:0] sw_page_beats=(&sw_offer_plan_address[11:9]) ?
      6'd32-{1'b0,sw_offer_plan_address[8:4]} : 6'd32;
  always_comb begin
    if(sw_offer_plan_address[3:0]!=0)begin
      sw_command_size_plan=2;
      sw_command_words_plan=sw_offer_plan_left>{6'b0,sw_line_words} ? {6'b0,sw_line_words} : sw_offer_plan_left;
      sw_command_beats_plan=sw_command_words_plan[5:0];
    end else if(sw_offer_plan_left>=4)begin
      sw_command_size_plan=4;
      sw_command_beats_plan=sw_full_beats>sw_page_beats ? sw_page_beats : sw_full_beats;
      sw_command_words_plan={1'b0,sw_command_beats_plan,2'b0};
    end else begin
      sw_command_size_plan=2;sw_command_words_plan=sw_offer_plan_left;sw_command_beats_plan=sw_offer_plan_left[5:0];
    end
  end
  // Capture the command for the next eligible offer in the existing drain
  // window. The start edge supplies the new block count, and a pending
  // fragment supplies its reserved end offset before physical retirement.
  // All original DMA/Sw boundary checks still inspect the accepted command.
  logic [2:0] sw_command_size;
  logic [5:0] sw_command_beats;
  logic [8:0] sw_command_words;
  always_ff @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)begin
      sw_command_size<=0;sw_command_beats<=0;sw_command_words<=0;
    end else begin
      sw_command_size<=sw_command_size_plan;
      sw_command_beats<=sw_command_beats_plan;
      sw_command_words<=sw_command_words_plan;
    end
  end
  (* keep=1,syn_keep=1 *) wire [15:0] sw_block_owner_match_bytes;
  generate for(genvar ob=0;ob<16;ob++)begin:sw_block_owner_compare
    assign sw_block_owner_match_bytes[ob]=sw_owner[8*ob+:8]===stream_owner[8*ob+:8];
  end endgenerate
  wire sw_block_matches=sw_first_row=={row[17:2],2'b0}&&sw_groups==groups&&
      (&sw_block_owner_match_bytes)&&sw_epoch==epoch&&sw_generation==generation;
  wire sw_issue=stream_active&&state==STREAM_SW_WAIT&&!sw_certificate&&!sw_bad&&
      sw_block_matches&&sw_left!=0&&sw_fragment_ready&&!abort_now;
  logic sw_command_pending,w_command_pending;
  logic [31:0] stream_chunk_bytes;
  logic w_running,w_next_bank;
  logic [6:0] w_offer_group;
  logic [6:0] w_first[2];
  // Cached modulo-128 end, written atomically with first/groups. The
  // selected-bank range has seven-bit arithmetic in the original RTL.
  logic [6:0] w_end[2];
  logic [3:0] w_groups[2];
  logic [17:0] w_row[2];
  logic [63:0] w_tags[2];
  wire [31:0] w_address=w_base+32'(w_offer_group)*64;
  // Seven-bit operands need eight subtraction bits to retain unsigned
  // underflow before capping at four, including inactive request values.
  wire [7:0] w_left={1'b0,groups}-{1'b0,w_offer_group};
  localparam integer W_GROUPS=W_PREFETCH ? 8 : 4;
  // M1 uses 256B quanta; M2-M4 retains the 512B prefetch quantum.
  // The physical synchronous W banks and all certification remain shared.
  wire [3:0] w_group_cap=inline_restore ? 4'd4 : 4'(W_GROUPS);
  wire [3:0] w_group_limit=w_left>{4'b0,w_group_cap} ? w_group_cap : w_left[3:0];
  // At most four 64-byte groups: only the final 256 page bytes matter.
  // The low-bit term retains the original floor for unaligned addresses.
  wire [3:0] w_page_limit=W_PREFETCH ? ((&w_address[11:9]) ?
      4'd8-{1'b0,w_address[8:6]}-{3'b0,(|w_address[5:0])} : 4'd8) :
      ((&w_address[11:8]) ? 4'd4-{2'b0,w_address[7:6]}-{3'b0,(|w_address[5:0])} : 4'd4);
  wire [3:0] w_count_plan=w_group_limit>w_page_limit ? w_page_limit : w_group_limit;
  // Prepare the next W quantum while its predecessor owns the DMA.  A row
  // resets w_offer_group before W can run, and a W acceptance keeps
  // w_command_pending asserted through AR/R/result.  Thus every offered W
  // command sees the plan from a stable preceding cycle, with no added wait.
  // This register cuts the group/page arithmetic before the Sw query-valid
  // and DMA scale checks; those checks retain their independent contracts.
  logic [3:0] w_count;
  always_ff @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)w_count<=0;
    else w_count<=w_count_plan;
  end
  wire w_window=state==STREAM_W_WAIT||state==DOT_A||state==DOT_WAIT||state==INLINE_FP_SEND||state==BANK_FP_SEND||
      (W_PREFETCH&&!inline_restore&&(state==WEIGHT_CHECK||state==DOT_SAVE||state==RAM_WRITE));
  wire [255:0] sw_next_scales,sw_raw_next_scales;
  wire sw_next_valid,sw_value_valid;
  // A completed Sw certificate reaches ROW_BIAS before STREAM_W_WAIT;
  // w_running then supplies another preparation edge. Later W offers are
  // separated by the non-cancellable DMA lifetime. Prepare the next scale
  // vector in those existing cycles so query validity/RAM read does not
  // feed the independent DMA scale32 reduction in the acceptance cycle.
  logic [255:0] w_scales;
  always_ff @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)w_scales<=0;
    else w_scales<=sw_raw_next_scales;
  end
  wire [31:0] sw_current_value,sw_raw_current_value;
  wire sw_current_zero,sw_raw_current_zero;
  wire w_issue=stream_active&&w_running&&w_window&&w_offer_group<groups&&w_count!=0&&
      !capture_held[w_next_bank]&&sw_next_valid&&!abort_now&&!w_command_pending&&!sw_command_pending;
  wire stream_command=sw_issue||w_issue;
  wire stream_accept=stream_command&&dma_ready;
  wire stream_result=(w_command_pending||sw_command_pending)&&dma_result_valid&&dma_result_ready;
  wire selected0=capture_held[0]&&capture_certificate[0]&&w_row[0]==row&&g>=w_first[0]&&g<w_end[0];
  wire selected1=capture_held[1]&&capture_certificate[1]&&w_row[1]==row&&g>=w_first[1]&&g<w_end[1];
  wire w_available=(selected0^selected1)&&sw_value_valid&&sw_block_matches;
  wire stream_first_a=stream_active&&state==STREAM_W_WAIT&&w_available&&!abort_now;
  // Prepare the next group's Sw response while DOT retires. Current Sw is
  // already held in sw_value; it remains the operand of the current FP issue.
  wire m1_lookahead=stream_active&&inline_restore&&g+7'd1<groups;
  wire [6:0] m1_next_group=g+7'd1;
  wire [6:0] sw_value_group=m1_lookahead&&(state==DOT_WAIT||state==INLINE_FP_SEND) ? m1_next_group : g;
  wire m1_next0=capture_held[0]&&capture_certificate[0]&&w_row[0]==row&&m1_next_group>=w_first[0]&&m1_next_group<w_end[0];
  wire m1_next1=capture_held[1]&&capture_certificate[1]&&w_row[1]==row&&m1_next_group>=w_first[1]&&m1_next_group<w_end[1];
  // The only removed state is the already-satisfied W/Sw rendezvous. If
  // either lease/data response is unavailable, use the original wait path.
  wire m1_next_start=m1_lookahead&&state==INLINE_FP_SEND&&fp_ready&&fp_request_valid&&
      (m1_next0^m1_next1)&&sw_value_valid&&sw_block_matches&&!abort_now;
  wire stream_fault=(certificate_fault&&!state_idle&&state!=DRAIN&&state!=PUBLISH)||stream_active&&!state_idle&&state!=DRAIN&&state!=PUBLISH&&((sw_bad&&sw_block_matches)||(|capture_bad)||stream_identity_bad||
      (((inline_restore||bank_active)&&state==DOT_A||!inline_restore&&!bank_active&&state==WEIGHT_CHECK)&&!abort_now&&capture_mask!==16'hffff));
  assign capture_owner=stream_owner;
  assign capture_revoke=abort_now||abort_publish||reset_grant||stream_identity_bad;
  assign dma_w_capture=w_issue;
  assign dma_sw_capture=sw_issue;
  assign dma_capture_bank=w_next_bank;
  assign capture_command_tag={35'b0,row,w_offer_group,w_count};
  assign capture_command_scales=w_scales;
  assign capture_peek_bank=selected0?1'b0:1'b1;
  assign capture_peek_beat=5'((g-w_first[capture_peek_bank])*4+beat);
  assign capture_peek_tag=w_tags[capture_peek_bank];
  for(genvar b=0;b<2;b++)begin: w_parallel_read_address
    // Synchronous bank address is advanced on the same edge that consumes
    // the current response. WAIT primes beat0; stalled consumers hold address.
    wire advance=W_PREFETCH&&(((inline_restore||bank_active)&&state==DOT_A&&dot_request_valid&&dot_ready&&beat<3)||
        (!inline_restore&&state==WEIGHT_CHECK&&beat<3));
    assign capture_raw_beats[5*b+:5]=m1_lookahead&&state==INLINE_FP_SEND ?
      5'((m1_next_group-w_first[b])*4) :
      5'((g-w_first[b])*4+((state==STREAM_W_WAIT||state==BANK_FP_SEND)?0:beat)+(advance?1:0));
  end
  always_comb begin
    capture_release=0;
    // A lease ends only after the final necessary W operand is accepted by DOT.
    if(stream_active&&state==DOT_A&&dot_request_valid&&dot_ready&&beat==3&&
        g+1==w_first[capture_peek_bank]+w_groups[capture_peek_bank]&&
        (inline_restore||token+1==mt))
      capture_release[capture_peek_bank]=1;
    // Revoked consumers release only completed DMA leases; accepted R still drains.
    if(state==DRAIN||abort_now)capture_release=capture_result_seen;
  end
  nx_ce64_sw_capture #(.W_PREFETCH(W_PREFETCH),.PLANNED_PAYLOAD(1)) sw_cache(
    .clk,.reset_n(platform_reset_n),.start(sw_start),.start_ready(sw_start_ready),
    .plan_start_hint(stream_active&&state==STREAM_SW_BEGIN&&row[1:0]==0),
    .value_raw_scale(sw_raw_current_value),.value_raw_zero(sw_raw_current_zero),.query_raw_scales(sw_raw_next_scales),
    .start_first_row(row),.start_rows(stream_rows),.start_groups(groups),
    .live_owner(stream_owner),.live_epoch(epoch),.live_generation(generation),
    .stop_new(stop_new||timeout_fault),.revoke(capture_revoke),.transport_fault(native_quarantined),
    .transport_idle(capture_physical_idle&&transport_drained),.no_w_held(!(|capture_held)),
    .fragment_begin(stream_accept&&sw_issue),.fragment_ready(sw_fragment_ready),
    .fragment_address(sw_address),.fragment_len(5'(sw_command_beats-1)),
    .fragment_size(sw_command_size),.fragment_word_offset(sw_filled),
    .r_take(capture_r_take),.r_data(capture_r_data),.r_id(capture_r_id),.r_resp(capture_r_resp),.r_last(capture_r_last),
    .result_take(stream_result&&sw_command_pending),.result_resp(dma_resp),
    .query_row(row[1:0]),.query_group(w_offer_group),.query_count(w_count),
    .query_scales(sw_next_scales),.query_valid(sw_next_valid),
    .value_row(row[1:0]),.value_group(sw_value_group),.value_scale(sw_current_value),.value_zero(sw_current_zero),.value_valid(sw_value_valid),
    .active(sw_active),.bad(sw_bad),.certificate(sw_certificate),.fragment_pending(sw_fragment_pending),.filled_words(sw_filled),
    .block_first_row(sw_first_row),.block_rows(sw_rows),.block_groups(sw_groups),
    .block_owner(sw_owner),.block_epoch(sw_epoch),.block_generation(sw_generation),.block_words(sw_total_words),
    .offer_plan_filled_words(sw_offer_plan_filled_words),.offer_plan_total_words(sw_offer_plan_total_words));
  always_ff @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)begin
      stream_active<=0;stream_epoch<=0;stream_generation<=0;
      sw_command_pending<=0;w_command_pending<=0;stream_chunk_bytes<=0;
      w_running<=0;w_next_bank<=0;w_offer_group<=0;
      for(integer b=0;b<2;b++)begin w_first[b]<=0;w_end[b]<=0;w_groups[b]<=0;w_row[b]<=0;w_tags[b]<=0;end
    end else begin
      // A completed linear command must retire its stream identity before another engine submits.
      if(counter_clear||reset_grant||state==DONE)stream_active<=0;
      if(state==DESC_WAIT&&desc_done&&desc_status==0)begin
        stream_active<=stream_eligible;stream_epoch<=epoch;stream_generation<=generation;
      end
      if(state==ROW_BEGIN)begin w_running<=0;w_next_bank<=0;w_offer_group<=0;end
      if(stream_active&&state==STREAM_W_WAIT&&!w_running)w_running<=1;
      if(stream_accept)begin
        stream_chunk_bytes<=sw_issue?{21'b0,sw_command_words,2'b0}:32'(w_count)*64;
        if(sw_issue)sw_command_pending<=1;
        else begin
          w_command_pending<=1;w_first[w_next_bank]<=w_offer_group;
          w_end[w_next_bank]<=w_offer_group+7'(w_count);
          w_groups[w_next_bank]<=w_count;w_row[w_next_bank]<=row;
          w_tags[w_next_bank]<=capture_command_tag;
          w_offer_group<=w_offer_group+7'(w_count);w_next_bank<=!w_next_bank;
        end
      end
      if(stream_result)begin sw_command_pending<=0;w_command_pending<=0;end
      if(state==DRAIN)w_running<=0;
    end
  end

  // Keep the consumption ledger and capture-side expectation separate.
  // Capture validates against the progress of an older buffered response
  // consumed on this edge; the physical arithmetic order remains unchanged.
  logic [31:0] fp_response_expected_tag;
  logic [6:0] fp_expected_group_next;
  always_ff @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)fp_response_expected_tag<=0;
    else fp_response_expected_tag<=index_small(fp_expected_group_next,mt,token);
  end
  // Capture-side expectation includes the older tuple consumed this edge.
  wire [31:0] fp_capture_expected_tag=index_small(fp_expected_group_next,mt,token);
  (* keep=1, syn_keep=1 *) wire [3:0] fp_tag_byte_match;
  generate for(genvar ftb=0;ftb<4;ftb++)begin:fp_tag_compare
    assign fp_tag_byte_match[ftb]=fp_raw_tag[8*ftb+:8]==fp_capture_expected_tag[8*ftb+:8];
  end endgenerate
  wire fp_raw_stream_bad=fp_raw_status!=0 || fp_raw_nonfinite || fp_raw_epoch_bad || !(&fp_tag_byte_match);
  wire fp_raw_serial_bad=fp_raw_status!=0 || fp_raw_nonfinite || fp_raw_tag!=index || fp_raw_epoch_bad;
  wire bias_raw_bad=!finite32(bias_raw_result) || bias_raw_tag!={epoch,29'b0,token};
  wire fp_bad_response=fp_stream_bad_q||fp_cancel_q||response_cancel_now;
  // Identical occupancy and modulo64 values, without a phase-enable path
  // feeding a 64-bit carry chain. Flags describe the CURRENT lower limbs.
  assign fp_response_error=(fp_valid&&(fp_unexpected_q||
      (fp_bank_q?fp_bank_bad_q:fp_stream_q?fp_stream_bad_q:fp_serial_bad_q)))||
      (bias_valid&&bias_bad_q)||submit_collision;
  assign abort_now=stop_new||timeout_fault||fp_abort_pending||fp_response_error||certificate_fault;
  assign dot_request_valid=(state==DOT_SEND||(stream_group&&state==DOT_A))&&(!abort_now||dot_live);
  assign fp_request_valid=(state==FP_SEND||state==INLINE_FP_SEND||state==BANK_FP_SEND)&&!abort_now;
  assign bias_request_valid=state==BIAS_SEND&&!abort_now;
  // Metadata checking does not drive the global data-register priority mux.
  // Reject new offers immediately; drain an already accepted partial dot.
  wire control_abort=(fp_abort_pending&&run_active&&!dot_live&&state!=DRAIN)||
      ((stop_new||timeout_fault)&&!state_idle&&state!=DRAIN&&state!=PUBLISH&&!dot_live);
  wire counter_enable=!state_idle && state!=PUBLISH;
  assign counter_clear=(state==IDLE||state==DONE)&&submit_safe&&!stop_new&&
      !(stream_restore&&fp_valid&&restoring&&fp_bad_response);
  nx_ce64_phase_counter64 total_counter(.clk,.reset_n(platform_reset_n),.clear(counter_clear),.enable(counter_enable),.value(ticks),.value_next(ticks_next));
  nx_ce64_phase_counter64 load_counter(.clk,.reset_n(platform_reset_n),.clear(counter_clear),.enable(counter_enable&&phase==1),.value(load_ticks));
  nx_ce64_phase_counter64 compute_counter(.clk,.reset_n(platform_reset_n),.clear(counter_clear),.enable(counter_enable&&phase==2),.value(compute_ticks));
  nx_ce64_phase_counter64 write_counter(.clk,.reset_n(platform_reset_n),.clear(counter_clear),.enable(counter_enable&&phase==3),.value(write_ticks));
  nx_ce64_phase_counter64 restore_counter(.clk,.reset_n(platform_reset_n),.clear(counter_clear),.enable(counter_enable&&restoring),.value(restore_ticks));
  assign index=index_small(g,mt,token);
  // Only consumed after descriptor validation: 1<=K<=4864, g<G.
  // Latch before weight-byte checks to remove g -> 32-bit subtracts -> cache CE.
  assign valid_lanes=lanes_remaining>7'd16 ? 32'd16 : 32'(lanes_remaining);
  // Exact unsigned modular products for the physical small coefficient.
  // Reduction parity is X iff an operand has X/Z; ordinary case preserves
  // the original SV multiply all-X result. No binary hardware range assumption.
  function automatic [31:0] address_mul_u3(input logic [31:0] a,input logic [2:0] b);
    begin
      case({^a,^b})
        2'b00,2'b01,2'b10,2'b11:address_mul_u3=(a & {32{b[0]}}) + ((a << 1) & {32{b[1]}}) + ((a << 2) & {32{b[2]}});
        default:address_mul_u3=32'bx;
      endcase
    end
  endfunction
  // The complete encoded domain is g<=127, m/t<=7, so g*m+t<=896.
  // Carry-save reduction removes the three serial carry chains from the
  // live DOT/restore tag. Unknown operands retain the original 32-bit math.
  function automatic [31:0] index_small(input logic [6:0] group_number,
      input logic [2:0] m,tok);
    logic [9:0] p0,p1,p2,s0,c0,s1,c1,t;
    begin
      case({^group_number,^m,^tok})
        3'b000,3'b001,3'b010,3'b011,3'b100,3'b101,3'b110,3'b111:begin
          p0=10'(group_number)&{10{m[0]}};
          p1=(10'(group_number)<<1)&{10{m[1]}};
          p2=(10'(group_number)<<2)&{10{m[2]}};
          s0=p0^p1^p2;c0=((p0&p1)|(p0&p2)|(p1&p2))<<1;
          t=10'(tok);s1=s0^c0^t;c1=((s0&c0)|(s0&t)|(c0&t))<<1;
          index_small={22'b0,10'(s1+c1)};
        end
        default:index_small=address_mul_u3(32'(group_number),m)+32'(tok);
      endcase
    end
  endfunction
  function automatic [31:0] address_mul_u4(input logic [31:0] a,input logic [3:0] b);
    begin
      case({^a,^b})
        2'b00,2'b01,2'b10,2'b11:address_mul_u4=(a & {32{b[0]}}) + ((a << 1) & {32{b[1]}}) + ((a << 2) & {32{b[2]}}) + ((a << 3) & {32{b[3]}});
        default:address_mul_u4=32'bx;
      endcase
    end
  endfunction
  // Exact modulo-8192 index comparison; high9 is shared across all16 lanes.
  // Unknown operand encodings retain the original pessimistic relational form.
  function automatic logic padding_index_ge(input logic [6:0] group_index,
      input logic [2:0] beat_index,input logic [12:0] limit,input logic [3:0] lane);
    logic [6:0] group_carry;
    logic [8:0] high_index;
    begin
      group_carry=group_index+7'(beat_index[2]);
      high_index={group_carry,beat_index[1:0]};
      case(^{group_index,beat_index,limit,lane})
        1'b0,1'b1:padding_index_ge=(high_index>limit[12:4]) ||
          (high_index==limit[12:4] && lane>=limit[3:0]);
        default:padding_index_ge=({group_index,6'b0}+{6'b0,beat_index,4'b0}+13'(lane))>=limit;
      endcase
    end
  endfunction
  function automatic [31:0] bounded_count(input logic [31:0] value,cap);
    if(value>cap)bounded_count=cap;
    else bounded_count=value;
  endfunction
  function automatic logic predicate_one(input logic value);
    if(value)predicate_one=1'b1;
    else predicate_one=1'b0;
  endfunction
  // ROW_BEGIN already supplies a preparation edge before ROW_WEIGHT_LOAD.
  // Subsequent chunks return through DMA_REQ/DMA_WAIT with offset unchanged.
  // Cache the exact bounded count there; the command and offset still advance
  // on their original ROW_WEIGHT_LOAD edge. Keep all 32-bit boundary checks.
  wire [15:0] row_plan_offset=state==ROW_BEGIN ? 16'b0 : offset;
  wire [31:0] row_transfer_plan=bounded_count(
    bounded_count(d[17]-32'(row_plan_offset),32'd512),
    32'd4096-((w_base+32'(row_plan_offset))&32'd4095));
  logic [31:0] row_transfer_count;
  always_ff @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)row_transfer_count<=0;
    else row_transfer_count<=row_transfer_plan;
  end
  always_comb begin
    case(state)
      PRELOAD_A:transfer_count=bounded_count(bounded_count(address_mul_u3(32'(padded_k),mt)-32'(offset),32'd512),4096-((aq_base+offset)&4095));
      PRELOAD_SA:transfer_count=bounded_count(bounded_count(32'(SA_SCALE_BURST ? (address_mul_u3(32'(groups),mt)*4-offset)/4 : 1),32'd32),(4096-((sa_base+offset)&4095))>>2);
      ROW_WEIGHT_LOAD:transfer_count=row_transfer_count;
      ROW_SW:transfer_count=bounded_count(bounded_count(SW_SCALE_BURST ? 32'(groups)-32'(g) : 32'd1,32'd32),(4096-((sw_base+g*4)&4095))>>2);
      WEIGHT_LOAD:transfer_count=32'(group_elements)-32'(offset);
      default:transfer_count=0;
    endcase
  end
  wire [15:0] activation_min_lane,activation_nonzero_lane,activation_padding_lane;
  wire [15:0] weight_min_lane,weight_nonzero_lane;
  for(genvar i=0;i<16;i=i+1)begin : ce_predicate_lane
    assign dot_keep[i]=predicate_one(i<valid_lanes);
    assign activation_min_lane[i]=SCRATCH_PREDICATES && SCRATCH_RESPONSE_BYPASS ?
      predicate_one(ram_min80_q[i]) : predicate_one(scratch_read_data[8*i+:8]==8'h80);
    assign activation_nonzero_lane[i]=SCRATCH_PREDICATES && SCRATCH_RESPONSE_BYPASS ?
      predicate_one(ram_nonzero_q[i]) : predicate_one(scratch_read_data[8*i+:8]!=0);
    assign activation_padding_lane[i]=predicate_one(padding_index_ge(g,beat,d[17][12:0],4'(i))) &&
      activation_nonzero_lane[i];
    // predicate_one projects only a known true value to 1.  Its AND/OR
    // distributivity preserves the original per-lane X/Z behavior while
    // moving the shared scale predicate after the two lane reductions.
    assign weight_min_lane[i]=predicate_one(i<valid_lanes) && activation_min_lane[i];
    assign weight_nonzero_lane[i]=predicate_one(i<valid_lanes) && activation_nonzero_lane[i];
  end
  assign bad_activation=(|activation_min_lane) ||
    (predicate_one(sa_value_zero) && (|activation_nonzero_lane)) || (|activation_padding_lane);
  assign bad_weight=stream_active&&!inline_restore&&state==WEIGHT_CHECK ?
      capture_mask!==16'hffff : (|weight_min_lane) || (predicate_one(sw_value_zero) && (|weight_nonzero_lane));
  assign dma_valid=stream_command||(state==DMA_REQ&&!abort_now);
  // Stream and legacy DMA commands have disjoint state windows. Pick the
  // payload from state shape, while the original valid/capture/ready gates
  // still reject errors immediately. Only invalid-cycle payload may change.
  wire stream_payload_shape=stream_active&&(state==STREAM_SW_WAIT||w_window);
  wire sw_payload_shape=stream_active&&state==STREAM_SW_WAIT;
  assign dma_write=stream_payload_shape?1'b0:cmd_write;
  assign dma_address=stream_payload_shape?(sw_payload_shape?sw_address:w_address):cmd_address;
  assign dma_size=stream_payload_shape?(sw_payload_shape?sw_command_size:3'd4):cmd_size;
  assign dma_len=stream_payload_shape?(sw_payload_shape?5'(sw_command_beats-1):5'(w_count*4-1)):cmd_len;
  assign dma_scratch=stream_payload_shape?16'b0:cmd_scratch;
  assign dma_data=cmd_data;assign dma_mask=cmd_mask;
  assign dma_result_ready=w_command_pending||sw_command_pending||state==DMA_WAIT||state==DRAIN;
  assign ram_en=state==RAM_REQ || state==RAM_WRITE || weight_read_next || activation_read_next ||
      first_a_read || next_sw_read || stream_first_a || m1_next_start;
  // Address selection ignores abort only while the original ram_en is false.
  // Enabled SRAM operations, DMA/DOT/FP offers and all abort priorities remain
  // exact. This removes the deadline comparator from the SRAM address cone.
  wire weight_address_shape=stream_group&&state==WEIGHT_CHECK&&
      (beat+1)*16<group_elements;
  wire activation_address_shape=stream_group&&state==DOT_A&&
      (beat+1)*16<group_elements;
  wire first_a_address_shape=boundary_prefetch&&state==WEIGHT_CHECK&&
      (beat+1)*16>=group_elements;
  wire next_sw_address_shape=!stream_active&&boundary_prefetch&&state==INLINE_FP_SEND&&
      g+7'd1<groups;
  // A token change is followed by the existing RAM_REQ/response prime
  // before DOT_A can request the next beat. Compute the token's activation
  // base in that window; no enabled request observes an old token base.
  logic [31:0] activation_token_base_q;
  always_ff @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)activation_token_base_q<=0;
    else activation_token_base_q<=state==STREAM_W_WAIT ? 32'b0 : address_mul_u3(32'(padded_k),token);
  end
  wire [15:0] stream_read_address=weight_address_shape ? weight_local_base+16'((beat+1)*16) :
      first_a_address_shape ? 16'(g*64) : next_sw_address_shape ? 16'h5800+16'((g+1)*4) :
      16'(activation_token_base_q+g*64+(beat+1)*16);
  // In STREAM_W_WAIT the sole RAM enable is stream_first_a. Likewise the
  // DOT_A and INLINE_FP_SEND address plans are consumed only through their
  // original ready/abort-qualified enables. Do not route those late gates
  // through the disabled address payload as well.
  wire stream_first_address_shape=stream_active&&state==STREAM_W_WAIT;
  assign ram_address=m1_lookahead&&state==INLINE_FP_SEND ? 12'(m1_next_group*4) : stream_first_address_shape ? 12'(g*4) : state==RAM_WRITE ? local_write_address[15:4] :
      (weight_address_shape || activation_address_shape || first_a_address_shape || next_sw_address_shape) ? stream_read_address[15:4] : local_read_address[15:4];
  assign ram_mask=state==RAM_WRITE ? local_write_mask : 0;
  assign ram_data=local_write_data;
  assign engine_idle=state_idle&&response_accept_idle&&!run_active&&!fp_abort_pending;
  assign arithmetic_idle=!dot_live && fp_idle && !bias_live && !desc_busy && !bias_raw_valid && !bias_valid;
  // Report quiescence only after the controller has left active scheduling.
  // These states never enable scratch; unknown state stays fail-closed.
  // RAM/DMA/FP scheduling is unchanged, while reset still drains in DRAIN.
  assign scratch_idle=predicate_one(state==IDLE || state==DONE || state==DRAIN || state==PUBLISH);
  // A scalar tail write is the only observed scratch-read -> word-select ->
  // byte-repack -> command-register cone. Capture its complete scalar first;
  // no extra RAM request is made, and local_read_address is held throughout.
  logic [31:0] tail_scalar_q;
  always_ff @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)tail_scalar_q<=0;
    else if(state==BULK_TAIL_CAPTURE)
      tail_scalar_q<=scratch_read_data[local_read_address[3:0]*8+:32];
  end
  // Both operands are the exact values being registered on this same edge.
  // Active/idle/drain gating stays at the original timeout use sites.
  always_ff @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)deadline_ge<=0;
    else deadline_ge<=(run_limit_next!=0 && ticks_next>=run_limit_next);
  end
  assign timeout_fault=!state_idle && state!=DRAIN && state!=PUBLISH &&
                       deadline_expired;
  assign call_fault=(status!=0 && !state_idle)||fp_abort_pending;
  assign publication_phase=state==PUBLISH;
  assign completion_valid=run_active&&state==PUBLISH&&!fp_abort_pending&&!fp_response_error&&response_accept_idle;
  assign perf={restore_ticks,write_ticks,compute_ticks,load_ticks,ticks,
               payload_write,payload_read,32'b0,rows};
  nx_ce64_dot16 #(.PIPE_PRODUCTS(1),.LATE_W_GATE(W_SW_STREAM),.DUAL_W_PRODUCTS(W_SW_STREAM)) dot(
    .clock(clk),.reset_n(platform_reset_n),.req_valid_i(dot_request_valid),
    .req_ready_o(dot_ready),.aq_i(stream_group ? ram_q : activation_data),
    .wq_i(stream_active&&(inline_restore||bank_active) ? capture_data : stream_group ? weight_group[beat[1:0]] : weight_data),.keep_i(dot_keep),
    .wq_raw_i(stream_active&&(inline_restore||bank_active) ? capture_raw_banks[127:0] : stream_group ? weight_group[beat[1:0]] : weight_data),
    .wq_raw_other_i(stream_active&&(inline_restore||bank_active) ? capture_raw_banks[255:128] : stream_group ? weight_group[beat[1:0]] : weight_data),
    .wq_raw_bank_i(capture_peek_bank),
    .wq_raw_valid_i(!stream_active || !(inline_restore||bank_active) || capture_mask==16'hffff),
    .first_i(beat==0),.last_i((beat+1)*16>=group_elements),.tag_i(index),.epoch_i(epoch),
    .rsp_valid_o(dot_valid),.rsp_ready_i(1'b1),.dot_o(dot_result),.tag_o(dot_tag),.epoch_o(dot_epoch),
    .bad_q_o(dot_bad),.protocol_error_o(dot_protocol),.nonzero_a_o(nonzero_a),.nonzero_w_o(nonzero_w));
  nx_ce64_fp32_ordered_r1_sink #(.MULTI_CONTEXT(A_W_BANKED)) restore(
    .context_i(bank_active?token[1:0]:2'b0),.context_o(fp_raw_context),
    .abort_row_i(state==DRAIN || abort_now),
    .clock(clk),.reset_n(platform_reset_n),.req_valid_i(fp_request_valid),
    .req_ready_o(fp_ready),.dot_i(dot_value),.sa_i(sa_value),.sw_i(sw_value),
    .initial_acc_i(y[token]),.tag_i(index),.epoch_i(epoch),.first_i(!stream_restore || g==0),.last_i(!stream_restore || g+1==groups),.status_i(4'b0),
    .rsp_valid_o(fp_raw_valid),.p_o(fp_raw_p),.v_o(fp_raw_v),.partial_o(fp_raw_partial),
    .tag_o(fp_raw_tag),.epoch_o(fp_raw_epoch),.last_o(fp_raw_last),.idle_o(fp_raw_idle),.status_o(fp_raw_status),.flags_o(fp_raw_flags));
  nx_ce64_fp32_op_sink #(.MUL(0),.PIPE_REGS(3)) bias_add(
    .clock(clk),.reset_n(platform_reset_n),.a_i(y[token]),.b_i(bias_value),
    .tag_i({epoch,29'b0,token}),.aux_i(1'b0),.valid_i(bias_request_valid),.ready_o(bias_ready),
    .result_o(bias_raw_result),.flags_o(bias_raw_flags),.tag_o(bias_raw_tag),.aux_o(bias_raw_aux),
    .valid_o(bias_raw_valid));
  // Accepted-job identity is separate from presentation/response occupancy.
  // Unsolicited responses fault closed without creating a completion or run.
  always_ff @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)run_active<=0;
    else if(reset_grant)run_active<=0;
    else if(submit_collision_job)run_active<=1;
    else if(completion_valid&&completion_ready)run_active<=0;
    else if(state_idle&&submit_safe&&!stop_new&&!fp_response_error)run_active<=1;
  end
  // The permanently ready producers may return every cycle. Consume the old
  // tuple and replace it atomically, with data and raw-time validation paired.
  // Soft grant/start never clear an unconsumed response; only platform reset
  // discards local arithmetic. Invalid payload/control bits need no reset.
  always_ff @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)begin fp_valid<=0;bias_valid<=0;end
    else begin fp_valid<=fp_raw_valid;bias_valid<=bias_raw_valid;end
  end
  always_ff @(posedge clk)begin
    if(fp_raw_valid)begin
      fp_p<=fp_raw_p;fp_v<=fp_raw_v;fp_partial<=fp_raw_partial;
      fp_tag<=fp_raw_tag;fp_epoch<=fp_raw_epoch;fp_last<=fp_raw_last;
      fp_status<=fp_raw_status;fp_flags<=fp_raw_flags;bank_response_context<=fp_raw_context;
      fp_token_q<=token;fp_dot_q<=dot_value;
      fp_stream_q<=stream_restore&&!bank_active;fp_bank_q<=bank_active;
      fp_serial_bad_q<=!predicate_one(!fp_raw_serial_bad);
      fp_stream_bad_q<=!predicate_one(!fp_raw_stream_bad);
      fp_bank_bad_q<=!predicate_one(!bank_raw_response_bad);
      fp_unexpected_q<=!predicate_one(!(!run_active||fp_raw_idle||state==IDLE||state==DONE||state==PUBLISH));
      fp_cancel_q<=response_cancel_now;
    end
    if(bias_raw_valid)begin
      bias_result<=bias_raw_result;bias_flags<=bias_raw_flags;bias_tag<=bias_raw_tag;bias_aux<=bias_raw_aux;
      bias_token_q<=token;
      bias_bad_q<=!predicate_one(!(bias_raw_bad||!bias_live||!run_active));
      bias_cancel_q<=response_cancel_now;
    end
  end
  function automatic [29:0] fetch_update(input logic [15:0] a,input state_t next_state);
    fetch_update={16'(a),7'(next_state),7'(RAM_REQ)};
  endfunction
  function automatic [173:0] store_update(input logic [15:0] a,input logic [127:0] data,
                       input logic [15:0] mask,input state_t next_state);
    store_update={16'(a),128'(data),16'(mask),7'(next_state),7'(RAM_WRITE)};
  endfunction
  function automatic [246:0] memory_read_update(input logic [31:0] a,input logic [2:0] sz,
      input logic [4:0] len,input logic [15:0] local_a,input state_t next_state);
    memory_read_update={32'(a),3'(sz),5'(len),16'(local_a),1'(0),128'(0),16'(0),32'((32'(len)+1)<<sz),7'(next_state),7'(DMA_REQ)};
  endfunction
  function automatic [246:0] memory_write_update(input logic [31:0] a,input logic [2:0] sz,
      input logic [127:0] data,input state_t next_state);
    memory_write_update={32'(a),3'(sz),5'(0),16'(0),1'(1),128'(data<<(8*a[3:0])),16'(16'(((32'd1<<(32'd1<<sz))-32'd1)<<a[3:0])),32'(32'd1<<sz),7'(next_state),7'(DMA_REQ)};
  endfunction
  // Read-only tuple aliases keep one function evaluation and scalar NBA destinations.
  wire [246:0] tuple_ce_call_000=memory_read_update(aq_base+offset,4,5'(transfer_count/16-1),16'(offset),PRELOAD_A);
  wire [29:0] tuple_ce_call_001=fetch_update(16'h5000,VALIDATE_SA);
  wire [246:0] tuple_ce_call_002=memory_read_update(sa_base+offset,2,5'(transfer_count-1),16'h5000+16'(offset),PRELOAD_SA);
  wire [29:0] tuple_ce_call_003=fetch_update(16'(address_mul_u3(32'(padded_k),token)+g*64),VALIDATE_A);
  wire [29:0] tuple_ce_call_004=fetch_update(16'(address_mul_u3(32'(padded_k),token)+g*64+(beat+1)*16),VALIDATE_A);
  wire [29:0] tuple_ce_call_005=fetch_update(16'h5000+16'((address_mul_u3(32'(groups),token)+g+1)*4),VALIDATE_SA);
  wire [29:0] tuple_ce_call_006=fetch_update(16'h5000+16'(address_mul_u4(32'(groups),4'(token)+4'd1)*4),VALIDATE_SA);
  wire [246:0] tuple_ce_call_007=memory_read_update(w_base+offset,4,5'(transfer_count/16-1),16'h8000+offset,ROW_WEIGHT_LOAD);
  wire [246:0] tuple_ce_call_008=memory_read_update(w_base+offset,2,0,16'h8000+offset,ROW_WEIGHT_LOAD);
  wire [246:0] tuple_ce_call_009=memory_read_update(w_base+offset,0,0,16'h8000+offset,ROW_WEIGHT_LOAD);
  wire [246:0] tuple_ce_call_010=memory_read_update(sw_base+g*4,2,5'(transfer_count-1),16'h5800+16'(g*4),ROW_SW);
  wire [246:0] tuple_ce_call_011=memory_read_update(bias_base,2,0,16'h5c00,BIAS_CHECK);
  wire [29:0] tuple_ce_call_012=fetch_update(16'h5800,WEIGHT_SCALE);
  wire [29:0] tuple_ce_call_013=fetch_update(16'h5c00,BIAS_BEGIN);
  wire [29:0] tuple_ce_call_014=fetch_update(weight_local_base,WEIGHT_CHECK);
  wire [29:0] tuple_ce_call_015=fetch_update(16'h8000,WEIGHT_CHECK);
  wire [246:0] tuple_ce_call_016=memory_read_update(w_base+g*64+offset,4,5'(transfer_count/16-1),16'h8000+16'(offset),WEIGHT_LOAD);
  wire [246:0] tuple_ce_call_017=memory_read_update(w_base+g*64+offset,2,0,16'h8000+16'(offset),WEIGHT_LOAD);
  wire [246:0] tuple_ce_call_018=memory_read_update(w_base+g*64+offset,0,0,16'h8000+16'(offset),WEIGHT_LOAD);
  wire [29:0] tuple_ce_call_019=fetch_update(weight_local_base+16'((beat+1)*16),WEIGHT_CHECK);
  wire [29:0] tuple_ce_call_020=fetch_update(16'(g*64),DOT_A);
  wire [29:0] tuple_ce_call_022=fetch_update(16'(address_mul_u3(32'(padded_k),token)+g*64+(beat+1)*16),DOT_A);
  wire [173:0] tuple_ce_call_023=store_update(16'h6000+16'(index*4),128'(32'(dot_result))<<(32*index[1:0]),16'h000f<<(4*index[1:0]),DOT_SAVE);
  wire [29:0] tuple_ce_call_024=fetch_update(16'h5800+16'((g+1)*4),WEIGHT_SCALE);
  wire [29:0] tuple_ce_call_025=fetch_update(16'(address_mul_u4(32'(padded_k),4'(token)+4'd1)+g*64),DOT_A);
  wire [29:0] tuple_ce_call_026=fetch_update(16'h5800+16'((g+1)*4),WEIGHT_SCALE);
  wire [29:0] tuple_ce_call_027=fetch_update(16'h6000,RESTORE_DOT);
  wire [29:0] tuple_ce_call_028=fetch_update(16'h5000+16'((address_mul_u3(32'(groups),token)+g)*4),RESTORE_SA);
  wire [29:0] tuple_ce_call_029=fetch_update(16'h5800+16'(g*4),RESTORE_SW);
  wire [29:0] tuple_ce_call_030=fetch_update(16'h6000+16'(address_mul_u3(32'(g)+32'd1,mt)*4+token*4),RESTORE_DOT);
  wire [29:0] tuple_ce_call_031=fetch_update(16'h6000+16'((token+1)*4),RESTORE_DOT);
  wire [173:0] tuple_ce_call_032=store_update(16'hc000+16'(index*16),{fp_partial,fp_v,fp_p,fp_dot_q},16'hffff,AUDIT_SAVE);
  wire [29:0] tuple_ce_call_033=fetch_update(16'h6000+16'((address_mul_u3(32'(g),mt)+token+1)*4),RESTORE_DOT);
  wire [29:0] tuple_ce_call_034=fetch_update(16'h6000+16'(address_mul_u3(32'(g)+32'd1,mt)*4),RESTORE_DOT);
  wire [29:0] tuple_ce_call_035=fetch_update(16'h5800,WEIGHT_SCALE);
  wire [246:0] tuple_ce_call_036=memory_write_update(output_pack_address,4,{y[0],output_pack_data[95:0]},AUDIT_BEGIN);
  wire [173:0] tuple_ce_call_037=store_update(16'hf000+16'(token*512)+16'(bulk_count*4),
          128'(y[token])<<(32*bulk_count[1:0]),16'h000f<<(4*bulk_count[1:0]),BULK_NEXT);
  wire [29:0] tuple_ce_call_038=fetch_update(16'hf000+16'(token*512)+16'(bulk_offset),BULK_TAIL_WRITE);
  wire [246:0] tuple_ce_call_039=memory_write_update(bulk_base[token]+32'(bulk_offset),2,
            128'(tail_scalar_q),BULK_FLUSH);
  wire [246:0] tuple_ce_call_040=memory_write_update(output_pack_address+32'(output_pack_tail)*4,2,
            128'(output_pack_data[output_pack_tail*32+:32]),OUTPUT_PACK_TAIL);
  wire [246:0] tuple_ce_call_041=memory_write_update(m4_address[token],4,m4_data[token],OUTPUT_M4_FLUSH);
  wire [246:0] tuple_ce_call_042=memory_write_update(m4_address[token]+32'(m4_tail)*4,2,
                       128'(m4_data[token][m4_tail*32+:32]),OUTPUT_M4_TAIL);
  wire [246:0] tuple_ce_call_043=memory_write_update(y_base+address_mul_u3(d[24],token),2,128'(y[token]),OUTPUT_WRITE);
  wire [29:0] tuple_ce_call_044=fetch_update(16'hc000+16'(offset*16),AUDIT_WRITE);
  wire [246:0] tuple_ce_call_045=memory_write_update(audit_cursor,4,scratch_read_data,AUDIT_BEGIN);

  always_comb begin
    completion={32'(generation),32'(generation),32'd0,32'd0,32'd0,32'(status),64'(ticks-load_ticks-compute_ticks-write_ticks),64'(write_ticks),64'(compute_ticks),64'(load_ticks),64'(ticks),64'(payload_write),64'(payload_read),64'(restore_ticks),32'(rows),32'(tiles),32'(status==0),32'(status),32'(d[13]),32'(d[12]),32'(d[11]),32'(d[10]),32'(104),32'(32'h4c4e3135),32'(native_quarantined ? 1 : 0),32'(first_fault_address),32'(0),32'(2),32'(epoch),32'(160),32'(1),32'(32'h52364543)};
  end
  always_ff @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)fp_abort_pending<=0;
    else if(fp_response_error||stream_fault)fp_abort_pending<=1;
    else if(reset_grant||counter_clear||
      (state==DRAIN&&transport_drained&&arithmetic_idle&&dma_idle&&!desc_busy&&!abort_publish))fp_abort_pending<=0;
  end
  // This explicit cache is independent of the one physical scratch port.
  // Every valid bit is cleared per call. Data is consumed only after the full
  // original Sa/activation validation pass and checked again per group.
  always_ff @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)m1_sa_valid<=0;
    else if(reset_grant||counter_clear)m1_sa_valid<=0;
    else if(state==VALIDATE_SA&&inline_restore&&read_scale_valid)m1_sa_valid[g]<=1;
  end
  always_ff @(posedge clk)begin
    if(state==VALIDATE_SA&&inline_restore&&read_scale_valid)begin
      m1_sa_cache[g]<=scratch_read_data[local_read_address[3:0]*8+:32];
      m1_sa_zero_cache[g]<=(scratch_read_data[local_read_address[3:0]*8+:32]==0);
    end
  end
  always_ff @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)begin
      bank_sa_valid<=0;
      for(integer t=0;t<4;t++)begin bank_expected[t]<=0;bank_expected_tag[t]<=9'(t);end
    end else begin
      if(reset_grant||counter_clear)bank_sa_valid<=0;
      else if(bank_active&&state==VALIDATE_SA&&read_scale_valid)
        bank_sa_valid[bank_sa_index]<=1;
      if(reset_grant||counter_clear||state==ROW_BEGIN)
        for(integer t=0;t<4;t++)begin bank_expected[t]<=0;bank_expected_tag[t]<=9'(t);end
      else if(fp_bank_response&&!bank_response_bad)begin
        bank_expected[bank_response_context]<=bank_expected[bank_response_context]+1'b1;
        bank_expected_tag[bank_response_context]<=bank_expected_tag[bank_response_context]+9'(mt);
      end
    end
  end
  always_ff @(posedge clk)begin
    if(bank_active&&state==VALIDATE_SA&&read_scale_valid)
      bank_sa_cache[bank_sa_index]<=scratch_read_data[local_read_address[3:0]*8+:32];
  end
  always_ff @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)begin
      group_elements<=0;
      ;return_state<=IDLE;write_return<=IDLE;active_descriptor<=0;
      descriptor_no_audit_q<=1'b1;descriptor_inline_restore_q<=1'b0;descriptor_bank_rows_q<=1'b0;
      status<=0;mb<=0;row<=0;mt<=0;g<=0;token<=0;beat<=0;offset<=0;count<=0;
      aq_base<=0;sa_base<=0;w_base<=0;sw_base<=0;bias_base<=0;y_base<=0;audit_cursor<=0;
      rows<=0;tiles<=0;bias_value<=0;sa_value<=0;sa_value_zero<=1'b1;sw_value<=0;sw_value_zero<=1'b1;dot_value<=0;
      output_pack_data<=0;output_pack_address<=0;;;
      
      for(integer t=0;t<4;t=t+1)bulk_base[t]<=0;
      ;;
      for(integer t=0;t<4;t=t+1)begin m4_data[t]<=0;m4_address[t]<=0;end
      ;
      for(integer i=0;i<4;i=i+1)weight_group[i]<=0;activation_data<=0;weight_data<=0;
      local_read_address<=0;local_write_address<=0;local_write_mask<=0;local_write_data<=0;
      ;
      phase<=0;restoring<=0;
      payload_read<=0;payload_write<=0;;bias_live<=0;
      cmd_write<=0;cmd_address<=0;cmd_size<=0;cmd_len<=0;cmd_scratch<=0;cmd_mask<=0;cmd_data<=0;chunk_bytes<=0;
      for(integer i=0;i<32;i=i+1)d[i]<=0;
      for(integer i=0;i<4;i=i+1)y[i]<=0;
    end else begin
      if(fp_stream_response)begin
        ;
        if(!fp_bad_response);
      end
      if(dot_valid);
      if(bias_valid);
      // Unissued packed words belong to a failed/aborted call. Accepted DMA
      // offers use cmd_data/the DMA's private buffer and still drain normally.
      if(state==DRAIN)begin ;;;;end
      if(fp_abort_pending&&run_active&&!dot_live&&state!=DRAIN)begin
        ;;;;
      end else if((stop_new || timeout_fault) && !state_idle && state!=DRAIN && state!=PUBLISH && !dot_live)begin
        if(status==0);
        ;;;
      end else case(state)
        IDLE,DONE:if(submit_safe && !stop_new && !fp_response_error)begin
          active_descriptor<=descriptor;
          descriptor_no_audit_q<=descriptor[32*28+:32]==0;
          descriptor_inline_restore_q<=(descriptor[32*15+:32]==1)&&(descriptor[32*28+:32]==0);
          descriptor_bank_rows_q<=(descriptor[32*15+:32]>=2)&&(descriptor[32*15+:32]<=4);
          for(integer i=0;i<32;i=i+1)d[i]<=descriptor[32*i+:32];
          ;rows<=0;tiles<=0;mb<=0;row<=0;;;
          output_pack_data<=0;output_pack_address<=0;;;

      ;;
      for(integer t=0;t<4;t=t+1)begin m4_data[t]<=0;m4_address[t]<=0;end
          payload_read<=0;payload_write<=0;;
        end
        DESC_START:;
        DESC_WAIT:if(desc_done)begin
          if(desc_status!=0)begin ;;end
          else begin
            aq_base<=d[22];sa_base<=d[23];w_base<=d[18];sw_base<=d[20];bias_base<=d[21];
            y_base<=d[19];audit_cursor<=d[28];mt<=d[15]>4 ? 4 : d[15];
            offset<=0;;;
          end
        end
        PRELOAD_A:begin
          if(resident_active||32'(offset)==address_mul_u3(32'(padded_k),mt))begin offset<=0;;end
          else begin
            // 512B maximum and page boundary slicing, with a 16B final quantum.
            offset<=offset+transfer_count;
            begin
            cmd_address<=tuple_ce_call_000[246:215];
            cmd_size<=tuple_ce_call_000[214:212];
            cmd_len<=tuple_ce_call_000[211:207];
            cmd_scratch<=tuple_ce_call_000[206:191];
            cmd_write<=tuple_ce_call_000[190:190];
            cmd_data<=tuple_ce_call_000[189:62];
            cmd_mask<=tuple_ce_call_000[61:46];
            chunk_bytes<=tuple_ce_call_000[45:14];
            return_state<=state_t'(tuple_ce_call_000[13:7]);
            ;
          end

          end
        end
        PRELOAD_SA:if(resident_active||offset==address_mul_u3(32'(groups),mt)*4)begin g<=0;token<=0;;begin
            local_read_address<=tuple_ce_call_001[29:14];
            return_state<=state_t'(tuple_ce_call_001[13:7]);
            ;
          end
end
          else begin
            offset<=offset+transfer_count*4;
            begin
            cmd_address<=tuple_ce_call_002[246:215];
            cmd_size<=tuple_ce_call_002[214:212];
            cmd_len<=tuple_ce_call_002[211:207];
            cmd_scratch<=tuple_ce_call_002[206:191];
            cmd_write<=tuple_ce_call_002[190:190];
            cmd_data<=tuple_ce_call_002[189:62];
            cmd_mask<=tuple_ce_call_002[61:46];
            chunk_bytes<=tuple_ce_call_002[45:14];
            return_state<=state_t'(tuple_ce_call_002[13:7]);
            ;
          end

          end
        VALIDATE_SA:begin
          sa_value<=scratch_read_data[local_read_address[3:0]*8+:32];
          sa_value_zero<=(scratch_read_data[local_read_address[3:0]*8+:32]==0);beat<=0;
          if(!read_scale_valid)begin ;;end
          else if(resident_group_active)begin
            // Sa still comes from the real synchronous scratch response and
            // fills the original cache. Only the already-certified Aq scan
            // is omitted; all N consumers still read/check the actual Aq.
            if(g+1<groups)begin
              g<=g+1'b1;local_read_address<=tuple_ce_call_005[29:14];return_state<=state_t'(tuple_ce_call_005[13:7]);
            end else if(token+1<mt)begin
              token<=token+1'b1;g<=0;local_read_address<=tuple_ce_call_006[29:14];return_state<=state_t'(tuple_ce_call_006[13:7]);
            end else row<=0;
          end else begin
            local_read_address<=tuple_ce_call_003[29:14];
            return_state<=state_t'(tuple_ce_call_003[13:7]);
            ;
          end

        end
        VALIDATE_A:if(bad_activation)begin ;;end else begin
          if(beat!=3)begin beat<=beat+1'b1;begin
            local_read_address<=tuple_ce_call_004[29:14];
            return_state<=state_t'(tuple_ce_call_004[13:7]);
            ;
          end
end
          else if(g+1<groups)begin g<=g+1'b1;begin
            local_read_address<=tuple_ce_call_005[29:14];
            return_state<=state_t'(tuple_ce_call_005[13:7]);
            ;
          end
end
          else if(token+1<mt)begin token<=token+1'b1;g<=0;begin
            local_read_address<=tuple_ce_call_006[29:14];
            return_state<=state_t'(tuple_ce_call_006[13:7]);
            ;
          end
end
          else begin row<=0;;end
        end
        ROW_BEGIN:begin
          g<=0;offset<=0;;;
          ;
        end
        // This is serial prefetch into the existing scratch B port, not a
        // double-buffer/overlap claim. Load only logical K bytes; padding is
        // neither read nor consumed. Every row keeps the original group order.
        ROW_WEIGHT_LOAD:if(stream_active)begin end else if(32'(offset)==d[17])begin ;end else begin
          if(transfer_count>=16)begin
            begin
            cmd_address<=tuple_ce_call_007[246:215];
            cmd_size<=tuple_ce_call_007[214:212];
            cmd_len<=tuple_ce_call_007[211:207];
            cmd_scratch<=tuple_ce_call_007[206:191];
            cmd_write<=tuple_ce_call_007[190:190];
            cmd_data<=tuple_ce_call_007[189:62];
            cmd_mask<=tuple_ce_call_007[61:46];
            chunk_bytes<=tuple_ce_call_007[45:14];
            return_state<=state_t'(tuple_ce_call_007[13:7]);
            ;
          end

            offset<=offset+(transfer_count/16)*16;
          end else if(transfer_count>=4)begin
            begin
            cmd_address<=tuple_ce_call_008[246:215];
            cmd_size<=tuple_ce_call_008[214:212];
            cmd_len<=tuple_ce_call_008[211:207];
            cmd_scratch<=tuple_ce_call_008[206:191];
            cmd_write<=tuple_ce_call_008[190:190];
            cmd_data<=tuple_ce_call_008[189:62];
            cmd_mask<=tuple_ce_call_008[61:46];
            chunk_bytes<=tuple_ce_call_008[45:14];
            return_state<=state_t'(tuple_ce_call_008[13:7]);
            ;
          end
offset<=offset+4;
          end else begin
            begin
            cmd_address<=tuple_ce_call_009[246:215];
            cmd_size<=tuple_ce_call_009[214:212];
            cmd_len<=tuple_ce_call_009[211:207];
            cmd_scratch<=tuple_ce_call_009[206:191];
            cmd_write<=tuple_ce_call_009[190:190];
            cmd_data<=tuple_ce_call_009[189:62];
            cmd_mask<=tuple_ce_call_009[61:46];
            chunk_bytes<=tuple_ce_call_009[45:14];
            return_state<=state_t'(tuple_ce_call_009[13:7]);
            ;
          end
offset<=offset+1;
          end
        end
        ROW_SW:if(g==groups)begin ;end else begin
          // Four-byte beats work for every scale-row alignment (e.g. the
          // 56-byte K896 row). LEN is five bits: at most 32 words / 128B.
          // Both external and scratch addresses retain four-byte alignment.
          g<=g+7'(transfer_count);
          begin
            cmd_address<=tuple_ce_call_010[246:215];
            cmd_size<=tuple_ce_call_010[214:212];
            cmd_len<=tuple_ce_call_010[211:207];
            cmd_scratch<=tuple_ce_call_010[206:191];
            cmd_write<=tuple_ce_call_010[190:190];
            cmd_data<=tuple_ce_call_010[189:62];
            cmd_mask<=tuple_ce_call_010[61:46];
            chunk_bytes<=tuple_ce_call_010[45:14];
            return_state<=state_t'(tuple_ce_call_010[13:7]);
            ;
          end

        end
        ROW_BIAS:if(d[21]!=0)begin
            cmd_address<=tuple_ce_call_011[246:215];
            cmd_size<=tuple_ce_call_011[214:212];
            cmd_len<=tuple_ce_call_011[211:207];
            cmd_scratch<=tuple_ce_call_011[206:191];
            cmd_write<=tuple_ce_call_011[190:190];
            cmd_data<=tuple_ce_call_011[189:62];
            cmd_mask<=tuple_ce_call_011[61:46];
            chunk_bytes<=tuple_ce_call_011[45:14];
            return_state<=state_t'(tuple_ce_call_011[13:7]);
            ;
          end

          else begin bias_value<=0;g<=0;;begin
            local_read_address<=tuple_ce_call_012[29:14];
            return_state<=state_t'(tuple_ce_call_012[13:7]);
            ;
          end
end
        BIAS_CHECK:begin
          // DMA loaded bias; fetch is necessary for synchronous scratch latency.
          begin
            local_read_address<=tuple_ce_call_013[29:14];
            return_state<=state_t'(tuple_ce_call_013[13:7]);
            ;
          end
count<=0;
        end
        WEIGHT_SCALE:begin
          group_elements<=g+7'd1==groups&&d[17][5:0]!=0 ? {1'b0,d[17][5:0]} : 7'd64;
          sw_value<=scratch_read_data[local_read_address[3:0]*8+:32];
          sw_value_zero<=(scratch_read_data[local_read_address[3:0]*8+:32]==32'b0);offset<=0;
          if(!read_scale_valid)begin ;;end
          else if(WEIGHT_ROW_BURST)begin beat<=0;begin
            local_read_address<=tuple_ce_call_014[29:14];
            return_state<=state_t'(tuple_ce_call_014[13:7]);
            ;
          end
end
          else ;
        end
        WEIGHT_LOAD:if(32'(offset)==32'(group_elements))begin beat<=0;begin
            local_read_address<=tuple_ce_call_015[29:14];
            return_state<=state_t'(tuple_ce_call_015[13:7]);
            ;
          end
end else begin
          if(transfer_count>=16)begin
            begin
            cmd_address<=tuple_ce_call_016[246:215];
            cmd_size<=tuple_ce_call_016[214:212];
            cmd_len<=tuple_ce_call_016[211:207];
            cmd_scratch<=tuple_ce_call_016[206:191];
            cmd_write<=tuple_ce_call_016[190:190];
            cmd_data<=tuple_ce_call_016[189:62];
            cmd_mask<=tuple_ce_call_016[61:46];
            chunk_bytes<=tuple_ce_call_016[45:14];
            return_state<=state_t'(tuple_ce_call_016[13:7]);
            ;
          end

            offset<=offset+(transfer_count/16)*16;
          end else if(transfer_count>=4)begin begin
            cmd_address<=tuple_ce_call_017[246:215];
            cmd_size<=tuple_ce_call_017[214:212];
            cmd_len<=tuple_ce_call_017[211:207];
            cmd_scratch<=tuple_ce_call_017[206:191];
            cmd_write<=tuple_ce_call_017[190:190];
            cmd_data<=tuple_ce_call_017[189:62];
            cmd_mask<=tuple_ce_call_017[61:46];
            chunk_bytes<=tuple_ce_call_017[45:14];
            return_state<=state_t'(tuple_ce_call_017[13:7]);
            ;
          end
offset<=offset+4;end
          else begin begin
            cmd_address<=tuple_ce_call_018[246:215];
            cmd_size<=tuple_ce_call_018[214:212];
            cmd_len<=tuple_ce_call_018[211:207];
            cmd_scratch<=tuple_ce_call_018[206:191];
            cmd_write<=tuple_ce_call_018[190:190];
            cmd_data<=tuple_ce_call_018[189:62];
            cmd_mask<=tuple_ce_call_018[61:46];
            chunk_bytes<=tuple_ce_call_018[45:14];
            return_state<=state_t'(tuple_ce_call_018[13:7]);
            ;
          end
offset<=offset+1;end
        end
        WEIGHT_CHECK:begin
          // Internal unpublished cache sampling is independent of validity.
          // The original bad_weight branch still abandons this group pre-DOT.
          weight_group[beat[1:0]]<=weight_check_data;
          if(bad_weight)begin ;;end else begin
          if((beat+1)*16<group_elements)begin
            beat<=beat+1'b1;
            if(!stream_group)begin
            local_read_address<=tuple_ce_call_019[29:14];
            return_state<=state_t'(tuple_ce_call_019[13:7]);
            ;
          end

          end
          else begin
            token<=0;beat<=0;
            if(first_a_read)begin local_read_address<=16'(g*64);;end
            else begin
            local_read_address<=tuple_ce_call_020[29:14];
            return_state<=state_t'(tuple_ce_call_020[13:7]);
            ;
          end

          end
        end
        end
        DOT_A:if(stream_group)begin
          if(dot_ready&&dot_request_valid)begin
            ;
            if((beat+1)*16>=group_elements);
            else beat<=beat+1'b1;
          end
        end else begin
          activation_data<=scratch_read_data;
          if(WEIGHT_GROUP_CACHE)begin weight_data<=weight_group[beat[1:0]];;end
          else begin
            local_read_address<=16'(fetch_update(weight_local_base+16'(beat*16),DOT_W) >> 14);
            return_state<=state_t'(7'(fetch_update(weight_local_base+16'(beat*16),DOT_W) >> 7));
            ;
          end

        end
        DOT_W:begin weight_data<=scratch_read_data;;end
        DOT_SEND:if(dot_ready&&dot_request_valid)begin
          ;
          if((beat+1)*16>=group_elements);
          else begin beat<=beat+1'b1;begin
            local_read_address<=tuple_ce_call_022[29:14];
            return_state<=state_t'(tuple_ce_call_022[13:7]);
            ;
          end
end
        end
        DOT_WAIT:if(dot_valid)begin
          if(abort_now)begin if(status==0);;;end
          else if(dot_bad || dot_protocol || dot_tag!=index || dot_epoch!=epoch)begin ;;end
          else begin
            dot_value<=dot_result;
            if(inline_restore)begin
              if(!m1_sa_valid[g])begin ;;;;end
              else begin sa_value<=m1_sa_cache[g];sa_value_zero<=m1_sa_zero_cache[g];;;end
            end else begin
            local_write_address<=tuple_ce_call_023[173:158];
            local_write_data<=tuple_ce_call_023[157:30];
            local_write_mask<=tuple_ce_call_023[29:14];
            write_return<=state_t'(tuple_ce_call_023[13:7]);
            ;
          end

          end
        end
        INLINE_FP_SEND:if(fp_ready&&fp_request_valid)begin
          if(g+1<groups)begin
            g<=g+1'b1;
            if(next_sw_read)begin local_read_address<=16'h5800+16'((g+1)*4);;end
            else begin
            local_read_address<=tuple_ce_call_024[29:14];
            return_state<=state_t'(tuple_ce_call_024[13:7]);
            ;
          end

          end
          else begin ;;end
        end
        INLINE_FP_DRAIN:if(fp_idle)begin
          if(fp_expected_group!=groups)begin ;;;end
          else begin token<=0;count<=1;;end
        end
        DOT_SAVE:if(token+1<mt)begin
          token<=token+1'b1;beat<=0;begin
            local_read_address<=tuple_ce_call_025[29:14];
            return_state<=state_t'(tuple_ce_call_025[13:7]);
            ;
          end

        end else if(g+1<groups)begin g<=g+1'b1;begin
            local_read_address<=tuple_ce_call_026[29:14];
            return_state<=state_t'(tuple_ce_call_026[13:7]);
            ;
          end
end
          else begin ;;;end
        RESTORE_BEGIN:begin
          for(integer i=0;i<4;i=i+1);
          token<=0;g<=0;;
          if(inline_restore);
          else begin
            local_read_address<=tuple_ce_call_027[29:14];
            return_state<=state_t'(tuple_ce_call_027[13:7]);
            ;
          end

        end
        RESTORE_DOT:begin
          dot_value<=scratch_read_data[local_read_address[3:0]*8+:32];
          begin
            local_read_address<=tuple_ce_call_028[29:14];
            return_state<=state_t'(tuple_ce_call_028[13:7]);
            ;
          end

        end
        RESTORE_SA:begin
          sa_value<=scratch_read_data[local_read_address[3:0]*8+:32];
          sa_value_zero<=(scratch_read_data[local_read_address[3:0]*8+:32]==0);begin
            local_read_address<=tuple_ce_call_029[29:14];
            return_state<=state_t'(tuple_ce_call_029[13:7]);
            ;
          end

        end
        RESTORE_SW:begin
          sw_value<=restore_sw_data[local_read_address[3:0]*8+:32];
          sw_value_zero<=(restore_sw_raw_data[local_read_address[3:0]*8+:32]==32'b0);
        end
        FP_SEND:if(fp_ready&&fp_request_valid)begin
          if(!stream_restore);
          else if(g+1<groups)begin
            g<=g+1'b1;begin
            local_read_address<=tuple_ce_call_030[29:14];
            return_state<=state_t'(tuple_ce_call_030[13:7]);
            ;
          end

          end else ;
        end
        FP_ROW_DRAIN:if(fp_idle)begin
          if(token+1<mt)begin
            token<=token+1'b1;g<=0;;
            begin
            local_read_address<=tuple_ce_call_031[29:14];
            return_state<=state_t'(tuple_ce_call_031[13:7]);
            ;
          end

          end else begin token<=0;count<=1;;end
        end
        FP_WAIT:if(fp_valid)begin
          if(fp_serial_response_bad)begin ;;;end
          else begin
            ;
            if(d[28]!=0)begin
            local_write_address<=tuple_ce_call_032[173:158];
            local_write_data<=tuple_ce_call_032[157:30];
            local_write_mask<=tuple_ce_call_032[29:14];
            write_return<=state_t'(tuple_ce_call_032[13:7]);
            ;
          end

            else ;
          end
        end
        AUDIT_SAVE:if(token+1<mt)begin
          token<=token+1'b1;begin
            local_read_address<=tuple_ce_call_033[29:14];
            return_state<=state_t'(tuple_ce_call_033[13:7]);
            ;
          end

        end else if(g+1<groups)begin
          token<=0;g<=g+1'b1;begin
            local_read_address<=tuple_ce_call_034[29:14];
            return_state<=state_t'(tuple_ce_call_034[13:7]);
            ;
          end

        end else begin token<=0;count<=1;;end
        BIAS_BEGIN:if(count==0)begin
          bias_value<=scratch_read_data[31:0];g<=0;;
          if(!finite32(scratch_read_data[31:0]))begin ;;end else begin
            local_read_address<=tuple_ce_call_035[29:14];
            return_state<=state_t'(tuple_ce_call_035[13:7]);
            ;
          end

        end else if(d[21]==0)begin ;;;end
          else ;
        BIAS_SEND:if(bias_ready&&bias_request_valid)begin ;;end
        BIAS_WAIT:if(bias_valid)begin
          if(bias_response_bad)begin ;;;end
          else begin
            ;
            if(token+1<mt)begin token<=token+1'b1;;end
            else begin ;;;end
          end
        end
        OUTPUT_BEGIN:begin
          token<=0;
          if(bulk_output)begin
            if(bulk_count==0)for(integer t=0;t<4;t=t+1)bulk_base[t]<=y_base+32'(t)*d[24];
            ;
          end else if(pack_m4_output)begin
            for(integer t=0;t<4;t=t+1)if(t<mt)begin
              m4_data[t][m4_count*32+:32]<=y[t];
              if(m4_count==0)m4_address[t]<=y_base+32'(t)*d[24];
            end
            if(m4_count==3)begin ;;end
            else begin
              ;
              if(row+1==d[16])begin ;;end
              else begin offset<=0;;end
            end
          end else if(!pack_m1_output);
          else begin
            output_pack_data[output_pack_count*32+:32]<=y[0];
            if(output_pack_count==0)output_pack_address<=y_base;
            if(output_pack_count==3)begin
              // The first three words were captured on preceding rows. The
              // current fourth word is used directly (not the old NBA value).
              ;offset<=0;
              begin
            cmd_address<=tuple_ce_call_036[246:215];
            cmd_size<=tuple_ce_call_036[214:212];
            cmd_len<=tuple_ce_call_036[211:207];
            cmd_scratch<=tuple_ce_call_036[206:191];
            cmd_write<=tuple_ce_call_036[190:190];
            cmd_data<=tuple_ce_call_036[189:62];
            cmd_mask<=tuple_ce_call_036[61:46];
            chunk_bytes<=tuple_ce_call_036[45:14];
            return_state<=state_t'(tuple_ce_call_036[13:7]);
            ;
          end

            end else begin
              ;
              if(row+1==d[16])begin
                ;;
              end else begin offset<=0;;end
            end
          end
        end
        BULK_STORE:begin
            local_write_address<=tuple_ce_call_037[173:158];
            local_write_data<=tuple_ce_call_037[157:30];
            local_write_mask<=tuple_ce_call_037[29:14];
            write_return<=state_t'(tuple_ce_call_037[13:7]);
            ;
          end

        BULK_NEXT:if(token+1<mt)begin token<=token+1'b1;;end
          else begin
            
            if(bulk_count==127||row+1==d[16])begin
              token<=0;;
            end else begin offset<=0;;end
          end
        BULK_FLUSH:if(token==mt)begin offset<=0;;end
          else if(bulk_offset==({2'b0,bulk_rows}<<2))begin token<=token+1'b1;end
          else if(bulk_can_burst)begin
            cmd_address<=bulk_base[token]+32'(bulk_offset);cmd_size<=4;cmd_len<=5'(bulk_bytes/16-1);
            cmd_scratch<=16'hf000+16'(token*512)+16'(bulk_offset);cmd_write<=1;cmd_data<=0;cmd_mask<=16'hffff;
            chunk_bytes<=bulk_bytes;return_state<=BULK_FLUSH;;
          end else begin
            local_read_address<=tuple_ce_call_038[29:14];
            return_state<=state_t'(tuple_ce_call_038[13:7]);
            ;
          end

        BULK_TAIL_WRITE:begin
          begin
            cmd_address<=tuple_ce_call_039[246:215];
            cmd_size<=tuple_ce_call_039[214:212];
            cmd_len<=tuple_ce_call_039[211:207];
            cmd_scratch<=tuple_ce_call_039[206:191];
            cmd_write<=tuple_ce_call_039[190:190];
            cmd_data<=tuple_ce_call_039[189:62];
            cmd_mask<=tuple_ce_call_039[61:46];
            chunk_bytes<=tuple_ce_call_039[45:14];
            return_state<=state_t'(tuple_ce_call_039[13:7]);
            ;
          end

        end
        OUTPUT_PACK_TAIL:if(output_pack_tail==output_pack_count)begin
          ;offset<=0;;
        end else begin
          // Never pad a short final group into a 16B write beyond Y's span.
          begin
            cmd_address<=tuple_ce_call_040[246:215];
            cmd_size<=tuple_ce_call_040[214:212];
            cmd_len<=tuple_ce_call_040[211:207];
            cmd_scratch<=tuple_ce_call_040[206:191];
            cmd_write<=tuple_ce_call_040[190:190];
            cmd_data<=tuple_ce_call_040[189:62];
            cmd_mask<=tuple_ce_call_040[61:46];
            chunk_bytes<=tuple_ce_call_040[45:14];
            return_state<=state_t'(tuple_ce_call_040[13:7]);
            ;
          end

          ;
        end
        OUTPUT_M4_FLUSH:if(token==mt)begin offset<=0;;end else begin
          token<=token+1'b1;begin
            cmd_address<=tuple_ce_call_041[246:215];
            cmd_size<=tuple_ce_call_041[214:212];
            cmd_len<=tuple_ce_call_041[211:207];
            cmd_scratch<=tuple_ce_call_041[206:191];
            cmd_write<=tuple_ce_call_041[190:190];
            cmd_data<=tuple_ce_call_041[189:62];
            cmd_mask<=tuple_ce_call_041[61:46];
            chunk_bytes<=tuple_ce_call_041[45:14];
            return_state<=state_t'(tuple_ce_call_041[13:7]);
            ;
          end

        end
        OUTPUT_M4_TAIL:if(token==mt)begin
          ;;offset<=0;;
        end else if(m4_tail==m4_count)begin token<=token+1'b1;;end
        else begin
          ;
          begin
            cmd_address<=tuple_ce_call_042[246:215];
            cmd_size<=tuple_ce_call_042[214:212];
            cmd_len<=tuple_ce_call_042[211:207];
            cmd_scratch<=tuple_ce_call_042[206:191];
            cmd_write<=tuple_ce_call_042[190:190];
            cmd_data<=tuple_ce_call_042[189:62];
            cmd_mask<=tuple_ce_call_042[61:46];
            chunk_bytes<=tuple_ce_call_042[45:14];
            return_state<=state_t'(tuple_ce_call_042[13:7]);
            ;
          end

        end
        OUTPUT_WRITE:if(token==mt)begin offset<=0;;end else begin
          token<=token+1'b1;begin
            cmd_address<=tuple_ce_call_043[246:215];
            cmd_size<=tuple_ce_call_043[214:212];
            cmd_len<=tuple_ce_call_043[211:207];
            cmd_scratch<=tuple_ce_call_043[206:191];
            cmd_write<=tuple_ce_call_043[190:190];
            cmd_data<=tuple_ce_call_043[189:62];
            cmd_mask<=tuple_ce_call_043[61:46];
            chunk_bytes<=tuple_ce_call_043[45:14];
            return_state<=state_t'(tuple_ce_call_043[13:7]);
            ;
          end

        end
        AUDIT_BEGIN:if(d[28]==0 || 32'(offset)==address_mul_u3(32'(groups),mt));
          else begin
            local_read_address<=tuple_ce_call_044[29:14];
            return_state<=state_t'(tuple_ce_call_044[13:7]);
            ;
          end

        AUDIT_WRITE:begin
          offset<=offset+1'b1;audit_cursor<=audit_cursor+16;
          begin
            cmd_address<=tuple_ce_call_045[246:215];
            cmd_size<=tuple_ce_call_045[214:212];
            cmd_len<=tuple_ce_call_045[211:207];
            cmd_scratch<=tuple_ce_call_045[206:191];
            cmd_write<=tuple_ce_call_045[190:190];
            cmd_data<=tuple_ce_call_045[189:62];
            cmd_mask<=tuple_ce_call_045[61:46];
            chunk_bytes<=tuple_ce_call_045[45:14];
            return_state<=state_t'(tuple_ce_call_045[13:7]);
            ;
          end

        end
        ROW_END:begin
          rows<=rows+1'b1;
          if(row[6:0]==127 || row+1==d[16])tiles<=tiles+1'b1;
          if(row+1<d[16])begin
            row<=row+1'b1;w_base<=w_base+padded_k;sw_base<=sw_base+groups*4;
            bias_base<=bias_base+4;y_base<=y_base+4;;
          end else if(32'(mb)+32'(mt)<d[15])begin
            mb<=mb+mt;mt<=d[15]-mb-mt>4 ? 4 : d[15]-mb-mt;
            aq_base<=aq_base+address_mul_u3(32'(padded_k),mt);sa_base<=sa_base+address_mul_u3(32'(groups),mt)*4;
            w_base<=d[18];sw_base<=d[20];bias_base<=d[21];
            y_base<=y_base-(d[16]-1)*4+address_mul_u3(d[24],mt);
            offset<=0;;;
          end else begin ;;end
        end
        // Select the banked RAM return in the same mutually exclusive case
        // as every legacy return update. Keep the original acceptance and
        // cancellation guards; stalled offers leave the return unchanged.
        BANK_FP_SEND:if(bank_active&&!reset_grant&&!control_abort&&
                       fp_request_valid&&fp_ready&&token+1<mt)begin
          return_state<=DOT_A;
        end
        RAM_REQ:;
        RAM_WAIT:begin ;;end
        RAM_WRITE:;
        DMA_REQ:if(dma_ready&&dma_valid);
        DMA_WAIT:if(dma_result_valid)begin
          if(dma_resp!=0)begin ;;;;end
          else begin
            if(cmd_write)payload_write<=payload_add(payload_write,chunk_bytes);
            else payload_read<=payload_add(payload_read,chunk_bytes);
            ;
          end
        end
        DRAIN:if(transport_drained && arithmetic_idle && dma_idle && !desc_busy && !abort_publish);
        PUBLISH:if(completion_ready&&completion_valid);
        default:;
      endcase
      if(reset_grant)begin
        ;;;;
        ;;
        
      end
      // Same original FF/reset group; original39bit last-NBA priorities only.
      if(reset_grant)begin
        ;
      end else begin
        if(fp_abort_pending&&run_active&&!dot_live&&state!=DRAIN)begin
          ;
        end else begin
          if((stop_new || timeout_fault) && !state_idle && state!=DRAIN && state!=PUBLISH && !dot_live)begin
            ;
          end else begin
            case(state)
              IDLE,DONE:begin
                if(submit_safe && !stop_new && !fp_response_error)begin
                  ;
                end
              end
              DESC_START:begin
                ;
              end
              DESC_WAIT:begin
                if(desc_done)begin
                  if(desc_status!=0)begin
                    ;
                  end else begin
                    ;
                  end
                end
              end
              PRELOAD_A:begin
                if(resident_active||32'(offset)==address_mul_u3(32'(padded_k),mt))begin
                  ;
                end else begin
                  ;
                end
              end
              PRELOAD_SA:begin
                if(resident_active||offset==address_mul_u3(32'(groups),mt)*4)begin
                  ;
                end else begin
                  ;
                end
              end
              VALIDATE_SA:begin
                if(!read_scale_valid)begin
                  ;
                end else begin
                  ;
                end
              end
              VALIDATE_A:begin
                if(bad_activation)begin
                  ;
                end else begin
                  if(beat!=3)begin
                    ;
                  end else begin
                    if(g+1<groups)begin
                      ;
                    end else begin
                      if(token+1<mt)begin
                        ;
                      end else begin
                        ;
                      end
                    end
                  end
                end
              end
              ROW_BEGIN:begin
                ;
              end
              ROW_WEIGHT_LOAD:begin
                if(32'(offset)==d[17])begin
                  ;
                end else begin
                  if(transfer_count>=16)begin
                    ;
                  end else begin
                    if(transfer_count>=4)begin
                      ;
                    end else begin
                      ;
                    end
                  end
                end
              end
              ROW_SW:begin
                if(g==groups)begin
                  ;
                end else begin
                  ;
                end
              end
              ROW_BIAS:begin
                if(d[21]!=0)begin
                  ;
                end else begin
                  ;
                end
              end
              BIAS_CHECK:begin
                ;
              end
              WEIGHT_SCALE:begin
                if(!read_scale_valid)begin
                  ;
                end else begin
                  if(WEIGHT_ROW_BURST)begin
                    ;
                  end else begin
                    ;
                  end
                end
              end
              WEIGHT_LOAD:begin
                if(32'(offset)==32'(group_elements))begin
                  ;
                end else begin
                  if(transfer_count>=16)begin
                    ;
                  end else begin
                    if(transfer_count>=4)begin
                      ;
                    end else begin
                      ;
                    end
                  end
                end
              end
              WEIGHT_CHECK:begin
                if(bad_weight)begin
                  ;
                end else begin
                  if((beat+1)*16<group_elements)begin
                    if(!stream_group)begin
                      ;
                    end
                  end else begin
                    if(first_a_read)begin
                      ;
                    end else begin
                      ;
                    end
                  end
                end
              end
              DOT_A:begin
                if(stream_group)begin
                  if(dot_ready&&dot_request_valid)begin
                    if((beat+1)*16>=group_elements)begin
                      ;
                    end
                  end
                end else begin
                  if(WEIGHT_GROUP_CACHE)begin
                    ;
                  end else begin
                    ;
                  end
                end
              end
              DOT_W:begin
                ;
              end
              DOT_SEND:begin
                if(dot_ready&&dot_request_valid)begin
                  if((beat+1)*16>=group_elements)begin
                    ;
                  end else begin
                    ;
                  end
                end
              end
              DOT_WAIT:begin
                if(dot_valid)begin
                  if(abort_now)begin
                    ;
                  end else begin
                    if(dot_bad || dot_protocol || dot_tag!=index || dot_epoch!=epoch)begin
                      ;
                    end else begin
                      if(inline_restore)begin
                        if(!m1_sa_valid[g])begin
                          ;
                        end else begin
                          ;
                        end
                      end else begin
                        ;
                      end
                    end
                  end
                end
              end
              INLINE_FP_SEND:begin
                if(fp_ready&&fp_request_valid)begin
                  if(g+1<groups)begin
                    if(next_sw_read)begin
                      ;
                    end else begin
                      ;
                    end
                  end else begin
                    ;
                  end
                end
              end
              INLINE_FP_DRAIN:begin
                if(fp_idle)begin
                  if(fp_expected_group!=groups)begin
                    ;
                  end else begin
                    ;
                  end
                end
              end
              DOT_SAVE:begin
                if(token+1<mt)begin
                  ;
                end else begin
                  if(g+1<groups)begin
                    ;
                  end else begin
                    ;
                  end
                end
              end
              RESTORE_BEGIN:begin
                if(inline_restore)begin
                  ;
                end else begin
                  ;
                end
              end
              RESTORE_DOT:begin
                ;
              end
              RESTORE_SA:begin
                ;
              end
              RESTORE_SW:begin
                ;
              end
              FP_SEND:begin
                if(fp_ready&&fp_request_valid)begin
                  if(!stream_restore)begin
                    ;
                  end else begin
                    if(g+1<groups)begin
                      ;
                    end else begin
                      ;
                    end
                  end
                end
              end
              FP_ROW_DRAIN:begin
                if(fp_idle)begin
                  if(token+1<mt)begin
                    ;
                  end else begin
                    ;
                  end
                end
              end
              FP_WAIT:begin
                if(fp_valid)begin
                  if(fp_serial_response_bad)begin
                    ;
                  end else begin
                    if(d[28]!=0)begin
                      ;
                    end else begin
                      ;
                    end
                  end
                end
              end
              AUDIT_SAVE:begin
                if(token+1<mt)begin
                  ;
                end else begin
                  if(g+1<groups)begin
                    ;
                  end else begin
                    ;
                  end
                end
              end
              BIAS_BEGIN:begin
                if(count==0)begin
                  if(!finite32(scratch_read_data[31:0]))begin
                    ;
                  end else begin
                    ;
                  end
                end else begin
                  if(d[21]==0)begin
                    ;
                  end else begin
                    ;
                  end
                end
              end
              BIAS_SEND:begin
                if(bias_ready&&bias_request_valid)begin
                  ;
                end
              end
              BIAS_WAIT:begin
                if(bias_valid)begin
                  if(bias_response_bad)begin
                    ;
                  end else begin
                    if(token+1<mt)begin
                      ;
                    end else begin
                      ;
                    end
                  end
                end
              end
              OUTPUT_BEGIN:begin
                if(bulk_output)begin
                  ;
                end else begin
                  if(pack_m4_output)begin
                    if(m4_count==3)begin
                      ;
                    end else begin
                      if(row+1==d[16])begin
                        ;
                      end else begin
                        ;
                      end
                    end
                  end else begin
                    if(!pack_m1_output)begin
                      ;
                    end else begin
                      if(output_pack_count==3)begin
                        ;
                      end else begin
                        if(row+1==d[16])begin
                          ;
                        end else begin
                          ;
                        end
                      end
                    end
                  end
                end
              end
              BULK_STORE:begin
                ;
              end
              BULK_NEXT:begin
                if(token+1<mt)begin
                  ;
                end else begin
                  if(bulk_count==127||row+1==d[16])begin
                    ;
                  end else begin
                    ;
                  end
                end
              end
              BULK_FLUSH:begin
                if(token==mt)begin
                  ;
                end else begin
                  case(bulk_offset==({2'b0,bulk_rows}<<2))
                    1'b1:;
                    default:begin
                      if(bulk_can_burst)begin
                        ;
                      end else begin
                        ;
                      end
                    end
                  endcase
                end
              end
              BULK_TAIL_WRITE:begin
                ;
              end
              OUTPUT_PACK_TAIL:begin
                if(output_pack_tail==output_pack_count)begin
                  ;
                end else begin
                  ;
                end
              end
              OUTPUT_M4_FLUSH:begin
                if(token==mt)begin
                  ;
                end else begin
                  ;
                end
              end
              OUTPUT_M4_TAIL:begin
                if(token==mt)begin
                  ;
                end else begin
                  case(m4_tail==m4_count)
                    1'b1:;
                    default:begin
                      ;
                    end
                  endcase
                end
              end
              OUTPUT_WRITE:begin
                if(token==mt)begin
                  ;
                end else begin
                  ;
                end
              end
              AUDIT_BEGIN:begin
                if(d[28]==0 || 32'(offset)==address_mul_u3(32'(groups),mt))begin
                  ;
                end else begin
                  ;
                end
              end
              AUDIT_WRITE:begin
                ;
              end
              ROW_END:begin
                if(row+1<d[16])begin
                  ;
                end else begin
                  if(32'(mb)+32'(mt)<d[15])begin
                    ;
                  end else begin
                    ;
                  end
                end
              end
              RAM_REQ:begin
                ;
              end
              RAM_WAIT:begin
                ;
              end
              RAM_WRITE:begin
                ;
              end
              DMA_REQ:begin
                if(dma_ready&&dma_valid)begin
                  ;
                end
              end
              DMA_WAIT:begin
                if(dma_result_valid)begin
                  if(dma_resp!=0)begin
                    ;
                  end else begin
                    ;
                  end
                end
              end
              DRAIN:begin
                if(transport_drained && arithmetic_idle && dma_idle && !desc_busy && !abort_publish)begin
                  ;
                end
              end
              PUBLISH:begin
                if(completion_ready&&completion_valid)begin
                  ;
                end
              end
              default:begin
                ;
              end
            endcase
          end
        end
      end
      // A validated error wins over a coincident clear or earlier timeout.
      if(fp_response_error)begin
        status<=-9;
      end else if(reset_grant)begin
        status<=0;
      end else begin
        if(fp_abort_pending&&run_active&&!dot_live&&state!=DRAIN)begin
          status<=-9;
        end else begin
          if((stop_new || timeout_fault) && !state_idle && state!=DRAIN && state!=PUBLISH && !dot_live)begin
            if(status==0)begin
              status<=timeout_fault ? -7 : -11;
            end
          end else begin
            case(state)
              IDLE,DONE:begin
                if(submit_safe && !stop_new && !fp_response_error)begin
                  status<=0;
                end
              end
              DESC_WAIT:begin
                if(desc_done)begin
                  if(desc_status!=0)begin
                    status<=desc_status;
                  end
                end
              end
              VALIDATE_SA:begin
                if(!read_scale_valid)begin
                  status<=-9;
                end
              end
              VALIDATE_A:begin
                if(bad_activation)begin
                  status<=-9;
                end
              end
              WEIGHT_SCALE:begin
                if(!read_scale_valid)begin
                  status<=-9;
                end
              end
              WEIGHT_CHECK:begin
                if(bad_weight)begin
                  status<=-9;
                end
              end
              DOT_WAIT:begin
                if(dot_valid)begin
                  if(abort_now)begin
                    if(status==0)begin
                      status<=(fp_abort_pending||fp_response_error) ? -9 : timeout_fault ? -7 : -11;
                    end
                  end else begin
                    if(dot_bad || dot_protocol || dot_tag!=index || dot_epoch!=epoch)begin
                      status<=-9;
                    end else begin
                      if(inline_restore)begin
                        if(!m1_sa_valid[g])begin
                          status<=-9;
                        end
                      end
                    end
                  end
                end
              end
              INLINE_FP_DRAIN:begin
                if(fp_idle)begin
                  if(fp_expected_group!=groups)begin
                    status<=-9;
                  end
                end
              end
              FP_WAIT:begin
                if(fp_valid)begin
                  if(fp_serial_response_bad)begin
                    status<=-9;
                  end
                end
              end
              BIAS_BEGIN:begin
                if(count==0)begin
                  if(!finite32(scratch_read_data[31:0]))begin
                    status<=-9;
                  end
                end
              end
              BIAS_WAIT:begin
                if(bias_valid)begin
                  if(bias_response_bad)begin
                    status<=-9;
                  end
                end
              end
              DMA_WAIT:begin
                if(dma_result_valid)begin
                  if(dma_resp!=0)begin
                    status<=-11;
                  end
                end
              end
              default:begin
                ;
              end
            endcase
          end
        end
      end
      // Same original FF/reset group, only3nonstate fields, exact old-NBA priority.
      if(fp_abort_pending&&run_active&&!dot_live&&state!=DRAIN)begin
        if(bias_valid)begin
          bias_live<=0;
        end
      end else begin
        if((stop_new || timeout_fault) && !state_idle && state!=DRAIN && state!=PUBLISH && !dot_live)begin
          if(bias_valid)begin
            bias_live<=0;
          end
        end else begin
          case(state)
            BIAS_SEND:begin
              if(bias_ready&&bias_request_valid)begin
                bias_live<=1;
              end else begin
                if(bias_valid)begin
                  bias_live<=0;
                end
              end
            end
            default:begin
              if(bias_valid)begin
                bias_live<=0;
              end
            end
          endcase
        end
      end
      if(reset_grant)begin
        phase<=0;
      end else begin
        if(fp_abort_pending&&run_active&&!dot_live&&state!=DRAIN)begin
          phase<=0;
        end else begin
          if((stop_new || timeout_fault) && !state_idle && state!=DRAIN && state!=PUBLISH && !dot_live)begin
            phase<=0;
          end else begin
            case(state)
              IDLE,DONE:begin
                if(submit_safe && !stop_new && !fp_response_error)begin
                  phase<=0;
                end
              end
              DESC_WAIT:begin
                if(desc_done)begin
                  case(desc_status!=0)
                    1'b1:;
                    default:begin
                      phase<=1;
                    end
                  endcase
                end
              end
              PRELOAD_SA:begin
                if(resident_active||offset==address_mul_u3(32'(groups),mt)*4)begin
                  phase<=0;
                end
              end
              ROW_BEGIN:begin
                phase<=1;
              end
              ROW_BIAS:begin
                case(d[21]!=0)
                  1'b1:;
                  default:begin
                    phase<=2;
                  end
                endcase
              end
              DOT_WAIT:begin
                if(dot_valid)begin
                  if(abort_now)begin
                    phase<=0;
                  end else begin
                    case(dot_bad || dot_protocol || dot_tag!=index || dot_epoch!=epoch)
                      1'b1:;
                      default:begin
                        if(inline_restore)begin
                          if(!m1_sa_valid[g])begin
                            phase<=0;
                          end
                        end
                      end
                    endcase
                  end
                end
              end
              INLINE_FP_SEND:begin
                if(fp_ready&&fp_request_valid)begin
                  case(g+1<groups)
                    1'b1:;
                    default:begin
                      phase<=0;
                    end
                  endcase
                end
              end
              DOT_SAVE:begin
                case(token+1<mt)
                  1'b1:;
                  default:begin
                    case(g+1<groups)
                      1'b1:;
                      default:begin
                        phase<=0;
                      end
                    endcase
                  end
                endcase
              end
              BIAS_BEGIN:begin
                if(count==0)begin
                  phase<=2;
                end else begin
                  if(d[21]==0)begin
                    phase<=3;
                  end
                end
              end
              BIAS_WAIT:begin
                if(bias_valid)begin
                  case(bias_response_bad)
                    1'b1:;
                    default:begin
                      case(token+1<mt)
                        1'b1:;
                        default:begin
                          phase<=3;
                        end
                      endcase
                    end
                  endcase
                end
              end
              ROW_END:begin
                case(row+1<d[16])
                  1'b1:;
                  default:begin
                    if(32'(mb)+32'(mt)<d[15])begin
                      phase<=1;
                    end else begin
                      phase<=0;
                    end
                  end
                endcase
              end
              DMA_WAIT:begin
                if(dma_result_valid)begin
                  if(dma_resp!=0)begin
                    phase<=0;
                  end
                end
              end
              default:begin
                ;
              end
            endcase
          end
        end
      end
      if(reset_grant)begin
        restoring<=0;
      end else begin
        if(fp_abort_pending&&run_active&&!dot_live&&state!=DRAIN)begin
          restoring<=0;
        end else begin
          if((stop_new || timeout_fault) && !state_idle && state!=DRAIN && state!=PUBLISH && !dot_live)begin
            restoring<=0;
          end else begin
            case(state)
              IDLE,DONE:begin
                if(submit_safe && !stop_new && !fp_response_error)begin
                  restoring<=0;
                end
              end
              ROW_BEGIN:begin
                restoring<=0;
              end
              DOT_WAIT:begin
                if(dot_valid)begin
                  case(abort_now)
                    1'b1:;
                    default:begin
                      case(dot_bad || dot_protocol || dot_tag!=index || dot_epoch!=epoch)
                        1'b1:;
                        default:begin
                          if(inline_restore)begin
                            if(!m1_sa_valid[g])begin
                              restoring<=0;
                            end else begin
                              restoring<=1;
                            end
                          end
                        end
                      endcase
                    end
                  endcase
                end
              end
              INLINE_FP_DRAIN:begin
                if(fp_idle)begin
                  if(fp_expected_group!=groups)begin
                    restoring<=0;
                  end
                end
              end
              DOT_SAVE:begin
                case(token+1<mt)
                  1'b1:;
                  default:begin
                    case(g+1<groups)
                      1'b1:;
                      default:begin
                        restoring<=1;
                      end
                    endcase
                  end
                endcase
              end
              FP_WAIT:begin
                if(fp_valid)begin
                  if(fp_serial_response_bad)begin
                    restoring<=0;
                  end
                end
              end
              BIAS_BEGIN:begin
                case(count==0)
                  1'b1:;
                  default:begin
                    if(d[21]==0)begin
                      restoring<=0;
                    end
                  end
                endcase
              end
              BIAS_WAIT:begin
                if(bias_valid)begin
                  if(bias_response_bad)begin
                    restoring<=0;
                  end else begin
                    case(token+1<mt)
                      1'b1:;
                      default:begin
                        restoring<=0;
                      end
                    endcase
                  end
                end
              end
              DMA_WAIT:begin
                if(dma_result_valid)begin
                  if(dma_resp!=0)begin
                    restoring<=0;
                  end
                end
              end
              default:begin
                ;
              end
            endcase
          end
        end
      end
      // Original y-array last-NBA precedence, one physical word at a time.
      if(fp_abort_pending&&run_active&&!dot_live&&state!=DRAIN)begin
        if(fp_stream_response)begin
          if(!fp_bad_response)begin
            if(fp_token_q==3'd0)begin
              y[0]<=fp_partial;
            end
          end
        end
      end else begin
        if((stop_new || timeout_fault) && !state_idle && state!=DRAIN && state!=PUBLISH && !dot_live)begin
          if(fp_stream_response)begin
            if(!fp_bad_response)begin
              if(fp_token_q==3'd0)begin
                y[0]<=fp_partial;
              end
            end
          end
        end else begin
          case(state)
            RESTORE_BEGIN:begin
              y[0]<=0;
            end
            FP_WAIT:begin
              if(fp_valid)begin
                if(fp_serial_response_bad)begin
                  if(fp_stream_response)begin
                    if(!fp_bad_response)begin
                      if(fp_token_q==3'd0)begin
                        y[0]<=fp_partial;
                      end
                    end
                  end
                end else begin
                  if(fp_token_q==3'd0)begin
                    y[0]<=fp_partial;
                  end else begin
                    if(fp_stream_response)begin
                      if(!fp_bad_response)begin
                        if(fp_token_q==3'd0)begin
                          y[0]<=fp_partial;
                        end
                      end
                    end
                  end
                end
              end else begin
                if(fp_stream_response)begin
                  if(!fp_bad_response)begin
                    if(fp_token_q==3'd0)begin
                      y[0]<=fp_partial;
                    end
                  end
                end
              end
            end
            BIAS_WAIT:begin
              if(bias_valid)begin
                if(bias_response_bad)begin
                  if(fp_stream_response)begin
                    if(!fp_bad_response)begin
                      if(fp_token_q==3'd0)begin
                        y[0]<=fp_partial;
                      end
                    end
                  end
                end else begin
                  if(bias_token_q==3'd0)begin
                    y[0]<=bias_result;
                  end else begin
                    if(fp_stream_response)begin
                      if(!fp_bad_response)begin
                        if(fp_token_q==3'd0)begin
                          y[0]<=fp_partial;
                        end
                      end
                    end
                  end
                end
              end else begin
                if(fp_stream_response)begin
                  if(!fp_bad_response)begin
                    if(fp_token_q==3'd0)begin
                      y[0]<=fp_partial;
                    end
                  end
                end
              end
            end
            default:begin
              if(fp_stream_response)begin
                if(!fp_bad_response)begin
                  if(fp_token_q==3'd0)begin
                    y[0]<=fp_partial;
                  end
                end
              end
            end
          endcase
        end
      end
      if(fp_abort_pending&&run_active&&!dot_live&&state!=DRAIN)begin
        if(fp_stream_response)begin
          if(!fp_bad_response)begin
            if(fp_token_q==3'd1)begin
              y[1]<=fp_partial;
            end
          end
        end
      end else begin
        if((stop_new || timeout_fault) && !state_idle && state!=DRAIN && state!=PUBLISH && !dot_live)begin
          if(fp_stream_response)begin
            if(!fp_bad_response)begin
              if(fp_token_q==3'd1)begin
                y[1]<=fp_partial;
              end
            end
          end
        end else begin
          case(state)
            RESTORE_BEGIN:begin
              y[1]<=0;
            end
            FP_WAIT:begin
              if(fp_valid)begin
                if(fp_serial_response_bad)begin
                  if(fp_stream_response)begin
                    if(!fp_bad_response)begin
                      if(fp_token_q==3'd1)begin
                        y[1]<=fp_partial;
                      end
                    end
                  end
                end else begin
                  if(fp_token_q==3'd1)begin
                    y[1]<=fp_partial;
                  end else begin
                    if(fp_stream_response)begin
                      if(!fp_bad_response)begin
                        if(fp_token_q==3'd1)begin
                          y[1]<=fp_partial;
                        end
                      end
                    end
                  end
                end
              end else begin
                if(fp_stream_response)begin
                  if(!fp_bad_response)begin
                    if(fp_token_q==3'd1)begin
                      y[1]<=fp_partial;
                    end
                  end
                end
              end
            end
            BIAS_WAIT:begin
              if(bias_valid)begin
                if(bias_response_bad)begin
                  if(fp_stream_response)begin
                    if(!fp_bad_response)begin
                      if(fp_token_q==3'd1)begin
                        y[1]<=fp_partial;
                      end
                    end
                  end
                end else begin
                  if(bias_token_q==3'd1)begin
                    y[1]<=bias_result;
                  end else begin
                    if(fp_stream_response)begin
                      if(!fp_bad_response)begin
                        if(fp_token_q==3'd1)begin
                          y[1]<=fp_partial;
                        end
                      end
                    end
                  end
                end
              end else begin
                if(fp_stream_response)begin
                  if(!fp_bad_response)begin
                    if(fp_token_q==3'd1)begin
                      y[1]<=fp_partial;
                    end
                  end
                end
              end
            end
            default:begin
              if(fp_stream_response)begin
                if(!fp_bad_response)begin
                  if(fp_token_q==3'd1)begin
                    y[1]<=fp_partial;
                  end
                end
              end
            end
          endcase
        end
      end
      if(fp_abort_pending&&run_active&&!dot_live&&state!=DRAIN)begin
        if(fp_stream_response)begin
          if(!fp_bad_response)begin
            if(fp_token_q==3'd2)begin
              y[2]<=fp_partial;
            end
          end
        end
      end else begin
        if((stop_new || timeout_fault) && !state_idle && state!=DRAIN && state!=PUBLISH && !dot_live)begin
          if(fp_stream_response)begin
            if(!fp_bad_response)begin
              if(fp_token_q==3'd2)begin
                y[2]<=fp_partial;
              end
            end
          end
        end else begin
          case(state)
            RESTORE_BEGIN:begin
              y[2]<=0;
            end
            FP_WAIT:begin
              if(fp_valid)begin
                if(fp_serial_response_bad)begin
                  if(fp_stream_response)begin
                    if(!fp_bad_response)begin
                      if(fp_token_q==3'd2)begin
                        y[2]<=fp_partial;
                      end
                    end
                  end
                end else begin
                  if(fp_token_q==3'd2)begin
                    y[2]<=fp_partial;
                  end else begin
                    if(fp_stream_response)begin
                      if(!fp_bad_response)begin
                        if(fp_token_q==3'd2)begin
                          y[2]<=fp_partial;
                        end
                      end
                    end
                  end
                end
              end else begin
                if(fp_stream_response)begin
                  if(!fp_bad_response)begin
                    if(fp_token_q==3'd2)begin
                      y[2]<=fp_partial;
                    end
                  end
                end
              end
            end
            BIAS_WAIT:begin
              if(bias_valid)begin
                if(bias_response_bad)begin
                  if(fp_stream_response)begin
                    if(!fp_bad_response)begin
                      if(fp_token_q==3'd2)begin
                        y[2]<=fp_partial;
                      end
                    end
                  end
                end else begin
                  if(bias_token_q==3'd2)begin
                    y[2]<=bias_result;
                  end else begin
                    if(fp_stream_response)begin
                      if(!fp_bad_response)begin
                        if(fp_token_q==3'd2)begin
                          y[2]<=fp_partial;
                        end
                      end
                    end
                  end
                end
              end else begin
                if(fp_stream_response)begin
                  if(!fp_bad_response)begin
                    if(fp_token_q==3'd2)begin
                      y[2]<=fp_partial;
                    end
                  end
                end
              end
            end
            default:begin
              if(fp_stream_response)begin
                if(!fp_bad_response)begin
                  if(fp_token_q==3'd2)begin
                    y[2]<=fp_partial;
                  end
                end
              end
            end
          endcase
        end
      end
      if(fp_abort_pending&&run_active&&!dot_live&&state!=DRAIN)begin
        if(fp_stream_response)begin
          if(!fp_bad_response)begin
            if(fp_token_q==3'd3)begin
              y[3]<=fp_partial;
            end
          end
        end
      end else begin
        if((stop_new || timeout_fault) && !state_idle && state!=DRAIN && state!=PUBLISH && !dot_live)begin
          if(fp_stream_response)begin
            if(!fp_bad_response)begin
              if(fp_token_q==3'd3)begin
                y[3]<=fp_partial;
              end
            end
          end
        end else begin
          case(state)
            RESTORE_BEGIN:begin
              y[3]<=0;
            end
            FP_WAIT:begin
              if(fp_valid)begin
                if(fp_serial_response_bad)begin
                  if(fp_stream_response)begin
                    if(!fp_bad_response)begin
                      if(fp_token_q==3'd3)begin
                        y[3]<=fp_partial;
                      end
                    end
                  end
                end else begin
                  if(fp_token_q==3'd3)begin
                    y[3]<=fp_partial;
                  end else begin
                    if(fp_stream_response)begin
                      if(!fp_bad_response)begin
                        if(fp_token_q==3'd3)begin
                          y[3]<=fp_partial;
                        end
                      end
                    end
                  end
                end
              end else begin
                if(fp_stream_response)begin
                  if(!fp_bad_response)begin
                    if(fp_token_q==3'd3)begin
                      y[3]<=fp_partial;
                    end
                  end
                end
              end
            end
            BIAS_WAIT:begin
              if(bias_valid)begin
                if(bias_response_bad)begin
                  if(fp_stream_response)begin
                    if(!fp_bad_response)begin
                      if(fp_token_q==3'd3)begin
                        y[3]<=fp_partial;
                      end
                    end
                  end
                end else begin
                  if(bias_token_q==3'd3)begin
                    y[3]<=bias_result;
                  end else begin
                    if(fp_stream_response)begin
                      if(!fp_bad_response)begin
                        if(fp_token_q==3'd3)begin
                          y[3]<=fp_partial;
                        end
                      end
                    end
                  end
                end
              end else begin
                if(fp_stream_response)begin
                  if(!fp_bad_response)begin
                    if(fp_token_q==3'd3)begin
                      y[3]<=fp_partial;
                    end
                  end
                end
              end
            end
            default:begin
              if(fp_stream_response)begin
                if(!fp_bad_response)begin
                  if(fp_token_q==3'd3)begin
                    y[3]<=fp_partial;
                  end
                end
              end
            end
          endcase
        end
      end
      if(!reset_grant&&!control_abort&&stream_active)begin
        if(state==STREAM_SW_BEGIN||state==STREAM_SW_WAIT)phase<=1;
        if(stream_first_a||m1_next_start)begin
          group_elements<=64;beat<=0;token<=0;sw_value<=sw_raw_current_value;
          sw_value_zero<=sw_raw_current_zero;phase<=2;
        end
        if(stream_result&&dma_resp==0)payload_read<=payload_add(payload_read,stream_chunk_bytes);
      end
      // Field-local final overrides for the independently selected banked
      // schedule. The legacy register/state path remains exact when disabled.
      if(bank_active&&!reset_grant&&!control_abort)begin
        if(state==ROW_BEGIN)begin
          for(integer t=0;t<4;t++)y[t]<=0;
          restoring<=1;
        end
        if(fp_bank_response&&!bank_response_bad&&!fp_cancel_q&&!response_cancel_now)y[bank_response_context]<=fp_partial;
        if(state==DOT_WAIT&&dot_valid&&!abort_now&&!dot_bad&&!dot_protocol&&dot_tag==index&&dot_epoch==epoch)begin
          sa_value<=bank_sa_cache[bank_sa_index];
          sa_value_zero<=bank_sa_cache[bank_sa_index]==0;
          if(!bank_sa_valid[bank_sa_index])begin status<=-9;phase<=0;end
        end
        if(state==BANK_FP_SEND&&fp_request_valid&&fp_ready)begin
          beat<=0;
          if(token+1<mt)begin
            token<=token+1'b1;
            local_read_address<=16'(address_mul_u3(32'(padded_k),token+3'd1)+g*64);
          end else if(g+1<groups)begin token<=0;g<=g+1'b1;end
        end
        if(state==BANK_FP_DRAIN&&fp_idle)begin
          token<=0;count<=1;restoring<=0;phase<=2;
          if(!bank_all_restored)begin status<=-9;phase<=0;end
        end
      end
      // submit is the CSR's already accepted doorbell pulse. A late
      // response collision converts it into an identified error job without
      // launching validation, RAM, DMA or arithmetic, or clearing the tuple.
      if(submit_collision_job)begin
        active_descriptor<=descriptor;
        descriptor_no_audit_q<=descriptor[32*28+:32]==0;
        descriptor_inline_restore_q<=(descriptor[32*15+:32]==1)&&(descriptor[32*28+:32]==0);
        descriptor_bank_rows_q<=(descriptor[32*15+:32]>=2)&&(descriptor[32*15+:32]<=4);
        for(integer i=0;i<32;i++)d[i]<=descriptor[32*i+:32];
        rows<=0;tiles<=0;status<=-9;phase<=0;
      end
    end
  end
  // Original nonreset state priorities only; asynchronousreset stays in FF.
  state_t ce_state_next;
  always @* begin
    ce_state_next=state;
    if(reset_grant)begin
      ce_state_next=IDLE;
    end else if(submit_collision_job)begin
      ce_state_next=DRAIN;
    end else begin
      if(fp_abort_pending&&run_active&&!dot_live&&state!=DRAIN)begin
        ce_state_next=DRAIN;
      end else begin
        if((stop_new || timeout_fault) && !state_idle && state!=DRAIN && state!=PUBLISH && !dot_live)begin
          ce_state_next=DRAIN;
        end else begin
          case(state)
            IDLE,DONE:begin
              if(submit_safe && !stop_new && !fp_response_error)begin
                ce_state_next=DESC_START;
              end else begin
                ce_state_next=ce_state_next;
              end
            end
            DESC_START:begin
              ce_state_next=DESC_WAIT;
            end
            DESC_WAIT:begin
              if(desc_done)begin
                if(desc_status!=0)begin
                  ce_state_next=DRAIN;
                end else begin
                  ce_state_next=PRELOAD_A;
                end
              end else begin
                ce_state_next=ce_state_next;
              end
            end
            PRELOAD_A:begin
              if(resident_active||32'(offset)==address_mul_u3(32'(padded_k),mt))begin
                ce_state_next=PRELOAD_SA;
              end else begin
                ce_state_next=state_t'(tuple_ce_call_000[6:0]);
              end
            end
            PRELOAD_SA:begin
              if(resident_active||offset==address_mul_u3(32'(groups),mt)*4)begin
                ce_state_next=state_t'(tuple_ce_call_001[6:0]);
              end else begin
                ce_state_next=state_t'(tuple_ce_call_002[6:0]);
              end
            end
            VALIDATE_SA:begin
              if(!read_scale_valid)begin
                ce_state_next=DRAIN;
              end else begin
                if(resident_group_active)begin
                  if(g+1<groups)ce_state_next=state_t'(tuple_ce_call_005[6:0]);
                  else if(token+1<mt)ce_state_next=state_t'(tuple_ce_call_006[6:0]);
                  else ce_state_next=ROW_BEGIN;
                end else ce_state_next=state_t'(tuple_ce_call_003[6:0]);
              end
            end
            VALIDATE_A:begin
              if(bad_activation)begin
                ce_state_next=DRAIN;
              end else begin
                if(beat!=3)begin
                  ce_state_next=state_t'(tuple_ce_call_004[6:0]);
                end else begin
                  if(g+1<groups)begin
                    ce_state_next=state_t'(tuple_ce_call_005[6:0]);
                  end else begin
                    if(token+1<mt)begin
                      ce_state_next=state_t'(tuple_ce_call_006[6:0]);
                    end else begin
                      ce_state_next=ROW_BEGIN;
                    end
                  end
                end
              end
            end
            ROW_BEGIN:begin
              ce_state_next=inline_restore ? RESTORE_BEGIN : WEIGHT_ROW_BURST ? ROW_WEIGHT_LOAD : ROW_SW;
            end
            ROW_WEIGHT_LOAD:begin
              if(32'(offset)==d[17])begin
                ce_state_next=ROW_SW;
              end else begin
                if(transfer_count>=16)begin
                  ce_state_next=state_t'(tuple_ce_call_007[6:0]);
                end else begin
                  if(transfer_count>=4)begin
                    ce_state_next=state_t'(tuple_ce_call_008[6:0]);
                  end else begin
                    ce_state_next=state_t'(tuple_ce_call_009[6:0]);
                  end
                end
              end
            end
            ROW_SW:begin
              if(g==groups)begin
                ce_state_next=ROW_BIAS;
              end else begin
                ce_state_next=state_t'(tuple_ce_call_010[6:0]);
              end
            end
            ROW_BIAS:begin
              if(d[21]!=0)begin
                ce_state_next=state_t'(tuple_ce_call_011[6:0]);
              end else begin
                ce_state_next=state_t'(tuple_ce_call_012[6:0]);
              end
            end
            BIAS_CHECK:begin
              ce_state_next=state_t'(tuple_ce_call_013[6:0]);
            end
            WEIGHT_SCALE:begin
              if(!read_scale_valid)begin
                ce_state_next=DRAIN;
              end else begin
                if(WEIGHT_ROW_BURST)begin
                  ce_state_next=state_t'(tuple_ce_call_014[6:0]);
                end else begin
                  ce_state_next=WEIGHT_LOAD;
                end
              end
            end
            WEIGHT_LOAD:begin
              if(32'(offset)==32'(group_elements))begin
                ce_state_next=state_t'(tuple_ce_call_015[6:0]);
              end else begin
                if(transfer_count>=16)begin
                  ce_state_next=state_t'(tuple_ce_call_016[6:0]);
                end else begin
                  if(transfer_count>=4)begin
                    ce_state_next=state_t'(tuple_ce_call_017[6:0]);
                  end else begin
                    ce_state_next=state_t'(tuple_ce_call_018[6:0]);
                  end
                end
              end
            end
            WEIGHT_CHECK:begin
              if(bad_weight)begin
                ce_state_next=DRAIN;
              end else begin
                if((beat+1)*16<group_elements)begin
                  if(!stream_group)begin
                    ce_state_next=state_t'(tuple_ce_call_019[6:0]);
                  end else begin
                    ce_state_next=ce_state_next;
                  end
                end else begin
                  if(first_a_read)begin
                    ce_state_next=DOT_A;
                  end else begin
                    ce_state_next=state_t'(tuple_ce_call_020[6:0]);
                  end
                end
              end
            end
            DOT_A:begin
              if(stream_group)begin
                if(dot_ready&&dot_request_valid)begin
                  if((beat+1)*16>=group_elements)begin
                    ce_state_next=DOT_WAIT;
                  end else begin
                    ce_state_next=ce_state_next;
                  end
                end else begin
                  ce_state_next=ce_state_next;
                end
              end else begin
                if(WEIGHT_GROUP_CACHE)begin
                  ce_state_next=DOT_SEND;
                end else begin
                  ce_state_next=state_t'(7'(fetch_update(weight_local_base+16'(beat*16),DOT_W) >> 0));
                end
              end
            end
            DOT_W:begin
              ce_state_next=DOT_SEND;
            end
            DOT_SEND:begin
              if(dot_ready&&dot_request_valid)begin
                if((beat+1)*16>=group_elements)begin
                  ce_state_next=DOT_WAIT;
                end else begin
                  ce_state_next=state_t'(tuple_ce_call_022[6:0]);
                end
              end else begin
                ce_state_next=ce_state_next;
              end
            end
            DOT_WAIT:begin
              if(dot_valid)begin
                if(abort_now)begin
                  ce_state_next=DRAIN;
                end else begin
                  if(dot_bad || dot_protocol || dot_tag!=index || dot_epoch!=epoch)begin
                    ce_state_next=DRAIN;
                  end else begin
                    if(inline_restore)begin
                      if(!m1_sa_valid[g])begin
                        ce_state_next=DRAIN;
                      end else begin
                        ce_state_next=INLINE_FP_SEND;
                      end
                    end else begin
                      ce_state_next=state_t'(tuple_ce_call_023[6:0]);
                    end
                  end
                end
              end else begin
                ce_state_next=ce_state_next;
              end
            end
            INLINE_FP_SEND:begin
              if(fp_ready&&fp_request_valid)begin
                if(g+1<groups)begin
                  if(next_sw_read)begin
                    ce_state_next=WEIGHT_SCALE;
                  end else begin
                    ce_state_next=state_t'(tuple_ce_call_024[6:0]);
                  end
                end else begin
                  ce_state_next=INLINE_FP_DRAIN;
                end
              end else begin
                ce_state_next=ce_state_next;
              end
            end
            INLINE_FP_DRAIN:begin
              if(fp_idle)begin
                if(fp_expected_group!=groups)begin
                  ce_state_next=DRAIN;
                end else begin
                  ce_state_next=BIAS_BEGIN;
                end
              end else begin
                ce_state_next=ce_state_next;
              end
            end
            DOT_SAVE:begin
              if(token+1<mt)begin
                ce_state_next=state_t'(tuple_ce_call_025[6:0]);
              end else begin
                if(g+1<groups)begin
                  ce_state_next=state_t'(tuple_ce_call_026[6:0]);
                end else begin
                  ce_state_next=RESTORE_BEGIN;
                end
              end
            end
            RESTORE_BEGIN:begin
              if(inline_restore)begin
                ce_state_next=WEIGHT_ROW_BURST ? ROW_WEIGHT_LOAD : ROW_SW;
              end else begin
                ce_state_next=state_t'(tuple_ce_call_027[6:0]);
              end
            end
            RESTORE_DOT:begin
              ce_state_next=state_t'(tuple_ce_call_028[6:0]);
            end
            RESTORE_SA:begin
              ce_state_next=state_t'(tuple_ce_call_029[6:0]);
            end
            RESTORE_SW:begin
              ce_state_next=FP_SEND;
            end
            FP_SEND:begin
              if(fp_ready&&fp_request_valid)begin
                if(!stream_restore)begin
                  ce_state_next=FP_WAIT;
                end else begin
                  if(g+1<groups)begin
                    ce_state_next=state_t'(tuple_ce_call_030[6:0]);
                  end else begin
                    ce_state_next=FP_ROW_DRAIN;
                  end
                end
              end else begin
                ce_state_next=ce_state_next;
              end
            end
            FP_ROW_DRAIN:begin
              if(fp_idle)begin
                if(token+1<mt)begin
                  ce_state_next=state_t'(tuple_ce_call_031[6:0]);
                end else begin
                  ce_state_next=BIAS_BEGIN;
                end
              end else begin
                ce_state_next=ce_state_next;
              end
            end
            FP_WAIT:begin
              if(fp_valid)begin
                if(fp_serial_response_bad)begin
                  ce_state_next=DRAIN;
                end else begin
                  if(d[28]!=0)begin
                    ce_state_next=state_t'(tuple_ce_call_032[6:0]);
                  end else begin
                    ce_state_next=AUDIT_SAVE;
                  end
                end
              end else begin
                ce_state_next=ce_state_next;
              end
            end
            AUDIT_SAVE:begin
              if(token+1<mt)begin
                ce_state_next=state_t'(tuple_ce_call_033[6:0]);
              end else begin
                if(g+1<groups)begin
                  ce_state_next=state_t'(tuple_ce_call_034[6:0]);
                end else begin
                  ce_state_next=BIAS_BEGIN;
                end
              end
            end
            BIAS_BEGIN:begin
              if(count==0)begin
                if(!finite32(scratch_read_data[31:0]))begin
                  ce_state_next=DRAIN;
                end else begin
                  ce_state_next=state_t'(tuple_ce_call_035[6:0]);
                end
              end else begin
                if(d[21]==0)begin
                  ce_state_next=OUTPUT_BEGIN;
                end else begin
                  ce_state_next=BIAS_SEND;
                end
              end
            end
            BIAS_SEND:begin
              if(bias_ready&&bias_request_valid)begin
                ce_state_next=BIAS_WAIT;
              end else begin
                ce_state_next=ce_state_next;
              end
            end
            BIAS_WAIT:begin
              if(bias_valid)begin
                if(bias_response_bad)begin
                  ce_state_next=DRAIN;
                end else begin
                  if(token+1<mt)begin
                    ce_state_next=BIAS_SEND;
                  end else begin
                    ce_state_next=OUTPUT_BEGIN;
                  end
                end
              end else begin
                ce_state_next=ce_state_next;
              end
            end
            OUTPUT_BEGIN:begin
              if(bulk_output)begin
                ce_state_next=BULK_STORE;
              end else begin
                if(pack_m4_output)begin
                  if(m4_count==3)begin
                    ce_state_next=OUTPUT_M4_FLUSH;
                  end else begin
                    if(row+1==d[16])begin
                      ce_state_next=OUTPUT_M4_TAIL;
                    end else begin
                      ce_state_next=AUDIT_BEGIN;
                    end
                  end
                end else begin
                  if(!pack_m1_output)begin
                    ce_state_next=OUTPUT_WRITE;
                  end else begin
                    if(output_pack_count==3)begin
                      ce_state_next=state_t'(tuple_ce_call_036[6:0]);
                    end else begin
                      if(row+1==d[16])begin
                        ce_state_next=OUTPUT_PACK_TAIL;
                      end else begin
                        ce_state_next=AUDIT_BEGIN;
                      end
                    end
                  end
                end
              end
            end
            BULK_STORE:begin
              ce_state_next=state_t'(tuple_ce_call_037[6:0]);
            end
            BULK_NEXT:begin
              if(token+1<mt)begin
                ce_state_next=BULK_STORE;
              end else begin
                if(bulk_count==127||row+1==d[16])begin
                  ce_state_next=BULK_FLUSH;
                end else begin
                  ce_state_next=AUDIT_BEGIN;
                end
              end
            end
            BULK_FLUSH:begin
              if(token==mt)begin
                ce_state_next=AUDIT_BEGIN;
              end else begin
                if(bulk_offset==({2'b0,bulk_rows}<<2))begin
                  ce_state_next=ce_state_next;
                end else begin
                  if(bulk_can_burst)begin
                    ce_state_next=DMA_REQ;
                  end else begin
                    ce_state_next=state_t'(tuple_ce_call_038[6:0]);
                  end
                end
              end
            end
            BULK_TAIL_WRITE:begin
              ce_state_next=state_t'(tuple_ce_call_039[6:0]);
            end
            OUTPUT_PACK_TAIL:begin
              if(output_pack_tail==output_pack_count)begin
                ce_state_next=AUDIT_BEGIN;
              end else begin
                ce_state_next=state_t'(tuple_ce_call_040[6:0]);
              end
            end
            OUTPUT_M4_FLUSH:begin
              if(token==mt)begin
                ce_state_next=AUDIT_BEGIN;
              end else begin
                ce_state_next=state_t'(tuple_ce_call_041[6:0]);
              end
            end
            OUTPUT_M4_TAIL:begin
              if(token==mt)begin
                ce_state_next=AUDIT_BEGIN;
              end else begin
                if(m4_tail==m4_count)begin
                  ce_state_next=ce_state_next;
                end else begin
                  ce_state_next=state_t'(tuple_ce_call_042[6:0]);
                end
              end
            end
            OUTPUT_WRITE:begin
              if(token==mt)begin
                ce_state_next=AUDIT_BEGIN;
              end else begin
                ce_state_next=state_t'(tuple_ce_call_043[6:0]);
              end
            end
            AUDIT_BEGIN:begin
              if(d[28]==0 || 32'(offset)==address_mul_u3(32'(groups),mt))begin
                ce_state_next=ROW_END;
              end else begin
                ce_state_next=state_t'(tuple_ce_call_044[6:0]);
              end
            end
            AUDIT_WRITE:begin
              ce_state_next=state_t'(tuple_ce_call_045[6:0]);
            end
            ROW_END:begin
              if(row+1<d[16])begin
                ce_state_next=ROW_BEGIN;
              end else begin
                if(32'(mb)+32'(mt)<d[15])begin
                  ce_state_next=PRELOAD_A;
                end else begin
                  ce_state_next=DRAIN;
                end
              end
            end
            RAM_REQ:begin
              ce_state_next=SCRATCH_RESPONSE_BYPASS ? (return_state==BULK_TAIL_WRITE ? BULK_TAIL_CAPTURE : return_state) : RAM_WAIT;
            end
            RAM_WAIT:begin
              ce_state_next=return_state==BULK_TAIL_WRITE ? BULK_TAIL_CAPTURE : return_state;
            end
            BULK_TAIL_CAPTURE:ce_state_next=BULK_TAIL_WRITE;
            RAM_WRITE:begin
              ce_state_next=write_return;
            end
            DMA_REQ:begin
              if(dma_ready&&dma_valid)begin
                ce_state_next=DMA_WAIT;
              end else begin
                ce_state_next=ce_state_next;
              end
            end
            DMA_WAIT:begin
              if(dma_result_valid)begin
                if(dma_resp!=0)begin
                  ce_state_next=DRAIN;
                end else begin
                  ce_state_next=return_state;
                end
              end else begin
                ce_state_next=ce_state_next;
              end
            end
            DRAIN:begin
              if(transport_drained && arithmetic_idle && dma_idle && !desc_busy && !abort_publish)begin
                ce_state_next=PUBLISH;
              end else begin
                ce_state_next=ce_state_next;
              end
            end
            PUBLISH:begin
              if(completion_ready&&completion_valid)begin
                ce_state_next=DONE;
              end else begin
                ce_state_next=ce_state_next;
              end
            end
            default:begin
              ce_state_next=DRAIN;
            end
          endcase
        end
      end
    end
    if(stream_active&&!reset_grant&&!control_abort)begin
      case(state)
        ROW_WEIGHT_LOAD:ce_state_next=STREAM_SW_BEGIN;
        STREAM_SW_BEGIN:ce_state_next=(row[1:0]!=0||sw_start_ready)?STREAM_SW_WAIT:STREAM_SW_BEGIN;
        STREAM_SW_WAIT:ce_state_next=sw_certificate&&sw_block_matches?ROW_BIAS:STREAM_SW_WAIT;
        ROW_BIAS:if(d[21]==0)ce_state_next=STREAM_W_WAIT;
        BIAS_BEGIN:if(count==0&&finite32(scratch_read_data[31:0]))ce_state_next=STREAM_W_WAIT;
        STREAM_W_WAIT:ce_state_next=stream_first_a?(inline_restore?DOT_A:WEIGHT_CHECK):STREAM_W_WAIT;
        DOT_SAVE:if(!inline_restore&&token+1==mt&&g+1<groups)ce_state_next=STREAM_W_WAIT;
        INLINE_FP_SEND:if(fp_ready&&fp_request_valid&&g+1<groups)ce_state_next=m1_next_start ? DOT_A : STREAM_W_WAIT;
        default:;
      endcase
    end
    if(bank_active&&!reset_grant&&!control_abort)begin
      case(state)
        STREAM_W_WAIT:if(stream_first_a)ce_state_next=DOT_A;
        DOT_WAIT:if(dot_valid&&!abort_now&&!dot_bad&&!dot_protocol&&dot_tag==index&&dot_epoch==epoch)
          ce_state_next=bank_sa_valid[bank_sa_index]?BANK_FP_SEND:DRAIN;
        BANK_FP_SEND:begin
          ce_state_next=BANK_FP_SEND;
          if(fp_ready&&fp_request_valid)begin
            if(token+1<mt)ce_state_next=RAM_REQ;
            else if(g+1<groups)ce_state_next=STREAM_W_WAIT;
            else ce_state_next=BANK_FP_DRAIN;
          end
        end
        BANK_FP_DRAIN:begin
          ce_state_next=BANK_FP_DRAIN;
          if(fp_idle)ce_state_next=bank_all_restored?BIAS_BEGIN:DRAIN;
        end
        default:;
      endcase
    end
  end
  always_ff @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)state<=IDLE;
    else state<=ce_state_next;
  end


  // Original field-local last-NBA precedence; all RHSs read original old state.
  always_ff @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)begin
      output_pack_count<=0;
    end else begin
      if(reset_grant)begin
        output_pack_count<=0;
      end else begin
        if(fp_abort_pending&&run_active&&!dot_live&&state!=DRAIN)begin
          if(state==DRAIN)begin
            output_pack_count<=0;
          end
        end else begin
          if((stop_new || timeout_fault) && !state_idle && state!=DRAIN && state!=PUBLISH && !dot_live)begin
            if(state==DRAIN)begin
              output_pack_count<=0;
            end
          end else begin
            case(state)
              IDLE,DONE:begin
                if(submit_safe && !stop_new && !fp_response_error)begin
                  output_pack_count<=0;
                end else begin
                  if(state==DRAIN)begin
                    output_pack_count<=0;
                  end
                end
              end
              OUTPUT_BEGIN:begin
                if(bulk_output)begin
                  if(state==DRAIN)begin
                    output_pack_count<=0;
                  end
                end else begin
                  if(pack_m4_output)begin
                    if(state==DRAIN)begin
                      output_pack_count<=0;
                    end
                  end else begin
                    if(!pack_m1_output)begin
                      if(state==DRAIN)begin
                        output_pack_count<=0;
                      end
                    end else begin
                      if(output_pack_count==3)begin
                        output_pack_count<=0;
                      end else begin
                        output_pack_count<=output_pack_count+1'b1;
                      end
                    end
                  end
                end
              end
              OUTPUT_PACK_TAIL:begin
                if(output_pack_tail==output_pack_count)begin
                  output_pack_count<=0;
                end else begin
                  if(state==DRAIN)begin
                    output_pack_count<=0;
                  end
                end
              end
              default:begin
                if(state==DRAIN)begin
                  output_pack_count<=0;
                end
              end
            endcase
          end
        end
      end
    end
  end
  always_ff @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)begin
      output_pack_tail<=0;
    end else begin
      if(reset_grant)begin
        output_pack_tail<=0;
      end else begin
        if(fp_abort_pending&&run_active&&!dot_live&&state!=DRAIN)begin
          if(state==DRAIN)begin
            output_pack_tail<=0;
          end
        end else begin
          if((stop_new || timeout_fault) && !state_idle && state!=DRAIN && state!=PUBLISH && !dot_live)begin
            if(state==DRAIN)begin
              output_pack_tail<=0;
            end
          end else begin
            case(state)
              IDLE,DONE:begin
                if(submit_safe && !stop_new && !fp_response_error)begin
                  output_pack_tail<=0;
                end else begin
                  if(state==DRAIN)begin
                    output_pack_tail<=0;
                  end
                end
              end
              OUTPUT_BEGIN:begin
                if(bulk_output)begin
                  if(state==DRAIN)begin
                    output_pack_tail<=0;
                  end
                end else begin
                  if(pack_m4_output)begin
                    if(state==DRAIN)begin
                      output_pack_tail<=0;
                    end
                  end else begin
                    if(!pack_m1_output)begin
                      if(state==DRAIN)begin
                        output_pack_tail<=0;
                      end
                    end else begin
                      if(output_pack_count==3)begin
                        if(state==DRAIN)begin
                          output_pack_tail<=0;
                        end
                      end else begin
                        if(row+1==d[16])begin
                          output_pack_tail<=0;
                        end else begin
                          if(state==DRAIN)begin
                            output_pack_tail<=0;
                          end
                        end
                      end
                    end
                  end
                end
              end
              OUTPUT_PACK_TAIL:begin
                if(output_pack_tail==output_pack_count)begin
                  if(state==DRAIN)begin
                    output_pack_tail<=0;
                  end
                end else begin
                  output_pack_tail<=output_pack_tail+1'b1;
                end
              end
              default:begin
                if(state==DRAIN)begin
                  output_pack_tail<=0;
                end
              end
            endcase
          end
        end
      end
    end
  end
  always_ff @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)begin
      m4_count<=0;
    end else begin
      if(fp_abort_pending&&run_active&&!dot_live&&state!=DRAIN)begin
        if(state==DRAIN)begin
          m4_count<=0;
        end
      end else begin
        if((stop_new || timeout_fault) && !state_idle && state!=DRAIN && state!=PUBLISH && !dot_live)begin
          if(state==DRAIN)begin
            m4_count<=0;
          end
        end else begin
          case(state)
            IDLE,DONE:begin
              if(submit_safe && !stop_new && !fp_response_error)begin
                m4_count<=0;
              end else begin
                if(state==DRAIN)begin
                  m4_count<=0;
                end
              end
            end
            OUTPUT_BEGIN:begin
              if(bulk_output)begin
                if(state==DRAIN)begin
                  m4_count<=0;
                end
              end else begin
                if(pack_m4_output)begin
                  if(m4_count==3)begin
                    m4_count<=0;
                  end else begin
                    m4_count<=m4_count+1'b1;
                  end
                end else begin
                  if(state==DRAIN)begin
                    m4_count<=0;
                  end
                end
              end
            end
            OUTPUT_M4_TAIL:begin
              if(token==mt)begin
                m4_count<=0;
              end else begin
                if(state==DRAIN)begin
                  m4_count<=0;
                end
              end
            end
            default:begin
              if(state==DRAIN)begin
                m4_count<=0;
              end
            end
          endcase
        end
      end
    end
  end
  always_ff @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)begin
      m4_tail<=0;
    end else begin
      if(fp_abort_pending&&run_active&&!dot_live&&state!=DRAIN)begin
        if(state==DRAIN)begin
          m4_tail<=0;
        end
      end else begin
        if((stop_new || timeout_fault) && !state_idle && state!=DRAIN && state!=PUBLISH && !dot_live)begin
          if(state==DRAIN)begin
            m4_tail<=0;
          end
        end else begin
          case(state)
            IDLE,DONE:begin
              if(submit_safe && !stop_new && !fp_response_error)begin
                m4_tail<=0;
              end else begin
                if(state==DRAIN)begin
                  m4_tail<=0;
                end
              end
            end
            OUTPUT_BEGIN:begin
              if(bulk_output)begin
                if(state==DRAIN)begin
                  m4_tail<=0;
                end
              end else begin
                if(pack_m4_output)begin
                  if(m4_count==3)begin
                    if(state==DRAIN)begin
                      m4_tail<=0;
                    end
                  end else begin
                    if(row+1==d[16])begin
                      m4_tail<=0;
                    end else begin
                      if(state==DRAIN)begin
                        m4_tail<=0;
                      end
                    end
                  end
                end else begin
                  if(state==DRAIN)begin
                    m4_tail<=0;
                  end
                end
              end
            end
            OUTPUT_M4_TAIL:begin
              if(token==mt)begin
                m4_tail<=0;
              end else begin
                if(m4_tail==m4_count)begin
                  m4_tail<=0;
                end else begin
                  m4_tail<=m4_tail+1'b1;
                end
              end
            end
            default:begin
              if(state==DRAIN)begin
                m4_tail<=0;
              end
            end
          endcase
        end
      end
    end
  end
  always_ff @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)begin
      dot_live<=0;
    end else begin
      if(fp_abort_pending&&run_active&&!dot_live&&state!=DRAIN)begin
        if(dot_valid)begin
          dot_live<=0;
        end
      end else begin
        if((stop_new || timeout_fault) && !state_idle && state!=DRAIN && state!=PUBLISH && !dot_live)begin
          if(dot_valid)begin
            dot_live<=0;
          end
        end else begin
          case(state)
            DOT_A:begin
              if(stream_group)begin
                if(dot_ready&&dot_request_valid)begin
                  dot_live<=1;
                end else begin
                  if(dot_valid)begin
                    dot_live<=0;
                  end
                end
              end else begin
                if(dot_valid)begin
                  dot_live<=0;
                end
              end
            end
            DOT_SEND:begin
              if(dot_ready&&dot_request_valid)begin
                dot_live<=1;
              end else begin
                if(dot_valid)begin
                  dot_live<=0;
                end
              end
            end
            default:begin
              if(dot_valid)begin
                dot_live<=0;
              end
            end
          endcase
        end
      end
    end
  end
  always_comb begin
    fp_expected_group_next=fp_expected_group;
    begin
      if(fp_abort_pending&&run_active&&!dot_live&&state!=DRAIN)begin
        if(fp_stream_response)begin
          fp_expected_group_next=fp_expected_group+1'b1;
        end
      end else begin
        if((stop_new || timeout_fault) && !state_idle && state!=DRAIN && state!=PUBLISH && !dot_live)begin
          if(fp_stream_response)begin
            fp_expected_group_next=fp_expected_group+1'b1;
          end
        end else begin
          case(state)
            RESTORE_BEGIN:begin
              fp_expected_group_next=0;
            end
            FP_ROW_DRAIN:begin
              if(fp_idle)begin
                if(token+1<mt)begin
                  fp_expected_group_next=0;
                end else begin
                  if(fp_stream_response)begin
                    fp_expected_group_next=fp_expected_group+1'b1;
                  end
                end
              end else begin
                if(fp_stream_response)begin
                  fp_expected_group_next=fp_expected_group+1'b1;
                end
              end
            end
            default:begin
              if(fp_stream_response)begin
                fp_expected_group_next=fp_expected_group+1'b1;
              end
            end
          endcase
        end
      end
    end
  end

  always_ff @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)fp_expected_group<=0;
    else fp_expected_group<=fp_expected_group_next;
  end

  always_ff @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)begin
      bulk_count<=0;bulk_rows<=0;bulk_offset<=0;
    end else if(reset_grant)begin
      bulk_count<=0;bulk_rows<=0;bulk_offset<=0;
    end else if(!control_abort)begin
      case(state)
        IDLE,DONE:if(submit_safe&&!stop_new)begin
          bulk_count<=0;bulk_rows<=0;bulk_offset<=0;
        end
        BULK_NEXT:if(!(token+1<mt))begin
          bulk_count<=bulk_count+1'b1;
          if(bulk_count==127||row+1==d[16])begin
            bulk_rows<=bulk_count+1'b1;bulk_offset<=0;
          end
        end
        BULK_FLUSH:if(token==mt)bulk_count<=0;
          else if(bulk_offset==({2'b0,bulk_rows}<<2))bulk_offset<=0;
          else if(bulk_can_burst)bulk_offset<=bulk_offset+10'(bulk_bytes);
        BULK_TAIL_WRITE:bulk_offset<=bulk_offset+4;
        default:;
      endcase
    end
  end
  // Select each transport source only at its actual state-local consumer.
  // Feeding revoke-masked Sw data through every scratch classifier created
  // an epoch -> abort -> Sw payload -> scratch predicate -> address chain,
  // even though its selector states cannot occur together.  All same-cycle
  // abort/identity/certificate gates remain on the real DMA/DOT/FP offers.
  assign weight_check_data=stream_active&&!inline_restore ? capture_raw_data : scratch_read_data;
  assign restore_sw_data=stream_active&&!inline_restore ? {4{sw_current_value}} : scratch_read_data;
  // Private zero metadata uses the same raw scale and byte-window capture.
  // Revocation still gates every actual offer and arithmetic consumer.
  assign restore_sw_raw_data=stream_active&&!inline_restore ? {4{sw_raw_current_value}} : scratch_read_data;
  // Keep the public bit parameter; saved data exists only when it is read.
  generate
    if(SCRATCH_RESPONSE_BYPASS)begin: scratch_response_bypass
      assign scratch_read_data=ram_q;
    end else begin: scratch_response_registered
      logic [127:0] saved;
      assign scratch_read_data=saved;
  always_ff @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)begin
      saved<=0;
    end else begin
      case(fp_abort_pending&&run_active&&!dot_live&&state!=DRAIN)
        1'b1:;
        default:begin
          case((stop_new || timeout_fault) && !state_idle && state!=DRAIN && state!=PUBLISH && !dot_live)
            1'b1:;
            default:begin
              case(state)
                RAM_WAIT:begin
                  saved<=ram_q;
                end
                default:begin
                  ;
                end
              endcase
            end
          endcase
        end
      endcase
    end
  end
    end
  endgenerate
endmodule

// The registered lookahead is valid across arbitrary stalls. At each enabled
// edge the low limbs increment and flags predict whether their new value is
// all ones. Each adder is only16 bits; no cycle or counter bit is dropped.
module nx_ce64_phase_counter64 #(parameter logic [63:0] RESET_VALUE=64'd0,parameter bit WHOLE_X_PROPAGATION=0)(
  input logic clk,reset_n,clear,enable,
  output logic [63:0] value,
  output logic [63:0] value_next
);
  logic [2:0] carry;
  always_comb begin
    value_next=value;
    if(!reset_n)value_next=RESET_VALUE;
    else if(clear)value_next=RESET_VALUE;
    else if(enable)begin
      value_next[15:0]=value[15:0]+16'd1;
      value_next[31:16]=value[31:16]+16'(carry[0]);
      value_next[47:32]=value[47:32]+16'(carry[1]);
      value_next[63:48]=value[63:48]+16'(carry[2]);
      if(WHOLE_X_PROPAGATION)case(^value)
        1'b0,1'b1:begin end
        default:value_next=value+64'd1;
      endcase
    end
  end
  always_ff @(posedge clk or negedge reset_n)begin
    if(!reset_n)begin
      value<=RESET_VALUE;
      carry<={(&RESET_VALUE[47:0]),(&RESET_VALUE[31:0]),(&RESET_VALUE[15:0])};
    end else if(clear)begin
      value<=RESET_VALUE;
      carry<={(&RESET_VALUE[47:0]),(&RESET_VALUE[31:0]),(&RESET_VALUE[15:0])};
    end else if(enable)begin
      value<=value_next;
      carry[0]<=value[15:0]==16'hfffe;
      carry[1]<=value[31:0]==32'hfffffffe;
      carry[2]<=value[47:0]==48'hfffffffffffe;
    end
  end
endmodule
