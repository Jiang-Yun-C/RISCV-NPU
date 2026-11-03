`timescale 1ns/1ps
module router_adversarial;
  logic clk=0,reset=1;always #5 clk=~clk;
  axi4_if #(.DATA_W(32),.ID_W(1)) cpu_bus(clk),memory_bus(clk),uart_bus(clk);
  t17_uart_router dut(.*);
  int memory_words=0,uart_words=0;
  always @(posedge clk)if(!reset)begin
    if(memory_bus.wvalid&&memory_bus.wready)begin
      if(memory_bus.wdata!=32'h11112222)$fatal(1,"second target data leaked into memory");
      memory_words++;
    end
    if(uart_bus.wvalid&&uart_bus.wready)begin
      if(uart_bus.wdata!=32'h33334444)$fatal(1,"first target data leaked into UART");
      uart_words++;
    end
  end
  initial begin
    cpu_bus.awvalid=0;cpu_bus.awaddr=0;cpu_bus.awid=0;cpu_bus.awlen=0;cpu_bus.awsize=2;cpu_bus.awburst=1;
    cpu_bus.wvalid=0;cpu_bus.wdata=0;cpu_bus.wstrb=15;cpu_bus.wlast=1;cpu_bus.bready=1;
    cpu_bus.arvalid=0;cpu_bus.araddr=0;cpu_bus.arid=0;cpu_bus.arlen=0;cpu_bus.arsize=2;cpu_bus.arburst=1;cpu_bus.rready=1;
    memory_bus.awready=1;memory_bus.wready=1;memory_bus.bvalid=0;memory_bus.bresp=0;memory_bus.bid=0;
    memory_bus.arready=1;memory_bus.rvalid=0;memory_bus.rdata=0;memory_bus.rresp=0;memory_bus.rid=0;memory_bus.rlast=1;
    uart_bus.awready=1;uart_bus.wready=1;uart_bus.bvalid=0;uart_bus.bresp=0;uart_bus.bid=0;
    uart_bus.arready=1;uart_bus.rvalid=0;uart_bus.rdata=0;uart_bus.rresp=0;uart_bus.rid=0;uart_bus.rlast=1;
    repeat(3)@(negedge clk);reset=0;
    @(negedge clk);cpu_bus.awaddr=32'h20000;cpu_bus.awvalid=1;
    @(negedge clk);cpu_bus.awvalid=0;cpu_bus.wdata=32'h11112222;cpu_bus.wvalid=1;
    @(negedge clk);cpu_bus.wdata=32'h33334444;cpu_bus.awaddr=32'h10000000;cpu_bus.awvalid=1;
    repeat(5)begin @(negedge clk);if(cpu_bus.wready||cpu_bus.awready)$fatal(1,"next transfer accepted before first B");end
    memory_bus.bvalid=1;
    @(negedge clk);memory_bus.bvalid=0;
    wait(cpu_bus.awready);@(negedge clk);cpu_bus.awvalid=0;
    wait(cpu_bus.wready);@(negedge clk);cpu_bus.wvalid=0;
    uart_bus.bvalid=1;@(negedge clk);uart_bus.bvalid=0;
    repeat(3)@(negedge clk);
    if(memory_words!=1||uart_words!=1)$fatal(1,"exact one word per destination");
    $display("ROUTER_ADVERSARIAL_PASS independent_checks=9 memory_words=%0d uart_words=%0d",memory_words,uart_words);$finish;
  end
  initial begin #5000;$fatal(1,"bounded router test timeout");end
endmodule
