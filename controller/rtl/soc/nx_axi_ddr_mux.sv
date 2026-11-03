// Serialize CPU I/D (32-bit/ID1) and Coral (128-bit/ID6) onto AXI128/ID6.
// Narrow CPU lanes move with the actual burst address, including cache refills.
// Selection is latched before asserting VALID and held through B or RLAST.
module nx_axi_ddr_mux(input logic clk, reset_n,
  input wire coral_w_capture,
  output wire memory_w_capture,
  axi4_if.slave cpu_i, cpu_d, coral, axi4_if.master memory);
  localparam IDLE=3'd0, ADDRESS=3'd1, WRITE=3'd2, RESPONSE=3'd3, READ=3'd4;
  logic [2:0] state, next_state, selected, priority_port;
  logic [5:0] rotated_requests;
  logic [3:0] candidate_sum;
  function automatic [2:0] first_request(input [5:0] r);
    if(r[0]) first_request=0; else if(r[1]) first_request=1;
    else if(r[2]) first_request=2; else if(r[3]) first_request=3;
    else if(r[4]) first_request=4; else if(r[5]) first_request=5;
    else first_request=7;
  endfunction
  logic [31:0] beat_address;
  logic [2:0] beat_size;
  logic [1:0] beat_burst;
  logic [7:0] write_left;
  logic [5:0] requests;
  logic [2:0] candidate;
  logic [3:0] lane;
  logic [2:0] b_pending;
  logic [5:0] b_id[0:2];
  logic [1:0] b_resp[0:2];
  // Sampled by the adapter only on its AR handshake. CPU I/D and writes
  // are excluded by the registered selection, even with CE work pending.
  assign memory_w_capture=state==ADDRESS && selected==3'd5 && coral_w_capture;
  always_comb begin
    requests={coral.arvalid,coral.awvalid&&!b_pending[2],cpu_d.arvalid,cpu_d.awvalid&&!b_pending[1],cpu_i.arvalid,cpu_i.awvalid&&!b_pending[0]};
    rotated_requests=(requests>>priority_port)|(requests<<(3'd6-priority_port));
    candidate_sum={1'b0,priority_port}+{1'b0,first_request(rotated_requests)};
    candidate=rotated_requests==0 ? 3'd7 : (candidate_sum>=6 ? 3'(candidate_sum-4'd6) : candidate_sum[2:0]);
    lane={beat_address[3:2],2'b00};
    memory.awaddr=0; memory.awid=0; memory.awlen=0; memory.awsize=0; memory.awburst=1; memory.awvalid=0;
    memory.wdata=0; memory.wstrb=0; memory.wlast=0; memory.wvalid=0; memory.bready=0;
    memory.araddr=0; memory.arid=0; memory.arlen=0; memory.arsize=0; memory.arburst=1; memory.arvalid=0; memory.rready=0;
    case(selected)
      0,1: begin
        memory.awaddr=cpu_i.awsize==2 && cpu_i.awlen==0 ? {cpu_i.awaddr[31:2],2'b00} : cpu_i.awaddr;
        memory.awid={5'b0,cpu_i.awid}; memory.awlen=cpu_i.awlen;
        memory.awsize=cpu_i.awsize<=2 ? cpu_i.awsize : 3'd7; memory.awburst=cpu_i.awburst;
        memory.awvalid=state==ADDRESS && !selected[0] && cpu_i.awvalid;
        memory.wdata={96'b0,cpu_i.wdata} << (8*lane); memory.wstrb={12'b0,cpu_i.wstrb} << lane;
        memory.wlast=cpu_i.wlast; memory.wvalid=state==WRITE && cpu_i.wvalid; memory.bready=state==RESPONSE;
        memory.araddr=cpu_i.araddr; memory.arid={5'b0,cpu_i.arid}; memory.arlen=cpu_i.arlen;
        memory.arsize=cpu_i.arsize<=2 ? cpu_i.arsize : 3'd7; memory.arburst=cpu_i.arburst;
        memory.arvalid=state==ADDRESS && selected[0] && cpu_i.arvalid; memory.rready=state==READ && cpu_i.rready;
      end
      2,3: begin
        // Vex cached partial stores: AW is byte-addressed with SIZE=2;
        // WSTRB already names lanes in the aligned 32-bit word.
        memory.awaddr=cpu_d.awsize==2 && cpu_d.awlen==0 ? {cpu_d.awaddr[31:2],2'b00} : cpu_d.awaddr;
        memory.awid={5'b0,cpu_d.awid}; memory.awlen=cpu_d.awlen;
        memory.awsize=cpu_d.awsize<=2 ? cpu_d.awsize : 3'd7; memory.awburst=cpu_d.awburst;
        memory.awvalid=state==ADDRESS && !selected[0] && cpu_d.awvalid;
        memory.wdata={96'b0,cpu_d.wdata} << (8*lane); memory.wstrb={12'b0,cpu_d.wstrb} << lane;
        memory.wlast=cpu_d.wlast; memory.wvalid=state==WRITE && cpu_d.wvalid; memory.bready=state==RESPONSE;
        memory.araddr=cpu_d.araddr; memory.arid={5'b0,cpu_d.arid}; memory.arlen=cpu_d.arlen;
        memory.arsize=cpu_d.arsize<=2 ? cpu_d.arsize : 3'd7; memory.arburst=cpu_d.arburst;
        memory.arvalid=state==ADDRESS && selected[0] && cpu_d.arvalid; memory.rready=state==READ && cpu_d.rready;
      end
      4,5: begin
        memory.awaddr=coral.awaddr; memory.awid=coral.awid; memory.awlen=coral.awlen; memory.awsize=coral.awsize; memory.awburst=coral.awburst;
        memory.awvalid=state==ADDRESS && !selected[0] && coral.awvalid;
        memory.wdata=coral.wdata; memory.wstrb=coral.wstrb; memory.wlast=coral.wlast;
        memory.wvalid=state==WRITE && coral.wvalid; memory.bready=state==RESPONSE;
        memory.araddr=coral.araddr; memory.arid=coral.arid; memory.arlen=coral.arlen; memory.arsize=coral.arsize; memory.arburst=coral.arburst;
        memory.arvalid=state==ADDRESS && selected[0] && coral.arvalid; memory.rready=state==READ && coral.rready;
      end
      default: begin end
    endcase
  end
`define NX_MUX(U,K,DW,IW) \
  assign U.awready=state==ADDRESS && selected==K && memory.awready; \
  assign U.wready=state==WRITE && selected==K && memory.wready; \
  assign U.bvalid=b_pending[K/2]; \
  assign U.bresp=b_resp[K/2]; assign U.bid=b_id[K/2][IW-1:0]; \
  assign U.arready=state==ADDRESS && selected==K+1 && memory.arready; \
  assign U.rvalid=state==READ && selected==K+1 && memory.rvalid; \
  assign U.rresp=memory.rresp; assign U.rid=memory.rid[IW-1:0]; assign U.rlast=memory.rlast;
  `NX_MUX(cpu_i,3'd0,32,1)
  `NX_MUX(cpu_d,3'd2,32,1)
  `NX_MUX(coral,3'd4,128,6)
`undef NX_MUX
  assign cpu_i.rdata=32'(memory.rdata >> (8*lane));
  assign cpu_d.rdata=32'(memory.rdata >> (8*lane));
  assign coral.rdata=memory.rdata;
  always_comb begin
    next_state=state;
    case(state)
      IDLE: if(candidate!=7) next_state=ADDRESS;
      ADDRESS: if(memory.awvalid&&memory.awready) next_state=WRITE;
        else if(memory.arvalid&&memory.arready) next_state=READ;
      WRITE: if(memory.wvalid&&memory.wready&&write_left==0) next_state=RESPONSE;
      RESPONSE: if(memory.bvalid&&memory.bready) next_state=IDLE;
      READ: if(memory.rvalid&&memory.rready&&memory.rlast) next_state=IDLE;
      default: next_state=IDLE;
    endcase
  end
  always_ff @(posedge clk or negedge reset_n) begin
    if(!reset_n) begin
      state<=IDLE; selected<=0; priority_port<=0; beat_address<=0; beat_size<=0; beat_burst<=1; write_left<=0; b_pending<=0;
      for(int p=0;p<3;p++) begin b_id[p]<=0; b_resp[p]<=0; end
    end else begin
      b_pending<=(b_pending & ~{coral.bvalid&&coral.bready,cpu_d.bvalid&&cpu_d.bready,cpu_i.bvalid&&cpu_i.bready}) |
        ((state==RESPONSE&&memory.bvalid&&memory.bready) ? (3'b001<<(selected/2)) : 3'b000);
      state<=next_state;
      case(state)
      IDLE: if(candidate!=7) begin selected<=candidate;  end
      ADDRESS: begin
        if(memory.awvalid && memory.awready) begin beat_address<=memory.awaddr; beat_size<=memory.awsize; beat_burst<=memory.awburst; write_left<=memory.awlen;  end
        else if(memory.arvalid && memory.arready) begin beat_address<=memory.araddr; beat_size<=memory.arsize; beat_burst<=memory.arburst;  end
      end
      WRITE: if(memory.wvalid && memory.wready) begin
        if(beat_burst==1) beat_address<=beat_address+(32'd1<<beat_size);
        write_left<=write_left-8'd1;
        
      end
      RESPONSE: if(memory.bvalid && memory.bready) begin
        b_id[selected/2]<=memory.bid; b_resp[selected/2]<=memory.bresp;
        priority_port<=selected==5 ? 3'd0 : selected+3'd1;
      end
      READ: if(memory.rvalid && memory.rready) begin
        if(beat_burst==1) beat_address<=beat_address+(32'd1<<beat_size);
        if(memory.rlast) begin priority_port<=selected==5 ? 3'd0 : selected+3'd1; end
      end
      default: begin end
      endcase
    end
  end
endmodule
