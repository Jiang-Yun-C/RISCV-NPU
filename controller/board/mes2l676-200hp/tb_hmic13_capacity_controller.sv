`timescale 1ns/1ps
// Synthetic DFI memory, not a DRAM/PHY/calibration model. Decode real controller
// row/bank/column commands and byte masks, then return stored payload.
module hmic13_dfi_memory_model(
 input clk,rst_n,
 input [59:0] address,
 input [11:0] bank,
 input [3:0] cs_n,ras_n,cas_n,we_n,wrdata_en,
 input [255:0] wrdata,
 input [31:0] wrmask,
 output [255:0] rddata,
 output rdvalid
);
 reg [14:0] open_row[0:7];
 reg [31:0] memory[0:1023];
 reg [27:0] write_addresses[0:2047];
 reg [255:0] read_delay[0:6];
 reg [6:0] valid_delay;
 integer write_tail=0,write_head=0,piece=0;
 integer phase,lane,byte_lane,k,read_count;
 reg [27:0] word_address;
 reg [14:0] ca;
 reg [2:0] ba;
 reg [255:0] read_value;
 assign rddata=read_delay[6];
 assign rdvalid=valid_delay[6];
 initial begin
  valid_delay=0;
  for(k=0;k<1024;k=k+1) memory[k]=0;
  for(k=0;k<8;k=k+1) open_row[k]=0;
  for(k=0;k<7;k=k+1) read_delay[k]=0;
 end
 always @(posedge clk) begin
  if(!rst_n) begin write_tail=0;write_head=0;piece=0;valid_delay<=0; end
  else begin
   read_count=0;read_value=0;
   for(phase=0;phase<4;phase=phase+1) begin
    ca=address[phase*15+:15];ba=bank[phase*3+:3];
    if(!cs_n[phase]) begin
     if(!ras_n[phase] && cas_n[phase] && we_n[phase]) open_row[ba]=ca;
     if(ras_n[phase] && !cas_n[phase] && !we_n[phase]) begin
      if(write_tail==2048) $fatal(1,"DFI write command fixture overflow");
      write_addresses[write_tail]={open_row[ba],ba,ca[9:0]};write_tail=write_tail+1;
     end
     if(ras_n[phase] && !cas_n[phase] && we_n[phase]) begin
      word_address={open_row[ba],ba,ca[9:0]};
      if(word_address+7>=1024) $fatal(1,"Read outside explicit4KiB DFI fixture");
      for(lane=0;lane<8;lane=lane+1) read_value[lane*32+:32]=memory[word_address+lane];
      read_count=read_count+1;
     end
    end
   end
   for(phase=0;phase<4;phase=phase+1) if(wrdata_en[phase]) begin
    if(write_head>=write_tail) $fatal(1,"DFI payload before WRITE command");
    word_address=write_addresses[write_head]+piece*2;
    if(word_address+1>=1024) $fatal(1,"Write outside explicit4KiB DFI fixture");
    for(lane=0;lane<2;lane=lane+1)
     for(byte_lane=0;byte_lane<4;byte_lane=byte_lane+1)
      if(!wrmask[phase*8+lane*4+byte_lane])
       memory[word_address+lane][byte_lane*8+:8]=wrdata[phase*64+lane*32+byte_lane*8+:8];
    if(piece==3) begin piece=0;write_head=write_head+1;end else piece=piece+1;
   end
   if(read_count>1) $fatal(1,"DFI fixture cannot combine multiple READ commands per core cycle");
   valid_delay<={valid_delay[5:0],read_count!=0};
   read_delay[0]<=read_value;
   for(k=1;k<7;k=k+1) read_delay[k]<=read_delay[k-1];
  end
 end
endmodule

module tb_hmic13_capacity_controller;
 reg clk=0,rst_n=0;
 always #5.333 clk=~clk;
 wire init_done,awready,arready,wready,wlast,rvalid,rlast;
 wire [3:0] rid,wid,awlen,arlen;
 wire [27:0] awaddr,araddr;
 wire awvalid,arvalid;
 wire [255:0] wdata,rdata;
 wire [31:0] wstrb,errors,passes,first_error,phase;
 wire full_verified,masks_verified,failed;
 ddr_capacity_bist #(.MEM_SPACE_AW(10),.WRITE_DRAIN_CYCLES(64),.STALL_LIMIT(10000)) bist (
  .clk(clk),.rst_n(rst_n),.ddr_init_done(init_done),
  .axi_awaddr(awaddr),.axi_araddr(araddr),.axi_awlen(awlen),.axi_arlen(arlen),
  .axi_awvalid(awvalid),.axi_arvalid(arvalid),.axi_awready(awready),.axi_arready(arready),
  .axi_wdata(wdata),.axi_wstrb(wstrb),.axi_wready(wready),.axi_wlast(wlast),
  .axi_rdata(rdata),.axi_rvalid(rvalid),.axi_rlast(rlast),.axi_rid(rid),
  .errors(errors),.verified_passes(passes),.first_error_word_address(first_error),
  .full_range_verified(full_verified),.byte_masks_verified(masks_verified),
  .phase_status(phase),.failed(failed)
 );
 hmic_probe dut (
  .ref_clk(clk),.resetn(rst_n),.ddr_init_done(init_done),
  .axi_awaddr(awaddr),.axi_awuser_ap(1'b1),.axi_awuser_id(4'd0),
  .axi_awlen(awlen),.axi_awready(awready),.axi_awvalid(awvalid),
  .axi_wdata(wdata),.axi_wstrb(wstrb),.axi_wready(wready),.axi_wusero_id(wid),.axi_wusero_last(wlast),
  .axi_araddr(araddr),.axi_aruser_ap(1'b1),.axi_aruser_id(4'd0),
  .axi_arlen(arlen),.axi_arready(arready),.axi_arvalid(arvalid),
  .axi_rdata(rdata),.axi_rid(rid),.axi_rlast(rlast),.axi_rvalid(rvalid),
  .apb_clk(clk),.apb_rst_n(rst_n),.apb_sel(1'b0),.apb_enable(1'b0),
  .apb_addr(8'd0),.apb_write(1'b0),.apb_wdata(16'd0)
 );
 GTP_GRS GRS_INST(.GRS_N(rst_n));
 integer write_beats=0,read_beats=0;
 always @(posedge clk) if(init_done) begin
  if(wready)write_beats=write_beats+1;
  if(rvalid)read_beats=read_beats+1;
  if(failed) $fatal(1,"HMIC_CAPACITY_CONTROLLER_FAIL phase=%0h errors=%0d first_error=%0h read=%0h expected=%0h",phase,errors,first_error,rdata,bist.expected_read);
 end
 initial begin
  repeat(20) @(negedge clk);rst_n=1;
  wait(passes==2);@(negedge clk);
  if(errors || !full_verified || !masks_verified || write_beats!=320 || read_beats!=320)
   $fatal(1,"HMIC capacity controller accounting mismatch");
  $display("HMIC13_CAPACITY_CONTROLLER_MODEL_PASS passes=%0d write_beats=%0d read_beats=%0d BYTE_STROBES=32 MODEL_BYTES=4096 PHY_STUB=1 BOARD_TEST=0",passes,write_beats,read_beats);
  $finish;
 end
 initial begin #1000000;$fatal(1,"HMIC capacity controller fixture timeout");end
endmodule
