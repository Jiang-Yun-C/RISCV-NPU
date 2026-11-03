#!/usr/bin/env python3
"""One isolated exact54 W/Sw integration; no root or frozen source mutation."""
import difflib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
from evidence import sha256,write_json,content_id
V=ROOT/'variants/opt10_r1_w_sw_integrated_v1'
P=ROOT/'evidence/OPT16_CANDIDATE/opt10-r1-candidate-20261020-v54'
FIELDS=[
 ('output','logic','dma_w_capture'),('output','logic','dma_sw_capture'),('output','logic','dma_capture_bank'),
 ('output','logic','capture_revoke'),('output','logic [127:0]','capture_owner'),
 ('output','logic [63:0]','capture_command_tag'),('output','logic [127:0]','capture_command_scales'),
 ('output','logic [1:0]','capture_release'),('output','logic','capture_peek_bank'),
 ('output','logic [3:0]','capture_peek_beat'),('output','logic [63:0]','capture_peek_tag'),
 ('input','logic [127:0]','capture_data'),('input','logic [15:0]','capture_mask'),
 ('input','logic [1:0]','capture_held'),('input','logic [1:0]','capture_certificate'),
 ('input','logic [1:0]','capture_bad'),('input','logic [1:0]','capture_result_seen'),
 ('input','logic [9:0]','capture_counts'),('input','logic','capture_physical_idle'),
 ('input','logic','capture_r_take'),('input','logic [127:0]','capture_r_data'),
 ('input','logic [5:0]','capture_r_id'),('input','logic [1:0]','capture_r_resp'),('input','logic','capture_r_last')]
PORTS=''.join('  '+d+' '+t+' '+n+',\n'for d,t,n in FIELDS)
CONNECT=','.join('.'+n+'('+n+')'for _,_,n in FIELDS)

DECL=r'''
  // This path is enabled only after the original descriptor validator succeeds.
  logic stream_active;
  logic [31:0] stream_epoch,stream_generation;
  wire stream_identity_bad=stream_active&&(epoch!==stream_epoch||generation!==stream_generation);
  wire stream_eligible=W_SW_STREAM&&inline_restore&&stream_group&&WEIGHT_ROW_BURST&&bulk_output&&d[17][5:0]==0&&d[18][5:0]==0;
  wire [127:0] stream_owner={d[13],d[12],d[11],d[10]};
  wire sw_start_ready,sw_fragment_ready,sw_active,sw_bad,sw_certificate,sw_fragment_pending;
  wire [8:0] sw_filled;
  wire [17:0] sw_first_row;
  wire [2:0] sw_rows;
  wire [6:0] sw_groups;
  wire [127:0] sw_owner;
  wire [31:0] sw_epoch,sw_generation;
  wire [2:0] stream_rows=d[16]-row>4?3'd4:3'(d[16]-row);
  wire [8:0] sw_total_words=9'(groups)*9'(stream_rows);
  wire sw_start=stream_active&&state==STREAM_SW_BEGIN&&row[1:0]==0&&sw_start_ready&&!abort_now;
  wire [31:0] sw_address=sw_base+32'(sw_filled)*4;
  wire [8:0] sw_left=sw_total_words-sw_filled;
  logic [2:0] sw_command_size;
  logic [5:0] sw_command_beats;
  logic [31:0] sw_command_words;
  always_comb begin
    if(sw_address[3:0]!=0)begin
      sw_command_size=2;
      sw_command_words=bounded_count(32'(sw_left),(16-(sw_address&15))>>2);
      sw_command_beats=6'(sw_command_words);
    end else if(sw_left>=4)begin
      sw_command_size=4;
      sw_command_beats=6'(bounded_count(bounded_count(32'(sw_left)>>2,32),(4096-(sw_address&4095))>>4));
      sw_command_words=32'(sw_command_beats)*4;
    end else begin
      sw_command_size=2;sw_command_words=32'(sw_left);sw_command_beats=6'(sw_left);
    end
  end
  wire sw_block_matches=sw_first_row=={row[17:2],2'b0}&&sw_groups==groups&&
      sw_owner===stream_owner&&sw_epoch==epoch&&sw_generation==generation;
  wire sw_issue=stream_active&&state==STREAM_SW_WAIT&&!sw_certificate&&!sw_bad&&
      sw_block_matches&&sw_left!=0&&sw_fragment_ready&&!abort_now;
  logic sw_command_pending,w_command_pending;
  logic [31:0] stream_chunk_bytes;
  logic w_running,w_next_bank;
  logic [6:0] w_offer_group;
  logic [6:0] w_first[2];
  logic [2:0] w_groups[2];
  logic [17:0] w_row[2];
  logic [63:0] w_tags[2];
  wire [31:0] w_address=w_base+32'(w_offer_group)*64;
  wire [2:0] w_count=3'(bounded_count(bounded_count(32'(groups)-32'(w_offer_group),4),
      (4096-(w_address&4095))>>6));
  wire w_window=state==STREAM_W_WAIT||state==DOT_A||state==DOT_WAIT||state==INLINE_FP_SEND;
  wire [127:0] sw_next_scales;
  wire sw_next_valid,sw_value_valid;
  wire [31:0] sw_current_value;
  wire w_issue=stream_active&&w_running&&w_window&&w_offer_group<groups&&w_count!=0&&
      !capture_held[w_next_bank]&&sw_next_valid&&!abort_now&&!w_command_pending&&!sw_command_pending;
  wire stream_command=sw_issue||w_issue;
  wire stream_accept=stream_command&&dma_ready;
  wire stream_result=(w_command_pending||sw_command_pending)&&dma_result_valid&&dma_result_ready;
  wire selected0=capture_held[0]&&capture_certificate[0]&&w_row[0]==row&&g>=w_first[0]&&g<w_first[0]+w_groups[0];
  wire selected1=capture_held[1]&&capture_certificate[1]&&w_row[1]==row&&g>=w_first[1]&&g<w_first[1]+w_groups[1];
  wire w_available=(selected0^selected1)&&sw_value_valid&&sw_block_matches;
  wire stream_first_a=stream_active&&state==STREAM_W_WAIT&&w_available&&!abort_now;
  wire stream_fault=stream_active&&!engine_idle&&state!=DRAIN&&state!=PUBLISH&&((sw_bad&&sw_block_matches)||(|capture_bad)||stream_identity_bad||
      (state==DOT_A&&!abort_now&&capture_mask!==16'hffff));
  assign capture_owner=stream_owner;
  assign capture_revoke=abort_now||abort_publish||reset_grant||stream_identity_bad;
  assign dma_w_capture=w_issue;
  assign dma_sw_capture=sw_issue;
  assign dma_capture_bank=w_next_bank;
  assign capture_command_tag={36'b0,row,w_offer_group,w_count};
  assign capture_command_scales=sw_next_scales;
  assign capture_peek_bank=selected0?1'b0:1'b1;
  assign capture_peek_beat=4'((g-w_first[capture_peek_bank])*4+beat);
  assign capture_peek_tag=w_tags[capture_peek_bank];
  always_comb begin
    capture_release=0;
    // A lease ends only after the final necessary W operand is accepted by DOT.
    if(stream_active&&state==DOT_A&&dot_request_valid&&dot_ready&&beat==3&&
        g+1==w_first[capture_peek_bank]+w_groups[capture_peek_bank])
      capture_release[capture_peek_bank]=1;
    // Revoked consumers release only completed DMA leases; accepted R still drains.
    if(state==DRAIN||abort_now)capture_release=capture_result_seen;
  end
  nx_ce64_sw_capture sw_cache(
    .clk,.reset_n(platform_reset_n),.start(sw_start),.start_ready(sw_start_ready),
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
    .value_row(row[1:0]),.value_group(g),.value_scale(sw_current_value),.value_valid(sw_value_valid),
    .active(sw_active),.bad(sw_bad),.certificate(sw_certificate),.fragment_pending(sw_fragment_pending),.filled_words(sw_filled),
    .block_first_row(sw_first_row),.block_rows(sw_rows),.block_groups(sw_groups),
    .block_owner(sw_owner),.block_epoch(sw_epoch),.block_generation(sw_generation));
  always_ff @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)begin
      stream_active<=0;stream_epoch<=0;stream_generation<=0;
      sw_command_pending<=0;w_command_pending<=0;stream_chunk_bytes<=0;
      w_running<=0;w_next_bank<=0;w_offer_group<=0;
      for(integer b=0;b<2;b++)begin w_first[b]<=0;w_groups[b]<=0;w_row[b]<=0;w_tags[b]<=0;end
    end else begin
      if(counter_clear||reset_grant)stream_active<=0;
      if(state==DESC_WAIT&&desc_done&&desc_status==0)begin
        stream_active<=stream_eligible;stream_epoch<=epoch;stream_generation<=generation;
      end
      if(state==ROW_BEGIN)begin w_running<=0;w_next_bank<=0;w_offer_group<=0;end
      if(stream_active&&state==STREAM_W_WAIT&&!w_running)w_running<=1;
      if(stream_accept)begin
        stream_chunk_bytes<=sw_issue?sw_command_words*4:32'(w_count)*64;
        if(sw_issue)sw_command_pending<=1;
        else begin
          w_command_pending<=1;w_first[w_next_bank]<=w_offer_group;
          w_groups[w_next_bank]<=w_count;w_row[w_next_bank]<=row;
          w_tags[w_next_bank]<=capture_command_tag;
          w_offer_group<=w_offer_group+7'(w_count);w_next_bank<=!w_next_bank;
        end
      end
      if(stream_result)begin sw_command_pending<=0;w_command_pending<=0;end
      if(state==DRAIN)w_running<=0;
    end
  end
'''

def main():
    pm=json.loads((P/'manifest.json').read_text());repo=Path(pm['candidate_repo']);inv=json.loads((P/'candidate-sources.json').read_text())
    assert all(sha256(repo/n)==h for n,h in inv.items())
    def save(n,old,new):
        f=V/n;assert not f.exists(),f;f.parent.mkdir(parents=True,exist_ok=True);f.write_text(new)
        p=V/(Path(n).name+'.patch');p.write_text(''.join(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='exact54/'+n,tofile='stream/'+n)))
    def replace(s,a,b):
        assert s.count(a)==1,(a[:100],s.count(a));return s.replace(a,b)
    n='rtl/ce64/nx_ce64_control.sv';old=(repo/n).read_text();s=old
    s=replace(s,'  input logic [127:0] ram_q',PORTS+'  input logic [127:0] ram_q')
    s=replace(s,'  parameter bit BOUNDARY_SCRATCH_PREFETCH=1\n','  parameter bit BOUNDARY_SCRATCH_PREFETCH=1,\n  parameter bit W_SW_STREAM=0\n')
    s=replace(s,'INLINE_FP_SEND,INLINE_FP_DRAIN\n','INLINE_FP_SEND,INLINE_FP_DRAIN,STREAM_SW_BEGIN,STREAM_SW_WAIT,STREAM_W_WAIT\n')
    s=replace(s,'  wire fp_bad_response=',DECL+'\n  wire fp_bad_response=')
    s=replace(s,'else if(fp_response_error)fp_abort_pending<=1;','else if(fp_response_error||stream_fault)fp_abort_pending<=1;')
    s=replace(s,'wire next_sw_read=boundary_prefetch&&','wire next_sw_read=!stream_active&&boundary_prefetch&&')
    s=replace(s,'wire next_sw_address_shape=boundary_prefetch&&','wire next_sw_address_shape=!stream_active&&boundary_prefetch&&')
    a=s.index('  assign dma_valid=');b=s.index('  assign ram_en=',a)
    s=s[:a]+'''  assign dma_valid=stream_command||(state==DMA_REQ&&!abort_now);
  assign dma_write=stream_command?1'b0:cmd_write;
  assign dma_address=stream_command?(sw_issue?sw_address:w_address):cmd_address;
  assign dma_size=stream_command?(sw_issue?sw_command_size:3'd4):cmd_size;
  assign dma_len=stream_command?(sw_issue?5'(sw_command_beats-1):5'(w_count*4-1)):cmd_len;
  assign dma_scratch=stream_command?16'b0:cmd_scratch;
  assign dma_data=cmd_data;assign dma_mask=cmd_mask;
  assign dma_result_ready=w_command_pending||sw_command_pending||state==DMA_WAIT||state==DRAIN;
'''+s[b:]
    s=replace(s,'      first_a_read || next_sw_read;','      first_a_read || next_sw_read || stream_first_a;')
    s=replace(s,'  assign ram_address=state==RAM_WRITE ?',"  assign ram_address=stream_first_a ? 12'(g*4) : state==RAM_WRITE ?")
    s=replace(s,'.wq_i(stream_group ? weight_group[beat[1:0]] : weight_data),','.wq_i(stream_active ? capture_data : stream_group ? weight_group[beat[1:0]] : weight_data),')
    s=replace(s,"        ROW_WEIGHT_LOAD:if(32'(offset)==d[17])begin", "        ROW_WEIGHT_LOAD:if(stream_active)begin end else if(32'(offset)==d[17])begin")
    # The old sequential datapath body owns all g/beat/phase/value counters;
    # these last-NBA overrides remain in that same original process.
    marker='    end\n  end\n  // Original nonreset state priorities only; asynchronousreset stays in FF.'
    overrides='''      if(!reset_grant&&!control_abort&&stream_active)begin
        if(state==STREAM_SW_BEGIN||state==STREAM_SW_WAIT)phase<=1;
        if(stream_first_a)begin
          group_elements<=64;beat<=0;token<=0;sw_value<=sw_current_value;phase<=2;
        end
        if(stream_result&&dma_resp==0)payload_read<=payload_read+stream_chunk_bytes;
      end
'''
    s=replace(s,marker,overrides+marker)
    # Keep the original abort/fault/reset priorities around new scheduling.
    marker='  end\n  always_ff @(posedge clk or negedge platform_reset_n)begin\n    if(!platform_reset_n)state<=IDLE;'
    decision='''    if(stream_active&&!reset_grant&&!control_abort)begin
      case(state)
        ROW_WEIGHT_LOAD:ce_state_next=STREAM_SW_BEGIN;
        STREAM_SW_BEGIN:ce_state_next=(row[1:0]!=0||sw_start_ready)?STREAM_SW_WAIT:STREAM_SW_BEGIN;
        STREAM_SW_WAIT:ce_state_next=sw_certificate&&sw_block_matches?ROW_BIAS:STREAM_SW_WAIT;
        ROW_BIAS:if(d[21]==0)ce_state_next=STREAM_W_WAIT;
        BIAS_BEGIN:if(count==0&&finite32(read_data[31:0]))ce_state_next=STREAM_W_WAIT;
        STREAM_W_WAIT:ce_state_next=stream_first_a?DOT_A:STREAM_W_WAIT;
        INLINE_FP_SEND:if(fp_ready&&fp_request_valid&&g+1<groups)ce_state_next=STREAM_W_WAIT;
        default:;
      endcase
    end
'''
    s=replace(s,marker,decision+marker);save(n,old,s)
    n='rtl/sfu/nx_opt11_dispatch.sv';old=(repo/n).read_text();a=old.index('\n// Internal startup-only');prefix=old[:a];suffix=old[a:]
    prefix=replace(prefix,'  input logic [127:0] ram_q',PORTS+'  input logic [127:0] ram_q')
    prefix=replace(prefix,'.ram_q(ram_q));','.ram_q(ram_q),'+CONNECT+');') if prefix.count('.ram_q(ram_q));')==1 else prefix
    # There are three controller instances. Only the linear one receives leases.
    if CONNECT not in prefix:
        a=prefix.index('  nx_ce64_control linear_control(');b=prefix.index('\n',a)
        line=prefix[a:b];assert line.endswith(');');line=line[:-2]+','+CONNECT+');';prefix=prefix[:a]+line+prefix[b:]
    prefix=replace(prefix,'nx_ce64_control linear_control(','nx_ce64_control #(.W_SW_STREAM(1)) linear_control(')
    save(n,old,prefix+suffix)
    n='rtl/ce64/nx_ce64.sv';old=(repo/n).read_text();s=old
    locals_=''.join('  '+t+' '+name+';\n' for _,t,name in FIELDS if not name.startswith('capture_r_'))
    s=replace(s,'  wire transport_drained=',locals_+'  wire transport_drained=')
    a=s.index('  nx_opt11_dispatch ');b=s.index('  nx_ce64_dma dma(',a)
    prefix=s[a:b];prefix=replace(prefix,'.ram_q(a_q));','.ram_q(a_q),'+','.join('.'+name+'('+name+')' for _,_,name in FIELDS if not name.startswith('capture_r_'))+',.capture_r_take(memory.rvalid&&memory.rready),.capture_r_data(memory.rdata),.capture_r_id(memory.rid),.capture_r_resp(memory.rresp),.capture_r_last(memory.rlast));')
    s=s[:a]+prefix+s[b:]
    s=replace(s,'  nx_ce64_dma dma(','  nx_ce64_dma #(.ENABLE_W_CAPTURE(1)) dma(')
    s=replace(s,'    .read_bytes(dma_read_bytes),.write_bytes(dma_write_bytes),.bus(memory));','''    .read_bytes(dma_read_bytes),.write_bytes(dma_write_bytes),
    .command_capture(dma_w_capture),.command_sw_capture(dma_sw_capture),.command_bank(dma_capture_bank),
    .capture_revoke,.capture_transport_fault(guard_fault||native_quarantined),.capture_live_owner(capture_owner),
    .command_capture_tag(capture_command_tag),.command_capture_scales(capture_command_scales),
    .capture_native_drained(native_safely_drained),.capture_guard_idle(guard_idle),.capture_release,
    .capture_peek_bank,.capture_peek_beat,.capture_peek_tag,.capture_data,.capture_mask,.capture_held,
    .capture_certificate,.capture_bad,.capture_result_seen,.capture_counts,.physical_idle(capture_physical_idle),.bus(memory));''')
    save(n,old,s)
    n='rtl/ce64/nx_ce64_dma.sv';base=ROOT/'evidence/OPT10_R1_LINEAR_STREAM_CAPTURE/opt10-r1-linear-stream-native-capture-20261021-v5/sources'/n;old=(repo/n).read_text();s=base.read_text()
    s=replace(s,'  input logic command_capture,command_bank,capture_revoke,capture_transport_fault,','  input logic command_capture,command_sw_capture,command_bank,capture_revoke,capture_transport_fault,')
    s=replace(s,'  logic capture_active,active_bank;','  logic capture_active,active_bank,sw_capture_active;')
    s=replace(s,'  // Payload has one physical write port and no reset or validity meaning.','''  // Sw has separate private payload; only suppress its old scratch write.
  // Accepted transaction state and bus.rready remain the original DMA's.
  always_ff @(posedge clk or negedge reset_n)begin
    if(!reset_n)sw_capture_active<=0;
    else if(command_valid&&command_ready)sw_capture_active<=ENABLE_W_CAPTURE&&command_sw_capture===1'b1;
    else if(result_valid&&result_ready)sw_capture_active<=0;
  end
  // Payload has one physical write port and no reset or validity meaning.''')
    s=replace(s,'&&!(ENABLE_W_CAPTURE&&capture_active))||state==WRITE_PREFETCH;', '&&!(ENABLE_W_CAPTURE&&(capture_active||sw_capture_active)))||state==WRITE_PREFETCH;')
    save(n,old,s)
    n='rtl/ce64/common/nx_ce64_guard.sv';save(n,(repo/n).read_text(),(ROOT/'variants/opt10_r1_guard_refill_v1'/n).read_text())
    print(V)
if __name__=='__main__':main()
