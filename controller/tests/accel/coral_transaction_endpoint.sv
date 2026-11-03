// TEST DOUBLE, never a Coral execution claim. Native TCM/CSR slave and explicit
// AXI master model the T13 transport probe. Image bytes are uploaded by real CPU;
// this endpoint does NOT execute them. Real RVV/W8 must be requalified in T16.
module coral_transaction_endpoint(input logic clk,reset_n,input int mode,input logic[31:0] cycle,input logic stale_data,
  output logic interrupt,output logic[31:0] launches,
  axi4_if.slave slave,axi4_if.master master);
  logic[31:0] itcm[2048],dtcm[8192];
  logic[31:0] control=3,entry=0,status=0,wa,ra;
  logic aw_have,w_have;
  logic[127:0] wd;logic[15:0] strobe;
  logic[31:0] source,destination,count,mask,index,value,launch_cycle;
  logic[63:0] session,seqno;
  logic[5:0] write_id=6'h25,read_id=6'h12;
  typedef enum logic[3:0]{STOP,READ_ADDR,READ_DATA,WRITE_DATA,WRITE_RESP,NEXT_WORD,HANG} state_t;
  state_t state=STOP;
  logic aw_sent,w_sent;
  int active_mode;
  logic[31:0] late_irq_due=0;
  function automatic logic[31:0] read_word(logic[31:0] address);
    if(address<8192)return itcm[address/4] ^ ((mode==12&&address==4)?32'h1:32'h0);
    if(address>=32'h10000&&address<32'h18000)return dtcm[(address-32'h10000)/4];
    case(address)32'h30000:return control;32'h30004:return entry;32'h30008:return status;default:return 0;endcase
  endfunction
  task automatic finish_record();
    dtcm[64]=1;dtcm[65]=32;dtcm[66]=session[31:0];dtcm[67]=session[63:32];
    dtcm[68]=seqno[31:0]-(active_mode==5?1:0);dtcm[69]=seqno[63:32];dtcm[70]=0;dtcm[71]=1;
    status=1;
    if(active_mode==6)late_irq_due=cycle+16000;
  endtask
  assign slave.awready=!aw_have&&!slave.bvalid;
  assign slave.wready=!w_have&&!slave.bvalid;
  assign slave.arready=!slave.rvalid;
  assign master.arvalid=state==READ_ADDR;
  assign master.araddr=source+4*index;assign master.arlen=0;assign master.arsize=2;assign master.arburst=1;assign master.arid=read_id;
  assign master.rready=state==READ_DATA;
  assign master.awvalid=state==WRITE_DATA&&!aw_sent;
  assign master.awaddr=destination+4*index;assign master.awlen=0;assign master.awsize=2;assign master.awburst=1;assign master.awid=write_id;
  assign master.wvalid=state==WRITE_DATA&&!w_sent;
  assign master.wdata={96'b0,value}<<(8*((destination+4*index)&15));
  assign master.wstrb=16'hf<<((destination+4*index)&15);assign master.wlast=1;
  assign master.bready=state==WRITE_RESP;
  always @(posedge clk)begin
    if(!reset_n)begin
      aw_have<=0;w_have<=0;slave.bvalid<=0;slave.bresp<=0;slave.bid<=0;
      slave.rvalid<=0;slave.rdata<=0;slave.rresp<=0;slave.rlast<=1;slave.rid<=0;
      control=3;status=0;entry=0;state<=STOP;index<=0;aw_sent<=0;w_sent<=0;
      interrupt<=0;launches<=0;active_mode<=0;launch_cycle<=0;
      source<=0;destination<=0;value<=0;count<=0;mask<=0;session<=0;seqno<=0;
    end else begin
      if(slave.awvalid&&slave.awready)begin aw_have<=1;wa<=slave.awaddr;end
      if(slave.wvalid&&slave.wready)begin w_have<=1;wd<=slave.wdata;strobe<=slave.wstrb;end
      if(aw_have&&w_have&&!slave.bvalid)begin
        for(int lane=0;lane<16;lane++)if(strobe[lane])begin
          if((wa&32'hfffffff0)+lane<8192)itcm[((wa&32'hfffffff0)+lane)/4][8*(lane%4)+:8]=wd[8*lane+:8];
          else if(wa>=32'h10000&&wa<32'h18000)dtcm[((wa&32'hfffffff0)+lane-32'h10000)/4][8*(lane%4)+:8]=wd[8*lane+:8];
        end
        if(wa==32'h30004)entry=wd[32+:32];
        if(wa==32'h30000)begin
          control=wd[31:0];
          if(control==3)begin state<=STOP;status=0;interrupt<=0;end
          if(control==0)begin
            launches<=launches+1;launch_cycle<=cycle;active_mode<=mode;
            source<=dtcm[7];destination<=mode==8?32'hb4000000:dtcm[8];count<=dtcm[9];mask<=dtcm[10];
            session<={dtcm[3],dtcm[2]};seqno<={dtcm[5],dtcm[4]};
            index<=0;status=0;interrupt<=0;aw_sent<=0;w_sent<=0;
            if(mode==2)begin status=3;state<=STOP;end
            else if(mode==3)state<=HANG;
            else state<=READ_ADDR;
          end
        end
        slave.bvalid<=1;slave.bresp<=0;slave.bid<=0;
      end
      if(slave.bvalid&&slave.bready)begin slave.bvalid<=0;aw_have<=0;w_have<=0;end
      if(slave.arvalid&&slave.arready)begin
        slave.rvalid<=1;slave.rresp<=0;slave.rid<=0;slave.rlast<=1;slave.rdata<=0;
        slave.rdata[32*slave.araddr[3:2]+:32]<=read_word(slave.araddr);
      end
      if(slave.rvalid&&slave.rready)slave.rvalid<=0;
      if(state==READ_ADDR&&master.arready)state<=READ_DATA;
      if(state==READ_DATA&&master.rvalid)begin
        if(master.rresp!=0)begin status=3;state<=STOP;end
        else begin value<=stale_data?32'hdeadbeef:(32'(master.rdata>>(8*((source+4*index)&15)))^mask);state<=WRITE_DATA;end
      end
      if(state==WRITE_DATA)begin
        if(master.awvalid&&master.awready)aw_sent<=1;
        if(master.wvalid&&master.wready)w_sent<=1;
        if((aw_sent||master.awready)&&(w_sent||master.wready))begin
          state<=WRITE_RESP;
          // Deliberately halt and publish the record while the last B is pending.
          // The driver/guard must independently wait for visibility, even at halt.
          if(index+1==count)finish_record();
        end
      end
      if(state==WRITE_RESP&&master.bvalid)begin
        if(master.bresp!=0)begin status=3;state<=STOP;end
        else begin
          aw_sent<=0;w_sent<=0;
          if(index+1==count)state<=STOP;
          else begin index<=index+1;state<=READ_ADDR;end
        end
      end
      if(late_irq_due!=0&&cycle>=late_irq_due)begin interrupt<=1;late_irq_due=0;end
      if(status!=0&&active_mode!=7&&active_mode!=6)begin
        if(active_mode!=6||cycle-launch_cycle>16000)interrupt<=1;
      end
    end
  end
endmodule
