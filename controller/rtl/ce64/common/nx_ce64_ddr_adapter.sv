// CE-private derivative: quarantine/drain require platform recovery.
// rst_n is platform reset only; never connect CE soft reset.
// AXI4 byte-addressed slave to the native HMIC1.10 simplified 256-bit port.
// One accepted AXI transaction at a time; vendor ID is always zero. All write
// data is buffered before issuing AW because the vendor has no WVALID. All
// read data is buffered because it has no RREADY. Qualified W captures may
// return committed buffer lines while later native lines arrive; the complete
// native LEN and its checks still precede LAST. B OKAY requires masked
// readback after a conservative drain. Physical qualification is separate.
module nx_ce64_ddr_adapter #(
  parameter DATA_W=128, ID_W=6,
  parameter WRITE_DRAIN_CYCLES=1024, STALL_LIMIT=125000000,
  parameter bit W_READ_OVERLAP=0
)(
  input wire clk, rst_n, ddr_init_done,
  // Real accepted W-capture context, qualified by both fabric selections.
  // This permission is sampled only with AXI AR; ordinary reads stay legacy.
  input wire s_capture_read,
  input wire [31:0] s_awaddr, s_araddr,
  input wire [ID_W-1:0] s_awid, s_arid,
  input wire [7:0] s_awlen, s_arlen,
  input wire [2:0] s_awsize, s_arsize,
  input wire [1:0] s_awburst, s_arburst,
  input wire s_awvalid, s_arvalid,
  output wire s_awready, s_arready,
  input wire [DATA_W-1:0] s_wdata,
  input wire [DATA_W/8-1:0] s_wstrb,
  input wire s_wvalid, s_wlast,
  output wire s_wready,
  output wire [ID_W-1:0] s_bid, s_rid,
  output wire [1:0] s_bresp, s_rresp,
  output wire s_bvalid, s_rvalid, s_rlast,
  input wire s_bready, s_rready,
  output reg [DATA_W-1:0] s_rdata,
  output wire [27:0] d_awaddr, d_araddr,
  output wire [3:0] d_awid, d_arid, d_awlen, d_arlen,
  output wire d_awvalid, d_arvalid,
  input wire d_awready, d_arready,
  output wire [255:0] d_wdata,
  output wire [31:0] d_wstrb,
  input wire d_wready, d_wlast,
  input wire [255:0] d_rdata,
  input wire [3:0] d_rid,
  input wire d_rvalid, d_rlast,
  output wire native_pending, upstream_pending, safely_drained,
  output reg quarantined,
  output reg fault,
  output reg [3:0] fault_reason,
  output reg [63:0] cycles, write_payload_bytes, read_payload_bytes,
  output reg [63:0] native_write_bytes, native_read_bytes
);
  localparam BUS_BYTES=DATA_W/8;
  localparam [3:0] IDLE=4'd0, CLEAR=4'd1, COLLECT=4'd2, PLAN=4'd3, AW=4'd4, WRITE=4'd5,
             DRAIN=4'd6, AR=4'd7, READ=4'd8, B=4'd9, R=4'd10, VERIFY=4'd11;
  reg [3:0] state;
  reg is_write, favor_write;
  reg calibration_seen;
  reg [31:0] address, cursor, line_base;
  reg [ID_W-1:0] identity;
  reg [7:0] length;
  reg [2:0] size;
  reg [1:0] response;
  reg [8:0] axi_beat, line_count, clear_line, line_index;
  reg [4:0] chunk_count, chunk_beat;
  reg [31:0] drain_left, stalled;
  reg [63:0] transaction_bytes;
  reg [255:0] data_buffer [0:127];
  reg [31:0] mask_buffer [0:127];
  integer lane, pack_lane, enabled_bytes, offset, index, step, boundary, remain;
  reg bad_strobe, read_mismatch;
  reg [31:0] verified_bytes;
  reg verify_valid;
  reg [255:0] packed_write, expanded_mask, buffer_write_data;
  reg [31:0] packed_mask, buffer_write_mask;
  reg [6:0] buffer_write_address;
  reg data_write_enable, mask_write_enable;
  reg capture_stream;
  reg [4:0] received_lines;
  reg stream_rvalid;
  reg [1:0] stream_response;
  wire stream_take=capture_stream && stream_rvalid && s_rready;
  wire stream_last_take=stream_take && axi_beat=={1'b0,length};
  // A consumed beat may refill the offered slot on the same edge. There is
  // no native-data bypass: received_lines describes earlier committed writes.
  wire [8:0] next_stream_beat=axi_beat+(stream_take ? 9'd1 : 9'd0);
  // Eligible reads start on a native-line boundary, with two AXI beats/line.
  // Use the beat index, without a new 32-bit address subtract on the ready path.
  wire stream_line_ready=next_stream_beat[8:1]<{3'b0,received_lines};
  wire [1:0] visible_read_response=capture_stream ? stream_response : response;
  wire current_native_read_error=state==READ && d_rvalid &&
    (d_rid!=0 || d_rlast!=(chunk_beat+1==chunk_count));
  wire current_transport_fault=(calibration_seen && !ddr_init_done) ||
    (native_pending && stalled>=$unsigned(STALL_LIMIT)) || (state!=READ && d_rvalid) ||
    current_native_read_error;

  function automatic descriptor_ok(input [31:0] a, input [7:0] len,
                                    input [2:0] sz, input [1:0] burst);
    reg [32:0] ending;
    begin
      ending={1'b0,a}+(({25'd0,len}+33'd1)<<sz);
      descriptor_ok=burst==2'b01 && sz<=$clog2(BUS_BYTES) &&
        (a & ((32'd1<<sz)-1))==0 && a>=32'h80000000 &&
        ending<=33'h0c0000000 && ending>{1'b0,a} &&
        ((ending-1)>>12)==({1'b0,a}>>12);
    end
  endfunction

  assign native_pending=(state==AW || state==WRITE || state==DRAIN || state==AR || state==READ);
  assign upstream_pending=state!=IDLE;
  assign safely_drained=state==IDLE && !quarantined;
  assign s_awready=rst_n && state==IDLE && ddr_init_done && !fault && !quarantined &&
                   (!s_arvalid || favor_write);
  assign s_arready=rst_n && state==IDLE && ddr_init_done && !fault && !quarantined &&
                   (!s_awvalid || !favor_write);
  assign s_wready=rst_n && state==COLLECT;
  assign s_bid=identity; assign s_rid=identity;
  assign s_bresp=response; assign s_rresp=visible_read_response;
  assign s_bvalid=rst_n && state==B;
  assign s_rvalid=rst_n && (capture_stream ? stream_rvalid : state==R);
  assign s_rlast=axi_beat=={1'b0,length};
  // Aligned byte address -> 4-byte native word address; the base is removed.
  assign d_awaddr=28'((line_base-32'h80000000+line_index*32)>>2);
  assign d_araddr=d_awaddr;
  assign d_awid=0; assign d_arid=0;
  assign d_awlen=chunk_count-1'b1; assign d_arlen=d_awlen;
  assign d_awvalid=rst_n && state==AW;
  assign d_arvalid=rst_n && state==AR;
  assign d_wdata=data_buffer[line_index+chunk_beat];
  assign d_wstrb=mask_buffer[line_index+chunk_beat];

  // Exact modulo-2^32 read index, with range detection independent of a
  // full-width subtraction. The low borrow chooses already computed high
  // equality/successor predicates; it never ripples through the high word.
  wire read_index_known=((cursor^cursor)===32'b0)&&((line_base^line_base)===32'b0);
  wire [12:0] read_low_delta={1'b0,cursor[11:0]}-{1'b0,line_base[11:0]};
  wire [4:0] read_high_equal,read_high_successor;
  generate for(genvar n=0;n<5;n++)begin:read_index_high_match
    wire carry;
    wire [3:0] successor;
    if(n==0)assign carry=1'b1;
    else assign carry=&line_base[12+:4*n];
    assign successor=line_base[12+4*n+:4]+4'(carry);
    assign read_high_equal[n]=cursor[12+4*n+:4]==line_base[12+4*n+:4];
    assign read_high_successor[n]=cursor[12+4*n+:4]==successor;
  end endgenerate
  wire read_range_fast=read_low_delta[12] ? (&read_high_successor) : (&read_high_equal);
  wire [31:0] read_legacy_delta=cursor-line_base;
  // Unknown payload addresses retain the original four-state arithmetic.
  // No descriptor-validity premise and no guard removal are used here.
  wire [31:0] read_buffer_index=read_index_known ? {25'b0,read_low_delta[11:5]} :
      (read_legacy_delta>>5);
  wire read_buffer_index_ok=read_index_known ? read_range_fast :
      ((read_legacy_delta>>5)<32'd128);

  always @* begin
    s_rdata=0; bad_strobe=0; read_mismatch=verify_valid && !(&verified_bytes);
    step=1<<size;
    offset=cursor & (BUS_BYTES-1);
    index=(cursor-line_base)>>5;
    for(lane=0; lane<BUS_BYTES; lane=lane+1) begin
      if(s_wstrb[lane] && (lane<offset || lane>=offset+step)) bad_strobe=1;
      if(visible_read_response==0 && lane>=offset && lane<offset+step && read_buffer_index_ok)
        s_rdata[lane*8+:8]=data_buffer[read_buffer_index][((cursor & 31)+lane-offset)*8+:8];
    end
    remain=line_count-line_index;
    boundary=(4096-((line_base+line_index*32)&4095))>>5;
    enabled_bytes=0;
    for(lane=0; lane<BUS_BYTES; lane=lane+1)
      if(s_wstrb[lane]) enabled_bytes=enabled_bytes+1;
  end

  // One complete-word write port per buffer. Do not describe byte updates
  // as many variable-index array writes: rc3 expands those into costly muxes.
  always @* begin
    packed_write=0; expanded_mask=0; packed_mask=0;
    for(pack_lane=0;pack_lane<BUS_BYTES;pack_lane=pack_lane+1)
      if(pack_lane>=offset && pack_lane<offset+step && s_wstrb[pack_lane]) begin
        packed_write[((cursor&31)+pack_lane-offset)*8+:8]=s_wdata[pack_lane*8+:8];
        expanded_mask[((cursor&31)+pack_lane-offset)*8+:8]=8'hff;
        packed_mask[(cursor&31)+pack_lane-offset]=1;
      end
    data_write_enable=0; mask_write_enable=0; buffer_write_address=0;
    buffer_write_data=0; buffer_write_mask=0;
    if(state==CLEAR) begin
      data_write_enable=1; mask_write_enable=1; buffer_write_address=clear_line;
    end else if(state==COLLECT && s_wvalid && response==0 && !bad_strobe) begin
      data_write_enable=1; mask_write_enable=1; buffer_write_address=index;
      buffer_write_data=(data_buffer[index]&~expanded_mask)|packed_write;
      buffer_write_mask=mask_buffer[index]|packed_mask;
    end else if(state==READ && d_rvalid && !is_write) begin
      data_write_enable=1; buffer_write_address=line_index+chunk_beat;
      buffer_write_data=d_rdata;
    end
  end
  always @(posedge clk) begin
    if(rst_n && data_write_enable) data_buffer[buffer_write_address]<=buffer_write_data;
    if(rst_n && mask_write_enable) mask_buffer[buffer_write_address]<=buffer_write_mask;
    // Register each masked byte comparison while consuming every native beat.
    // The next cycle aggregates matches; the final beat remains owned in VERIFY.
    // Native write wait stays exactly 1024, with no native RREADY introduced.
    if(rst_n && state==READ && d_rvalid && is_write)
      for(integer b=0;b<32;b=b+1)
        verified_bytes[b]<=!mask_buffer[line_index+chunk_beat][b] ||
          d_rdata[b*8+:8]==data_buffer[line_index+chunk_beat][b*8+:8];
  end

  always @(posedge clk or negedge rst_n) begin
    if(!rst_n) begin
      state<=IDLE; quarantined<=0; fault<=0; fault_reason<=0; favor_write<=1;calibration_seen<=0;
      address<=0; cursor<=0; line_base<=0; identity<=0; length<=0; size<=0;
      response<=0; is_write<=0; axi_beat<=0; line_count<=0; clear_line<=0;
      line_index<=0; chunk_count<=1; chunk_beat<=0; stalled<=0; drain_left<=0;
      cycles<=0; write_payload_bytes<=0; read_payload_bytes<=0;
      native_write_bytes<=0; native_read_bytes<=0;
      transaction_bytes<=0;
      verify_valid<=0;
      capture_stream<=0;received_lines<=0;stream_rvalid<=0;stream_response<=0;
    end else begin
      verify_valid<=state==READ && d_rvalid && is_write;
      cycles<=cycles+1'b1;
      if(ddr_init_done)calibration_seen<=1;
      if((state==AW && !d_awready) || (state==WRITE && !d_wready) ||
         (state==AR && !d_arready) || (state==READ && !d_rvalid))
        stalled<=stalled+1'b1;
      else stalled<=0;
      // Never change an already offered B/R response during backpressure.
      // Platform faults are sticky until a genuine platform reset. A soft CE
      // reset cannot clear this adapter, even after its AXI response is consumed.
      // Keep every offered native address and consume LEN-authorized W/R beats.
      if((calibration_seen && !ddr_init_done) ||
         (native_pending && stalled>=STALL_LIMIT) ||
         (state!=READ && d_rvalid)) begin
        quarantined<=1; fault<=1;
        if(!fault) fault_reason<=!ddr_init_done ? 1 : (d_rvalid ? 7 : 2);
        if(state!=B && state!=R) response<=2'b10;
      end
      if(read_mismatch)begin
        quarantined<=1;fault<=1;if(!fault)fault_reason<=6;response<=2'b10;
      end
      case(state)
        IDLE: begin
          if(s_awvalid && s_awready) begin
            capture_stream<=0;received_lines<=0;stream_rvalid<=0;
            address<=s_awaddr; cursor<=s_awaddr; line_base<={s_awaddr[31:5],5'd0};
            identity<=s_awid; length<=s_awlen; size<=s_awsize;
            is_write<=1; favor_write<=0; axi_beat<=0; clear_line<=0;
            transaction_bytes<=0;
            line_index<=0;
            line_count<=9'(((s_awaddr&31)+(({1'b0,s_awlen}+9'd1)<<s_awsize)+31)>>5);
            response<=descriptor_ok(s_awaddr,s_awlen,s_awsize,s_awburst) ? 0 : 3;
            state<=descriptor_ok(s_awaddr,s_awlen,s_awsize,s_awburst) ? CLEAR : COLLECT;
          end else if(s_arvalid && s_arready) begin
            // At most eight native lines, exactly one native chunk. The source
            // qualifier excludes CPU, auxiliary, Sw and other noncapture reads.
            capture_stream<=W_READ_OVERLAP && ((DATA_W==128 &&
              s_capture_read && descriptor_ok(s_araddr,s_arlen,s_arsize,s_arburst) &&
              s_arsize==4 && s_araddr[5:0]==0 &&
              (s_arlen==3 || s_arlen==7 || s_arlen==11 || s_arlen==15))===1'b1);
            received_lines<=0;stream_rvalid<=0;stream_response<=0;transaction_bytes<=0;
            address<=s_araddr; cursor<=s_araddr; line_base<={s_araddr[31:5],5'd0};
            identity<=s_arid; length<=s_arlen; size<=s_arsize;
            is_write<=0; favor_write<=1; axi_beat<=0; line_index<=0;
            line_count<=9'(((s_araddr&31)+(({1'b0,s_arlen}+9'd1)<<s_arsize)+31)>>5);
            response<=descriptor_ok(s_araddr,s_arlen,s_arsize,s_arburst) ? 0 : 3;
            state<=descriptor_ok(s_araddr,s_arlen,s_arsize,s_arburst) ? PLAN : R;
          end
        end
        CLEAR: begin
          if(clear_line+1==line_count) state<=COLLECT;
          else clear_line<=clear_line+1'b1;
        end
        COLLECT: if(s_wvalid) begin
          transaction_bytes<=transaction_bytes+enabled_bytes;
          if(s_wlast!=(axi_beat=={1'b0,length}) || bad_strobe) response<=2'b10;
          if(axi_beat=={1'b0,length}) begin
            line_index<=0;
            state<=(response!=0 || fault || !ddr_init_done || bad_strobe || !s_wlast) ? B : PLAN;
          end else begin axi_beat<=axi_beat+1'b1; cursor<=cursor+(1<<size); end
        end
        PLAN: begin
          chunk_count<=5'(boundary<remain && boundary<16 ? boundary : (remain>16 ? 16 : remain));
          chunk_beat<=0; state<=is_write ? AW : AR;
        end
        AW: if(d_awready) state<=WRITE;
        WRITE: if(d_wready) begin
          native_write_bytes<=native_write_bytes+32;
          if(d_wlast!=(chunk_beat+1==chunk_count)) begin
            quarantined<=1; fault<=1; if(!fault) fault_reason<=3; response<=2'b10;
          end
          if(chunk_beat+1==chunk_count) begin
            drain_left<=WRITE_DRAIN_CYCLES; state<=DRAIN;
          end else chunk_beat<=chunk_beat+1'b1;
        end
        DRAIN: if(drain_left!=0) drain_left<=drain_left-1'b1;
          else begin chunk_beat<=0; state<=AR; end
        AR: if(d_arready) state<=READ;
        READ: if(d_rvalid) begin
          native_read_bytes<=native_read_bytes+32;
          if(capture_stream)received_lines<=received_lines+1'b1;
          if(d_rid!=0 || d_rlast!=(chunk_beat+1==chunk_count)) begin
            quarantined<=1; fault<=1;
            if(!fault) fault_reason<=d_rid!=0 ? 4 :
              (d_rlast!=(chunk_beat+1==chunk_count) ? 5 : 6);
            response<=2'b10;
          end
          // RLAST never cancels the remaining native LEN. Stop further chunks
          // after this chunk has genuinely drained; uncertainty stays quarantined.
          if(chunk_beat+1==chunk_count) begin
            if(is_write)state<=VERIFY;
            else if(line_index+chunk_count==line_count || quarantined || fault ||
               d_rid!=0 || !d_rlast) begin
              if(!capture_stream)begin axi_beat<=0; cursor<=address; end
              state<=is_write ? B : R;
            end else begin line_index<=line_index+chunk_count; state<=PLAN; end
          end else chunk_beat<=chunk_beat+1'b1;
        end
        VERIFY:begin
          if(line_index+chunk_count==line_count || quarantined || fault || read_mismatch || !ddr_init_done)begin
            axi_beat<=0;cursor<=address;state<=B;
          end else begin line_index<=line_index+chunk_count;state<=PLAN;end
        end
        B: if(s_bready) begin
          if(response==0) write_payload_bytes<=write_payload_bytes+transaction_bytes;
          state<=IDLE;
        end
        R: if(!capture_stream && s_rready) begin
          if(response==0) read_payload_bytes<=read_payload_bytes+(1<<size);
          if(axi_beat=={1'b0,length}) state<=IDLE;
          else begin axi_beat<=axi_beat+1'b1; cursor<=cursor+(1<<size); end
        end
        default: state<=IDLE;
      endcase
      if(capture_stream)begin
        // Payload is read from an immutable committed line. Holding cursor and
        // this per-offer response freezes the full R tuple on backpressure,
        // even if a later native beat poisons the transaction's response.
        if(!stream_rvalid || s_rready)begin
          stream_rvalid<=0;
          if((state==READ || state==R) && !stream_last_take &&
             next_stream_beat<={1'b0,length} && stream_line_ready &&
             (next_stream_beat!={1'b0,length} || state==R))begin
            stream_rvalid<=1;
            stream_response<=(response!=0 || fault || quarantined || current_transport_fault) ? 2'b10 : 2'b00;
          end
        end
        if(stream_take)begin
          if(axi_beat=={1'b0,length})begin
            // Early OKAY prefixes are not successful transaction payload.
            // Commit their byte count only after a fault-free final retirement.
            if(stream_response==0 && response==0 && !fault && !quarantined && !current_transport_fault)
              read_payload_bytes<=read_payload_bytes+(({56'd0,length}+64'd1)<<size);
            capture_stream<=0;stream_rvalid<=0;state<=IDLE;
          end else begin
            axi_beat<=axi_beat+1'b1;cursor<=cursor+32'd16;
          end
        end
      end
      if((state==B || state==R) && !ddr_init_done) begin
        quarantined<=1; fault<=1; if(!fault) fault_reason<=1;
      end
      if(state==COLLECT && !ddr_init_done) begin
        quarantined<=1; fault<=1; if(!fault) fault_reason<=1; response<=2'b10;
      end
    end
  end
endmodule
