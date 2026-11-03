`define IC soc.compute.ce.control.linear_control
integer inline_fault_fd;
reg delayed_response=0,inline_injected=0,boundary_seen=0;
longint unsigned dot_firsts=0,dot_lasts=0,boundary_cycle=0;
initial inline_fault_fd=$fopen("inline-faults.csv","w");
always @(posedge clk)if(!reset)begin
 if(`IC.dot.req_valid_i&&`IC.dot.req_ready_o)begin
  if(`IC.dot.first_i)begin
   dot_firsts++;
   if(test_mode==66&&inline_injected)$fatal(1,"DOT FIRST accepted after illegal final weight beat");
  end
  if(`IC.dot.last_i)dot_lasts++;
 end
 if(test_mode>=60&&test_mode<=70)begin
  if(`IC.first_a_read)begin
   if(!`IC.ram_en||`IC.ram_mask!=0||`IC.ram_address!==12'((`IC.g*64)>>4))$fatal(1,"bad actual firstA prefetch address");
   $fwrite(inline_fault_fd,"BOUNDARY,%0d,%0d,1,%0d,%0d,%0d\n",cycles,test_mode,`IC.row,`IC.g,`IC.beat);
   if((test_mode==60||test_mode==61||test_mode==62||test_mode==68||test_mode==70)&&`IC.row==0&&`IC.g==2&&!inline_injected)begin boundary_seen=1;boundary_cycle=cycles;end
  end
  if(`IC.next_sw_read)begin
   if(!`IC.fp_request_valid||!`IC.fp_ready||!`IC.ram_en||`IC.ram_mask!=0||`IC.ram_address!==12'((16'h5800+16'((`IC.g+1)*4))>>4))$fatal(1,"bad actual accepted nextSw prefetch");
   $fwrite(inline_fault_fd,"BOUNDARY,%0d,%0d,2,%0d,%0d,%0d\n",cycles,test_mode,`IC.row,`IC.g,`IC.beat);
   if((test_mode==63||test_mode==64||test_mode==65||test_mode==67||test_mode==69)&&`IC.row==0&&`IC.g==2&&!inline_injected)begin boundary_seen=1;boundary_cycle=cycles;end
  end
  if(test_mode==66&&inline_injected&&`IC.state==`IC.WEIGHT_CHECK&&`IC.g==0&&`IC.beat==3)begin
   if(!`IC.bad_weight||dot_firsts!=dot_lasts)$fatal(1,"illegal last W predicate not exercised before FIRST");
   $fwrite(inline_fault_fd,"BAD_LAST,%0d,%0d,%0d,%0d\n",cycles,test_mode,`IC.g,`IC.beat);
  end
 end
 if(`IC.stream_restore&&`IC.restoring&&`IC.fp_valid&&(`IC.fp_status!=0||`IC.fp_epoch!=`IC.epoch||`IC.fp_tag!=(32'(`IC.fp_expected_group)*32'(`IC.mt)+32'(`IC.token))))begin
  if(!`IC.dot_live&&`IC.dot.req_valid_i&&`IC.dot.req_ready_o)$fatal(1,"new DOT on invalid FP response");
  if(`IC.restore.req_valid_i&&`IC.restore.req_ready_o)$fatal(1,"new FP on invalid FP response");
  if(`IC.bias_add.valid_i&&`IC.bias_add.ready_o)$fatal(1,"new bias on invalid FP response");
  if(`IC.dma_valid&&`IC.dma_ready)$fatal(1,"new DMA on invalid FP response");
 end
end
always @(negedge clk)if(!reset)begin
 if(test_mode<60||test_mode>70)begin delayed_response=0;inline_injected=0;boundary_seen=0;end
 if((test_mode==62||test_mode==65||test_mode==68||test_mode==69||test_mode==70)&&!delayed_response&&`IC.state==`IC.INLINE_FP_SEND&&`IC.g==0&&`IC.fp_ready)begin
  delayed_response=1;force `IC.restore.rsp_ready_i=1'b0;force `IC.fp_valid=1'b0;
  if(`IC.dot.rsp_ready_i!==1'b1)$fatal(1,"unrelated arithmetic port forced");
 end
 if(!inline_injected&&((test_mode==66&&`IC.state==`IC.WEIGHT_CHECK&&`IC.g==0&&`IC.beat==3)||
     (boundary_seen&&cycles>boundary_cycle&&((test_mode!=70)||(test_mode==70&&`IC.state==`IC.DOT_A&&`IC.g==2&&`IC.beat==1&&`IC.dot_live)))))begin
  inline_injected=1;
  if(test_mode==60||test_mode==63)begin
   force soc.compute.ce.reset_request=1'b1;fork begin @(negedge clk);release soc.compute.ce.reset_request;end join_none
  end
  if(test_mode==61||test_mode==64)begin
   force `IC.timeout_fault=1'b1;fork begin wait(`IC.state==`IC.DRAIN);@(negedge clk);release `IC.timeout_fault;end join_none
  end
  if(test_mode==62||test_mode==65||test_mode==68||test_mode==69||test_mode==70)begin
   release `IC.restore.rsp_ready_i;release `IC.fp_valid;
   if(!`IC.fp_valid)$fatal(1,"no real delayed FP response at accepted prefetch boundary");
   if(test_mode==62||test_mode==70)begin force `IC.fp_tag=32'hffffffff;fork begin @(negedge clk);release `IC.fp_tag;end join_none end
   if(test_mode==65)begin force `IC.fp_epoch=32'hffffffff;fork begin @(negedge clk);release `IC.fp_epoch;end join_none end
   if(test_mode==68||test_mode==69)begin force `IC.fp_status=4'he;fork begin @(negedge clk);release `IC.fp_status;end join_none end
  end
  if(test_mode==66)begin force `IC.read_data=128'h80000000000000000000000000000000;fork begin @(negedge clk);release `IC.read_data;end join_none end
  if(test_mode==67)begin
   if(`IC.state!=`IC.WEIGHT_SCALE||`IC.g!=3)$fatal(1,"nextSw low word selector target missed");
   force `IC.read_data=128'h7fc000007fc000007fc000007fc00000;fork begin @(negedge clk);release `IC.read_data;end join_none
  end
  $fwrite(inline_fault_fd,"INJECT,%0d,%0d,%0d,%0d\n",cycles,test_mode,`IC.state,`IC.g);$fflush(inline_fault_fd);
 end
 if(soc.compute.ce.reset_grant)begin
  if(!`IC.arithmetic_idle||!soc.compute.ce.control.vector_control.arithmetic_idle||!`IC.transport_drained||!`IC.dma_idle||dot_firsts!=dot_lasts)$fatal(1,"reset grant before FP DOT and native drain");
  $fwrite(inline_fault_fd,"RESET,%0d,%0d\n",cycles,test_mode);$fflush(inline_fault_fd);
 end
end
`undef IC
