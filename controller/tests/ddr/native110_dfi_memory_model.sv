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

