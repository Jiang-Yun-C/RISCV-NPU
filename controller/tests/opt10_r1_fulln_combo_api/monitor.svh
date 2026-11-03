// Passive complete backend/native ledger, with a post-inspection close.
wire api_transport_drained=soc.native_safely_drained&&!soc.native_pending&&!soc.upstream_pending&&backend_idle;
longint unsigned api_activity=0;
integer api_fd;
initial begin api_fd=$fopen("api-transport.csv","w");if(!api_fd)$fatal(1,"api ledger open");end
always @(posedge clk)if(!reset)begin
 if(backend.arvalid&&backend.arready)begin api_activity++;$fwrite(api_fd,"%0d,AR,%h,%h,%h,%h,%h\n",cycles,backend.araddr,backend.arlen,backend.arsize,backend.arid,backend.arburst);end
 if(backend.rvalid&&backend.rready)begin api_activity++;$fwrite(api_fd,"%0d,R,%h,%h,%h,%h,0\n",cycles,backend.rdata,backend.rid,backend.rresp,backend.rlast);end
 if(backend.awvalid&&backend.awready)begin api_activity++;$fwrite(api_fd,"%0d,AW,%h,%h,%h,%h,%h\n",cycles,backend.awaddr,backend.awlen,backend.awsize,backend.awid,backend.awburst);end
 if(backend.wvalid&&backend.wready)begin api_activity++;$fwrite(api_fd,"%0d,W,%h,%h,%h,0,0\n",cycles,backend.wdata,backend.wstrb,backend.wlast);end
 if(backend.bvalid&&backend.bready)begin api_activity++;$fwrite(api_fd,"%0d,B,%h,%h,0,0,0\n",cycles,backend.bid,backend.bresp);end
 if(d_arvalid&&d_arready)begin api_activity++;$fwrite(api_fd,"%0d,NAR,%h,%h,%h,0,0\n",cycles,d_araddr,d_arlen,d_arid);end
 if(d_rvalid)begin api_activity++;$fwrite(api_fd,"%0d,NR,%h,%h,%h,0,0\n",cycles,d_rdata,d_rid,d_rlast);end
 if(d_awvalid&&d_awready)begin api_activity++;$fwrite(api_fd,"%0d,NAW,%h,%h,%h,0,0\n",cycles,d_awaddr,d_awlen,d_awid);end
 if(d_wready)begin api_activity++;$fwrite(api_fd,"%0d,NW,%h,%h,%h,0,0\n",cycles,d_wdata,d_wstrb,d_wlast);end
 if(soc.compute.ce.regs.publishing&&soc.compute.ce.regs.publish_index==39)
  $fwrite(api_fd,"%0d,COMMIT,%h,%h,%h,%h,%h\n",cycles,soc.compute.ce.control.linear_control.ticks,soc.compute.ce.control.linear_control.load_ticks,soc.compute.ce.control.linear_control.compute_ticks,soc.compute.ce.control.linear_control.write_ticks,soc.compute.ce.control.linear_control.restore_ticks);
 if(completed)$fflush(api_fd);
end
`define API_CTRL soc.compute.ce.control.linear_control
integer consumer_fd;
initial begin consumer_fd=$fopen("consumer.csv","w");if(!consumer_fd)$fatal(1,"consumer ledger open");end
longint unsigned api_state_ticks[0:255],api_overlap_w_dot=0,api_overlap_w_fp=0,api_overlap_w_both=0;
logic[255:0] api_state_previous='1;
wire[255:0] api_state_sample={128'b0,32'(`API_CTRL.state),18'(`API_CTRL.row),7'(`API_CTRL.g),
 `API_CTRL.counter_enable,`API_CTRL.phase,`API_CTRL.restoring,`API_CTRL.dot_request_valid,`API_CTRL.dot_ready,
 `API_CTRL.fp_request_valid,`API_CTRL.fp_ready,`API_CTRL.dma_valid,`API_CTRL.dma_write,`API_CTRL.dma_ready,
 `API_CTRL.dma_result_valid,`API_CTRL.dma_result_ready,`API_CTRL.dma_idle,`API_CTRL.ram_en,`API_CTRL.transport_drained};
initial for(integer api_s=0;api_s<256;api_s++)api_state_ticks[api_s]=0;
always @(posedge clk)if(!reset)begin
 if(`API_CTRL.counter_clear)begin
  for(integer api_s=0;api_s<256;api_s++)api_state_ticks[api_s]=0;
  api_overlap_w_dot=0;api_overlap_w_fp=0;api_overlap_w_both=0;
 end else if(`API_CTRL.counter_enable)api_state_ticks[int'(`API_CTRL.state)]++;
 if(api_state_sample!==api_state_previous)begin
  $fwrite(consumer_fd,"%0d,STATE,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d,%0d\n",cycles,
   `API_CTRL.state,`API_CTRL.row,`API_CTRL.g,`API_CTRL.counter_enable,`API_CTRL.phase,`API_CTRL.restoring,
   `API_CTRL.dot_request_valid,`API_CTRL.dot_ready,`API_CTRL.fp_request_valid,`API_CTRL.fp_ready,
   `API_CTRL.dma_valid,`API_CTRL.dma_write,`API_CTRL.dma_ready,`API_CTRL.dma_result_valid,`API_CTRL.dma_result_ready,
   `API_CTRL.dma_idle,`API_CTRL.ram_en,`API_CTRL.transport_drained);
  api_state_previous<=api_state_sample;
 end
 if(`API_CTRL.dot_request_valid&&`API_CTRL.dot_ready)
  $fwrite(consumer_fd,"%0d,DOT_IN,%0d,%0d,%0d,%h,%h,%h,%h,%h\n",cycles,`API_CTRL.row,`API_CTRL.g,`API_CTRL.beat,`API_CTRL.index,`API_CTRL.epoch,`API_CTRL.dot_keep,`API_CTRL.dot.aq_i,`API_CTRL.dot.wq_i);
 if(`API_CTRL.dot_valid)
  $fwrite(consumer_fd,"%0d,DOT_OUT,%0d,%h,%h,%h,%h,%h\n",cycles,`API_CTRL.row,`API_CTRL.dot_tag,`API_CTRL.dot_epoch,`API_CTRL.dot_result,`API_CTRL.dot_bad,`API_CTRL.dot_protocol);
 if(`API_CTRL.fp_request_valid&&`API_CTRL.fp_ready)
  $fwrite(consumer_fd,"%0d,FP_IN,%0d,%0d,%h,%h,%h,%h,%h,%h\n",cycles,`API_CTRL.row,`API_CTRL.g,`API_CTRL.index,`API_CTRL.epoch,`API_CTRL.dot_value,`API_CTRL.sa_value,`API_CTRL.sw_value,`API_CTRL.y[`API_CTRL.token]);
 if(`API_CTRL.fp_valid)
  $fwrite(consumer_fd,"%0d,FP_OUT,%0d,%h,%h,%h,%h,%h,%h,%h,%h\n",cycles,`API_CTRL.row,`API_CTRL.fp_tag,`API_CTRL.fp_epoch,`API_CTRL.fp_p,`API_CTRL.fp_v,`API_CTRL.fp_partial,`API_CTRL.fp_status,`API_CTRL.fp_flags,`API_CTRL.fp_last);
 if(`API_CTRL.completion_valid&&`API_CTRL.completion_ready)begin
  $fwrite(consumer_fd,"%0d,COMPLETE,%0d,%0d,%0d,%h,%h\n",cycles,$signed(`API_CTRL.status),`API_CTRL.rows,`API_CTRL.tiles,`API_CTRL.epoch,`API_CTRL.generation);
  for(integer api_s=0;api_s<256;api_s++)if(api_state_ticks[api_s]!=0)$fwrite(consumer_fd,"%0d,HIST,%0d,%0d\n",cycles,api_s,api_state_ticks[api_s]);
  $fwrite(consumer_fd,"%0d,OVERLAP,%0d,%0d,%0d\n",cycles,api_overlap_w_dot,api_overlap_w_fp,api_overlap_w_both);
 end
 if(soc.compute.ce.a_en&&soc.compute.ce.b_en)$fatal(1,"single scratch ownership collision");
 if(completed)$fflush(consumer_fd);
end
`ifdef API_W_SW_VARIANT
logic[1:0] api_last_held=0,api_last_certificate=0;
logic api_last_sw_certificate=0,api_last_sw_bad=0;
always @(posedge clk)if(!reset)begin
 if(`API_CTRL.counter_enable&&`API_CTRL.w_command_pending)begin
  if(`API_CTRL.dot_live)api_overlap_w_dot++;
  if(!`API_CTRL.fp_idle)api_overlap_w_fp++;
  if(`API_CTRL.dot_live&&!`API_CTRL.fp_idle)api_overlap_w_both++;
 end
 if(`API_CTRL.stream_accept&&`API_CTRL.w_issue)
  $fwrite(consumer_fd,"%0d,W_CMD,%0d,%0d,%0d,%0d,%h,%h,%h,%h,%h\n",cycles,`API_CTRL.row,`API_CTRL.w_offer_group,`API_CTRL.w_count,`API_CTRL.dma_capture_bank,`API_CTRL.capture_command_tag,`API_CTRL.capture_owner,`API_CTRL.epoch,`API_CTRL.generation,`API_CTRL.dma_address);
 if(`API_CTRL.stream_accept&&`API_CTRL.sw_issue)
  $fwrite(consumer_fd,"%0d,SW_FRAG,%0d,%0d,%0d,%h,%h,%h,%h\n",cycles,`API_CTRL.row,`API_CTRL.sw_filled,`API_CTRL.sw_command_words,`API_CTRL.dma_address,`API_CTRL.dma_len,`API_CTRL.dma_size,`API_CTRL.capture_owner);
 if(`API_CTRL.sw_start)
  $fwrite(consumer_fd,"%0d,SW_START,%0d,%0d,%0d,%h,%h,%h\n",cycles,`API_CTRL.row,`API_CTRL.stream_rows,`API_CTRL.groups,`API_CTRL.stream_owner,`API_CTRL.epoch,`API_CTRL.generation);
 if(`API_CTRL.sw_certificate!=api_last_sw_certificate||`API_CTRL.sw_bad!=api_last_sw_bad)
  $fwrite(consumer_fd,"%0d,SW_CERT,%0d,%0d,%0d,%h,%h,%h,%h,%h,%h,%h\n",cycles,`API_CTRL.sw_first_row,`API_CTRL.sw_rows,`API_CTRL.sw_groups,`API_CTRL.sw_filled,`API_CTRL.sw_certificate,`API_CTRL.sw_bad,`API_CTRL.sw_owner,`API_CTRL.sw_epoch,`API_CTRL.sw_generation,`API_CTRL.sw_fragment_pending);
 if(`API_CTRL.capture_held!=api_last_held||`API_CTRL.capture_certificate!=api_last_certificate)
  $fwrite(consumer_fd,"%0d,BANK_STATE,%h,%h,%h,%h,%h,%h,%h\n",cycles,`API_CTRL.capture_held,`API_CTRL.capture_certificate,`API_CTRL.capture_bad,`API_CTRL.capture_counts,`API_CTRL.w_tags[0],`API_CTRL.w_tags[1],`API_CTRL.capture_owner);
 for(integer api_bank=0;api_bank<2;api_bank++)if(`API_CTRL.capture_release[api_bank])begin
  $fwrite(consumer_fd,"%0d,W_RELEASE,%0d,%0d,%0d,%0d,%h,%h,%h,%h\n",cycles,api_bank,`API_CTRL.row,`API_CTRL.g,`API_CTRL.beat,`API_CTRL.w_tags[api_bank],`API_CTRL.capture_owner,`API_CTRL.epoch,`API_CTRL.generation);
  if(!`API_CTRL.abort_now&&`API_CTRL.stream_active&&!
    (`API_CTRL.dot_request_valid&&`API_CTRL.dot_ready&&`API_CTRL.beat==3&&
      `API_CTRL.g+1==`API_CTRL.w_first[api_bank]+`API_CTRL.w_groups[api_bank]))$fatal(1,"W lease released before actual final DOT consumption");
 end
 if(`API_CTRL.stream_active&&`API_CTRL.dma_valid&&`API_CTRL.dma_ready&&`API_CTRL.dma_write)begin
  $fwrite(consumer_fd,"%0d,PUBLISH_BEGIN,%0d,%h,%h,%h,%h\n",cycles,`API_CTRL.row,`API_CTRL.dma_address,`API_CTRL.capture_held,`API_CTRL.transport_drained,`API_CTRL.capture_owner);
  if(`API_CTRL.capture_held!==0||!`API_CTRL.transport_drained)$fatal(1,"publisher entered before W lease/transport handoff");
 end
 if(`API_CTRL.stream_active&&!`API_CTRL.abort_now&&`API_CTRL.dot_request_valid&&`API_CTRL.dot_ready&&
   (`API_CTRL.capture_mask!==16'hffff||!`API_CTRL.sw_certificate))$fatal(1,"DOT accepted uncertified W/Sw");
 api_last_held<=`API_CTRL.capture_held;api_last_certificate<=`API_CTRL.capture_certificate;
 api_last_sw_certificate<=`API_CTRL.sw_certificate;api_last_sw_bad<=`API_CTRL.sw_bad;
end
`endif
`undef API_CTRL
