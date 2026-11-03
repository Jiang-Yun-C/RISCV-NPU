// Core-domain level request, ref-domain hold, native synchronized release.
// Never tied to CE soft reset. The board shell resets the physical DDR IP and
// every native/fabric endpoint together before a fresh calibration epoch.
module ce64_platform_reset_original #(parameter HOLD_CYCLES=125000000)(
  input logic ref_clk,board_reset_n,core_request,
  output logic hold_reset
);
  (* syn_preserve=1 *) logic request_meta,request_sync;
  logic [26:0] remaining;
  always_ff @(posedge ref_clk or negedge board_reset_n)begin
    if(!board_reset_n)begin request_meta<=0;request_sync<=0;remaining<=0;hold_reset<=0;end
    else begin
      request_meta<=core_request;request_sync<=request_meta;
      if(!hold_reset&&request_sync)begin hold_reset<=1;remaining<=HOLD_CYCLES-1;end
      else if(hold_reset)begin
        if(remaining==0)hold_reset<=0;
        else remaining<=remaining-1'b1;
      end
    end
  end
endmodule
