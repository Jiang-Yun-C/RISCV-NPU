// A physical synchronous single-port bank. Load and SFU read are serialized.
module nx_opt11_bank #(parameter integer DEPTH=32,AW=$clog2(DEPTH))(
  input wire clk,write,
  input wire [AW-1:0] address,
  input wire [31:0] data,
  output reg [31:0] q
);
  (* syn_ramstyle="block_ram" *) reg [31:0] memory[0:DEPTH-1];
  always @(posedge clk)begin
    q<=memory[address];
    if(write)memory[address]<=data;
  end
endmodule
