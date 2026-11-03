// Passive actual-handshake counters. No request, response or data is changed.
// bytes are 64-bit; blocking/transaction ages saturate rather than wrap.
module nx_ce64_bus_stats #(parameter DATA_W=128)(
  input logic clk,reset_n,
  axi4_if bus,
  output wire [255:0] stats
);
  logic [63:0] writes,reads;
  logic [31:0] ar_count,aw_count,max_blocked,max_pending,blocked_age,rage,wage;
  logic rpending,wpending;
  logic [2:0] rsize;
  logic [7:0] bytes;
  always_comb begin
    bytes=0;
    for(integer i=0;i<DATA_W/8;i=i+1)bytes=bytes+8'(bus.wstrb[i]);
  end
  wire blocked=(bus.arvalid&&!bus.arready)||(bus.awvalid&&!bus.awready);
  function automatic [31:0] inc(input [31:0] v);
    return &v ? v : v+1'b1;
  endfunction
  assign stats={aw_count,ar_count,max_pending,max_blocked,reads,writes};
  always_ff @(posedge clk or negedge reset_n)begin
    if(!reset_n)begin writes<=0;reads<=0;ar_count<=0;aw_count<=0;max_blocked<=0;max_pending<=0;blocked_age<=0;rage<=0;wage<=0;rsize<=0;rpending<=0;wpending<=0;end
    else begin
      blocked_age<=blocked ? inc(blocked_age) : 0;
      if(blocked&&inc(blocked_age)>max_blocked)max_blocked<=inc(blocked_age);
      if(rpending)rage<=inc(rage);
      if(wpending)wage<=inc(wage);
      if(rpending&&rage>max_pending)max_pending<=rage;
      if(wpending&&wage>max_pending&&(!rpending||wage>=rage))max_pending<=wage;
      if(bus.arvalid&&bus.arready)begin ar_count<=ar_count+1'b1;rsize<=bus.arsize;rpending<=1;rage<=0;end
      if(bus.awvalid&&bus.awready)begin aw_count<=aw_count+1'b1;wpending<=1;wage<=0;end
      if(bus.wvalid&&bus.wready)writes<=writes+64'(bytes);
      if(bus.rvalid&&bus.rready)begin reads<=reads+(64'd1<<rsize);if(bus.rlast)rpending<=0;end
      if(bus.bvalid&&bus.bready)wpending<=0;
    end
  end
endmodule
