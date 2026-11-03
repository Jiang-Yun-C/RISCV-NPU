// D2P1: one coherent 256-byte snapshot followed by IEEE CRC32, transmit only.
module ddr_phy_uart #(
  parameter BIT_TICKS=814,
  parameter FRAME_GAP=1875000
)(input clk, rst_n, input [2047:0] report, output uart_txd);
  reg [2079:0] frame;
  reg [31:0] seq, gap, crc;
  reg [9:0] shift_reg;
  reg [15:0] ticks;
  reg [8:0] byte_index;
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
      for(k=0;k<8;k=k+1) c=c[0] ? (c>>1)^32'hedb88320 : c>>1;
      crc_byte=c;
    end
  endfunction
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      frame<=0; seq<=0; gap<=0; crc<=32'hffffffff;
      shift_reg<=10'h3ff; ticks<=0; byte_index<=0; bit_index<=0;
      state<=WAIT_FRAME;
    end else case (state)
      WAIT_FRAME: if (gap==0) begin
        frame<={32'b0,report[2047:64],seq,32'h31503244};
        seq<=seq+1'b1; crc<=32'hffffffff; byte_index<=0; state<=PREP_BYTE;
      end else gap<=gap-1'b1;
      PREP_BYTE: begin
        shift_reg<={1'b1,frame[byte_index*8+:8],1'b0};
        if (byte_index<256) crc<=crc_byte(crc,frame[byte_index*8+:8]);
        ticks<=0; bit_index<=0; state<=SEND_BYTE;
      end
      SEND_BYTE: if (ticks==BIT_TICKS-1) begin
        ticks<=0; shift_reg<={1'b1,shift_reg[9:1]};
        if (bit_index==9) begin
          if (byte_index==259) begin gap<=FRAME_GAP-1; state<=WAIT_FRAME; end
          else begin
            if (byte_index==255) frame[2079:2048]<=~crc;
            byte_index<=byte_index+1'b1; state<=PREP_BYTE;
          end
        end else bit_index<=bit_index+1'b1;
      end else ticks<=ticks+1'b1;
      default: state<=WAIT_FRAME;
    endcase
  end
endmodule
