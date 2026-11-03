// Shared memory fabric with independent AXI channel arbitration. Widths are
// preserved at the three memory user ports (CPU I/D 32, Coral 128). Behavioral
// storage implements the downstream controller, never CPU/backend computation.
// AW/W ownership lasts through WLAST; accepted B may remain outstanding while
// other masters progress. Every AR, R beat and B consumes at most one shared
// channel slot per cycle. CPU-private traffic can progress during a late B.
module nx_shared_memory_arbiter(input logic clk,reset_n,
 axi4_if.slave up_i,up_d,up_n,axi4_if.master dn_i,dn_d,dn_n);
 logic[2:0] want_w,want_ar,want_r,want_b;
 logic[1:0] wp,ap,rp,bp,ws,as_,rs,bs;
 logic wb,ab,rb,bb,aw_done,w_done;
 logic[1:0] wc,ac,rc,bc;
 logic wha,whw,whlast,aha,rha,bha;
 wire write_finished=(aw_done||wha)&&(w_done||(whw&&whlast));
 function automatic logic[1:0] choose(input logic[2:0] requests,input logic[1:0] start);
   logic[1:0] idx;
   choose=3;
   for(int k=2;k>=0;k--)begin idx=2'((int'(start)+k)%3);if(requests[idx])choose=idx;end
 endfunction
 function automatic logic[1:0] next_port(input logic[1:0] p);return p==2?0:p+1;endfunction
 assign want_w={up_n.awvalid||up_n.wvalid,up_d.awvalid||up_d.wvalid,up_i.awvalid||up_i.wvalid};
 assign want_ar={up_n.arvalid,up_d.arvalid,up_i.arvalid};
 assign want_r={dn_n.rvalid,dn_d.rvalid,dn_i.rvalid};
 assign want_b={dn_n.bvalid,dn_d.bvalid,dn_i.bvalid};
 assign wc=wb?ws:choose(want_w,wp);assign ac=ab?as_:choose(want_ar,ap);
 assign rc=rb?rs:choose(want_r,rp);assign bc=bb?bs:choose(want_b,bp);
`define NX_PORT(U,D,K) \
 assign D.awaddr=U.awaddr;assign D.awid=U.awid;assign D.awlen=U.awlen;assign D.awsize=U.awsize;assign D.awburst=U.awburst; \
 assign D.awvalid=wc==K&&!aw_done&&U.awvalid;assign U.awready=wc==K&&!aw_done&&D.awready; \
 assign D.wdata=U.wdata;assign D.wstrb=U.wstrb;assign D.wlast=U.wlast; \
 assign D.wvalid=wc==K&&!w_done&&U.wvalid;assign U.wready=wc==K&&!w_done&&D.wready; \
 assign U.bid=D.bid;assign U.bresp=D.bresp;assign U.bvalid=bc==K&&D.bvalid;assign D.bready=bc==K&&U.bready; \
 assign D.araddr=U.araddr;assign D.arid=U.arid;assign D.arlen=U.arlen;assign D.arsize=U.arsize;assign D.arburst=U.arburst; \
 assign D.arvalid=ac==K&&U.arvalid;assign U.arready=ac==K&&D.arready; \
 assign U.rdata=D.rdata;assign U.rid=D.rid;assign U.rresp=D.rresp;assign U.rlast=D.rlast; \
 assign U.rvalid=rc==K&&D.rvalid;assign D.rready=rc==K&&U.rready;
 `NX_PORT(up_i,dn_i,0)
 `NX_PORT(up_d,dn_d,1)
 `NX_PORT(up_n,dn_n,2)
`undef NX_PORT
 always_comb begin
  wha=0;whw=0;whlast=0;aha=0;rha=0;bha=0;
  case(wc)
   0:begin wha=dn_i.awvalid&&dn_i.awready;whw=dn_i.wvalid&&dn_i.wready;whlast=dn_i.wlast;end
   1:begin wha=dn_d.awvalid&&dn_d.awready;whw=dn_d.wvalid&&dn_d.wready;whlast=dn_d.wlast;end
   2:begin wha=dn_n.awvalid&&dn_n.awready;whw=dn_n.wvalid&&dn_n.wready;whlast=dn_n.wlast;end
  endcase
  case(ac)
   0:aha=dn_i.arvalid&&dn_i.arready;
   1:aha=dn_d.arvalid&&dn_d.arready;
   2:aha=dn_n.arvalid&&dn_n.arready;
  endcase
  case(rc)
   0:rha=up_i.rvalid&&up_i.rready;
   1:rha=up_d.rvalid&&up_d.rready;
   2:rha=up_n.rvalid&&up_n.rready;
  endcase
  case(bc)
   0:bha=up_i.bvalid&&up_i.bready;
   1:bha=up_d.bvalid&&up_d.bready;
   2:bha=up_n.bvalid&&up_n.bready;
  endcase
 end
 always_ff @(posedge clk)begin
  if(!reset_n)begin wp<=0;ap<=0;rp<=0;bp<=0;ws<=0;as_<=0;rs<=0;bs<=0;wb<=0;ab<=0;rb<=0;bb<=0;aw_done<=0;w_done<=0;end
  else begin
   if(wc!=3)begin
    ws<=wc;wb<=!write_finished;
    aw_done<=!write_finished&&(aw_done||wha);
    w_done<=!write_finished&&(w_done||(whw&&whlast));
    if(write_finished)wp<=next_port(wc);
   end
   if(ac!=3)begin as_<=ac;ab<=!aha;if(aha)ap<=next_port(ac);end
   if(rc!=3)begin rs<=rc;rb<=!rha;if(rha)rp<=next_port(rc);end
   if(bc!=3)begin bs<=bc;bb<=!bha;if(bha)bp<=next_port(bc);end
  end
 end
endmodule
