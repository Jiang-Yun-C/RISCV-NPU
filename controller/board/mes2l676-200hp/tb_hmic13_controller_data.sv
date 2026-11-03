`timescale 1ns/1ps
// Only the encrypted controller is real here. PHY is replaced by a DFI responder.
// This determines user-port burst encoding; it cannot validate DDR memory.
module tb_hmic13_controller_data;
  reg clk=0, rstn=0;
  always #5.333 clk=~clk;
  reg [27:0] awaddr=0, araddr=0;
  reg [3:0] awlen=0, arlen=0, awid=0, arid=0;
  reg awvalid=0, arvalid=0;
  wire awready, arready, wready, wlast, rvalid, rlast, init_done;
  wire [3:0] wid, rid;
  wire [255:0] rdata;
  reg [255:0] wdata;
  reg [31:0] wstrb;
  integer requested_data_beats=0, dfi_data_beats=0, data_mismatches=0, mask_mismatches=0;
  integer dfi_quarters=0, phase, qbeat, quarter;
  reg [255:0] expected_data[0:255];
  reg [31:0] expected_mask[0:255];
  function [255:0] pattern;
    input integer index;
    integer lane;
    begin
      for(lane=0;lane<8;lane=lane+1)
        pattern[lane*32+:32]=32'hc3a55a3c ^ (index*8+lane);
    end
  endfunction
  always @(posedge clk) begin
    if(rstn && init_done && wready) begin
      expected_data[requested_data_beats]=wdata;
      expected_mask[requested_data_beats]=~wstrb;
      requested_data_beats=requested_data_beats+1;
      wdata<=pattern(requested_data_beats);
      wstrb<=32'hf0f0f0f0 ^ (32'h01010101 << (requested_data_beats % 8));
    end
  end
  // DFI quarters may straddle two core cycles. Only enabled phases are valid.
  // The physical phase index is independent of the position within a user beat.
  always @(posedge clk) begin
    if(rstn && init_done) begin
      for(phase=0;phase<4;phase=phase+1) begin
        if(dut.dfi_wrdata_en[phase]) begin
          qbeat=dfi_quarters/4; quarter=dfi_quarters%4;
          if(qbeat>=requested_data_beats) $fatal(1,"DFI output precedes requested user payload");
          if(dut.dfi_wrdata[phase*64+:64] !== expected_data[qbeat][quarter*64+:64])
            data_mismatches=data_mismatches+1;
          if(dut.dfi_wrdata_mask[phase*8+:8] !== expected_mask[qbeat][quarter*8+:8])
            mask_mismatches=mask_mismatches+1;
          dfi_quarters=dfi_quarters+1;
        end
      end
      dfi_data_beats=dfi_quarters/4;
    end
  end
  integer wbeats=0, rbeats=0, expected_len=0, cases=0;
  integer wdone=0, rdone=0, mismatches=0;
  integer write_id_mismatches=0, read_id_mismatches=0;
  hmic_probe dut (
    .ref_clk(clk), .resetn(rstn), .ddr_init_done(init_done),
    .axi_awaddr(awaddr), .axi_awuser_ap(1'b1), .axi_awuser_id(awid),
    .axi_awlen(awlen), .axi_awready(awready), .axi_awvalid(awvalid),
    .axi_wdata(wdata), .axi_wstrb(wstrb),
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
    wdata=pattern(0); wstrb=32'hf1f1f1f1;
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
    repeat(100) @(negedge clk);
    $display("HMIC_CONTROLLER_DATA_RESULT requests=%0d dfi_beats=%0d data_mismatches=%0d mask_mismatches=%0d PHY_STUB=1 BOARD_TEST=0",requested_data_beats,dfi_data_beats,data_mismatches,mask_mismatches);
    if(dfi_quarters!=requested_data_beats*4 || data_mismatches || mask_mismatches) $fatal(1,"Variable data/mask mismatch");
    if(mismatches!=0) $fatal(1,"Controller LEN+1 mismatches=%0d",mismatches);
    $display("HMIC13_CONTROLLER_DATA_PASS cases=%0d writes=%0d reads=%0d write_id_mismatches=%0d read_id_mismatches=%0d PHY_STUB=1 BOARD_TEST=0",
      cases,wdone,rdone,write_id_mismatches,read_id_mismatches);
    $finish;
  end
  initial begin #1000000; $fatal(1,"HMIC13_CONTROLLER_LEN_TIMEOUT writes=%0d reads=%0d",wdone,rdone); end
endmodule
