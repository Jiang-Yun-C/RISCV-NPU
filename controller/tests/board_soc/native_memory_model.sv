// Digital HMIC user-port environment. No PHY, DDR training or analog timing.
// Native writes commit six cycles after WLAST; the SoC adapter must read back.
module t24_native_memory_model(input logic clk, reset_n,
  input logic [27:0] d_awaddr, d_araddr,
  input logic [3:0] d_awid, d_arid, d_awlen, d_arlen,
  input logic d_awvalid, d_arvalid,
  output logic d_awready, d_arready, d_wready, d_wlast,
  input logic [255:0] d_wdata,
  input logic [31:0] d_wstrb,
  output logic [255:0] d_rdata,
  output logic [3:0] d_rid,
  output logic d_rvalid, d_rlast);
  import sparse_memory_pkg::*;
  sparse_memory mem;
  logic [31:0] rng=32'h2468ace1;
  logic writing=0, reading=0;
  logic [27:0] write_word, read_word;
  integer write_len, read_len, write_beat=0, read_beat=0, commit_due=0;
  logic [255:0] payload[0:15];
  logic [31:0] masks[0:15];
  longint unsigned address;
  integer native_checks=0, native_write_beats=0, native_read_beats=0;
  initial mem=new(0,64'h100000000);
  always_comb begin
    d_awready=reset_n && !writing && !reading && commit_due==0 && rng[0];
    d_arready=reset_n && !writing && !reading && commit_due==0 && rng[1];
    d_wready=reset_n && writing && rng[2];
    d_wlast=writing && write_beat==write_len;
    d_rvalid=reset_n && reading && rng[3];
    d_rlast=reading && read_beat==read_len; d_rid=0;
  end
  always @(negedge clk) begin
    d_rdata=0;
    if(reading) begin
      address=64'h80000000+4*(64'(read_word)+8*read_beat);
      for(int i=0;i<32;i++) d_rdata[8*i+:8]=mem.read_byte(address+i);
    end
  end
  always @(posedge clk) begin
    if(!reset_n) begin writing<=0; reading<=0; commit_due<=0; write_beat<=0; read_beat<=0; rng<=32'h2468ace1; end
    else begin
      rng<={rng[30:0],rng[31]^rng[21]^rng[1]^rng[0]};
      if(commit_due>0) begin
        commit_due<=commit_due-1;
        if(commit_due==1) begin
          for(int b=0;b<=write_len;b++) begin
            address=64'h80000000+4*(64'(write_word)+8*b);
            for(int i=0;i<32;i++) if(masks[b][i]) mem.write_byte(address+i,payload[b][8*i+:8]);
          end
        end
      end
      if(d_awvalid && d_awready) begin
        if(d_awid!=0 || d_awaddr[2:0]!=0 || {1'b0,d_awaddr[9:0]}+8*(int'(d_awlen)+1)>1024) $fatal(1,"native write address/ID/column");
        native_checks++; writing<=1; write_word<=d_awaddr; write_len<=d_awlen; write_beat<=0;
      end
      if(d_arvalid && d_arready) begin
        if(d_arid!=0 || d_araddr[2:0]!=0 || {1'b0,d_araddr[9:0]}+8*(int'(d_arlen)+1)>1024) $fatal(1,"native read address/ID/column");
        native_checks++; reading<=1; read_word<=d_araddr; read_len<=d_arlen; read_beat<=0;
      end
      if(writing && d_wready) begin
        payload[write_beat]<=d_wdata; masks[write_beat]<=d_wstrb;
        native_write_beats++; native_checks++;
        if(d_wlast) begin writing<=0; commit_due<=6; end
        else write_beat<=write_beat+1;
      end
      if(reading && d_rvalid) begin
        native_read_beats++; native_checks++;
        if(d_rlast) reading<=0; else read_beat<=read_beat+1;
      end
    end
  end
endmodule
