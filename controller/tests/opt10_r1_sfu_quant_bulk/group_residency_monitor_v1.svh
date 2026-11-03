// Passive diagnostics only. No force, deposits, stalls or DUT input changes.
`define GP soc.compute.ce.control.linear_control
integer gp_fd,gp_i;
longint unsigned gp_states[0:127],gp_phases[0:3],gp_total;
longint unsigned gp_dot_beats,gp_dot_results,gp_fp_accepts,gp_fp_results,gp_fp_send_stalls;
initial gp_fd=$fopen("group-residency.csv","w");
always @(posedge clk)if(!reset)begin
  if(`GP.submit)begin
    gp_total=0;gp_dot_beats=0;gp_dot_results=0;gp_fp_accepts=0;gp_fp_results=0;gp_fp_send_stalls=0;
    for(gp_i=0;gp_i<128;gp_i=gp_i+1)gp_states[gp_i]=0;
    for(gp_i=0;gp_i<4;gp_i=gp_i+1)gp_phases[gp_i]=0;
  end
  if(!`GP.engine_idle&&!`GP.completion_valid)begin
    gp_total++;gp_states[int'(`GP.state)]++;gp_phases[int'(`GP.phase)]++;
    if(`GP.dot_request_valid&&`GP.dot_ready)gp_dot_beats++;
    if(`GP.dot_valid)gp_dot_results++;
    if(`GP.fp_request_valid&&`GP.fp_ready)gp_fp_accepts++;
    if(`GP.fp_valid)gp_fp_results++;
    if(`GP.state==51&&!`GP.fp_ready)gp_fp_send_stalls++;
    if(`GP.row<2&&`GP.g<3&&`GP.phase==2)
      $fwrite(gp_fd,"TRACE,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d\n",cycles,`GP.state,`GP.return_state,`GP.row,`GP.g,`GP.beat,`GP.phase,`GP.restoring,`GP.dot_request_valid,`GP.dot_ready,`GP.dot_valid,`GP.dot_live,`GP.fp_request_valid,`GP.fp_ready,`GP.fp_valid,`GP.fp_idle,`GP.fp_abort_pending,`GP.ram_en,`GP.ram_address,`GP.local_read_address);
  end
  if(`GP.dma_valid&&`GP.dma_ready)
    $fwrite(gp_fd,"DMA,%0d,%0d,%0d,%0d,%0d,%h,%0d,%0d,%h\n",cycles,`GP.return_state,`GP.row,`GP.g,`GP.dma_write,`GP.dma_address,`GP.dma_size,`GP.dma_len,`GP.dma_scratch);
  if(`GP.completion_valid&&`GP.completion_ready)begin
    $fwrite(gp_fd,"COMPLETE,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d\n",cycles,$signed(`GP.status),`GP.d[15],`GP.d[16],`GP.d[17],`GP.groups,`GP.ticks,`GP.load_ticks,`GP.compute_ticks,`GP.write_ticks,`GP.restore_ticks,`GP.payload_read,`GP.payload_write,gp_total,gp_dot_beats,gp_dot_results);
    $fwrite(gp_fd,"FP,%0d,%0d,%0d\n",gp_fp_accepts,gp_fp_results,gp_fp_send_stalls);
    for(gp_i=0;gp_i<128;gp_i=gp_i+1)if(gp_states[gp_i]!=0)$fwrite(gp_fd,"STATECOUNT,%0d,%0d\n",gp_i,gp_states[gp_i]);
    for(gp_i=0;gp_i<4;gp_i=gp_i+1)$fwrite(gp_fd,"PHASECOUNT,%0d,%0d\n",gp_i,gp_phases[gp_i]);
    $fflush(gp_fd);
  end
end
`undef GP
