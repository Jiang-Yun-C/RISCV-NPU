
  integer fullgraph_linear_fd;
  longint unsigned fgt=0,fgl=0,fgc=0,fgw=0,fgr=0;
  initial fullgraph_linear_fd=$fopen("linear.csv","w");
  always @(posedge clk)if(!reset)begin
    if(soc.compute.ce.control.linear_control.submit)begin fgt=0;fgl=0;fgc=0;fgw=0;fgr=0;end
    if(!soc.compute.ce.control.linear_control.engine_idle&&!soc.compute.ce.control.linear_control.completion_valid)begin
      fgt++;
      case(soc.compute.ce.control.linear_control.phase)1:fgl++;2:fgc++;3:fgw++;default:;endcase
      if(soc.compute.ce.control.linear_control.restoring)fgr++;
    end
    if(soc.compute.ce.control.linear_control.completion_valid&&soc.compute.ce.control.linear_control.completion_ready)begin
      $fwrite(fullgraph_linear_fd,"LCOMPLETE,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d\n",cycles,launches,$signed(soc.compute.ce.control.linear_control.status),
        soc.compute.ce.control.linear_control.ticks,soc.compute.ce.control.linear_control.load_ticks,soc.compute.ce.control.linear_control.compute_ticks,soc.compute.ce.control.linear_control.write_ticks,soc.compute.ce.control.linear_control.restore_ticks,
        soc.compute.ce.control.linear_control.payload_read,soc.compute.ce.control.linear_control.payload_write,fgt,fgl,fgc,fgw,fgr);
      $fflush(fullgraph_linear_fd);
    end
  end
