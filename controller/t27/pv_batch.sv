// Test-private PV ABI. Reuses the exact production nx_opt11_fp RNE operator.
// One owner, one in-flight operation; no CE/SFU overlap or DMA assumptions.
module t27_pv_batch(input logic clk,reset_n,we,re,input logic [15:0] address,
 input logic [31:0] wdata,output logic [31:0] rdata);
 localparam P=0,V=448,W=4544,O=4608,WORDS=5056;
 logic [31:0] mem[0:WORDS-1];
 logic [31:0] length,heads,padded,request_seq,generation,cycles,muls,adds;
 logic busy,done;integer state,h,d,t,width;
 localparam IDLE=0,MUL=1,MWAIT=2,PAD=3,ADD=4,AWAIT=5,STORE=6;
 wire ready,valid;wire [31:0] result;
 wire start=(state==MUL||state==ADD)&&busy&&ready;
 wire [31:0] a=state==MUL?mem[P+h*64+t]:mem[W+2*t];
 wire [31:0] b=state==MUL?mem[V+d*64+t]:mem[W+2*t+1];
 nx_opt11_fp fp(.clk(clk),.reset_n(reset_n),.start(start),.multiply(state==MUL),.a(a),.b(b),.ready(ready),.valid(valid),.result(result));
 always_comb begin
  rdata=0;
  case(address)
   0:rdata={30'b0,done,busy};4:rdata=length;8:rdata=heads;12:rdata=padded;
   16:rdata=generation;20:rdata=request_seq;28:rdata=cycles;32:rdata=muls;36:rdata=adds;
   default:if(address>=16'h1000&&((address-16'h1000)>>2)<WORDS)rdata=mem[(address-16'h1000)>>2];
  endcase
 end
 always @(posedge clk)begin
  if(!reset_n)begin
   busy<=0;done<=0;state<=IDLE;generation<=0;request_seq<=0;length<=0;heads<=0;padded<=0;cycles<=0;muls<=0;adds<=0;h<=0;d<=0;t<=0;width<=0;
  end else begin
   if(we)begin
    if(address==24)begin
     if(!done||busy||wdata!=generation)$fatal(1,"PV bad ACK");
     done<=0;
    end else if(address==0)begin
     if(busy||done||wdata!=1||request_seq!=generation+1||generation==32'hffffffff||
        length<1||length>64||heads<1||heads>7||padded<length||padded>64||(padded&(padded-1))!=0)
      $fatal(1,"PV illegal submit/owner/shape");
     busy<=1;generation<=request_seq;cycles<=0;muls<=0;adds<=0;h<=0;d<=0;t<=0;state<=MUL;
    end else begin
     if(busy||done)$fatal(1,"PV host write while owned");
     case(address)
      4:length<=wdata;8:heads<=wdata;12:padded<=wdata;20:request_seq<=wdata;
      default:begin
       if(address<16'h1000||((address-16'h1000)>>2)>=W)$fatal(1,"PV write range");
       mem[(address-16'h1000)>>2]<=wdata;
      end
     endcase
    end
   end
   if(re&&address>=16'h1000&&(!done||busy||((address-16'h1000)>>2)<O))$fatal(1,"PV result before completion");
   if(busy)begin
    cycles<=cycles+1;
    case(state)
     MUL:if(ready)state<=MWAIT;
     MWAIT:if(valid)begin
      mem[W+t]<=result;muls<=muls+1;t<=t+1;
      if(t+1==length)begin
       if(length<padded)state<=PAD;
       else begin t<=0;width<=padded/2;state<=padded==1?STORE:ADD;end
      end else state<=MUL;
     end
     PAD:begin
      mem[W+t]<=0;t<=t+1;
      if(t+1==padded)begin t<=0;width<=padded/2;state<=padded==1?STORE:ADD;end
     end
     ADD:if(ready)state<=AWAIT;
     AWAIT:if(valid)begin
      mem[W+t]<=result;adds<=adds+1;t<=t+1;
      if(t+1==width)begin t<=0;width<=width/2;state<=width==1?STORE:ADD;end
      else state<=ADD;
     end
     STORE:begin
      mem[O+h*64+d]<=mem[W];t<=0;
      if(d==63)begin d<=0;h<=h+1;if(h+1==heads)begin busy<=0;done<=1;state<=IDLE;end else state<=MUL;end
      else begin d<=d+1;state<=MUL;end
     end
     default:$fatal(1,"PV invalid state");
    endcase
   end
  end
 end
endmodule
