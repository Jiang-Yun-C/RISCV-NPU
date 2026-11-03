`timescale 1ns/1ps
// Control-only stub. Real arithmetic and real native DMA are tested separately.
module nx_opt11_group #(parameter integer LANES=2)(
  input wire clk,reset_n,start,ack,input wire [6:0] length,
  input wire [3:0] mode,input wire quantize_result,pad_full,input wire [31:0] scalar,
  input wire load_valid,output wire load_ready,input wire [127:0] gate_data,up_data,
  output reg valid,output wire idle,error,input wire [5:0] peek,
  output wire [127:0] fp_data,output reg [127:0] q_data,output wire [31:0] scale,output wire [63:0] cycles
);
  reg active;
  assign load_ready=1;assign idle=!active&&!valid;assign error=0;
  assign fp_data={96'b0,tb_buffer_abort.pattern+32'(peek)};assign scale=32'h3f800000;assign cycles=0;
  always @*for(integer j=0;j<16;j++)q_data[8*j+:8]=8'(tb_buffer_abort.pattern)+8'(peek)+8'(j);
  always @(posedge clk or negedge reset_n)
    if(!reset_n)begin valid<=0;active<=0;end
    else if(ack)begin valid<=0;active<=0;end
    else if(start)active<=1;
    else if(active&&load_valid)begin valid<=1;active<=0;end
endmodule
module tb_buffer_abort;
  reg clk=0;always #4 clk=~clk;
  reg platform_reset_n=0,submit=0,reset_grant=0,stop_new=0;
  reg [1023:0] descriptor;
  reg [31:0] pattern=32'h3f800001;
  reg [63:0] run_limit=0;
  wire dma_valid,dma_write,dma_ready,dma_result_valid,dma_idle,completion_valid,engine_idle;
  wire [31:0] dma_address;wire [2:0] dma_size;wire [4:0] dma_len;
  wire [15:0] dma_scratch,dma_mask;wire [127:0] dma_data,completion_unused;
  wire [1279:0] completion;
  wire ram_en;wire [11:0] ram_address;wire [15:0] ram_mask;
  wire [127:0] ram_data,ram_q,unused_q;
  nx_ce64_scratch scratch(.clk,.a_en(1'b0),.a_addr(12'b0),.a_we(16'b0),.a_data(128'b0),.a_q(unused_q),
    .b_en(ram_en),.b_addr(ram_address),.b_we(ram_mask),.b_data(ram_data),.b_q(ram_q));
  integer pending=0,accepted=0,retired=0,write_commands=0,stores=0;
  assign dma_ready=pending==0;assign dma_idle=pending==0;
  assign dma_result_valid=pending==1;
  nx_opt11_control dut(.clk,.platform_reset_n,.submit,.reset_grant,.stop_new,
    .abort_publish(1'b0),.descriptor,.epoch(32'd7),.generation(32'd1),.first_fault_address(32'd0),.run_limit,
    .transport_drained(dma_idle),.native_quarantined(1'b0),.engine_idle,
    .completion,.completion_valid,.completion_ready(1'b0),.dma_ready,.dma_result_valid,.dma_idle,.dma_resp(2'b0),
    .dma_valid,.dma_write,.dma_address,.dma_size,.dma_len,.dma_scratch,.dma_mask,.dma_data,
    .ram_en,.ram_address,.ram_mask,.ram_data,.ram_q);
  always @(posedge clk)begin
    if(!platform_reset_n)begin pending<=0;accepted<=0;retired<=0;write_commands<=0;stores<=0;end
    else begin
      if(pending>0)begin pending<=pending-1;if(pending==1)retired<=retired+1;end
      if(dma_valid&&dma_ready)begin
        pending<=20;accepted<=accepted+1;
        if(dma_write)begin
          write_commands<=write_commands+1;
          if((dma_address&4095)+((32'(dma_len)+1)<<dma_size)>4096)$fatal(1,"buffered write crosses page");
          if(dma_scratch!=0)for(integer beat=0;beat<=dma_len;beat++)begin
            if(dma_scratch>=16'hf100)begin
              for(integer b=0;b<16;b++)
                if(scratch.ram[(dma_scratch>>4)+beat][8*b+:8] !== (8'(pattern)+8'(dma_scratch-16'hf100)+8'(beat*16+b)))$fatal(1,"Aq scratch group not complete/ordered before DMA offer");
            end else for(integer word_index=0;word_index<4;word_index++)
              if(scratch.ram[(dma_scratch>>4)+beat][32*word_index+:32] !== (pattern+32'((dma_scratch-16'hf000)/4+beat*4+word_index)))$fatal(1,"FP32 scratch group not complete/ordered before DMA offer");
          end
          if(dma_scratch!=0&&(dma_size!=4||dma_mask!=16'hffff||dma_scratch<16'hf000||dma_scratch+((32'(dma_len)+1)<<4)>16'hf140))$fatal(1,"bad buffered quantum");
        end
      end
      if(ram_en&&ram_mask!=0)begin
        stores<=stores+1;
        if(ram_address<12'hf00||ram_address>12'hf13)$fatal(1,"buffer scratch escape");
        if(pending!=0)$fatal(1,"control/DMA physical scratch overlap");
      end
      if(completion_valid&&pending!=0)$fatal(1,"premature completion before accepted DMA retirement");
    end
  end
  integer cases=0,checks=0;
  task automatic prepare;
    begin
      descriptor=0;descriptor[0*32+:32]=32'h34364543;descriptor[1*32+:32]=1;descriptor[2*32+:32]=128;
      descriptor[4*32+:32]=7;descriptor[5*32+:32]=1;descriptor[8*32+:32]=32'h4c4e3135;descriptor[9*32+:32]=96;
      descriptor[10*32+:32]=1;descriptor[12*32+:32]=1;descriptor[14*32+:32]=3;descriptor[15*32+:32]=1;descriptor[16*32+:32]=1;
      descriptor[17*32+:32]=131;descriptor[18*32+:32]=32'hac000000;descriptor[19*32+:32]=32'hae1f0ff0;
      descriptor[20*32+:32]=32'hac010000;descriptor[22*32+:32]=32'hba1d0ff0;descriptor[23*32+:32]=32'hba1d1400;
    end
  endtask
  task automatic launch(input bit cold);
    begin
      @(negedge clk);stop_new=0;run_limit=0;reset_grant=0;submit=0;
      if(cold)begin platform_reset_n=0;repeat(2)@(negedge clk);platform_reset_n=1;end
      else begin reset_grant=1;@(negedge clk);reset_grant=0;end
      pattern=pattern+32'h10001;
      @(negedge clk);submit=1;@(negedge clk);submit=0;
    end
  endtask
  task automatic wait_complete;
    integer deadline;
    begin
      deadline=0;
      while(!completion_valid&&deadline<20000)begin @(negedge clk);deadline++;end
      checks++;
      if(!completion_valid||pending!=0||accepted!=retired)$fatal(1,"bounded drained completion");
    end
  endtask
  integer target[0:4]='{30,31,34,35,16};
  integer deadline,before_writes;
  initial begin
    prepare();launch(1);wait_complete();
    if($signed(completion[14*32+:32])!=0||write_commands!=13||dut.write_bytes!=728)$fatal(1,"successful split-page group quantum count/payload");
    cases++;
    for(integer stage=0;stage<5;stage++)for(integer action=1;action<=3;action++)begin
      prepare();launch(1);deadline=0;
      while(!(dut.state==target[stage]&&(stage!=4||dut.cmd_write&&pending>1))&&deadline<20000)begin @(negedge clk);deadline++;end
      if(deadline>=20000)$fatal(1,"target buffer/accepted stage never reached");
      before_writes=write_commands;
      if(action==2)run_limit=1;else stop_new=1;
      @(negedge clk);
      if(action==3)begin
        deadline=0;
        while(!(dut.state==17&&pending==0)&&deadline<200)begin @(negedge clk);deadline++;end
        if(deadline>=200)$fatal(1,"reset failed to drain");
        reset_grant=1;@(negedge clk);reset_grant=0;
        checks++;if(!engine_idle||completion_valid)$fatal(1,"reset published stale success");
      end else begin
        wait_complete();checks++;
        if($signed(completion[14*32+:32])!=(action==2?-7:-11)||completion[15*32+:32]!=0)$fatal(1,"abort published success");
      end
      checks++;if(write_commands!=before_writes)$fatal(1,"new output issued after stop/timeout/reset request");
      cases++;
      // Recovery uses reset_grant without erasing the already dirty scratch.
      prepare();launch(0);before_writes=write_commands;wait_complete();
      if($signed(completion[14*32+:32])!=0||write_commands-before_writes!=13||dut.write_bytes!=728)$fatal(1,"recovered split-page call failed");
      cases++;
    end
    $display("BUFFER_ABORT_PASS cases=%0d checks=%0d",cases,checks);$finish;
  end
endmodule
