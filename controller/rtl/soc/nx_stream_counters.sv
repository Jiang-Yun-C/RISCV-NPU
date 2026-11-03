// Per-owner-epoch counters on the single-read/single-write Coral guard port.
// Never clear accepted state; clear is legal only at a drained boundary.
module nx_stream_counters(input logic clk,reset_n,clear,
 axi4_if bus,
 output logic[63:0] cycles,read_bytes,write_bytes,read_wait,write_wait,
 output logic[63:0] ar_count,r_count,aw_count,w_count,b_count);
 logic[2:0] read_size;
 logic read_active,write_active;
 always_ff @(posedge clk) begin
  if(!reset_n || clear)begin
   cycles<=0;read_bytes<=0;write_bytes<=0;read_wait<=0;write_wait<=0;
   ar_count<=0;r_count<=0;aw_count<=0;w_count<=0;b_count<=0;
   read_size<=0;read_active<=0;write_active<=0;
  end else begin
   cycles<=cycles+1;
   read_wait<=read_wait+(read_active && !(bus.rvalid&&bus.rready));
   write_wait<=write_wait+(write_active && !(bus.bvalid&&bus.bready));
   // Terminal responses retain priority if both events occur on one edge.
   // Each active flag has one explicit update, including that boundary case.
   if(bus.rvalid&&bus.rready&&bus.rlast)read_active<=0;
   else if(bus.arvalid&&bus.arready)read_active<=1;
   if(bus.bvalid&&bus.bready)write_active<=0;
   else if(bus.awvalid&&bus.awready)write_active<=1;
   if(bus.arvalid&&bus.arready)begin read_size<=bus.arsize;ar_count<=ar_count+1;end
   if(bus.rvalid&&bus.rready)begin
    r_count<=r_count+1;read_bytes<=read_bytes+(64'd1<<read_size);
   end
   if(bus.awvalid&&bus.awready)aw_count<=aw_count+1;
   if(bus.wvalid&&bus.wready)begin w_count<=w_count+1;write_bytes<=write_bytes+$countones(bus.wstrb);end
   if(bus.bvalid&&bus.bready)b_count<=b_count+1;
  end
 end
endmodule
