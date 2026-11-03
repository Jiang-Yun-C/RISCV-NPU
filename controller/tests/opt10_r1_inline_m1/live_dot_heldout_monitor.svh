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
    // Independently restate the complete observed response identity contract.
    if(`IC.stream_restore&&`IC.restoring&&`IC.fp_valid&&
       (`IC.fp_status!=0||`IC.fp_epoch!=`IC.epoch||`IC.fp_tag!=(32'(`IC.fp_expected_group)*32'(`IC.mt)+32'(`IC.token))))begin
      if(!`IC.dot_live&&`IC.dot.req_valid_i&&`IC.dot.req_ready_o)$fatal(1,"new DOT accepted on invalid FP response");
      if(`IC.restore.req_valid_i&&`IC.restore.req_ready_o)$fatal(1,"new FP accepted on invalid FP response");
      if(`IC.bias_add.valid_i&&`IC.bias_add.ready_o)$fatal(1,"new bias accepted on invalid FP response");
      if(`IC.dma_valid&&`IC.dma_ready)$fatal(1,"new DMA accepted on invalid FP response");
    end
  end
  always @(negedge clk)if(!reset)begin
    if(test_mode<43||test_mode>47)begin delayed_response=0;inline_injected=0;end
    if((test_mode==43||test_mode==44||test_mode==47)&&!delayed_response&&`IC.state==`IC.INLINE_FP_SEND&&`IC.g==0&&`IC.fp_ready)begin
      delayed_response=1;
      force `IC.restore.rsp_ready_i=1'b0;force `IC.fp_valid=1'b0;
      if(`IC.dot.rsp_ready_i!==1'b1)$fatal(1,"unrelated constant port forced by fixture");
    end
    if(!inline_injected&&
       ((test_mode==43&&`IC.state==`IC.DOT_A&&`IC.g==2&&`IC.beat==1&&`IC.dot_live)||
        (test_mode==44&&`IC.state==`IC.DOT_A&&`IC.g==3&&`IC.beat==0&&!`IC.dot_live)||
        (test_mode==45&&`IC.state==`IC.DOT_A&&`IC.g==2&&`IC.beat==2&&`IC.dot_live)||
        (test_mode==46&&`IC.state==`IC.DOT_A&&`IC.g==2&&`IC.beat==1&&`IC.dot_live)||
        (test_mode==47&&`IC.state==`IC.WEIGHT_CHECK&&`IC.g==3&&`IC.beat==0)))begin
      inline_injected=1;
      if(test_mode==43||test_mode==44||test_mode==47)begin
        release `IC.restore.rsp_ready_i;release `IC.fp_valid;
        if(!`IC.fp_valid)$fatal(1,"no real delayed response at required boundary");
        force `IC.fp_tag=32'hffffffff;
        fork begin @(negedge clk);release `IC.fp_tag;end join_none
      end
      if(test_mode==45)begin
        force `IC.timeout_fault=1'b1;
        fork begin wait(`IC.state==`IC.DRAIN);@(negedge clk);release `IC.timeout_fault;end join_none
      end
      if(test_mode==46)begin
        force soc.compute.ce.reset_request=1'b1;
        fork begin @(negedge clk);release soc.compute.ce.reset_request;end join_none
      end
      if(test_mode==47)begin
        force `IC.read_data=128'h01010101010101010101010101010101;
        fork begin
          @(posedge clk);#1;
          if(`IC.weight_group[0]!==128'h01010101010101010101010101010101)$fatal(1,"dirty unpublished cache condition not exercised");
          @(negedge clk);release `IC.read_data;
        end join_none
      end
      $fwrite(inline_fault_fd,"INJECT,%0d,%0d,%0d,%0d\n",cycles,test_mode,`IC.state,`IC.g);$fflush(inline_fault_fd);
    end
    if(soc.compute.ce.reset_grant)begin
      if(!`IC.arithmetic_idle||!soc.compute.ce.control.vector_control.arithmetic_idle||!`IC.transport_drained||!`IC.dma_idle||dot_firsts!=dot_lasts)
        $fatal(1,"reset granted before all accepted groups and native work drained");
      $fwrite(inline_fault_fd,"RESET,%0d,%0d\n",cycles,test_mode);$fflush(inline_fault_fd);
    end
  end
`undef IC
