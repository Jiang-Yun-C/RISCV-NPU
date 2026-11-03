// Qualification-only response faults. Computation and request payloads remain
// actual CPU/Coral traffic; the selected transport error is consumed normally.
module nx_soc_test_response #(parameter ENABLE_TEST_CONTROL=0)(
  input logic clk,reset_n,
  input logic [31:0] mode,injection_address,hold_address,
  input logic [63:0] cycles,
  axi4_if.slave upstream,axi4_if.master downstream);
  logic read_error,write_error;
  logic [63:0] hold_until;
  wire release_b=!ENABLE_TEST_CONTROL||cycles>=hold_until;
  assign downstream.awaddr=upstream.awaddr;assign downstream.awid=upstream.awid;
  assign downstream.awlen=upstream.awlen;assign downstream.awsize=upstream.awsize;
  assign downstream.awburst=upstream.awburst;assign downstream.awvalid=upstream.awvalid;
  assign upstream.awready=downstream.awready;
  assign downstream.wdata=upstream.wdata;assign downstream.wstrb=upstream.wstrb;
  assign downstream.wlast=upstream.wlast;assign downstream.wvalid=upstream.wvalid;
  assign upstream.wready=downstream.wready;
  assign upstream.bid=downstream.bid;
  assign upstream.bresp=ENABLE_TEST_CONTROL&&write_error?2'b11:downstream.bresp;
  assign upstream.bvalid=downstream.bvalid&&release_b;
  assign downstream.bready=upstream.bready&&release_b;
  assign downstream.araddr=upstream.araddr;assign downstream.arid=upstream.arid;
  assign downstream.arlen=upstream.arlen;assign downstream.arsize=upstream.arsize;
  assign downstream.arburst=upstream.arburst;assign downstream.arvalid=upstream.arvalid;
  assign upstream.arready=downstream.arready;
  assign upstream.rid=downstream.rid;assign upstream.rdata=downstream.rdata;
  assign upstream.rresp=ENABLE_TEST_CONTROL&&read_error?2'b10:downstream.rresp;
  assign upstream.rlast=downstream.rlast;assign upstream.rvalid=downstream.rvalid;
  assign downstream.rready=upstream.rready;
  always_ff @(posedge clk) begin
    if(!reset_n)begin read_error<=0;write_error<=0;hold_until<=0;end
    else begin
      if(upstream.arvalid&&upstream.arready)
        read_error<=mode==3&&upstream.araddr>=injection_address&&{1'b0,upstream.araddr}<={1'b0,injection_address}+33'd15;
      if(upstream.awvalid&&upstream.awready)begin
        write_error<=mode==4&&upstream.awaddr>=injection_address&&{1'b0,upstream.awaddr}<={1'b0,injection_address}+33'd15;
        if(mode==5&&upstream.awaddr==hold_address)hold_until<=cycles+64'd1000000;
      end
    end
  end
endmodule
