// Isolated Sw-private capture component. Payload: exactly 304 x 32 bits.
// This block only observes an accepted DMA fragment; it never drives READY,
// cancels transport, or occupies scratch/W payload storage.
module nx_ce64_sw_capture #(parameter bit W_PREFETCH=1, parameter bit PLANNED_PAYLOAD=0) (
  input logic clk, reset_n,
  input logic stop_new, revoke, transport_fault,
  input logic [127:0] live_owner,
  input logic [31:0] live_epoch, live_generation,
  input logic transport_idle, no_w_held,
  input logic start,
  input wire plan_start_hint,
  output logic start_ready,
  input logic [17:0] start_first_row,
  input logic [2:0] start_rows,
  input logic [6:0] start_groups,
  input logic fragment_begin,
  output logic fragment_ready,
  input logic [31:0] fragment_address,
  input logic [4:0] fragment_len,
  input logic [2:0] fragment_size,
  input logic [8:0] fragment_word_offset,
  input logic r_take,
  input logic [127:0] r_data,
  input logic [5:0] r_id,
  input logic [1:0] r_resp,
  input logic r_last,
  input logic result_take,
  input logic [1:0] result_resp,
  input logic [1:0] query_row,
  input logic [6:0] query_group,
  input logic [3:0] query_count,
  output logic [255:0] query_scales,
  output logic query_valid,
  input logic [1:0] value_row,
  input logic [6:0] value_group,
  output logic [31:0] value_scale,
  output logic value_zero,
  output logic value_valid,
  output wire [31:0] value_raw_scale,
  output wire value_raw_zero,
  output wire [255:0] query_raw_scales,
  output logic active, bad, certificate, fragment_pending,
  output logic [8:0] filled_words,
  output logic [127:0] block_owner,
  output logic [31:0] block_epoch, block_generation,
  output logic [17:0] block_first_row,
  output logic [2:0] block_rows,
  output logic [6:0] block_groups,
  output wire [8:0] block_words,
  output wire [8:0] offer_plan_filled_words,offer_plan_total_words
);
  // Cyclic word banking: logical word i is bank i[1:0], row i[8:2].
  // Every accepted beat writes at most one word to each bank.  Keep the
  // asynchronous read contract: one query read and one value read per bank.
  // There are still exactly 304 x 32 payload bits, with no payload reset.
  localparam integer BANK_BITS=W_PREFETCH ? 3 : 2;
  localparam integer BANKS=1<<BANK_BITS;
  localparam integer DEPTH=304/BANKS;
  wire [31:0] query_bank_data [0:BANKS-1];
  wire [31:0] value_bank_data [0:BANKS-1];
  wire [BANKS-1:0] value_bank_zero;
  logic [8:0] query_index_q,value_index_q;
  logic bad_reg, certificate_reg, fragment_legal, result_seen;
  logic [8:0] total_words, frag_offset, frag_words;
  // The controller consumes the count captured at start, not a live
  // row/group multiply in its DMA command path.
  assign block_words=total_words;
  logic [31:0] frag_address;
  logic [4:0] frag_len;
  logic [2:0] frag_size;
  logic [5:0] r_count;
  wire live_known=((live_owner^live_owner)===128'b0)&&
    ((live_epoch^live_epoch)===32'b0)&&((live_generation^live_generation)===32'b0);
  wire live_enabled=(stop_new===1'b0)&&(revoke===1'b0)&&
    (transport_fault===1'b0)&&live_known;
  // Compare immutable identity bytes in parallel before the small balanced
  // reduction. Case equality retains the original X/Z matching semantics;
  // live_known independently rejects unknown live identities immediately.
  wire [191:0] live_identity={live_owner,live_epoch,live_generation};
  wire [191:0] block_identity={block_owner,block_epoch,block_generation};
  wire [23:0] identity_byte_match;
  wire [3:0] identity_group_match;
  generate for(genvar b=0;b<24;b++)begin:identity_compare_byte
    assign identity_byte_match[b]=live_identity[8*b+:8]===block_identity[8*b+:8];
  end
  for(genvar g=0;g<4;g++)begin:identity_compare_group
    assign identity_group_match[g]=&identity_byte_match[6*g+:6];
  end endgenerate
  wire owner_match=&identity_group_match;
  wire poison=!live_enabled || (active&&!owner_match);
  wire physical_safe=(transport_idle===1'b1)&&(no_w_held===1'b1);
  wire [9:0] start_words={7'b0,start_rows}*{3'b0,start_groups};
  wire start_legal=(((start_first_row^start_first_row)===18'b0)&&
    start_rows>=1&&start_rows<=4&&start_groups>=1&&start_groups<=76&&
    start_words>=1&&start_words<=304)===1'b1;
  // Plan the next eligible fragment while this one drains. This is not a
  // promise that filled_words advances on the next clock: only a successful
  // physical retirement exposes this end offset to fragment_ready. Start
  // has the same known-true priority as the original procedural capture.
  wire offer_plan_start=(PLANNED_PAYLOAD ? plan_start_hint : start&&start_ready)===1'b1;
  assign offer_plan_total_words=offer_plan_start ? start_words[8:0] : total_words;
  assign offer_plan_filled_words=offer_plan_start ? 9'b0 :
    (fragment_pending ? 9'(frag_offset+frag_words) : filled_words);
  wire [8:0] offered_words=({4'b0,fragment_len}+9'd1) << (fragment_size==4 ? 2 : 0);
  wire [9:0] offered_end={1'b0,fragment_word_offset}+{1'b0,offered_words};
  wire [32:0] offered_byte_end={1'b0,fragment_address}+
    (({28'b0,fragment_len}+33'd1)<<fragment_size);
  wire offered_legal=((fragment_size==4||fragment_size==2)&&
    (fragment_address&((32'd1<<fragment_size)-1))==0&&
    offered_byte_end>{1'b0,fragment_address}&&
    (offered_byte_end-1)>>12=={1'b0,fragment_address}>>12&&
    fragment_word_offset==filled_words&&offered_end<={1'b0,total_words}&&
    offered_end<=304)===1'b1;
  wire [31:0] beat_address=frag_address+({26'b0,r_count}<<frag_size);
  wire [9:0] write_word={1'b0,frag_offset}+({4'b0,r_count}<<(frag_size==4 ? 2 : 0));
  wire [2:0] words_per_beat=frag_size==4 ? 3'd4 : 3'd1;
  wire payload_write=fragment_pending&&fragment_legal&&r_take&&
    r_count<({1'b0,frag_len}+6'd1)&&write_word+words_per_beat<=304;
  logic [31:0] incoming [0:3];
  logic incoming_bad;
  wire [8:0] query_index={7'b0,query_row}*{2'b0,block_groups}+{2'b0,query_group};
  wire [8:0] value_index={7'b0,value_row}*{2'b0,block_groups}+{2'b0,value_group};
  always_ff @(posedge clk)begin query_index_q<=query_index;value_index_q<=value_index;end
  always_comb begin
    incoming_bad=0;
    for(integer k=0;k<4;k++)begin
      incoming[k]=0;
      if(k<words_per_beat)begin
        incoming[k]=r_data[8*beat_address[3:0]+32*k+:32];
        if(((incoming[k]^incoming[k])!==32'b0)||
           nx_ce64_math_pkg::scale32(incoming[k])!==1'b1)incoming_bad=1;
      end
    end
  end

  // A logical burst need not begin on a bank boundary: earlier narrow
  // fragments may leave filled_words unaligned.  Rotate the beat lanes and
  // carry into the bank row for the banks preceding the starting bank.
  generate for(genvar b=0;b<BANKS;b++)begin:sw_payload_bank
    localparam logic [BANK_BITS-1:0] BANK=BANK_BITS'(b);
    logic [31:0] words [0:DEPTH-1];
    // One predicate bit per payload word, written before the read-side
    // capture edge.  The payload RAM keeps its existing read/register
    // structure; there is no wide comparator on its value read port.
    logic zero_words [0:DEPTH-1];
    wire [BANK_BITS-1:0] write_lane=BANK-write_word[BANK_BITS-1:0];
    wire [8-BANK_BITS:0] write_address=write_word[8:BANK_BITS]+(BANK<write_word[BANK_BITS-1:0]);
    wire [8-BANK_BITS:0] query_address=query_index[8:BANK_BITS]+(BANK<query_index[BANK_BITS-1:0]);
    // No reset, no second logical Sw copy, no W-bank/scratch writes.
    always_ff @(posedge clk)begin
      if(payload_write&&{1'b0,write_lane}<words_per_beat)begin
        words[write_address]<=incoming[write_lane];
        zero_words[write_address]<=(incoming[write_lane]==32'b0);
      end
    end
    if(W_PREFETCH)begin:synchronous_read
      logic [31:0] query_q,value_q;
      logic zero_q;
      always_ff @(posedge clk)begin
        query_q<=words[query_address];
        value_q<=words[value_index[8:BANK_BITS]];
        zero_q<=zero_words[value_index[8:BANK_BITS]];
      end
      assign query_bank_data[b]=query_q;
      assign value_bank_data[b]=value_q;
      assign value_bank_zero[b]=zero_q;
    end else begin:asynchronous_read
      assign query_bank_data[b]=words[query_address];
      assign value_bank_data[b]=words[value_index[8:BANK_BITS]];
      assign value_bank_zero[b]=zero_words[value_index[8:BANK_BITS]];
    end
  end endgenerate

  // Raw payload uses the same existing synchronous bank responses. Consumers
  // retain all original query/value validity and immediate revoke checks.
  assign value_raw_scale=value_bank_data[value_index[BANK_BITS-1:0]];
  assign value_raw_zero=value_bank_zero[value_index[BANK_BITS-1:0]];
  generate for(genvar rb=0;rb<BANKS;rb++)begin:raw_query_payload
    assign query_raw_scales[32*rb+:32]=rb<query_count ?
      query_bank_data[BANK_BITS'(query_index[BANK_BITS-1:0]+rb)] : 32'b0;
  end
  if(BANKS<8)begin:raw_query_unused
    assign query_raw_scales[255:BANKS*32]=0;
  end endgenerate
  assign start_ready=reset_n&&live_enabled&&physical_safe&&!fragment_pending;
  assign fragment_ready=reset_n&&!start&&active&&!bad&&!certificate&&!fragment_pending&&
    physical_safe&&!poison&&filled_words<total_words;
  assign bad=bad_reg||(active&&poison);
  assign certificate=active&&certificate_reg&&!bad&&!poison&&!(start&&start_ready);
  always_comb begin
    query_scales=0;query_valid=0;value_scale=0;value_zero=1'b1;value_valid=0;
    if(certificate&&((query_row^query_row)===2'b0)&&
       ((query_group^query_group)===7'b0)&&((query_count^query_count)===4'b0)&&
       {1'b0,query_row}<block_rows&&query_count>=1&&query_count<=BANKS&&(!W_PREFETCH||query_index_q===query_index)&&
       ({1'b0,query_group}+query_count)<={1'b0,block_groups})begin
      query_valid=1;
      for(integer k=0;k<BANKS;k++)if(k<query_count)
        query_scales[32*k+:32]=query_bank_data[BANK_BITS'(query_index[BANK_BITS-1:0]+k)];
    end
    if(certificate&&((value_row^value_row)===2'b0)&&
       ((value_group^value_group)===7'b0)&&{1'b0,value_row}<block_rows&&
       value_group<block_groups&&(!W_PREFETCH||value_index_q===value_index))begin
      value_valid=1;value_scale=value_bank_data[value_index[BANK_BITS-1:0]];
      value_zero=value_bank_zero[value_index[BANK_BITS-1:0]];
    end
  end

  // A count is consumed only while a fragment is pending. Pre-clear the
  // private counter while idle, including the fragment-acceptance edge, so
  // its enable does not depend on the DMA command-ready/abort cone.
  always_ff @(posedge clk or negedge reset_n)begin
    if(!reset_n)r_count<=0;
    else if(!fragment_pending)r_count<=0;
    else if(r_take)begin
      if(r_count!=63)r_count<=r_count+1'b1;
    end
  end

  always_ff @(posedge clk or negedge reset_n)begin
    if(!reset_n)begin
      active<=0;bad_reg<=0;certificate_reg<=0;fragment_pending<=0;
      fragment_legal<=0;result_seen<=0;filled_words<=0;total_words<=0;
      frag_offset<=0;frag_words<=0;frag_address<=0;frag_len<=0;frag_size<=0;
      block_owner<=0;block_epoch<=0;block_generation<=0;block_first_row<=0;block_rows<=0;block_groups<=0;
    end else begin
      if(active&&poison)begin bad_reg<=1;certificate_reg<=0;end
      if(start&&start_ready)begin
        active<=1;bad_reg<=!start_legal;certificate_reg<=0;fragment_pending<=0;
        fragment_legal<=0;result_seen<=0;filled_words<=0;total_words<=start_words[8:0];
        block_owner<=live_owner;block_epoch<=live_epoch;block_generation<=live_generation;
        block_first_row<=start_first_row;block_rows<=start_rows;block_groups<=start_groups;
      end else if(fragment_begin&&fragment_ready)begin
        fragment_pending<=1;fragment_legal<=offered_legal;result_seen<=0;
        frag_offset<=fragment_word_offset;frag_words<=offered_words;
        frag_address<=fragment_address;frag_len<=fragment_len;frag_size<=fragment_size;
        if(!offered_legal)begin bad_reg<=1;certificate_reg<=0;end
      end else if(fragment_pending)begin
        if(no_w_held!==1'b1)begin bad_reg<=1;certificate_reg<=0;end
        if(r_take)begin
          if(result_seen||r_count>={1'b0,frag_len}+6'd1||r_id!==0||r_resp!==0||
             r_last!==(r_count=={1'b0,frag_len})||incoming_bad)begin
            bad_reg<=1;certificate_reg<=0;
          end
        end
        if(result_take)begin
          result_seen<=1;
          if(result_seen||r_take||result_resp!==0||r_count!={1'b0,frag_len}+6'd1)begin
            bad_reg<=1;certificate_reg<=0;
          end
        end
        // A result is insufficient: real DMA/guard/native idle must follow it.
        if(result_seen&&physical_safe)begin
          fragment_pending<=0;result_seen<=0;
          if(!bad&&!poison&&fragment_legal&&!r_take&&!result_take&&
             r_count=={1'b0,frag_len}+6'd1)begin
            filled_words<=frag_offset+frag_words;
            if({1'b0,frag_offset}+{1'b0,frag_words}=={1'b0,total_words})certificate_reg<=1;
          end
        end
      end
    end
  end
endmodule
