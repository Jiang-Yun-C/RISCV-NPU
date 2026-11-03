`timescale 1ns/1ps
module tb_counter;
  logic clk=0,reset_n=0,clear=0,enable=0;
  logic [63:0] value[0:7],reference[0:7];
  localparam logic [63:0] INITIAL[0:7]='{
    64'h0,64'hfffc,64'hfffffffc,64'hfffffffffffc,
    64'hfffffffffffffffc,64'h1234ffffffffffff,
    64'h7ffffffffffffffe,64'hffffffff};
  for(genvar g=0;g<8;g++)begin:instances
    nx_ce64_phase_counter64 #(.RESET_VALUE(INITIAL[g])) dut(
      .clk,.reset_n,.clear,.enable,.value(value[g]));
    always @(posedge clk or negedge reset_n)
      if(!reset_n)reference[g]<=INITIAL[g];
      else if(clear)reference[g]<=INITIAL[g];
      else if(enable)reference[g]<=reference[g]+64'd1;
  end
  always #5 clk=~clk;
  integer seed,checks=0,clear_count=0,reset_count=0,enabled=0,stalled=0;
  logic [31:0] rng;
  initial begin
    if(!$value$plusargs("SEED=%d",seed))seed=1;
    rng=32'(seed);repeat(2)@(negedge clk);
    for(integer i=0;i<250000;i++)begin
      @(negedge clk);
      rng={rng[30:0],rng[31]^rng[21]^rng[1]^rng[0]};
      reset_n=(i%997)!=0;
      clear=(i%947)==0;
      enable=rng[3:0]!=0;
      if(!reset_n)reset_count++;
      else if(clear)clear_count++;
      else if(enable)enabled++;else stalled++;
      #1;
      if(!reset_n)for(integer j=0;j<8;j++)
        if(value[j]!==INITIAL[j])$fatal(1,"async reset mismatch %0d",j);
      @(posedge clk);#1;
      for(integer j=0;j<8;j++)begin
        checks++;
        if(value[j]!==reference[j])$fatal(1,"counter mismatch i=%0d j=%0d got=%h want=%h",i,j,value[j],reference[j]);
      end
    end
    $display("COUNTER_PASS checks=%0d clear=%0d reset=%0d enabled=%0d stalled=%0d",checks,clear_count,reset_count,enabled,stalled);
    $finish;
  end
endmodule
