`timescale 1ns/1ps
// Drive real serial pins and AXI. Internal state is observed only to align
// simultaneous boundary events; expected bytes come from the stimulus queue.
module tb_fifo;
    logic clk=0,reset=1,rx=1,miso=0;
    always #5 clk=~clk;
    axi4_if u_bus(clk),s_bus(clk);
    wire tx,sck,cs_n,mosi;
    t17_uart #(.DIVISOR(8),.FIFO_DEPTH(2)) u(.clk,.reset,.rx,.boot_mode(32'd0),
        .preload_bytes(32'd0),.tx,.app_signature(),.app_data_signature(),.source_mode(),.fault_code(),.bus(u_bus));
    t18_spi s(.clk,.reset,.miso,.card_generation(32'd0),.ddr_ready(1'b1),
        .sck,.cs_n,.mosi,.model_ready(),.boot_error(),.boot_done(),.selftest(),.directory_count(),.bus(s_bus));
    int uart_checks=0,spi_checks=0,spi_samples=0;
    logic [7:0] spi_bytes[0:31];
    always @(posedge sck) if(!reset)spi_samples++;
    always @(negedge sck) if(!reset&&spi_samples<256)miso=spi_bytes[spi_samples/8][7-spi_samples%8];

`define INIT_BUS(B) \
    B.awaddr=0;B.awid=0;B.awlen=0;B.awsize=2;B.awburst=1;B.awvalid=0; \
    B.wdata=0;B.wstrb=15;B.wlast=1;B.wvalid=0;B.bready=1; \
    B.araddr=0;B.arid=0;B.arlen=0;B.arsize=2;B.arburst=1;B.arvalid=0;B.rready=0;

`define READ_TASK(NAME,B,COUNTER) \
    task automatic NAME(input logic[31:0] address,expected,input logic[1:0] response=0,input int hold=0); \
        @(negedge clk);B.araddr=address;B.arvalid=1; \
        do @(posedge clk);while(!B.arready); \
        @(negedge clk);B.arvalid=0; \
        while(!B.rvalid)@(negedge clk); \
        repeat(hold+1)begin \
            if(B.rvalid!==1'b1||B.rdata!==expected||B.rresp!==response||B.rlast!==1'b1) \
                $fatal(1,"read %h expected %h/%h got %h/%h",address,expected,response,B.rdata,B.rresp); \
            COUNTER++;@(negedge clk); \
        end \
        B.rready=1;@(negedge clk);B.rready=0; \
    endtask
    `READ_TASK(uread,u_bus,uart_checks)
    `READ_TASK(sread,s_bus,spi_checks)

    task automatic swrite(input logic[31:0] address,data);
        @(negedge clk);s_bus.awaddr=address;s_bus.awvalid=1;
        do @(posedge clk);while(!s_bus.awready);
        @(negedge clk);s_bus.awvalid=0;s_bus.wdata=data;s_bus.wvalid=1;
        do @(posedge clk);while(!s_bus.wready);
        @(negedge clk);s_bus.wvalid=0;
        if(s_bus.bvalid!==1'b1||s_bus.bresp!==0)$fatal(1,"SPI write failed");
        @(negedge clk);
    endtask
    task automatic send_byte(input logic[7:0] data,input bit good_stop=1);
        @(negedge clk);rx=0;repeat(8)@(negedge clk);
        for(int b=0;b<8;b++)begin rx=data[b];repeat(8)@(negedge clk);end
        rx=good_stop;repeat(8)@(negedge clk);rx=1;repeat(8)@(negedge clk);
    endtask
    task automatic restart;
        @(negedge clk);reset=1;rx=1;repeat(4)@(negedge clk);reset=0;repeat(4)@(negedge clk);
    endtask
    initial begin
        `INIT_BUS(u_bus)
        `INIT_BUS(s_bus)
        for(int i=0;i<32;i++)spi_bytes[i]=8'h31+7*i;
        repeat(4)@(negedge clk);reset=0;
        uread(8,0); // empty read must not move the pointer
        send_byte(8'h12);send_byte(8'h34);
        // A bad AXI request may not pop the full FIFO.
        u_bus.arlen=1;uread(8,0,2);u_bus.arlen=0;
        fork
            send_byte(8'h56);
            begin
                wait(u.rx_state==3&&u.rx_timer==0);
                // The next rising edge both samples the stop bit and pops.
                uread(8,32'h12,0,3);
            end
        join
        uread(4,2);uread(8,32'h34);uread(8,32'h56);uread(8,0);
        // Overflow rejects the newest byte, while preserving FIFO ordering.
        send_byte(8'ha1);send_byte(8'hb2);send_byte(8'hc3);
        uread(4,10);uread(8,32'ha1);uread(8,32'hb2);uread(4,8);
        restart();send_byte(8'h77,0);uread(4,4);uread(8,0);
        restart();send_byte(8'h9a);restart();uread(4,0);uread(8,0);

        spi_samples=0;miso=spi_bytes[0][7];
        swrite(4,0);swrite(16,0);swrite(56,18);
        wait(s.fifo_count==16&&!s.busy);
        repeat(12)@(negedge clk);
        if(s.fifo_count!=16||s.busy)$fatal(1,"full SPI FIFO did not pause");
        s_bus.arlen=1;sread(60,0,2);s_bus.arlen=0;
        // Popping a full FIFO must launch the next receive on that same edge.
        fork
            sread(60,{24'd0,spi_bytes[0]});
            begin
                wait(s_bus.arvalid&&s_bus.arready);
                @(posedge clk);@(negedge clk);
                if(!s.busy||s.fifo_count!=15)$fatal(1,"SPI full/pop restart");
                spi_checks++;
            end
        join
        // Align the next pop with completion of byte 17.
        wait(s.state==3&&s.timer==0);
        sread(60,{24'd0,spi_bytes[1]});
        if(s.fifo_count!=15)$fatal(1,"SPI simultaneous push/pop count");
        spi_checks++;
        for(int i=2;i<18;i++)sread(60,{24'd0,spi_bytes[i]},0,i%3);
        if(s.fifo_count!=0)$fatal(1,"SPI FIFO failed to drain");
        swrite(56,2);wait(s.fifo_count!=0);restart();
        if(s.fifo_count!=0||s.busy||!cs_n)$fatal(1,"SPI reset did not flush");
        spi_checks++;
        $display("R01_FIFO_PASS uart=%0d spi=%0d",uart_checks,spi_checks);$finish;
    end
    initial begin #200000;$fatal(1,"FIFO test timeout");end
endmodule
