// Two 128-bit masters, one locked read and one locked write offer. Selection
// is registered BEFORE presenting VALID; arrival of another master cannot
// change a blocked offer. One downstream native adapter owns all transactions.
module nx_ce64_aux_mux (
  input logic clk,reset_n,
  input wire ce_w_capture,
  output wire memory_w_capture,
  axi4_if.slave ce,aux,
  axi4_if.master memory
);
  logic ro,rsent,rsel,rfavor,wo,awsent,wdone,wsel,wfavor;
  logic [7:0] rlen,wlen;
  logic [8:0] rb,wb;
  // ro/rsel belong to the locked AR offer, including all backpressure.
  // An auxiliary transaction cannot inherit the CE's pending capture context.
  assign memory_w_capture=ro && !rsel && ce_w_capture;
  assign memory.araddr=rsel ? aux.araddr : ce.araddr;
  assign memory.arid=rsel ? aux.arid : ce.arid;
  assign memory.arlen=rsel ? aux.arlen : ce.arlen;
  assign memory.arsize=rsel ? aux.arsize : ce.arsize;
  assign memory.arburst=rsel ? aux.arburst : ce.arburst;
  assign memory.arvalid=ro&&!rsent;
  assign ce.arready=ro&&!rsent&&!rsel&&memory.arready;
  assign aux.arready=ro&&!rsent&&rsel&&memory.arready;
  assign ce.rvalid=ro&&rsent&&!rsel&&memory.rvalid;
  assign aux.rvalid=ro&&rsent&&rsel&&memory.rvalid;
  assign ce.rdata=memory.rdata;assign aux.rdata=memory.rdata;
  assign ce.rid=memory.rid;assign aux.rid=memory.rid;
  assign ce.rresp=memory.rresp;assign aux.rresp=memory.rresp;
  assign ce.rlast=memory.rlast;assign aux.rlast=memory.rlast;
  assign memory.rready=ro&&rsent&&(rsel ? aux.rready : ce.rready);
  assign memory.awaddr=wsel ? aux.awaddr : ce.awaddr;
  assign memory.awid=wsel ? aux.awid : ce.awid;
  assign memory.awlen=wsel ? aux.awlen : ce.awlen;
  assign memory.awsize=wsel ? aux.awsize : ce.awsize;
  assign memory.awburst=wsel ? aux.awburst : ce.awburst;
  assign memory.awvalid=wo&&!awsent;
  assign ce.awready=wo&&!awsent&&!wsel&&memory.awready;
  assign aux.awready=wo&&!awsent&&wsel&&memory.awready;
  assign memory.wdata=wsel ? aux.wdata : ce.wdata;
  assign memory.wstrb=wsel ? aux.wstrb : ce.wstrb;
  assign memory.wlast=wsel ? aux.wlast : ce.wlast;
  assign memory.wvalid=wo&&!wdone&&(wsel ? aux.wvalid : ce.wvalid);
  assign ce.wready=wo&&!wdone&&!wsel&&memory.wready;
  assign aux.wready=wo&&!wdone&&wsel&&memory.wready;
  assign ce.bvalid=wo&&awsent&&wdone&&!wsel&&memory.bvalid;
  assign aux.bvalid=wo&&awsent&&wdone&&wsel&&memory.bvalid;
  assign ce.bid=memory.bid;assign aux.bid=memory.bid;
  assign ce.bresp=memory.bresp;assign aux.bresp=memory.bresp;
  assign memory.bready=wo&&awsent&&wdone&&(wsel ? aux.bready : ce.bready);
  always_ff @(posedge clk or negedge reset_n) begin
    if(!reset_n)begin ro<=0;rsent<=0;rsel<=0;rfavor<=0;wo<=0;awsent<=0;wdone<=0;wsel<=0;wfavor<=0;rlen<=0;wlen<=0;rb<=0;wb<=0;end
    else begin
      if(!ro && (ce.arvalid||aux.arvalid))begin
        ro<=1;rsent<=0;rb<=0;
        rsel<=aux.arvalid&&(!ce.arvalid||rfavor);
        rlen<=aux.arvalid&&(!ce.arvalid||rfavor) ? aux.arlen : ce.arlen;
      end
      if(memory.arvalid&&memory.arready)rsent<=1;
      if(memory.rvalid&&memory.rready)begin
        if(rb==rlen)begin ro<=0;rsent<=0;rfavor<=!rsel;end
        else rb<=rb+1'b1;
      end
      if(!wo && (ce.awvalid||aux.awvalid))begin
        wo<=1;awsent<=0;wdone<=0;wb<=0;
        wsel<=aux.awvalid&&(!ce.awvalid||wfavor);
        wlen<=aux.awvalid&&(!ce.awvalid||wfavor) ? aux.awlen : ce.awlen;
      end
      if(memory.awvalid&&memory.awready)awsent<=1;
      if(memory.wvalid&&memory.wready)begin
        if(wb==wlen)wdone<=1;else wb<=wb+1'b1;
      end
      if(memory.bvalid&&memory.bready)begin wo<=0;awsent<=0;wdone<=0;wfavor<=!wsel;end
    end
  end
endmodule
