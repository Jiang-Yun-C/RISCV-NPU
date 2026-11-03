// API-v2 transport registers. A shadow is not a second accepted job. CAPS=0
// until an independently registered board profile is qualified.
module nx_ce64_regs #(parameter bit AQSA_RESIDENT=1,LONG_PV=0,HEAD_ARGMAX=0) (
  input logic clk, platform_reset_n,
  axi4_if.slave mmio,
  input logic engine_idle, drained, faulted, quarantined, submission_allowed, window_allowed,
  input logic reset_grant,
  input logic [31:0] first_fault_address,startup_status,
  input logic [31:0] outstanding,
  input logic [511:0] perf,
  input wire [383:0] head_result,
  input wire [2047:0] dma_snapshot,
  output logic isolate_request, reset_request,
  output logic [31:0] epoch, generation,
  output logic [63:0] run_limit,run_limit_next,
  output logic submit,
  output logic [1023:0] descriptor,
  input logic completion_valid,
  output logic completion_ready, commit_idle,
  input logic [1279:0] completion,
  output logic irq,
  // Private CPU/PV handoff: one synchronous 32-bit read port. The data
  // array has no reset; publication/coverage metadata controls all use.
  input wire p_window_en,
  input wire [8:0] p_window_address,
  output logic [31:0] p_window_q,
  output wire p_window_valid,
  output wire [31:0] p_window_epoch,p_window_words,p_window_len,p_window_padded,
  output wire [63:0] p_window_session,p_window_sequence
);
  logic run_enable;
  logic [63:0] drain_limit;
  logic [31:0] shadow [0:31];
  logic [31:0] banks [0:79];
  logic [31:0] bitmap,last_generation,irq_mask,irq_status,irq_generation;
  logic bank,publishing,target_bank,pending,epoch_exhausted;
  logic [5:0] publish_index;
  logic [1279:0] publish_data;
  logic [511:0] perf_snapshot;
  logic aw_have,w_have;
  logic [11:0] wa;
  logic [31:0] wd;
  logic [127:0] raw_wdata;
  logic [15:0] raw_wstrb;
  logic raw_wlast;
  logic write_legal;
  logic [31:0] status_word;
  // Sample the selected word at AR acceptance, then place it in its AXI lane
  // on the following clock. The snapshot edge is unchanged; only response
  // latency grows by one clock, with one outstanding read and normal R hold.
  logic read_pending;
  // Capture each constant high-nibble group independently at the same AR edge.
  // Only groups0/1/2/4/5 are live; all other groups are constant zero.
  logic [31:0] read_bank_word_q [0:15];
  logic [3:0] read_bank_q;
  logic [31:0] read_word_selected,read_id_q;
  logic [1:0] read_lane_q,read_resp_q;
  // Read-only presentation of the previous core cycle. Keep raw drained at
  // the fault/reset coordinator; this register never authorizes an operation.
  // Only STATUS[3] and RESET_STATUS[0] use this bounded-latency snapshot.
  logic read_drained_q;
  always_ff @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)read_drained_q<=0;
    else read_drained_q<=drained;
  end
  // CPU-owned DDR traffic may be active when the doorbell arrives. The prior
  // CE call already proved drain before publication and ACK; current engine
  // idle plus no pending publication retains that proof. Global adapter idle
  // is still required by the reset coordinator, never by a new CE submission.
  wire can_submit=engine_idle && !publishing && !pending && !faulted &&
                  !quarantined && !epoch_exhausted && run_enable && !isolate_request && submission_allowed;
  wire do_write=aw_have && w_have && !mmio.bvalid;
  assign wd=raw_wdata[wa[3:2]*32+:32];
  assign status_word={24'b0,bank,can_submit,faulted,pending,read_drained_q,
                      isolate_request,!engine_idle,engine_idle};
  assign completion_ready=!publishing && !pending;
  assign commit_idle=!publishing;
  assign irq=|(irq_status&irq_mask);
  assign mmio.awready=!aw_have&&!mmio.bvalid;
  assign mmio.wready=!w_have&&!mmio.bvalid;
  assign mmio.arready=!mmio.rvalid&&!read_pending;
  // CPU staging is legal before DDR ownership transfers. window_allowed
  // excludes actual bridge isolation/unsealed models; submission_allowed
  // additionally requires owner and remains the gate for the doorbell.
  // A ready batch is immutable from submit acceptance through completion ACK.
  // Full epoch/session/sequence/geometry binding is checked again by PV CHECK.
  logic [31:0] p_memory[0:511];
  logic p_filling,p_ready,p_locked;
  logic [9:0] p_words,p_count;
  logic [31:0] p_epoch,p_len,p_padded;
  logic [63:0] p_session,p_sequence;
  wire p_access_idle=engine_idle&&!publishing&&!pending&&!p_locked&&
    !faulted&&!quarantined&&!isolate_request&&window_allowed&&run_enable;
  wire p_geometry_ok=p_words!=0&&p_words<=448&&p_words[5:0]==0&&
    p_len>=1&&p_len<=64&&p_padded>=p_len&&p_padded<=64&&
    (p_padded&(p_padded-1))==0&&p_session!=0&&p_sequence!=0;
  wire p_data_write_ok=p_access_idle&&p_filling&&p_words!=0&&p_words<=448&&
    p_count<p_words&&wa==12'h800+12'(p_count<<2);
  wire p_publish_ok=p_access_idle&&p_filling&&p_geometry_ok&&p_count==p_words;
  wire p_revoke=reset_grant||faulted||quarantined||!window_allowed||
    (control_write&&wd[1]);
  assign p_window_valid=p_ready&&p_locked&&!p_revoke;
  assign p_window_epoch=p_epoch;
  assign p_window_session=p_session;
  assign p_window_sequence=p_sequence;
  assign p_window_words={22'b0,p_words};
  assign p_window_len=p_len;
  assign p_window_padded=p_padded;
  // Native synchronous one-read/one-write RAM inference pattern. Accesses
  // never collide: CPU writes require unlocked; PV reads require locked.
  always_ff @(posedge clk)begin
    if(software_write&&wa>=12'h800&&p_data_write_ok)
      p_memory[p_count[8:0]]<=wd;
    if(p_window_en&&p_window_valid)p_window_q<=p_memory[p_window_address];
  end
  always_ff @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)begin
      p_filling<=0;p_ready<=0;p_locked<=0;p_words<=0;p_count<=0;
      p_epoch<=0;p_session<=0;p_sequence<=0;p_len<=0;p_padded<=0;
    end else if(p_revoke)begin
      p_filling<=0;p_ready<=0;p_locked<=0;p_words<=0;p_count<=0;
    end else if(accept_ack)begin
      p_filling<=0;p_ready<=0;p_locked<=0;p_count<=0;
    end else if(accept_submit)begin
      p_filling<=0;
      if(shadow[14]==5&&shadow[27]==1)p_locked<=1;
      else begin p_ready<=0;p_locked<=0;end
    end else if(software_write)begin
      if(wa==12'h100&&p_access_idle&&(wd==0||wd==1))begin
        p_filling<=wd[0];p_ready<=0;p_locked<=0;p_words<=0;p_count<=0;
        p_epoch<=epoch;p_session<=0;p_sequence<=0;p_len<=0;p_padded<=0;
      end else if(p_access_idle&&p_filling&&p_count==0)begin
        case(wa)
          12'h104:p_words<=wd<=448?10'(wd):10'd0;
          12'h108:p_session[31:0]<=wd;
          12'h10c:p_session[63:32]<=wd;
          12'h110:p_sequence[31:0]<=wd;
          12'h114:p_sequence[63:32]<=wd;
          12'h120:p_len<=wd;
          12'h128:p_padded<=wd;
          default:;
        endcase
      end
      if(wa>=12'h800&&p_data_write_ok)p_count<=p_count+1'b1;
      if(wa==12'h118&&p_publish_ok&&wd==1)begin p_ready<=1;p_filling<=0;end
    end
  end
  function automatic logic [31:0] read_word(input logic [11:0] a);
    if(a>=12'h600 && a<12'h700)return dma_snapshot[(a-12'h600)*8+:32];
    if(a>=12'h140 && a<12'h170)return HEAD_ARGMAX?head_result[(a-12'h140)*8+:32]:32'b0;
    if(a>=12'h200 && a<12'h280)return shadow[(a-12'h200)>>2];
    if(a>=12'h400 && a<12'h4a0)return banks[(a-12'h400)>>2];
    if(a>=12'h500 && a<12'h5a0)return banks[40+((a-12'h500)>>2)];
    if(a>=12'h080 && a<12'h0c0)return perf_snapshot[(a-12'h080)*8+:32];
    case(a)
      12'h000:return 32'h34364543;
      12'h004:return 2;
      12'h008:return 0;
      12'h00c:return status_word;
      12'h010:return {30'b0,isolate_request,run_enable};
      12'h014:return irq_status;
      12'h018:return irq_mask;
      12'h01c:return epoch;
      12'h024:return generation;
      12'h02c:return first_fault_address;
      12'h030:return run_limit[31:0];
      12'h034:return run_limit[63:32];
      12'h038:return drain_limit[31:0];
      12'h03c:return drain_limit[63:32];
      12'h040:return {29'b0,epoch_exhausted,quarantined,read_drained_q};
      12'h044:return 0;
      12'h048:return irq_generation;
      12'h04c:return quarantined ? 32'd1 : 0;
      12'h050:return bitmap;
      12'h054:return outstanding;
      12'h058:return startup_status;
      12'h104:return {22'b0,p_words};
      12'h108:return p_session[31:0];
      12'h10c:return p_session[63:32];
      12'h110:return p_sequence[31:0];
      12'h114:return p_sequence[63:32];
      12'h11c:return {6'b0,p_count,14'b0,p_locked,(p_ready&&!p_locked)};
      12'h120:return p_len;
      12'h124:return 32'h50574231;
      12'h128:return p_padded;
      12'h12c:return AQSA_RESIDENT ? 32'h41515331 : 32'b0;
      12'h130:return LONG_PV ? 32'h50563531 : 32'b0;
      12'h134:return HEAD_ARGMAX ? 32'h414d5831 : 32'b0;
      default:return 0;
    endcase
  endfunction
  wire capture_aw=mmio.awvalid&&mmio.awready;
  wire capture_w=mmio.wvalid&&mmio.wready;
  wire capture_ar=mmio.arvalid&&mmio.arready;
  wire access_ok=write_legal && raw_wlast && raw_wstrb==(16'hf<<(4*wa[3:2]));
  wire software_write=do_write && access_ok;
  wire shadow_write=software_write && wa>=12'h200 && wa<12'h280;
  function automatic logic control_data_accepted();
    if(wd[31:3]!=0)control_data_accepted=0;else control_data_accepted=1;
  endfunction
  wire control_write=software_write && wa==12'h010 && control_data_accepted();
  wire accept_submit=software_write && wa==12'h020 && can_submit && bitmap==32'hffffffff && wd!=0 && wd>last_generation;
  wire accept_ack=software_write && wa==12'h028 && pending && wd==generation;
  wire accept_completion=completion_valid&&completion_ready;
  wire publish_last=publishing && publish_index==39;
  wire limits_idle=engine_idle && !publishing && !pending;
  function automatic logic [1:0] write_response();
    write_response=access_ok ? 2'd0 : 2'd3;
    if(access_ok) begin
      if(wa>=12'h200 && wa<12'h280) write_response=0;
      else case(wa)
        12'h010:if(wd[31:3]!=0)write_response=3;
        12'h014,12'h018,12'h060,12'h070:write_response=0;
        12'h020:if(can_submit && bitmap==32'hffffffff && wd!=0 && wd>last_generation)write_response=0;else write_response=2;
        12'h028:if(pending && wd==generation)write_response=0;else write_response=2;
        12'h030,12'h034,12'h038,12'h03c:if(limits_idle)write_response=0;else write_response=2;
        12'h044:if(wd!=0)write_response=3;
        12'h100:if(p_access_idle&&(wd==0||wd==1))write_response=0;else write_response=2;
        12'h104,12'h108,12'h10c,12'h110,12'h114,12'h120,12'h128:
          if(p_access_idle&&p_filling&&p_count==0)write_response=0;else write_response=2;
        12'h118:if(p_publish_ok&&wd==1)write_response=0;else write_response=2;
        default:if(wa>=12'h800&&p_data_write_ok)write_response=0;else write_response=3;
      endcase
    end
  endfunction
  logic [31:0] epoch_next;
  always_comb begin
    epoch_next=epoch;
    if(reset_grant)begin if(epoch==32'hffffffff)begin end else epoch_next=epoch+1'b1;end
  end
  always_ff @(posedge clk or negedge platform_reset_n) begin
    if(!platform_reset_n) begin aw_have<=0; end
    else begin if(do_write)aw_have<=0;else if(capture_aw)aw_have<=1; end
  end
  always_ff @(posedge clk or negedge platform_reset_n) begin
    if(!platform_reset_n) begin w_have<=0; end
    else begin if(do_write)w_have<=0;else if(capture_w)w_have<=1; end
  end
  always_ff @(posedge clk or negedge platform_reset_n) begin
    if(!platform_reset_n) begin wa<=0;write_legal<=0; end
    else begin if(capture_aw)begin wa<=mmio.awaddr[11:0];write_legal<=mmio.awsize==2 && mmio.awlen==0 && mmio.awburst==1 && mmio.awaddr[1:0]==0;end end
  end
  always_ff @(posedge clk or negedge platform_reset_n) begin
    if(!platform_reset_n) begin raw_wdata<=0;raw_wstrb<=0;raw_wlast<=0; end
    else begin if(capture_w)begin raw_wdata<=mmio.wdata;raw_wstrb<=mmio.wstrb;raw_wlast<=mmio.wlast;end end
  end
  always_ff @(posedge clk or negedge platform_reset_n) begin
    if(!platform_reset_n) begin mmio.bvalid<=0; end
    else begin if(do_write)mmio.bvalid<=1;else if(mmio.bvalid&&mmio.bready)mmio.bvalid<=0; end
  end
  always_ff @(posedge clk or negedge platform_reset_n) begin
    if(!platform_reset_n) begin mmio.bresp<=0;mmio.bid<=0; end
    else begin if(do_write)begin mmio.bresp<=write_response();mmio.bid<=0;end end
  end
  always_ff @(posedge clk or negedge platform_reset_n) begin
    if(!platform_reset_n) begin read_pending<=0;mmio.rvalid<=0; end
    else begin
      read_pending<=capture_ar;
      if(read_pending)mmio.rvalid<=1;
      else if(mmio.rvalid&&mmio.rready)mmio.rvalid<=0;
    end
  end
  always_ff @(posedge clk) begin
    if(capture_ar)begin
      read_bank_q<=mmio.araddr[11:8];read_lane_q<=mmio.araddr[3:2];
      read_id_q<=32'(mmio.arid);
      read_resp_q<=mmio.arlen==0 && mmio.arsize==2 && mmio.araddr[1:0]==0 ? 0 : 3;
    end
  end
  for(genvar read_group=0;read_group<16;read_group++)begin:read_group_capture
    always_ff @(posedge clk)begin
      if(capture_ar)read_bank_word_q[read_group]<=read_word({4'(read_group),mmio.araddr[7:0]});
    end
  end
  always_comb begin
    // Plain case retains zero for any X/Z in the captured group selector.
    read_word_selected=0;
    case(read_bank_q)
      4'd0:read_word_selected=read_bank_word_q[0];
      4'd1:read_word_selected=read_bank_word_q[1];
      4'd2:read_word_selected=read_bank_word_q[2];
      4'd3:read_word_selected=read_bank_word_q[3];
      4'd4:read_word_selected=read_bank_word_q[4];
      4'd5:read_word_selected=read_bank_word_q[5];
      4'd6:read_word_selected=read_bank_word_q[6];
      4'd7:read_word_selected=read_bank_word_q[7];
      4'd8:read_word_selected=read_bank_word_q[8];
      4'd9:read_word_selected=read_bank_word_q[9];
      4'd10:read_word_selected=read_bank_word_q[10];
      4'd11:read_word_selected=read_bank_word_q[11];
      4'd12:read_word_selected=read_bank_word_q[12];
      4'd13:read_word_selected=read_bank_word_q[13];
      4'd14:read_word_selected=read_bank_word_q[14];
      4'd15:read_word_selected=read_bank_word_q[15];
      default:;
    endcase
  end
  always_ff @(posedge clk or negedge platform_reset_n) begin
    if(!platform_reset_n) begin mmio.rresp<=0;mmio.rid<=0;mmio.rlast<=1;mmio.rdata<=0; end
    else begin if(read_pending)begin mmio.rid<=read_id_q;mmio.rlast<=1;mmio.rresp<=read_resp_q;mmio.rdata<=128'(read_word_selected)<<(32*read_lane_q);end end
  end
  always_ff @(posedge clk or negedge platform_reset_n) begin
    if(!platform_reset_n) begin reset_request<=0; end
    else begin if(control_write)reset_request<=wd[2];else reset_request<=0; end
  end
  always_ff @(posedge clk or negedge platform_reset_n) begin
    if(!platform_reset_n) begin isolate_request<=1;run_enable<=0; end
    else begin if(reset_grant)begin isolate_request<=1;run_enable<=0;end else if(control_write)begin run_enable<=wd[0];isolate_request<=wd[1];end end
  end
  always_ff @(posedge clk or negedge platform_reset_n) begin
    if(!platform_reset_n) begin submit<=0; end
    else begin if(reset_grant)submit<=0;else if(accept_submit)submit<=1;else submit<=0; end
  end
  always_ff @(posedge clk or negedge platform_reset_n) begin
    if(!platform_reset_n) begin bitmap<=0; end
    else begin if(reset_grant)bitmap<=0;else if(accept_submit || (software_write && wa==12'h060))bitmap<=0;else if(shadow_write)bitmap[(wa-12'h200)>>2]<=1; end
  end
  always_ff @(posedge clk or negedge platform_reset_n) begin
    if(!platform_reset_n) begin generation<=0;last_generation<=0;descriptor<=0; end
    else begin if(accept_submit)begin generation<=wd;last_generation<=wd;for(integer i=0;i<32;i=i+1)descriptor[i*32+:32]<=shadow[i];end end
  end
  always_ff @(posedge clk or negedge platform_reset_n) begin
    if(!platform_reset_n) begin irq_mask<=0; end
    else begin if(software_write && wa==12'h018)irq_mask<=wd&1; end
  end
  always_ff @(posedge clk or negedge platform_reset_n) begin
    if(!platform_reset_n) begin irq_status<=0; end
    else begin if(reset_grant)irq_status<=0;else if(publish_last)irq_status<=irq_status|1;else if(software_write && wa==12'h014)irq_status<=irq_status&~wd; end
  end
  always_ff @(posedge clk or negedge platform_reset_n) begin
    if(!platform_reset_n) begin irq_generation<=0;bank<=0; end
    else begin if(publish_last)begin irq_generation<=generation;bank<=target_bank;end end
  end
  always_ff @(posedge clk or negedge platform_reset_n) begin
    if(!platform_reset_n) begin publishing<=0; end
    else begin if(reset_grant)publishing<=0;else if(publish_last)publishing<=0;else if(accept_completion)publishing<=1; end
  end
  always_ff @(posedge clk or negedge platform_reset_n) begin
    if(!platform_reset_n) begin pending<=0; end
    else begin if(reset_grant)pending<=0;else if(publish_last)pending<=1;else if(accept_ack)pending<=0; end
  end
  always_ff @(posedge clk or negedge platform_reset_n) begin
    if(!platform_reset_n) begin publish_index<=0; end
    else begin if(publishing)begin if(publish_index==39)begin end else publish_index<=publish_index+1'b1;end else if(accept_completion)publish_index<=0; end
  end
  always_ff @(posedge clk or negedge platform_reset_n) begin
    if(!platform_reset_n) begin publish_data<=0; end
    // The staging payload is unobservable until accept_completion starts
    // publishing. Prepare it whenever ready, retaining the exact data on
    // the acceptance edge and holding it throughout publish and pending.
    else begin if(completion_ready)publish_data<=completion;end
  end
  always_ff @(posedge clk or negedge platform_reset_n) begin
    if(!platform_reset_n)begin target_bank<=1;end
    else if(accept_completion)target_bank<=!bank;
  end
  always_ff @(posedge clk or negedge platform_reset_n) begin
    if(!platform_reset_n)begin epoch<=1;end
    else begin epoch<=epoch_next;end
  end
  always_ff @(posedge clk or negedge platform_reset_n) begin
    if(!platform_reset_n)begin epoch_exhausted<=0;end
    else begin if(reset_grant)begin if(epoch==32'hffffffff)epoch_exhausted<=1;end end
  end
  // Exact next value of the original two MMIO words. Consumers sample
  // deadline metadata on the same edge as this register, including partial
  // writes, refused active writes and reset. Procedural-if X behavior matches
  // the original FF update; no new software-visible state or permission.
  always_comb begin
    run_limit_next=run_limit;
    if(!platform_reset_n)run_limit_next=0;
    else if(software_write && limits_idle)case(wa)
      12'h030:run_limit_next[31:0]=wd;
      12'h034:run_limit_next[63:32]=wd;
      default:begin end
    endcase
  end
  always_ff @(posedge clk or negedge platform_reset_n) begin
    if(!platform_reset_n) begin run_limit<=0;drain_limit<=0; end
    else begin if(software_write && limits_idle)case(wa)12'h030:run_limit[31:0]<=wd;12'h034:run_limit[63:32]<=wd;12'h038:drain_limit[31:0]<=wd;12'h03c:drain_limit[63:32]<=wd;default:begin end endcase end
  end
  always_ff @(posedge clk or negedge platform_reset_n) begin
    if(!platform_reset_n) begin perf_snapshot<=0; end
    else begin if(software_write && wa==12'h070)perf_snapshot<=perf; end
  end
  always_ff @(posedge clk or negedge platform_reset_n) begin
    if(!platform_reset_n) begin for(integer i=0;i<32;i=i+1)shadow[i]<=0; end
    else begin if(shadow_write)shadow[(wa-12'h200)>>2]<=wd; end
  end
  for(genvar word_index=0;word_index<80;word_index=word_index+1) begin: completion_word
    always_ff @(posedge clk or negedge platform_reset_n) begin
      if(!platform_reset_n)banks[word_index]<=0;
      else if(reset_grant && (word_index==39 || word_index==79))banks[word_index]<=0;
      else if(publishing && ((target_bank ? 40 : 0)+publish_index)==word_index)
        banks[word_index]<=publish_data[publish_index*32+:32];
      else if(accept_completion && ((!bank ? 40 : 0)+39)==word_index)banks[word_index]<=0;
    end
  end
endmodule
