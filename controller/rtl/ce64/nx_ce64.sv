module nx_ce64 #(parameter bit CROSS_GROUP_WRITE=1,AQSA_RESIDENT=1,W_PREFETCH=1,A_W_BANKED=1,LONG_PV=0,HEAD_ARGMAX=0) (
  input logic clk, platform_reset_n, external_isolate, external_window_isolate, startup_authorized,
  input logic guard_idle,guard_fault,native_safely_drained,native_quarantined,
  input logic [31:0] visible_fault_address,
  axi4_if.slave mmio,
  axi4_if.master memory,
  output logic irq, idle, quarantined, drained,
  output wire clear_guard_error,
  output wire memory_w_capture
);
  wire [255:0] observer_live;wire [2047:0] dma_snapshot;
  wire p_window_en,p_window_valid;
  wire [8:0] p_window_address;
  wire [31:0] p_window_q,p_window_epoch,p_window_words,p_window_len,p_window_padded;
  wire [63:0] p_window_session,p_window_sequence;
  logic engine_idle,arithmetic_idle,scratch_idle,timeout_fault,call_fault;
  logic isolate_request,reset_request,reset_grant,stop_new,faulted;
  wire reset_pending;
  assign clear_guard_error=reset_grant;
  logic [31:0] epoch,generation,first_fault_address;
  logic [63:0] run_limit,run_limit_next;
  logic submit,completion_valid,completion_ready,commit_idle;
  wire engine_completion_valid,engine_completion_ready;
  wire head_drained;
  logic [1023:0] descriptor;
  logic [1279:0] completion;
  logic [511:0] perf;
  logic [31:0] startup_status;
  logic dma_valid,dma_ready,dma_write,dma_result_valid,dma_result_ready,dma_idle,pending_offer;
  logic [31:0] dma_address,dma_result_address;
  logic [2:0] dma_size;
  logic [4:0] dma_len;
  logic [15:0] dma_scratch,dma_mask;
  logic [127:0] dma_data;
  logic [1:0] dma_resp;
  logic a_en,b_en;
  logic [11:0] a_addr,b_addr;
  logic [15:0] a_we,b_we;
  logic [127:0] a_data,b_data,a_q,b_q;
  wire [15:0] ram_min80_q,ram_nonzero_q;
  wire [15:0] dma_min80,dma_nonzero;
  wire [15:0] ram_scale_zero_q,ram_scale_lo0_q,ram_scale_lo1_q;
  wire [15:0] dma_scale_zero,dma_scale_lo0,dma_scale_lo1;
  logic [63:0] dma_read_bytes,dma_write_bytes;
  logic dma_w_capture;
  logic dma_sw_capture;
  logic dma_capture_bank;
  logic capture_revoke;
  logic [127:0] capture_owner;
  logic [63:0] capture_command_tag;
  logic [255:0] capture_command_scales;
  logic [1:0] capture_release;
  logic capture_peek_bank;
  logic [4:0] capture_peek_beat;
  logic [63:0] capture_peek_tag;
  logic [127:0] capture_data;
  logic [127:0] capture_raw_data;
  wire [9:0] capture_raw_beats;
  wire [255:0] capture_raw_banks;
  logic [15:0] capture_mask;
  logic [1:0] capture_held;
  logic [1:0] capture_certificate;
  logic [1:0] capture_bad;
  logic [1:0] capture_result_seen;
  logic [11:0] capture_counts;
  logic capture_physical_idle;
  wire transport_drained=guard_idle && native_safely_drained;
  wire control_stop=stop_new || external_isolate || isolate_request;
  wire [383:0] head_result;
  generate if(HEAD_ARGMAX)begin:head_selection
    nx_ce64_head_argmax select_head(.clk,.reset_n(platform_reset_n),.start(submit),
      .revoke(reset_grant||faulted||quarantined||external_window_isolate||isolate_request),
      .descriptor,.epoch,.generation,
      .aw_take(memory.awvalid&&memory.awready),.aw_address(memory.awaddr),
      .aw_size(memory.awsize),.aw_length(memory.awlen),
      .w_take(memory.wvalid&&memory.wready),.w_data(memory.wdata),.w_mask(memory.wstrb),.w_last(memory.wlast),
      .complete(completion_valid&&completion_ready),.completion,.head_drained,.result(head_result));
  end else begin:without_head_selection
    assign head_result=384'b0;
    assign head_drained=1'b1;
  end endgenerate
  // The observer accepts every W beat. Only completion publication waits for
  // its final candidate to retire, keeping the head result atomic with the
  // register-bank completion. Gate both sides of the same handshake.
  assign completion_valid=engine_completion_valid&&head_drained;
  assign engine_completion_ready=completion_ready&&head_drained;
  // The guard cannot be idle with a CE-owned native transaction/held response.
  // CPU-owned DDR traffic does not invalidate a completed CE lease.
  assign idle=engine_idle && dma_idle && arithmetic_idle && commit_idle && guard_idle && !quarantined;
  nx_ce64_regs #(.AQSA_RESIDENT(AQSA_RESIDENT),.LONG_PV(LONG_PV),.HEAD_ARGMAX(HEAD_ARGMAX)) regs(.clk,.platform_reset_n,.mmio,.engine_idle,.drained,.faulted,.quarantined,.submission_allowed(!external_isolate),.window_allowed(!external_window_isolate),.head_result,.dma_snapshot,
    .reset_grant,.startup_status,.first_fault_address,.outstanding({30'b0,pending_offer,!dma_idle}),.perf,
    .isolate_request,.reset_request,.epoch,.generation,.run_limit,.run_limit_next,
    .submit,.descriptor,.completion_valid,.completion_ready,.commit_idle,.completion,.irq,
    .p_window_en,.p_window_address,.p_window_q,.p_window_valid,.p_window_epoch,
    .p_window_words,.p_window_len,.p_window_padded,.p_window_session,.p_window_sequence);
  nx_ce64_fault fault(.clk,.platform_reset_n,.isolate_request(external_isolate||isolate_request),
    .reset_request,.run_timeout(timeout_fault),.guard_fault(guard_fault||call_fault),
    .dma_fault(dma_result_valid&&dma_resp!=0),.native_quarantined,
    .visible_fault_address,.dma_idle,.guard_idle,.native_safely_drained,.arithmetic_idle,
    .scratch_idle,.commit_idle(commit_idle&&!engine_completion_valid),.stop_new,.drained,.reset_grant,.quarantined,.faulted,
    .reset_pending_o(reset_pending),.first_fault_address);
  nx_opt11_dispatch #(.LONG_PV(LONG_PV),.AQSA_GROUP_HANDOFF(1'b0),.A_W_BANKED(A_W_BANKED),.W_PREFETCH(W_PREFETCH),.AQSA_RESIDENT(AQSA_RESIDENT),.CROSS_GROUP_WRITE(CROSS_GROUP_WRITE),.LANES(`OPT11_LANES),.SCRATCH_PREDICATES(1),.SCRATCH_SCALE_PREDICATES(1),.DEADLINE_CACHE(1)) control(.scratch_b_en(b_en),.scratch_b_address(b_addr),.scratch_b_mask(b_we),.resident_revoke(external_window_isolate||isolate_request||faulted||quarantined),.clk,.platform_reset_n,.startup_authorized,.startup_status,.submit,.reset_grant,.stop_new(control_stop),.abort_publish(reset_pending),
    .descriptor,.epoch,.generation,.first_fault_address,.run_limit,.run_limit_next,.transport_drained,.native_quarantined,
    .p_window_en,.p_window_address,.p_window_q,.p_window_valid,.p_window_epoch,
    .p_window_words,.p_window_len,.p_window_padded,.p_window_session,.p_window_sequence,
    .engine_idle,.arithmetic_idle,.scratch_idle,.timeout_fault,.call_fault,
    .completion,.completion_valid(engine_completion_valid),.completion_ready(engine_completion_ready),.perf,
    .dma_ready,.dma_result_valid,.dma_idle,.dma_resp,.dma_valid,.dma_write,.dma_result_ready,
    .dma_address,.dma_size,.dma_len,.dma_scratch,.dma_data,.dma_mask,
    .ram_en(a_en),.ram_address(a_addr),.ram_mask(a_we),.ram_data(a_data),.ram_q(a_q),.ram_min80_q,.ram_nonzero_q,.ram_scale_zero_q,.ram_scale_lo0_q,.ram_scale_lo1_q,.dma_w_capture(dma_w_capture),.dma_sw_capture(dma_sw_capture),.dma_capture_bank(dma_capture_bank),.capture_revoke(capture_revoke),.capture_owner(capture_owner),.capture_command_tag(capture_command_tag),.capture_command_scales(capture_command_scales),.capture_release(capture_release),.capture_peek_bank(capture_peek_bank),.capture_peek_beat(capture_peek_beat),.capture_peek_tag(capture_peek_tag),.capture_data(capture_data),.capture_raw_data(capture_raw_data),.capture_raw_beats(capture_raw_beats),.capture_raw_banks(capture_raw_banks),.capture_mask(capture_mask),.capture_held(capture_held),.capture_certificate(capture_certificate),.capture_bad(capture_bad),.capture_result_seen(capture_result_seen),.capture_counts(capture_counts),.capture_physical_idle(capture_physical_idle),.capture_r_take(memory.rvalid&&memory.rready),.capture_r_data(memory.rdata),.capture_r_id(memory.rid),.capture_r_resp(memory.rresp),.capture_r_last(memory.rlast));
  nx_ce64_dma #(.ENABLE_W_CAPTURE(1),.W_PREFETCH(W_PREFETCH)) dma(.clk,.reset_n(platform_reset_n),.stop_new(control_stop),
    .command_valid(dma_valid),.command_write(dma_write),.command_ready(dma_ready),
    .command_address(dma_address),.command_size(dma_size),.command_len(dma_len),
    .command_scratch(dma_scratch),.command_data(dma_data),.command_mask(dma_mask),
    .result_valid(dma_result_valid),.result_ready(dma_result_ready),.result_resp(dma_resp),
    .result_address(dma_result_address),.idle(dma_idle),.pending_offer,
    .scratch_en(b_en),.scratch_addr(b_addr),.scratch_data(b_data),.scratch_mask(b_we),.scratch_min80(dma_min80),.scratch_nonzero(dma_nonzero),.scratch_scale_zero(dma_scale_zero),.scratch_scale_lo0(dma_scale_lo0),.scratch_scale_lo1(dma_scale_lo1),.scratch_q(b_q),
    .read_bytes(dma_read_bytes),.write_bytes(dma_write_bytes),
    .command_capture(dma_w_capture),.command_sw_capture(dma_sw_capture),.command_bank(dma_capture_bank),
    .capture_revoke,.capture_transport_fault(guard_fault||native_quarantined),.capture_live_owner(capture_owner),
    .command_capture_tag(capture_command_tag),.command_capture_scales(capture_command_scales),
    .capture_native_drained(native_safely_drained),.capture_guard_idle(guard_idle),.capture_release,
    .capture_peek_bank,.capture_peek_beat,.capture_peek_tag,.capture_data,.capture_raw_data,.capture_raw_beats,.capture_raw_banks,.capture_mask,.capture_held,
    .capture_certificate,.capture_bad,.capture_result_seen,.capture_counts,.physical_idle(capture_physical_idle),
    .w_capture_pending(memory_w_capture),.observer_live,.bus(memory));
  nx_dma_flight_recorder dma_observer(.clk,.platform_reset_n,
    .fault_event({native_quarantined,guard_fault||call_fault,dma_result_valid&&dma_resp!=0,timeout_fault}),
    .epoch,.generation,.session(descriptor[10*32+:64]),.sequence_id(descriptor[12*32+:64]),
    .command_fire(dma_valid&&dma_ready),.command_write(dma_write),.result_fire(dma_result_valid&&dma_result_ready),
    .command_address(dma_address),.result_address(dma_result_address),.command_size(dma_size),.command_len(dma_len),.command_scratch(dma_scratch),.result_resp(dma_resp),
    .ar_fire(memory.arvalid&&memory.arready),.r_fire(memory.rvalid&&memory.rready),
    .aw_fire(memory.awvalid&&memory.awready),.w_fire(memory.wvalid&&memory.wready),.b_fire(memory.bvalid&&memory.bready),
    .dma_live(observer_live),
    .axi_flags({memory.rid,memory.bid,memory.rlast,memory.wlast,memory.rresp,memory.bresp,2'b0,dma_valid,dma_ready,
      memory.awvalid,memory.awready,memory.wvalid,memory.wready,memory.bvalid,memory.bready,memory.arvalid,memory.arready,memory.rvalid,memory.rready}),
    .ar_address(memory.araddr),.aw_address(memory.awaddr),
    .axi_shape({memory.awlen[4:0],memory.awsize,memory.awid,memory.arlen[4:0],memory.arsize,memory.arid,memory.rresp,memory.bresp}),.snapshot(dma_snapshot));
  nx_ce64_scratch #(.PREDICATE_METADATA(1),.B_PRECOMPUTED_PREDICATES(1),.SCALE_METADATA(1),.B_PRECOMPUTED_SCALE_PREDICATES(1)) scratch(.clk,.a_en,.b_en,.a_addr,.b_addr,.a_we,.b_we,.a_data,.b_data,.b_min80(dma_min80),.b_nonzero(dma_nonzero),.b_scale_zero(dma_scale_zero),.b_scale_lo0(dma_scale_lo0),.b_scale_lo1(dma_scale_lo1),.a_q,.b_q,
    .min80_q(ram_min80_q),.nonzero_q(ram_nonzero_q),.scale_zero_q(ram_scale_zero_q),.scale_lo0_q(ram_scale_lo0_q),.scale_lo1_q(ram_scale_lo1_q));
endmodule

// Passive final-output observer. It neither changes DMA scheduling nor reads
// logits back from DDR. Only a complete successful M1 full-vocabulary head
// publishes a token; numerical/error/coverage failure leaves VALID clear.
module nx_ce64_head_argmax #(parameter integer VOCAB=151936)(
 input logic clk,reset_n,start,revoke,
 input logic [1023:0] descriptor,
 input logic [31:0] epoch,generation,
 input logic aw_take,w_take,w_last,complete,
 input logic [31:0] aw_address,
 input logic [2:0] aw_size,
 input logic [7:0] aw_length,
 input logic [127:0] w_data,
 input logic [15:0] w_mask,
 input logic [1279:0] completion,
 output wire head_drained,
 output wire [383:0] result
);
 logic active,valid,bad,pending,have_best,have_received;
 logic [31:0] output_base,count,best_index,best_value,call_epoch,call_generation;
 logic [63:0] call_session,call_sequence;
 logic [31:0] write_address;
 logic [2:0] write_size;
 logic [7:0] write_left;
 logic [31:0] count_next;
 logic bad_next,have_next;
 typedef struct packed {
   logic present;
   logic [31:0] value,index;
 } candidate_t;
 candidate_t lane_q[0:3],pair_q[0:1],beat_q,global_next;
 logic lane_valid,pair_valid,beat_valid,finish_pending,finish_ok;
 logic [3:0] lane_selected;
 logic [2:0] lane_prefix[0:3],selected_words;
 logic [1:0] selected_low,selected_high;
 logic [32:0] lane_count[0:3],total_count;
 logic [31:0] lane_index[0:3];
 wire [31:0] beat_address=pending?write_address:aw_address;
 wire [2:0] beat_size=pending?write_size:aw_size;
 wire [7:0] beat_left=pending?write_left:aw_length;
 wire [32:0] output_end={1'b0,output_base}+33'(VOCAB*4);
 function automatic logic greater(input logic [31:0] a,b);
   if(a[30:0]==0&&b[30:0]==0)greater=0;
   else if(a[31]!=b[31])greater=!a[31];
   else greater=a[31]?a[30:0]<b[30:0]:a[30:0]>b[30:0];
 endfunction
 // Earlier candidates always win equal values, including both signs of zero.
 // The balanced per-beat tree is independent of the previous global winner.
 function automatic candidate_t earlier_best(input candidate_t earlier,later);
   earlier_best=earlier;
   if(!earlier.present)earlier_best=later;
   else if(later.present&&greater(later.value,earlier.value))earlier_best=later;
 endfunction
 wire pipeline_empty=!lane_valid&&!pair_valid&&!beat_valid;
 assign head_drained=pipeline_empty&&!finish_pending&&!(active&&w_take);
 always_comb begin
   lane_selected=0;
   for(integer lane=0;lane<4;lane++)begin
     // Keep the original 33-bit range arithmetic and procedural X handling.
     if(w_mask[lane*4+:4]!=0&&
        {1'b0,beat_address[31:4],4'b0}+33'(lane*4)>={1'b0,output_base}&&
        {1'b0,beat_address[31:4],4'b0}+33'(lane*4)<output_end)lane_selected[lane]=1;
   end
   selected_low={1'b0,lane_selected[0]}+{1'b0,lane_selected[1]};
   selected_high={1'b0,lane_selected[2]}+{1'b0,lane_selected[3]};
   selected_words={1'b0,selected_low}+{1'b0,selected_high};
   lane_prefix[0]=0;
   lane_prefix[1]={2'b0,lane_selected[0]};
   lane_prefix[2]={1'b0,selected_low};
   lane_prefix[3]={1'b0,selected_low}+{2'b0,lane_selected[2]};
   for(integer lane=0;lane<4;lane++)begin
     lane_count[lane]={1'b0,count}+{30'b0,lane_prefix[lane]};
     lane_index[lane]=lane_count[lane][32]?32'hffffffff:lane_count[lane][31:0];
   end
   total_count={1'b0,count}+{30'b0,selected_words};
   count_next=count;bad_next=bad;have_next=have_received;
   if(active&&w_take)begin
     if(!(pending||aw_take)||w_last!=(beat_left==0))bad_next=1;
     for(integer lane=0;lane<4;lane++)begin
       if(lane_selected[lane])begin
         if(w_mask[lane*4+:4]!=4'hf||beat_size<2||beat_size>4||beat_address[1:0]!=0||
            ({1'b0,beat_address[31:4],4'b0}+33'(lane*4)-{1'b0,output_base})!=33'(lane_index[lane]*4)||
            lane_index[lane]>=VOCAB)bad_next=1;
         if(w_data[lane*32+23+:8]==8'hff)bad_next=1;
       end
     end
     have_next=have_received||(|lane_selected);
     count_next=total_count[32]?32'hffffffff:total_count[31:0];
     if(total_count[32])bad_next=1;
   end
 end
 always_comb global_next=earlier_best({have_best,best_value,best_index},beat_q);
 // Dead candidate payloads deliberately have no asynchronous reset. Their
 // stage valid is reset/flushed before any consumer may observe them; every
 // valid entry writes the complete candidate before it advances one stage.
 always_ff @(posedge clk)begin
   if(active&&w_take)begin
     for(integer lane=0;lane<4;lane++)
       lane_q[lane]<={lane_selected[lane],w_data[lane*32+:32],lane_index[lane]};
   end
   if(lane_valid)begin
     pair_q[0]<=earlier_best(lane_q[0],lane_q[1]);
     pair_q[1]<=earlier_best(lane_q[2],lane_q[3]);
   end
   if(pair_valid)beat_q<=earlier_best(pair_q[0],pair_q[1]);
 end
 wire finish_checks=active&&!bad_next&&!(aw_take&&pending)&&have_next&&count_next==VOCAB&&
   ((!pending&&!aw_take)||(w_take&&(pending||aw_take)&&beat_left==0))&&
   completion[14*32+:32]==0&&completion[15*32+:32]==1&&
   completion[3*32+:32]==call_epoch&&completion[38*32+:32]==call_generation&&
   completion[39*32+:32]==call_generation&&
   completion[10*32+:64]==call_session&&completion[12*32+:64]==call_sequence;
 // 0 status,1 token,2 FP32 best,3 count,4 epoch,5 generation,
 // 6..7 session,8..9 sequence,10 output address,11 vocabulary size.
 assign result={32'(VOCAB),output_base,call_sequence,call_session,call_generation,call_epoch,
   count,best_value,best_index,30'b0,bad,valid};
 always_ff @(posedge clk or negedge reset_n)begin
   if(!reset_n)begin
     active<=0;valid<=0;bad<=0;pending<=0;have_best<=0;have_received<=0;count<=0;best_index<=0;best_value<=0;
     lane_valid<=0;pair_valid<=0;beat_valid<=0;finish_pending<=0;finish_ok<=0;
     output_base<=0;call_epoch<=0;call_generation<=0;call_session<=0;call_sequence<=0;
     write_address<=0;write_size<=0;write_left<=0;
   end else if(revoke)begin
     active<=0;valid<=0;bad<=0;pending<=0;have_best<=0;have_received<=0;count<=0;
     lane_valid<=0;pair_valid<=0;beat_valid<=0;finish_pending<=0;finish_ok<=0;
   end
   else if(start)begin
     active<=descriptor[14*32+:32]==2&&descriptor[15*32+:32]==1&&descriptor[16*32+:32]==VOCAB;
     valid<=0;bad<=0;have_best<=0;have_received<=0;pending<=0;count<=0;best_index<=0;best_value<=0;
     lane_valid<=0;pair_valid<=0;beat_valid<=0;finish_pending<=0;finish_ok<=0;
     output_base<=descriptor[19*32+:32];call_epoch<=epoch;call_generation<=generation;
     call_session<=descriptor[10*32+:64];call_sequence<=descriptor[12*32+:64];
   end else begin
     lane_valid<=active&&w_take&&(|lane_selected);
     pair_valid<=lane_valid;beat_valid<=pair_valid;
     if(beat_valid)begin
       best_index<=global_next.index;best_value<=global_next.value;have_best<=global_next.present;
     end
     if(aw_take)begin
       write_address<=aw_address;write_size<=aw_size;write_left<=aw_length;pending<=1;
       if(pending)bad<=1;
     end
     if(w_take&&(pending||aw_take))begin
       if(beat_left==0)pending<=0;
       else begin write_address<=beat_address+(32'd1<<beat_size);write_size<=beat_size;write_left<=beat_left-1'b1;pending<=1;end
     end
     if(active&&w_take)begin
       count<=count_next;have_received<=have_next;bad<=bad_next||(aw_take&&pending);
     end
     if(complete&&!finish_pending)begin
       active<=0;
       finish_ok<=finish_checks;
       if(pipeline_empty&&!(active&&w_take))begin valid<=finish_checks&&have_best;finish_pending<=0;end
       else begin valid<=0;finish_pending<=1;end
     end else if(finish_pending&&pipeline_empty)begin
       valid<=finish_ok&&have_best;finish_pending<=0;
     end
   end
 end
endmodule

// Passive first-fault observer. Never drives READY, VALID, reset or ownership.
// Read-only 64 words at CE+0x600. First fault survives all software CE resets.
// Diagnostic-only input pipeline: all event, identity and state samples delayed exactly one clock.
module nx_dma_flight_recorder(
 input wire clk,platform_reset_n,
 input wire [3:0] fault_event,
 input wire [31:0] epoch,generation,
 input wire [63:0] session,sequence_id,
 input wire command_fire,command_write,result_fire,
 input wire [31:0] command_address,result_address,
 input wire [2:0] command_size,input wire [4:0] command_len,
 input wire [15:0] command_scratch,input wire [1:0] result_resp,
 input wire ar_fire,r_fire,aw_fire,w_fire,b_fire,
 input wire [255:0] dma_live,
 input wire [31:0] axi_flags,ar_address,aw_address,axi_shape,
 output wire [2047:0] snapshot
);
 logic [3:0] fault_event_q;
 logic [31:0] epoch_q;
 logic [31:0] generation_q;
 logic [63:0] session_q;
 logic [63:0] sequence_id_q;
 logic command_fire_q;
 logic command_write_q;
 logic result_fire_q;
 logic [31:0] command_address_q;
 logic [31:0] result_address_q;
 logic [2:0] command_size_q;
 logic [4:0] command_len_q;
 logic [15:0] command_scratch_q;
 logic [1:0] result_resp_q;
 logic ar_fire_q;
 logic r_fire_q;
 logic aw_fire_q;
 logic w_fire_q;
 logic b_fire_q;
 logic [255:0] dma_live_q;
 logic [31:0] axi_flags_q;
 logic [31:0] ar_address_q;
 logic [31:0] aw_address_q;
 logic [31:0] axi_shape_q;
 always @(posedge clk or negedge platform_reset_n)begin
  if(!platform_reset_n)begin
   fault_event_q<=0;
   epoch_q<=0;
   generation_q<=0;
   session_q<=0;
   sequence_id_q<=0;
   command_fire_q<=0;
   command_write_q<=0;
   result_fire_q<=0;
   command_address_q<=0;
   result_address_q<=0;
   command_size_q<=0;
   command_len_q<=0;
   command_scratch_q<=0;
   result_resp_q<=0;
   ar_fire_q<=0;
   r_fire_q<=0;
   aw_fire_q<=0;
   w_fire_q<=0;
   b_fire_q<=0;
   dma_live_q<=0;
   axi_flags_q<=0;
   ar_address_q<=0;
   aw_address_q<=0;
   axi_shape_q<=0;
  end else begin
   fault_event_q<=fault_event;
   epoch_q<=epoch;
   generation_q<=generation;
   session_q<=session;
   sequence_id_q<=sequence_id;
   command_fire_q<=command_fire;
   command_write_q<=command_write;
   result_fire_q<=result_fire;
   command_address_q<=command_address;
   result_address_q<=result_address;
   command_size_q<=command_size;
   command_len_q<=command_len;
   command_scratch_q<=command_scratch;
   result_resp_q<=result_resp;
   ar_fire_q<=ar_fire;
   r_fire_q<=r_fire;
   aw_fire_q<=aw_fire;
   w_fire_q<=w_fire;
   b_fire_q<=b_fire;
   dma_live_q<=dma_live;
   axi_flags_q<=axi_flags;
   ar_address_q<=ar_address;
   aw_address_q<=aw_address;
   axi_shape_q<=axi_shape;
  end
 end
 nx_dma_flight_recorder_core core(.clk(clk),.platform_reset_n(platform_reset_n),.fault_event(fault_event_q),.epoch(epoch_q),.generation(generation_q),.session(session_q),.sequence_id(sequence_id_q),.command_fire(command_fire_q),.command_write(command_write_q),.result_fire(result_fire_q),.command_address(command_address_q),.result_address(result_address_q),.command_size(command_size_q),.command_len(command_len_q),.command_scratch(command_scratch_q),.result_resp(result_resp_q),.ar_fire(ar_fire_q),.r_fire(r_fire_q),.aw_fire(aw_fire_q),.w_fire(w_fire_q),.b_fire(b_fire_q),.dma_live(dma_live_q),.axi_flags(axi_flags_q),.ar_address(ar_address_q),.aw_address(aw_address_q),.axi_shape(axi_shape_q),.snapshot(snapshot));
endmodule

module nx_dma_flight_recorder_core(
 input wire clk,platform_reset_n,
 input wire [3:0] fault_event,
 input wire [31:0] epoch,generation,
 input wire [63:0] session,sequence_id,
 input wire command_fire,command_write,result_fire,
 input wire [31:0] command_address,result_address,
 input wire [2:0] command_size,input wire [4:0] command_len,
 input wire [15:0] command_scratch,input wire [1:0] result_resp,
 input wire ar_fire,r_fire,aw_fire,w_fire,b_fire,
 input wire [255:0] dma_live,
 input wire [31:0] axi_flags,ar_address,aw_address,axi_shape,
 output wire [2047:0] snapshot
);
 logic frozen;logic [63:0] tick,last_progress;
 logic [31:0] words[0:63];
 wire any_progress=command_fire||result_fire||ar_fire||r_fire||aw_fire||w_fire||b_fire;
 wire [1:0] slot=words[11][1:0];
 wire [1:0] finished_slot=words[11][1:0]-2'd1;
 for(genvar i=0;i<64;i++)assign snapshot[i*32+:32]=words[i];
 always @(posedge clk or negedge platform_reset_n)begin
  if(!platform_reset_n)begin
   frozen<=0;tick<=0;last_progress<=0;
   for(integer i=0;i<64;i++)words[i]<=0;
   words[0]<=32'h444d5231;words[1]<=1;
  end else begin
   tick<=tick+1;
   if(any_progress)last_progress<=tick;
   if(!frozen)begin
    words[2]<={27'b0,(|fault_event),fault_event};
    words[3]<=tick[31:0];words[4]<=tick[63:32];words[5]<=epoch;words[6]<=generation;
    words[7]<=session[31:0];words[8]<=session[63:32];words[9]<=sequence_id[31:0];words[10]<=sequence_id[63:32];
    words[11]<=words[11]+32'(command_fire);words[12]<=words[12]+32'(result_fire);
    words[13]<=words[13]+32'(ar_fire);words[14]<=words[14]+32'(r_fire);
    words[15]<=words[15]+32'(aw_fire);words[16]<=words[16]+32'(w_fire);words[17]<=words[17]+32'(b_fire);
    words[18]<=any_progress?tick[31:0]:last_progress[31:0];words[19]<=any_progress?tick[63:32]:last_progress[63:32];
    for(integer i=0;i<8;i++)words[20+i]<=dma_live[32*i+:32];
    words[28]<=axi_flags;words[29]<=ar_address;words[30]<=aw_address;words[31]<=axi_shape;
    if(command_fire)begin
     words[32+8*slot]<=command_address;
     words[33+8*slot]<={23'b0,command_write,command_size,command_len};
     words[34+8*slot]<={16'b0,command_scratch};words[35+8*slot]<=tick[31:0];words[36+8*slot]<=tick[63:32];
     words[37+8*slot]<=0;words[38+8*slot]<=0;words[39+8*slot]<=0;
    end
    if(result_fire)begin
     words[37+8*finished_slot]<=result_address;words[38+8*finished_slot]<={29'b0,1'b1,result_resp};
     words[39+8*finished_slot]<=tick[31:0]-words[35+8*finished_slot];
    end
    if(|fault_event)frozen<=1;
   end
  end
 end
endmodule
