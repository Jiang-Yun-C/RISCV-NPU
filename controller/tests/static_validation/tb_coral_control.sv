`timescale 1ns/1ps
module fifo_control_case #(parameter bit CHAOS=0,FULL=0,POPCLR=0,ASYNC=0)(output bit done=0);
  localparam M=3,N=3,D=8;
  logic clk=0,rst_n=0,clear=0;
  always #5 clk=~clk;
  logic [M-1:0] push=0;
  logic [N-1:0] pop=0;
  logic [M-1:0][15:0] din;
  wire [M-1:0] ready,old_ready,af,old_af;
  wire [N-1:0] ae,old_ae;
  wire [N-1:0][15:0] dout,old_dout;
  wire [D-1:0][15:0] data,old_data;
  wire full,old_full,empty,old_empty;
  wire [2:0] wp,rp,old_wp,old_rp;
  wire [3:0] count,old_count;
  multi_fifo #(.T(logic[15:0]),.M(M),.N(N),.DEPTH(D),.CHAOS_PUSH(CHAOS),.FULL_PUSH(FULL),.POP_CLEAR(POPCLR),.ASYNC_RSTN(ASYNC)) dut
    (.clk,.rst_n,.clear,.push,.pop,.datain(din),.pushRdy(ready),.full,.almost_full(af),.dataout(dout),.empty,.almost_empty(ae),.fifo_data(data),.wptr(wp),.rptr(rp),.entry_count(count));
  multi_fifo_previous #(.T(logic[15:0]),.M(M),.N(N),.DEPTH(D),.CHAOS_PUSH(CHAOS),.FULL_PUSH(FULL),.POP_CLEAR(POPCLR),.ASYNC_RSTN(ASYNC)) prev
    (.clk,.rst_n,.clear,.push,.pop,.datain(din),.pushRdy(old_ready),.full(old_full),.almost_full(old_af),.dataout(old_dout),.empty(old_empty),.almost_empty(old_ae),.fifo_data(old_data),.wptr(old_wp),.rptr(old_rp),.entry_count(old_count));
  logic [15:0] model[$],discard,expected;
  int seed,checks=0,concurrent=0,clear_collision=0,full_cycles=0,wraps=0,old_write=0,np,room,accepted;
  bit bad;
  always @(posedge clk) begin
    if(!rst_n) model.delete();
    else begin
      if({ready,af,ae,full,empty,wp,rp,count,dout,data} !==
         {old_ready,old_af,old_ae,old_full,old_empty,old_wp,old_rp,old_count,old_dout,old_data})
        $fatal(1,"FIFO miter CHAOS=%0d FULL=%0d POPCLR=%0d",CHAOS,FULL,POPCLR);
      if(count !== model.size() || empty !== (model.size()==0)) $fatal(1,"FIFO occupancy");
      for(int k=0;k<N && k<model.size();k++) begin
        expected=model[k] ^ (bad ? 16'd1 : 16'd0);
        if(dout[k] !== expected) $fatal(1,"FIFO independent data scoreboard");
        checks++;
      end
      if(full)full_cycles++;
      if(wp<old_write)wraps++;old_write=wp;
      if((|push)&&(|pop))concurrent++;
      if(clear && ((|push)||(|pop)))clear_collision++;
      if(clear)model.delete();
      else begin
        for(int k=0;k<N;k++)if(pop[k])discard=model.pop_front();
        for(int k=0;k<M;k++)if(push[k])model.push_back(din[k]);
      end
    end
  end
  initial begin
    if(!$value$plusargs("SEED=%d",seed))seed=1;
    bad=$test$plusargs("BAD_ORACLE");din='0;
    // Do not clock invalid commands into the FIFO. Check the original four-state
    // combinational compaction/count semantics while the pointers are in reset.
    push=3'bx10;#1;
    if({ready,dut.push_seq,dut.datain_seq,dut.push_count} !==
       {old_ready,prev.push_seq,prev.datain_seq,prev.push_count})$fatal(1,"FIFO X-push compaction/count");
    push=0;pop=3'b00x;#1;
    if(dut.pop_count!==prev.pop_count)$fatal(1,"FIFO X-pop count");
    pop=0;
    repeat(4)@(negedge clk);rst_n=1;
    // Fill, drain, wrap, sparse enqueue, backpressure and clear with live events.
    for(int cycle=0;cycle<4000;cycle++)begin
      @(negedge clk);push=0;pop=0;clear=(cycle%127==126);
      np=(cycle%31<10)?0:$urandom_range(0,N);
      if(np>count)np=count;
      for(int k=0;k<np;k++)pop[k]=1;
      room=D-int'(count)+(FULL?np:0);accepted=0;
      for(int k=0;k<M;k++)begin
        din[k]=16'(cycle*M+k+seed);
        if(accepted<room && (cycle%31<10 || $urandom_range(0,1)))begin
          push[k]=1;accepted++;
        end else if(!CHAOS)break;
      end
      // Reset is asynchronous; keep driven commands settled before its edge.
      // The non-ASYNC memory branches still use negedge rst_n as an event.
      if(cycle==2100)begin #1;rst_n=0;end
      if(cycle==2103)begin #1;rst_n=1;end
    end
    @(negedge clk);push=0;pop=0;clear=0;
    if(checks<1000||concurrent==0||clear_collision==0||full_cycles==0||wraps==0)$fatal(1,"FIFO coverage");
    $display("R01_FIFO_CONTROL_PASS chaos=%0d full=%0d popclear=%0d async=%0d checks=%0d concurrent=%0d clear=%0d fullcycles=%0d wraps=%0d",CHAOS,FULL,POPCLR,ASYNC,checks,concurrent,clear_collision,full_cycles,wraps);
    done=1;
  end
endmodule

module tb_coralcontrol;
  logic [15:0] done;
  for(genvar k=0;k<16;k++)begin
    fifo_control_case #(.CHAOS(k%2),.FULL((k/2)%2),.POPCLR((k/4)%2),.ASYNC(k/8)) q(done[k]);
  end
  STRCT_UOP_t [`NUM_DP_UOP-1:0] uops;
  wire [`NUM_DP_VRF-1:0][`REGIDX_WIDTH-1:0] rd,old_rd;
  ARCH_HAZARD_t hz,old_hz;
  rvv_backend_dispatch_structure_hazard scheduler(rd,hz,uops);
  rvv_backend_dispatch_structure_hazard_previous scheduler_old(old_rd,old_hz,uops);
  logic clk=0,rstn=0,flush=0;
  always #5 clk=~clk;
  logic [3:0] iv=0;
  RVVInstruction [3:0] instructions='0;
  logic [7:0] rrvalid=0;
  logic [7:0][31:0] rrdata='0;
  logic [3:0][31:0] frdata='0;
  wire [3:0] ir,old_ir,rwvalid,old_rwvalid,cv,old_cv;
  wire [3:0][4:0] rwaddr,old_rwaddr;
  wire [3:0][31:0] rwdata,old_rwdata;
  RVVCmd [3:0] cmd,old_cmd;
  RVVConfigState cfg,old_cfg;
  wire tv,old_tv,cfgvalid,old_cfgvalid;
  RVVInstruction td,old_td;
  wire [3:0] capacity,old_capacity;
  wire [31:0] mtype,old_mtype;
  RvvFrontEnd front(.clk,.rstn,.vstart_i('0),.vstart_valid_i(1'b0),.vxrm_i('0),.vxsat_i('0),.frm_i('0),.flush_i(flush),
    .inst_valid_i(iv),.inst_data_i(instructions),.inst_ready_o(ir),.reg_read_valid_i(rrvalid),.reg_read_data_i(rrdata),.freg_read_data_i(frdata),
    .reg_write_valid_o(rwvalid),.reg_write_addr_o(rwaddr),.reg_write_data_o(rwdata),.cmd_valid_o(cv),.cmd_data_o(cmd),
    .queue_capacity_i(4'd8),.queue_capacity_o(capacity),.trap_valid_o(tv),.trap_data_o(td),.config_state_valid(cfgvalid),.config_state(cfg),.next_config_mtype_o(mtype));
  RvvFrontEnd_previous front_old(.clk,.rstn,.vstart_i('0),.vstart_valid_i(1'b0),.vxrm_i('0),.vxsat_i('0),.frm_i('0),.flush_i(flush),
    .inst_valid_i(iv),.inst_data_i(instructions),.inst_ready_o(old_ir),.reg_read_valid_i(rrvalid),.reg_read_data_i(rrdata),.freg_read_data_i(frdata),
    .reg_write_valid_o(old_rwvalid),.reg_write_addr_o(old_rwaddr),.reg_write_data_o(old_rwdata),.cmd_valid_o(old_cv),.cmd_data_o(old_cmd),
    .queue_capacity_i(4'd8),.queue_capacity_o(old_capacity),.trap_valid_o(old_tv),.trap_data_o(old_td),.config_state_valid(old_cfgvalid),.config_state(old_cfg),.next_config_mtype_o(old_mtype));
  logic [3:0] forced_traps;
  RVVInstruction [3:0] trap_tokens;
  int scheduler_checks=0,trap_checks=0,front_checks=0,first,seed;
  bit sched_done=0,front_done=0,found;
  initial begin
    uops='0;
    for(int a=0;a<8;a++)for(int b=0;b<8;b++)for(int c=0;c<8;c++)for(int flags=0;flags<16;flags++)begin
      uops[0].uop_class=UOP_CLASS_e'(a);uops[1].uop_class=UOP_CLASS_e'(b);uops[2].uop_class=UOP_CLASS_e'(c);
      for(int k=0;k<3;k++)begin
        uops[k].vs1_index=5'(1+3*k);uops[k].vs2_index=5'(2+3*k);uops[k].vd_index=5'(3+3*k);
        uops[k].vs1_valid=(int'(uops[k].uop_class)&1)!=0;
        uops[k].vs2_valid=(int'(uops[k].uop_class)&2)!=0;
        uops[k].vs3_valid=(int'(uops[k].uop_class)&4)!=0;
      end
      uops[0].vs1_valid=flags[0];uops[2].vs1_valid=flags[1];uops[2].vs2_valid=flags[2];uops[2].vs3_valid=flags[3];
      #1;
      if(rd!==old_rd||hz!==old_hz)$fatal(1,"Scheduler miter a=%0d b=%0d c=%0d flags=%0d",a,b,c,flags);
      scheduler_checks++;
      // For coherent classes, every required operand must appear on a read port.
      if(!hz.vr_limit && a!=5 && b!=5 && c!=5 && flags[0]==a[0] && flags[3:1]==c[2:0])begin
        for(int k=0;k<3;k++)for(int op=0;op<3;op++)begin
          if(int'(uops[k].uop_class)&(1<<op))begin
            found=0;
            for(int p=0;p<6;p++)if(rd[p]==5'(1+3*k+op))found=1;
            if(!found)$fatal(1,"Scheduler missing required operand");
          end
        end
      end
    end
    // Unknown class/valid probes preserve procedural case and if behavior.
    uops[0].uop_class=UOP_CLASS_e'(3'bxxx);#1;
    if(rd!==old_rd||hz!==old_hz)$fatal(1,"Scheduler X-class mismatch");
    uops[0].uop_class=VVX;uops[1].uop_class=XVV;uops[2].uop_class=VVX;uops[0].vs1_valid=1'bx;#1;
    if(rd!==old_rd||hz!==old_hz)$fatal(1,"Scheduler X-valid mismatch");
    sched_done=1;
  end
  initial begin
    if(!$value$plusargs("SEED=%d",seed))seed=1;
    for(int k=0;k<4;k++)trap_tokens[k]='{pc:32'(32'h10000+4*k),bits:32'(32'h57+k),opcode:RVV,rob_tag:5'(k)};
    force front.unaligned_trap_valid=forced_traps;force front_old.unaligned_trap_valid=forced_traps;
    force front.unaligned_trap_data=trap_tokens;force front_old.unaligned_trap_data=trap_tokens;
    for(int mask=0;mask<16;mask++)begin
      forced_traps=4'(mask);#1;first=-1;
      for(int k=0;k<4;k++)if(first<0 && forced_traps[k])first=k;
      if(tv!==old_tv||td!==old_td||tv!==(mask!=0))$fatal(1,"Trap miter/valid");
      if(first>=0 && td!==trap_tokens[first])$fatal(1,"Trap lowest lane priority");trap_checks++;
    end
    forced_traps=4'bx100;#1;if(td!==trap_tokens[2]||td!==old_td)$fatal(1,"Trap known-one priority with X");trap_checks++;
    forced_traps=4'b00x0;#1;if(tv!==1'bx||tv!==old_tv||td!==old_td)$fatal(1,"Trap X/no-known-one behavior");trap_checks++;
    release front.unaligned_trap_valid;release front_old.unaligned_trap_valid;
    release front.unaligned_trap_data;release front_old.unaligned_trap_data;
    repeat(4)@(negedge clk);rstn=1;
    for(int cycle=0;cycle<1000;cycle++)begin
      @(negedge clk);iv=4'($urandom);flush=(cycle%17==16);rrvalid='1;
      for(int k=0;k<4;k++)instructions[k]='{pc:32'(32'h10000+16*cycle+4*k),bits:32'h02000057,opcode:RVV,rob_tag:5'(k)};
      #1;
      if({ir,rwvalid,rwaddr,rwdata,cv,cmd,capacity,tv,td,cfgvalid,cfg,mtype}!==
         {old_ir,old_rwvalid,old_rwaddr,old_rwdata,old_cv,old_cmd,old_capacity,old_tv,old_td,old_cfgvalid,old_cfg,old_mtype})$fatal(1,"Frontend cycle/flush miter");
      front_checks++;
    end
    front_done=1;
  end
  initial begin
    wait((&done)&&sched_done&&front_done);
    $display("R01_CORAL_CONTROL_PASS scheduler=%0d trap=%0d frontend=%0d",scheduler_checks,trap_checks,front_checks);$finish;
  end
  initial begin #100000;$fatal(1,"Coral control timeout");end
endmodule
