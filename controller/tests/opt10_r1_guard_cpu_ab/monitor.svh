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
