module nx_opt11_control #(parameter integer LANES=2,FP32_OUTPUT_PACK=1,FP32_OUTPUT_BURST=1,QUANT_OUTPUT_BURST=1,SEALED_NORM_READ=1,parameter bit DEADLINE_CACHE=0,EXTERNAL_FP=0,CROSS_GROUP_WRITE=1) (

  output wire shared_start,shared_multiply,
  output wire [31:0] shared_a,shared_b,
  input wire shared_ready,shared_valid,input wire [31:0] shared_result,
  input logic clk, platform_reset_n, submit, reset_grant, stop_new, abort_publish,
  input logic [1023:0] descriptor,
  input wire resident_authorized,
  input wire resident_certificate_fault,
  output wire resident_row_check,
  input wire [1:0] resident_row,
  input logic [31:0] epoch, generation, first_fault_address,
  input logic [63:0] run_limit,run_limit_next,
  input logic transport_drained, native_quarantined,
  output logic engine_idle, arithmetic_idle, scratch_idle, timeout_fault, call_fault,
  output logic [1279:0] completion,
  output logic completion_valid,
  input logic completion_ready,
  output logic [511:0] perf,
  input logic dma_ready,dma_result_valid,dma_idle,
  input logic [1:0] dma_resp,
  output logic dma_valid,dma_write,dma_result_ready,
  output logic [31:0] dma_address,
  output logic [2:0] dma_size,
  output logic [4:0] dma_len,
  output logic [15:0] dma_scratch,
  output logic [127:0] dma_data,
  output logic [15:0] dma_mask,
  output logic ram_en,
  output logic [11:0] ram_address,
  output logic [15:0] ram_mask,
  output logic [127:0] ram_data,
  input logic [127:0] ram_q
);

  localparam logic [5:0] IDLE=0,VALIDATE=1,READ_G=2,READ_U=3,G_START=4,GET_G=5,GET_G_WAIT=6,
    GET_U=7,GET_U_WAIT=8,LOAD=9,G_WAIT=10,WRITE_Q=11,WRITE_S=12,WRITE_FP=13,
    NEXT_GROUP=14,DMA_REQ=15,DMA_WAIT=16,DRAIN=17,PUBLISH=18,DONE=19,RANGE=20,OVERLAP=21,FP_PEEK=22,SUM_GET=23,SUM_WAIT=24,SUM_SAVE=25,REDUCE_NEXT=26,NEXT_PASS=27,SCALAR_WRITE=28,VALIDATE_RESULT=29,FP_STORE=30,FP_FLUSH=31,FP_TAIL_PEEK=32,FP_TAIL_WRITE=33,Q_STORE=34,Q_FLUSH=35,NORM_LOOKUP=36,NORM_COMPARE=37,S_STORE=38,AG_FP_FLUSH=39,AG_Q_FLUSH=40,AG_S_FLUSH=41,AG_S_GET=42,AG_S_WAIT=43,AG_S_WRITE=44;
  reg [5:0] state,ret;
  // Fixed verified-model norm table. Lookup is registered before the only
  // 32-bit equality comparison; every miss is a bounded pre-DMA rejection.
  reg [5:0] norm_check_index;
  reg [31:0] norm_catalog_base;
  function automatic [31:0] norm_catalog_address(input [5:0] slot);
    begin case(slot)
      6'd0:norm_catalog_address=32'h889f1400;
      6'd1:norm_catalog_address=32'h88bcf400;
      6'd2:norm_catalog_address=32'h8990fa00;
      6'd3:norm_catalog_address=32'h89aeda00;
      6'd4:norm_catalog_address=32'h8a82e000;
      6'd5:norm_catalog_address=32'h8aa0c000;
      6'd6:norm_catalog_address=32'h8b74c600;
      6'd7:norm_catalog_address=32'h8b92a600;
      6'd8:norm_catalog_address=32'h8c66ac00;
      6'd9:norm_catalog_address=32'h8c848c00;
      6'd10:norm_catalog_address=32'h8d589200;
      6'd11:norm_catalog_address=32'h8d767200;
      6'd12:norm_catalog_address=32'h8e4a7800;
      6'd13:norm_catalog_address=32'h8e685800;
      6'd14:norm_catalog_address=32'h8f3c5e00;
      6'd15:norm_catalog_address=32'h8f5a3e00;
      6'd16:norm_catalog_address=32'h902e4400;
      6'd17:norm_catalog_address=32'h904c2400;
      6'd18:norm_catalog_address=32'h91202a00;
      6'd19:norm_catalog_address=32'h913e0a00;
      6'd20:norm_catalog_address=32'h92121000;
      6'd21:norm_catalog_address=32'h922ff000;
      6'd22:norm_catalog_address=32'h9303f600;
      6'd23:norm_catalog_address=32'h9321d600;
      6'd24:norm_catalog_address=32'h93f5dc00;
      6'd25:norm_catalog_address=32'h9413bc00;
      6'd26:norm_catalog_address=32'h94e7c200;
      6'd27:norm_catalog_address=32'h9505a200;
      6'd28:norm_catalog_address=32'h95d9a800;
      6'd29:norm_catalog_address=32'h95f78800;
      6'd30:norm_catalog_address=32'h96cb8e00;
      6'd31:norm_catalog_address=32'h96e96e00;
      6'd32:norm_catalog_address=32'h97bd7400;
      6'd33:norm_catalog_address=32'h97db5400;
      6'd34:norm_catalog_address=32'h98af5a00;
      6'd35:norm_catalog_address=32'h98cd3a00;
      6'd36:norm_catalog_address=32'h99a14000;
      6'd37:norm_catalog_address=32'h99bf2000;
      6'd38:norm_catalog_address=32'h9a932600;
      6'd39:norm_catalog_address=32'h9ab10600;
      6'd40:norm_catalog_address=32'h9b850c00;
      6'd41:norm_catalog_address=32'h9ba2ec00;
      6'd42:norm_catalog_address=32'h9c76f200;
      6'd43:norm_catalog_address=32'h9c94d200;
      6'd44:norm_catalog_address=32'h9d68d800;
      6'd45:norm_catalog_address=32'h9d86b800;
      6'd46:norm_catalog_address=32'h9e5abe00;
      6'd47:norm_catalog_address=32'h9e789e00;
      6'd48:norm_catalog_address=32'h9f4ca400;
      default:norm_catalog_address=0;
    endcase end
  endfunction

  reg [31:0] d[0:31];
  reg signed [31:0] status;
  // Authorization is an explicit private lease from the dispatcher. Data is
  // retained in the existing synchronous scratch; public vector outputs keep
  // their original DDR contract.
  wire certificate_fault=resident_certificate_fault===1'b1;
  assign resident_row_check=state==NEXT_GROUP&&aggregate_last;
  reg resident_active;
  reg [1:0] resident_active_row;
  always @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)begin resident_active<=0;resident_active_row<=0;end
    else if(reset_grant)begin resident_active<=0;resident_active_row<=0;end
    else if((state==IDLE||state==DONE)&&submit&&!stop_new)begin
      resident_active<=resident_authorized;resident_active_row<=resident_row;
    end
  end
  wire resident_extension=(d[27]&32'hfffffff0)==32'ha3510000&&
      d[27][1:0]<=d[27][3:2]&&d[17]==4864&&d[24]==0&&
      d[25]==0&&d[26]==0&&d[28]==0&&(d[29]|d[30])!=0&&
      resident_active&&resident_active_row==d[27][1:0];
  wire [15:0] resident_aq_offset=16'(resident_active_row*4864)+16'(base_index);
  wire [15:0] resident_sa_offset=16'h5000+16'(resident_active_row*304)+16'(base_index>>4);

  reg [12:0] base_index;
  reg [6:0] length,index,read_offset,write_offset;
  reg [1:0] phase;
  reg [1:0] pass;
  reg [7:0] summary_count;
  reg [31:0] norm_factor,final_sum;
  wire reduction=d[24]>=5;
  wire needs_up=d[24]==0||d[24]==2||d[24]==3||pass==3;
  wire need_quant=d[24]<2||d[25][0];
  wire [3:0] group_mode=pass==2 ? 9 : pass==3 ? 8 : pass==1 ? (d[24]==6 ? 6 : 5) : d[24][3:0];
  wire [31:0] group_factor=pass==3 ? norm_factor : d[26];
  wire [127:0] group_fp,group_q;
  wire [31:0] summary_q[0:1];
  genvar sb;
  generate for(sb=0;sb<2;sb=sb+1)begin:summaries
    wire [6:0] position=state==SUM_SAVE ? 7'(base_index>>6) : 7'(base_index+index);
    nx_opt11_bank #(.DEPTH(64)) bank(.clk,.write(state==SUM_SAVE&&position[0]==sb),
      .address(position[6:1]),.data(group_fp[31:0]),.q(summary_q[sb]));
  end endgenerate
  function automatic [31:0] as_float(input [12:0] k);
    integer e;
    reg [23:0] v;
    begin e=0;for(integer j=0;j<13;j=j+1)if(k[j])e=j;v={11'b0,k}<<(23-e);as_float={1'b0,8'(127+e),v[22:0]};end
  endfunction
  reg [31:0] cmd_address;
  reg [2:0] cmd_size;
  reg [4:0] cmd_len;
  reg [15:0] cmd_scratch,cmd_mask;
  reg [127:0] cmd_data,gate_hold;
  reg cmd_write;
  reg [9:0] chunk_bytes;
  // Validated K<=4864 bounds reads to 38912 B and writes to 24624 B.
  reg [63:0] ticks,loads,computes,writes;
  wire [63:0] ticks_next;
  reg ticks_clear,ticks_enable;
  reg deadline_ge;
  wire deadline_expired=DEADLINE_CACHE ? deadline_ge : (run_limit!=0&&ticks>=run_limit);
  // Preserve the original procedural clear/increment decisions even with X
  // control inputs; metadata uses the same value as the real counter FF.
  always @*begin
    ticks_clear=0;ticks_enable=0;
    case(state)
      IDLE,DONE:if(submit&&!stop_new)ticks_clear=1;
      default:if(!engine_idle&&state!=PUBLISH)ticks_enable=1;
    endcase
  end
  generate if(DEADLINE_CACHE)begin:cached_deadline
    nx_ce64_phase_counter64 #(.WHOLE_X_PROPAGATION(1)) counter(.clk,.reset_n(platform_reset_n),
      .clear(ticks_clear),.enable(ticks_enable),.value(ticks),.value_next(ticks_next));
    always @(posedge clk or negedge platform_reset_n)begin
      if(!platform_reset_n)deadline_ge<=0;
      else deadline_ge<=(run_limit_next!=0&&ticks_next>=run_limit_next);
    end
  end else begin:original_deadline
    assign ticks_next=ticks;
    always @(posedge clk or negedge platform_reset_n)begin
      if(!platform_reset_n)ticks<=0;
      else case(state)
        IDLE,DONE:if(submit&&!stop_new)ticks<=0;
        default:if(!engine_idle&&state!=PUBLISH)ticks<=ticks+1;
      endcase
    end
    always @*deadline_ge=1'b0;
  end endgenerate
  // SwiGLU alone may retain results across groups. The input DMA uses
  // 0xe000..0xe1ff; these output regions are disjoint and are owned by this
  // descriptor until all real write responses have drained. No extra RAM port
  // or tensor array is introduced. The dispatcher serializes PV/linear/SFU.
  // 0xf000..0xf1ff: two FP groups; 0xf200..0xf3ff: eight Aq groups;
  // 0xf400..0xf52f: all 76 Sa words. Non-SwiGLU modes keep the old path.
  wire aggregate=(CROSS_GROUP_WRITE!=0)&&(FP32_OUTPUT_BURST!=0)&&
      (FP32_OUTPUT_PACK!=0)&&(QUANT_OUTPUT_BURST!=0)&&d[24]==0;
  wire aggregate_last=32'(base_index)+64>=d[17];
  wire aggregate_fp_ready=base_index[6]||aggregate_last;
  wire aggregate_q_ready=(&base_index[8:6])||aggregate_last;
  reg [9:0] aggregate_offset;
  wire [9:0] aggregate_fp_bytes=({3'b0,base_index[6],6'b0}+{3'b0,length})<<2;
  wire [9:0] aggregate_fp_full={aggregate_fp_bytes[9:4],4'b0};
  wire [9:0] aggregate_q_bytes={1'b0,base_index[8:6],6'b0}+10'd64;
  wire [9:0] aggregate_s_bytes=10'(((d[17]+63)>>6)<<2);
  wire [9:0] aggregate_s_full={aggregate_s_bytes[9:4],4'b0};
  wire [31:0] aggregate_address=state==AG_FP_FLUSH ?
      d[19]+((32'(base_index)&32'hffffff80)<<2)+32'(aggregate_offset) :
      state==AG_Q_FLUSH ? d[22]+(32'(base_index)&32'hfffffe00)+32'(aggregate_offset) :
      d[23]+32'(aggregate_offset);
  wire [9:0] aggregate_left=state==AG_FP_FLUSH ? aggregate_fp_full-aggregate_offset :
      state==AG_Q_FLUSH ? aggregate_q_bytes-aggregate_offset : aggregate_s_full-aggregate_offset;
  wire [31:0] aggregate_page_left=32'd4096-(aggregate_address&32'hfff);
  wire [9:0] aggregate_chunk=32'(aggregate_left)>aggregate_page_left ?
      10'(aggregate_page_left) : aggregate_left;
  reg [31:0] fp_store_word;
  reg [8:0] fp_bulk_offset;
  reg [6:0] q_bulk_offset;
  wire [31:0] q_bulk_address=d[22]+32'(base_index)+32'(q_bulk_offset);
  wire [31:0] q_page_left=32'd4096-(q_bulk_address&32'hfff);
  wire [6:0] q_left=7'd64-q_bulk_offset;
  wire [6:0] q_chunk=32'(q_left)>q_page_left?7'(q_page_left):q_left;
  wire fp_bulk=(FP32_OUTPUT_BURST!=0)&&(FP32_OUTPUT_PACK!=0);
  wire [8:0] fp_bulk_bytes={length[6:2],4'b0};
  wire [31:0] fp_bulk_address=d[19]+(32'(base_index)<<2)+32'(fp_bulk_offset);
  wire [31:0] fp_page_left=32'd4096-(fp_bulk_address&32'hfff);
  wire [8:0] fp_left=fp_bulk_bytes-fp_bulk_offset;
  wire [8:0] fp_chunk=32'(fp_left)>fp_page_left?9'(fp_page_left):fp_left;
  reg [15:0] read_bytes,write_bytes;
  wire group_valid,group_idle,group_error,load_ready;
  wire [31:0] group_scale;
  wire [63:0] group_cycles;
  wire group_ack=group_valid&&(state==NEXT_GROUP||state==REDUCE_NEXT||state==NEXT_PASS||state==DRAIN);
  wire [6:0] peek_index=state==WRITE_FP||state==FP_PEEK||state==FP_TAIL_PEEK||state==FP_TAIL_WRITE ? write_offset : state==WRITE_Q ? write_offset : 0;
  nx_opt11_group #(.LANES(LANES),.EXTERNAL_FP(EXTERNAL_FP)) group_core(.shared_start,.shared_multiply,.shared_a,.shared_b,.shared_ready,.shared_valid,.shared_result,.clk,.reset_n(platform_reset_n&&state!=DRAIN),
    .start(state==G_START&&!stop_new&&!timeout_fault&&!abort_publish&&!certificate_fault),.ack(group_ack),.length,.mode(group_mode),.pad_full(pass==0&&d[17]>64||pass==1&&summary_count>64),.quantize_result(need_quant&&!reduction||pass==3&&need_quant),.scalar(group_factor),
    .load_valid(state==LOAD),.load_ready,.gate_data(gate_hold),
    .up_data(pass==2 ? {96'b0,as_float(d[17][12:0])} : pass==1 ? 128'b0 : ram_q>>(32*(index%4))),.valid(group_valid),.idle(group_idle),.error(group_error),
    .peek(peek_index[5:0]),.fp_data(group_fp),.q_data(group_q),.scale(group_scale),.cycles(group_cycles));
  assign engine_idle=state==IDLE||state==DONE;
  assign arithmetic_idle=group_idle||group_valid;
  assign scratch_idle=state!=GET_G&&state!=GET_G_WAIT&&state!=GET_U&&state!=GET_U_WAIT&&state!=LOAD&&state!=FP_STORE&&state!=Q_STORE&&state!=S_STORE&&state!=AG_S_GET&&state!=AG_S_WAIT;
  assign timeout_fault=!engine_idle&&state!=DRAIN&&state!=PUBLISH&&deadline_expired;
  // Numeric/rejected descriptors are recoverable completion errors, not bus quarantine.
  assign call_fault=0;
  assign completion_valid=state==PUBLISH;
  assign perf={64'b0,writes,computes,loads,ticks,48'b0,write_bytes,48'b0,read_bytes,32'b0,32'd1};
  assign dma_valid=state==DMA_REQ&&!stop_new&&!timeout_fault&&!certificate_fault;
  assign dma_result_ready=1;
  assign dma_write=cmd_write;assign dma_address=cmd_address;assign dma_size=cmd_size;
  assign dma_len=cmd_len;assign dma_scratch=cmd_scratch;assign dma_data=cmd_data;assign dma_mask=cmd_mask;
  assign ram_en=state==GET_G||state==GET_U||state==FP_STORE||state==Q_STORE||state==S_STORE||state==AG_S_GET;
  assign ram_address=state==AG_S_GET ? 12'hf40+12'(aggregate_offset>>4) :
      state==S_STORE ? (resident_active ? resident_sa_offset[15:4] : 12'hf40+12'(base_index>>8)) :
      state==Q_STORE ? (resident_active ? resident_aq_offset[15:4] : aggregate ? 12'hf20+{7'b0,base_index[8:6],2'b0} : 12'hf10)+12'(write_offset>>4) :
      state==FP_STORE ? (aggregate ? 12'hf00+{7'b0,base_index[6],4'b0} : 12'hf00)+12'(write_offset>>2) :
      (state==GET_U ? 12'he10 : 12'he00)+(index>>2);
  assign ram_mask=state==S_STORE ? 16'h000f<<(base_index[7:6]*4) : state==Q_STORE ? 16'hffff : state==FP_STORE ? 16'h000f<<(write_offset[1:0]*4) : 16'b0;
  assign ram_data=state==S_STORE ? {96'b0,group_scale}<<(base_index[7:6]*32) : state==Q_STORE ? cmd_data : state==FP_STORE ? {96'b0,fp_store_word}<<(write_offset[1:0]*32) : 128'b0;
  function automatic region(input [31:0] a,input [31:0] bytes,input [32:0] e);
    begin region=bytes!=0&&e>{1'b0,a}&&e<=33'h100000000&&
      ((a>=32'hac000000&&e<=33'h0b4000000)||(a>=32'hba000000&&e<=33'h0bc000000));end
  endfunction
  // Separate short registered predicates from the state/priority mux. Every
  // original header/shape/mode/reserved check must pass before range checking;
  // no DMA or group start is allowed in either validation cycle.
  reg [7:0] legal_parts;
  reg [2:0] check_index,compare_index;
  reg [31:0] addresses[0:4],sizes[0:4];
  // d is captured before VALIDATE and is unchanged throughout RANGE/OVERLAP.
  // Sample the full-width endpoint arithmetic during those existing prepare
  // cycles; mode-dependent byte counts no longer precede an address carry in
  // the range and overlap decision. No descriptor check or state is skipped.
  reg [32:0] region_end[0:4];
  always @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)begin
      for(integer j=0;j<5;j=j+1)region_end[j]<=0;
    end else begin
      for(integer j=0;j<5;j=j+1)region_end[j]<={1'b0,addresses[j]}+sizes[j];
    end
  end
  integer count,remaining,alignment;
  always @* begin
    addresses[0]=d[18];addresses[1]=d[20];addresses[2]=d[22];addresses[3]=d[23];addresses[4]=d[19];
    sizes[0]=d[17]<<2;sizes[1]=(d[24]==0||d[24]==2||d[24]==3||d[24]==7) ? d[17]<<2 : 0;sizes[2]=need_quant ? ((d[17]+63)>>6)<<6 : 0;
    sizes[3]=need_quant ? ((d[17]+63)>>6)<<2 : 0;sizes[4]=(d[24]==5||d[24]==6) ? 4 : d[17]<<2;
    remaining=integer'(length)-integer'(read_offset);
    count=remaining>32 ? 32 : remaining;
    alignment=(4096-integer'((state==READ_G ? d[18]+((32'(base_index)+read_offset)<<2) : d[20]+((32'(base_index)+read_offset)<<2))&32'hfff))>>2;
    if(count>alignment)count=alignment;
  end
  function automatic [221:0] memory_read_update(input [31:0] a,input [15:0] local_a,input [4:0] len,input [5:0] next_state);
    memory_read_update={32'(a),3'(2),5'(len),16'(local_a),16'(0),128'(0),1'(0),9'((9'(len)+1)<<2),6'(next_state),6'(DMA_REQ)};
  endfunction
  function automatic [221:0] memory_write_update(input [31:0] a,input [2:0] size,input [127:0] data,input [5:0] next_state);
    memory_write_update={32'(a),3'(size),5'(0),16'(0),1'(1),128'(data<<(8*a[3:0])),16'(((16'd1<<(1<<size))-1)<<a[3:0]),9'(9'd1<<size),6'(next_state),6'(DMA_REQ)};
  endfunction
  // Read-only tuple aliases keep one function evaluation and scalar NBA destinations.
  wire [221:0] tuple_sfu_call_000=memory_read_update(d[18]+((32'(base_index)+read_offset)<<2),16'he000+{7'b0,read_offset,2'b0},5'(count-1),READ_G);
  wire [221:0] tuple_sfu_call_001=memory_read_update(d[20]+((32'(base_index)+read_offset)<<2),16'he100+{7'b0,read_offset,2'b0},5'(count-1),READ_U);
  wire [221:0] tuple_sfu_call_003=memory_write_update(d[23]+(base_index>>4),2,{96'b0,group_scale},FP_PEEK);
  wire [221:0] tuple_sfu_call_004=memory_write_update(d[19]+((32'(base_index)+write_offset-3)<<2),4,{group_fp[31:0],cmd_data[95:0]},FP_PEEK);
  wire [221:0] tuple_sfu_call_005=memory_write_update(d[19]+((32'(base_index)+write_offset)<<2),2,{96'b0,group_fp[31:0]},FP_PEEK);
  wire [221:0] tuple_sfu_call_006=memory_write_update(d[19]+((32'(base_index)+write_offset)<<2),2,{96'b0,group_fp[31:0]},FP_TAIL_PEEK);
  wire [221:0] tuple_sfu_call_007=memory_write_update(d[19],2,{96'b0,final_sum},DRAIN);

  always @* begin
    completion={32'(generation),32'(generation),32'd0,32'd0,32'd0,32'(status),64'(ticks-loads-computes-writes),64'(writes),64'(computes),64'(loads),64'(ticks),64'(write_bytes),64'(read_bytes),32'd0,32'd0,32'(1),32'(1),32'(status==0),32'(status),32'(d[13]),32'(d[12]),32'(d[11]),32'(d[10]),32'(104),32'(32'h4c4e3135),32'(native_quarantined ? 1 : 0),32'(first_fault_address),32'd0,32'(2),32'(epoch),32'(160),32'(1),32'(32'h52364543)};
  end
  always @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)begin
      pass<=0;summary_count<=0;norm_factor<=0;final_sum<=0;state<=IDLE;ret<=IDLE;status<=0;check_index<=0;compare_index<=0;base_index<=0;length<=0;index<=0;read_offset<=0;write_offset<=0;phase<=0;
      cmd_address<=0;cmd_size<=0;cmd_len<=0;cmd_scratch<=0;cmd_mask<=0;cmd_data<=0;cmd_write<=0;gate_hold<=0;chunk_bytes<=0;
      fp_store_word<=0;fp_bulk_offset<=0;q_bulk_offset<=0;aggregate_offset<=0;
      legal_parts<=0;
      loads<=0;computes<=0;writes<=0;read_bytes<=0;write_bytes<=0;
      for(integer i=0;i<32;i=i+1)d[i]<=0;
    end else begin
      // Source-derived last-NBA priority inside the original normal FF branch.
      if(reset_grant)begin
        status<=0;
      end else begin
        if((stop_new||timeout_fault||certificate_fault)&&!engine_idle&&state!=DRAIN&&state!=PUBLISH)begin
          status<=certificate_fault ? -9 : timeout_fault ? -7 : -11;
        end else begin
          case(state)
            IDLE,DONE:begin
              if(submit&&!stop_new)begin
                status<=0;
              end
            end
            VALIDATE_RESULT:begin
              if(!(&legal_parts))begin
                status<=-4;
              end
            end
            RANGE:begin
              case(check_index==5)
                1'b1:;
                default:begin
                  if(sizes[check_index]==0||check_index==4&&addresses[4]==0)begin
                    if(sizes[check_index]==0&&addresses[check_index]!=0)begin
                      status<=-4;
                    end
                  end else begin
                    if(addresses[check_index][3:0]!=0)begin
                      status<=-4;
                    end else begin
                      case(region(addresses[check_index],sizes[check_index],region_end[check_index]))
                        1'b1:;
                        default:begin
                          case((SEALED_NORM_READ!=0)&&check_index==1&&d[24]==7&&d[17]==896&&d[25]==0&&d[26]==0&&sizes[1]==3584)
                            1'b1:;
                            default:begin
                              status<=-4;
                            end
                          endcase
                        end
                      endcase
                    end
                  end
                end
              endcase
            end
            NORM_COMPARE:begin
              case(addresses[1]==norm_catalog_base)
                1'b1:;
                default:begin
                  if(norm_check_index==48)begin
                    status<=-4;
                  end
                end
              endcase
            end
            OVERLAP:begin
              case(compare_index==check_index)
                1'b1:;
                default:begin
                  if(sizes[compare_index]!=0&&addresses[compare_index]!=0&&
                  !(check_index==4&&(compare_index==0||compare_index==1)&&d[24]>=2&&d[24]!=5&&d[24]!=6&&addresses[4]==addresses[compare_index])&&
                  {1'b0,addresses[check_index]}<region_end[compare_index]&&
                  {1'b0,addresses[compare_index]}<region_end[check_index])begin
                    status<=-4;
                  end
                end
              endcase
            end
            G_WAIT:begin
              if(group_valid)begin
                if(group_error)begin
                  status<=-9;
                end
              end
            end
            DMA_WAIT:begin
              if(dma_result_valid)begin
                if(dma_resp!=0)begin
                  status<=-11;
                end
              end
            end
            default:begin
              ;
            end
          endcase
        end
      end
      if(reset_grant)begin
        phase<=0;
      end else begin
        if((stop_new||timeout_fault||certificate_fault)&&!engine_idle&&state!=DRAIN&&state!=PUBLISH)begin
          phase<=0;
        end else begin
          case(state)
            IDLE,DONE:begin
              if(submit&&!stop_new)begin
                phase<=0;
              end
            end
            RANGE:begin
              if(check_index==5)begin
                phase<=1;
              end
            end
            READ_G:begin
              if(read_offset>=length)begin
                phase<=needs_up ? 1 : 2;
              end
            end
            READ_U:begin
              if(read_offset>=length)begin
                phase<=2;
              end
            end
            G_WAIT:begin
              if(group_valid)begin
                if(group_error)begin
                  phase<=0;
                end else begin
                  phase<=reduction&&pass<3 ? 2 : 3;
                end
              end
            end
            REDUCE_NEXT:begin
              case(base_index+64>=(pass==0 ? d[17] : summary_count))
                1'b1:;
                default:begin
                  phase<=pass==0 ? 1 : 2;
                end
              endcase
            end
            NEXT_PASS:begin
              if(pass==2)begin
                phase<=1;
              end else begin
                if(summary_count==1)begin
                  case(d[24]==7)
                    1'b1:;
                    default:begin
                      phase<=3;
                    end
                  endcase
                end
              end
            end
            NEXT_GROUP:begin
              if(base_index+64>=d[17])begin
                phase<=0;
              end else begin
                phase<=1;
              end
            end
            DMA_WAIT:begin
              if(dma_result_valid)begin
                if(dma_resp!=0)begin
                  phase<=0;
                end
              end
            end
            default:begin
              ;
            end
          endcase
        end
      end

      case(state)
        IDLE,DONE:if(submit&&!stop_new)begin loads<=0;computes<=0;writes<=0;end
        default:if(!engine_idle&&state!=PUBLISH)begin
          case(phase)1:loads<=loads+1;2:computes<=computes+1;3:writes<=writes+1;default:;endcase
        end
      endcase
      if((stop_new||timeout_fault||certificate_fault)&&!engine_idle&&state!=DRAIN&&state!=PUBLISH)begin
        ;state<=DRAIN;;
      end else case(state)
        IDLE,DONE:if(submit&&!stop_new)begin
          for(integer i=0;i<32;i=i+1)d[i]<=descriptor[32*i+:32];
          ;base_index<=0;read_offset<=0;read_bytes<=0;write_bytes<=0;
          fp_bulk_offset<=0;q_bulk_offset<=0;aggregate_offset<=0;
          pass<=0;summary_count<=8'((descriptor[17*32+:32]+63)>>6);norm_factor<=0;;state<=VALIDATE;
        end
        VALIDATE:begin
          legal_parts[0]<=d[0]==32'h34364543&&d[1]==1&&d[2]==128&&d[3]==0;
          legal_parts[1]<=d[4]==epoch&&d[5]==1&&d[6]==0&&d[7]==0;
          legal_parts[2]<=d[8]==32'h4c4e3135&&d[9]==96&&(d[10]|d[11])!=0&&(d[12]|d[13])!=0;
          legal_parts[3]<=d[14]==3&&d[15]==1&&d[16]==1&&d[17]!=0&&d[17]<=4864;
          legal_parts[4]<=d[24]<=7&&d[25]<=1;
          legal_parts[5]<=(d[24]==4 ? d[26][30:23]!=255 : d[26]==0)&&(!(d[24]==5||d[24]==6)||d[25]==0);
          legal_parts[6]<=d[19]!=0||need_quant;
          legal_parts[7]<=d[21]==0&&((d[27]|d[28]|d[29]|d[30]|d[31])==0||resident_extension);
          state<=VALIDATE_RESULT;
        end
        VALIDATE_RESULT:if(!(&legal_parts))begin ;state<=DRAIN;end else begin
          length<=d[17]>64 ? 64 : d[17][6:0];check_index<=0;compare_index<=0;state<=RANGE;
        end
        RANGE:if(check_index==5)begin ;state<=READ_G;end
          else if(sizes[check_index]==0||check_index==4&&addresses[4]==0)begin
            if(sizes[check_index]==0&&addresses[check_index]!=0)begin ;state<=DRAIN;end
            else check_index<=check_index+1;end
          else if(addresses[check_index][3:0]!=0)begin ;state<=DRAIN;end
          else if(region(addresses[check_index],sizes[check_index],region_end[check_index]))begin compare_index<=0;state<=OVERLAP;end
          else if((SEALED_NORM_READ!=0)&&check_index==1&&d[24]==7&&d[17]==896&&d[25]==0&&d[26]==0&&sizes[1]==3584)begin
            state<=NORM_LOOKUP;
          end else begin ;state<=DRAIN;end
        NORM_LOOKUP:begin state<=NORM_COMPARE;end
        NORM_COMPARE:if(addresses[1]==norm_catalog_base)begin compare_index<=0;state<=OVERLAP;end
          else if(norm_check_index==48)begin ;state<=DRAIN;end
          else begin state<=NORM_LOOKUP;end
        OVERLAP:if(compare_index==check_index)begin check_index<=check_index+1;state<=RANGE;end
          else if(sizes[compare_index]!=0&&addresses[compare_index]!=0&&
                  !(check_index==4&&(compare_index==0||compare_index==1)&&d[24]>=2&&d[24]!=5&&d[24]!=6&&addresses[4]==addresses[compare_index])&&
                  {1'b0,addresses[check_index]}<region_end[compare_index]&&
                  {1'b0,addresses[compare_index]}<region_end[check_index])begin ;state<=DRAIN;end
          else compare_index<=compare_index+1;
        READ_G:if(read_offset>=length)begin read_offset<=0;state<=needs_up ? READ_U : G_START;;index<=0;end else begin
          begin
            cmd_address<=tuple_sfu_call_000[221:190];
            cmd_size<=tuple_sfu_call_000[189:187];
            cmd_len<=tuple_sfu_call_000[186:182];
            cmd_scratch<=tuple_sfu_call_000[181:166];
            cmd_mask<=tuple_sfu_call_000[165:150];
            cmd_data<=tuple_sfu_call_000[149:22];
            cmd_write<=tuple_sfu_call_000[21:21];
            chunk_bytes<=tuple_sfu_call_000[20:12];
            ret<=tuple_sfu_call_000[11:6];
            state<=tuple_sfu_call_000[5:0];
          end
read_offset<=read_offset+7'(count);
        end
        READ_U:if(read_offset>=length)begin index<=0;;state<=G_START;end else begin
          begin
            cmd_address<=tuple_sfu_call_001[221:190];
            cmd_size<=tuple_sfu_call_001[189:187];
            cmd_len<=tuple_sfu_call_001[186:182];
            cmd_scratch<=tuple_sfu_call_001[181:166];
            cmd_mask<=tuple_sfu_call_001[165:150];
            cmd_data<=tuple_sfu_call_001[149:22];
            cmd_write<=tuple_sfu_call_001[21:21];
            chunk_bytes<=tuple_sfu_call_001[20:12];
            ret<=tuple_sfu_call_001[11:6];
            state<=tuple_sfu_call_001[5:0];
          end
read_offset<=read_offset+7'(count);
        end
        G_START:begin index<=0;state<=pass==1 ? SUM_GET : pass==2 ? LOAD : GET_G;
          if(pass==2)gate_hold<={96'b0,final_sum};end
        GET_G:state<=GET_G_WAIT;
        GET_G_WAIT:begin gate_hold<=ram_q>>(32*(index%4));state<=needs_up ? GET_U : LOAD;end
        GET_U:state<=GET_U_WAIT;
        GET_U_WAIT:state<=LOAD;
        LOAD:if(index+LANES>=64)state<=G_WAIT;else begin index<=index+LANES;state<=pass==1 ? SUM_GET : pass==2 ? LOAD : GET_G;end
        SUM_GET:state<=SUM_WAIT;
        SUM_WAIT:begin gate_hold<={64'b0,summary_q[1],summary_q[0]};state<=LOAD;end
        G_WAIT:if(group_valid)begin
          if(group_error)begin ;;state<=DRAIN;end
          else begin write_offset<=0;state<=reduction&&pass<2 ? SUM_SAVE : pass==2 ? NEXT_PASS : need_quant ? WRITE_Q : FP_PEEK;;end
        end
        WRITE_Q:if(write_offset==64)begin
          write_offset<=0;
          if(resident_active||aggregate)state<=WRITE_S;
          else if(QUANT_OUTPUT_BURST)begin q_bulk_offset<=0;state<=Q_FLUSH;end else state<=WRITE_S;
        end else if(resident_active||QUANT_OUTPUT_BURST)begin cmd_data<=group_q;state<=Q_STORE;end
          else begin
            begin
            cmd_address<=32'(memory_write_update(d[22]+base_index+write_offset,4,group_q,WRITE_Q) >> 190);
            cmd_size<=3'(memory_write_update(d[22]+base_index+write_offset,4,group_q,WRITE_Q) >> 187);
            cmd_len<=5'(memory_write_update(d[22]+base_index+write_offset,4,group_q,WRITE_Q) >> 182);
            cmd_scratch<=16'(memory_write_update(d[22]+base_index+write_offset,4,group_q,WRITE_Q) >> 166);
            cmd_write<=1'(memory_write_update(d[22]+base_index+write_offset,4,group_q,WRITE_Q) >> 165);
            cmd_data<=128'(memory_write_update(d[22]+base_index+write_offset,4,group_q,WRITE_Q) >> 37);
            cmd_mask<=16'(memory_write_update(d[22]+base_index+write_offset,4,group_q,WRITE_Q) >> 21);
            chunk_bytes<=9'(memory_write_update(d[22]+base_index+write_offset,4,group_q,WRITE_Q) >> 12);
            ret<=6'(memory_write_update(d[22]+base_index+write_offset,4,group_q,WRITE_Q) >> 6);
            state<=6'(memory_write_update(d[22]+base_index+write_offset,4,group_q,WRITE_Q) >> 0);
          end
write_offset<=write_offset+16;
          end
        Q_STORE:begin write_offset<=write_offset+16;state<=WRITE_Q;end
        Q_FLUSH:if(q_bulk_offset==64)state<=WRITE_S;
          else begin
            cmd_address<=q_bulk_address;cmd_size<=4;cmd_len<=5'((q_chunk>>4)-1);
            cmd_scratch<=16'hf100+16'(q_bulk_offset);cmd_mask<=16'hffff;cmd_data<=0;cmd_write<=1;
            chunk_bytes<=9'(q_chunk);ret<=Q_FLUSH;state<=DMA_REQ;q_bulk_offset<=q_bulk_offset+q_chunk;
          end
        WRITE_S:if(resident_active||aggregate)state<=S_STORE;else begin begin
            cmd_address<=tuple_sfu_call_003[221:190];
            cmd_size<=tuple_sfu_call_003[189:187];
            cmd_len<=tuple_sfu_call_003[186:182];
            cmd_scratch<=tuple_sfu_call_003[181:166];
            cmd_write<=tuple_sfu_call_003[165:165];
            cmd_data<=tuple_sfu_call_003[164:37];
            cmd_mask<=tuple_sfu_call_003[36:21];
            chunk_bytes<=tuple_sfu_call_003[20:12];
            ret<=tuple_sfu_call_003[11:6];
            state<=tuple_sfu_call_003[5:0];
          end
write_offset<=0;end
        S_STORE:begin write_offset<=0;state<=FP_PEEK;end
        FP_PEEK:state<=WRITE_FP;
        WRITE_FP:if(d[19]==0)begin
          if(aggregate)begin aggregate_offset<=0;state<=AG_Q_FLUSH;end else state<=NEXT_GROUP;
        end
          else if(write_offset>=length)begin
            if(aggregate)begin aggregate_offset<=0;state<=AG_FP_FLUSH;end
            else if(fp_bulk)begin fp_bulk_offset<=0;state<=FP_FLUSH;end
            else state<=NEXT_GROUP;
          end
          else if(fp_bulk)begin fp_store_word<=group_fp[31:0];state<=FP_STORE;end
          else if((FP32_OUTPUT_PACK!=0) && write_offset<{length[6:2],2'b0})begin
            write_offset<=write_offset+1;
            if(write_offset[1:0]==3)
              begin
            cmd_address<=tuple_sfu_call_004[221:190];
            cmd_size<=tuple_sfu_call_004[189:187];
            cmd_len<=tuple_sfu_call_004[186:182];
            cmd_scratch<=tuple_sfu_call_004[181:166];
            cmd_write<=tuple_sfu_call_004[165:165];
            cmd_data<=tuple_sfu_call_004[164:37];
            cmd_mask<=tuple_sfu_call_004[36:21];
            chunk_bytes<=tuple_sfu_call_004[20:12];
            ret<=tuple_sfu_call_004[11:6];
            state<=tuple_sfu_call_004[5:0];
          end

            else begin
              cmd_data[write_offset[1:0]*32+:32]<=group_fp[31:0];state<=FP_PEEK;
            end
          end else begin
            // A short group tail never writes bytes outside the declared view.
            begin
            cmd_address<=tuple_sfu_call_005[221:190];
            cmd_size<=tuple_sfu_call_005[189:187];
            cmd_len<=tuple_sfu_call_005[186:182];
            cmd_scratch<=tuple_sfu_call_005[181:166];
            cmd_write<=tuple_sfu_call_005[165:165];
            cmd_data<=tuple_sfu_call_005[164:37];
            cmd_mask<=tuple_sfu_call_005[36:21];
            chunk_bytes<=tuple_sfu_call_005[20:12];
            ret<=tuple_sfu_call_005[11:6];
            state<=tuple_sfu_call_005[5:0];
          end
write_offset<=write_offset+1;
          end
        // One physical scratch port. Complete this group's buffer before
        // offering any write; DMA then prefetches the entire accepted quantum.
        FP_STORE:begin write_offset<=write_offset+1'b1;state<=FP_PEEK;end
        FP_FLUSH:if(fp_bulk_offset==fp_bulk_bytes)begin
          write_offset<={length[6:2],2'b0};state<=FP_TAIL_PEEK;
        end else begin
          cmd_address<=fp_bulk_address;cmd_size<=4;cmd_len<=5'((fp_chunk>>4)-1);
          cmd_scratch<=16'hf000+16'(fp_bulk_offset);cmd_mask<=16'hffff;cmd_data<=0;cmd_write<=1;
          chunk_bytes<=fp_chunk;ret<=FP_FLUSH;state<=DMA_REQ;fp_bulk_offset<=fp_bulk_offset+fp_chunk;
        end
        FP_TAIL_PEEK:state<=FP_TAIL_WRITE;
        FP_TAIL_WRITE:if(write_offset>=length)begin
          if(aggregate)begin aggregate_offset<=0;state<=AG_Q_FLUSH;end else state<=NEXT_GROUP;
        end
          else begin
            begin
            cmd_address<=tuple_sfu_call_006[221:190];
            cmd_size<=tuple_sfu_call_006[189:187];
            cmd_len<=tuple_sfu_call_006[186:182];
            cmd_scratch<=tuple_sfu_call_006[181:166];
            cmd_write<=tuple_sfu_call_006[165:165];
            cmd_data<=tuple_sfu_call_006[164:37];
            cmd_mask<=tuple_sfu_call_006[36:21];
            chunk_bytes<=tuple_sfu_call_006[20:12];
            ret<=tuple_sfu_call_006[11:6];
            state<=tuple_sfu_call_006[5:0];
          end

            write_offset<=write_offset+1'b1;
          end
        // Every accepted chunk is still a normal DMA transaction. Only the
        // number of transactions changes; DMA/native response completion,
        // timeout/stop priority and publication are deliberately unchanged.
        AG_FP_FLUSH:if(!aggregate_fp_ready)begin
          aggregate_offset<=0;state<=AG_Q_FLUSH;
        end else if(aggregate_offset==aggregate_fp_full)begin
          write_offset<={length[6:2],2'b0};state<=FP_TAIL_PEEK;
        end else begin
          cmd_address<=aggregate_address;cmd_size<=4;cmd_len<=5'((aggregate_chunk>>4)-1);
          cmd_scratch<=16'hf000+16'(aggregate_offset);cmd_mask<=16'hffff;cmd_data<=0;cmd_write<=1;
          chunk_bytes<=aggregate_chunk;ret<=AG_FP_FLUSH;state<=DMA_REQ;
          aggregate_offset<=aggregate_offset+aggregate_chunk;
        end
        AG_Q_FLUSH:if(resident_active)begin aggregate_offset<=0;state<=NEXT_GROUP;end
        else if(!aggregate_q_ready||aggregate_offset==aggregate_q_bytes)begin
          aggregate_offset<=0;state<=AG_S_FLUSH;
        end else begin
          cmd_address<=aggregate_address;cmd_size<=4;cmd_len<=5'((aggregate_chunk>>4)-1);
          cmd_scratch<=16'hf200+16'(aggregate_offset);cmd_mask<=16'hffff;cmd_data<=0;cmd_write<=1;
          chunk_bytes<=aggregate_chunk;ret<=AG_Q_FLUSH;state<=DMA_REQ;
          aggregate_offset<=aggregate_offset+aggregate_chunk;
        end
        AG_S_FLUSH:if(!aggregate_last||aggregate_offset==aggregate_s_bytes)state<=NEXT_GROUP;
          else if(aggregate_offset>=aggregate_s_full)state<=AG_S_GET;
          else begin
            cmd_address<=aggregate_address;cmd_size<=4;cmd_len<=5'((aggregate_chunk>>4)-1);
            cmd_scratch<=16'hf400+16'(aggregate_offset);cmd_mask<=16'hffff;cmd_data<=0;cmd_write<=1;
            chunk_bytes<=aggregate_chunk;ret<=AG_S_FLUSH;state<=DMA_REQ;
            aggregate_offset<=aggregate_offset+aggregate_chunk;
          end
        // Sa has at most three residual words. Read those from the same
        // synchronous scratch before issuing exact four-byte writes; untouched
        // padding is never copied into the declared DDR view.
        AG_S_GET:state<=AG_S_WAIT;
        AG_S_WAIT:begin fp_store_word<=ram_q>>(aggregate_offset[3:2]*32);state<=AG_S_WRITE;end
        AG_S_WRITE:begin
          cmd_address<=d[23]+32'(aggregate_offset);cmd_size<=2;cmd_len<=0;cmd_scratch<=0;
          cmd_data<={96'b0,fp_store_word}<<(aggregate_address[3:0]*8);
          cmd_mask<=16'h000f<<aggregate_address[3:0];cmd_write<=1;chunk_bytes<=4;
          aggregate_offset<=aggregate_offset+4;ret<=AG_S_FLUSH;state<=DMA_REQ;
        end
        SUM_SAVE:state<=REDUCE_NEXT;
        REDUCE_NEXT:begin final_sum<=group_fp[31:0];if(base_index+64>=(pass==0 ? d[17] : summary_count))begin
          summary_count<=pass==0 ? 8'((d[17]+63)>>6) : (summary_count+63)>>6;
          base_index<=0;index<=0;state<=NEXT_PASS;
        end else begin base_index<=base_index+64;
          length<=pass==0 ? (d[17]-base_index-64>64 ? 64 : 7'(d[17]-base_index-64)) :
            (32'(summary_count)-base_index-64>64 ? 64 : 7'(32'(summary_count)-base_index-64));
          read_offset<=0;state<=pass==0 ? READ_G : G_START;;end end
        NEXT_PASS:if(pass==2)begin norm_factor<=group_fp[31:0];pass<=3;length<=d[17]>64 ? 64 : d[17][6:0];
          base_index<=0;read_offset<=0;;state<=READ_G;end
          else if(summary_count==1)begin
            if(d[24]==7)begin pass<=2;length<=1;state<=G_START;end
            else begin ;state<=SCALAR_WRITE;end
          end else begin pass<=1;length<=summary_count>64 ? 64 : summary_count[6:0];state<=G_START;end
        SCALAR_WRITE:begin
            cmd_address<=tuple_sfu_call_007[221:190];
            cmd_size<=tuple_sfu_call_007[189:187];
            cmd_len<=tuple_sfu_call_007[186:182];
            cmd_scratch<=tuple_sfu_call_007[181:166];
            cmd_write<=tuple_sfu_call_007[165:165];
            cmd_data<=tuple_sfu_call_007[164:37];
            cmd_mask<=tuple_sfu_call_007[36:21];
            chunk_bytes<=tuple_sfu_call_007[20:12];
            ret<=tuple_sfu_call_007[11:6];
            state<=tuple_sfu_call_007[5:0];
          end

        NEXT_GROUP:if(base_index+64>=d[17])begin ;state<=DRAIN;end
          else begin base_index<=base_index+64;length<=d[17]-base_index-64>64 ? 64 : 7'(d[17]-base_index-64);read_offset<=0;;state<=READ_G;end
        DMA_REQ:if(dma_ready)state<=DMA_WAIT;
        DMA_WAIT:if(dma_result_valid)begin
          if(dma_resp!=0)begin ;state<=DRAIN;;end
          else begin
            if(cmd_write)write_bytes<=write_bytes+chunk_bytes;else read_bytes<=read_bytes+chunk_bytes;
            state<=ret;
          end
        end
        DRAIN:if(group_idle&&transport_drained&&dma_idle&&!abort_publish)state<=PUBLISH;
        PUBLISH:if(completion_ready)state<=DONE;
        default:state<=DRAIN;
      endcase
      if(reset_grant)begin state<=IDLE;;;end
    end
  end
  // Lookup-register reset priority is local; other FSM registers retain
  // their original same-edge case/tick updates, including reset_grant edges.
  wire norm_range_lookup=state==RANGE&&check_index!=5&&
    !(sizes[check_index]==0||check_index==4&&addresses[4]==0)&&
    addresses[check_index][3:0]==0&&!region(addresses[check_index],sizes[check_index],region_end[check_index])&&
    (SEALED_NORM_READ!=0)&&check_index==1&&d[24]==7&&d[17]==896&&d[25]==0&&d[26]==0&&sizes[1]==3584;
  always @(posedge clk or negedge platform_reset_n)begin
    if(!platform_reset_n)begin norm_check_index<=0;norm_catalog_base<=0;end
    else if(reset_grant)begin norm_check_index<=0;norm_catalog_base<=0;end
    else if(!((stop_new||timeout_fault||certificate_fault)&&!engine_idle&&state!=DRAIN&&state!=PUBLISH))begin
      if(norm_range_lookup)norm_check_index<=0;
      else if(state==NORM_COMPARE&&addresses[1]!=norm_catalog_base&&norm_check_index!=48)
        norm_check_index<=norm_check_index+1'b1;
      if(state==NORM_LOOKUP)norm_catalog_base<=norm_catalog_address(norm_check_index);
    end
  end
endmodule
