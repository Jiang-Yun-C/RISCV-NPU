`timescale 1ns/1ps
module tb_sram_equivalence;
  reg clock=0,enable=0,write=0;
  reg [8:0] addr=0;
  reg [127:0] wdata=0;
  reg [15:0] wmask=0;
  wire [127:0] original_data,merged_data;
  wire original_valid,merged_valid;
  reg [127:0] model[0:511];
  reg [8:0] model_addr;
  integer checks=0,cycles=0,seed=24;
  Sram #(.NUM_ENTRIES(512)) original(clock,enable,write,addr,wdata,wmask,original_data,original_valid);
  Sram_merged merged(clock,enable,write,addr,wdata,wmask,merged_data,merged_valid);
  always #5 clock=~clock;
  task step;
    begin
      @(posedge clock);
      if(enable && write)
        for(integer b=0;b<16;b=b+1)
          if(wmask[b]) model[addr][8*b+:8]=wdata[8*b+:8];
      if(enable && !write) model_addr=addr;
      #1;
      if(original_valid !== enable || merged_valid !== enable)
        $fatal(1,"SRAM valid mismatch cycle=%0d",cycles);
      checks=checks+2;
      for(integer b=0;b<16;b=b+1) begin
        if(original_data[8*b+:8] !== merged_data[8*b+:8] ||
           original_data[8*b+:8] !== model[model_addr][8*b+:8])
          $fatal(1,"SRAM byte mismatch cycle=%0d byte=%0d read_addr=%0d",cycles,b,model_addr);
        checks=checks+2;
      end
      cycles=cycles+1;
      @(negedge clock);
    end
  endtask
  initial begin
    @(negedge clock);
    // Read-before-write preserves unknown bytes. Then populate every word.
    enable=1;write=0;addr=0;step();
    for(integer word=0;word<512;word=word+1) begin
      enable=1;write=1;addr=word;wmask=16'hffff;
      wdata={4{32'h10203040^word}};step();
      write=0;step();
    end
    // Isolated bytes, no-op mask, same-address read/write and held read address.
    for(integer word=0;word<512;word=word+1)
      for(integer b=0;b<16;b=b+1) begin
        enable=1;write=0;addr=word;step();
        write=1;wmask=16'h0001<<b;wdata={4{32'hb1c2d3e4^(word*16+b)}};step();
        wmask=0;wdata=~wdata;step();
        enable=0;wmask=16'hffff;step();
      end
    for(integer i=0;i<5000;i=i+1) begin
      enable=$random(seed);write=$random(seed);addr=$random(seed);
      wmask=$random(seed);wdata={$random(seed),$random(seed),$random(seed),$random(seed)};
      step();
    end
    $display("SRAM_EQ_PASS cycles=%0d checks=%0d",cycles,checks);
    $finish;
  end
endmodule
