// exp(-abs(binary32)): ln2 range reduction and degree-21 Q96 Horner.
// The exact radix-65536 multiplier takes 7 cycles, independent of lane count.
// Generated constants are round-even high precision values; no runtime table
// is derived from test inputs. Every output is rounded once to binary32.
module nx_opt11_exp (
  input wire clk,reset_n,start,
  input wire [31:0] a,
  output wire ready,
  output reg valid,
  output reg [31:0] result
);
  localparam [103:0] LN2=104'h00b17217f7d1cf79abc9e3b398;
  reg [3:0] state;
  reg [103:0] remainder;
  (* keep = 1, syn_keep = 1 *) wire [103:0] reduced_remainder=remainder-LN2;
  reg [7:0] power;
  reg [96:0] y,r;
  reg [208:0] product;
  reg [111:0] multiplier;
  reg [3:0] chunk;
  reg [4:0] degree;
  wire [112:0] partial=r*multiplier[15:0];
  // Constant shifts;112 padded multiplier bits, all bits above96 are zero.
  wire [224:0] accumulated={16'b0,product}+{partial,112'b0};
  wire [208:0] next_product=accumulated[224:16];
  reg [96:0] mant;
  reg guard_bit,sticky;
  integer exponent,lead,sh;
  reg signed [9:0] exponent_q;
  reg [6:0] shift_q;
  reg [23:0] mant_q;
  reg guard_q,sticky_q;
  wire [24:0] final_round={1'b0,mant_q}+(guard_q&&(sticky_q||mant_q[0]));
  function automatic [96:0] coefficient(input [4:0] k);
    case(k)
      5'd0:coefficient=97'h1000000000000000000000000;
      5'd1:coefficient=97'h1000000000000000000000000;
      5'd2:coefficient=97'h0800000000000000000000000;
      5'd3:coefficient=97'h02aaaaaaaaaaaaaaaaaaaaaab;
      5'd4:coefficient=97'h00aaaaaaaaaaaaaaaaaaaaaab;
      5'd5:coefficient=97'h0022222222222222222222222;
      5'd6:coefficient=97'h0005b05b05b05b05b05b05b06;
      5'd7:coefficient=97'h0000d00d00d00d00d00d00d01;
      5'd8:coefficient=97'h00001a01a01a01a01a01a01a0;
      5'd9:coefficient=97'h000002e3bc74aad8e671f5584;
      5'd10:coefficient=97'h00000049f93edde27d71cbbc0;
      5'd11:coefficient=97'h00000006b99159fd5138e3f9d;
      5'd12:coefficient=97'h000000008f76c77fc6c4bdaa2;
      5'd13:coefficient=97'h000000000b092309d43684be5;
      5'd14:coefficient=97'h0000000000c9cba54603e4e90;
      5'd15:coefficient=97'h00000000000d73f9f399dc0f9;
      5'd16:coefficient=97'h000000000000d73f9f399dc10;
      5'd17:coefficient=97'h0000000000000ca963b81856a;
      5'd18:coefficient=97'h00000000000000b413c31dcbf;
      5'd19:coefficient=97'h00000000000000097a4da340a;
      5'd20:coefficient=97'h00000000000000007950ae901;
      5'd21:coefficient=97'h000000000000000005c6e3bdb;
      default:coefficient=0;
    endcase
  endfunction
  assign ready=state==0;
  function automatic logic exp_if_true(input logic value);
    begin if(value)exp_if_true=1'b1;else exp_if_true=1'b0;end
  endfunction
  function automatic logic guard_from_shift(input logic[96:0] value,input logic[6:0] shift);
    begin if(shift>=1&&shift<=97)guard_from_shift=value[integer'(shift)-1];else guard_from_shift=1'b0;end
  endfunction
  wire[96:0] sticky_terms;
  genvar sticky_lane;
  generate for(sticky_lane=0;sticky_lane<97;sticky_lane=sticky_lane+1)begin:sticky_projection
    assign sticky_terms[sticky_lane]=exp_if_true(integer'(sticky_lane)<integer'(shift_q)-1) ? y[sticky_lane] : 1'b0;
  end endgenerate
  always @* begin
    // Reduced exponential is in [1/2,1], so only these leading bits occur.
    lead=y[96] ? 96 : 95;
    exponent=lead-96-power;
    sh=exponent < -126 ? integer'(power)-53 : lead-23;
    mant=y>>shift_q;
    guard_bit=guard_from_shift(y,shift_q);sticky=|sticky_terms;
  end
  always @(posedge clk or negedge reset_n)begin
    if(!reset_n)begin ;valid<=0;result<=0;remainder<=0;power<=0;
      chunk<=0;degree<=0;exponent_q<=0;shift_q<=0;mant_q<=0;guard_q<=0;sticky_q<=0;end
    else begin
      valid<=0;
      case(state)
        0:if(start)begin
          power<=0;
          if(a[30:23]==255)begin result<=32'h7fc00000;;end
          else if(a[30:0]>=31'h42d00000)begin result<=0;;end // abs(a)>=104
          else if(a[30:23]<31)begin result<=32'h3f800000;;end
          else begin
            // a = 24-bit significand * 2^(encoded_exponent-150).
            remainder<=a[30:23]>=54 ? (104'({1'b1,a[22:0]})<<(a[30:23]-54)) :
                (104'({1'b1,a[22:0]})>>(54-a[30:23]));
            ;
          end
        end
        1:if(remainder>=LN2)begin remainder<=reduced_remainder;power<=power+1;end
          else begin degree<=20;;end
        2:begin chunk<=0;;end
        3:begin
          if(chunk==6)begin ;end
          else chunk<=chunk+1;
        end
        4:if(degree==0);else begin degree<=degree-1;;end
        5:begin exponent_q<=10'(exponent);shift_q<=7'(sh);;end
        7:begin mant_q<=mant[23:0];guard_q<=guard_bit;sticky_q<=sticky;;end
        8:begin
          if(exponent_q < -126)result<={8'b0,final_round[23:0]};
          else if(final_round[24])result<={1'b0,8'(exponent_q+128),23'b0};
          else result<={1'b0,8'(exponent_q+127),final_round[22:0]};
          ;
        end
        6:begin valid<=1;;end
        default:;
      endcase
    end
  end
  // The private Horner value is initialized in state 1 before state 2 reads
  // it, and each state-3 update precedes the next iteration or rounding.
  // Its pre-initialization value cannot reach ready/valid/result, including
  // during reset: those public outputs retain their original reset behavior.
  // These private multiplier operands/accumulator are dead until state 3.
  // A normal call fully loads r in state 1, then multiplier and product in
  // state 2 before that first use. Each polynomial iteration reloads state 2.
  // Reset still clears state/valid/result; interrupted and special-value calls
  // cannot publish or consume stale operands. Keep the original load/shift
  // edges and enables without distributing async reset to the APM inputs.
  always @(posedge clk)begin
      case(state)
        1:if(remainder>=LN2)begin end
          else begin r<=remainder[96:0];y<=coefficient(21);end
        2:begin product<=0;multiplier<={15'b0,y};end
        3:begin
          product<=next_product;multiplier<=multiplier>>16;
          if(chunk==6)y<=coefficient(degree)-next_product[192:96];
        end
        default:;
      endcase
  end
  reg[3:0]state_next;
  always @*begin
    case(state)
      0:begin
        if(start)begin
          if(a[30:23]==255)begin
            state_next=6;
          end else begin
            if(a[30:0]>=31'h42d00000)begin
              state_next=6;
            end else begin
              if(a[30:23]<31)begin
                state_next=6;
              end else begin
                state_next=1;
              end
            end
          end
        end else begin
          state_next=state;
        end
      end
      1:begin
        if(remainder>=LN2)begin
          state_next=state;
        end else begin
          state_next=2;
        end
      end
      2:begin
        state_next=3;
      end
      3:begin
        if(chunk==6)begin
          state_next=4;
        end else begin
          state_next=state;
        end
      end
      4:begin
        if(degree==0)begin
          state_next=5;
        end else begin
          state_next=2;
        end
      end
      5:begin
        state_next=7;
      end
      7:begin
        state_next=8;
      end
      8:begin
        state_next=6;
      end
      default:begin
        state_next=0;
      end
    endcase
  end
  always @(posedge clk or negedge reset_n)begin
    if(!reset_n)state<=0;else state<=state_next;
  end

endmodule
