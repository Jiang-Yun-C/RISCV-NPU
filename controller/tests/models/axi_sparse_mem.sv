`timescale 1ns/1ps
// Simulation-only AXI4 subset: 32-bit physical address, normal non-exclusive memory.
module axi_sparse_mem #(
    parameter DATA_W=32, ID_W=4, MAX_OUTSTANDING=8, W_DEPTH=16, TIMING_CONTROL=0,
    parameter longint unsigned BASE_ADDR=64'h80000000, SIZE_BYTES=64'h40000000
) (input logic clk, reset_n, input logic random_delays,
   input int unsigned seed, max_delay,
   input logic inject_enable, input logic [31:0] inject_start, inject_end,
   input logic [1:0] inject_resp,
   axi4_if.slave bus);
    import sparse_memory_pkg::*;
    localparam LANES=DATA_W/8;
    typedef struct packed {
        logic [31:0] addr;
        logic [ID_W-1:0] id;
        logic [7:0] len;
        logic [2:0] size;
        logic [1:0] burst, resp;
    } request_t;
    typedef struct packed {
        logic [DATA_W-1:0] data;
        logic [LANES-1:0] strb;
        logic last;
    } write_t;
    typedef struct {logic [ID_W-1:0] id; logic [1:0] resp; int due;} response_t;
    request_t awq[$], arq[$], wr, rd, incoming;
    write_t wq[$], wd;
    response_t bq[$], br;
    sparse_memory mem;
    int cycle=0, w_out=0, r_out=0, wbeat=0, rbeat=0, r_due=0;
    bit writing=0, reading=0;
    int unsigned rng;
    longint unsigned addr, aligned_addr;
    logic [DATA_W-1:0] value;
    logic [LANES-1:0] legal_strobe;
    string plan, mode;
    // T07 opt-in timing contract. Defaults preserve the T04 environment.
    int fixed_latency=2, service_interval=1, ready_period=1, next_read_slot=0;

    function automatic int unsigned random_word();
        rng ^= rng << 13; rng ^= rng >> 17; rng ^= rng << 5;
        return rng;
    endfunction
    function automatic int delay_cycles();
        if (TIMING_CONTROL) return fixed_latency + (random_delays ? random_word() % (max_delay+1) : 0);
        return random_delays ? random_word() % (max_delay+1) : 2;
    endfunction
    function automatic longint unsigned beat_addr(request_t req, int beat);
        longint unsigned step_bytes, span, start_aligned, wrap_base;
        step_bytes = 64'd1 << req.size;
        span = step_bytes * (int'(req.len)+1);
        start_aligned = (64'(req.addr) / step_bytes) * step_bytes;
        wrap_base = (64'(req.addr) / span) * span;
        case (req.burst)
            0: return req.addr;
            2: return wrap_base + ((64'(req.addr)-wrap_base+beat*step_bytes) % span);
            default: return beat == 0 ? 64'(req.addr) : start_aligned+beat*step_bytes;
        endcase
    endfunction
    function automatic logic [1:0] request_response(request_t req);
        longint unsigned a, hi, step_bytes;
        bit bad, injected;
        step_bytes = 64'd1 << req.size;
        bad = step_bytes > LANES || req.burst == 3;
        bad |= req.burst == 0 && req.len > 15;
        bad |= req.burst == 2 && (!(req.len inside {1,3,7,15}) || (req.addr % step_bytes) != 0);
        injected = 0;
        for (int b=0; b<=int'(req.len); b++) begin
            a = beat_addr(req, b);
            hi = (a / step_bytes)*step_bytes + step_bytes-1;
            if (!mem.in_range(a) || !mem.in_range(hi)) return 3; // DECERR has priority
            if ((a >> 12) != (64'(req.addr) >> 12) || (hi >> 12) != (64'(req.addr) >> 12)) bad=1;
            if (inject_enable && a <= 64'(inject_end) && hi >= 64'(inject_start)) injected=1;
        end
        if (bad) return 2;
        if (injected) return inject_resp;
        return 0;
    endfunction
    function automatic logic [LANES-1:0] lane_mask(request_t req, int beat);
        longint unsigned a, hi, word_base;
        logic [LANES-1:0] mask;
        a=beat_addr(req, beat); hi=(a/(64'd1 << req.size)+1)*(64'd1 << req.size);
        word_base=(a/LANES)*LANES; mask='0;
        for (int l=0; l<LANES; l++) if (word_base+l >= a && word_base+l < hi) mask[l]=1;
        return mask;
    endfunction
    initial begin
        if (!(DATA_W inside {32,64,128}) || ID_W<1 || ID_W>16 || MAX_OUTSTANDING<1 || W_DEPTH<1
            || $bits(bus.wdata)!=DATA_W || $bits(bus.awid)!=ID_W
            || SIZE_BYTES==0 || BASE_ADDR>64'hffffffff || SIZE_BYTES>64'h100000000-BASE_ADDR)
            $fatal(1, "MEM_CONFIG invalid");
        mem = new(BASE_ADDR, SIZE_BYTES);
        if (TIMING_CONTROL) begin
            if ($value$plusargs("mem_latency=%d",fixed_latency)) begin end
            if ($value$plusargs("mem_interval=%d",service_interval)) begin end
            if ($value$plusargs("mem_ready_period=%d",ready_period)) begin end
            if (fixed_latency<0 || fixed_latency>65535 || service_interval<1 || ready_period<1)
                $fatal(1,"MEM_CONFIG timing");
        end
        if (!$value$plusargs("mode=%s", mode)) mode="PRELOAD";
        if (!$value$plusargs("image_plan=%s", plan)) plan="";
        mem.load_plan(plan, mode);
        $display("AXI_MEMORY mode=%s base=%h bytes=%h pages=%0d", mode, BASE_ADDR, SIZE_BYTES, mem.pages.num());
    end

    // Queues/state use blocking assignments locally; all bus outputs use NBA.
    // READY depends only on registered capacity/randomness, never on VALID.
    always @(posedge clk) begin
        if (!reset_n) begin
            awq.delete(); arq.delete(); wq.delete(); bq.delete();
            writing=0; reading=0; w_out=0; r_out=0; cycle=0; wbeat=0; rbeat=0; next_read_slot=0;
            rng=seed ^ 32'h9e3779b9;
            if (!rng) rng=1;
            bus.awready<=0; bus.wready<=0; bus.arready<=0;
            bus.bvalid<=0; bus.rvalid<=0; bus.bid<='0; bus.rid<='0;
            bus.bresp<=0; bus.rresp<=0; bus.rlast<=0; bus.rdata<='0;
            // Reset aborts outstanding transactions; external memory contents persist.
        end else begin
            cycle++;
            if (max_delay>65535) $fatal(1,"MEM_CONFIG max_delay exceeds 65535");
            if ($isunknown({bus.awvalid,bus.wvalid,bus.arvalid,bus.bready,bus.rready})) $fatal(1,"AXI_UNKNOWN handshake");
            if (inject_enable && !(inject_resp inside {2,3})) $fatal(1, "MEM_CONFIG error injection response");
            if (bus.bvalid && bus.bready) begin bus.bvalid<=0; w_out--; end
            if (bus.rvalid && bus.rready) begin
                bus.rvalid<=0;
                if (TIMING_CONTROL) next_read_slot=cycle+service_interval;
                if (bus.rlast) begin reading=0; r_out--; end
                else begin rbeat++; r_due=cycle+(TIMING_CONTROL ? 0 : delay_cycles()); end
            end
            if (bus.awvalid && bus.awready) begin
                if ($isunknown({bus.awaddr,bus.awid,bus.awlen,bus.awsize,bus.awburst})) $fatal(1,"AXI_UNKNOWN AW");
                incoming='{bus.awaddr,bus.awid,bus.awlen,bus.awsize,bus.awburst,2'b00};
                incoming.resp=request_response(incoming); awq.push_back(incoming); w_out++;
            end
            if (bus.arvalid && bus.arready) begin
                if ($isunknown({bus.araddr,bus.arid,bus.arlen,bus.arsize,bus.arburst})) $fatal(1,"AXI_UNKNOWN AR");
                incoming='{bus.araddr,bus.arid,bus.arlen,bus.arsize,bus.arburst,2'b00};
                incoming.resp=request_response(incoming); arq.push_back(incoming); r_out++;
            end
            if (bus.wvalid && bus.wready) begin
                if ($isunknown({bus.wstrb,bus.wlast})) $fatal(1,"AXI_UNKNOWN W");
                for (int l=0;l<LANES;l++)
                    if (bus.wstrb[l] && $isunknown(bus.wdata[8*l+:8])) $fatal(1,"AXI_UNKNOWN active W lane");
                wq.push_back('{bus.wdata,bus.wstrb,bus.wlast});
            end
            if (!writing && awq.size()) begin wr=awq.pop_front(); writing=1; wbeat=0; end
            if (writing && wq.size()) begin
                wd=wq.pop_front();
                if (wd.last !== (wbeat==int'(wr.len))) $fatal(1, "AXI_WLAST mismatch beat=%0d len=%0d",wbeat,wr.len);
                addr=beat_addr(wr,wbeat); aligned_addr=(addr/LANES)*LANES;
                legal_strobe=lane_mask(wr,wbeat);
                if (wr.resp==0 && (wd.strb & ~legal_strobe)!=0) $fatal(1,"AXI_WSTRB outside transfer");
                if (wr.resp==0) for (int l=0;l<LANES;l++)
                    if (wd.strb[l]) mem.write_byte(aligned_addr+l,wd.data[8*l+:8]);
                if (wbeat==int'(wr.len)) begin
                    br.id=wr.id; br.resp=wr.resp; br.due=cycle+delay_cycles();
                    bq.push_back(br); writing=0;
                end else wbeat++;
            end
            if ((!bus.bvalid || bus.bready) && bq.size()) begin
                if (bq[0].due <= cycle) begin
                    br=bq.pop_front(); bus.bvalid<=1; bus.bid<=br.id; bus.bresp<=br.resp;
                end
            end
            if (!reading && arq.size()) begin
                rd=arq.pop_front(); reading=1; rbeat=0; r_due=cycle+delay_cycles();
            end
            if (reading && (!bus.rvalid || bus.rready) && r_due<=cycle
                && (!TIMING_CONTROL || cycle>=next_read_slot-1)) begin
                value='0; addr=beat_addr(rd,rbeat); aligned_addr=(addr/LANES)*LANES;
                legal_strobe=lane_mask(rd,rbeat);
                if (rd.resp==0) for (int l=0;l<LANES;l++)
                    if (legal_strobe[l]) value[8*l+:8]=mem.read_byte(aligned_addr+l);
                bus.rvalid<=1; bus.rid<=rd.id; bus.rresp<=rd.resp;
                bus.rlast<=(rbeat==int'(rd.len)); bus.rdata<=value;
            end
            bus.awready <= w_out<MAX_OUTSTANDING && (!random_delays || random_word()%3!=0);
            bus.wready <= wq.size()<W_DEPTH && (!random_delays || random_word()%3!=0);
            bus.arready <= r_out<MAX_OUTSTANDING && (!random_delays || random_word()%3!=0);
            if (TIMING_CONTROL) begin
                if ((cycle+1)%ready_period != 0) begin bus.awready<=0; bus.arready<=0; end
                if ((cycle+1)%service_interval != 0) bus.wready<=0;
            end
        end
    end
endmodule
