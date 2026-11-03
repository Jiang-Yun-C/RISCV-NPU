`timescale 1ns/1ps
`include "rvv_backend.svh"
module tb_robseq;
logic clk=0,rst_n=0;
always #5 clk=~clk;
logic [`NUM_DP_UOP-1:0] push=0,ready,old_ready;
DP2ROB_t [`NUM_DP_UOP-1:0] din='0;
logic empty,old_empty;
logic [`ROB_DEPTH_WIDTH-1:0] wp,old_wp,rp,old_rp;
logic [`NUM_SMPORT-1:0] complete=0;
PU2ROB_t [`NUM_SMPORT-1:0] result='0;
logic [`NUM_SMPORT-1:0][$clog2(`VLENB):0] tails='0;
logic [`NUM_RT_UOP-1:0] valid,old_valid,pop_ready=0;
ROB2RT_t [`NUM_RT_UOP-1:0] dout,old_dout;
ROB2DP_t [`ROB_DEPTH-1:0] bypass,old_bypass;
logic trap_request=0,trap_ready,old_trap_ready,external_trap=0;
logic [`ROB_DEPTH_WIDTH-1:0] trap_entry=0;
logic flush,old_flush,flush_ready,old_flush_ready;
rvv_backend_rob dut(.clk(clk),.rst_n(rst_n),.uop_valid_dp2rob(push),.uop_dp2rob(din),
 .uop_ready_rob2dp(ready),.rob_empty(empty),.rob_entry_rob2dp(wp),
 .wr_valid_pu2rob(complete),.wr_pu2rob(result),.ff_tail_index(tails),
 .rd_valid_rob2rt(valid),.rd_rob2rt(dout),.rd_ready_rt2rob(pop_ready),.rob_entry_rob2rt(rp),
 .uop_rob2dp(bypass),.trap_valid_rmp2rob(trap_request),.trap_rob_entry_rmp2rob(trap_entry),
 .trap_ready_rob2rmp(trap_ready),.trap_valid_rvs2rvv(external_trap),
 .trap_ready_rvv2rvs(flush_ready),.trap_flush_rvv(flush));
rvv_backend_rob_previous prev(.clk(clk),.rst_n(rst_n),.uop_valid_dp2rob(push),.uop_dp2rob(din),
 .uop_ready_rob2dp(old_ready),.rob_empty(old_empty),.rob_entry_rob2dp(old_wp),
 .wr_valid_pu2rob(complete),.wr_pu2rob(result),.ff_tail_index(tails),
 .rd_valid_rob2rt(old_valid),.rd_rob2rt(old_dout),.rd_ready_rt2rob(pop_ready),.rob_entry_rob2rt(old_rp),
 .uop_rob2dp(old_bypass),.trap_valid_rmp2rob(trap_request),.trap_rob_entry_rmp2rob(trap_entry),
 .trap_ready_rob2rmp(old_trap_ready),.trap_valid_rvs2rvv(external_trap),
 .trap_ready_rvv2rvs(old_flush_ready),.trap_flush_rvv(old_flush));
DP2ROB_t queue_info[$],discard;
int queue_slot[$],discard_slot;
bit [`ROB_DEPTH-1:0] done_ledger=0,trap_ledger=0;
logic [`ROB_DEPTH-1:0][`VLEN-1:0] data_ledger='0;
int model_wp=0,model_rp=0,next_id=1,checks=0,wraps=0,holds=0;
int same_entry=0,different_entry=0,multi_port=0,flush_complete=0,retired=0;
bit model_trapping=0,expected_flush,trap_in,prefix;

task automatic idle;
push=0;complete=0;pop_ready=0;external_trap=0;trap_request=0;
endtask
task automatic reset_all;
@(negedge clk);idle();#1;rst_n=0;
queue_info.delete();queue_slot.delete();done_ledger=0;trap_ledger=0;data_ledger=0;
model_wp=0;model_rp=0;model_trapping=0;
repeat(2)@(negedge clk);#1;rst_n=1;
endtask
task automatic add(input int lane);
push[lane]=1;din[lane]='0;
din[lane].rob_tag=4'(next_id);din[lane].w_index=5'(next_id);
din[lane].last_uop_valid=next_id[0];din[lane].res_updating_end=1;
din[lane].w_type=VRF;din[lane].byte_type={`VLENB{BODY_ACTIVE}};
`ifdef TB_SUPPORT
din[lane].uop_pc=32'h10000+4*next_id;
`endif
next_id++;
endtask
task automatic finish_entry(input int port,input int entry,input int data_id);
complete[port]=1;result[port]='0;result[port].rob_entry=`ROB_DEPTH_WIDTH'(entry);
result[port].w_valid=1;result[port].w_data=`VLEN'(data_id);
endtask

task automatic tick;
int count_pop,accepted,idx;
bit [`ROB_DEPTH-1:0] retired_slots,written_slots;
@(posedge clk);
if({ready,empty,wp,rp,valid,dout,bypass,flush,flush_ready,trap_ready} !==
   {old_ready,old_empty,old_wp,old_rp,old_valid,old_dout,old_bypass,old_flush,old_flush_ready,old_trap_ready})$fatal(1,"ROB full output miter");
if(wp!==`ROB_DEPTH_WIDTH'(model_wp) || rp!==`ROB_DEPTH_WIDTH'(model_rp) || empty!==(queue_info.size()==0))$fatal(1,"ROB pointer/occupancy ledger");
trap_in=external_trap || (queue_info.size()!=0 && trap_ledger[model_rp] && pop_ready[0]);
expected_flush=trap_in||model_trapping;
if(flush!==expected_flush)$fatal(1,"ROB trap/flush contract");
prefix=1;count_pop=0;retired_slots=0;written_slots=0;
for(int k=0;k<`NUM_RT_UOP;k++)begin
 bit ev;
 ev=(k<queue_info.size()) && (k==0 ? (done_ledger[(model_rp+k)%`ROB_DEPTH]||trap_ledger[(model_rp+k)%`ROB_DEPTH]) :
   (prefix && done_ledger[(model_rp+k)%`ROB_DEPTH] && !trap_ledger[(model_rp+k-1)%`ROB_DEPTH]));
 prefix=ev;
 if(valid[k]!==ev)$fatal(1,"ROB completion/order visibility lane %0d",k);
 if(k<queue_info.size())begin
  if({dout[k].rob_tag,dout[k].last_uop_valid,dout[k].w_index,dout[k].w_type,dout[k].res_updating_end} !==
     {queue_info[k].rob_tag,queue_info[k].last_uop_valid,queue_info[k].w_index,queue_info[k].w_type,queue_info[k].res_updating_end})$fatal(1,"ROB metadata identity");
  if(done_ledger[(model_rp+k)%`ROB_DEPTH] && dout[k].w_data!==data_ledger[(model_rp+k)%`ROB_DEPTH])$fatal(1,"ROB result data ledger");
 end
 if(valid[k]&&!pop_ready[k])holds++;
 if(valid[k]&&pop_ready[k])begin count_pop++;retired_slots[(model_rp+k)%`ROB_DEPTH]=1;end
end
accepted=0;
for(int k=0;k<`NUM_DP_UOP;k++)if(push[k])begin
 if(!ready[k])$fatal(1,"test violated ROB allocation credit");accepted++;
end
if(expected_flush)begin
 if(|complete)flush_complete++;
 queue_info.delete();queue_slot.delete();done_ledger=0;trap_ledger=0;model_wp=0;model_rp=0;
end else begin
 // A ledger removes retired identities first, then records incoming results.
 // Deliberate duplicate/same-entry inputs test the original winner explicitly.
 for(int k=0;k<count_pop;k++)begin
  discard=queue_info.pop_front();discard_slot=queue_slot.pop_front();done_ledger[discard_slot]=0;retired++;
 end
 if(model_rp+count_pop>=`ROB_DEPTH)wraps++;
 model_rp=(model_rp+count_pop)%`ROB_DEPTH;
 for(int k=0;k<`NUM_DP_UOP;k++)if(push[k])begin
  queue_info.push_back(din[k]);queue_slot.push_back(model_wp);model_wp=(model_wp+1)%`ROB_DEPTH;
 end
 for(int k=0;k<`NUM_SMPORT;k++)if(complete[k])begin
  idx=int'(result[k].rob_entry);
  if(retired_slots[idx])same_entry++;
  if((|retired_slots)&&!retired_slots[idx])different_entry++;
  if(written_slots[idx])multi_port++;
  written_slots[idx]=1;done_ledger[idx]=1;
 end
 if(trap_request)trap_ledger[trap_entry]=1;
end
// Result memory remains writable during flush, but done=0 masks its consumption.
for(int k=0;k<`NUM_SMPORT;k++)if(complete[k])data_ledger[result[k].rob_entry]=result[k].w_data;
model_trapping=trap_in&&!model_trapping;
#1;
if(dut.uop_done!==done_ledger || dut.uop_done!==prev.uop_done || dut.res_mem!==prev.res_mem)$fatal(1,"ROB lifecycle/miter state");
checks++;
endtask

initial begin
reset_all();
// Actual same-entry completion/retirement and two-PU collision, no exclusivity assumption.
@(negedge clk);idle();add(0);add(1);tick();
@(negedge clk);idle();finish_entry(0,0,100);finish_entry(1,1,101);tick();
@(negedge clk);idle();pop_ready=1;finish_entry(0,0,200);finish_entry(1,0,201);finish_entry(2,1,202);tick();
if(!dut.uop_done[0] || dut.res_mem[0].w_data!==`VLEN'(201))$fatal(1,"ROB same-entry preserved winner");
// Flush dominates completed and old-retired identities, including its second cycle.
@(negedge clk);idle();external_trap=1;finish_entry(0,1,300);tick();
@(negedge clk);idle();finish_entry(0,0,301);tick();
@(negedge clk);idle();tick();
if(dut.uop_done!=0 || !empty)$fatal(1,"ROB flush cancellation");
reset_all();
for(int cycle=0;cycle<3000;cycle++)begin
 int room,pos,entry;
 bit [`ROB_DEPTH-1:0] selected;
 @(negedge clk);idle();
 pop_ready=(cycle%23<8)?0:`NUM_RT_UOP'((1<<$urandom_range(0,`NUM_RT_UOP))-1);
 room=`ROB_DEPTH-queue_info.size();
 for(int k=0;k<`NUM_DP_UOP;k++)if(k<room && $urandom_range(0,1))add(k);
 selected=0;
 for(int k=0;k<`NUM_SMPORT;k++)begin
  if(queue_info.size()>0 && $urandom_range(0,1))begin
   pos=$urandom_range(0,queue_info.size()-1);entry=queue_slot[pos];
   if(!done_ledger[entry]&&!selected[entry])begin finish_entry(k,entry,cycle*`NUM_SMPORT+k);selected[entry]=1;end
  end
 end
 if(cycle%211==210)external_trap=1;
 tick();
end
// A ROB-generated trap at the head cancels otherwise live result traffic.
reset_all();@(negedge clk);idle();add(0);tick();
@(negedge clk);idle();trap_request=1;trap_entry=0;tick();
@(negedge clk);idle();pop_ready=1;finish_entry(0,0,400);tick();
@(negedge clk);idle();tick();
if(wraps<10 || holds<100 || same_entry==0 || different_entry==0 || multi_port==0 || flush_complete<3)$fatal(1,"ROB coverage");
$display("R01_ROB_SEQUENTIAL_PASS checks=%0d retired=%0d wraps=%0d holds=%0d same=%0d different=%0d multi=%0d flush_complete=%0d",checks,retired,wraps,holds,same_entry,different_entry,multi_port,flush_complete);
$finish;
end
initial begin #100000;$fatal(1,"ROB test timeout");end
endmodule
