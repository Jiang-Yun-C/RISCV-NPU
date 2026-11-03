// CPU+DDR baseline: absent compute endpoint returns held, framed DECERR.
module nx_ce64_disabled(input logic clk,reset_n,axi4_if.slave bus);
  logic aw,w;
  assign bus.awready=!aw&&!bus.bvalid;
  assign bus.wready=!w&&!bus.bvalid;
  assign bus.arready=!bus.rvalid;
  assign bus.bid=0;assign bus.bresp=3;
  assign bus.rid=0;assign bus.rdata=0;assign bus.rresp=3;assign bus.rlast=1;
  always_ff @(posedge clk or negedge reset_n)begin
    if(!reset_n)begin aw<=0;w<=0;bus.bvalid<=0;bus.rvalid<=0;end
    else begin
      if(bus.awvalid&&bus.awready)aw<=1;
      if(bus.wvalid&&bus.wready)w<=1;
      if(aw&&w&&!bus.bvalid)bus.bvalid<=1;
      if(bus.bvalid&&bus.bready)begin bus.bvalid<=0;aw<=0;w<=0;end
      if(bus.arvalid&&bus.arready)bus.rvalid<=1;
      if(bus.rvalid&&bus.rready)bus.rvalid<=0;
    end
  end
endmodule
