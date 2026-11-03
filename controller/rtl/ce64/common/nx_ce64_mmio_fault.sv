// Qualification hook: corrupt a completion identity at the response capture
// boundary. It never calculates a result and it holds corrupted R data stable.
module nx_ce64_mmio_fault #(parameter ENABLE=0)(
  input logic clk,reset_n,stale,
  axi4_if.slave upstream,
  axi4_if.master downstream
);
  logic corrupt;
  assign downstream.awaddr=upstream.awaddr;assign downstream.awid=upstream.awid;
  assign downstream.awlen=upstream.awlen;assign downstream.awsize=upstream.awsize;
  assign downstream.awburst=upstream.awburst;assign downstream.awvalid=upstream.awvalid;
  assign upstream.awready=downstream.awready;
  assign downstream.wdata=upstream.wdata;assign downstream.wstrb=upstream.wstrb;
  assign downstream.wlast=upstream.wlast;assign downstream.wvalid=upstream.wvalid;
  assign upstream.wready=downstream.wready;assign upstream.bid=downstream.bid;
  assign upstream.bresp=downstream.bresp;assign upstream.bvalid=downstream.bvalid;
  assign downstream.bready=upstream.bready;
  assign downstream.araddr=upstream.araddr;assign downstream.arid=upstream.arid;
  assign downstream.arlen=upstream.arlen;assign downstream.arsize=upstream.arsize;
  assign downstream.arburst=upstream.arburst;assign downstream.arvalid=upstream.arvalid;
  assign upstream.arready=downstream.arready;
  assign upstream.rid=downstream.rid;assign upstream.rresp=downstream.rresp;
  assign upstream.rlast=downstream.rlast;assign upstream.rvalid=downstream.rvalid;
  assign upstream.rdata=downstream.rdata^(corrupt ? 128'h00000001000000000000000000000000 : 128'b0);
  assign downstream.rready=upstream.rready;
  always_ff @(posedge clk or negedge reset_n)begin
    if(!reset_n)corrupt<=0;
    else if(downstream.arvalid&&downstream.arready)
      corrupt<=ENABLE && stale && (downstream.araddr==32'h40c || downstream.araddr==32'h50c);
  end
endmodule
