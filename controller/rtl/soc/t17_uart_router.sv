// One outstanding read and write per destination; W may precede AW upstream.
module t17_uart_router #(parameter logic [31:0] MMIO_BASE=32'h10000000)
                     (input logic clk,reset, axi4_if.slave cpu_bus,
                      axi4_if.master memory_bus,uart_bus);
    logic read_active,read_uart,write_active,write_uart,write_data_done;
    wire ar_uart=cpu_bus.araddr>=MMIO_BASE&&cpu_bus.araddr<MMIO_BASE+256;
    wire aw_uart=cpu_bus.awaddr>=MMIO_BASE&&cpu_bus.awaddr<MMIO_BASE+256;
    assign cpu_bus.arready=!read_active&&(ar_uart?uart_bus.arready:memory_bus.arready);
    assign cpu_bus.awready=!write_active&&(aw_uart?uart_bus.awready:memory_bus.awready);
    assign cpu_bus.wready=write_active&&!write_data_done&&(write_uart?uart_bus.wready:memory_bus.wready);
    assign cpu_bus.rvalid=read_active&&(read_uart?uart_bus.rvalid:memory_bus.rvalid);
    assign cpu_bus.rdata=read_uart?uart_bus.rdata:memory_bus.rdata;
    assign cpu_bus.rresp=read_uart?uart_bus.rresp:memory_bus.rresp;
    assign cpu_bus.rlast=read_uart?uart_bus.rlast:memory_bus.rlast;
    assign cpu_bus.rid=0;
    assign cpu_bus.bvalid=write_active&&(write_uart?uart_bus.bvalid:memory_bus.bvalid);
    assign cpu_bus.bresp=write_uart?uart_bus.bresp:memory_bus.bresp;
    assign cpu_bus.bid=0;
    wire read_start=cpu_bus.arvalid&&cpu_bus.arready;
    wire read_finish=cpu_bus.rvalid&&cpu_bus.rready&&cpu_bus.rlast;
    wire write_start=cpu_bus.awvalid&&cpu_bus.awready;
    wire write_finish=cpu_bus.bvalid&&cpu_bus.bready;
    wire write_last=cpu_bus.wvalid&&cpu_bus.wready&&cpu_bus.wlast;
    always @(posedge clk)begin
        if(reset)begin read_active<=0;read_uart<=0;write_active<=0;write_uart<=0;write_data_done<=0;end
        else begin
            // Completion keeps the original priority. READY excludes a new
            // address while active; W can only fire after the AW capture.
            if(read_start||read_finish)read_active<=!read_finish;
            if(read_start)read_uart<=ar_uart;
            if(write_start||write_finish)write_active<=!write_finish;
            if(write_start)write_uart<=aw_uart;
            if(write_start||write_last)write_data_done<=write_last;
        end
    end
    `define CONNECT(B,U) \
      assign B.arvalid=cpu_bus.arvalid&&!read_active&&(ar_uart==U); \
      assign B.araddr=cpu_bus.araddr;assign B.arlen=cpu_bus.arlen;assign B.arsize=cpu_bus.arsize;assign B.arburst=cpu_bus.arburst;assign B.arid=0; \
      assign B.rready=cpu_bus.rready&&read_active&&(read_uart==U); \
      assign B.awvalid=cpu_bus.awvalid&&!write_active&&(aw_uart==U); \
      assign B.awaddr=cpu_bus.awaddr;assign B.awlen=cpu_bus.awlen;assign B.awsize=cpu_bus.awsize;assign B.awburst=cpu_bus.awburst;assign B.awid=0; \
      assign B.wvalid=cpu_bus.wvalid&&write_active&&!write_data_done&&(write_uart==U); \
      assign B.wdata=cpu_bus.wdata;assign B.wstrb=cpu_bus.wstrb;assign B.wlast=cpu_bus.wlast; \
      assign B.bready=cpu_bus.bready&&write_active&&(write_uart==U);
    `CONNECT(memory_bus,1'b0)
    `CONNECT(uart_bus,1'b1)
    `undef CONNECT
endmodule
