// Receive-only host protocol: 52 payload bytes followed by IEEE CRC32.
// Payload is little endian: "D2R1", sequence, flags, errors, write beats,
// read beats, AW count, AR count, maximum AW/AR address, init-write passes,
// and the 64-bit core-cycle counter. All sources share the core clock.
module ddr_telemetry_uart #(
  parameter BIT_TICKS = 814, // nominal 93.75 MHz / 115200
  parameter FRAME_GAP = 18750000
)(
  input clk, input rst_n,
  input [31:0] flags, errors, write_beats, read_beats,
  input [31:0] aw_count, ar_count, max_awaddr, max_araddr, init_passes,
  output uart_txd
);
  reg [63:0] core_cycles;
  reg [31:0] sequence_number, gap, crc;
  reg [447:0] frame;
  reg [9:0] shift_reg;
  reg [15:0] bit_ticks;
  reg [5:0] byte_index;
  reg [3:0] bit_index;
  reg [1:0] state;
  localparam WAIT_FRAME=0, PREP_BYTE=1, SEND_BYTE=2;
  assign uart_txd=shift_reg[0];
  function [31:0] crc_byte;
    input [31:0] previous;
    input [7:0] data;
    reg [31:0] c;
    integer k;
    begin
      c=previous ^ {24'b0,data};
      for(k=0;k<8;k=k+1)
        c=c[0] ? (c>>1)^32'hedb88320 : c>>1;
      crc_byte=c;
    end
  endfunction
  always @(posedge clk or negedge rst_n) begin
    if(!rst_n) begin
      core_cycles<=0; sequence_number<=0; gap<=0; crc<=32'hffffffff;
      frame<=0; shift_reg<=10'h3ff; bit_ticks<=0;
      byte_index<=0; bit_index<=0; state<=WAIT_FRAME;
    end else begin
      core_cycles<=core_cycles+1'b1;
      case(state)
        WAIT_FRAME: begin
          if(gap==0) begin
            frame<={32'b0,core_cycles,init_passes,max_araddr,max_awaddr,
                    ar_count,aw_count,read_beats,write_beats,errors,flags,
                    sequence_number,32'h31523244};
            sequence_number<=sequence_number+1'b1;
            crc<=32'hffffffff; byte_index<=0; state<=PREP_BYTE;
          end else gap<=gap-1'b1;
        end
        PREP_BYTE: begin
          shift_reg<={1'b1,frame[byte_index*8+:8],1'b0};
          if(byte_index<52) crc<=crc_byte(crc,frame[byte_index*8+:8]);
          bit_ticks<=0; bit_index<=0; state<=SEND_BYTE;
        end
        SEND_BYTE: begin
          if(bit_ticks==BIT_TICKS-1) begin
            bit_ticks<=0; shift_reg<={1'b1,shift_reg[9:1]};
            if(bit_index==9) begin
              if(byte_index==55) begin gap<=FRAME_GAP-1; state<=WAIT_FRAME; end
              else begin
                if(byte_index==51) frame[447:416]<=~crc;
                byte_index<=byte_index+1'b1; state<=PREP_BYTE;
              end
            end else bit_index<=bit_index+1'b1;
          end else bit_ticks<=bit_ticks+1'b1;
        end
        default: state<=WAIT_FRAME;
      endcase
    end
  end
endmodule
