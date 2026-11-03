// Binary32 sqrt: restoring radix-4 integer root and exact remainder RNE.
module nx_opt12_sqrt(input wire clk,reset_n,start,input wire [31:0] a,
  output wire ready,output reg valid,output reg [31:0] result);
  reg [2:0] state;reg [23:0] mantissa,root;
  reg signed [10:0] exponent;reg [47:0] radicand;
  reg [25:0] remainder;reg [4:0] count;
  wire [25:0] shifted={remainder[23:0],radicand[47:46]};
  wire [25:0] trial={root,2'b01};
  wire [24:0] rounded={1'b0,root}+(remainder>{2'b0,root});
  assign ready=state==0;
  always @(posedge clk or negedge reset_n)begin
    if(!reset_n)begin ;valid<=0;result<=0;mantissa<=0;root<=0;
      exponent<=0;radicand<=0;remainder<=0;count<=0;end
    else begin
      valid<=0;
      case(state)
        0:if(start)begin
          mantissa<={a[30:23]!=0,a[22:0]};
          exponent<=a[30:23]==0 ? -126 : $signed({1'b0,a[30:23]})-127;
          if(a[30:0]==0)begin result<=a;;end
          else if(a[31]||a[30:23]==255)begin result<=32'h7fc00000;;end
          else ;
        end
        1:if(!mantissa[23])begin mantissa<=mantissa<<1;exponent<=exponent-1;end
          else begin
            radicand<=exponent[0] ? {mantissa,24'b0} : {1'b0,mantissa,23'b0};
            exponent<=exponent>>>1;root<=0;remainder<=0;count<=0;;
          end
        2:begin
          if(shifted>=trial)begin remainder<=shifted-trial;root<={root[22:0],1'b1};end
          else begin remainder<=shifted;root<=root<<1;end
          radicand<=radicand<<2;
          if(count==23);else count<=count+1;
        end
        3:begin
          result<=rounded[24] ? {1'b0,8'(exponent+128),23'b0} : {1'b0,8'(exponent+127),rounded[22:0]};;
        end
        4:begin valid<=1;;end
        default:;
      endcase
    end
  end
  // Original state transition priority; all predicates read original old state.
  reg [2:0] state_next;
  always @* begin
    case(state)
      0:begin
        if(start)begin
          if(a[30:0]==0)begin
            state_next=4;
          end else begin
            if(a[31]||a[30:23]==255)begin
              state_next=4;
            end else begin
              state_next=1;
            end
          end
        end else begin
          state_next=state;
        end
      end
      1:begin
        if(!mantissa[23])begin
          state_next=state;
        end else begin
          state_next=2;
        end
      end
      2:begin
        if(count==23)begin
          state_next=3;
        end else begin
          state_next=state;
        end
      end
      3:begin
        state_next=4;
      end
      default:begin
        state_next=0;
      end
    endcase
  end
  always @(posedge clk or negedge reset_n)begin
    if(!reset_n)state<=0;
    else state<=state_next;
  end

endmodule
