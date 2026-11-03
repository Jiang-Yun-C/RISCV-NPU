// CPU data AXI router + 32-to-128 native Coral lane adapter. One CPU write is
// accepted through B before ANY later read/MMIO side effect can complete.
module nx_accel_bridge(input logic clk,reset_n,
  input logic backend_idle,backend_error,backend_irq,input logic[31:0] backend_fault_address,
  output logic owner,isolate,clear_backend_error,irq,
  axi4_if.slave cpu,axi4_if.master memory,axi4_if.master coral);
  import nx_accel_map::*;
  typedef enum logic[2:0]{MEM,CORAL,CSR,REJECT} target_t;
  logic aw_have,w_have,aw_sent,w_sent,write_started,ar_have,ar_sent;
  logic[31:0] wa,ra,wd;
  logic[3:0] strobe;
  logic[2:0] ws,rs;
  logic[7:0] rl,rbeat;
  logic aw_invalid,wlast;
  target_t wt,rt;
  logic cpu_error,irq_pending,irq_enable,previous_irq;
  logic[31:0] fault_address;
  logic[32:0] we;
  assign irq=irq_pending&&irq_enable;
  assign cpu.awready=!aw_have&&!cpu.bvalid&&!ar_have&&!cpu.rvalid;
  assign cpu.wready=!w_have&&!cpu.bvalid&&!ar_have&&!cpu.rvalid;
  assign cpu.arready=!ar_have&&!cpu.rvalid&&!aw_have&&!w_have&&!cpu.bvalid&&!cpu.awvalid&&!cpu.wvalid;
  assign we=({1'b0,wa}>>ws<<ws)+(33'd1<<ws);
  function automatic logic[3:0] cpu_strobe_mask(logic[31:0] a,logic[2:0] size);
    logic[3:0] mask;
    mask=0;
    for(int i=0;i<4;i++)if(i>=a[1:0]&&i<((int'(a[1:0])/(1<<size))+1)*(1<<size))mask[i]=1;
    return mask;
  endfunction
  function automatic bit is_csr(logic[31:0] a);
    return a>=32'h10000100&&a<=32'h10000114&&a[1:0]==0;
  endfunction
  function automatic logic[31:0] csr_read(logic[31:0] a);
    case(a)
      32'h10000100:return {30'b0,isolate,owner};
      32'h10000104:return {29'b0,backend_error,cpu_error,backend_idle};
      32'h10000108:return 0;
      32'h1000010c:return {31'b0,irq_pending};
      32'h10000110:return backend_error?backend_fault_address:fault_address;
      32'h10000114:return {31'b0,irq_enable};
      default:return 0;
    endcase
  endfunction
  assign memory.awaddr=wa;assign memory.awlen=0;assign memory.awsize=ws;assign memory.awid=0;assign memory.awburst=1;
  assign memory.awvalid=write_started&&wt==MEM&&!aw_sent;
  assign memory.wvalid=write_started&&wt==MEM&&!w_sent;assign memory.wdata=wd;assign memory.wstrb=strobe;assign memory.wlast=1;
  assign memory.bready=write_started&&wt==MEM&&aw_sent&&w_sent&&!cpu.bvalid;
  assign coral.awaddr=wa-32'h20000000;assign coral.awlen=0;assign coral.awsize=ws;assign coral.awid=0;assign coral.awburst=1;
  assign coral.awvalid=write_started&&wt==CORAL&&!aw_sent;
  assign coral.wvalid=write_started&&wt==CORAL&&!w_sent;
  assign coral.wdata={96'b0,wd}<<(8*{wa[3:2],2'b00});
  assign coral.wstrb={12'b0,strobe}<<{wa[3:2],2'b00};assign coral.wlast=1;
  assign coral.bready=write_started&&wt==CORAL&&aw_sent&&w_sent&&!cpu.bvalid;
  assign memory.araddr=ra;assign memory.arlen=rl;assign memory.arsize=rs;assign memory.arid=0;assign memory.arburst=1;
  assign memory.arvalid=ar_have&&rt==MEM&&!ar_sent;
  assign memory.rready=ar_have&&rt==MEM&&ar_sent&&!cpu.rvalid;
  assign coral.araddr=ra-32'h20000000;assign coral.arlen=0;assign coral.arsize=rs;assign coral.arid=0;assign coral.arburst=1;
  assign coral.arvalid=ar_have&&rt==CORAL&&!ar_sent;
  assign coral.rready=ar_have&&rt==CORAL&&ar_sent&&!cpu.rvalid;
  wire take_aw=cpu.awvalid&&cpu.awready;
  wire take_w=cpu.wvalid&&cpu.wready;
  wire take_ar=cpu.arvalid&&cpu.arready;
  wire take_b=cpu.bvalid&&cpu.bready;
  wire take_r=cpu.rvalid&&cpu.rready;
  wire start_write=aw_have&&w_have&&!write_started;
  wire send_aw=(memory.awvalid&&memory.awready)||(coral.awvalid&&coral.awready);
  wire send_w=(memory.wvalid&&memory.wready)||(coral.wvalid&&coral.wready);
  wire send_ar=(memory.arvalid&&memory.arready)||(coral.arvalid&&coral.arready);
  wire receive_b=(memory.bvalid&&memory.bready)||(coral.bvalid&&coral.bready);
  wire receive_r=(memory.rvalid&&memory.rready)||(coral.rvalid&&coral.rready);
  wire local_b=write_started&&!cpu.bvalid&&(wt==REJECT||wt==CSR);
  wire local_r=ar_have&&!cpu.rvalid&&(rt==REJECT||rt==CSR);
  wire csr_write=local_b&&wt==CSR;
  wire control_bad=(!wd[0]&&!backend_idle)||(!wd[1]&&isolate&&!backend_idle)||wd[31:2]!=0;
  wire csr_known_write=wa==32'h10000100||wa==32'h10000108||wa==32'h1000010c||wa==32'h10000114;
  wire [1:0] local_bresp=wt==REJECT||!csr_known_write?2'd3:
                         wa==32'h10000100&&control_bad?2'd2:2'd0;
  wire [1:0] backend_bresp=wt==MEM?memory.bresp:coral.bresp;
  wire [1:0] backend_rresp=rt==MEM?memory.rresp:coral.rresp;
  wire write_fault=(local_b&&local_bresp!=0)||(receive_b&&backend_bresp!=0);
  wire read_fault=(local_r&&rt==REJECT)||(receive_r&&backend_rresp!=0);
  wire clear_fault=csr_write&&wa==32'h10000108&&backend_idle;
  wire ack_irq=csr_write&&wa==32'h1000010c&&wd[0];
  always_ff @(posedge clk)begin
    if(!reset_n)begin
      owner<=0;isolate<=1;clear_backend_error<=0;cpu_error<=0;irq_pending<=0;irq_enable<=0;previous_irq<=0;fault_address<=0;
      aw_have<=0;w_have<=0;aw_sent<=0;w_sent<=0;write_started<=0;ar_have<=0;ar_sent<=0;
      wt<=REJECT;rt<=REJECT;wa<=0;ra<=0;wd<=0;ws<=0;rs<=0;strobe<=0;rl<=0;rbeat<=0;aw_invalid<=0;wlast<=0;
      cpu.bvalid<=0;cpu.bresp<=0;cpu.bid<=0;cpu.rvalid<=0;cpu.rdata<=0;cpu.rresp<=0;cpu.rlast<=0;cpu.rid<=0;
    end else begin
      clear_backend_error<=clear_fault;previous_irq<=backend_irq;
      // CSR acknowledgement wins over a simultaneous backend IRQ edge.
      if(ack_irq)irq_pending<=0;else if(backend_irq&&!previous_irq)irq_pending<=1;
      // Read faults win over write faults; a clear only applies without a fault.
      if(read_fault)begin cpu_error<=1;fault_address<=ra;end
      else if(write_fault)begin cpu_error<=1;fault_address<=wa;end
      else if(clear_fault)begin cpu_error<=0;fault_address<=0;end
      if(take_b)begin aw_have<=0;w_have<=0;aw_sent<=0;w_sent<=0;write_started<=0;end
      else begin
        if(take_aw)aw_have<=1;
        if(take_w)w_have<=1;
        if(send_aw)aw_sent<=1;
        if(send_w)w_sent<=1;
        if(start_write)write_started<=1;
      end
      if(take_aw)begin
        wa<=cpu.awaddr;ws<=cpu.awsize;
        // Vex cached partial stores use AWSIZE=2 with an unaligned AW and WSTRB.
        aw_invalid<=cpu.awlen!=0||cpu.awsize>2||cpu.awburst!=1;
      end
      if(take_w)begin wd<=cpu.wdata;strobe<=cpu.wstrb;wlast<=cpu.wlast;end
      if(start_write)begin
        if(aw_invalid||!wlast|| (strobe & ~cpu_strobe_mask(wa,ws))!=0)wt<=REJECT;
        else if(is_csr(wa)&&ws==2&&strobe==15)wt<=CSR;
        else if(coral_local(wa,we,1))begin
          // A running core cannot be reset while its accepted AXI requests remain.
          if(wa==32'h20030000&&((wd==3&&!backend_idle)||(wd==0&&(!owner||isolate))))wt<=REJECT;
          else wt<=CORAL;
        end
        else if(cpu_memory(wa,we,1,owner))wt<=MEM;
        else wt<=REJECT;
      end
      if(local_b)begin cpu.bvalid<=1;cpu.bresp<=local_bresp;end
      else if(receive_b)begin cpu.bvalid<=1;cpu.bresp<=backend_bresp;end
      else if(take_b)cpu.bvalid<=0;
      if(csr_write)begin
        case(wa)
          32'h10000100:if(!control_bad)begin owner<=wd[0];isolate<=wd[1];end
          32'h10000114:irq_enable<=wd[0];
          default: ;
        endcase
      end
      if(take_r&&cpu.rlast)begin ar_have<=0;ar_sent<=0;end
      else begin
        if(take_ar)ar_have<=1;
        if(send_ar)ar_sent<=1;
      end
      if(take_ar)rbeat<=0;else if(take_r)rbeat<=rbeat+1;
      if(take_ar)begin
        ra<=cpu.araddr;rs<=cpu.arsize;rl<=cpu.arlen;
        if(!burst_ok(cpu.araddr,cpu.arlen,cpu.arsize,cpu.arburst,2))rt<=REJECT;
        else if(is_csr(cpu.araddr)&&cpu.arlen==0&&cpu.arsize==2)rt<=CSR;
        else if(coral_local(cpu.araddr,{1'b0,cpu.araddr}+((33'(cpu.arlen)+1)<<cpu.arsize),0)&&cpu.arlen==0)rt<=CORAL;
        else if(cpu_memory(cpu.araddr,{1'b0,cpu.araddr}+((33'(cpu.arlen)+1)<<cpu.arsize),0,owner))rt<=MEM;
        else rt<=REJECT;
      end
      if(local_r)begin
        cpu.rvalid<=1;cpu.rdata<=rt==CSR?csr_read(ra):0;cpu.rresp<=rt==REJECT?3:0;cpu.rlast<=rbeat==rl;
      end else if(receive_r)begin
        cpu.rvalid<=1;cpu.rdata<=rt==MEM?memory.rdata:32'(coral.rdata>>(8*{ra[3:2],2'b00}));
        cpu.rresp<=backend_rresp;cpu.rlast<=rt==MEM?memory.rlast:coral.rlast;
      end else if(take_r)cpu.rvalid<=0;
    end
  end
endmodule
