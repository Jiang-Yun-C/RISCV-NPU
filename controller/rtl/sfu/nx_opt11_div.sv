// Binary32 division, gradual underflow, round-to-nearest ties-to-even.
// One restoring bit per cycle; no real/shortreal or simulator arithmetic.
module nx_opt11_div (
  input wire clk,reset_n,start,
  input wire [31:0] a,b,
  output wire ready,
  output reg valid,
  output reg [31:0] result
);
  reg [2:0] state;
  reg sign_bit;
  reg [23:0] ma,mb;
  reg signed [11:0] ea,eb,ex;
  reg [25:0] remainder;
  reg [26:0] quotient;
  reg [5:0] count;
  reg [26:0] shifted;
  reg [24:0] rounded;
  reg sticky;
  integer shift_by;
  assign ready=state==0;
  // Same original if(j<shift_by) selection; unknown comparisons select zero.
  wire [26:0] lost_mask;
  for(genvar lost_bit=0;lost_bit<27;lost_bit=lost_bit+1)begin: sticky_select
    localparam integer LOST_INDEX=lost_bit;
    reg selected;
    always @* begin
      if(LOST_INDEX<shift_by)selected=1'b1;
      else selected=1'b0;
    end
    assign lost_mask[lost_bit]=selected;
  end
  always @* begin
    shifted=quotient;shift_by=0;
    if(ex < -126) begin
      shift_by=-126-ex;
      shifted=shift_by>=27 ? 0 : quotient>>shift_by;
    end
    sticky=(remainder!=0)|(|(quotient&lost_mask));
    rounded={1'b0,shifted[26:3]}+
      (shifted[2]&&(shifted[1]||shifted[0]||sticky||shifted[3]));
  end
  always @(posedge clk or negedge reset_n) begin
    if(!reset_n)begin ;valid<=0;result<=0;ma<=0;mb<=0;ea<=0;eb<=0;ex<=0;
      remainder<=0;quotient<=0;count<=0;sign_bit<=0;end
    else begin
      valid<=0;
      case(state)
        0:if(start)begin
          sign_bit<=a[31]^b[31];
          ma<={a[30:23]!=0,a[22:0]};mb<={b[30:23]!=0,b[22:0]};
          ea<=a[30:23]==0 ? -126 : $signed({1'b0,a[30:23]})-127;
          eb<=b[30:23]==0 ? -126 : $signed({1'b0,b[30:23]})-127;
          if(a[30:23]==255||b[30:23]==255||b[30:0]==0)begin result<=32'h7fc00000;;end
          else if(a[30:0]==0)begin result<={a[31]^b[31],31'b0};;end
          else ;
        end
        1:if(!ma[23])begin ma<=ma<<1;ea<=ea-1;end
          else if(!mb[23])begin mb<=mb<<1;eb<=eb-1;end
          else begin
            ex<=ea-eb-(ma<mb);remainder<=ma<mb ? {1'b0,ma,1'b0} : {2'b0,ma};
            quotient<=0;count<=0;;
          end
        2:begin
          if(remainder>={2'b0,mb})begin
            remainder<=(remainder-{2'b0,mb})<<1;quotient<={quotient[25:0],1'b1};
          end else begin remainder<=remainder<<1;quotient<=quotient<<1;end
          if(count==26);else count<=count+1;
        end
        3:begin
          if(ex>127)result<={sign_bit,8'hff,23'b0};
          else if(ex < -126)result<={sign_bit,7'b0,rounded[23],rounded[22:0]};
          else if(rounded[24])begin
            if(ex==127)result<={sign_bit,8'hff,23'b0};
            else result<={sign_bit,8'(ex+128),23'b0};
          end else result<={sign_bit,8'(ex+127),rounded[22:0]};
          ;
        end
        5:begin valid<=1;;end
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
          if(a[30:23]==255||b[30:23]==255||b[30:0]==0)begin
            state_next=5;
          end else begin
            if(a[30:0]==0)begin
              state_next=5;
            end else begin
              state_next=1;
            end
          end
        end else begin
          state_next=state;
        end
      end
      1:begin
        if(!ma[23])begin
          state_next=state;
        end else begin
          if(!mb[23])begin
            state_next=state;
          end else begin
            state_next=2;
          end
        end
      end
      2:begin
        if(count==26)begin
          state_next=3;
        end else begin
          state_next=state;
        end
      end
      3:begin
        state_next=5;
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
