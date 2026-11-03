`define IC soc.compute.ce.control.linear_control
  integer inline_fault_fd;
  reg delayed_response=0,inline_injected=0;
  longint unsigned dot_firsts=0,dot_lasts=0;
  initial inline_fault_fd=$fopen("inline-faults.csv","w");
  always @(posedge clk)if(!reset)begin
    if(`IC.dot.req_valid_i&&`IC.dot.req_ready_o)begin
      if(`IC.dot.first_i)dot_firsts++;
      if(`IC.dot.last_i)dot_lasts++;
    end
  end
  always @(negedge clk)if(!reset)begin
    if(test_mode==43&&!delayed_response&&`IC.state==`IC.INLINE_FP_SEND&&`IC.g==0&&`IC.fp_ready)begin
      delayed_response=1;
      // Hold a real response in the existing elastic FP ADD output. Hide its
      // valid from the always-ready controller during this injected stall.
      force `IC.restore.rsp_ready_i=1'b0;
      force `IC.fp_valid=1'b0;
      if(`IC.dot.rsp_ready_i!==1'b1)$fatal(1,"fault fixture forced an unrelated constant port");
      $fwrite(inline_fault_fd,"HOLD,%0d\n",cycles);$fflush(inline_fault_fd);
    end
    if(test_mode==43&&delayed_response&&!inline_injected&&`IC.state==`IC.DOT_A&&`IC.g==2&&`IC.beat==1&&`IC.dot_live)begin
      inline_injected=1;
      release `IC.restore.rsp_ready_i;release `IC.fp_valid;
      force `IC.fp_tag=32'hffffffff;
      if(!`IC.fp_valid)$fatal(1,"no real stalled FP response at live-DOT fault boundary");
      $fwrite(inline_fault_fd,"INJECT,%0d,43,%0d,%0d\n",cycles,`IC.state,`IC.g);
      $fwrite(inline_fault_fd,"LIVE,%0d,%0d,%0d\n",cycles,dot_firsts,dot_lasts);$fflush(inline_fault_fd);
      fork begin @(negedge clk);release `IC.fp_tag;end join_none
    end
    if(soc.compute.ce.reset_grant)begin
      if(!`IC.arithmetic_idle||!soc.compute.ce.control.vector_control.arithmetic_idle||!`IC.transport_drained||!`IC.dma_idle||dot_firsts!=dot_lasts)
        $fatal(1,"reset granted with accepted incomplete arithmetic");
      $fwrite(inline_fault_fd,"RESET,%0d,%0d\n",cycles,test_mode);$fflush(inline_fault_fd);
    end
    if(test_mode==43&&inline_injected&&cycles%10000==0)begin
      $fwrite(inline_fault_fd,"DRAIN,%0d,%0d,%0d,%0d,%0d,%0d\n",cycles,`IC.state,`IC.dot_live,`IC.fp_idle,dot_firsts,dot_lasts);$fflush(inline_fault_fd);
    end
  end
`undef IC
