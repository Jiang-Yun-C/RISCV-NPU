// FPGA reservation-station storage candidate. The original full-table monitor
// is disconnected in the selected ALU/MUL/FALU stations; it is not a product
// consumer. This module preserves their 3-push/2-pop/8-entry queue boundary.
module nx_coral_banked_rs_fifo #(
  parameter integer WIDTH = 597
) (
  input wire clk, rst_n, clear,
  input wire [2:0] push,
  output wire [2:0] pushRdy,
  input wire [3*WIDTH-1:0] datain,
  output wire full,
  output wire [2:0] almost_full,
  input wire [1:0] pop,
  output wire [2*WIDTH-1:0] dataout,
  output wire empty,
  output wire [1:0] almost_empty,
  output reg [2:0] wptr, rptr,
  output reg [3:0] entry_count
);
  wire [3:0] push_count = {3'd0,push[0]} + {3'd0,push[1]} + {3'd0,push[2]};
  wire [3:0] pop_count = {3'd0,pop[0]} + {3'd0,pop[1]};
  wire [2:0] next_rptr = clear ? 3'd0 : rptr + pop_count;
  wire [2:0] next_wptr = wptr + push_count;
  assign full = entry_count == 8;
  assign almost_full[0] = full;
  assign almost_full[1] = entry_count + 1 >= 8;
  assign almost_full[2] = entry_count + 2 >= 8;
  assign empty = entry_count == 0;
  assign almost_empty = {entry_count <= 1,empty};

  reg [2:0] accepted;
  integer i;
  always @* begin
    for (i=0;i<3;i=i+1)
      if (push[i]) accepted[i]=1'b1;
      else accepted[i]=1'b0;
  end
  wire [1:0] prefix0=0;
  wire [1:0] prefix1={1'b0,accepted[0]};
  wire [1:0] prefix2={1'b0,accepted[0]}+{1'b0,accepted[1]};
  wire [2:0] slot0=wptr+prefix0;
  wire [2:0] slot1=wptr+prefix1;
  wire [2:0] slot2=wptr+prefix2;
  assign pushRdy[0]=!almost_full[prefix0];
  assign pushRdy[1]=!almost_full[prefix1];
  assign pushRdy[2]=!almost_full[prefix2];
  reg [7:0] written;
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) begin
      wptr<=0; rptr<=0; entry_count<=0;
    end else if (clear) begin
      wptr<=0; rptr<=0; entry_count<=0;
    end else begin
      if (|push) wptr<=next_wptr;
      if (|pop) rptr<=next_rptr;
      if ((|push)||(|pop)) entry_count<=entry_count+push_count-pop_count;
    end
  end
  // POP_CLEAR=0 in these stations: clear affects pointers/count, not memory.
  // Writes at a clear edge still use the old write pointer, as upstream does.
  always @(posedge clk or negedge rst_n) begin
    if (!rst_n) written<=0;
    else begin
      if (accepted[0]) written[slot0]<=1'b1;
      if (accepted[1]) written[slot1]<=1'b1;
      if (accepted[2]) written[slot2]<=1'b1;
    end
  end

  wire [4*WIDTH-1:0] read_data;
  genvar b;
  generate for (b=0;b<4;b=b+1) begin : bank
    (* syn_ramstyle = "block_ram" *) reg [WIDTH-1:0] mem [0:1];
    reg read_address;
    wire hit0=accepted[0] && slot0[1:0]==b;
    wire hit1=accepted[1] && slot1[1:0]==b;
    wire hit2=accepted[2] && slot2[1:0]==b;
    wire write_enable=hit0||hit1||hit2;
    wire write_address=(hit0&&slot0[2])||(hit1&&slot1[2])||(hit2&&slot2[2]);
    wire [WIDTH-1:0] write_data=({WIDTH{hit0}}&datain[0+:WIDTH])|
      ({WIDTH{hit1}}&datain[WIDTH+:WIDTH])|({WIDTH{hit2}}&datain[2*WIDTH+:WIDTH]);
    wire [2:0] next_second=next_rptr+1;
    // Prefetch the pointer that becomes visible at this edge. Banked writes
    // have distinct low two bits, including the 7->0 wrap boundary.
    always @(posedge clk) begin
      if (next_rptr[1:0]==b) read_address<=next_rptr[2];
      else if (next_second[1:0]==b) read_address<=next_second[2];
      else read_address<=0;
      if (rst_n && write_enable) mem[write_address]<=write_data;
    end
    assign read_data[b*WIDTH+:WIDTH]=mem[read_address];
  end endgenerate
  wire [2:0] second=rptr+1;
  assign dataout[0+:WIDTH]=written[rptr] ? read_data[rptr[1:0]*WIDTH+:WIDTH] : {WIDTH{1'b0}};
  assign dataout[WIDTH+:WIDTH]=written[second] ? read_data[second[1:0]*WIDTH+:WIDTH] : {WIDTH{1'b0}};
endmodule
