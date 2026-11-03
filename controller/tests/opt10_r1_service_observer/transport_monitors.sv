// Passive accepted-work ledgers. No READY, VALID, reset, owner or data is driven.
module nx_service_axi_observer #(parameter string FILE="transport.csv",parameter READS=1)(
  input wire clk,reset,input wire [63:0] cycles,input wire [31:0] epoch,
  input wire owner,input wire fault,axi4_if bus,
  output wire idle,output reg [63:0] activity=0
);
  longint unsigned aw_count=0,b_count=0,ar_count=0,r_count=0,aw_beats=0,w_beats=0;
  reg [31:0] previous_epoch=0;
  reg epoch_seen=0,previous_fault=0,previous_reset=1;
  integer fd,increment;
  initial begin fd=$fopen(FILE,"w");if(!fd)$fatal(1,"transport log open");end
  assign idle=aw_count==b_count && aw_beats==w_beats && ar_count==r_count &&
    !bus.awvalid&&!bus.wvalid&&!bus.bvalid&&(!READS||(!bus.arvalid&&!bus.rvalid));
  always @(posedge clk)begin
    increment=0;
    if(reset)begin
      if(!previous_reset)begin
        $fwrite(fd,"%0d,RESET,0,0,0,0,0,0,%0d,%0d\n",cycles,epoch,owner);increment++;
      end
      previous_reset=1;
    end else begin
      previous_reset=0;
      if(!epoch_seen||epoch!=previous_epoch)begin
        $fwrite(fd,"%0d,EPOCH,0,0,0,0,0,0,%0d,%0d\n",cycles,epoch,owner);
        previous_epoch=epoch;epoch_seen=1;increment++;
      end
      if(fault!=previous_fault)begin
        $fwrite(fd,"%0d,FAULT,0,0,0,0,0,%0d,%0d,%0d\n",cycles,fault,epoch,owner);
        previous_fault=fault;increment++;
      end
      if(bus.awvalid&&bus.awready)begin
        aw_count<=aw_count+1;aw_beats<=aw_beats+int'(bus.awlen)+1;increment++;
        $fwrite(fd,"%0d,AW,%0d,%h,%0d,%0d,0,0,%0d,%0d\n",cycles,bus.awid,bus.awaddr,bus.awlen,bus.awsize,epoch,owner);
      end
      if(bus.wvalid&&bus.wready)begin
        w_beats<=w_beats+1;increment++;
        $fwrite(fd,"%0d,W,0,0,0,0,%0d,0,%0d,%0d\n",cycles,bus.wlast,epoch,owner);
      end
      if(bus.bvalid&&bus.bready)begin
        b_count<=b_count+1;increment++;
        $fwrite(fd,"%0d,B,%0d,0,0,0,0,%0d,%0d,%0d\n",cycles,bus.bid,bus.bresp,epoch,owner);
      end
      if(READS&&bus.arvalid&&bus.arready)begin
        ar_count<=ar_count+1;increment++;
        $fwrite(fd,"%0d,AR,%0d,%h,%0d,%0d,0,0,%0d,%0d\n",cycles,bus.arid,bus.araddr,bus.arlen,bus.arsize,epoch,owner);
      end
      if(READS&&bus.rvalid&&bus.rready)begin
        if(bus.rlast)r_count<=r_count+1;increment++;
        $fwrite(fd,"%0d,R,%0d,0,0,0,%0d,%0d,%0d,%0d\n",cycles,bus.rid,bus.rlast,bus.rresp,epoch,owner);
      end
    end
    activity<=activity+increment;
  end
  final $fclose(fd);
endmodule

// The native HMIC port has neither B nor RREADY. COMMIT comes from the exact
// digital memory model's delayed-write retirement, in addition to AXI readback.
module nx_service_native_observer #(parameter string FILE="transport-native.csv")(
  input wire clk,reset,input wire [63:0] cycles,input wire [31:0] epoch,
  input wire owner,input wire [27:0] awaddr,araddr,input wire [3:0] awid,arid,awlen,arlen,
  input wire awvalid,awready,arvalid,arready,wready,wlast,rvalid,rlast,
  input wire [3:0] rid,input wire commit_fire,model_pending,
  output wire idle,output reg [63:0] activity=0
);
  longint unsigned aw_count=0,commit_count=0,ar_count=0,r_count=0;
  integer fd,increment;
  initial begin fd=$fopen(FILE,"w");if(!fd)$fatal(1,"native transport log open");end
  assign idle=aw_count==commit_count && ar_count==r_count && !model_pending&&!awvalid&&!arvalid&&!rvalid;
  always @(posedge clk)if(!reset)begin
    increment=0;
    if(awvalid&&awready)begin
      aw_count<=aw_count+1;increment++;
      $fwrite(fd,"%0d,AW,%0d,%h,%0d,5,0,0,%0d,%0d\n",cycles,awid,32'h80000000+{awaddr,2'b0},awlen,epoch,owner);
    end
    if(wready)begin
      increment++;
      $fwrite(fd,"%0d,W,0,0,0,0,%0d,0,%0d,%0d\n",cycles,wlast,epoch,owner);
    end
    if(commit_fire)begin
      commit_count<=commit_count+1;increment++;
      $fwrite(fd,"%0d,COMMIT,0,0,0,0,0,0,%0d,%0d\n",cycles,epoch,owner);
    end
    if(arvalid&&arready)begin
      ar_count<=ar_count+1;increment++;
      $fwrite(fd,"%0d,AR,%0d,%h,%0d,5,0,0,%0d,%0d\n",cycles,arid,32'h80000000+{araddr,2'b0},arlen,epoch,owner);
    end
    if(rvalid)begin
      if(rlast)r_count<=r_count+1;increment++;
      $fwrite(fd,"%0d,R,%0d,0,0,0,%0d,0,%0d,%0d\n",cycles,rid,rlast,epoch,owner);
    end
    activity<=activity+increment;
  end
  final $fclose(fd);
endmodule
