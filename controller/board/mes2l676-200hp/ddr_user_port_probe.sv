`timescale 1ns/1ps
// Behavioral probe of the generated controller. Does not prescribe LEN encoding.
module ddr_user_port_probe;
  integer wlen[16][64], rlen[16][64];
  integer wh[16], wt[16], rh[16], rt[16], wb[16], rb[16];
  integer aw_count = 0, ar_count = 0, w_count = 0, r_count = 0;
  integer wbursts = 0, rbursts = 0, plus_one_mismatch = 0;
  integer old_manual_mismatch = 0, unexpected_data = 0;
  integer i, id, enc, beats;
  initial begin
    for (i=0; i<16; i=i+1) begin
      wh[i]=0; wt[i]=0; rh[i]=0; rt[i]=0; wb[i]=0; rb[i]=0;
    end
  end
  always @(posedge ddr3_test_top_tb.u_ddr.core_clk) begin
    if (ddr3_test_top_tb.dfi_init_complete === 1'b1) begin
      if (ddr3_test_top_tb.u_ddr.axi_awvalid && ddr3_test_top_tb.u_ddr.axi_awready) begin
        id=ddr3_test_top_tb.u_ddr.axi_awuser_id;
        if (wt[id]-wh[id]>=64) $fatal(1,"WRITE_PROBE_QUEUE_OVERFLOW");
        wlen[id][wt[id]%64]=ddr3_test_top_tb.u_ddr.axi_awlen;
        wt[id]=wt[id]+1; aw_count=aw_count+1;
      end
      if (ddr3_test_top_tb.u_ddr.axi_arvalid && ddr3_test_top_tb.u_ddr.axi_arready) begin
        id=ddr3_test_top_tb.u_ddr.axi_aruser_id;
        if (rt[id]-rh[id]>=64) $fatal(1,"READ_PROBE_QUEUE_OVERFLOW");
        rlen[id][rt[id]%64]=ddr3_test_top_tb.u_ddr.axi_arlen;
        rt[id]=rt[id]+1; ar_count=ar_count+1;
      end
      if (ddr3_test_top_tb.u_ddr.axi_wready) begin
        id=ddr3_test_top_tb.u_ddr.axi_wusero_id;
        w_count=w_count+1; wb[id]=wb[id]+1;
        if (ddr3_test_top_tb.u_ddr.axi_wusero_last) begin
          if (wh[id]==wt[id]) unexpected_data=unexpected_data+1;
          else begin
            enc=wlen[id][wh[id]%64]; beats=wb[id];
            if (beats!=enc+1) plus_one_mismatch=plus_one_mismatch+1;
            if (beats!=(enc==0 ? 16 : enc)) old_manual_mismatch=old_manual_mismatch+1;
            if (wbursts<8) $display("DDR_PORT_WRITE_BURST id=%0d len_field=%0d beats=%0d",id,enc,beats);
            wh[id]=wh[id]+1;
          end
          wb[id]=0; wbursts=wbursts+1;
        end
      end
      if (ddr3_test_top_tb.u_ddr.axi_rvalid) begin
        id=ddr3_test_top_tb.u_ddr.axi_rid;
        r_count=r_count+1; rb[id]=rb[id]+1;
        if (ddr3_test_top_tb.u_ddr.axi_rlast) begin
          if (rh[id]==rt[id]) unexpected_data=unexpected_data+1;
          else begin
            enc=rlen[id][rh[id]%64]; beats=rb[id];
            if (beats!=enc+1) plus_one_mismatch=plus_one_mismatch+1;
            if (beats!=(enc==0 ? 16 : enc)) old_manual_mismatch=old_manual_mismatch+1;
            if (rbursts<8) $display("DDR_PORT_READ_BURST id=%0d len_field=%0d beats=%0d",id,enc,beats);
            rh[id]=rh[id]+1;
          end
          rb[id]=0; rbursts=rbursts+1;
        end
      end
    end
  end
  final begin
    $display("DDR_PORT_PROBE_SUMMARY aw=%0d ar=%0d wbeats=%0d rbeats=%0d wbursts=%0d rbursts=%0d len_plus_one_mismatch=%0d old_manual_mismatch=%0d unexpected_data=%0d vendor_err_cnt=%0d",
      aw_count,ar_count,w_count,r_count,wbursts,rbursts,plus_one_mismatch,
      old_manual_mismatch,unexpected_data,ddr3_test_top_tb.u_ddr.err_cnt);
  end
endmodule
