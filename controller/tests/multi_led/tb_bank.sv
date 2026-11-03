`timescale 1ns/1ps
// The production AXI local peripheral and the actual physical-top display mux.
// No replacement register bank, prerecorded response or vendor board model.
module tb_bank #(parameter bit FAST=1);
  logic clk=0,reset_n=0;
  always #5 clk=~clk;
  axi4_if #(.DATA_W(32),.ID_W(1)) ib(clk);
  axi4_if #(.DATA_W(32),.ID_W(1)) db(clk);
  axi4_if #(.DATA_W(128),.ID_W(6)) nb(clk);
  // Separate procedural stimulus from the interface nets.
  logic [31:0] drive_awaddr; assign db.awaddr=drive_awaddr;
  logic drive_awid; assign db.awid=drive_awid;
  logic [7:0] drive_awlen; assign db.awlen=drive_awlen;
  logic [2:0] drive_awsize; assign db.awsize=drive_awsize;
  logic [1:0] drive_awburst; assign db.awburst=drive_awburst;
  logic drive_awvalid; assign db.awvalid=drive_awvalid;
  logic [31:0] drive_wdata; assign db.wdata=drive_wdata;
  logic [3:0] drive_wstrb; assign db.wstrb=drive_wstrb;
  logic drive_wlast; assign db.wlast=drive_wlast;
  logic drive_wvalid; assign db.wvalid=drive_wvalid;
  logic drive_bready; assign db.bready=drive_bready;
  logic [31:0] drive_araddr; assign db.araddr=drive_araddr;
  logic drive_arid; assign db.arid=drive_arid;
  logic [7:0] drive_arlen; assign db.arlen=drive_arlen;
  logic [2:0] drive_arsize; assign db.arsize=drive_arsize;
  logic [1:0] drive_arburst; assign db.arburst=drive_arburst;
  logic drive_arvalid; assign db.arvalid=drive_arvalid;
  logic drive_rready; assign db.rready=drive_rready;
  wire led0;
  wire [7:0] user_led_mask,user_led_value;
  wire uart_tx,model_sealed,platform_reset_request,exited;
  wire [31:0] rom_data,selected_profile,exit_code,report_tag;
  nx_ce64_local #(.UART_DIVISOR(4),.PRELOAD_MODE(1),.LOCAL_READ_PIPELINE(FAST)) dut(
    .clk,.reset_n,.ddr_init_done(1'b1),.uart_rx(1'b1),.platform_ready(1'b1),
    .platform_status(32'h12345678),.telemetry(4096'b0),.uart_tx,.led0,
    .user_led_mask,.user_led_value,.rom_enable(1'b0),.rom_address(32'b0),.rom_data,
    .model_sealed,.selected_profile,.platform_reset_request,.exit_code,.report_tag,.exited,
    .local_i(ib),.local_d(db),.local_n(nb));
  logic error_status=1,heartbeat_status=0,bist_status=1;
  wire error_pin,heartbeat_pin,bist_pin;
  nx_led_display_override display_mux(
    .owned(user_led_mask),.value(user_led_value),.error_status,.heartbeat_status,.bist_status,
    .error_pin,.heartbeat_pin,.bist_pin);
  logic [7:0] expected_mask=8'h01,expected_value=0;
  int writes=0,reads=0,negative_writes=0,pin_checks=0,stall_checks=0;
  bit held_b=0,held_r=0;
  logic [1:0] prior_b;
  logic [34:0] prior_r;
  always @(posedge clk)begin
    if(reset_n)begin
      if(held_b)begin
        if(!db.bvalid||db.bresp!==prior_b)$fatal(1,"B changed under backpressure");
        stall_checks++;
      end
      if(held_r)begin
        if(!db.rvalid||{db.rlast,db.rresp,db.rdata}!==prior_r)$fatal(1,"R changed under backpressure");
        stall_checks++;
      end
      held_b=db.bvalid&&!drive_bready;prior_b=db.bresp;
      held_r=db.rvalid&&!drive_rready;prior_r={db.rlast,db.rresp,db.rdata};
      if(((user_led_mask&8'hd2)!=0)||((user_led_value&8'hd2)!=0))$fatal(1,"unsupported LED bit changed");
    end else begin held_b=0;held_r=0;end
  end
  task automatic check_bank;
    if(user_led_mask!==expected_mask||user_led_value!==expected_value)
      $fatal(1,"bank mismatch mask=%x/%x value=%x/%x",user_led_mask,expected_mask,user_led_value,expected_value);
    if(led0!==(expected_mask[0]&&expected_value[0]))$fatal(1,"legacy LED0 mismatch");
  endtask
  task automatic check_pins;
    // Every independent automatic-state combination remains meaningful while
    // owned pins are overridden. Releasing a pin must expose its live status.
    for(int a=0;a<8;a++)begin
      {error_status,heartbeat_status,bist_status}=3'(a);#1;
      if(error_pin!==(expected_mask[2]?expected_value[2]:error_status)||
         heartbeat_pin!==(expected_mask[3]?expected_value[3]:heartbeat_status)||
         bist_pin!==(expected_mask[5]?expected_value[5]:bist_status))$fatal(1,"display ownership routing");
      pin_checks++;
    end
  endtask
  task automatic write_d(input logic [31:0] address,data,
      input logic [1:0] response,input logic [7:0] after_mask,after_value,
      input int ordering=0,input logic [3:0] strobes=15,input logic [2:0] size=2,
      input logic [7:0] length=0,input bit last=1);
    bit awdone,wdone;int age;
    logic [7:0] before_mask,before_value;
    awdone=0;wdone=0;age=0;before_mask=expected_mask;before_value=expected_value;
    @(negedge clk);drive_awaddr=address;drive_awsize=size;drive_awlen=length;drive_awvalid=ordering!=1;
    drive_wdata=data;drive_wstrb=strobes;drive_wlast=last;drive_wvalid=ordering!=2;drive_bready=0;
    while(!awdone||!wdone)begin
      @(posedge clk);
      if(drive_awvalid&&db.awready)awdone=1;
      if(drive_wvalid&&db.wready)wdone=1;
      @(negedge clk);age++;
      if(user_led_mask!==before_mask||user_led_value!==before_value)$fatal(1,"bank changed before complete AW/W");
      drive_awvalid=!awdone&&(ordering!=1||age>=3);
      drive_wvalid=!wdone&&(ordering!=2||age>=3);
      if(age>100)$fatal(1,"AW/W timeout");
    end
    while(!db.bvalid)begin @(negedge clk);age++;if(age>120)$fatal(1,"B timeout");end
    if(db.bresp!==response)$fatal(1,"wrong B response address=%x got=%x expected=%x",address,db.bresp,response);
    expected_mask=after_mask;expected_value=after_value;check_bank();
    repeat(4)begin @(negedge clk);check_bank();end
    drive_bready=1;@(posedge clk);@(negedge clk);drive_bready=0;
    writes++;if(response!=0)negative_writes++;
  endtask
  task automatic good_apply(input logic [7:0] mask,value,input int ordering=0);
    logic [7:0] next_mask,next_value;
    next_mask=expected_mask|mask;next_value=(expected_value&~mask)|value;
    write_d(32'h10000418,{16'b0,mask,value},0,next_mask,next_value,ordering);
  endtask
  task automatic good_release(input logic [7:0] mask,input int ordering=0);
    write_d(32'h1000041c,{24'b0,mask},0,expected_mask&~mask,expected_value&~mask,ordering);
  endtask
  task automatic bad_write(input logic [31:0] address,data,
      input logic [3:0] strobes=15,input logic [2:0] size=2,input logic [7:0] length=0,input bit last=1);
    write_d(address,data,3,expected_mask,expected_value,writes%3,strobes,size,length,last);
  endtask
  task automatic read_d(input logic [31:0] address,want,input logic [1:0] response=0,
      input logic [2:0] size=2,input logic [7:0] length=0);
    int age;age=0;
    @(negedge clk);drive_araddr=address;drive_arlen=length;drive_arsize=size;drive_arvalid=1;drive_rready=0;
    do begin @(posedge clk);age++;if(age>100)$fatal(1,"AR timeout");end while(!db.arready);
    @(negedge clk);drive_arvalid=0;
    for(int beat=0;beat<=int'(length);beat++)begin
      while(!db.rvalid)begin @(negedge clk);age++;if(age>200)$fatal(1,"R timeout");end
      if(db.rresp!==response||db.rlast!==(beat==int'(length)))$fatal(1,"bad read response/framing");
      if(response==0&&db.rdata!==want)$fatal(1,"bad read data address=%x got=%x expected=%x",address,db.rdata,want);
      repeat(3)@(negedge clk);
      drive_rready=1;@(posedge clk);@(negedge clk);drive_rready=0;reads++;
    end
    check_bank();
  endtask
  task automatic held_read_then_update;
    logic [31:0] held;
    @(negedge clk);drive_araddr=32'h10000410;drive_arlen=0;drive_arsize=2;drive_arvalid=1;drive_rready=0;
    do @(posedge clk);while(!db.arready);
    @(negedge clk);drive_arvalid=0;while(!db.rvalid)@(negedge clk);
    held=db.rdata;
    good_apply(8'h2d,8'h24,2);
    if(db.rdata!==held||!db.rvalid)$fatal(1,"atomic update changed held readback");
    drive_rready=1;@(posedge clk);@(negedge clk);drive_rready=0;reads++;
    read_d(32'h10000410,{24'b0,expected_value});
  endtask
  assign ib.awaddr=0;assign ib.awid=0;assign ib.awlen=0;assign ib.awsize=2;assign ib.awburst=1;assign ib.awvalid=0;
  assign ib.wdata=0;assign ib.wstrb=0;assign ib.wlast=1;assign ib.wvalid=0;assign ib.bready=1;
  assign ib.araddr=0;assign ib.arid=0;assign ib.arlen=0;assign ib.arsize=2;assign ib.arburst=1;assign ib.arvalid=0;assign ib.rready=1;
  assign nb.awaddr=0;assign nb.awid=0;assign nb.awlen=0;assign nb.awsize=4;assign nb.awburst=1;assign nb.awvalid=0;
  assign nb.wdata=0;assign nb.wstrb=0;assign nb.wlast=1;assign nb.wvalid=0;assign nb.bready=1;
  assign nb.araddr=0;assign nb.arid=0;assign nb.arlen=0;assign nb.arsize=4;assign nb.arburst=1;assign nb.arvalid=0;assign nb.rready=1;
  initial begin
    // Drive the active AXI master after elaboration, before the first clock.
    // Keep interface instance state independent of static initial values.
    #1;
    drive_awaddr=0;drive_awid=0;drive_awlen=0;drive_awsize=2;drive_awburst=1;drive_awvalid=0;
    drive_wdata=0;drive_wstrb=0;drive_wlast=1;drive_wvalid=0;drive_bready=0;
    drive_araddr=0;drive_arid=0;drive_arlen=0;drive_arsize=2;drive_arburst=1;drive_arvalid=0;drive_rready=0;
    repeat(4)@(negedge clk);reset_n=1;repeat(2)@(negedge clk);check_bank();check_pins();
    read_d(32'h10000400,32'h3144454c);read_d(32'h10000408,32'h3244454c);
    read_d(32'h1000040c,32'h2d);read_d(32'h10000410,0);read_d(32'h10000414,1);
    read_d(32'h100000d0,32'h12345678);read_d(32'h100000e8,0);
    write_d(32'h10000404,1,0,1,1,1);read_d(32'h10000404,1);
    good_apply(8'h2d,8'h2d,2);check_pins();
    good_apply(8'h04,0);check_pins();
    good_apply(8'h21,8'h01,1);check_pins();
    good_release(8'h0c,2);check_pins();
    good_release(8'h2d);read_d(32'h10000404,0);check_pins();
    write_d(32'h10000404,1,0,1,1);read_d(32'h10000414,1);
    good_apply(8'h2c,8'h28);
    write_d(32'h10000404,0,0,expected_mask,expected_value&8'hfe,2);
    // All 80 nonempty-mask/value combinations over the four real channels.
    for(int m=1;m<256;m++)if((m&~32'h2d)==0)begin
      for(int v=0;v<256;v++)if((v&~m)==0)begin
        good_release(8'h2d);
        good_apply(8'(m),8'(v),writes%3);check_pins();
      end
    end
    held_read_then_update();
    // Every unsupported/empty selection must leave both registers untouched.
    for(int m=0;m<256;m++)if(m==0||(m&~32'h2d)!=0)begin
      bad_write(32'h10000418,{16'b0,8'(m),8'(m)});
      bad_write(32'h1000041c,32'(m));
    end
    bad_write(32'h10000418,32'h00000104); // value outside selected mask
    bad_write(32'h10000418,32'h00010101); // high reserved bits
    bad_write(32'h1000041c,32'h00000101); // high reserved bits
    bad_write(32'h10000404,2);
    foreach_bad_format: for(int i=0;i<3;i++)begin
      logic [31:0] address,data;
      address=i==0?32'h10000404:i==1?32'h10000418:32'h1000041c;
      data=i==0?1:i==1?32'h00000101:1;
      bad_write(address,data,7);bad_write(address,data,15,1);
      bad_write(address,data,15,2,1);bad_write(address,data,15,2,0,0);
      for(int lane=1;lane<4;lane++)bad_write(address+32'(lane),data);
    end
    for(int offset=0;offset<24;offset+=4)if(offset!=4)bad_write(32'h10000400+32'(offset),1);
    read_d(32'h10000418,0,3);read_d(32'h1000041c,0,3);
    read_d(32'h10000409,0,3);read_d(32'h10000410,0,3,1);
    read_d(32'h10000410,0,3,2,1);
    // Reset releases status pins, clears every value, and keeps legacy LED0 off.
    @(negedge clk);reset_n=0;repeat(3)@(negedge clk);
    expected_mask=1;expected_value=0;check_bank();reset_n=1;check_pins();
    read_d(32'h10000410,0);read_d(32'h10000414,1);
    $display("RESULT {\"status\":\"PASS\",\"fast\":%0d,\"writes\":%0d,\"negative_writes\":%0d,\"read_beats\":%0d,\"pin_checks\":%0d,\"stall_checks\":%0d}",FAST,writes,negative_writes,reads,pin_checks,stall_checks);
    $finish;
  end
  initial begin #1000000;$fatal(1,"test timeout");end
endmodule
