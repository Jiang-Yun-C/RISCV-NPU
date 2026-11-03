// Hardware workload/checker outside DDR; all traffic traverses nx_ddr_adapter.
// Address and complement sweeps detect high-bit aliasing before masks and
// sustained workloads. CPU/Coral competition is a separate T24 qualification.
module ce64_axi_bist #(
  parameter WINDOW_BITS=30,
  parameter BASE_ADDRESS=32'h80000000,
  parameter BANDWIDTH_CYCLES=64'd3125000000,
  parameter STALL_LIMIT=250000000
)(
  input clk,rst_n,ddr_init_done,fault,enable,
  output stopped,
  output [31:0] s_awaddr,s_araddr,
  output [5:0] s_awid,s_arid,
  output [7:0] s_awlen,s_arlen,
  output [2:0] s_awsize,s_arsize,
  output [1:0] s_awburst,s_arburst,
  output s_awvalid,s_arvalid,s_wvalid,s_wlast,s_bready,s_rready,
  output reg [127:0] s_wdata,
  output [15:0] s_wstrb,
  input s_awready,s_arready,s_wready,s_bvalid,s_rvalid,s_rlast,
  input [5:0] s_bid,s_rid,
  input [1:0] s_bresp,s_rresp,
  input [127:0] s_rdata,
  output reg [31:0] errors,verified_passes,first_error_word_address,
  output reg full_range_verified,byte_masks_verified,
  output failed,
  output [31:0] phase_status,debug_address,debug_stalled,debug_reason,
  output [255:0] debug_expected,
  output [3:0] debug_beat,
  output reg [31:0] workload,
  output reg [63:0] workload_cycles
);
  localparam WAIT=0,AW=1,W=2,B=3,AR=4,R=5,FAIL=6,R_CHECK=7,HOLD=8;
  localparam WRITE_ALL=0,READ_ALL=1,WRITE_MASK=2,READ_MASK=3,RESTORE=4;
  localparam [30:0] CAPACITY=31'd1<<WINDOW_BITS;
  reg [3:0] state;reg [2:0] phase;
  reg [29:0] offset;
  reg [7:0] beat;
  reg [4:0] mask_index;
  reg seed_phase;
  wire [31:0] seed=32'ha5a55a5a^{32{seed_phase}};
  reg [31:0] stalled,reason;
  reg [127:0] expected;
  // Capture byte comparisons on the original accepted-read edge.  The
  // existing R_CHECK cycle combines them into the same per-word predicate.
  reg [15:0] read_byte_match;
  wire [3:0] read_word_match;
  genvar read_word;
  generate for(read_word=0;read_word<4;read_word=read_word+1) begin : read_match_word
    assign read_word_match[read_word]=&read_byte_match[read_word*4+:4];
  end endgenerate
  reg read_protocol_match;
  integer lane,j,read_byte;
  reg [31:0] word_address;
  wire masking=phase==WRITE_MASK || phase==READ_MASK;
  wire [7:0] last_beat=phase==WRITE_MASK ? 8'd0 : (phase==READ_MASK || phase==RESTORE) ? 8'd1 :
                             workload==4 ? 8'd0 : workload==5 ? 8'd15 : 8'd31;
  wire [12:0] transfer_bytes=({5'd0,last_beat}+13'd1)<<4;
  wire final_address={1'b0,offset}+transfer_bytes==CAPACITY;
  wire [29:0] selected_offset=phase==READ_MASK ? 30'd0 : masking ? {25'd0,mask_index[4],4'd0} : offset;
  wire progress=(state==AW&&s_awready)||(state==W&&s_wready)||
                (state==B&&s_bvalid)||(state==AR&&s_arready)||(state==R&&s_rvalid)||state==R_CHECK;
  assign s_awaddr=BASE_ADDRESS+selected_offset;
  assign s_araddr=s_awaddr;
  assign s_awid=6'd61; assign s_arid=6'd43;
  assign s_awlen=last_beat; assign s_arlen=last_beat;
  assign s_awsize=4; assign s_arsize=4;
  assign s_awburst=1; assign s_arburst=1;
  assign s_awvalid=state==AW; assign s_arvalid=state==AR;
  assign s_wvalid=state==W; assign s_wlast=beat==last_beat;
  assign s_wstrb=phase==WRITE_MASK ? (16'd1<<mask_index[3:0]) : 16'hffff;
  assign s_bready=state==B; assign s_rready=state==R;
  assign failed=state==FAIL;
  assign stopped=state==HOLD;
  assign phase_status={seed[31],19'd0,mask_index,phase,state};
  assign debug_address={2'd0,selected_offset}>>2;
  assign debug_stalled=stalled; assign debug_reason=reason;
  assign debug_beat=beat[3:0]; assign debug_expected={128'd0,expected};
  always @* begin
    s_wdata=0; expected=0; word_address=0;
    for(lane=0;lane<4;lane=lane+1) begin
      word_address=({2'd0,selected_offset}>>2)+{22'd0,beat,2'd0}+lane;
      s_wdata[lane*32+:32]=word_address^seed;
      expected[lane*32+:32]=word_address^seed;
    end
    if(phase==WRITE_MASK) s_wdata=~s_wdata;
    if(phase==READ_MASK)
      for(j=0;j<16;j=j+1)
        if(beat*16+j<=mask_index)
          expected[j*8+:8]=~expected[j*8+:8];
  end
  // Advance workloads only between complete transactions. A mode is exposed
  // for at least 25 physical seconds, with 64-bit cycle/payload telemetry.
  task next_workload;
    begin
      offset<=0;beat<=0;workload_cycles<=0;phase<=WRITE_ALL;
      if(workload==6) begin workload<=0;seed_phase<=~seed_phase;state<=AW;end
      else begin
        workload<=workload+1'b1;
        state<=workload==0 ? AR : AW;
      end
    end
  endtask
  always @(posedge clk or negedge rst_n) begin
    if(!rst_n) begin
      state<=WAIT;phase<=WRITE_ALL;offset<=0;beat<=0;mask_index<=0;
      seed_phase<=1'b0;stalled<=0;reason<=0;errors<=0;verified_passes<=0;
      first_error_word_address<=0;full_range_verified<=0;byte_masks_verified<=0;
      workload<=0;workload_cycles<=0;
      read_byte_match<=0;read_protocol_match<=0;
    end else begin
      if(workload!=0) workload_cycles<=workload_cycles+1'b1;
      if(state==WAIT || state==FAIL || state==HOLD || progress) stalled<=0;
      else stalled<=stalled+1'b1;
      if(state!=WAIT && state!=FAIL && state!=HOLD && (!ddr_init_done || fault || stalled>=STALL_LIMIT)) begin
        state<=FAIL;errors<=errors+1'b1;first_error_word_address<=debug_address;
        reason<=!ddr_init_done ? 1 : fault ? 2 : 3;
      end else case(state)
        WAIT: if(ddr_init_done && enable) state<=AW;
        HOLD: if(enable)state<=WAIT;
        AW: if(s_awready) begin beat<=0;state<=W;end
        W: if(s_wready) begin
          if(beat==last_beat) begin beat<=0;state<=B;end
          else beat<=beat+1'b1;
        end
        B: if(s_bvalid) begin
          if(s_bresp!=0 || s_bid!=61) begin
            state<=FAIL;errors<=errors+1'b1;reason<=4;first_error_word_address<=debug_address;
          end else if(!enable)state<=HOLD;
          else if(phase==WRITE_MASK) begin phase<=READ_MASK;state<=AR;end
          else if(phase==RESTORE) begin next_workload;end
          else if(workload>=3) state<=AR;
          else if(workload==2 && workload_cycles>=BANDWIDTH_CYCLES) next_workload;
          else if(final_address) begin
            offset<=0;
            if(workload==0) begin phase<=READ_ALL;state<=AR;end
            else state<=AW;
          end else begin offset<=offset+transfer_bytes;state<=AW;end
        end
        AR: if(s_arready) begin beat<=0;state<=R;end
        R: if(s_rvalid) begin
          // Keep the accepted beat/address stable and compare bytes in
          // parallel before the original R_CHECK error decision.
          for(read_byte=0;read_byte<16;read_byte=read_byte+1)
            read_byte_match[read_byte]<=s_rdata[read_byte*8+:8]==expected[read_byte*8+:8];
          read_protocol_match<=s_rresp==0 && s_rid==43 && s_rlast==(beat==last_beat);
          state<=R_CHECK;
        end
        R_CHECK: begin
          if(!(&read_word_match) || !read_protocol_match) begin
            state<=FAIL;errors<=errors+1'b1;reason<=5;
            first_error_word_address<=debug_address+{22'd0,beat,2'd0};
          end else if(beat!=last_beat) begin beat<=beat+1'b1;state<=R;end
          else if(!enable)state<=HOLD;
          else begin
            beat<=0;
            if(phase==READ_MASK) begin
              if(mask_index==31) begin
                byte_masks_verified<=1;verified_passes<=verified_passes+1'b1;
                phase<=RESTORE;offset<=0;state<=AW;
              end else begin mask_index<=mask_index+1'b1;phase<=WRITE_MASK;state<=AW;end
            end else if(workload!=0 && workload_cycles>=BANDWIDTH_CYCLES) next_workload;
            else if(workload>=3) begin
              offset<=final_address ? 30'd0 : offset+transfer_bytes;state<=AW;
            end else if(final_address) begin
              offset<=0;
              if(workload==0) begin
                full_range_verified<=1;mask_index<=0;phase<=WRITE_MASK;state<=AW;
              end else state<=AR;
            end else begin offset<=offset+transfer_bytes;state<=AR;end
          end
        end
        FAIL: state<=FAIL;
        default: begin state<=FAIL;errors<=errors+1'b1;reason<=6;end
      endcase
    end
  end
endmodule
