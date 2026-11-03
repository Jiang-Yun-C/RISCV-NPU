`timescale 1ns/1ps
// Only the encrypted controller is real here. PHY is replaced by a DFI responder.
// This determines user-port burst encoding; it cannot validate DDR memory.
module tb_hmic13_controller_len;
  reg clk=0, rstn=0;
  always #5.333 clk=~clk;
  reg [27:0] awaddr=0, araddr=0;
  reg [3:0] awlen=0, arlen=0, awid=0, arid=0;
  reg awvalid=0, arvalid=0;
  wire awready, arready, wready, wlast, rvalid, rlast, init_done;
  wire [3:0] wid, rid;
  wire [255:0] rdata;
  integer wbeats=0, rbeats=0, expected_len=0, cases=0;
  integer wdone=0, rdone=0, mismatches=0;
  integer write_id_mismatches=0, read_id_mismatches=0;
  hmic_probe dut (
    .ref_clk(clk), .resetn(rstn), .ddr_init_done(init_done),
    .axi_awaddr(awaddr), .axi_awuser_ap(1'b1), .axi_awuser_id(awid),
    .axi_awlen(awlen), .axi_awready(awready), .axi_awvalid(awvalid),
    .axi_wdata({8{32'h12345678}}), .axi_wstrb(32'hffffffff),
    .axi_wready(wready), .axi_wusero_id(wid), .axi_wusero_last(wlast),
    .axi_araddr(araddr), .axi_aruser_ap(1'b1), .axi_aruser_id(arid),
    .axi_arlen(arlen), .axi_arready(arready), .axi_arvalid(arvalid),
    .axi_rdata(rdata), .axi_rid(rid), .axi_rlast(rlast), .axi_rvalid(rvalid),
    .apb_clk(clk), .apb_rst_n(rstn), .apb_sel(1'b0), .apb_enable(1'b0),
    .apb_addr(8'b0), .apb_write(1'b0), .apb_wdata(16'b0)
  );
  GTP_GRS GRS_INST(.GRS_N(rstn));
  always @(posedge clk) begin
    if (rstn && init_done) begin
      if (wready) begin
        wbeats=wbeats+1;
        if (wid!=awid) begin
          write_id_mismatches=write_id_mismatches+1;
          $display("HMIC_CTRL_WRITE_ID_MISMATCH actual=%0d expected=%0d last=%0b",wid,awid,wlast);
        end
        if (wlast) begin
          $display("HMIC_CTRL_WRITE_LEN field=%0d beats=%0d",expected_len,wbeats);
          if (wbeats!=expected_len+1) mismatches=mismatches+1;
          wdone=wdone+1;
        end
      end
      if (rvalid) begin
        rbeats=rbeats+1;
        if (rid!=arid) read_id_mismatches=read_id_mismatches+1;
        if (rlast) begin
          $display("HMIC_CTRL_READ_LEN field=%0d beats=%0d",expected_len,rbeats);
          if (rbeats!=expected_len+1) mismatches=mismatches+1;
          rdone=rdone+1;
        end
      end
    end
  end
  integer trace_cycles=0;
  always @(negedge clk) begin
    if (init_done && trace_cycles<120) begin
      trace_cycles=trace_cycles+1;
      $display("CTRL_TRACE t=%0t aw=%0b/%0b awid=%0d awlen=%0d wready=%0b wid=%0d wlast=%0b ar=%0b/%0b rid=%0d rv=%0b rlast=%0b",$time,awvalid,awready,awid,awlen,wready,wid,wlast,arvalid,arready,rid,rvalid,rlast);
    end
  end
  integer n;
  initial begin
    repeat (20) @(negedge clk); rstn=1;
    wait(init_done);
    for(n=0;n<17;n=n+1) begin
      repeat(8) @(negedge clk);
      expected_len=(n==16 ? 0 : n);
      awlen=expected_len[3:0]; arlen=expected_len[3:0];
      awid=(n==16 ? 4'd9 : n[3:0]); arid=awid;
      awaddr=n*128; araddr=n*128; wbeats=0; rbeats=0;
      awvalid=1;
      do @(posedge clk); while(!awready);
      @(negedge clk); awvalid=0;
      wait(wdone==n+1);
      repeat(16) @(negedge clk);
      arvalid=1;
      do @(posedge clk); while(!arready);
      @(negedge clk); arvalid=0;
      wait(rdone==n+1);
      cases=cases+1;
    end
    if(mismatches!=0) $fatal(1,"Controller LEN+1 mismatches=%0d",mismatches);
    $display("HMIC13_CONTROLLER_LEN_PASS cases=%0d writes=%0d reads=%0d write_id_mismatches=%0d read_id_mismatches=%0d PHY_STUB=1 BOARD_TEST=0",
      cases,wdone,rdone,write_id_mismatches,read_id_mismatches);
    $finish;
  end
  initial begin #1000000; $fatal(1,"HMIC13_CONTROLLER_LEN_TIMEOUT writes=%0d reads=%0d",wdone,rdone); end
endmodule
