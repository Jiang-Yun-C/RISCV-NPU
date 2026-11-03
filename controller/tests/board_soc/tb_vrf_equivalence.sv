module tb_vrf_equivalence;
  reg clk=0,rst_n=0;
  reg [29:0] dp2vrf_rd_index=0;
  reg [4:0] pmt2vrf_rd_index=0;
  reg [3:0] rt2vrf_wr_valid=0;
  reg [723:0] rt2vrf_wr_data=0;
  wire [767:0] original_dp,converted_dp;
  wire [127:0] original_v0,converted_v0,original_pmt,converted_pmt;
  wire [4095:0] original_regs,converted_regs;
  original_vrf original(.clk,.rst_n,.dp2vrf_rd_index,.vrf2dp_rd_data(original_dp),.vrf2dp_v0_data(original_v0),.pmt2vrf_rd_index,.vrf2pmt_rd_data(original_pmt),.rt2vrf_wr_valid,.rt2vrf_wr_data,.vrf_data(original_regs));
  rvv_backend_vrf converted(.clk,.rst_n,.dp2vrf_rd_index,.vrf2dp_rd_data(converted_dp),.vrf2dp_v0_data(converted_v0),.pmt2vrf_rd_index,.vrf2pmt_rd_data(converted_pmt),.rt2vrf_wr_valid,.rt2vrf_wr_data,.vrf_data(converted_regs));
  reg [127:0] expected[0:31];
  reg [7:0] merged;
  reg touched;
  reg [127:0] data;
  reg [15:0] mask;
  integer index,checks=0,fd;
  task require(input bit ok,input string what);
    if(!ok)$fatal(1,"VRF %s",what);checks++;
  endtask
  always #5 clk=~clk;
  initial begin
    for(int r=0;r<32;r++)expected[r]=0;
    for(int n=0;n<5000;n++)begin
      @(negedge clk);rst_n=n!=0 && n!=1024 && n!=4000;
      rt2vrf_wr_valid=n<512 ? 4'b1111 : 4'($urandom);
      for(int p=0;p<4;p++)begin
        index=n<512 || n%7==0 ? n%32 : ($urandom%32);
        data={$urandom,$urandom,$urandom,$urandom};
        mask=n<512 ? 16'd1<<(n/32) : 16'($urandom);
        rt2vrf_wr_data[p*181+:181]={32'($urandom),5'(index),data,mask};
      end
      for(int p=0;p<6;p++)dp2vrf_rd_index[p*5+:5]=5'(n<512 ? n%32 : $urandom%32);
      pmt2vrf_rd_index=5'($urandom%32);
      @(posedge clk);
      for(int r=0;r<32;r++)for(int b=0;b<16;b++)begin
        merged=0;touched=0;
        for(int p=0;p<4;p++)begin
          if(rt2vrf_wr_valid[p] && rt2vrf_wr_data[p*181+144+:5]==r && rt2vrf_wr_data[p*181+b])begin
            merged=merged | rt2vrf_wr_data[p*181+16+b*8+:8];touched=1;
          end
        end
        if(!rst_n)expected[r][b*8+:8]=0;
        else if(touched)expected[r][b*8+:8]=merged;
      end
      #1;
      require(original_regs===converted_regs,"all registers differential");
      require(original_dp===converted_dp && original_pmt===converted_pmt && original_v0===converted_v0,"all read ports differential");
      for(int r=0;r<32;r++)require(converted_regs[r*128+:128]===expected[r],"independent byte/OR/reset model");
      for(int p=0;p<6;p++)require(converted_dp[p*128+:128]===expected[dp2vrf_rd_index[p*5+:5]],"dispatch read index");
      require(converted_pmt===expected[pmt2vrf_rd_index] && converted_v0===expected[0],"permutation/v0 read");
    end
    fd=$fopen("vrf-result.json","w");$fwrite(fd,"{\"status\":\"PASS\",\"cycles\":5000,\"checks\":%0d}\n",checks);$fclose(fd);
    $display("T24_VRF_EQUIVALENCE_PASS checks=%0d",checks);$finish;
  end
endmodule
