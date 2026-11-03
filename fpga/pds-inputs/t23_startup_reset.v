// Hold the unchanged native IP reset until the independent 27MHz reference
// has run for a bounded startup interval. KEY0 asynchronously restarts it.
module t23_startup_reset #(parameter HOLD_CYCLES=27000000)(
 input clk,rst_n,output reg ready=1'b0
);
 reg [31:0] count=32'd0;
 always @(posedge clk or negedge rst_n)
   if(!rst_n)begin count<=0;ready<=0;end
   else if(!ready)begin
     count<=count+1'b1;
     if(count==HOLD_CYCLES-1)ready<=1;
   end
endmodule
