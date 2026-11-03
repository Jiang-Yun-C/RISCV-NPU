`timescale 1ns/1ps
module tb_reset;
    import sparse_memory_pkg::*;
    logic clk=0, reset_n=0;
    always #5 clk=~clk;
    axi4_if bus(clk);
    logic inject_enable=0;
    logic [1:0] inject_resp=2;
    axi_sparse_mem memory(.clk,.reset_n,.random_delays(1'b0),.seed(32'd1),.max_delay(32'd9),
        .inject_enable,.inject_start(32'h80001000),.inject_end(32'h80001fff),.inject_resp,.bus(bus));
    sparse_memory test_mem;
    task write_word(logic [31:0] address, value, logic [1:0] response);
        @(negedge clk); bus.awaddr=address; bus.awvalid=1;
        do @(posedge clk); while(!bus.awready);
        @(negedge clk); bus.awvalid=0; bus.wdata=value; bus.wvalid=1;
        do @(posedge clk); while(!bus.wready);
        @(negedge clk); bus.wvalid=0;
        do @(posedge clk); while(!bus.bvalid);
        if (bus.bresp!==response || bus.bid!==3) $fatal(1,"injection write response");
        @(negedge clk);
    endtask
    task read_word(logic [31:0] address, value, logic [1:0] response);
        @(negedge clk); bus.araddr=address; bus.arvalid=1;
        do @(posedge clk); while(!bus.arready);
        @(negedge clk); bus.arvalid=0;
        do @(posedge clk); while(!bus.rvalid);
        if (bus.rdata!==value || bus.rresp!==response || bus.rid!==7 || !bus.rlast) $fatal(1,"injection read response");
        @(negedge clk);
    endtask
    initial begin
        test_mem=new(64'h80000000,64'h40000000);
        test_mem.write_byte(64'h80000000,8'ha5);
        test_mem.write_byte(64'hbfffffff,8'h5a);
        test_mem.zero_range(64'h80000000,64'h40000000);
        if (test_mem.pages.num()!=2 || test_mem.read_byte(64'h80000000)!=0 || test_mem.read_byte(64'hbfffffff)!=0)
            $fatal(1,"sparse BSS clear did not overwrite allocated bytes");
        bus.awvalid=0; bus.awaddr=32'h80000000; bus.awid=3; bus.awlen=0; bus.awsize=2; bus.awburst=1;
        bus.wvalid=0; bus.wdata=32'h12345678; bus.wstrb=15; bus.wlast=1;
        bus.bready=0; bus.arvalid=0; bus.araddr=32'h80000000; bus.arid=7; bus.arlen=0; bus.arsize=2; bus.arburst=1; bus.rready=0;
        repeat(4) @(negedge clk); reset_n=1;
        @(negedge clk); bus.awvalid=1; bus.wvalid=1;
        @(posedge clk); if (!bus.awready || !bus.wready) $fatal(1,"reset fixture handshake");
        @(negedge clk); bus.awvalid=0; bus.wvalid=0;
        wait(bus.bvalid);
        @(negedge clk); bus.arvalid=1;
        do @(posedge clk); while(!bus.arready);
        @(negedge clk); bus.arvalid=0;
        wait(bus.rvalid);
        if (bus.rdata!==32'h12345678 || bus.rid!==7 || bus.bid!==3) $fatal(1,"reset fixture data");
        // Also leave orphan W and queued address requests before resetting.
        @(negedge clk); bus.wvalid=1; bus.wdata=32'hdeadbeef; bus.arvalid=1;
        @(posedge clk);
        @(negedge clk); bus.wvalid=0; bus.arvalid=0; reset_n=0;
        repeat(3) @(negedge clk);
        if (bus.bvalid || bus.rvalid || memory.w_out || memory.r_out || memory.wq.size()
            || memory.awq.size() || memory.arq.size()) $fatal(1,"reset did not abort pending traffic");
        reset_n=1;
        @(negedge clk); bus.arvalid=1; bus.rready=1; bus.bready=1;
        do @(posedge clk); while(!bus.arready);
        @(negedge clk); bus.arvalid=0;
        do @(posedge clk); while(!bus.rvalid);
        if (bus.rdata!==32'h12345678 || bus.rresp!==0 || !bus.rlast) $fatal(1,"reset changed external data");
        repeat(5) @(negedge clk);
        if (bus.bvalid || bus.rvalid || memory.w_out || memory.r_out) $fatal(1,"stale response after reset");
        write_word(32'h80001000,32'habcdef01,0);
        inject_enable=1;
        write_word(32'h80001000,32'hdeadbeef,2);
        read_word(32'h80001000,0,2);
        inject_resp=3;
        write_word(32'h80001000,32'hdeadbeef,3);
        read_word(32'h80001000,0,3);
        inject_enable=0;
        read_word(32'h80001000,32'habcdef01,0);
        $display("T04_RESET_PASS sparse_zero=1 pending_abort=1 contents_preserved=1 injection_2_3_no_write=1");
        $finish;
    end
    initial begin #100000; $fatal(1,"reset test timeout"); end
endmodule
