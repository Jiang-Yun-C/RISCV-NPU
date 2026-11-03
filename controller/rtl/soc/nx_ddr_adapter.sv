// AXI4 byte-addressed slave to the native HMIC1.10 simplified 256-bit port.
// One accepted AXI transaction at a time; vendor ID is always zero. All write
// data is buffered before issuing AW because the vendor has no WVALID. All
// read data is buffered because it has no RREADY. B OKAY requires masked
// readback after a conservative drain. Physical qualification is separate.
module nx_ddr_adapter #(
  parameter DATA_W=128, ID_W=6,
  parameter WRITE_DRAIN_CYCLES=1024, STALL_LIMIT=125000000
)(
  input wire clk, rst_n, ddr_init_done,
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
  output reg fault,
  output reg [3:0] fault_reason,
  output reg [63:0] cycles, write_payload_bytes, read_payload_bytes,
  output reg [63:0] native_write_bytes, native_read_bytes
);
  localparam BUS_BYTES=DATA_W/8;
  localparam [3:0] IDLE=4'd0, CLEAR=4'd1, COLLECT=4'd2, PLAN=4'd3, AW=4'd4, WRITE=4'd5,
             DRAIN=4'd6, AR=4'd7, READ=4'd8, B=4'd9, R=4'd10;
  reg [3:0] state;
  reg is_write, favor_write;
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
  reg [255:0] packed_write, expanded_mask, buffer_write_data;
  reg [31:0] packed_mask, buffer_write_mask;
  reg [6:0] buffer_write_address;
  reg data_write_enable, mask_write_enable;

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

  assign s_awready=rst_n && state==IDLE && ddr_init_done && !fault &&
                   (!s_arvalid || favor_write);
  assign s_arready=rst_n && state==IDLE && ddr_init_done && !fault &&
                   (!s_awvalid || !favor_write);
  assign s_wready=rst_n && state==COLLECT;
  assign s_bid=identity; assign s_rid=identity;
  assign s_bresp=response; assign s_rresp=response;
  assign s_bvalid=rst_n && state==B;
  assign s_rvalid=rst_n && state==R;
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

  always @* begin
    s_rdata=0; bad_strobe=0; read_mismatch=0;
    step=1<<size;
    offset=cursor & (BUS_BYTES-1);
    index=(cursor-line_base)>>5;
    for(lane=0; lane<BUS_BYTES; lane=lane+1) begin
      if(s_wstrb[lane] && (lane<offset || lane>=offset+step)) bad_strobe=1;
      if(response==0 && lane>=offset && lane<offset+step && index<128)
        s_rdata[lane*8+:8]=data_buffer[index][((cursor & 31)+lane-offset)*8+:8];
    end
    for(lane=0; lane<32; lane=lane+1)
      if(mask_buffer[line_index+chunk_beat][lane] &&
         d_rdata[lane*8+:8]!=data_buffer[line_index+chunk_beat][lane*8+:8])
        read_mismatch=1;
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
  end

  always @(posedge clk or negedge rst_n) begin
    if(!rst_n) begin
      state<=IDLE; fault<=0; fault_reason<=0; favor_write<=1;
      address<=0; cursor<=0; line_base<=0; identity<=0; length<=0; size<=0;
      response<=0; is_write<=0; axi_beat<=0; line_count<=0; clear_line<=0;
      line_index<=0; chunk_count<=1; chunk_beat<=0; stalled<=0; drain_left<=0;
      cycles<=0; write_payload_bytes<=0; read_payload_bytes<=0;
      native_write_bytes<=0; native_read_bytes<=0;
      transaction_bytes<=0;
    end else begin
      cycles<=cycles+1'b1;
      if((state==AW && !d_awready) || (state==WRITE && !d_wready) ||
         (state==AR && !d_arready) || (state==READ && !d_rvalid))
        stalled<=stalled+1'b1;
      else stalled<=0;
      // Never change an already offered B/R response during backpressure.
      if(state!=IDLE && state!=COLLECT && state!=B && state!=R &&
         (!ddr_init_done || stalled>=STALL_LIMIT)) begin
        fault<=1; fault_reason<=!ddr_init_done ? 1 : 2;
        response<=2'b10; axi_beat<=0; cursor<=address;
        // Drain an already accepted AXI write without side effects.
        if(is_write && state==CLEAR) state<=COLLECT;
        else state<=is_write ? B : R;
      end else case(state)
        IDLE: begin
          if(s_awvalid && s_awready) begin
            address<=s_awaddr; cursor<=s_awaddr; line_base<={s_awaddr[31:5],5'd0};
            identity<=s_awid; length<=s_awlen; size<=s_awsize;
            is_write<=1; favor_write<=0; axi_beat<=0; clear_line<=0;
            transaction_bytes<=0;
            line_index<=0;
            line_count<=9'(((s_awaddr&31)+(({1'b0,s_awlen}+9'd1)<<s_awsize)+31)>>5);
            response<=descriptor_ok(s_awaddr,s_awlen,s_awsize,s_awburst) ? 0 : 3;
            state<=descriptor_ok(s_awaddr,s_awlen,s_awsize,s_awburst) ? CLEAR : COLLECT;
          end else if(s_arvalid && s_arready) begin
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
            fault<=1; fault_reason<=3; response<=2'b10; state<=B;
          end else if(chunk_beat+1==chunk_count) begin
            drain_left<=WRITE_DRAIN_CYCLES; state<=DRAIN;
          end else chunk_beat<=chunk_beat+1'b1;
        end
        DRAIN: if(drain_left!=0) drain_left<=drain_left-1'b1;
          else begin chunk_beat<=0; state<=AR; end
        AR: if(d_arready) state<=READ;
        READ: if(d_rvalid) begin
          native_read_bytes<=native_read_bytes+32;
          if(d_rid!=0 || d_rlast!=(chunk_beat+1==chunk_count) ||
             (is_write && read_mismatch)) begin
            fault<=1; fault_reason<=d_rid!=0 ? 4 :
              (d_rlast!=(chunk_beat+1==chunk_count) ? 5 : 6);
            response<=2'b10; axi_beat<=0; cursor<=address;
            state<=is_write ? B : R;
          end else begin
            if(chunk_beat+1==chunk_count) begin
              if(line_index+chunk_count==line_count) begin
                axi_beat<=0; cursor<=address; state<=is_write ? B : R;
              end else begin line_index<=line_index+chunk_count; state<=PLAN; end
            end else chunk_beat<=chunk_beat+1'b1;
          end
        end
        B: if(s_bready) begin
          if(response==0) write_payload_bytes<=write_payload_bytes+transaction_bytes;
          state<=IDLE;
        end
        R: if(s_rready) begin
          if(response==0) read_payload_bytes<=read_payload_bytes+(1<<size);
          if(axi_beat=={1'b0,length}) state<=IDLE;
          else begin axi_beat<=axi_beat+1'b1; cursor<=cursor+(1<<size); end
        end
        default: state<=IDLE;
      endcase
      if((state==B || state==R) && !ddr_init_done) begin
        fault<=1; fault_reason<=1;
      end
      if(state==COLLECT && !ddr_init_done) begin
        fault<=1; fault_reason<=1; response<=2'b10;
      end
    end
  end
endmodule
