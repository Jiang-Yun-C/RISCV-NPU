`timescale 1ns/1ps
module tb_cpu;
logic  timerInterrupt;
logic  externalInterrupt;
logic  softwareInterrupt;
wire  trace_predictor_ready;
wire  rom_enable;
wire [31:0] rom_address;
logic [31:0] rom_data;
wire  iAxi_ar_valid;
logic  iAxi_ar_ready;
wire [31:0] iAxi_ar_payload_addr;
wire [7:0] iAxi_ar_payload_len;
wire [1:0] iAxi_ar_payload_burst;
wire [3:0] iAxi_ar_payload_cache;
wire [2:0] iAxi_ar_payload_prot;
logic  iAxi_r_valid;
wire  iAxi_r_ready;
logic [31:0] iAxi_r_payload_data;
logic [1:0] iAxi_r_payload_resp;
logic  iAxi_r_payload_last;
wire  dAxi_aw_valid;
logic  dAxi_aw_ready;
wire [31:0] dAxi_aw_payload_addr;
wire [7:0] dAxi_aw_payload_len;
wire [2:0] dAxi_aw_payload_size;
wire [3:0] dAxi_aw_payload_cache;
wire [2:0] dAxi_aw_payload_prot;
wire  dAxi_w_valid;
logic  dAxi_w_ready;
wire [31:0] dAxi_w_payload_data;
wire [3:0] dAxi_w_payload_strb;
wire  dAxi_w_payload_last;
logic  dAxi_b_valid;
wire  dAxi_b_ready;
logic [1:0] dAxi_b_payload_resp;
wire  dAxi_ar_valid;
logic  dAxi_ar_ready;
wire [31:0] dAxi_ar_payload_addr;
wire [7:0] dAxi_ar_payload_len;
wire [2:0] dAxi_ar_payload_size;
wire [3:0] dAxi_ar_payload_cache;
wire [2:0] dAxi_ar_payload_prot;
logic  dAxi_r_valid;
wire  dAxi_r_ready;
logic [31:0] dAxi_r_payload_data;
logic [1:0] dAxi_r_payload_resp;
logic  dAxi_r_payload_last;
wire  trace_retire;
wire [31:0] trace_pc;
wire [31:0] trace_instruction;
wire  trace_stall;
wire  trace_branch;
wire [31:0] trace_branch_pc;
wire  trace_mispredict;
logic  clk;
logic  reset;
T09Cpu cpu(.*);
wire pv_we=dAxi_w_valid&&dAxi_w_ready&&wa[31:16]==16'h1002;
wire pv_re=dAxi_r_valid&&dAxi_r_ready&&da[31:16]==16'h1002;
wire [31:0] pv_rdata;
t27_pv_batch pv(.clk(clk),.reset_n(!reset),.we(pv_we),.re(pv_re),.address(pv_we?wa[15:0]:da[15:0]),.wdata(dAxi_w_payload_data),.rdata(pv_rdata));
integer pf;logic olddone=0;
initial pf=$fopen("pv-transactions.txt","w");
always @(posedge clk)if(!reset)begin
 if(pv_we&&wa[15:0]==0)$fwrite(pf,"SUBMIT %0d %0d %0d %0d %0d\n",cycles,pv.length,pv.heads,pv.padded,pv.request_seq);
 if(pv.done&&!olddone)$fwrite(pf,"COMPLETE %0d %0d %0d %0d %0d\n",cycles,pv.generation,pv.cycles,pv.muls,pv.adds);
 if(pv_we&&wa[15:0]==24)$fwrite(pf,"ACK %0d %0d\n",cycles,dAxi_w_payload_data);
 olddone<=pv.done;
end
// Isolated exact T09 CPU; deterministic local AXI memory, no DDR controller/PHY.
// Separate one-outstanding I/D read channels; one-outstanding AW/W/B channel.
// Firmware and tensor addresses preserve production SRAM/DDR region classes.
byte unsigned rom[65536],sram[65536],textmem[1048576],activ[262144],keys[327680],vals[327680];
function automatic byte unsigned read8(input logic[31:0] a);
    if(a>=32'h10000&&a<32'h20000)return rom[a-32'h10000];
    if(a>=32'h20000&&a<32'h30000)return sram[a-32'h20000];
    if(a>=32'hb4000000&&a<32'hb4100000)return textmem[a-32'hb4000000];
    if(a>=32'hac000000&&a<32'hac040000)return activ[a-32'hac000000];
    if(a>=32'ha8000000&&a<32'ha8050000)return keys[a-32'ha8000000];
    if(a>=32'ha8780000&&a<32'ha87d0000)return vals[a-32'ha8780000];
    $fatal(1,"unmapped read %h",a);return 0;
endfunction
task automatic write8(input logic[31:0] a,input byte unsigned v);
    if(a>=32'h10000&&a<32'h20000)rom[a-32'h10000]=v;
    else if(a>=32'h20000&&a<32'h30000)sram[a-32'h20000]=v;
    else if(a>=32'hb4000000&&a<32'hb4100000)textmem[a-32'hb4000000]=v;
    else if(a>=32'hac000000&&a<32'hac040000)activ[a-32'hac000000]=v;
    else if(a>=32'ha8000000&&a<32'ha8050000)keys[a-32'ha8000000]=v;
    else if(a>=32'ha8780000&&a<32'ha87d0000)vals[a-32'ha8780000]=v;
    else $fatal(1,"unmapped write %h",a);
endtask
function automatic logic[31:0] read32(input logic[31:0] a);
    for(int b=0;b<4;b++)read32[8*b+:8]=read8(a+b);
endfunction
logic ibusy=0,dbusy=0,wbusy=0;
logic[31:0] ia=0,da=0,wa=0;
int ilen=0,dlen=0,wlen=0;
longint cycles=0,retired=0,ireads=0,dreads=0,writes=0;
int max_cycles=150000000,fd,tag=0;
logic exit_pending=0;
logic[31:0] exit_code=0;
assign iAxi_ar_ready=!ibusy;
assign iAxi_r_valid=ibusy;
assign iAxi_r_payload_data=ibusy?read32(ia):32'b0;
assign iAxi_r_payload_resp=0;
assign iAxi_r_payload_last=ilen==0;
assign dAxi_ar_ready=!dbusy;
assign dAxi_r_valid=dbusy;
assign dAxi_r_payload_data=dbusy?(da[31:16]==16'h1002 ? pv_rdata:read32(da)):32'b0;
assign dAxi_r_payload_resp=0;
assign dAxi_r_payload_last=dlen==0;
assign dAxi_aw_ready=!wbusy&&!dAxi_b_valid;
assign dAxi_w_ready=wbusy&&!dAxi_b_valid;
assign dAxi_b_payload_resp=0;
always #4 clk=~clk;
initial begin
    string plan,path;int planfd,f,parsed,c;logic[31:0] addr;int size;string kind;
    clk=0;reset=1;timerInterrupt=0;externalInterrupt=0;softwareInterrupt=0;rom_data=0;dAxi_b_valid=0;
    if(!$value$plusargs("plan=%s",plan))$fatal(1,"missing plan");
    if($value$plusargs("max_cycles=%d",max_cycles))begin end
    planfd=$fopen(plan,"r");if(!planfd)$fatal(1,"plan open");
    while(!$feof(planfd))begin
        parsed=$fscanf(planfd,"%s %h %h %s\n",kind,addr,size,path);
        if(parsed==4)begin
            f=$fopen(path,"rb");if(!f)$fatal(1,"binary open %s",path);
            for(int i=0;i<size;i++)begin c=$fgetc(f);if(c<0)$fatal(1,"short binary");write8(addr+i,8'(c));end
            $fclose(f);
        end
    end
    $fclose(planfd);fd=$fopen("cpu-output.txt","w");
    repeat(20)@(negedge clk);reset=0;
end
always @(posedge clk)begin
    if(rom_enable)rom_data<=read32(rom_address);
    if(!reset)begin
        cycles<=cycles+1;if(trace_retire)retired<=retired+1;
        if(cycles>=max_cycles)$fatal(1,"cycle ceiling %d retired %d pc %h",cycles,retired,trace_pc);
        if(iAxi_ar_valid&&iAxi_ar_ready)begin ibusy<=1;ia<=iAxi_ar_payload_addr;ilen<=iAxi_ar_payload_len;end
        if(iAxi_r_valid&&iAxi_r_ready)begin ireads<=ireads+4;if(ilen==0)ibusy<=0;else begin ia<=ia+4;ilen<=ilen-1;end end
        if(dAxi_ar_valid&&dAxi_ar_ready)begin dbusy<=1;da<=dAxi_ar_payload_addr;dlen<=dAxi_ar_payload_len;end
        if(dAxi_r_valid&&dAxi_r_ready)begin dreads<=dreads+4;if(dlen==0)dbusy<=0;else begin da<=da+4;dlen<=dlen-1;end end
        if(dAxi_aw_valid&&dAxi_aw_ready)begin wbusy<=1;wa<=dAxi_aw_payload_addr;wlen<=dAxi_aw_payload_len;end
        if(dAxi_b_valid&&dAxi_b_ready)begin
            dAxi_b_valid<=0;
            if(exit_pending)begin
                $fflush(fd);$fclose(fd);
                $display("CPU_EXIT code=%d cycles=%d retired=%d Ibytes=%d Dbytes=%d Wbytes=%d",exit_code,cycles,retired,ireads,dreads,writes);
                if(exit_code!=0)$fatal(1,"firmware failed");$finish;
            end
        end
        if(dAxi_w_valid&&dAxi_w_ready)begin
            if(dAxi_w_payload_last!=(wlen==0))$fatal(1,"W last mismatch");
            if(wa==32'h10000080)tag<=dAxi_w_payload_data;
            else if(wa==32'h10000084)$fwrite(fd,"%0d %0d %0d\n",tag>>16,tag&65535,dAxi_w_payload_data);
            else if(wa==32'h10000020)begin exit_pending<=1;exit_code<=dAxi_w_payload_data;end
            else if(wa[31:16]==16'h1002)begin end
            else for(int b=0;b<4;b++)if(dAxi_w_payload_strb[b])begin write8({wa[31:2],2'b0}+b,dAxi_w_payload_data[8*b+:8]);writes<=writes+1;end
            if(wlen==0)begin wbusy<=0;dAxi_b_valid<=1;end else begin wa<=wa+4;wlen<=wlen-1;end
        end
    end
end

endmodule
