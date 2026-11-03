`define IC soc.compute.ce.control.linear_control
  integer inline_fault_fd;
  reg inline_injected=0;
  initial inline_fault_fd=$fopen("inline-faults.csv","w");
  always @(negedge clk)if(!reset)begin
    if(test_mode<30||test_mode>42)inline_injected=0;
    if(!inline_injected&&test_mode>=30&&test_mode<=42&&
      ((test_mode==30||test_mode==31||test_mode==38)&&`IC.state==`IC.INLINE_FP_SEND||
       (test_mode==32||test_mode==33||test_mode==39)&&`IC.state==`IC.INLINE_FP_DRAIN||
       (test_mode>=34&&test_mode<=36)&&`IC.fp_valid&&`IC.restoring||
       test_mode==37&&`IC.state==`IC.DOT_WAIT&&`IC.dot_valid||
       test_mode==40&&`IC.state==`IC.DESC_START||
       test_mode==41&&`IC.state==`IC.DESC_WAIT&&`IC.desc_busy||
       test_mode==42&&soc.compute.ce.control.vector_control.state==soc.compute.ce.control.vector_control.G_START))begin
      inline_injected=1;
      $fwrite(inline_fault_fd,"INJECT,%0d,%0d,%0d,%0d\n",cycles,test_mode,`IC.state,`IC.g);$fflush(inline_fault_fd);
      case(test_mode)
        30,32:begin force `IC.stop_new=1'b1;fork begin repeat(2)@(negedge clk);release `IC.stop_new;end join_none end
        31,33:begin force `IC.timeout_fault=1'b1;fork begin repeat(2)@(negedge clk);release `IC.timeout_fault;end join_none end
        34:begin force `IC.fp_tag=32'hffffffff;fork begin @(negedge clk);release `IC.fp_tag;end join_none end
        35:begin force `IC.fp_epoch=32'hffffffff;fork begin @(negedge clk);release `IC.fp_epoch;end join_none end
        36:begin force `IC.fp_status=4'hf;fork begin @(negedge clk);release `IC.fp_status;end join_none end
        37:begin force `IC.m1_sa_valid=76'b0;fork begin repeat(2)@(negedge clk);release `IC.m1_sa_valid;end join_none end
        38,39,40,41,42:begin force soc.compute.ce.reset_request=1'b1;fork begin repeat(2)@(negedge clk);release soc.compute.ce.reset_request;end join_none end
        default:;
      endcase
    end
    if(soc.compute.ce.reset_grant)begin
      if(!`IC.arithmetic_idle||!soc.compute.ce.control.vector_control.arithmetic_idle||!`IC.transport_drained||!`IC.dma_idle)$fatal(1,"inline reset granted before accepted work drained");
      $fwrite(inline_fault_fd,"RESET,%0d,%0d\n",cycles,test_mode);$fflush(inline_fault_fd);
    end
  end
`undef IC
