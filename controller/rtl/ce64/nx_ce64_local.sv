// Board-local 64KiB ROM + 64KiB SRAM + UART/loader seal + report transport.
// ROM initialization is bound to the new ELF. No reset clears data arrays.
module nx_ce64_local #(
  parameter ROM_FILE="", UART_DIVISOR=125, PRELOAD_MODE=0, PROFILE_HEAD=0,
  parameter bit LOCAL_READ_PIPELINE=1, REQUEST_PMU=1
)(
  input logic clk,reset_n,ddr_init_done,uart_rx,platform_ready,
  input logic [31:0] platform_status,
  input wire [4095:0] telemetry,
  output wire uart_tx,
  output wire uart_interrupt,timer_interrupt,
  output wire [63:0] debug_observe,
  output wire led0,
  output logic [7:0] user_led_mask,user_led_value,
  input logic rom_enable,
  input logic [31:0] rom_address,
  output logic [31:0] rom_data,
  output logic model_sealed,
  output wire [31:0] selected_profile,
  output logic platform_reset_request,
  output logic [31:0] exit_code,report_tag,
  output logic exited,
  axi4_if.slave local_i,local_d,local_n
);
  logic [31:0] rom [0:16383];
  logic [31:0] ram [0:16383];
  initial begin
    if(ROM_FILE!="")$readmemh(ROM_FILE,rom);
`ifndef SYNTHESIS
    else begin
      string path;
      if($value$plusargs("ce_rom=%s",path))$readmemh(path,rom);
    end
`endif
  end
  // Keep the original visible synchronous read/hold behavior while the ROM
  // port reads every clock. Only a known-true request selects the new word;
  // X/Z enable retains the old visible value just like procedural if.
  // These registers intentionally have no reset, matching the original ROM.
  logic [31:0] rom_word,rom_hold;
  logic rom_read_taken;
  always_ff @(posedge clk)begin
    rom_word<=rom[rom_address[15:2]];
    rom_hold<=rom_data;
    rom_read_taken<=1'b0;
    if(rom_enable)rom_read_taken<=1'b1;
  end
  always_comb rom_data=rom_read_taken ? rom_word : rom_hold;
  // The normal fabric arbitrates I/D, but each local read port independently
  // retains its response until handshake. ROM is read-only on both ports.
  logic iar;
  logic [31:0] ia;
  logic [7:0] il,ib;
  logic [2:0] isize;
  logic [31:0] iq;
  logic [31:0] i_rom_q,i_ram_q;
  assign local_i.awready=0;assign local_i.wready=0;
  assign local_i.bid=0;assign local_i.bvalid=0;assign local_i.bresp=3;
  generate if(LOCAL_READ_PIPELINE)begin:fast_i
    // One synchronous RAM read register is also the elastic R response slot.
    // An accepted AR launches the read on that edge. A consumed non-last beat
    // launches its successor; while RREADY is low neither data nor address moves.
    wire accept=local_i.arvalid&&local_i.arready;
    wire advance=local_i.rvalid&&local_i.rready&&ib!=il;
    wire issue=accept||advance;
    wire [31:0] address=accept ? local_i.araddr : ia+32'd4;
    assign local_i.arready=!iar&&!local_i.rvalid;
    assign local_i.rdata=ia>=32'h10000&&ia<32'h20000 ? i_rom_q :
                         ia>=32'h20000&&ia<32'h30000 ? i_ram_q : 0;
    always_ff @(posedge clk)begin
      if(issue)begin i_rom_q<=rom[address[15:2]];i_ram_q<=ram[address[15:2]];end
    end
    always_ff @(posedge clk or negedge reset_n)begin
      if(!reset_n)begin
        iar<=0;ia<=0;il<=0;ib<=0;isize<=0;
        local_i.rvalid<=0;local_i.rresp<=0;local_i.rid<=0;local_i.rlast<=0;
      end else begin
        if(local_i.rvalid&&local_i.rready)begin
          if(ib==il)begin iar<=0;local_i.rvalid<=0;end
          else begin
            ia<=address;ib<=ib+1'b1;local_i.rlast<=ib+8'd1==il;
            local_i.rresp<=(address>=32'h10000&&address<32'h30000&&isize==2)?0:3;
          end
        end
        if(accept)begin
          iar<=1;ia<=local_i.araddr;il<=local_i.arlen;ib<=0;isize<=local_i.arsize;
          local_i.rvalid<=1;local_i.rlast<=local_i.arlen==0;
          local_i.rresp<=(local_i.araddr>=32'h10000&&local_i.araddr<32'h30000&&local_i.arsize==2)?0:3;
        end
      end
    end
  end else begin:legacy_i
  assign local_i.arready=!iar&&!local_i.rvalid;
  always_ff @(posedge clk)begin
    if(iar)begin
      i_rom_q<=rom[ia[15:2]];
      i_ram_q<=ram[ia[15:2]];
    end
  end
  always_comb iq=ia>=32'h10000&&ia<32'h20000 ? i_rom_q :
                 ia>=32'h20000&&ia<32'h30000 ? i_ram_q : 0;
  logic i_wait;
  always_ff @(posedge clk or negedge reset_n)begin
    if(!reset_n)begin iar<=0;ia<=0;il<=0;ib<=0;isize<=0;i_wait<=0;local_i.rvalid<=0;local_i.rdata<=0;local_i.rresp<=0;local_i.rid<=0;local_i.rlast<=0;end
    else begin
      if(local_i.arvalid&&local_i.arready)begin
        iar<=1;ia<=local_i.araddr;il<=local_i.arlen;ib<=0;isize<=local_i.arsize;i_wait<=1;
      end
      if(iar&&!local_i.rvalid)begin
        if(i_wait)i_wait<=0;
        else begin local_i.rvalid<=1;local_i.rdata<=iq;local_i.rid<=0;local_i.rlast<=ib==il;
          local_i.rresp<=(ia>=32'h10000&&ia<32'h30000&&isize==2) ? 0 : 3;end
      end
      if(local_i.rvalid&&local_i.rready)begin
        local_i.rvalid<=0;
        if(ib==il)iar<=0;
        else begin ia<=ia+4;ib<=ib+1'b1;i_wait<=1;end
      end
    end
  end
  end endgenerate
  axi4_if #(.DATA_W(32),.ID_W(1)) uart(clk);
  logic aw_have,w_have,aw_sent,w_sent,ar_have,ar_sent;
  logic [31:0] wa,wd,ra;
  logic [3:0] ws;
  logic [2:0] wsize,rsize;
  logic [7:0] rl,rb,led_wlen;
  logic led_wlast;
  // LED0/A20 plus the existing error, heartbeat and BIST display pins.
  // Other pins remain unavailable; the mask never grants access to them.
  localparam logic [7:0] USER_LED_CAPS=8'h2d;
  assign led0=user_led_mask[0]&&user_led_value[0];
  logic [31:0] rq,d_response_data;
  logic [31:0] d_rom_q,d_ram_q,io_q;
  // Separate the physical READ_FIRST RAM output from the visible read/hold
  // contract. The RAM can then use its native synchronous read/write port;
  // a write still leaves an already offered D response unchanged.
  logic [31:0] d_ram_word,d_ram_hold;
  logic d_ram_read_taken;
  logic [63:0] mtime,mtimecmp;
  logic uart_irq_enable;
  wire uart_pending;
  logic [31:0] software_event;
  assign uart_interrupt=uart_irq_enable&&uart_pending;
  assign timer_interrupt=mtime>=mtimecmp;
  wire [15:0] debug_events={2'b0,uart_pending,uart_interrupt,timer_interrupt,
    (aw_have&&w_have&&!local_d.bvalid&&wa==32'h10000418),
    (aw_have&&w_have&&!local_d.bvalid&&wa==32'h1000041c),
    (uart.arvalid&&uart.arready&&ra==32'h100000c0),wd[7:0]};
  assign debug_observe={debug_events,user_led_mask,user_led_value,software_event};
  logic [31:0] profile_head;
  assign selected_profile=profile_head;
  logic read_wait;
  logic is_uart_write,is_uart_read;
  logic packet_busy;
  assign is_uart_write=wa==32'h10000000||wa==32'h100000c8;
  assign is_uart_read=ra==32'h10000004 || ra==32'h100000c0;
  assign uart.awaddr=wa==32'h100000c8 ? 32'h10000018 : wa;assign uart.awid=0;assign uart.awlen=0;assign uart.awsize=wsize;assign uart.awburst=1;
  assign uart.awvalid=aw_have&&w_have&&is_uart_write&&!aw_sent&&!packet_busy;
  assign uart.wdata=wd;assign uart.wstrb=ws;assign uart.wlast=1;
  assign uart.wvalid=aw_have&&w_have&&is_uart_write&&!w_sent;
  assign uart.bready=aw_have&&w_have&&is_uart_write&&aw_sent&&w_sent&&!local_d.bvalid;
  assign uart.araddr=ra==32'h100000c0 ? 32'h10000008 : ra;assign uart.arid=0;assign uart.arlen=0;assign uart.arsize=rsize;assign uart.arburst=1;
  assign uart.arvalid=ar_have&&is_uart_read&&!ar_sent;
  assign uart.rready=ar_have&&is_uart_read&&ar_sent&&!local_d.rvalid;
  logic [31:0] uart_fault,app_signature,app_data_signature,source_mode;
  wire uart_serial;
  t17_uart #(.DIVISOR(UART_DIVISOR)) uart_device(.clk,.reset(!reset_n),.rx(uart_rx),
    .boot_mode(32'(PRELOAD_MODE)),.preload_bytes(32'b0),.tx(uart_serial),.rx_pending(uart_pending),.app_signature,
    .app_data_signature,.source_mode,.fault_code(uart_fault),.bus(uart));
  // Reports serialize through the same UART's actual TX register. A record
  // consists of magic, kind, tag/index, value and CRC32. Backpressure reaches
  // CPU B rather than dropping a record when transmission is busy.
  logic [159:0] packet;
  logic [4:0] packet_byte;
  logic [31:0] packet_crc;
  logic [3:0] crc_index;
  logic crc_done;
  logic tx_valid,tx_busy;
  logic [7:0] tx_data;
  wire report_serial;
  t03_uart_tx #(.DIVISOR(UART_DIVISOR)) report_tx(.clk,.reset(!reset_n),.valid(tx_valid),.data(tx_data),.busy(tx_busy),.tx(report_serial));
  assign uart_tx=packet_busy ? report_serial : uart_serial;
  assign tx_valid=packet_busy&&crc_done&&packet_byte<20&&!tx_busy;
  assign tx_data=packet[packet_byte*8+:8];
  function automatic logic [31:0] crc_byte(input logic [31:0] prior,input logic [7:0] data);
    logic [31:0] c;
    c=prior^data;
    for(integer j=0;j<8;j=j+1)c=(c>>1)^((c[0]) ? 32'hedb88320 : 0);
    return c;
  endfunction
  logic [127:0] new_record;
  logic [31:0] output_index;
  wire report_write=wa==32'h10000084 || wa==32'h1000008c || wa==32'h10000020;
  always_comb begin
    new_record={wd,wa==32'h1000008c ? output_index : report_tag,
                 wa==32'h1000008c ? 32'd1 : wa==32'h10000020 ? 32'd2 : 32'd0,32'h3245434e};
  end
  assign local_d.awready=!aw_have&&!local_d.bvalid;
  assign local_d.wready=!w_have&&!local_d.bvalid;
  assign local_d.arready=!ar_have&&!local_d.rvalid;
  wire d_ram_write=aw_have&&w_have&&!is_uart_write&&!local_d.bvalid&&wa>=32'h20000&&wa<32'h30000;
  wire d_ar_fire=local_d.arvalid&&local_d.arready;
  wire d_new_memory=local_d.araddr>=32'h10000&&local_d.araddr<32'h30000;
  wire d_memory=ra>=32'h10000&&ra<32'h30000;
  wire d_consume=local_d.rvalid&&local_d.rready;
  wire d_next=d_consume&&rb!=rl;
  // The data RAM has one D read/write port. A byte write wins that port; an
  // accepted read remains queued and is issued after the write. A stalled R
  // response owns d_ram_q until consumed, so writes never overwrite held data.
  wire d_fast_issue=LOCAL_READ_PIPELINE&&!d_ram_write&&d_fast_address>=32'h10000&&d_fast_address<32'h30000&&
      ((d_ar_fire&&d_new_memory)||(ar_have&&d_memory&&(!local_d.rvalid||d_next)));
  wire [31:0] d_fast_address=d_ar_fire ? local_d.araddr : d_next ? ra+(32'd1<<rsize) : ra;
  wire [13:0] d_ram_address=d_ram_write ? wa[15:2] :
      LOCAL_READ_PIPELINE ? d_fast_address[15:2] : ra[15:2];
  wire d_ram_read=LOCAL_READ_PIPELINE ? d_fast_issue&&d_fast_address>=32'h20000&&d_fast_address<32'h30000 :
      ar_have&&ra>=32'h20000&&ra<32'h30000;
  always_comb rq=ra>=32'h10000&&ra<32'h20000 ? d_rom_q :
                 ra>=32'h20000&&ra<32'h30000 ? d_ram_q : io_q;
  assign local_d.rdata=LOCAL_READ_PIPELINE&&ar_have&&d_memory ? rq : d_response_data;
  always_comb d_ram_q=d_ram_read_taken ? d_ram_word : d_ram_hold;
  always_ff @(posedge clk)begin
    d_ram_hold<=d_ram_q;
    d_ram_read_taken<=1'b0;
    if(LOCAL_READ_PIPELINE)begin
      if(d_fast_issue)d_rom_q<=rom[d_fast_address[15:2]];
    end else if(ar_have)d_rom_q<=rom[ra[15:2]];
    if(d_ram_write||d_ram_read)begin
      d_ram_word<=ram[d_ram_address];
      if(!LOCAL_READ_PIPELINE||!d_ram_write)d_ram_read_taken<=1'b1;
      if(d_ram_write)
        for(integer i=0;i<4;i=i+1)if(ws[i])ram[d_ram_address][8*i+:8]<=wd[8*i+:8];
    end
    if(ar_have&&!is_uart_read)begin
      if(ra>=32'h10000200&&ra<32'h10000400)io_q<=telemetry[ra[8:2]*32+:32];
      else case(ra)
        32'h100000c4:io_q<={31'b0,uart_irq_enable};
        32'h10000420:io_q<=software_event;
        32'h10000008:io_q<=mtime[31:0];
        32'h1000000c:io_q<=mtime[63:32];
        32'h10000010:io_q<=mtimecmp[31:0];
        32'h10000014:io_q<=mtimecmp[63:32];
        32'h10000400:io_q<=32'h3144454c; // LED1 ABI, read-only
        32'h10000404:io_q<={31'b0,led0};
        32'h10000408:io_q<=32'h3244454c; // LED2 bank ABI, read-only
        32'h1000040c:io_q<={24'b0,USER_LED_CAPS};
        32'h10000410:io_q<={24'b0,user_led_value};
        32'h10000414:io_q<={24'b0,user_led_mask};
        32'h100000d0:io_q<=platform_status;
        32'h100000e0:io_q<={30'b0,model_sealed,(ddr_init_done&&platform_ready)};
        32'h100000e4:io_q<=32'(PRELOAD_MODE);
        32'h100000e8:io_q<=profile_head;
        32'h100000b8:io_q<=REQUEST_PMU ? 32'h3152504e : 0;
        32'h100000bc:io_q<=REQUEST_PMU ? telemetry[2080+:32] : 0;
        default:io_q<=0;
      endcase
    end
  end
  always_ff @(posedge clk or negedge reset_n)begin
    if(!reset_n)begin
      aw_have<=0;w_have<=0;aw_sent<=0;w_sent<=0;ar_have<=0;ar_sent<=0;
      wa<=0;wd<=0;ra<=0;ws<=0;wsize<=0;rsize<=0;rl<=0;rb<=0;led_wlen<=0;led_wlast<=0;read_wait<=0;
      local_d.bvalid<=0;local_d.bresp<=0;local_d.bid<=0;
      local_d.rvalid<=0;local_d.rresp<=0;d_response_data<=0;local_d.rlast<=0;local_d.rid<=0;
      model_sealed<=PRELOAD_MODE!=0;exit_code<=0;exited<=0;report_tag<=0;output_index<=0;
      mtime<=0;mtimecmp<=64'hffffffffffffffff;uart_irq_enable<=0;software_event<=0;
      platform_reset_request<=0;profile_head<=PROFILE_HEAD;
      user_led_value<=0;user_led_mask<=8'h01;
      packet_busy<=0;packet<=0;packet_byte<=0;packet_crc<=32'hffffffff;crc_index<=0;crc_done<=0;
    end else begin
      mtime<=mtime+1'b1;
      if(packet_busy&&!crc_done)begin
        packet_crc<=crc_byte(packet_crc,packet[crc_index*8+:8]);
        if(crc_index==15)begin packet[128+:32]<=~crc_byte(packet_crc,packet[crc_index*8+:8]);crc_done<=1;end
        else crc_index<=crc_index+1'b1;
      end
      if(packet_busy&&tx_valid)begin
        if(packet_byte==19)packet_byte<=20;else packet_byte<=packet_byte+1'b1;
      end
      if(packet_busy&&packet_byte==20&&!tx_busy)begin packet_busy<=0;packet_byte<=0;end
      if(local_d.awvalid&&local_d.awready)begin aw_have<=1;wa<=local_d.awaddr;wsize<=local_d.awsize;led_wlen<=local_d.awlen;end
      if(local_d.wvalid&&local_d.wready)begin w_have<=1;wd<=local_d.wdata;ws<=local_d.wstrb;led_wlast<=local_d.wlast;end
      if(uart.awvalid&&uart.awready)aw_sent<=1;
      if(uart.wvalid&&uart.wready)w_sent<=1;
      if(local_d.bvalid&&local_d.bready)begin
        local_d.bvalid<=0;aw_have<=0;w_have<=0;aw_sent<=0;w_sent<=0;
      end
      if(aw_have&&w_have&&!local_d.bvalid)begin
        if(is_uart_write)begin
          if(uart.bvalid&&uart.bready)begin local_d.bvalid<=1;local_d.bresp<=uart.bresp;end
        end else if(!report_write || !packet_busy)begin
          local_d.bvalid<=1;local_d.bresp<=0;
          if(wa>=32'h20000&&wa<32'h30000)begin end
          else if(ws!=15||wsize!=2)local_d.bresp<=3;
          else case(wa)
            // The legacy LED0 write reacquires that display after RELEASE.
            32'h10000404:if(wd<=1&&led_wlen==0&&led_wlast)begin
              user_led_value[0]<=wd[0];user_led_mask[0]<=1'b1;
            end else local_d.bresp<=3;
            // Validate the entire operation before a single atomic update.
            // Read-only addresses and misaligned aliases hit default DECERR.
            32'h10000418:if(led_wlen==0&&led_wlast&&wd[31:16]==0&&
                wd[15:8]!=0&&(wd[15:8]&~USER_LED_CAPS)==0&&
                (wd[7:0]&~wd[15:8])==0)begin
              user_led_value<=(user_led_value&~wd[15:8])|wd[7:0];
              user_led_mask<=user_led_mask|wd[15:8];
            end else local_d.bresp<=3;
            32'h1000041c:if(led_wlen==0&&led_wlast&&wd[31:8]==0&&
                wd[7:0]!=0&&(wd[7:0]&~USER_LED_CAPS)==0)begin
              user_led_value<=user_led_value&~wd[7:0];
              user_led_mask<=user_led_mask&~wd[7:0];
            end else local_d.bresp<=3;
            32'h100000c4:if(wd<=1)uart_irq_enable<=wd[0];else local_d.bresp<=3;
            32'h10000420:software_event<=wd;
            32'h10000010:mtimecmp[31:0]<=wd;
            32'h10000014:mtimecmp[63:32]<=wd;
            32'h100000e0:if(wd==32'h5345414c)model_sealed<=1;else local_d.bresp<=3;
            32'h100000e8:if(wd<=3)profile_head<=wd;else local_d.bresp<=3;
            32'h100000ec:if(wd==32'h52535432)platform_reset_request<=1;else local_d.bresp<=3;
            32'h10000080:report_tag<=wd;
            32'h10000088:output_index<=wd;
            32'h10000084,32'h1000008c,32'h10000020:begin
              packet<={32'b0,new_record};packet_busy<=1;packet_byte<=0;
              packet_crc<=32'hffffffff;crc_index<=0;crc_done<=0;
              if(wa==32'h10000020)begin exited<=1;exit_code<=wd;end
            end
            32'h100000a0,32'h100000a4,32'h100000a8:;
            // Actual command application is observed at the successful B
            // handshake by the SoC PMU. Disabled PMU never accepts controls.
            32'h100000b0:if(!REQUEST_PMU)local_d.bresp<=3;
            32'h100000b4:if(!REQUEST_PMU||wd<1||wd>4)local_d.bresp<=3;
            default:local_d.bresp<=3;
          endcase
        end
      end
      if(local_d.arvalid&&local_d.arready)begin
        ar_have<=1;ar_sent<=0;ra<=local_d.araddr;rsize<=local_d.arsize;
        rl<=local_d.arlen;rb<=0;read_wait<=1;
      end
      if(uart.arvalid&&uart.arready)ar_sent<=1;
      if(LOCAL_READ_PIPELINE&&ar_have&&d_memory)begin
        if(d_consume)begin
          local_d.rvalid<=0;
          if(rb==rl)begin ar_have<=0;ar_sent<=0;end
          else begin ra<=ra+(32'd1<<rsize);rb<=rb+1'b1;read_wait<=1;end
        end
      end else begin
        if(ar_have&&!local_d.rvalid)begin
          if(d_ram_write)read_wait<=1;
          else if(is_uart_read)begin
            if(uart.rvalid&&uart.rready)begin local_d.rvalid<=1;d_response_data<=uart.rdata | (ra==32'h10000004 ? {31'b0,packet_busy} : 32'b0);local_d.rresp<=uart.rresp;local_d.rlast<=1;end
          end else if(read_wait)read_wait<=0;
          else begin local_d.rvalid<=1;d_response_data<=rq;local_d.rresp<=((ra>=32'h10000400&&ra<32'h10000420) ?
              ((ra==32'h10000400||ra==32'h10000404||ra==32'h10000408||ra==32'h1000040c||
                ra==32'h10000410||ra==32'h10000414)&&rsize==2&&rl==0) : rsize<=2) ? 0 : 3;local_d.rlast<=rb==rl;end
        end
        if(d_consume)begin
          local_d.rvalid<=0;
          if(rb==rl)begin ar_have<=0;ar_sent<=0;end
          else begin ra<=ra+(32'd1<<rsize);rb<=rb+1'b1;read_wait<=1;end
        end
      end
      if(d_fast_issue)begin
        local_d.rvalid<=1;
        local_d.rresp<=(d_ar_fire ? local_d.arsize : rsize)<=2 ? 0 : 3;
        local_d.rlast<=d_ar_fire ? local_d.arlen==0 : (d_next ? rb+8'd1 : rb)==rl;
      end
    end
  end
  // CE and platform BIST are DDR-only. A local N access is a framed DECERR.
  logic nread,nwrite;
  logic [7:0] nlen,nbeat,nwlen,nwbeat;
  assign local_n.arready=!nread&&!local_n.rvalid;
  assign local_n.awready=!nwrite&&!local_n.bvalid;
  assign local_n.wready=nwrite&&!local_n.bvalid;
  assign local_n.rdata=0;assign local_n.rid=0;assign local_n.rresp=3;
  assign local_n.bid=0;assign local_n.bresp=3;
  always_ff @(posedge clk or negedge reset_n)begin
    if(!reset_n)begin nread<=0;nwrite<=0;nlen<=0;nbeat<=0;nwlen<=0;nwbeat<=0;local_n.rvalid<=0;local_n.rlast<=0;local_n.bvalid<=0;end
    else begin
      if(local_n.arvalid&&local_n.arready)begin nread<=1;nlen<=local_n.arlen;nbeat<=0;end
      if(nread&&!local_n.rvalid)begin local_n.rvalid<=1;local_n.rlast<=nbeat==nlen;end
      if(local_n.rvalid&&local_n.rready)begin local_n.rvalid<=0;if(nbeat==nlen)nread<=0;else nbeat<=nbeat+1'b1;end
      if(local_n.awvalid&&local_n.awready)begin nwrite<=1;nwlen<=local_n.awlen;nwbeat<=0;end
      if(local_n.wvalid&&local_n.wready)begin
        if(nwbeat==nwlen)begin nwrite<=0;local_n.bvalid<=1;end else nwbeat<=nwbeat+1'b1;
      end
      if(local_n.bvalid&&local_n.bready)local_n.bvalid<=0;
    end
  end
endmodule
