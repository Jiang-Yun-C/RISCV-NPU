// Validate the immutable snapshot, in frozen private-validation order.
// A single iterative 64x32 shift/add datapath computes every byte span.
module nx_ce64_desc (
  input logic clk, reset_n, start,
  input logic [1023:0] descriptor,
  input logic [31:0] expected_epoch,
  output logic done, busy,
  output logic signed [31:0] status,
  output logic [31:0] diagnostic,
  output logic [31:0] groups, padded_k,
  output logic [6:0][63:0] spans
);
  import nx_accel_map::*;
  typedef enum logic [3:0] {IDLE, HEADER, BODY, IDENTITY, OPCODE, SHAPE,
      LIMITS, COPY, STRIDE, PRODUCT, RANGE, ALIGN, FINISH, RANGE_PRE} state_t;
  state_t state;
  logic [31:0] d [0:31];
  logic [3:0] product_index;
  logic [5:0] bit_index;
  logic [63:0] mx, ma;
  logic [31:0] my;
  logic [63:0] product;
  logic [2:0] range_index;
  logic [31:0] input_base;
  logic [63:0] input_span;
  function automatic logic region(input logic [31:0] a,
                                  input logic [63:0] bytes,input logic wr);
    logic [63:0] e;
    logic [32:0] e_low;
    begin
      e={32'b0,a}+bytes;
      e_low={1'b0,a}+{1'b0,bytes[31:0]};
      // Every permitted region ends below 2^32. A non-wrapping accepted
      // span therefore has a zero high limb and no low-limb carry. This
      // removes the 64-bit carry chain without narrowing the checker.
      case({^a,^bytes})
        2'b00,2'b01,2'b10,2'b11:region=bytes[63:32]==0&&bytes[31:0]!=0&&!e_low[32]&&
          ((!wr&&a>=32'h80000000&&e_low[31:0]<=32'ha8000000)||
           (a>=32'ha8000000&&e_low[31:0]<=32'hac000000)||
           (a>=32'hac000000&&e_low[31:0]<=32'hb4000000)||
           (a>=32'hba000000&&e_low[31:0]<=32'hbc000000));
        // Preserve the original four-state arithmetic for unknown inputs.
        default:region=bytes!=0&&e>{32'b0,a}&&e<=64'h100000000&&
          ((!wr&&a>=32'h80000000&&e<=64'ha8000000)||
           (a>=32'ha8000000&&e<=64'hac000000)||
           (a>=32'hac000000&&e<=64'hb4000000)||
           (a>=32'hba000000&&e<=64'hbc000000));
      endcase
    end
  endfunction
  function automatic logic overlap(input logic [31:0] a,b,
                                    input logic [63:0] an,bn);
    logic [32:0] ae_low,be_low;
    logic ae_high_zero,be_high_zero;
    begin
      ae_low={1'b0,a}+{1'b0,an[31:0]};
      be_low={1'b0,b}+{1'b0,bn[31:0]};
      // Exact modulo-2^64 addition: adding the low-limb carry can make the
      // high limb zero only for high=0/carry=0 or high=all-ones/carry=1.
      ae_high_zero=(an[63:32]==0&&!ae_low[32])||((&an[63:32])&&ae_low[32]);
      be_high_zero=(bn[63:32]==0&&!be_low[32])||((&bn[63:32])&&be_low[32]);
      case({^a,^b,^an,^bn})
        4'b0000,4'b0001,4'b0010,4'b0011,4'b0100,4'b0101,4'b0110,4'b0111,
        4'b1000,4'b1001,4'b1010,4'b1011,4'b1100,4'b1101,4'b1110,4'b1111:
          overlap=(!be_high_zero||a<be_low[31:0])&&(!ae_high_zero||b<ae_low[31:0]);
        default:overlap={32'b0,a}<{32'b0,b}+bn&&{32'b0,b}<{32'b0,a}+an;
      endcase
    end
  endfunction
  assign busy=state!=IDLE && state!=FINISH;
  assign product=ma+(my[0] ? mx : 64'b0);
  always_comb begin
    case(range_index)
      0:begin input_base=d[18];input_span=spans[0];end
      1:begin input_base=d[20];input_span=spans[1];end
      2:begin input_base=d[22];input_span=spans[2];end
      3:begin input_base=d[23];input_span=spans[3];end
      default:begin input_base=d[21];input_span=spans[4];end
    endcase
  end
  // Compute range predicates before selecting a range. A range-index
  // transition now selects one bit rather than feeding a payload mux and
  // a 64-bit endpoint add/compare chain in the same cycle.
  wire output_range_bad=!region(d[19],spans[5],1)||
    (d[28]!=0&&(!region(d[28],spans[6],1)||overlap(d[28],d[19],spans[6],spans[5])));
  wire [4:0] input_range_bad;
  wire [31:0] range_base[0:4];
  assign range_base[0]=d[18];assign range_base[1]=d[20];assign range_base[2]=d[22];
  assign range_base[3]=d[23];assign range_base[4]=d[21];
  generate for(genvar r=0;r<5;r++)begin:range_checks
    assign input_range_bad[r]=!region(range_base[r],spans[r],0)||
      overlap(range_base[r],d[19],spans[r],spans[5])||
      (d[28]!=0&&overlap(range_base[r],d[28],spans[r],spans[6]));
  end endgenerate
  logic output_range_bad_q;
  logic [4:0] input_range_bad_q;
  logic selected_input_range_bad;
  always_comb begin
    case(range_index)
      0:selected_input_range_bad=input_range_bad_q[0];
      1:selected_input_range_bad=input_range_bad_q[1];
      2:selected_input_range_bad=input_range_bad_q[2];
      3:selected_input_range_bad=input_range_bad_q[3];
      default:selected_input_range_bad=input_range_bad_q[4];
    endcase
  end
  // Private resident linear descriptors retain all ordinary bounds, shape,
  // alignment and numeric checks. Authorization is independent in control.
  wire resident_extension=(d[27]&32'hfffffff0)==32'ha3520000&&
    d[27][1:0]==0&&d[15]==({30'b0,d[27][3:2]}+32'd1)&&
    d[17]==4864&&d[25]==0&&d[26]==0&&d[28]==0&&
    {d[30],d[29]}!=0&&d[31][3:0]==0&&
    d[31]>=32'hac000000&&({1'b0,d[31]}+33'(d[15])*33'd19456)<=33'h0b4000000;
  wire private_copy_bad=(d[25]|d[26]|d[27]|d[29]|d[30]|d[31])!=0&&!resident_extension;
  // All spans are final at RANGE_PRE. Register the parallel endpoint and
  // overlap checks before the range selector and error/status priority.
  // The descriptor and spans cannot change until the validator returns IDLE.
  always_ff @(posedge clk or negedge reset_n)begin
    if(!reset_n)begin output_range_bad_q<=0;input_range_bad_q<=0;end
    else if(state==RANGE_PRE)begin
      output_range_bad_q<=output_range_bad;input_range_bad_q<=input_range_bad;
    end
  end
  wire range_bad=output_range_bad_q||
    ((range_index!=4||d[21]!=0)&&selected_input_range_bad);
  always_ff @(posedge clk or negedge reset_n) begin
    if(!reset_n) begin
      ;done<=0;status<=0;diagnostic<=0;groups<=0;padded_k<=0;
      spans<='0; product_index<=0;bit_index<=0;mx<=0;my<=0;ma<=0;range_index<=0;
      for(integer i=0;i<32;i=i+1)d[i]<=0;
    end else begin
      done<=0;
      case(state)
        IDLE:if(start)begin
          for(integer i=0;i<32;i=i+1)d[i]<=descriptor[i*32+:32];
          status<=0;diagnostic<=0;;
        end
        HEADER:begin
          if(d[0]!=32'h34364543 || d[1]!=1 || d[2]!=128 || d[5]!=1)begin status<=-2;;end
          else if(d[3]>1 || d[4]!=expected_epoch || d[4]==0 || d[6]!=0 || d[7]!=0 ||
                  d[3][0]!=(d[28]!=0))begin status<=-1;;end
          else ;
        end
        BODY:if(d[8]!=32'h4c4e3135 || d[9]!=96)begin status<=-2;;end else ;
        IDENTITY:if((d[10]|d[11])==0 || (d[12]|d[13])==0)begin status<=-10;;end else ;
        OPCODE:if(d[14]!=2)begin status<=-3;;end else ;
        SHAPE:if(d[15]==0 || d[16]==0 || d[17]==0)begin status<=-1;;end else ;
        LIMITS:if(d[15]>512 || d[16]>151936 || d[17]>4864)begin status<=-3;;end else begin
          groups<=(d[17]+63)>>6;padded_k<=((d[17]+63)>>6)<<6;;
        end
        COPY:if(private_copy_bad)begin status<=-1;;end else ;
        STRIDE:if(d[24]<(d[16]<<2))begin status<=-4;;end else begin
          // W, Sw, A, Sa, bias, Y, audit. Products are bounded by accepted
          // shapes; address endpoints stay 64-bit until region validation.
          product_index<=0;bit_index<=0;ma<=0;mx<={32'b0,padded_k};my<=d[16];;
        end
        PRODUCT:begin
          if(bit_index!=31)begin
            ma<=product;mx<=mx<<1;my<=my>>1;
            bit_index<=bit_index+1'b1;
          end
          else begin
            bit_index<=0;ma<=0;product_index<=product_index+1'b1;
            case(product_index)
              0:begin spans[0]<=product;mx<={32'b0,groups}<<2;my<=d[16];end
              1:begin spans[1]<=product;mx<={32'b0,padded_k};my<=d[15];end
              2:begin spans[2]<=product;mx<={32'b0,groups}<<2;my<=d[15];end
              3:begin spans[3]<=product;mx<=4;my<=d[16];end
              4:begin spans[4]<=product;mx<={32'b0,d[24]};my<=d[15]-1'b1;end
              5:begin spans[5]<=product+({32'b0,d[16]}<<2);mx<={32'b0,d[16]};my<=d[15];end
              6:begin mx<=product;my<=groups;end
              7:begin mx<=mx<<1;my<=my>>1;spans[6]<=product<<4;range_index<=0;;end
              default:begin mx<=mx<<1;my<=my>>1;status<=-4;;end
            endcase
          end
        end
        RANGE:begin
          if(range_bad)begin
            status<=-4;diagnostic<=input_base;;
          end else if(range_index==4);
          else range_index<=range_index+1'b1;
        end
        ALIGN:begin
          if(((d[18]|d[19]|d[20]|d[21]|d[22]|d[23]|d[28])&15)!=0 || d[24][1:0]!=0)status<=-5;
          ;
        end
        FINISH:begin done<=1;;end
        default:;
      endcase
    end
  end
  // Original state NBA priority; every predicate/RHS reads original old state.
  state_t state_next;
  always_comb begin
    case(state)
      IDLE:begin
        if(start)begin
          state_next=HEADER;
        end else begin
          state_next=state;
        end
      end
      HEADER:begin
        if(d[0]!=32'h34364543 || d[1]!=1 || d[2]!=128 || d[5]!=1)begin
          state_next=FINISH;
        end else begin
          if(d[3]>1 || d[4]!=expected_epoch || d[4]==0 || d[6]!=0 || d[7]!=0 ||
                  d[3][0]!=(d[28]!=0))begin
            state_next=FINISH;
          end else begin
            state_next=BODY;
          end
        end
      end
      BODY:begin
        if(d[8]!=32'h4c4e3135 || d[9]!=96)begin
          state_next=FINISH;
        end else begin
          state_next=IDENTITY;
        end
      end
      IDENTITY:begin
        if((d[10]|d[11])==0 || (d[12]|d[13])==0)begin
          state_next=FINISH;
        end else begin
          state_next=OPCODE;
        end
      end
      OPCODE:begin
        if(d[14]!=2)begin
          state_next=FINISH;
        end else begin
          state_next=SHAPE;
        end
      end
      SHAPE:begin
        if(d[15]==0 || d[16]==0 || d[17]==0)begin
          state_next=FINISH;
        end else begin
          state_next=LIMITS;
        end
      end
      LIMITS:begin
        if(d[15]>512 || d[16]>151936 || d[17]>4864)begin
          state_next=FINISH;
        end else begin
          state_next=COPY;
        end
      end
      COPY:begin
        if(private_copy_bad)begin
          state_next=FINISH;
        end else begin
          state_next=STRIDE;
        end
      end
      STRIDE:begin
        if(d[24]<(d[16]<<2))begin
          state_next=FINISH;
        end else begin
          state_next=PRODUCT;
        end
      end
      PRODUCT:begin
        if(bit_index!=31)begin
          state_next=state;
        end else begin
          case(product_index)
            0:begin
              state_next=state;
            end
            1:begin
              state_next=state;
            end
            2:begin
              state_next=state;
            end
            3:begin
              state_next=state;
            end
            4:begin
              state_next=state;
            end
            5:begin
              state_next=state;
            end
            6:begin
              state_next=state;
            end
            7:begin
              state_next=RANGE_PRE;
            end
            default:begin
              state_next=FINISH;
            end
          endcase
        end
      end
      RANGE_PRE:state_next=RANGE;
      RANGE:begin
        if(range_bad)begin
          state_next=FINISH;
        end else begin
          if(range_index==4)begin
            state_next=ALIGN;
          end else begin
            state_next=state;
          end
        end
      end
      ALIGN:begin
        state_next=FINISH;
      end
      default:begin
        state_next=IDLE;
      end
    endcase
  end
  always_ff @(posedge clk or negedge reset_n)begin
    if(!reset_n)state<=IDLE;
    else state<=state_next;
  end

endmodule
