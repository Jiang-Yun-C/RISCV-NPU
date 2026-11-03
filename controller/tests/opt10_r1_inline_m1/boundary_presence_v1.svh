`define BP soc.compute.ce.control.linear_control
integer bp_fd;longint unsigned bp_first=0,bp_next=0;
initial bp_fd=$fopen("boundary-presence.csv","w");
always @(posedge clk)if(!reset)begin
 if(`BP.submit)begin bp_first=0;bp_next=0;end
 if(`BP.first_a_read)begin
  if(!`BP.ram_en||`BP.ram_mask!=0||`BP.ram_address!==12'((`BP.g*64)>>4))$fatal(1,"firstA scratch address/mask");bp_first++;
 end
 if(`BP.next_sw_read)begin
  if(!`BP.fp_request_valid||!`BP.fp_ready||!`BP.ram_en||`BP.ram_mask!=0||`BP.ram_address!==12'((16'h5800+16'((`BP.g+1)*4))>>4))$fatal(1,"nextSw accepted scratch address/mask");bp_next++;
 end
 if(`BP.completion_valid&&`BP.completion_ready)begin
  $fwrite(bp_fd,"COMPLETE,%0d,%0d,%0d,%0d,%0d,%0d,%0d\n",cycles,$signed(`BP.status),`BP.d[15],`BP.d[16],`BP.d[17],bp_first,bp_next);$fflush(bp_fd);
 end
end
`undef BP
