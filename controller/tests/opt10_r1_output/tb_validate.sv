`timescale 1ns/1ps
// Validation-only differential probe. The arithmetic stub cannot qualify math.
module nx_opt11_group #(parameter integer LANES=2)(
  input wire clk,reset_n,start,ack,input wire [6:0] length,
  input wire [3:0] mode,input wire quantize_result,pad_full,input wire [31:0] scalar,
  input wire load_valid,output wire load_ready,input wire [127:0] gate_data,up_data,
  output wire valid,idle,error,input wire [5:0] peek,
  output wire [127:0] fp_data,q_data,output wire [31:0] scale,output wire [63:0] cycles
);
  assign load_ready=1;assign valid=0;assign idle=1;assign error=0;
  assign fp_data=0;assign q_data=0;assign scale=0;assign cycles=0;
  always @(posedge clk)if(reset_n&&start)$fatal(1,"arithmetic reached before validation probe ends");
endmodule
module tb_validate;
  reg clk=0;always #4 clk=~clk;
  reg platform_reset_n=0,submit=0,reset_grant=0,stop_new=0;
  reg [1023:0] descriptor;
  reg [63:0] run_limit=0;
  wire [1:0] dma_valid,completion_valid,engine_idle;
  wire [1279:0] completion[0:1];
  nx_opt11_control_original original(.clk,.platform_reset_n,.submit,.reset_grant,.stop_new,
    .abort_publish(1'b0),.descriptor,.epoch(32'd7),.generation(32'd1),.first_fault_address(32'd0),.run_limit,
    .transport_drained(1'b1),.native_quarantined(1'b0),.engine_idle(engine_idle[0]),
    .completion(completion[0]),.completion_valid(completion_valid[0]),.completion_ready(1'b0),
    .dma_ready(1'b0),.dma_result_valid(1'b0),.dma_idle(1'b1),.dma_resp(2'b0),.dma_valid(dma_valid[0]),.ram_q(128'b0));
  nx_opt11_control candidate(.clk,.platform_reset_n,.submit,.reset_grant,.stop_new,
    .abort_publish(1'b0),.descriptor,.epoch(32'd7),.generation(32'd1),.first_fault_address(32'd0),.run_limit,
    .transport_drained(1'b1),.native_quarantined(1'b0),.engine_idle(engine_idle[1]),
    .completion(completion[1]),.completion_valid(completion_valid[1]),.completion_ready(1'b0),
    .dma_ready(1'b0),.dma_result_valid(1'b0),.dma_idle(1'b1),.dma_resp(2'b0),.dma_valid(dma_valid[1]),.ram_q(128'b0));
  integer checks=0,accepted=0,rejected=0,recovery_cases=0;
  reg [1023:0] valid_descriptor;
  integer lengths[0:5]='{1,63,64,65,896,4864};
  task automatic prepare(input integer mode,quant,k);
    begin
      descriptor=0;
      descriptor[0*32+:32]=32'h34364543;descriptor[1*32+:32]=1;descriptor[2*32+:32]=128;
      descriptor[4*32+:32]=7;descriptor[5*32+:32]=1;descriptor[8*32+:32]=32'h4c4e3135;
      descriptor[9*32+:32]=96;descriptor[10*32+:32]=1;descriptor[12*32+:32]=1;
      descriptor[14*32+:32]=3;descriptor[15*32+:32]=1;descriptor[16*32+:32]=1;
      descriptor[17*32+:32]=k;descriptor[18*32+:32]=32'hac000000;descriptor[19*32+:32]=32'hac010000;
      if(mode==0||mode==2||mode==3||mode==7)descriptor[20*32+:32]=32'hac020000;
      if(mode<2||quant)begin descriptor[22*32+:32]=32'hba100000;descriptor[23*32+:32]=32'hba110000;end
      descriptor[24*32+:32]=mode;descriptor[25*32+:32]=quant;
      if(mode==4)descriptor[26*32+:32]=32'h3f800000;
    end
  endtask
  task automatic reset;
    begin
      @(negedge clk);platform_reset_n=0;submit=0;reset_grant=0;stop_new=0;run_limit=0;
      repeat(2)@(negedge clk);platform_reset_n=1;
      @(negedge clk);submit=1;@(negedge clk);submit=0;
    end
  endtask
  task automatic compare(input integer action,when_cycle);
    reg [1:0] seen,ok;
    reg [31:0] result[0:1];
    integer deadline;
    begin
      reset();seen=0;ok=0;result[0]=0;result[1]=0;deadline=0;
      while(seen!=3&&deadline<160)begin
        if(deadline==when_cycle)begin
          if(action==1)stop_new=1;
          if(action==2)run_limit=1;
          if(action==3)reset_grant=1;
          if(action==4)platform_reset_n=0;
        end
        if(action>=3&&deadline==when_cycle+2)begin reset_grant=0;platform_reset_n=1;end
        for(integer i=0;i<2;i=i+1)if(!seen[i])begin
          if(dma_valid[i])begin seen[i]=1;ok[i]=1;end
          else if(completion_valid[i])begin seen[i]=1;result[i]=completion[i][14*32+:32];end
          else if(action>=3&&deadline>when_cycle+2&&engine_idle[i])seen[i]=1;
        end
        @(negedge clk);deadline++;
      end
      checks++;
      if(seen!=3||ok[0]!=ok[1]||result[0]!=result[1])
        $fatal(1,"descriptor mismatch check=%0d seen=%b ok=%b status=%h/%h",checks,seen,ok,result[0],result[1]);
      if(ok[0])accepted++;else rejected++;
      if(action)begin
        recovery_cases++;
        if(ok!=0)$fatal(1,"validation abort published memory command");
        if(action==1&&result[0]!=-11)$fatal(1,"stop status");
        if(action==2&&result[0]!=-7)$fatal(1,"timeout status");
      end
    end
  endtask
  initial begin
    for(integer mode=0;mode<8;mode++)for(integer quant=0;quant<2;quant++)for(integer k=0;k<6;k++)begin
      prepare(mode,quant,lengths[k]);valid_descriptor=descriptor;compare(0,-1);
      // Includes every bit in high mode/flags, session/sequence, reserved,
      // sizes, addresses and epoch. Original source decides acceptance.
      for(integer bit_index=0;bit_index<1024;bit_index++)begin
        descriptor=valid_descriptor;descriptor[bit_index]=~descriptor[bit_index];compare(0,-1);
      end
    end
    for(integer action=1;action<=4;action++)for(integer cycle_index=0;cycle_index<2;cycle_index++)begin
      prepare(7,0,896);compare(action,cycle_index);
      prepare(7,0,896);compare(0,-1);
    end
    $display("VALIDATE_EQ_PASS checks=%0d accepted=%0d rejected=%0d recovery=%0d",checks,accepted,rejected,recovery_cases);$finish;
  end
endmodule
