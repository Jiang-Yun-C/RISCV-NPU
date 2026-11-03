// Synthesizable single-read/single-write AXI firewall and drain boundary.
// Isolation never resets accepted channel state. No response can be discarded.
module nx_accel_guard(input logic clk,reset_n,isolate,clear_error,
  output logic idle,error,output logic[31:0] fault_address,
  axi4_if.slave upstream,axi4_if.master downstream);
  import nx_accel_map::*;
  logic aw_have,w_have,aw_sent,w_sent,deny_w;
  logic ar_have,ar_sent,deny_r;
  logic[31:0] wa,ra;
  logic[5:0] wi,ri;
  logic[7:0] wl,rl,wb,rb;
  logic[2:0] ws,rs;
  logic[127:0] data;
  logic[15:0] strb;
  logic last;
  logic[32:0] w_end,r_end;
  assign w_end={1'b0,upstream.awaddr}+((33'(upstream.awlen)+1)<<upstream.awsize);
  assign r_end={1'b0,upstream.araddr}+((33'(upstream.arlen)+1)<<upstream.arsize);
  assign idle=!aw_have&&!w_have&&!ar_have&&!upstream.bvalid&&!upstream.rvalid;
  assign upstream.awready=!aw_have&&!upstream.bvalid&&(!isolate||w_have);
  assign upstream.wready=!w_have&&!upstream.bvalid&&(!isolate||aw_have);
  assign upstream.arready=!ar_have&&!upstream.rvalid&&!isolate;
  assign downstream.awvalid=aw_have&&!deny_w&&!aw_sent;
  assign downstream.awaddr=wa;assign downstream.awid=wi;assign downstream.awlen=wl;
  assign downstream.awsize=ws;assign downstream.awburst=1;
  assign downstream.wvalid=aw_have&&w_have&&!deny_w&&!w_sent;
  assign downstream.wdata=data;assign downstream.wstrb=strb;assign downstream.wlast=last;
  assign downstream.bready=aw_have&&!deny_w&&aw_sent&&w_sent&&!upstream.bvalid;
  assign downstream.arvalid=ar_have&&!deny_r&&!ar_sent;
  assign downstream.araddr=ra;assign downstream.arid=ri;assign downstream.arlen=rl;
  assign downstream.arsize=rs;assign downstream.arburst=1;
  assign downstream.rready=ar_have&&!deny_r&&ar_sent&&!upstream.rvalid;
  wire take_aw=upstream.awvalid&&upstream.awready;
  wire take_w=upstream.wvalid&&upstream.wready;
  wire take_ar=upstream.arvalid&&upstream.arready;
  wire take_b=upstream.bvalid&&upstream.bready;
  wire take_r=upstream.rvalid&&upstream.rready;
  wire send_aw=downstream.awvalid&&downstream.awready;
  wire send_ar=downstream.arvalid&&downstream.arready;
  // Preserve the rejected-burst state while B is held; acceptance below wins.
  wire consume_w=aw_have&&w_have&&(deny_w||(downstream.wvalid&&downstream.wready));
  wire write_done=consume_w&&wb==wl;
  wire write_more=consume_w&&wb!=wl;
  wire denied_b=write_done&&deny_w;
  wire receive_b=downstream.bvalid&&downstream.bready;
  wire denied_r=ar_have&&deny_r&&!upstream.rvalid;
  wire receive_r=downstream.rvalid&&downstream.rready;
  wire write_fault=denied_b||(receive_b&&downstream.bresp!=0);
  wire read_fault=denied_r||(receive_r&&downstream.rresp!=0);
  always_ff @(posedge clk)begin
    if(!reset_n)begin
      aw_have<=0;w_have<=0;aw_sent<=0;w_sent<=0;ar_have<=0;ar_sent<=0;
      deny_w<=0;deny_r<=0;wb<=0;rb<=0;wa<=0;ra<=0;wi<=0;ri<=0;wl<=0;rl<=0;ws<=0;rs<=0;
      data<=0;strb<=0;last<=0;error<=0;fault_address<=0;
      upstream.bvalid<=0;upstream.bid<=0;upstream.bresp<=0;
      upstream.rvalid<=0;upstream.rid<=0;upstream.rresp<=0;upstream.rdata<=0;upstream.rlast<=0;
    end else begin
      // Preserve read-fault > write-fault > idle clear priority.
      if(read_fault)begin error<=1;fault_address<=ra;end
      else if(write_fault)begin error<=1;fault_address<=wa;end
      else if(clear_error&&idle)begin error<=0;fault_address<=0;end
      if(take_b)aw_have<=0;else if(take_aw)aw_have<=1;
      if(take_b||write_more)w_have<=0;else if(take_w)w_have<=1;
      if(take_b)aw_sent<=0;else if(send_aw)aw_sent<=1;
      if(take_b)w_sent<=0;else if(write_done)w_sent<=1;
      if(take_r&&upstream.rlast)begin ar_have<=0;ar_sent<=0;end
      else begin
        if(take_ar)ar_have<=1;
        if(send_ar)ar_sent<=1;
      end
      if(take_aw)wb<=0;else if(write_more)wb<=wb+1;
      if(take_ar)rb<=0;else if(take_r)rb<=rb+1;
      if(take_aw)begin
        wa<=upstream.awaddr;wi<=upstream.awid;wl<=upstream.awlen;ws<=upstream.awsize;
        deny_w<=!burst_ok(upstream.awaddr,upstream.awlen,upstream.awsize,upstream.awburst,4)||
          shared_region(upstream.awaddr,w_end,1)==0||isolate;
      end
      if(take_w)begin data<=upstream.wdata;strb<=upstream.wstrb;last<=upstream.wlast;end
      if(take_b)upstream.bvalid<=0;
      else if(denied_b)begin upstream.bvalid<=1;end
      else if(receive_b)begin
        upstream.bvalid<=1;
      end
      if(denied_b)begin upstream.bid<=wi;upstream.bresp<=3;end
      else if(receive_b)begin upstream.bid<=downstream.bid;upstream.bresp<=downstream.bresp;end
      if(take_ar)begin
        ra<=upstream.araddr;ri<=upstream.arid;rl<=upstream.arlen;rs<=upstream.arsize;
        deny_r<=!burst_ok(upstream.araddr,upstream.arlen,upstream.arsize,upstream.arburst,4)||
          shared_region(upstream.araddr,r_end,0)==0;
      end
      if(denied_r)begin
        upstream.rvalid<=1;upstream.rid<=ri;upstream.rresp<=3;upstream.rdata<=0;upstream.rlast<=rb==rl;
      end
      else if(receive_r)begin
        upstream.rvalid<=1;upstream.rid<=downstream.rid;upstream.rresp<=downstream.rresp;
        upstream.rdata<=downstream.rdata;upstream.rlast<=downstream.rlast;
      end
      else if(take_r)upstream.rvalid<=0;
    end
  end
endmodule
