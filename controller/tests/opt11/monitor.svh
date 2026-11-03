// Passive observations. Arithmetic and native DMA remain the real DUT.
`define VC soc.compute.ce.control.vector_control
  int opt11_fd;
  longint unsigned measured_ticks=0,measured_load=0,measured_compute=0,measured_write=0;
  longint unsigned measured_read=0,measured_written=0,last_native_write=0;
  int read_size=0;
  initial opt11_fd=$fopen("vector.csv","w");
  always @(posedge clk)if(!reset)begin
    if(`VC.submit)begin
      measured_ticks=0;measured_load=0;measured_compute=0;measured_write=0;measured_read=0;measured_written=0;
    end
    if(!`VC.engine_idle&&!`VC.completion_valid)begin
      measured_ticks++;
      case(`VC.phase)1:measured_load++;2:measured_compute++;3:measured_write++;default:;endcase
    end
    if(soc.compute.ce.a_en&&soc.compute.ce.b_en)$fatal(1,"OPT11 single scratch port collision");
    if(backend.arvalid&&backend.arready)read_size=backend.arsize;
    if(soc.compute.ce.control.vector_selected)begin
      if(backend.rvalid&&backend.rready)measured_read+=1<<read_size;
      if(backend.wvalid&&backend.wready)measured_written+=$countones(backend.wstrb);
    end
    if(d_wready&&d_wlast)last_native_write=cycles;
    if(report_tag[15:0]==20)begin
      if(d_arvalid&&d_arready)$fwrite(opt11_fd,"NREAD,%0d,%0d,%0d\n",report_tag[31:16],(32'(d_arlen)+1)*32,owner);
      if(d_wready)$fwrite(opt11_fd,"NWRITE,%0d,%0d,%0d\n",report_tag[31:16],$countones(d_wstrb),owner);
    end
    if(backend.bvalid&&backend.bready&&backend.bresp==0)
      if(cycles-last_native_write<1024)$fatal(1,"OPT11 native drain shortened");
    if(`VC.dma_valid&&`VC.dma_ready)
      $fwrite(opt11_fd,"CMD,%0d,%0d,%0d,%h,%0d,%0d\n",cycles,launches,`VC.dma_write,`VC.dma_address,`VC.dma_size,`VC.dma_len);
    if(`VC.completion_valid&&`VC.completion_ready)begin
      $fwrite(opt11_fd,"COMPLETE,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d\n",cycles,launches,$signed(`VC.status),
        `VC.ticks,`VC.loads,`VC.computes,`VC.writes,`VC.read_bytes,`VC.write_bytes,
        measured_ticks,measured_load,measured_compute,measured_write,measured_read,measured_written);
      $fflush(opt11_fd);
    end
    if(completed)$fflush(opt11_fd);
  end
`undef VC
