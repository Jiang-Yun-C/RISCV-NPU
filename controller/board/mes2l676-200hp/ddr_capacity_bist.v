// One outstanding burst; hardware/test state resides outside the tested DDR.
// HMIC1.3 simplified user port: LEN+1 beats, 256-bit data, 4-byte word address.
// Full write/read address patterns detect address aliasing. Afterwards each
// of the 32 byte strobes is tested by selective write and independent readback.
module ddr_capacity_bist #(
  parameter MEM_SPACE_AW=28,
  parameter WRITE_DRAIN_CYCLES=1024,
  parameter STALL_LIMIT=187500000
)(
  input clk, rst_n, ddr_init_done,
  output [27:0] axi_awaddr, axi_araddr,
  output [3:0] axi_awlen, axi_arlen,
  output axi_awvalid, axi_arvalid,
  input axi_awready, axi_arready,
  output [255:0] axi_wdata,
  output [31:0] axi_wstrb,
  input axi_wready, axi_wlast,
  input [255:0] axi_rdata,
  input axi_rvalid, axi_rlast,
  input [3:0] axi_rid,
  output reg [31:0] errors, verified_passes,
  output reg [31:0] first_error_word_address,
  output reg full_range_verified, byte_masks_verified,
  output [31:0] phase_status,
  output failed
);
  localparam WAIT_DDR=0, AW=1, W=2, DRAIN=3, AR=4, R=5, FAIL=6;
  localparam WRITE_ALL=0, READ_ALL=1, WRITE_MASK=2, READ_MASK=3;
  localparam [28:0] CAPACITY_WORDS=29'd1 << MEM_SPACE_AW;
  reg [2:0] state;
  reg [1:0] phase;
  reg [27:0] address;
  reg [3:0] beat;
  reg [4:0] mask_index;
  reg [31:0] seed, drain_left, stalled;
  reg [255:0] write_pattern, expected_read;
  integer lane, byte_lane;
  reg [31:0] word_address;
  reg [31:0] bad_word;
  reg mismatch;
  wire mask_phase=(phase==WRITE_MASK || phase==READ_MASK);
  wire [3:0] last_beat=mask_phase ? 4'd0 : 4'd15;
  wire final_address=({1'b0,address}+29'd128==CAPACITY_WORDS);
  assign axi_awaddr=mask_phase ? 28'd0 : address;
  assign axi_araddr=mask_phase ? 28'd0 : address;
  assign axi_awlen=mask_phase ? 4'd0 : 4'd15;
  assign axi_arlen=mask_phase ? 4'd0 : 4'd15;
  assign axi_awvalid=(state==AW);
  assign axi_arvalid=(state==AR);
  assign axi_wstrb=phase==WRITE_MASK ? (32'd1 << mask_index) : 32'hffffffff;
  assign axi_wdata=write_pattern;
  assign failed=(state==FAIL);
  assign phase_status={seed[31],21'd0,mask_index,phase,state};
  always @* begin
    write_pattern=0; expected_read=0; mismatch=0; bad_word=0;
    for(lane=0;lane<8;lane=lane+1) begin
      word_address=(mask_phase ? 32'd0 : {4'd0,address})+{25'd0,beat,3'd0}+lane;
      write_pattern[lane*32+:32]=word_address ^ seed;
      expected_read[lane*32+:32]=word_address ^ seed;
    end
    if(phase==WRITE_MASK) write_pattern=~write_pattern;
    if(phase==READ_MASK)
      for(byte_lane=0;byte_lane<32;byte_lane=byte_lane+1)
        if(byte_lane<=mask_index)
          expected_read[byte_lane*8+:8]=~expected_read[byte_lane*8+:8];
    // Preserve the lowest mismatching physical word for diagnosis.
    for(lane=7;lane>=0;lane=lane-1)
      if(axi_rdata[lane*32+:32]!=expected_read[lane*32+:32]) begin
        mismatch=1;
        bad_word=(mask_phase ? 32'd0 : {4'd0,address})+{25'd0,beat,3'd0}+lane;
      end
  end
  always @(posedge clk or negedge rst_n) begin
    if(!rst_n) begin
      state<=WAIT_DDR; phase<=WRITE_ALL; address<=0; beat<=0; mask_index<=0;
      seed<=32'ha5a55a5a; drain_left<=0; stalled<=0;
      errors<=0; verified_passes<=0; first_error_word_address<=0;
      full_range_verified<=0; byte_masks_verified<=0;
    end else begin
      if(state==WAIT_DDR || state==DRAIN || state==FAIL ||
         (state==AW && axi_awready) || (state==W && axi_wready) ||
         (state==AR && axi_arready) || (state==R && axi_rvalid)) stalled<=0;
      else stalled<=stalled+1'b1;
      if(state!=WAIT_DDR && state!=FAIL && !ddr_init_done) begin
        errors<=errors+1'b1; first_error_word_address<={4'd0,address}; state<=FAIL;
      end else if(state!=WAIT_DDR && state!=FAIL && stalled==STALL_LIMIT) begin
        errors<=errors+1'b1; first_error_word_address<={4'd0,address}; state<=FAIL;
      end else case(state)
        WAIT_DDR: if(ddr_init_done) state<=AW;
        AW: if(axi_awready) begin beat<=0; state<=W; end
        W: if(axi_wready) begin
          if(axi_wlast!=(beat==last_beat)) begin
            errors<=errors+1'b1; first_error_word_address<={4'd0,address}; state<=FAIL;
          end else if(beat==last_beat) begin
            drain_left<=WRITE_DRAIN_CYCLES; beat<=0; state<=DRAIN;
          end else beat<=beat+1'b1;
        end
        DRAIN: if(drain_left!=0) drain_left<=drain_left-1'b1;
        else if(phase==WRITE_MASK) begin phase<=READ_MASK; state<=AR; end
        else if(final_address) begin phase<=READ_ALL; address<=0; state<=AR; end
        else begin address<=address+28'd128; state<=AW; end
        AR: if(axi_arready) begin beat<=0; state<=R; end
        R: if(axi_rvalid) begin
          if(mismatch || axi_rid!=0 || axi_rlast!=(beat==last_beat)) begin
            errors<=errors+1'b1; first_error_word_address<=mismatch ? bad_word : {4'd0,address}; state<=FAIL;
          end else if(beat!=last_beat) beat<=beat+1'b1;
          else begin
            beat<=0;
            if(phase==READ_ALL) begin
              if(final_address) begin
                full_range_verified<=1; phase<=WRITE_MASK; address<=0; mask_index<=0; state<=AW;
              end else begin address<=address+28'd128; state<=AR; end
            end else if(mask_index!=31) begin
              mask_index<=mask_index+1'b1; phase<=WRITE_MASK; state<=AW;
            end else begin
              byte_masks_verified<=1; verified_passes<=verified_passes+1'b1;
              seed<=~seed; address<=0; mask_index<=0; phase<=WRITE_ALL; state<=AW;
            end
          end
        end
        FAIL: state<=FAIL;
        default: begin errors<=errors+1'b1; state<=FAIL; end
      endcase
    end
  end
endmodule
