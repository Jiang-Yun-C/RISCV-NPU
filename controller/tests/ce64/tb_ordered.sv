`timescale 1ns/1ps
module tb_ordered;
  logic clock=0,reset_n=0,req_valid_i=0,req_ready_o,rsp_valid_o,rsp_ready_i=0;
  logic signed [31:0] dot_i=0;
  logic [31:0] sa_i=0,sw_i=0,initial_acc_i=0,tag_i=0,epoch_i=0;
  logic first_i=0,last_i=0,last_o,idle_o;
  logic [3:0] status_i=0,status_o;
  logic [31:0] p_o,v_o,partial_o,tag_o,epoch_o;
  logic [4:0] flags_o;
  nx_ce64_fp32_ordered dut(.*);
  always #4 clock=~clock;
  typedef struct packed {
    logic [31:0] dot,sa,sw,initial_acc,first,last,epoch,initial_status,p,v,y,status,flags;
  } vector_t;
  vector_t vectors[0:99999];
  integer offered=0,received=0,count=0,cycle=0,fd,n,logfd;
  integer accept_cycle[0:99999];
  string file;
  logic held=0;
  logic [169:0] held_payload;
  integer random_seed=64641;
  integer blocked=0, held_checks=0;
  bit accepted;
  initial begin
    n=$urandom(random_seed);
    if(!$value$plusargs("vectors=%s",file)) $fatal(1,"missing vectors");
    fd=$fopen(file,"r");if(!fd)$fatal(1,"no input");
    while(!$feof(fd)) begin
      n=$fscanf(fd,"%h %h %h %h %h %h %h %h %h %h %h %h %h\n",
        vectors[count].dot,vectors[count].sa,vectors[count].sw,vectors[count].initial_acc,
        vectors[count].first,vectors[count].last,vectors[count].epoch,vectors[count].initial_status,
        vectors[count].p,vectors[count].v,vectors[count].y,vectors[count].status,vectors[count].flags);
      if(n==13)count++;
      else if(n!=-1)$fatal(1,"bad vector");
    end
    $fclose(fd);if(count<10000)$fatal(1,"empty/short test");
    logfd=$fopen("ordered.csv","w");
    $fwrite(logfd,"index,accepted,returned,epoch,last,p,v,partial,status,flags\n");
    repeat(4)@(negedge clock);reset_n=1;
    while(received<count) begin
      @(negedge clock);
      rsp_ready_i=received<256 ? 1 : ($urandom_range(0,7)>1);
      if(received>=256 && cycle%311==0) blocked=80;
      if(blocked>0) begin rsp_ready_i=0;blocked--;end
      if(!req_valid_i && offered<count && (offered<256 || $urandom_range(0,3)!=0)) begin
        req_valid_i=1;dot_i=vectors[offered].dot;sa_i=vectors[offered].sa;sw_i=vectors[offered].sw;
        initial_acc_i=vectors[offered].initial_acc;status_i=vectors[offered].initial_status;
        first_i=vectors[offered].first[0];last_i=vectors[offered].last[0];
        tag_i=offered;epoch_i=vectors[offered].epoch;
      end
      @(posedge clock);
      cycle++;accepted=0;
      if(cycle>count*100)$fatal(1,"watchdog");
      if(held && (!rsp_valid_o || {p_o,v_o,partial_o,tag_o,epoch_o,last_o,status_o,flags_o}!==held_payload))
        $fatal(1,"unstable blocked output");
      if(held)held_checks++;
      held=rsp_valid_o&&!rsp_ready_i;
      held_payload={p_o,v_o,partial_o,tag_o,epoch_o,last_o,status_o,flags_o};
      if(req_valid_i && req_ready_o) begin accept_cycle[offered]=cycle;offered++;accepted=1;end
      if(rsp_valid_o && rsp_ready_i) begin
        if(tag_o!==32'(received)||epoch_o!==vectors[received].epoch||last_o!==vectors[received].last[0])
          $fatal(1,"identity/reorder");
        if({p_o,v_o,partial_o}!=={vectors[received].p,vectors[received].v,vectors[received].y}
            || status_o!==vectors[received].status[3:0] || flags_o!==vectors[received].flags[4:0])
          $fatal(1,"FP mismatch index=%0d got=%h/%h/%h status=%h flags=%h expected=%h/%h/%h status=%h flags=%h",
            received,p_o,v_o,partial_o,status_o,flags_o,vectors[received].p,vectors[received].v,
            vectors[received].y,vectors[received].status,vectors[received].flags);
        $fwrite(logfd,"%0d,%0d,%0d,%h,%0d,%h,%h,%h,%0d,%0d\n",received,accept_cycle[received],cycle,
          epoch_o,last_o,p_o,v_o,partial_o,status_o,flags_o);
        received++;
      end
      #1;if(accepted)req_valid_i=0;
      if(offered-received>4)$fatal(1,"preparation credit overflow");
    end
    @(negedge clock);req_valid_i=0;rsp_ready_i=1;
    if(!idle_o)$fatal(1,"row not drained");
    repeat(40)begin @(negedge clock);if(rsp_valid_o)$fatal(1,"extra result");end
    // Local reset qualification only: drop a blocked arithmetic row and prove
    // no old partial/epoch reaches a fresh row. This is not an AXI soft reset.
    dot_i=1;sa_i=32'h3f800000;sw_i=32'h3f800000;initial_acc_i=0;
    first_i=1;last_i=1;tag_i=123;epoch_i=2;status_i=0;req_valid_i=1;
    do @(posedge clock);while(!req_ready_o);
    @(negedge clock);req_valid_i=0;rsp_ready_i=0;
    do @(negedge clock);while(!rsp_valid_o);
    repeat(40)@(negedge clock);
    reset_n=0;repeat(3)@(negedge clock);
    reset_n=1;epoch_i=3;req_valid_i=1;
    do @(posedge clock);while(!req_ready_o);
    @(negedge clock);req_valid_i=0;rsp_ready_i=1;
    do @(negedge clock);while(!rsp_valid_o);
    if(epoch_o!==3 || partial_o!==32'h3f800000 || status_o!==0)$fatal(1,"reset stale epoch");
    $fclose(logfd);
    $display("CE64_ORDERED_PASS groups=%0d held_checks=%0d cycles=%0d",count,held_checks,cycle);
    $finish;
  end
endmodule
