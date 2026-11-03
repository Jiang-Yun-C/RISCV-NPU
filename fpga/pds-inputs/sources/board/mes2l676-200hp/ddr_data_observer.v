// D2D1 diagnostic snapshot. All signals share the native125MHz core clock.
module ddr_data_observer(
 input clk,rst_n, input [31:0] flags,errors,wbeats,rbeats,awcount,arcount,
 input [31:0] max_aw,max_ar,phase,address,drain,stalled,reason,
 input [3:0] beat,rid, input rvalid,rlast,wready,wlast,failed,
 input [255:0] expected,rdata,wdata,
 output reg [2047:0] report
);
 reg [63:0] cycles,first_drain_cycle;
 reg first_drain_seen,first_drain_complete,first_read_seen,first_write_seen;
 reg [31:0] first_drain_load,first_drain_elapsed,second_aw_address,first_read_context;
 reg [255:0] first_expected,first_rdata,first_wdata;
 always @(posedge clk or negedge rst_n) begin
  if(!rst_n) begin
   cycles<=0; first_drain_cycle<=0; first_drain_seen<=0; first_drain_complete<=0;
   first_read_seen<=0;first_write_seen<=0;first_drain_load<=0;
   first_drain_elapsed<=0;second_aw_address<=0;first_read_context<=0;
   first_expected<=0;first_rdata<=0;first_wdata<=0;report<=0;
  end else begin
   cycles<=cycles+1'b1;
   if(phase[2:0]==3 && !first_drain_seen) begin
    first_drain_seen<=1;first_drain_cycle<=cycles;first_drain_load<=drain;
   end
   if(first_drain_seen && phase[2:0]==1 && !first_drain_complete) begin
    first_drain_complete<=1;first_drain_elapsed<=cycles-first_drain_cycle;
    second_aw_address<=address;
   end
   if(rvalid && !first_read_seen) begin
    first_read_seen<=1;first_expected<=expected;first_rdata<=rdata;
    first_read_context<={22'd0,rlast,rid,beat,1'b1};
   end
   if(wready && !first_write_seen) begin first_write_seen<=1;first_wdata<=wdata; end
   report<=0;
   report[2*32+:32]<=flags; report[3*32+:32]<=errors;
   report[4*32+:32]<=wbeats;report[5*32+:32]<=rbeats;
   report[6*32+:32]<=awcount;report[7*32+:32]<=arcount;
   report[8*32+:32]<=max_aw;report[9*32+:32]<=max_ar;
   report[10*32+:32]<=phase;report[11*32+:32]<=address;
   report[12*32+:32]<=drain;report[13*32+:32]<=stalled;
   report[14*32+:32]<={18'd0,failed,wlast,wready,rlast,rvalid,rid,beat,1'b0};
   report[15*32+:32]<=reason;
   report[16*32+:32]<={28'd0,first_write_seen,first_read_seen,first_drain_complete,first_drain_seen};
   report[17*32+:32]<=first_drain_load;report[18*32+:32]<=first_drain_elapsed;
   report[19*32+:32]<=second_aw_address;report[20*32+:32]<=first_read_context;
   report[21*32+:256]<=first_expected;report[29*32+:256]<=first_rdata;
   report[37*32+:256]<=first_wdata;
   report[45*32+:64]<=cycles;
  end
 end
endmodule
