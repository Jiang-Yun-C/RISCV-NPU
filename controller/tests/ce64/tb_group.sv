`timescale 1ns/1ps
module tb_group;
  parameter bit PARALLEL=0;
  logic clock=0,reset_n=0,req_valid_i=0,req_ready_o,rsp_valid_o,rsp_ready_i=0;
  logic [127:0] aq_i=0,wq_i=0;
  logic [15:0] keep_i=0;
  logic first_i=0,last_i=0;
  logic [31:0] sa_i=0,sw_i=0,acc_i=0,tag_i=0,epoch_i=0;
  logic signed [31:0] dot_o;
  logic [31:0] p_o,v_o,partial_o,tag_o,epoch_o;
  logic [3:0] status_o;
  logic [4:0] flags_o;
  nx_ce64_group_probe #(.PARALLEL(PARALLEL)) dut(.*);
  always #4 clock=~clock;
  logic [511:0] a,w;
  logic [31:0] dot,p,v,y;
  logic [3:0] status;
  logic [4:0] flags;
  integer fd,logfd,n,count,len,offset,beat_count,checks=0,cycle=0,last_cycle,random_seed=16;
  string file;
  initial begin
    n=$urandom(random_seed);
    if(!$value$plusargs("vectors=%s",file))$fatal(1,"missing vectors");
    fd=$fopen(file,"r");if(!fd)$fatal(1,"no vector file");
    logfd=$fopen("groups.csv","w");$fwrite(logfd,"index,last_accept,returned,dot,p,v,partial,status,flags\n");
    repeat(4)@(negedge clock);reset_n=1;count=0;
    while(!$feof(fd))begin
      n=$fscanf(fd,"%d %h %h %h %h %h %h %h %h %h %h %h\n",len,a,w,sa_i,sw_i,acc_i,dot,p,v,y,status,flags);
      if(n==-1)break;
      if(n!=12 || len<1 || len>64)$fatal(1,"malformed vector");
      rsp_ready_i=0;
      for(offset=0;offset<len;offset=offset+16)begin
        repeat($urandom_range(0,2))@(negedge clock);
        aq_i=a[offset*8+:128];wq_i=w[offset*8+:128];beat_count=len-offset<16 ? len-offset : 16;
        keep_i=16'hffff >> (16-beat_count);first_i=offset==0;last_i=offset+16>=len;
        tag_i=count;epoch_i=32'hce640002;req_valid_i=1;
        do @(posedge clock);while(!req_ready_o);
        last_cycle=cycle;
        @(negedge clock);req_valid_i=0;
      end
      do @(negedge clock);while(!rsp_valid_o);
      if(dot_o!==dot || {p_o,v_o,partial_o}!=={p,v,y} || status_o!==status || flags_o!==flags
          || tag_o!==32'(count)||epoch_o!==32'hce640002)
        $fatal(1,"group mismatch i=%0d got dot=%h p=%h v=%h y=%h status=%h flags=%h exp dot=%h p=%h v=%h y=%h status=%h flags=%h",count,dot_o,p_o,v_o,partial_o,status_o,flags_o,dot,p,v,y,status,flags);
      checks+=7;
      repeat(count%89==0 ? 40 : $urandom_range(0,4)) begin
        @(negedge clock);
        if(dot_o!==dot || {p_o,v_o,partial_o}!=={p,v,y} || status_o!==status || !rsp_valid_o)$fatal(1,"unstable output");
        checks++;
      end
      $fwrite(logfd,"%0d,%0d,%0d,%h,%h,%h,%h,%0d,%0d\n",count,last_cycle,cycle,dot_o,p_o,v_o,partial_o,status_o,flags_o);
      rsp_ready_i=1;@(negedge clock);rsp_ready_i=0;count++;
    end
    if(count<1000)$fatal(1,"empty test");
    // Explicit K65 / K127 two-group chains, feeding the DUT's previous partial
    // back as the next accumulator. All actual q are 1; masked tail q are -128.
    for(integer kcase=0;kcase<2;kcase++)begin
      acc_i=0;sa_i=32'h3f800000;sw_i=32'h3f800000;
      for(integer group=0;group<2;group++)begin
        len=group==0 ? 64 : (kcase==0 ? 1 : 63);
        for(offset=0;offset<len;offset=offset+16)begin
          beat_count=len-offset<16 ? len-offset : 16;
          aq_i={16{8'h80}};wq_i=aq_i;
          for(integer lane=0;lane<beat_count;lane++)begin aq_i[8*lane+:8]=1;wq_i[8*lane+:8]=1;end
          keep_i=16'hffff>>(16-beat_count);first_i=offset==0;last_i=offset+16>=len;
          tag_i=200000+kcase*2+group;epoch_i=15;req_valid_i=1;
          do @(posedge clock);while(!req_ready_o);
          @(negedge clock);req_valid_i=0;
        end
        do @(negedge clock);while(!rsp_valid_o);
        if(status_o!==0 || dot_o!==32'(len) || partial_o!==(group==0 ? 32'h42800000 : (kcase==0 ? 32'h42820000 : 32'h42fe0000)))
          $fatal(1,"K65/K127 chain mismatch");
        acc_i=partial_o;rsp_ready_i=1;@(negedge clock);rsp_ready_i=0;
      end
    end
    // Interrupted group cannot leak into a new reset/epoch session.
    aq_i='0;wq_i='0;sa_i=32'h3f800000;sw_i=sa_i;acc_i=0;
    keep_i='1;first_i=1;last_i=0;epoch_i=9;tag_i=99;req_valid_i=1;
    do @(posedge clock);while(!req_ready_o);
    @(negedge clock);req_valid_i=0;reset_n=0;repeat(3)@(negedge clock);
    reset_n=1;epoch_i=10;last_i=1;keep_i=1;req_valid_i=1;
    do @(posedge clock);while(!req_ready_o);
    @(negedge clock);req_valid_i=0;
    do @(negedge clock);while(!rsp_valid_o);
    if(epoch_o!==10 || status_o!==0 || partial_o!==0)$fatal(1,"stale local arithmetic");
    $fclose(fd);$fclose(logfd);
    $display("CE64_GROUP_PASS parallel=%0d groups=%0d checks=%0d explicit_K65_K127=4",PARALLEL,count,checks);$finish;
  end
  always @(posedge clock)begin cycle++;if(cycle>3000000)$fatal(1,"group watchdog");end
endmodule
