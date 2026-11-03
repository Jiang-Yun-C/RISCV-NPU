`timescale 1ns/1ps
module tb_restore;
  parameter bit PARALLEL=0;
  logic clock=0,reset_n=0,req_valid_i=0,req_ready_o,rsp_valid_o,rsp_ready_i=0;
  logic signed [31:0] dot_i=0;
  logic [31:0] sa_i=0,sw_i=0,acc_i=0,tag_i=0,epoch_i=0;
  logic [3:0] status_i=0,status_o;
  logic [31:0] p_o,v_o,partial_o,tag_o,epoch_o;
  logic [4:0] flags_o;
  nx_ce64_fp32_restore #(.PARALLEL(PARALLEL)) dut(.*);
  always #4 clock=~clock;
  typedef struct packed {logic [31:0] dot,sa,sw,acc,initial_status,p,v,y,status,flags;} vector_t;
  vector_t vectors[0:49999];
  integer offered=0,received=0,count=0,cycle=0,fd,n,logfd;
  integer accept_cycle[0:49999];
  integer min_latency=999999,max_latency=0,first_accept=-1,last_accept=-1;
  string file;
  logic held=0;
  logic [168:0] held_payload;
  integer random_seed=641;
  bit accepted;
  initial begin
    n=$urandom(random_seed);
    if(!$value$plusargs("vectors=%s",file)) $fatal(1,"missing vectors");
    fd=$fopen(file,"r");if(!fd)$fatal(1,"no input");
    while(!$feof(fd)) begin
      n=$fscanf(fd,"%h %h %h %h %h %h %h %h %h %h\n",vectors[count].dot,vectors[count].sa,vectors[count].sw,vectors[count].acc,
          vectors[count].initial_status,vectors[count].p,vectors[count].v,vectors[count].y,vectors[count].status,vectors[count].flags);
      if(n==10)count++;
      else if(n!=-1)$fatal(1,"bad vector");
    end
    $fclose(fd);if(count<1000)$fatal(1,"empty/short test");
    logfd=$fopen("restore.csv","w");
    $fwrite(logfd,"index,accepted,returned,p,v,partial,status,flags\n");
    repeat(4)@(negedge clock);reset_n=1;
    while(received<count) begin
      @(negedge clock);
      // First 128 vectors: no bubble/stall, measure intrinsic latency and II.
      rsp_ready_i=received<128 ? 1 : ($urandom_range(0,7)>1);
      if(cycle%311==0 && received>=128) rsp_ready_i=0;
      if(!req_valid_i && offered<count && (offered<128 || $urandom_range(0,3)!=0)) begin
        req_valid_i=1;dot_i=vectors[offered].dot;sa_i=vectors[offered].sa;sw_i=vectors[offered].sw;
        acc_i=vectors[offered].acc;status_i=vectors[offered].initial_status;
        tag_i=offered;epoch_i=32'hce640001;
      end
      @(posedge clock);
      cycle++;
      accepted=0;
      if(cycle>count*50)$fatal(1,"watchdog");
      if(held && {p_o,v_o,partial_o,tag_o,epoch_o,status_o,flags_o}!==held_payload)
        $fatal(1,"unstable blocked output");
      held=rsp_valid_o&&!rsp_ready_i;
      held_payload={p_o,v_o,partial_o,tag_o,epoch_o,status_o,flags_o};
      if(req_valid_i && req_ready_o) begin
        accept_cycle[offered]=cycle;
        if(offered==0)first_accept=cycle;
        if(offered==127)last_accept=cycle;
        offered++;
        accepted=1;
      end
      if(rsp_valid_o && rsp_ready_i) begin
        if(tag_o!==32'(received)||epoch_o!==32'hce640001)$fatal(1,"identity/reorder");
        if({p_o,v_o,partial_o}!=={vectors[received].p,vectors[received].v,vectors[received].y} || status_o!==vectors[received].status[3:0]
            || flags_o!==vectors[received].flags[4:0])
          $fatal(1,"FP mismatch index=%0d got=%h/%h/%h status=%h flags=%h expected=%h/%h/%h status=%h flags=%h",received,p_o,v_o,partial_o,status_o,flags_o,
            vectors[received].p,vectors[received].v,vectors[received].y,vectors[received].status,vectors[received].flags);
        if(received<128) begin
          if(cycle-accept_cycle[received]<min_latency)min_latency=cycle-accept_cycle[received];
          if(cycle-accept_cycle[received]>max_latency)max_latency=cycle-accept_cycle[received];
        end
        $fwrite(logfd,"%0d,%0d,%0d,%h,%h,%h,%0d,%0d\n",received,accept_cycle[received],cycle,p_o,v_o,partial_o,status_o,flags_o);
        received++;
      end
      #1;if(accepted)req_valid_i=0;
    end
    @(negedge clock);req_valid_i=0;rsp_ready_i=1;
    // Reset a blocked output and replay a new epoch. Reset only local arithmetic.
    dot_i=1;sa_i=32'h3f800000;sw_i=32'h3f800000;acc_i=0;tag_i=123;epoch_i=2;status_i=0;req_valid_i=1;
    do @(posedge clock);while(!req_ready_o);
    @(negedge clock);req_valid_i=0;rsp_ready_i=0;
    do @(negedge clock);while(!rsp_valid_o);
    repeat(40)@(negedge clock);
    reset_n=0;repeat(3)@(negedge clock);
    reset_n=1;epoch_i=3;req_valid_i=1;
    do @(posedge clock);while(!req_ready_o);
    @(negedge clock);req_valid_i=0;rsp_ready_i=1;
    do @(negedge clock);while(!rsp_valid_o);
    if(epoch_o!==3 || partial_o!==32'h3f800000)$fatal(1,"reset stale epoch");
    $fclose(logfd);
    $display("CE64_RESTORE_PASS parallel=%0d cases=%0d min_latency=%0d max_latency=%0d acceptance_span_128=%0d cycles=%0d",PARALLEL,count,min_latency,max_latency,last_accept-first_accept,cycle);
    $finish;
  end
endmodule
