`timescale 1ns/1ps
// Deterministic observer fixture, not a replacement CPU/native/DUT model.
module tb_measurement;
  reg clk=0;
  always #4 clk=~clk;
  longint unsigned cycles=0, cpu_write_accepts=0, cpu_write_responses=0;
  reg completed=0, backend_idle=1, timed_out=0;
  reg native_pending=1;
  longint unsigned native_activity=0;
  reg [31:0] peek_address=0;
  wire [31:0] peek_value=peek_address^32'h12345678;
  integer trace_fd;
  initial begin
    trace_fd=$fopen("transactions.csv","w");
    if(!trace_fd)$fatal(1,"trace open");
  end
  always @(posedge clk) begin
    cycles<=cycles+1;
    if(cycles==2)begin
      completed<=1;cpu_write_accepts<=cpu_write_accepts+1;
      $fwrite(trace_fd,"%0d,CW,10000020,0,f,0\n",cycles+1);
    end
    if(cycles==6)begin
      cpu_write_responses<=cpu_write_responses+1;
      $fwrite(trace_fd,"%0d,CB,0,0,0,0\n",cycles+1);
    end
    // Passive inspection advances the clock far enough to include a late store.
    if(cycles==20)begin
      cpu_write_accepts<=cpu_write_accepts+1;
      $fwrite(trace_fd,"%0d,CW,2fe80,1234,f,0\n",cycles+1);
    end
    if(cycles==25)begin
      cpu_write_responses<=cpu_write_responses+1;
      $fwrite(trace_fd,"%0d,CB,0,0,0,0\n",cycles+1);
    end
    // Balanced counters changing together must restart the stable interval.
    if((cycles>=27&&cycles<=29)||cycles==53)begin
      cpu_write_accepts<=cpu_write_accepts+1;
      cpu_write_responses<=cpu_write_responses+1;
      $fwrite(trace_fd,"%0d,CW,2fe84,5678,f,0\n",cycles+1);
      $fwrite(trace_fd,"%0d,CB,0,0,0,0\n",cycles+1);
    end
    if(cycles>=127)timed_out<=1;
    if(cycles==40||cycles==48||cycles==55)native_activity<=native_activity+1;
    if(cycles==50)native_pending<=0;
    // Deliberately no fflush: the parent must wait for simulator termination.
  end
  final $fclose(trace_fd);
endmodule
