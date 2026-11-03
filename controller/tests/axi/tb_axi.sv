`timescale 1ns/1ps
`ifndef AXI_DATA_W
`define AXI_DATA_W 32
`endif
`ifndef AXI_ID_W
`define AXI_ID_W 4
`endif
module tb_axi;
    localparam DATA_W=`AXI_DATA_W;
    logic clk=0, reset_n=0, random_delays=0;
    always #5 clk=~clk;
    axi4_if #(.DATA_W(DATA_W),.ID_W(`AXI_ID_W)) bus(clk);
    int unsigned seed=1, max_delay=9;
    logic inject_enable=1;
    logic [31:0] inject_start=32'h84000000, inject_end=32'h84000fff;
    logic [1:0] inject_resp=2;
    soc_memory_env #(.DATA_W(DATA_W),.ID_W(`AXI_ID_W)) env
        (.clk,.reset_n,.random_delays,.seed,.max_delay,.inject_enable,.inject_start,.inject_end,
         .inject_resp,.ext_mem(bus));
    int cycles=0, phase=0, bcount=0, rcount=0, total_writes, total_reads;
    bit aw_done=0, w_done=0, ar_done=0;
    integer trace_fd, result_fd;
    int unsigned ready_rng;
    string stimulus;

    initial begin
        if (!$value$plusargs("seed=%d",seed)) seed=1;
        if (!$value$plusargs("random_delays=%d",random_delays)) random_delays=0;
        if (!$value$plusargs("stimulus=%s",stimulus)) $fatal(1,"missing stimulus");
        if (!$value$plusargs("writes=%d",total_writes) || !$value$plusargs("reads=%d",total_reads)) $fatal(1,"missing counts");
        ready_rng=seed ^ 32'h7f4a7c15;
        trace_fd=$fopen("bus.csv","w");
        if (!trace_fd) $fatal(1,"trace open");
        $fwrite(trace_fd,"cycle,awvalid,awready,awid,awaddr,awlen,awsize,awburst,wvalid,wready,wdata,wstrb,wlast,bvalid,bready,bid,bresp,arvalid,arready,arid,araddr,arlen,arsize,arburst,rvalid,rready,rid,rdata,rresp,rlast\n");
        $dumpfile("axi.vcd");
        // VCS requires full dumping for SystemVerilog interfaces.
        $dumpvars(0,tb_axi);
        repeat (8) @(negedge clk);
        reset_n=1;
        wait(aw_done && w_done && bcount==total_writes);
        @(negedge clk); phase=1;
        wait(ar_done && rcount==total_reads);
        repeat(5) @(negedge clk);
        // Reset drops queued transactions but preserves committed external data.
        if (env.memory.w_out || env.memory.r_out || bus.bvalid || bus.rvalid) $fatal(1,"AXI_NOT_DRAINED");
        $fclose(trace_fd);
        result_fd=$fopen("simulation.json","w");
        $fwrite(result_fd,"{\"seed\":%0d,\"random_delays\":%0d,\"width\":%0d,\"cycles\":%0d,\"writes\":%0d,\"reads\":%0d,\"pages\":%0d,\"exit_code\":0}\n",
            seed,random_delays,DATA_W,cycles,bcount,rcount,env.memory.mem.pages.num());
        $fclose(result_fd);
        $display("T04_AXI_PASS seed=%0d random=%0d width=%0d writes=%0d reads=%0d pages=%0d",seed,random_delays,DATA_W,bcount,rcount,env.memory.mem.pages.num());
        $finish;
    end

    initial begin : aw_driver
        integer fd, rc, gap, id, addr, len, size, burst;
        bus.awvalid=0; bus.awaddr=0; bus.awid=0; bus.awlen=0; bus.awsize=0; bus.awburst=0;
        wait(reset_n); @(negedge clk);
        fd=$fopen({stimulus,"/aw.txt"},"r"); if (!fd) $fatal(1,"AW file");
        while (!$feof(fd)) begin
            rc=$fscanf(fd,"%d %h %h %h %h %h\n",gap,id,addr,len,size,burst);
            if (rc!=6) $fatal(1,"AW stimulus");
            repeat(gap) @(negedge clk);
            bus.awid=id; bus.awaddr=addr; bus.awlen=len; bus.awsize=size; bus.awburst=burst; bus.awvalid=1;
            if (addr==32'h80000000 && $test$plusargs("bad_wstrb")) bus.awsize=0;
            do @(posedge clk); while (!bus.awready);
            @(negedge clk); bus.awvalid=0;
        end
        $fclose(fd); aw_done=1;
    end
    initial begin : w_driver
        integer fd, rc, gap, last;
        logic [DATA_W-1:0] data;
        logic [DATA_W/8-1:0] strb;
        bit first=1;
        bus.wvalid=0; bus.wdata=0; bus.wstrb=0; bus.wlast=0;
        wait(reset_n); @(negedge clk);
        fd=$fopen({stimulus,"/w.txt"},"r"); if (!fd) $fatal(1,"W file");
        while (!$feof(fd)) begin
            rc=$fscanf(fd,"%d %h %h %d\n",gap,data,strb,last);
            if (rc!=4) $fatal(1,"W stimulus");
            repeat(gap) @(negedge clk);
            bus.wdata=data; bus.wstrb=strb; bus.wlast=last; bus.wvalid=1;
            if (first && $test$plusargs("bad_wlast")) bus.wlast=~bus.wlast;
            first=0;
            do @(posedge clk); while (!bus.wready);
            @(negedge clk); bus.wvalid=0;
        end
        $fclose(fd); w_done=1;
    end
    initial begin : ar_driver
        integer fd, rc, wait_phase, gap, id, addr, len, size, burst;
        bus.arvalid=0; bus.araddr=0; bus.arid=0; bus.arlen=0; bus.arsize=0; bus.arburst=0;
        wait(reset_n); @(negedge clk);
        fd=$fopen({stimulus,"/ar.txt"},"r"); if (!fd) $fatal(1,"AR file");
        while (!$feof(fd)) begin
            rc=$fscanf(fd,"%d %d %h %h %h %h %h\n",wait_phase,gap,id,addr,len,size,burst);
            if (rc!=7) $fatal(1,"AR stimulus");
            wait(phase>=wait_phase); @(negedge clk);
            repeat(gap) @(negedge clk);
            bus.arid=id; bus.araddr=addr; bus.arlen=len; bus.arsize=size; bus.arburst=burst; bus.arvalid=1;
            do @(posedge clk); while (!bus.arready);
            @(negedge clk); bus.arvalid=0;
        end
        $fclose(fd); ar_done=1;
    end
    always @(negedge clk) begin
        ready_rng=1664525*ready_rng+1013904223;
        bus.bready=reset_n && cycles>160 && cycles%23>=9 && (!random_delays || ready_rng[3]);
        bus.rready=reset_n && cycles>60 && cycles%19>=7 && (!random_delays || ready_rng[7]);
    end
    always @(posedge clk) if (reset_n) begin
        cycles++;
        if (cycles>100000) $fatal(1,"T04_TIMEOUT");
        if (bus.bvalid && bus.bready) bcount++;
        if (bus.rvalid && bus.rready && bus.rlast) rcount++;
        $fwrite(trace_fd,"%0d,%h,%h,%h,%h,%h,%h,%h,%h,%h,%h,%h,%h,%h,%h,%h,%h,%h,%h,%h,%h,%h,%h,%h,%h,%h,%h,%h,%h,%h\n",
            cycles,bus.awvalid,bus.awready,bus.awid,bus.awaddr,bus.awlen,bus.awsize,bus.awburst,
            bus.wvalid,bus.wready,bus.wdata,bus.wstrb,bus.wlast,bus.bvalid,bus.bready,bus.bid,bus.bresp,
            bus.arvalid,bus.arready,bus.arid,bus.araddr,bus.arlen,bus.arsize,bus.arburst,
            bus.rvalid,bus.rready,bus.rid,bus.rdata,bus.rresp,bus.rlast);
    end
endmodule
