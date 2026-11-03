// Request-window observer. All inputs are passive; this module cannot stall a
// CPU/CE transaction or modify architectural state. Control commits only on a
// successful local-MMIO B handshake. See request-pmu.md for exact edge semantics.
module nx_ce64_request_pmu #(parameter integer COUNTER_WIDTH=64)(
  input logic clk,reset_n,
  input logic retire,execute_stall,branch,mispredict,
  axi4_if.master control,
  axi4_if cpu_i,cpu_d,ce,
  output wire [2047:0] snapshot
);
  localparam integer COUNT=24;
  logic [COUNTER_WIDTH-1:0] live[0:COUNT-1],frozen_hold[0:COUNT-1];
  wire [COUNTER_WIDTH-1:0] frozen[0:COUNT-1];
  logic capture_take,clear_take,capture_q,frozen_zero_q;
  logic [COUNTER_WIDTH:0] next_value[0:COUNT-1];
  logic [7:0] increment[0:COUNT-1];
  logic active,valid,protocol_error,overflow,frozen_overflow;
  logic [31:0] next_tag,active_tag,snapshot_tag,snapshot_sequence;
  logic have_aw,have_w;
  logic [31:0] address,data;
  logic [7:0] awlen;
  logic [2:0] awsize,ds,cs;
  logic [3:0] strobe;
  logic last;
  wire b_fire=control.bvalid&&control.bready;
  wire command=b_fire&&have_aw&&have_w&&control.bresp==0&&address==32'h100000b4;
  wire format_ok=awlen==0&&awsize==2&&strobe==15&&last;
  wire tag_write=b_fire&&have_aw&&have_w&&control.bresp==0&&address==32'h100000b0;
  function automatic [7:0] pop4(input [3:0] x);
    return {7'b0,x[0]}+{7'b0,x[1]}+{7'b0,x[2]}+{7'b0,x[3]};
  endfunction
  function automatic [7:0] pop16(input [15:0] x);
    reg [7:0] n;
    n=0;for(integer i=0;i<16;i=i+1)n=n+{7'b0,x[i]};return n;
  endfunction
  always_comb begin
    for(integer i=0;i<COUNT;i=i+1)increment[i]=0;
    increment[0]=1;
    increment[1]={7'b0,retire};increment[2]={7'b0,execute_stall};
    increment[3]={7'b0,branch};increment[4]={7'b0,branch&&mispredict};
    increment[5]={7'b0,cpu_i.arvalid&&cpu_i.arready};
    increment[6]={7'b0,cpu_i.rvalid&&cpu_i.rready};
    increment[7]=(cpu_i.rvalid&&cpu_i.rready)?8'd4:0;
    increment[8]={7'b0,cpu_i.arvalid&&!cpu_i.arready};
    increment[9]={7'b0,cpu_d.arvalid&&cpu_d.arready};
    increment[10]={7'b0,cpu_d.rvalid&&cpu_d.rready};
    increment[11]=(cpu_d.rvalid&&cpu_d.rready)?(8'd1<<ds):0;
    increment[12]={7'b0,cpu_d.awvalid&&cpu_d.awready};
    increment[13]={7'b0,cpu_d.wvalid&&cpu_d.wready};
    increment[14]=(cpu_d.wvalid&&cpu_d.wready)?pop4(cpu_d.wstrb):0;
    increment[15]={7'b0,(cpu_d.arvalid&&!cpu_d.arready)||(cpu_d.awvalid&&!cpu_d.awready)};
    increment[16]={7'b0,ce.arvalid&&ce.arready};
    increment[17]={7'b0,ce.rvalid&&ce.rready};
    increment[18]=(ce.rvalid&&ce.rready)?(8'd1<<cs):0;
    increment[19]={7'b0,ce.awvalid&&ce.awready};
    increment[20]={7'b0,ce.wvalid&&ce.wready};
    increment[21]=(ce.wvalid&&ce.wready)?pop16(ce.wstrb):0;
    increment[22]={7'b0,(ce.arvalid&&!ce.arready)||(ce.awvalid&&!ce.awready)};
    increment[23]={7'b0,cpu_i.rvalid&&cpu_i.rready&&cpu_i.rresp!=0}+
                  {7'b0,cpu_d.rvalid&&cpu_d.rready&&cpu_d.rresp!=0}+
                  {7'b0,cpu_d.bvalid&&cpu_d.bready&&cpu_d.bresp!=0}+
                  {7'b0,ce.rvalid&&ce.rready&&ce.rresp!=0}+
                  {7'b0,ce.bvalid&&ce.bready&&ce.bresp!=0};
  end
  // Only the low eight bits add the current event. Higher limbs precompute
  // +1 from their old payload and select it in parallel using cached prefixes.
  // Thus a late AXI event never propagates through a full-width carry chain.
  generate if(COUNTER_WIDTH<=8)begin:narrow_counter
    // Preserve the original cast/truncation semantics for validation widths.
    for(genvar ci=0;ci<COUNT;ci=ci+1)begin:counter
      assign next_value[ci]={1'b0,live[ci]}+(COUNTER_WIDTH+1)'(increment[ci]);
    end
  end else begin:limb_counter
    localparam integer HIGH_LIMBS=(COUNTER_WIDTH+7)/8-1;
    for(genvar ci=0;ci<COUNT;ci=ci+1)begin:counter
      logic [HIGH_LIMBS:1] prefix_ones;
      wire [8:0] low_sum={1'b0,live[ci][7:0]}+{1'b0,increment[ci]};
      wire top_carry=low_sum[8]&&prefix_ones[HIGH_LIMBS];
      wire [COUNTER_WIDTH:0] limb_sum;
      assign limb_sum[7:0]=low_sum[7:0];
      assign limb_sum[COUNTER_WIDTH]=top_carry;
      for(genvar li=1;li<=HIGH_LIMBS;li=li+1)begin:high_limb
        localparam integer LIMB_BITS=(COUNTER_WIDTH-li*8<8)?COUNTER_WIDTH-li*8:8;
        localparam integer PREFIX_BITS=li*8+LIMB_BITS-8;
        localparam logic [PREFIX_BITS-1:0] PREFIX_BEFORE_ALL_ONES={{(PREFIX_BITS-1){1'b1}},1'b0};
        wire [LIMB_BITS-1:0] old_limb=live[ci][li*8+:LIMB_BITS];
        wire [LIMB_BITS-1:0] plus_one=old_limb+LIMB_BITS'(1);
        wire carry_in;
        if(li==1)assign carry_in=low_sum[8];
        else assign carry_in=low_sum[8]&&prefix_ones[li-1];
        assign limb_sum[li*8+:LIMB_BITS]=carry_in?plus_one:old_limb;
        wire prefix_before_all_ones=live[ci][8+:PREFIX_BITS]==PREFIX_BEFORE_ALL_ONES;
        // Prefix payload is unobservable while inactive. Every inactive clock
        // prepares zero, including the legal START edge before counting.
        // Public commands still commit at the original B handshake.
        always_ff @(posedge clk)begin
          if(!active)prefix_ones[li]<=0;
          else if(active)begin
            if(top_carry)prefix_ones[li]<=1;
            else if(low_sum[8])prefix_ones[li]<=prefix_before_all_ones;
          end
        end
      end
      // The old full-width + pessimistically poisons its entire result for
      // any X/Z operand bit. Keep that simulation contract. This self-XOR is
      // identically zero in binary hardware and synthesis removes it.
      wire unknown_operand=(^{live[ci],increment[ci]})^(^{live[ci],increment[ci]});
      assign next_value[ci]=limb_sum^{(COUNTER_WIDTH+1){unknown_operand}};
    end
  end endgenerate
  wire any_overflow;
  logic overflow_now;
  always_comb begin
    overflow_now=0;for(integer i=0;i<COUNT;i=i+1)overflow_now|=next_value[i][COUNTER_WIDTH];
  end
  assign any_overflow=overflow_now;
  assign snapshot[31:0]=32'h3152504e; // NPR1
  assign snapshot[63:32]={16'd1,11'b0,frozen_overflow,overflow,protocol_error,valid,active};
  assign snapshot[95:64]=snapshot_tag;
  assign snapshot[127:96]=snapshot_sequence;
  for(genvar i=0;i<COUNT;i=i+1)begin:expose
    assign snapshot[128+i*64+:64]=64'(frozen[i]);
  end
  assign snapshot[2047:1664]=384'b0;
  // Preserve the exact successful-B procedural command policy, including
  // the original negative-format if semantics for four-state inputs.
  always_comb begin
    capture_take=0;clear_take=0;
    if(command)begin
      if(!format_ok)begin end
      else case(data)
        2,3:begin
          if(!active||snapshot_sequence==32'hffffffff)begin end
          else capture_take=1;
        end
        4:begin if(active)begin end else clear_take=1;end
        default:;
      endcase
    end
  end
  // Capture publishes this edge's inclusive live value immediately. On the
  // next edge the old live value moves to the original-sized holding bank,
  // before counting, START preparation or inactive clearing can change it.
  // No late B handshake or platform reset drives this wide bank's enable.
  always_ff @(posedge clk or negedge reset_n)begin
    if(!reset_n)begin capture_q<=0;frozen_zero_q<=1;end
    else begin
      capture_q<=capture_take;
      if(clear_take)frozen_zero_q<=1;
      else if(capture_take)frozen_zero_q<=0;
    end
  end
  for(genvar fi=0;fi<COUNT;fi=fi+1)begin:frozen_bank
    always_ff @(posedge clk)begin
      if(capture_q)frozen_hold[fi]<=live[fi];
    end
    assign frozen[fi]=frozen_zero_q ? {COUNTER_WIDTH{1'b0}} : capture_q ? live[fi] : frozen_hold[fi];
  end
  // Live counters are private while inactive; only frozen is exposed.
  // Prepare the next START state every stopped clock. START excludes its
  // commit edge; STOP/SNAPSHOT still include theirs through old active.
  // This removes late command/B-ready from all live-counter enables.
  always_ff @(posedge clk or negedge reset_n)begin
    if(!reset_n)begin
      for(integer i=0;i<COUNT;i=i+1)live[i]<=0;
    end else begin
      for(integer i=0;i<COUNT;i=i+1)begin
        if(active)live[i]<=next_value[i][COUNTER_WIDTH]?{COUNTER_WIDTH{1'b1}}:next_value[i][COUNTER_WIDTH-1:0];
        else live[i]<=0;
      end
    end
  end
  always_ff @(posedge clk or negedge reset_n)begin
    if(!reset_n)begin
      active<=0;valid<=0;protocol_error<=0;overflow<=0;frozen_overflow<=0;
      next_tag<=0;active_tag<=0;snapshot_tag<=0;snapshot_sequence<=0;
      have_aw<=0;have_w<=0;address<=0;data<=0;awlen<=0;awsize<=0;strobe<=0;last<=0;ds<=2;cs<=4;
    end else begin
      // Sizes are tracked even while stopped, so a boundary may fall during an
      // outstanding transaction. I bus is fixed 32-bit by the T09 contract.
      if(cpu_d.arvalid&&cpu_d.arready)ds<=cpu_d.arsize;
      if(ce.arvalid&&ce.arready)cs<=ce.arsize;
      if(control.awvalid&&control.awready)begin have_aw<=1;address<=control.awaddr;awsize<=control.awsize;awlen<=control.awlen;end
      if(control.wvalid&&control.wready)begin have_w<=1;data<=control.wdata;strobe<=control.wstrb;last<=control.wlast;end
      if(b_fire)begin have_aw<=0;have_w<=0;end
      if(active)begin
        if(any_overflow)overflow<=1;
      end
      if(tag_write)begin if(format_ok)next_tag<=data;else protocol_error<=1;end
      if(command)begin
        if(!format_ok)protocol_error<=1;
        else case(data)
          1:begin // START: exclude this edge; count the next edge onward.
            if(active)protocol_error<=1;
            else begin
              active<=1;valid<=0;overflow<=0;frozen_overflow<=0;active_tag<=next_tag;
            end
          end
          2,3:begin // SNAPSHOT/STOP: include this edge, freeze all values together.
            // Even when the sequence is exhausted, STOP releases the window so
            // software can CLEAR and recover without a platform reset. A
            // rejected capture never wraps the sequence or changes its data.
            if(data==3&&active)active<=0;
            if(!active||snapshot_sequence==32'hffffffff)protocol_error<=1;
            else begin
              snapshot_tag<=active_tag;snapshot_sequence<=snapshot_sequence+1'b1;valid<=1;
              frozen_overflow<=overflow||any_overflow;
            end
          end
          4:begin // CLEAR is only legal while stopped.
            if(active)protocol_error<=1;
            else begin
              valid<=0;protocol_error<=0;overflow<=0;frozen_overflow<=0;next_tag<=0;active_tag<=0;snapshot_tag<=0;snapshot_sequence<=0;
            end
          end
          default:protocol_error<=1;
        endcase
      end
    end
  end
endmodule
