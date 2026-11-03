`timescale 1ns/1ps
module tb_t23_phy_observer;
  reg clk=0,rst_n=0;
  always #4 clk=~clk;
  reg [31:0] flags=0,phy_aux=0;
  reg [33:0] phy_calib=0;
  reg [67:0] phy_slice_status=0;
  wire [2047:0] report;
  ddr_data_observer dut(.clk(clk),.rst_n(rst_n),.flags(flags),.errors(32'd0),
    .wbeats(32'd0),.rbeats(32'd0),.awcount(32'd0),.arcount(32'd0),
    .max_aw(32'd0),.max_ar(32'd0),.phase(32'd0),.address(32'd0),
    .drain(32'd0),.stalled(32'd0),.reason(32'd0),.beat(4'd0),.rid(4'd0),
    .rvalid(1'b0),.rlast(1'b0),.wready(1'b0),.wlast(1'b0),.failed(1'b0),
    .expected(256'd0),.rdata(256'd0),.wdata(256'd0),
    .verified_passes(32'd0),.first_error(32'd0),.full_verified(1'b0),.masks_verified(1'b0),
    .write_payload(64'd0),.read_payload(64'd0),.workload_cycles(64'd0),.workload(32'd0),
    .phy_aux(phy_aux),.phy_calib(phy_calib),.phy_slice_status(phy_slice_status),.report(report));
  integer fd,k;
  initial begin
    repeat(4) @(negedge clk);rst_n=1;
    repeat(4) @(negedge clk);
    flags=32'h07001130;
    repeat(4) @(negedge clk);
    phy_calib=34'h123450001;
    phy_slice_status=(68'd5<<64)|(68'd1<<48)|(68'd8<<32);phy_aux=32'h12345678;
    repeat(4) @(negedge clk);
    flags=32'h0c001130;phy_calib=34'h000020000;phy_slice_status=0;phy_aux=32'h87654321;
    repeat(4) @(negedge clk);
    fd=$fopen("observer-words.hex","w");
    for(k=0;k<64;k=k+1)$fwrite(fd,"%08x\n",report[k*32+:32]);
    $fclose(fd);$display("T23_PHY_OBSERVER_CAPTURE_READY");$finish;
  end
  initial begin #10000;$fatal(1,"Observer timeout");end
endmodule
