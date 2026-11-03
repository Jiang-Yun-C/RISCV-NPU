`timescale 1ns/1ps
module tb_combo;
reg clk=0;always #4 clk=~clk;reg reset_n=0;
integer owner=0,outstanding=0;integer pvjobs=0,sfujobs=0;
reg we=0,re=0;reg[15:0] address=0;reg[31:0] wdata=0;wire[31:0] rdata;
wire ps,pm,gs,gm,fr,fv;wire[31:0] pa,pb,ga,gb,fy;
reg gstart=0,gack=0,load_valid=0;reg[127:0] gate_data=0,up_data=0;reg[5:0] peek=0;
wire load_ready,gvalid,gidle,gerror;wire[127:0] fp_data,q_data;wire[31:0] scale;wire[63:0] cycles;
t27_pv_external pv(.clk,.reset_n,.we,.re,.address,.wdata,.rdata,.resource_start(ps),.resource_mul(pm),.resource_a(pa),.resource_b(pb),.resource_ready(fr&&owner==1),.resource_valid(fv&&owner==1),.resource_result(fy));
t27_sfu_external #(.LANES(2)) sg(.clk,.reset_n,.start(gstart),.ack(gack),.length(7'd64),.mode(4'd0),.quantize_result(1'b0),.pad_full(1'b1),.scalar(32'b0),.load_valid,.load_ready,.gate_data,.up_data,.valid(gvalid),.idle(gidle),.error(gerror),.peek,.fp_data,.q_data,.scale,.cycles,
.resource_start(gs),.resource_mul(gm),.resource_a(ga),.resource_b(gb),.resource_ready(fr&&owner==2),.resource_valid(fv&&owner==2),.resource_result(fy));
nx_opt11_fp shared_fp(.clk,.reset_n,.start(owner==1?ps:owner==2?gs:1'b0),.multiply(owner==1?pm:gm),.a(owner==1?pa:ga),.b(owner==1?pb:gb),.ready(fr),.valid(fv),.result(fy));
integer last_owner=0;integer events_fd,numeric_fd,requests=0,responses=0;
initial begin events_fd=$fopen("events.csv","w");numeric_fd=$fopen("numeric.csv","w");end
always @(posedge clk)if(reset_n)begin
 if((ps&&owner!=1)||(gs&&owner!=2))$fatal(1,"wrong arithmetic owner");
 if((ps||gs)&&fv)outstanding<=outstanding;else if(ps||gs)outstanding<=outstanding+1;else if(fv)outstanding<=outstanding-1;
 if(owner!=last_owner&&outstanding!=0)$fatal(1,"owner changed before FP drain");
 if(pv.busy&&owner!=1)$fatal(1,"PV scratch ownership");
 if(load_valid&&owner!=2)$fatal(1,"SFU scratch ownership");
 if(ps||gs)begin requests++;$fwrite(events_fd,"%0t,REQUEST,%0d,%0d,%h,%h\n",$time,owner,owner==1?pm:gm,owner==1?pa:ga,owner==1?pb:gb);end
 if(fv)begin responses++;$fwrite(events_fd,"%0t,RESPONSE,%0d,0,%h,0\n",$time,owner,fy);end
 if(owner!=last_owner)$fwrite(events_fd,"%0t,OWNER,%0d,%0d,0,0\n",$time,owner,outstanding);
 last_owner<=owner;
end
task automatic wr(input integer a,input reg[31:0] x);begin @(negedge clk);we=1;address=16'(a);wdata=x;@(negedge clk);we=0;end endtask
task automatic release_owner;begin
 @(negedge clk);if(outstanding!=0||!gidle||pv.busy||pv.done)$fatal(1,"undrained owner release");owner=0;@(negedge clk);
end endtask
reg[31:0] pp[0:314],vv[0:2879],want[0:447];
reg[31:0] gg[0:255],uu[0:255],aa[0:255],qq[0:63],ss[0:3];
integer length,n,fd,j;
initial begin
 fd=$fopen("combination.txt","w");
 $readmemh("data9.hex",gg);$readmemh("data10.hex",uu);$readmemh("data11.hex",aa);$readmemh("data12.hex",qq);$readmemh("data13.hex",ss);
 repeat(20)@(negedge clk);reset_n=1;
 for(integer round=0;round<3;round++)begin
  length=round==0?32:round==1?33:45;n=round==0?32:64;
  case(round)
   0:begin $readmemh("data0.hex",pp);$readmemh("data1.hex",vv);$readmemh("data2.hex",want);end
   1:begin $readmemh("data3.hex",pp);$readmemh("data4.hex",vv);$readmemh("data5.hex",want);end
   2:begin $readmemh("data6.hex",pp);$readmemh("data7.hex",vv);$readmemh("data8.hex",want);end
  endcase
  owner=1;
  for(integer h=0;h<7;h++)for(integer t=0;t<length;t++)wr(4096+4*(h*64+t),pp[h*length+t]);
  for(integer d=0;d<64;d++)for(integer t=0;t<length;t++)wr(4096+4*(448+d*64+t),vv[d*length+t]);
  wr(4,length);wr(8,7);wr(12,n);wr(20,round+1);wr(0,1);
  wait(pv.done);@(negedge clk);
  for(integer i=0;i<448;i++)begin $fwrite(numeric_fd,"PV,%0d,%0d,%h\n",round,i,pv.mem[4608+i]);if(pv.mem[4608+i]!==want[i])$fatal(1,"PV numeric round=%0d i=%0d",round,i);end
  wr(24,round+1);pvjobs++;release_owner();
  owner=2;
  for(integer row=0;row<4;row++)begin
   @(negedge clk);gstart=1;@(negedge clk);gstart=0;
   wait(load_ready);
   for(integer i=0;i<64;i+=2)begin
    gate_data={64'b0,gg[row*64+i+1],gg[row*64+i]};up_data={64'b0,uu[row*64+i+1],uu[row*64+i]};load_valid=1;
    @(negedge clk);
   end
   load_valid=0;wait(gvalid);@(negedge clk);if(gerror||scale!==ss[row])$fatal(1,"SFU scale/error");
   for(integer i=0;i<64;i++)begin
    peek=6'(i);repeat(2)@(negedge clk);$fwrite(numeric_fd,"FP,%0d,%0d,%h\n",round,row*64+i,fp_data[31:0]);if(fp_data[31:0]!==aa[row*64+i])$fatal(1,"SFU FP numeric");
   end
   for(integer i=0;i<16;i++)begin
    peek=6'(i*4);repeat(2)@(negedge clk);$fwrite(numeric_fd,"AQ,%0d,%0d,%h\n",round,row*16+i,q_data[31:0]);if(q_data[31:0]!==qq[row*16+i])$fatal(1,"SFU Aq numeric");
    // Same backing PV scratch is reused only after PV ACK, under SFU owner.
    wr(4096+4*(row*17+i),q_data[31:0]);
   end
   wr(4096+4*(row*17+16),scale);
   $fwrite(numeric_fd,"SA,%0d,%0d,%h\n",round,row,scale);
   for(integer i=0;i<16;i++)if(pv.mem[row*17+i]!==qq[row*16+i])$fatal(1,"test scratch Aq readback");
   if(pv.mem[row*17+16]!==ss[row])$fatal(1,"test scratch Sa readback");
   gack=1;@(negedge clk);gack=0;wait(gidle);sfujobs++;
  end
  release_owner();$fwrite(fd,"ROUND %0d len=%0d PV448words SFU4x64 Aq256B Sa16B owners_drained\n",round,length);
 end
 if(outstanding||owner||requests!=responses)$fatal(1,"terminal owner");$fwrite(fd,"PASS jobs=%0d/%0d FP_drain=0 owner=0\n",pvjobs,sfujobs);$fwrite(fd,"REQUESTS %0d RESPONSES %0d\n",requests,responses);$fclose(events_fd);$fclose(numeric_fd);$fclose(fd);$finish;
end
initial begin #100000000;$fatal(1,"combo timeout");end
endmodule
