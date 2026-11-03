`timescale 1ns/1ps
// Actual candidate DMA, persistent fault coordinator and DDR adapter. Commands
// come from this fixture, not the production CPU, scheduler or publication path.
module tb_service_observer;
  reg clk=0;always #4 clk=~clk;
  reg reset=1;initial begin repeat(8)@(negedge clk);reset=0;end
  longint unsigned cycles=0;always @(posedge clk)cycles<=cycles+1;
  wire timed_out=cycles>=2048;
  reg command_valid=0,command_write=0,result_ready=0;
  reg [31:0] command_address=0;
  reg [2:0] command_size=4;
  reg [4:0] command_len=0;
  reg [15:0] command_scratch=0,command_mask=16'hffff;
  reg [127:0] command_data=128'h00112233445566778899aabbccddeeff;
  wire command_ready,result_valid,dma_idle,pending_offer,scratch_en;
  wire [1:0] result_resp;
  wire [31:0] result_address;
  wire [11:0] scratch_addr;
  wire [127:0] scratch_data;
  wire [15:0] scratch_mask;
  wire [63:0] read_bytes,write_bytes;
  axi4_if #(.DATA_W(128),.ID_W(6)) backend(clk),memory(clk);
  wire stop_new,drained,reset_grant,faulted,quarantined,reset_pending;
  reg reset_request=0,run_timeout=0;
  wire [31:0] first_fault_address;
  reg [31:0] epoch=0;
  always @(posedge clk)if(reset)epoch<=0;else if(reset_grant)epoch<=epoch+1;
  reg owner=0;
  nx_ce64_dma dma(.clk,.reset_n(!reset),.stop_new,.command_valid,.command_write,.command_ready,
    .command_address,.command_size,.command_len,.command_scratch,.command_data,.command_mask,
    .result_valid,.result_ready,.result_resp,.result_address,.idle(dma_idle),.pending_offer,
    .scratch_en,.scratch_addr,.scratch_data,.scratch_mask,.read_bytes,.write_bytes,.bus(backend));
  wire native_pending,upstream_pending,native_safely_drained,native_quarantined,ddr_fault;
  wire [3:0] fault_reason;
  wire [63:0] ddr_cycles,write_payload_bytes,read_payload_bytes,native_write_bytes,native_read_bytes;
  nx_ce64_fault faults(.clk,.platform_reset_n(!reset),.isolate_request(1'b0),.reset_request,.run_timeout,
    .guard_fault(1'b0),.dma_fault(1'b0),.native_quarantined,.visible_fault_address(command_address),
    .dma_idle,.guard_idle(1'b1),.native_safely_drained,.arithmetic_idle(1'b1),.scratch_idle(1'b1),.commit_idle(1'b1),
    .stop_new,.drained,.reset_grant,.quarantined,.faulted,.reset_pending_o(reset_pending),.first_fault_address);
  // Legal environment backpressure between two unmodified actual modules.
  reg allow_b=0,allow_r=1;
  assign memory.awaddr=backend.awaddr;assign memory.awid=backend.awid;assign memory.awlen=backend.awlen;
  assign memory.awsize=backend.awsize;assign memory.awburst=backend.awburst;assign memory.awvalid=backend.awvalid;
  assign backend.awready=memory.awready;
  assign memory.wdata=backend.wdata;assign memory.wstrb=backend.wstrb;assign memory.wlast=backend.wlast;assign memory.wvalid=backend.wvalid;
  assign backend.wready=memory.wready;assign backend.bid=memory.bid;assign backend.bresp=memory.bresp;
  assign backend.bvalid=memory.bvalid&&allow_b;assign memory.bready=backend.bready&&allow_b;
  assign memory.araddr=backend.araddr;assign memory.arid=backend.arid;assign memory.arlen=backend.arlen;
  assign memory.arsize=backend.arsize;assign memory.arburst=backend.arburst;assign memory.arvalid=backend.arvalid;
  assign backend.arready=memory.arready;assign backend.rid=memory.rid;assign backend.rresp=memory.rresp;
  assign backend.rdata=memory.rdata;assign backend.rlast=memory.rlast;
  assign backend.rvalid=memory.rvalid&&allow_r;assign memory.rready=backend.rready&&allow_r;
  wire held_b_valid=memory.bvalid,held_r_valid=memory.rvalid;
  wire [27:0] d_awaddr,d_araddr;
  wire [3:0] d_awid,d_arid,d_awlen,d_arlen,d_rid;
  wire d_awvalid,d_arvalid,d_awready,d_arready,d_wready,d_wlast,d_rvalid,d_rlast;
  wire [255:0] d_wdata,d_rdata;wire [31:0] d_wstrb;
  nx_ce64_ddr_adapter #(.DATA_W(128),.ID_W(6),.WRITE_DRAIN_CYCLES(1024)) adapter(
    .clk,.rst_n(!reset),.ddr_init_done(!reset),
    .s_awaddr(memory.awaddr),.s_awid(memory.awid),.s_awlen(memory.awlen),.s_awsize(memory.awsize),.s_awburst(memory.awburst),.s_awvalid(memory.awvalid),.s_awready(memory.awready),
    .s_wdata(memory.wdata),.s_wstrb(memory.wstrb),.s_wlast(memory.wlast),.s_wvalid(memory.wvalid),.s_wready(memory.wready),
    .s_bid(memory.bid),.s_bresp(memory.bresp),.s_bvalid(memory.bvalid),.s_bready(memory.bready),
    .s_araddr(memory.araddr),.s_arid(memory.arid),.s_arlen(memory.arlen),.s_arsize(memory.arsize),.s_arburst(memory.arburst),.s_arvalid(memory.arvalid),.s_arready(memory.arready),
    .s_rdata(memory.rdata),.s_rid(memory.rid),.s_rresp(memory.rresp),.s_rvalid(memory.rvalid),.s_rlast(memory.rlast),.s_rready(memory.rready),
    .d_awaddr,.d_araddr,.d_awid,.d_arid,.d_awlen,.d_arlen,.d_awvalid,.d_arvalid,.d_awready,.d_arready,.d_wready,.d_wlast,.d_wdata,.d_wstrb,
    .d_rdata,.d_rid,.d_rvalid,.d_rlast,.native_pending,.upstream_pending,.safely_drained(native_safely_drained),
    .quarantined(native_quarantined),.fault(ddr_fault),.fault_reason,.cycles(ddr_cycles),.write_payload_bytes,.read_payload_bytes,.native_write_bytes,.native_read_bytes);
  ce64_native_memory_model native_model(.clk,.reset_n(!reset),.seed(32'd20261021),.max_delay(32'd3),
    .d_awaddr,.d_araddr,.d_awid,.d_arid,.d_awlen,.d_arlen,.d_awvalid,.d_arvalid,.d_awready,.d_arready,
    .d_wready,.d_wlast,.d_wdata,.d_wstrb,.d_rdata,.d_rid,.d_rvalid,.d_rlast);
  wire backend_idle=1; // Deliberately cannot stand in for actual transport drain.
  wire service_cpu_write_drained,service_backend_drained,service_ddr_drained,service_native_drained;
  wire [63:0] service_cpu_write_activity,service_backend_activity,service_ddr_activity,service_native_activity;
  nx_service_axi_observer #(.FILE("transport-backend.csv")) backend_observer(
    .clk,.reset,.cycles,.epoch,.owner,.fault(ddr_fault),.bus(backend),.idle(service_backend_drained),.activity(service_backend_activity));
  nx_service_axi_observer #(.FILE("transport-ddr.csv")) ddr_observer(
    .clk,.reset,.cycles,.epoch,.owner,.fault(ddr_fault),.bus(memory),.idle(service_ddr_drained),.activity(service_ddr_activity));
  nx_service_native_observer native_observer(.clk,.reset,.cycles,.epoch,.owner,
    .awaddr(d_awaddr),.araddr(d_araddr),.awid(d_awid),.arid(d_arid),.awlen(d_awlen),.arlen(d_arlen),
    .awvalid(d_awvalid),.awready(d_awready),.arvalid(d_arvalid),.arready(d_arready),
    .wready(d_wready),.wlast(d_wlast),.rvalid(d_rvalid),.rlast(d_rlast),.rid(d_rid),
    .commit_fire(native_model.commit_due==1),.model_pending(native_model.writing||native_model.reading||native_model.commit_due!=0),
    .idle(service_native_drained),.activity(service_native_activity));
  wire service_transport_drained=service_cpu_write_drained&&service_backend_drained&&service_ddr_drained&&service_native_drained&&
    dma_idle&&drained&&native_safely_drained&&!native_pending&&!upstream_pending&&!ddr_fault&&!native_quarantined&&owner==0;
  wire [63:0] service_transport_activity=service_cpu_write_activity+service_backend_activity+service_ddr_activity+service_native_activity;
  reg [127:0] observed_scratch=0;
  always @(posedge clk)if(scratch_en)observed_scratch<=scratch_data;
  reg [31:0] service_stack_peek_address=0;
  wire [31:0] service_stack_peek_value=service_stack_peek_address^32'h12345678;
  // CPU-channel observer fixture only, including legal W before AW. These
  // channels are not an RV32 CPU execution or production service qualification.
  axi4_if #(.DATA_W(32),.ID_W(1)) cpu_fixture(clk);
  reg cpu_fixture_awvalid=0,cpu_fixture_wvalid=0,cpu_fixture_bvalid=0;
  reg late_store=0,late_seen=0;
  reg [2:0] late_phase=0;
  assign cpu_fixture.awaddr=32'h2fe80;assign cpu_fixture.awid=0;assign cpu_fixture.awlen=0;
  assign cpu_fixture.awsize=2;assign cpu_fixture.awburst=1;assign cpu_fixture.awready=1;
  assign cpu_fixture.awvalid=cpu_fixture_awvalid||late_phase==1;
  assign cpu_fixture.wvalid=cpu_fixture_wvalid||late_phase==1;
  assign cpu_fixture.wlast=1;assign cpu_fixture.wdata=32'h1234;assign cpu_fixture.wstrb=4'hf;assign cpu_fixture.wready=1;
  assign cpu_fixture.bvalid=cpu_fixture_bvalid||late_phase==3;assign cpu_fixture.bready=1;
  assign cpu_fixture.bid=0;assign cpu_fixture.bresp=0;
  assign cpu_fixture.arvalid=0;assign cpu_fixture.rvalid=0;
  nx_service_axi_observer #(.FILE("transport-cpu.csv"),.READS(0)) cpu_observer(
    .clk,.reset,.cycles,.epoch,.owner,.fault(ddr_fault),.bus(cpu_fixture),
    .idle(service_cpu_write_drained),.activity(service_cpu_write_activity));
  longint unsigned cpu_write_accepts=0,cpu_write_responses=0;
  reg cpu_aw_seen=0,cpu_w_seen=0,cpu_joined=0;
  integer cpu_fd;
  initial begin cpu_fd=$fopen("transactions.csv","w");if(!cpu_fd)$fatal(1,"CPU fixture trace open");end
  always @(posedge clk)if(!reset)begin
    if(late_store&&!late_seen)begin late_seen<=1;late_phase<=1;end
    else if(late_phase!=0)late_phase<=late_phase==4 ? 0 : late_phase+1;
    if(cpu_fixture.awvalid&&cpu_fixture.awready)cpu_aw_seen<=1;
    if(cpu_fixture.wvalid&&cpu_fixture.wready)cpu_w_seen<=1;
    if(!cpu_joined&&(cpu_aw_seen||cpu_fixture.awvalid)&&(cpu_w_seen||cpu_fixture.wvalid))begin
      cpu_write_accepts<=cpu_write_accepts+1;cpu_joined<=1;
      $fwrite(cpu_fd,"%0d,CW,2fe80,1234,f,0\n",cycles);
    end
    if(cpu_fixture.bvalid&&cpu_fixture.bready)begin
      cpu_write_responses<=cpu_write_responses+1;
      $fwrite(cpu_fd,"%0d,CB,0,0,0,0\n",cycles);
      cpu_aw_seen<=0;cpu_w_seen<=0;cpu_joined<=0;
    end
  end
  final $fclose(cpu_fd);
endmodule
