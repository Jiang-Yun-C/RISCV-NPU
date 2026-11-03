// Keep local/MMIO traffic independent of a pending DDR response. One read and
// one write may be accepted; each destination remains fixed through its response.
module nx_axi_ddr_route(input logic clk, reset_n,
  axi4_if.slave upstream, axi4_if.master local_bus, ddr_bus);
  logic write_active, read_active, write_ddr, read_ddr, write_done;
  logic [7:0] write_left;
  wire aw_ddr = upstream.awaddr >= 32'h80000000 && upstream.awaddr < 32'hc0000000;
  wire ar_ddr = upstream.araddr >= 32'h80000000 && upstream.araddr < 32'hc0000000;
  assign upstream.awready = !write_active && (aw_ddr ? ddr_bus.awready : local_bus.awready);
  assign upstream.wready = write_active && !write_done && (write_ddr ? ddr_bus.wready : local_bus.wready);
  assign upstream.bvalid = write_active && (write_ddr ? ddr_bus.bvalid : local_bus.bvalid);
  assign upstream.bresp = write_ddr ? ddr_bus.bresp : local_bus.bresp;
  assign upstream.bid = write_ddr ? ddr_bus.bid : local_bus.bid;
  assign upstream.arready = !read_active && (ar_ddr ? ddr_bus.arready : local_bus.arready);
  assign upstream.rvalid = read_active && (read_ddr ? ddr_bus.rvalid : local_bus.rvalid);
  assign upstream.rdata = read_ddr ? ddr_bus.rdata : local_bus.rdata;
  assign upstream.rresp = read_ddr ? ddr_bus.rresp : local_bus.rresp;
  assign upstream.rid = read_ddr ? ddr_bus.rid : local_bus.rid;
  assign upstream.rlast = read_ddr ? ddr_bus.rlast : local_bus.rlast;
`define NX_ROUTE(D,K) \
  assign D.awaddr=upstream.awaddr; assign D.awid=upstream.awid; \
  assign D.awlen=upstream.awlen; assign D.awsize=upstream.awsize; assign D.awburst=upstream.awburst; \
  assign D.awvalid=!write_active && aw_ddr==K && upstream.awvalid; \
  assign D.wdata=upstream.wdata; assign D.wstrb=upstream.wstrb; assign D.wlast=upstream.wlast; \
  assign D.wvalid=write_active && !write_done && write_ddr==K && upstream.wvalid; \
  assign D.bready=write_active && write_ddr==K && upstream.bready; \
  assign D.araddr=upstream.araddr; assign D.arid=upstream.arid; \
  assign D.arlen=upstream.arlen; assign D.arsize=upstream.arsize; assign D.arburst=upstream.arburst; \
  assign D.arvalid=!read_active && ar_ddr==K && upstream.arvalid; \
  assign D.rready=read_active && read_ddr==K && upstream.rready;
  `NX_ROUTE(local_bus,1'b0)
  `NX_ROUTE(ddr_bus,1'b1)
`undef NX_ROUTE
  always_ff @(posedge clk or negedge reset_n) begin
    if(!reset_n) begin
      write_active<=0; read_active<=0; write_ddr<=0; read_ddr<=0; write_done<=0; write_left<=0;
    end else begin
      if(upstream.awvalid && upstream.awready) begin write_active<=1; write_ddr<=aw_ddr; write_done<=0; write_left<=upstream.awlen; end
      else if(upstream.wvalid && upstream.wready) begin write_left<=write_left-8'd1; if(write_left==0) write_done<=1; end
      else if(upstream.bvalid && upstream.bready) begin write_active<=0; write_done<=0; end
      if(upstream.arvalid && upstream.arready) begin read_active<=1; read_ddr<=ar_ddr; end
      else if(upstream.rvalid && upstream.rready && upstream.rlast) read_active<=0;
    end
  end
endmodule
