package nx_accel_map;
  // Mirror memory-map-v1.json; the contract test checks all boundary pairs.
  function automatic int shared_region(logic[31:0] a,logic[32:0] e,bit write_access);
    if(e<= {1'b0,a})return 0;
    if(!write_access&&a>=32'h80000000&&e<=33'ha8000000)return 1;
    if(a>=32'ha8000000&&e<=33'hac000000)return 2;
    if(a>=32'hac000000&&e<=33'hb4000000)return 3;
    if(a>=32'hba000000&&e<=33'hbc000000)return 4;
    return 0;
  endfunction
  function automatic bit burst_ok(logic[31:0] a,logic[7:0] len,logic[2:0] size,logic[1:0] burst,int max_size);
    logic[32:0] e;
    e={1'b0,a}+((33'(len)+1)<<size);
    return size<=max_size&&burst==1&&(a&((32'd1<<size)-1))==0&&e<=33'h100000000&&
      (a>>12)==((e-1)>>12);
  endfunction
  function automatic bit coral_local(logic[31:0] a,logic[32:0] e,bit wr);
    return (a>=32'h20000000&&e<=33'h20002000)||
      (a>=32'h20010000&&e<=33'h20018000)||
      (a>=32'h20030000&&e<=33'h20030008)||
      (!wr&&a==32'h20030008&&e<=33'h2003000c);
  endfunction
  function automatic bit cpu_memory(logic[31:0] a,logic[32:0] e,bit wr,bit owner);
    return (!wr&&a>=32'h00010000&&e<=33'h00020000)||
      (a>=32'h00020000&&e<=33'h00030000)||
      (a>=32'h10000000&&e<=33'h10000100)||
      (a>=32'hb4000000&&e<=33'hb8000000)||
      (!wr&&a>=32'hb8000000&&e<=33'hba000000)||
      (!owner&&shared_region(a,e,wr)!=0)||
      (!wr&&a>=32'h80000000&&e<=33'ha8000000);
  endfunction
endpackage
