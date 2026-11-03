// One non-cancellable quantum. Once command_ready accepts a command all AXI
// offers survive isolate/reset requests; only platform reset resets this unit.
// Reads: <=32 beats, <=512B, no page crossing. A scalar write uses command_data.
// New full-width writes with nonzero command_scratch prebuffer the complete
// quantum from the single scratch port BEFORE AW. Accepted offers never cancel.
module nx_ce64_dma #(parameter bit ENABLE_W_CAPTURE=0, W_PREFETCH=1) (
  input logic clk, reset_n, stop_new,
  input logic command_valid, command_write,
  output logic command_ready,
  input logic [31:0] command_address,
  input logic [2:0] command_size,
  input logic [4:0] command_len,
  input logic [15:0] command_scratch,
  input logic [127:0] command_data,
  input logic [15:0] command_mask,
  output logic result_valid,
  input logic result_ready,
  output logic [1:0] result_resp,
  output logic [31:0] result_address,
  output logic idle, pending_offer,
  output logic scratch_en,
  output logic [11:0] scratch_addr,
  output logic [127:0] scratch_data,
  output logic [15:0] scratch_mask,
  output logic [15:0] scratch_min80,scratch_nonzero,
  output logic [15:0] scratch_scale_zero,scratch_scale_lo0,scratch_scale_lo1,
  input logic [127:0] scratch_q,
  output logic [63:0] read_bytes, write_bytes,
  // Optional private W lease. Default OFF preserves the original DMA interface.
  input logic command_capture,command_sw_capture,command_bank,capture_revoke,capture_transport_fault,
  input logic [127:0] capture_live_owner,
  input logic [63:0] command_capture_tag,capture_peek_tag,
  input logic [255:0] command_capture_scales,
  input logic capture_native_drained,capture_guard_idle,
  input logic [1:0] capture_release,
  input logic capture_peek_bank,
  input logic [4:0] capture_peek_beat,
  output logic [127:0] capture_data,
  // Arithmetic-only parallel read. Authorization is still represented by
  // capture_mask and capture_data retains its original fail-closed value.
  output wire [127:0] capture_raw_data,
  input logic [9:0] capture_raw_beats,
  output wire [255:0] capture_raw_banks,
  output logic [15:0] capture_mask,
  output logic [1:0] capture_held,capture_certificate,capture_bad,capture_result_seen,
  output logic [11:0] capture_counts,
  output logic physical_idle,
  // Accepted W command context, held through its entire AR/R/result lifetime.
  // The fabric qualifies this with its real selected port; this is not an ID
  // convention and does not grant a bank certificate or a consumer credit.
  output wire w_capture_pending,
  output wire [255:0] observer_live,
  axi4_if.master bus
);
  typedef enum logic [2:0] {IDLE, READ_ADDR, READ_DATA, WRITE_SEND,
                            WRITE_RESP, RESULT, WRITE_PREFETCH, WRITE_CAPTURE} state_t;
  state_t state;
  logic [31:0] address, base_address;
  logic [15:0] local_address;
  // Both addresses advance by the same accepted beat size. Their low-byte
  // displacement is invariant for the full non-cancellable command.
  logic [3:0] read_byte_rotation;
  logic [2:0] size;
  logic [4:0] length, beat;
  logic [127:0] data;
  logic [15:0] mask;
  logic aw_sent,w_sent;
  logic [1:0] response;
  logic legal;
  logic buffered_write;
  logic [127:0] write_buffer[0:31];
  wire source_write=command_write&&command_scratch!=0;
  // LEN is at most 31 and legal SIZE is at most 4: the last byte is at
  // most 511 bytes beyond the first. Form that displacement by wiring,
  // without a LEN+1 -> variable shift -> full-address add -> subtract chain.
  logic [8:0] command_last_byte;
  logic [3:0] command_alignment_mask;
  always_comb begin
    command_last_byte=0;command_alignment_mask=0;
    case(command_size)
      3'd0:begin command_last_byte={4'b0,command_len};command_alignment_mask=4'h0;end
      3'd1:begin command_last_byte={3'b0,command_len,1'b1};command_alignment_mask=4'h1;end
      3'd2:begin command_last_byte={2'b0,command_len,2'b11};command_alignment_mask=4'h3;end
      3'd3:begin command_last_byte={1'b0,command_len,3'b111};command_alignment_mask=4'h7;end
      3'd4:begin command_last_byte={command_len,4'b1111};command_alignment_mask=4'hf;end
      default:begin command_last_byte=0;command_alignment_mask=0;end
    endcase
  end
  wire [9:0] command_address_last_low={1'b0,command_address[8:0]}+{1'b0,command_last_byte};
  wire [9:0] command_scratch_last_low={1'b0,command_scratch[8:0]}+{1'b0,command_last_byte};
  // A carry out of bit 8 can cross a 4-KiB/64-KiB boundary only when every
  // remaining bit below that boundary is one. The page check also excludes
  // 32-bit address overflow; a last byte of 0xffffffff remains legal.
  wire command_page_ok=!(command_address_last_low[9]&&(&command_address[11:9]));
  wire command_scratch_ok=!(command_scratch_last_low[9]&&(&command_scratch[15:9]));
  // Do not let the unused upper address bits hide an X/Z in simulation.
  wire command_fields_known=((command_address^command_address)===32'b0)&&
      ((command_scratch^command_scratch)===16'b0)&&
      ((command_len^command_len)===5'b0)&&((command_size^command_size)===3'b0);
  assign legal=command_fields_known&&command_size<=4 &&
      (command_address[3:0]&command_alignment_mask)==0 &&
      (command_scratch[3:0]&command_alignment_mask)==0 &&
      command_page_ok && command_scratch_ok &&
      (!command_write || (source_write ? command_size==4&&command_mask==16'hffff&&command_scratch>=16'hf000 : command_len==0));
  wire capture_request=ENABLE_W_CAPTURE ? command_capture===1'b1 : 1'b0;
  wire capture_shape=command_size==4 && command_len[1:0]==2'b11 &&
      (W_PREFETCH || command_len<=15);
  wire accepted_legal=legal&&(!capture_request||(!command_write&&capture_shape));
  wire owner_known=((capture_live_owner^capture_live_owner)===128'b0);
  wire tag_known=((command_capture_tag^command_capture_tag)===64'b0);
  logic capture_active,active_bank,sw_capture_active;
  assign w_capture_pending=ENABLE_W_CAPTURE && capture_active;
  logic [127:0] bank_owner[2];
  logic [255:0] bank_scales[2];
  logic [63:0] bank_tag[2];
  logic [5:0] bank_count[2],bank_expected[2];
  // Compare each immutable bank identity before selecting a bank. Byte
  // comparisons followed by small reductions avoid the long wide-compare
  // carry chain; case equality keeps every X/Z match of the original check.
  // Both tool stages retain these boundaries: keep prevents Yosys merging,
  // syn_keep maps to the documented ADS PAP_KEEP. The production lowerer
  // exports only this explicitly qualified synthesis attribute.
  wire [1:0] bank_owner_match,bank_tag_match;
  generate for(genvar b=0;b<2;b++)begin:capture_identity_compare
    (* keep=1, syn_keep=1 *) wire [15:0] owner_byte_match;
    (* keep=1, syn_keep=1 *) wire [3:0] owner_group_match;
    (* keep=1, syn_keep=1 *) wire [7:0] tag_byte_match;
    (* keep=1, syn_keep=1 *) wire [1:0] tag_group_match;
    for(genvar k=0;k<16;k++)begin:owner_byte
      assign owner_byte_match[k]=capture_live_owner[8*k+:8]===bank_owner[b][8*k+:8];
    end
    for(genvar g=0;g<4;g++)begin:owner_group
      assign owner_group_match[g]=&owner_byte_match[4*g+:4];
    end
    for(genvar k=0;k<8;k++)begin:tag_byte
      assign tag_byte_match[k]=capture_peek_tag[8*k+:8]===bank_tag[b][8*k+:8];
    end
    for(genvar g=0;g<2;g++)begin:tag_group
      assign tag_group_match[g]=&tag_byte_match[4*g+:4];
    end
    assign bank_owner_match[b]=&owner_group_match;
    assign bank_tag_match[b]=&tag_group_match;
  end endgenerate
  wire owner_wrong=(capture_held[0]&&!bank_owner_match[0])||
                   (capture_held[1]&&!bank_owner_match[1]);
  wire capture_poison=ENABLE_W_CAPTURE&&((stop_new!==1'b0)||(capture_revoke!==1'b0)||
      (capture_transport_fault!==1'b0)||!owner_known||owner_wrong);
  wire physical_safe=state==IDLE&&capture_native_drained===1'b1&&capture_guard_idle===1'b1;
  assign physical_idle=state==IDLE;
  assign command_ready=reset_n && state==IDLE && !stop_new &&
      (!ENABLE_W_CAPTURE || (!capture_poison&&!(|capture_bad)&&
       (capture_request ? ((command_bank===1'b0||command_bank===1'b1)&&!capture_held[command_bank]&&tag_known&&physical_safe) :
                          (command_capture===1'b0&&!(|capture_held)))));
  assign idle=state==IDLE&&!(|capture_held);
  generate if(ENABLE_W_CAPTURE)begin:w_capture
    wire [127:0] bank_q[0:1];
    wire [4:0] response_beat[0:1];
    if(W_PREFETCH)begin:sync_prefetch
      // Separate 2 x 512B W payload, one write and one synchronous read per
      // bank. Generic 512B write buffering retains its original storage.
      // Payload is never reset; lease metadata is the only authorization.
      for(genvar b=0;b<2;b++)begin:banks
        logic [127:0] payload[0:31];
        logic [127:0] q;
        logic [4:0] q_beat;
        always_ff @(posedge clk)begin
          if(capture_active&&active_bank==b&&state==READ_DATA&&bus.rvalid&&bus.rready)
            payload[beat]<=bus.rdata;
          q<=payload[capture_raw_beats[5*b+:5]];
          q_beat<=capture_raw_beats[5*b+:5];
        end
        assign bank_q[b]=q;
        assign response_beat[b]=q_beat;
      end
    end else begin:legacy_prefetch
      for(genvar b=0;b<2;b++)begin:banks
        assign bank_q[b]=write_buffer[{1'(b),capture_raw_beats[5*b+:4]}];
        assign response_beat[b]={1'b0,capture_raw_beats[5*b+:4]};
      end
    end
    assign capture_raw_data=bank_q[capture_peek_bank];
    assign capture_raw_banks={bank_q[1],bank_q[0]};
    for(genvar b=0;b<2;b++)assign capture_counts[6*b+:6]=bank_count[b];
    always_comb begin
      capture_data=0;capture_mask=0;
      if((capture_peek_bank===1'b0||capture_peek_bank===1'b1)&&!capture_poison&&
          capture_certificate[capture_peek_bank]&&!capture_bad[capture_peek_bank]&&
          bank_owner_match[capture_peek_bank]&&bank_tag_match[capture_peek_bank]&&
          {1'b0,capture_peek_beat}<bank_expected[capture_peek_bank]&&
          response_beat[capture_peek_bank]===capture_peek_beat)begin
        capture_data=bank_q[capture_peek_bank];capture_mask=16'hffff;
      end
    end
    always_ff @(posedge clk or negedge reset_n)begin
      if(!reset_n)begin
        capture_active<=0;active_bank<=0;capture_held<=0;capture_certificate<=0;capture_bad<=0;capture_result_seen<=0;
        for(integer b=0;b<2;b++)begin bank_owner[b]<=0;bank_tag[b]<=0;bank_scales[b]<=0;bank_count[b]<=0;bank_expected[b]<=0;end
      end else begin
        if(capture_poison)for(integer b=0;b<2;b++)if(capture_held[b])begin capture_bad[b]<=1;capture_certificate[b]<=0;end
        if(command_valid&&command_ready)begin
          capture_active<=capture_request;active_bank<=command_bank;
          if(capture_request)begin
            capture_held[command_bank]<=1;capture_certificate[command_bank]<=0;capture_result_seen[command_bank]<=0;
            capture_bad[command_bank]<=!accepted_legal;bank_count[command_bank]<=0;bank_expected[command_bank]<={1'b0,command_len}+6'd1;
            bank_owner[command_bank]<=capture_live_owner;bank_tag[command_bank]<=command_capture_tag;bank_scales[command_bank]<=command_capture_scales;
            for(integer g=0;g<8;g++)if(g<(int'(command_len)+1)/4&&
                nx_ce64_math_pkg::scale32(command_capture_scales[32*g+:32])!==1'b1)capture_bad[command_bank]<=1;
          end
        end
        if(capture_active&&state==READ_DATA&&bus.rvalid&&bus.rready)begin
          bank_count[active_bank]<=bank_count[active_bank]+1'b1;
          if(bus.rresp!==0||bus.rid!==0||bus.rlast!==(beat==length)||((bus.rdata^bus.rdata)!==128'b0))capture_bad[active_bank]<=1;
          for(integer b=0;b<16;b++)if(bus.rdata[8*b+:8]===8'h80||
              (bank_scales[active_bank][32*beat[4:2]+:32]==0&&bus.rdata[8*b+:8]!==0))capture_bad[active_bank]<=1;
        end
        if(capture_active&&result_valid&&result_ready)begin
          capture_result_seen[active_bank]<=1;capture_active<=0;
          if(result_resp!==0||bank_count[active_bank]!=bank_expected[active_bank])capture_bad[active_bank]<=1;
        end
        for(integer b=0;b<2;b++)begin
          if(capture_held[b]&&capture_result_seen[b]&&!capture_bad[b]&&!capture_poison&&physical_safe&&
              bank_count[b]==bank_expected[b])capture_certificate[b]<=1;
          // Release is a consumer assertion that all operands have been copied.
          // Another bank may still be physically in flight; this bank never is.
          if(capture_release[b]===1'b1&&capture_held[b]&&capture_result_seen[b]&&
              !(capture_active&&active_bank==b))begin
            capture_held[b]<=0;capture_bad[b]<=0;capture_certificate[b]<=0;capture_result_seen[b]<=0;bank_count[b]<=0;
          end
        end
      end
    end
  end else begin:legacy_capture_off
    assign capture_raw_data=0;
    assign capture_raw_banks=0;
    assign capture_held=0;assign capture_certificate=0;assign capture_bad=0;assign capture_result_seen=0;assign capture_counts=0;
    assign capture_data=0;assign capture_mask=0;
  end endgenerate
  // Sw has separate private payload; only suppress its old scratch write.
  // Accepted transaction state and bus.rready remain the original DMA's.
  always_ff @(posedge clk or negedge reset_n)begin
    if(!reset_n)sw_capture_active<=0;
    else if(command_valid&&command_ready)sw_capture_active<=ENABLE_W_CAPTURE&&command_sw_capture===1'b1;
    else if(result_valid&&result_ready)sw_capture_active<=0;
  end
  // Payload has one physical write port and no reset or validity meaning.
  // Asynchronous reset only clears metadata; stale payload is never eligible.
  always_ff @(posedge clk)begin
    if(state==WRITE_CAPTURE)write_buffer[beat]<=scratch_q;
    else if(ENABLE_W_CAPTURE&&!W_PREFETCH&&capture_active&&state==READ_DATA&&bus.rvalid)
      write_buffer[{active_bank,beat[3:0]}]<=bus.rdata;
  end
  assign pending_offer=(state==READ_ADDR) ||
                        (state==WRITE_SEND && (!aw_sent || !w_sent));
  // Passive payload. No observer signal authorizes or stalls a transaction.
  assign observer_live={32'b0,{28'b0,buffered_write,pending_offer,result_valid,idle},
    {30'b0,response},{13'b0,read_byte_rotation,size,length,beat,aw_sent,w_sent},
    {16'b0,local_address},address,base_address,{29'b0,state}};
  assign result_valid=state==RESULT;
  assign result_resp=response;
  assign result_address=base_address;
  assign bus.araddr=address; assign bus.arid=0;
  assign bus.arlen={3'b0,length}; assign bus.arsize=size; assign bus.arburst=1;
  assign bus.arvalid=reset_n && state==READ_ADDR;
  assign bus.rready=reset_n && state==READ_DATA;
  assign bus.awaddr=address; assign bus.awid=0;
  assign bus.awlen={3'b0,length}; assign bus.awsize=size; assign bus.awburst=1;
  assign bus.awvalid=reset_n && state==WRITE_SEND && !aw_sent;
  assign bus.wdata=buffered_write ? write_buffer[beat] : data;
  assign bus.wstrb=mask; assign bus.wlast=beat==length;
  assign bus.wvalid=reset_n && state==WRITE_SEND && !w_sent;
  assign bus.bready=reset_n && state==WRITE_RESP;
  // Classify before the payload's dynamic byte selection. These are raw
  // write metadata only: no transaction check, enable or mask is changed.
  logic [15:0] read_min80,read_nonzero;
  logic [15:0] read_scale_zero,read_scale_lo0,read_scale_lo1;
  always_comb begin
    read_min80=0;read_nonzero=0;
    for(integer i=0;i<16;i=i+1)begin
      if(bus.rdata[8*i+:8]==8'h80)read_min80[i]=1'b1;
      if(bus.rdata[8*i+:8]!=0)read_nonzero[i]=1'b1;
      // These scale predicates retain logical X. In particular, they are
      // not the known-true projection used by the legacy error predicates.
      read_scale_zero[i]=(bus.rdata[8*i+:8]==8'b0);
      read_scale_lo0[i]=!bus.rdata[8*i+7] && (bus.rdata[8*i+:7]!=7'b0);
      read_scale_lo1[i]=!bus.rdata[8*i+7] && (bus.rdata[8*i+:7]!=7'h7f);
    end
  end
  wire [3:0] read_source_lane[0:15];
  generate for(genvar byte_lane=0;byte_lane<16;byte_lane++)begin:read_byte_rotate
    assign read_source_lane[byte_lane]=read_byte_rotation+4'(byte_lane);
  end endgenerate
  always_comb begin
    scratch_en=(state==READ_DATA && bus.rvalid&&!(ENABLE_W_CAPTURE&&(capture_active||sw_capture_active)))||state==WRITE_PREFETCH;
    scratch_addr=local_address[15:4];
    // Only original mask-selected bytes are stored by the scratch port.
    // A single command-latched rotation supplies every lane; inactive and
    // unmasked payload may differ, while all enables/masks remain unchanged.
    for(integer i=0;i<16;i=i+1)begin
      scratch_data[8*i+:8]=bus.rdata[8*read_source_lane[i]+:8];
      scratch_min80[i]=read_min80[read_source_lane[i]];
      scratch_nonzero[i]=read_nonzero[read_source_lane[i]];
      scratch_scale_zero[i]=read_scale_zero[read_source_lane[i]];
      scratch_scale_lo0[i]=read_scale_lo0[read_source_lane[i]];
      scratch_scale_lo1[i]=read_scale_lo1[read_source_lane[i]];
    end
    if(state==READ_DATA)begin
      case(size)
        3'd0:begin
          case(local_address[3:0])
            4'd0:scratch_mask=16'h0001;
            4'd1:scratch_mask=16'h0002;
            4'd2:scratch_mask=16'h0004;
            4'd3:scratch_mask=16'h0008;
            4'd4:scratch_mask=16'h0010;
            4'd5:scratch_mask=16'h0020;
            4'd6:scratch_mask=16'h0040;
            4'd7:scratch_mask=16'h0080;
            4'd8:scratch_mask=16'h0100;
            4'd9:scratch_mask=16'h0200;
            4'd10:scratch_mask=16'h0400;
            4'd11:scratch_mask=16'h0800;
            4'd12:scratch_mask=16'h1000;
            4'd13:scratch_mask=16'h2000;
            4'd14:scratch_mask=16'h4000;
            4'd15:scratch_mask=16'h8000;
            default:scratch_mask=0;
          endcase
        end
        3'd1:begin
          case(local_address[3:0])
            4'd0:scratch_mask=16'h0003;
            4'd1:scratch_mask=16'h0006;
            4'd2:scratch_mask=16'h000c;
            4'd3:scratch_mask=16'h0018;
            4'd4:scratch_mask=16'h0030;
            4'd5:scratch_mask=16'h0060;
            4'd6:scratch_mask=16'h00c0;
            4'd7:scratch_mask=16'h0180;
            4'd8:scratch_mask=16'h0300;
            4'd9:scratch_mask=16'h0600;
            4'd10:scratch_mask=16'h0c00;
            4'd11:scratch_mask=16'h1800;
            4'd12:scratch_mask=16'h3000;
            4'd13:scratch_mask=16'h6000;
            4'd14:scratch_mask=16'hc000;
            4'd15:scratch_mask=16'h8000;
            default:scratch_mask=0;
          endcase
        end
        3'd2:begin
          case(local_address[3:0])
            4'd0:scratch_mask=16'h000f;
            4'd1:scratch_mask=16'h001e;
            4'd2:scratch_mask=16'h003c;
            4'd3:scratch_mask=16'h0078;
            4'd4:scratch_mask=16'h00f0;
            4'd5:scratch_mask=16'h01e0;
            4'd6:scratch_mask=16'h03c0;
            4'd7:scratch_mask=16'h0780;
            4'd8:scratch_mask=16'h0f00;
            4'd9:scratch_mask=16'h1e00;
            4'd10:scratch_mask=16'h3c00;
            4'd11:scratch_mask=16'h7800;
            4'd12:scratch_mask=16'hf000;
            4'd13:scratch_mask=16'he000;
            4'd14:scratch_mask=16'hc000;
            4'd15:scratch_mask=16'h8000;
            default:scratch_mask=0;
          endcase
        end
        3'd3:begin
          case(local_address[3:0])
            4'd0:scratch_mask=16'h00ff;
            4'd1:scratch_mask=16'h01fe;
            4'd2:scratch_mask=16'h03fc;
            4'd3:scratch_mask=16'h07f8;
            4'd4:scratch_mask=16'h0ff0;
            4'd5:scratch_mask=16'h1fe0;
            4'd6:scratch_mask=16'h3fc0;
            4'd7:scratch_mask=16'h7f80;
            4'd8:scratch_mask=16'hff00;
            4'd9:scratch_mask=16'hfe00;
            4'd10:scratch_mask=16'hfc00;
            4'd11:scratch_mask=16'hf800;
            4'd12:scratch_mask=16'hf000;
            4'd13:scratch_mask=16'he000;
            4'd14:scratch_mask=16'hc000;
            4'd15:scratch_mask=16'h8000;
            default:scratch_mask=0;
          endcase
        end
        3'd4:begin
          case(local_address[3:0])
            4'd0:scratch_mask=16'hffff;
            4'd1:scratch_mask=16'hfffe;
            4'd2:scratch_mask=16'hfffc;
            4'd3:scratch_mask=16'hfff8;
            4'd4:scratch_mask=16'hfff0;
            4'd5:scratch_mask=16'hffe0;
            4'd6:scratch_mask=16'hffc0;
            4'd7:scratch_mask=16'hff80;
            4'd8:scratch_mask=16'hff00;
            4'd9:scratch_mask=16'hfe00;
            4'd10:scratch_mask=16'hfc00;
            4'd11:scratch_mask=16'hf800;
            4'd12:scratch_mask=16'hf000;
            4'd13:scratch_mask=16'he000;
            4'd14:scratch_mask=16'hc000;
            4'd15:scratch_mask=16'h8000;
            default:scratch_mask=0;
          endcase
        end
        3'd5:begin
          case(local_address[3:0])
            4'd0:scratch_mask=16'hffff;
            4'd1:scratch_mask=16'hfffe;
            4'd2:scratch_mask=16'hfffc;
            4'd3:scratch_mask=16'hfff8;
            4'd4:scratch_mask=16'hfff0;
            4'd5:scratch_mask=16'hffe0;
            4'd6:scratch_mask=16'hffc0;
            4'd7:scratch_mask=16'hff80;
            4'd8:scratch_mask=16'hff00;
            4'd9:scratch_mask=16'hfe00;
            4'd10:scratch_mask=16'hfc00;
            4'd11:scratch_mask=16'hf800;
            4'd12:scratch_mask=16'hf000;
            4'd13:scratch_mask=16'he000;
            4'd14:scratch_mask=16'hc000;
            4'd15:scratch_mask=16'h8000;
            default:scratch_mask=0;
          endcase
        end
        3'd6:begin
          case(local_address[3:0])
            4'd0:scratch_mask=16'hffff;
            4'd1:scratch_mask=16'hfffe;
            4'd2:scratch_mask=16'hfffc;
            4'd3:scratch_mask=16'hfff8;
            4'd4:scratch_mask=16'hfff0;
            4'd5:scratch_mask=16'hffe0;
            4'd6:scratch_mask=16'hffc0;
            4'd7:scratch_mask=16'hff80;
            4'd8:scratch_mask=16'hff00;
            4'd9:scratch_mask=16'hfe00;
            4'd10:scratch_mask=16'hfc00;
            4'd11:scratch_mask=16'hf800;
            4'd12:scratch_mask=16'hf000;
            4'd13:scratch_mask=16'he000;
            4'd14:scratch_mask=16'hc000;
            4'd15:scratch_mask=16'h8000;
            default:scratch_mask=0;
          endcase
        end
        3'd7:begin
          case(local_address[3:0])
            4'd0:scratch_mask=16'hffff;
            4'd1:scratch_mask=16'hfffe;
            4'd2:scratch_mask=16'hfffc;
            4'd3:scratch_mask=16'hfff8;
            4'd4:scratch_mask=16'hfff0;
            4'd5:scratch_mask=16'hffe0;
            4'd6:scratch_mask=16'hffc0;
            4'd7:scratch_mask=16'hff80;
            4'd8:scratch_mask=16'hff00;
            4'd9:scratch_mask=16'hfe00;
            4'd10:scratch_mask=16'hfc00;
            4'd11:scratch_mask=16'hf800;
            4'd12:scratch_mask=16'hf000;
            4'd13:scratch_mask=16'he000;
            4'd14:scratch_mask=16'hc000;
            4'd15:scratch_mask=16'h8000;
            default:scratch_mask=0;
          endcase
        end
        default:scratch_mask=0;
      endcase
    end else scratch_mask=0;
  end
  always_ff @(posedge clk or negedge reset_n) begin
    if(!reset_n) begin
      ; address<=0; base_address<=0; local_address<=0; read_byte_rotation<=0; size<=0; length<=0; beat<=0;
      data<=0; mask<=0; response<=0; aw_sent<=0; w_sent<=0;
      read_bytes<=0; write_bytes<=0;
      buffered_write<=0;
    end else begin
      case(state)
        IDLE:begin
          // Private command-start state is prepared before acceptance.
          // Only unqualified result/beat payload can differ while IDLE;
          // ready/valid, lease revocation and accepted AXI state are unchanged.
          beat<=0;
          response<=accepted_legal ? 0 : 3;
          if(command_valid && command_ready) begin
          address<=command_address; base_address<=command_address; local_address<=command_scratch;
          read_byte_rotation<=command_address[3:0]-command_scratch[3:0];
          size<=command_size; length<=command_len;
          data<=command_data; mask<=command_mask; aw_sent<=0; w_sent<=0;
          buffered_write<=source_write;
          ;
          end
        end
        WRITE_PREFETCH:;
        WRITE_CAPTURE:begin
          if(beat==length)begin beat<=0;;end
          else begin beat<=beat+1'b1;local_address<=local_address+16;;end
        end
        READ_ADDR:if(bus.arready);
        READ_DATA:if(bus.rvalid) begin
          // RLAST is checked against LEN and never used to abandon later beats.
          if(bus.rresp!=0 || bus.rid!=0 || bus.rlast!=(beat==length))
            response<=bus.rresp!=0 ? bus.rresp : 2;
          read_bytes<=read_bytes+(64'd1<<size);
          if(beat==length);
          else begin
            beat<=beat+1'b1; address<=address+(32'd1<<size);
            local_address<=local_address+(16'd1<<size);
          end
        end
        WRITE_SEND:begin
          if(bus.awvalid&&bus.awready)aw_sent<=1;
          if(bus.wvalid&&bus.wready)begin
            if(beat==length)w_sent<=1;
            else beat<=beat+1'b1;
          end
          if((aw_sent||(bus.awvalid&&bus.awready))&&
             (w_sent||(bus.wvalid&&bus.wready&&beat==length)));
        end
        WRITE_RESP:if(bus.bvalid) begin
          response<=bus.bid!=0 ? 2 : bus.bresp;
          if(bus.bresp==0&&bus.bid==0)
            write_bytes<=write_bytes+(buffered_write ? ((64'(length)+1)<<4) : 64'($countones(mask)));
          ;
        end
        RESULT:if(result_ready);
        default:;
      endcase
    end
  end
  // Original state transition priority; all predicates use original old state.
  state_t state_next;
  always_comb begin
    case(state)
      IDLE:begin
        if(command_valid && command_ready)begin
          state_next=!accepted_legal ? RESULT : (command_write ? (source_write ? WRITE_PREFETCH : WRITE_SEND) : READ_ADDR);
        end else begin
          state_next=state;
        end
      end
      WRITE_PREFETCH:begin
        state_next=WRITE_CAPTURE;
      end
      WRITE_CAPTURE:begin
        if(beat==length)begin
          state_next=WRITE_SEND;
        end else begin
          state_next=WRITE_PREFETCH;
        end
      end
      READ_ADDR:begin
        if(bus.arready)begin
          state_next=READ_DATA;
        end else begin
          state_next=state;
        end
      end
      READ_DATA:begin
        if(bus.rvalid)begin
          if(beat==length)begin
            state_next=RESULT;
          end else begin
            state_next=state;
          end
        end else begin
          state_next=state;
        end
      end
      WRITE_SEND:begin
        if((aw_sent||(bus.awvalid&&bus.awready))&&
             (w_sent||(bus.wvalid&&bus.wready&&beat==length)))begin
          state_next=WRITE_RESP;
        end else begin
          state_next=state;
        end
      end
      WRITE_RESP:begin
        if(bus.bvalid)begin
          state_next=RESULT;
        end else begin
          state_next=state;
        end
      end
      RESULT:begin
        if(result_ready)begin
          state_next=IDLE;
        end else begin
          state_next=state;
        end
      end
      default:begin
        state_next=IDLE;
      end
    endcase
  end
  always_ff @(posedge clk or negedge reset_n)begin
    if(!reset_n)state<=IDLE;
    else state<=state_next;
  end

endmodule
