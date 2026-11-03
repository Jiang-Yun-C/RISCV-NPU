// Rate-bound only the independent T25 background BIST. A registered offer
// remains asserted through backpressure; no in-flight B/R is delayed/dropped.
// Capacity BIST, CPU/CE arbitration, native drain and all clocks are unchanged.
module t25_pressure_gate #(
  parameter GAP_CYCLES=8192
)(input logic clk,reset_n,
  axi4_if.slave source_bus,
  axi4_if.master memory
);
  localparam IDLE=2'd0,OFFER=2'd1,ACTIVE=2'd2;
  localparam GAP_W=GAP_CYCLES>0 ? $clog2(GAP_CYCLES+1) : 1;
  logic [1:0] state;
  logic writing;
  logic [GAP_W-1:0] remaining;
  logic [31:0] offer_address;
  logic [5:0] offer_id;
  logic [7:0] offer_len;
  logic [2:0] offer_size;
  logic [1:0] offer_burst;
  assign memory.awaddr=offer_address;
  assign memory.awid=offer_id;
  assign memory.awlen=offer_len;
  assign memory.awsize=offer_size;
  assign memory.awburst=offer_burst;
  assign memory.awvalid=state==OFFER&&writing;
  assign source_bus.awready=state==OFFER&&writing&&memory.awready;
  assign memory.araddr=offer_address;
  assign memory.arid=offer_id;
  assign memory.arlen=offer_len;
  assign memory.arsize=offer_size;
  assign memory.arburst=offer_burst;
  assign memory.arvalid=state==OFFER&&!writing;
  assign source_bus.arready=state==OFFER&&!writing&&memory.arready;
  assign memory.wdata=source_bus.wdata;
  assign memory.wstrb=source_bus.wstrb;
  assign memory.wlast=source_bus.wlast;
  assign memory.wvalid=state==ACTIVE&&writing&&source_bus.wvalid;
  assign source_bus.wready=state==ACTIVE&&writing&&memory.wready;
  assign source_bus.bid=memory.bid;
  assign source_bus.bresp=memory.bresp;
  assign source_bus.bvalid=state==ACTIVE&&writing&&memory.bvalid;
  assign memory.bready=state==ACTIVE&&writing&&source_bus.bready;
  assign source_bus.rdata=memory.rdata;
  assign source_bus.rid=memory.rid;
  assign source_bus.rresp=memory.rresp;
  assign source_bus.rlast=memory.rlast;
  assign source_bus.rvalid=state==ACTIVE&&!writing&&memory.rvalid;
  assign memory.rready=state==ACTIVE&&!writing&&source_bus.rready;
  always_ff @(posedge clk or negedge reset_n)begin
    if(!reset_n)begin
      state<=IDLE;writing<=0;remaining<=0;offer_address<=0;
      offer_id<=0;offer_len<=0;offer_size<=0;offer_burst<=0;
    end
    else begin
      if(remaining!=0)remaining<=remaining-1'b1;
      case(state)
        IDLE: if(remaining==0&&(source_bus.awvalid||source_bus.arvalid))begin
          writing<=source_bus.awvalid;state<=OFFER;
          offer_address<=source_bus.awvalid ? source_bus.awaddr : source_bus.araddr;
          offer_id<=source_bus.awvalid ? source_bus.awid : source_bus.arid;
          offer_len<=source_bus.awvalid ? source_bus.awlen : source_bus.arlen;
          offer_size<=source_bus.awvalid ? source_bus.awsize : source_bus.arsize;
          offer_burst<=source_bus.awvalid ? source_bus.awburst : source_bus.arburst;
        end
        OFFER: if((memory.awvalid&&memory.awready)||(memory.arvalid&&memory.arready))state<=ACTIVE;
        ACTIVE: if((writing&&memory.bvalid&&memory.bready)||
                   (!writing&&memory.rvalid&&memory.rready&&memory.rlast))begin
          state<=IDLE;remaining<=GAP_W'(GAP_CYCLES);
        end
        default: state<=2'd3; // Isolate an invalid state; never release a new offer.
      endcase
    end
  end
endmodule
