// Passive monitors only. No DUT result/completion/ownership force.
`define OC soc.compute.ce.control
  int opt10_fd,opt10_state_fd;
  int opt10_previous_state=-1;
  longint unsigned opt10_ticks=0,opt10_load=0,opt10_compute=0,opt10_write=0,opt10_restore=0;
  longint unsigned opt10_read_bytes=0,opt10_write_bytes=0;
  longint unsigned opt10_rbytes=0;
  int opt10_rsize=0,opt10_rlen=0;
  int opt10_scratch_dma=0,opt10_scratch_control=0,opt10_shared_requests=0;
  initial begin
    opt10_fd=$fopen("phases.csv","w");opt10_state_fd=$fopen("timeline.csv","w");
    if(!opt10_fd||!opt10_state_fd)$fatal(1,"OPT10 monitor output");
  end
  always @(posedge clk)if(!reset)begin
    if(`OC.submit)begin
      opt10_ticks=0;opt10_load=0;opt10_compute=0;opt10_write=0;opt10_restore=0;
      opt10_read_bytes=0;opt10_write_bytes=0;
      opt10_scratch_dma=0;opt10_scratch_control=0;opt10_shared_requests=0;
    end
    if(!`OC.engine_idle && !`OC.completion_valid)begin
      opt10_ticks++;
      case(`OC.phase)
        1:opt10_load++;
        2:opt10_compute++;
        3:opt10_write++;
        default:;
      endcase
      if(`OC.restoring)opt10_restore++;
    end
    if(soc.compute.ce.a_en)opt10_scratch_control++;
    if(soc.compute.ce.b_en)opt10_scratch_dma++;
    if(soc.compute.ce.a_en&&soc.compute.ce.b_en)$fatal(1,"OPT10 physical single SRAM port collision");
    if(owner&&dmem_port.arvalid&&dmem_port.arready)opt10_shared_requests++;
    if(backend.arvalid&&backend.arready)begin opt10_rsize=backend.arsize;opt10_rlen=backend.arlen;end
    if(backend.rvalid&&backend.rready)opt10_read_bytes+=1<<opt10_rsize;
    if(backend.wvalid&&backend.wready)opt10_write_bytes+=$countones(backend.wstrb);
    if(`OC.dma_valid&&`OC.dma_ready)
      $fwrite(opt10_state_fd,"%0d,CMD,%0d,%0d,%h,%0d,%0d,%h\n",cycles,launches,`OC.dma_write,`OC.dma_address,`OC.dma_size,`OC.dma_len,`OC.dma_scratch);
    if(`OC.dma_result_valid&&`OC.dma_result_ready)
      $fwrite(opt10_state_fd,"%0d,RESULT,%0d,%0d\n",cycles,launches,`OC.dma_resp);
    if(d_arvalid&&d_arready)
      $fwrite(opt10_state_fd,"%0d,HMAR,%0d,%h,%0d,%0d\n",cycles,launches,d_araddr,d_arlen,owner);
    if(d_awvalid&&d_awready)
      $fwrite(opt10_state_fd,"%0d,HMAW,%0d,%h,%0d,%0d\n",cycles,launches,d_awaddr,d_awlen,owner);
    if(d_wready)
      $fwrite(opt10_state_fd,"%0d,HMW,%0d,%0d,%h,%0d\n",cycles,launches,d_wlast,d_wstrb,owner);
    if(int'(`OC.state)!=opt10_previous_state)begin
      $fwrite(opt10_state_fd,"%0d,STATE,%0d,%s,%s,%0d,%0d,%0d\n",cycles,launches,`OC.state.name(),`OC.return_state.name(),`OC.phase,`OC.restoring,`OC.row);
      opt10_previous_state=int'(`OC.state);
    end
    if(`OC.completion_valid&&`OC.completion_ready)begin
      $fwrite(opt10_fd,"%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d\n",
        cycles,launches,$signed(`OC.status),`OC.ticks,`OC.load_ticks,`OC.compute_ticks,`OC.write_ticks,`OC.restore_ticks,`OC.payload_read,`OC.payload_write,
        opt10_ticks,opt10_load,opt10_compute,opt10_write,opt10_restore,opt10_read_bytes,opt10_write_bytes,
        opt10_scratch_dma,opt10_scratch_control,opt10_shared_requests,soc.compute.ce.dma_read_bytes,soc.compute.ce.dma_write_bytes);
      $fflush(opt10_fd);$fflush(opt10_state_fd);
    end
    if(completed)begin $fflush(opt10_fd);$fflush(opt10_state_fd);end
  end
`undef OC
