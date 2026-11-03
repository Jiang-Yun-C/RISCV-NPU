// Copyright 2026 Google LLC; modifications 2026 NexusRV contributors.
// SPDX-License-Identifier: Apache-2.0
// Mode-0/manual-CS AXI adaptation of Coral SpiMasterCtrl (SpiMaster.scala).
// Retains the setup/shift/finish machine, MSB-first edges and divider. Single
// transaction adapter and 16-byte RX FIFO replace TL-UL; one clock domain.
module t18_spi #(parameter EXPOSE_BOOT_STATUS=0)(input logic clk,reset,miso,input logic [31:0] card_generation,
              input logic ddr_ready,output logic sck,cs_n,mosi,
              output logic [31:0] model_ready,boot_error,boot_done,selftest,directory_count,
              output logic model_ready_one,
              axi4_if.slave bus);
    logic aw_pending;logic [31:0] aw_address;logic [1:0] aw_error;
    logic [7:0] tx_shift,rx_shift,rx_byte;logic busy;
    logic [15:0] divider,timer;
    integer state,bit_count;
    logic [9:0] stream_left;
    logic streaming;
    logic [7:0] fifo[0:15];
    integer fifo_count,rd_ptr,wr_ptr;
    wire fifo_pop=bus.arvalid&&bus.arready&&bus.arlen==0&&bus.arsize==2
                  &&bus.araddr[1:0]==0&&bus.araddr[7:0]==8'h3c;
    wire fifo_push=busy&&timer==0&&state==3&&streaming;
    wire take_aw=bus.awvalid&&bus.awready;
    wire take_w=bus.wvalid&&bus.wready;
    wire take_ar=bus.arvalid&&bus.arready;
    wire good_write=take_w&&aw_error==0&&bus.wstrb==15&&bus.wlast;
    wire manual_start=good_write&&aw_address[7:0]==8'h08;
    wire stream_start=!busy&&stream_left!=0&&(fifo_count<16||fifo_pop);
    wire start_byte=stream_start||manual_start;
    wire finish_byte=busy&&timer==0&&state==3;
    wire sample_bit=busy&&timer==0&&state==1;
    wire shift_bit=busy&&timer==0&&state==2&&bit_count!=0;
    wire set_stream=good_write&&aw_address[7:0]==8'h38&&!busy&&stream_left==0
                    &&fifo_count==0&&bus.wdata>0&&bus.wdata<=514;
    wire read_known=bus.araddr[7:0]==8'h00||bus.araddr[7:0]==8'h04||bus.araddr[7:0]==8'h0c
                    ||bus.araddr[7:0]==8'h24||bus.araddr[7:0]==8'h34||bus.araddr[7:0]==8'h3c
                    ||(EXPOSE_BOOT_STATUS&&(bus.araddr[7:0]==8'h18||bus.araddr[7:0]==8'h1c
                    ||bus.araddr[7:0]==8'h20||bus.araddr[7:0]==8'h28||bus.araddr[7:0]==8'h2c));
    assign mosi=busy?tx_shift[7]:1'b1;
    assign bus.awready=!reset&&!aw_pending&&!bus.bvalid;
    assign bus.wready=!reset&&aw_pending&&!bus.bvalid&&!(aw_address[7:0]==8&&busy);
    assign bus.arready=!reset&&!bus.rvalid&&(bus.araddr[7:0]!=8'h3c||fifo_count!=0);
    assign bus.bid=0;assign bus.rid=0;assign bus.rlast=1;
    always @(posedge clk)begin
        if(reset)begin
            aw_pending<=0;aw_address<=0;aw_error<=0;bus.bvalid<=0;bus.bresp<=0;
            bus.rvalid<=0;bus.rdata<=0;bus.rresp<=0;
            sck<=0;cs_n<=1;busy<=0;state<=0;timer<=0;divider<=249;
            bit_count<=7;tx_shift<=255;rx_shift<=0;rx_byte<=255;
            model_ready<=0;model_ready_one<=0;boot_error<=0;boot_done<=0;selftest<=0;directory_count<=0;
            stream_left<=0;streaming<=0;fifo_count<=0;rd_ptr<=0;wr_ptr<=0;
        end else begin
            if(take_w)aw_pending<=0;else if(take_aw)aw_pending<=1;
            if(take_w)bus.bvalid<=1;else if(bus.bvalid&&bus.bready)bus.bvalid<=0;
            if(take_ar)bus.rvalid<=1;else if(bus.rvalid&&bus.rready)bus.rvalid<=0;
            if(take_aw)begin
                aw_address<=bus.awaddr;
                aw_error<=(bus.awlen!=0||bus.awsize!=2||bus.awaddr[1:0]!=0)?2:0;
            end
            if(take_w)begin
                bus.bresp<=aw_error;
                if(bus.wstrb!=15||!bus.wlast)bus.bresp<=2;
                else if(aw_error==0)case(aw_address[7:0])
                    8'h04:if(!busy)divider<=bus.wdata[15:0];else bus.bresp<=2;
                    8'h08: ; // start_byte performs the state update below
                    8'h10:if(!busy)cs_n<=bus.wdata[0];else bus.bresp<=2;
                    // Publish the seal predicate with its source register,
                    // without a 32-bit compare in the isolation/abort path.
                    // Logical equality preserves the original X/Z behavior.
                    8'h18:begin model_ready<=bus.wdata;model_ready_one<=(bus.wdata==32'd1);end
                    8'h1c:boot_error<=bus.wdata;
                    8'h20:boot_done<=bus.wdata;
                    8'h28:selftest<=bus.wdata;
                    8'h2c:directory_count<=bus.wdata;
                    8'h38:if(!set_stream)bus.bresp<=2;
                    default:bus.bresp<=3;
                endcase
            end
            if(take_ar)begin
                bus.rresp<=bus.arlen!=0||bus.arsize!=2||bus.araddr[1:0]!=0?2'd2:read_known?2'd0:2'd3;
                bus.rdata<=0;
                if(bus.arlen==0&&bus.arsize==2&&bus.araddr[1:0]==0)case(bus.araddr[7:0])
                    8'h00:bus.rdata<={31'b0,busy};
                    8'h04:bus.rdata<={16'b0,divider};
                    8'h0c:bus.rdata<={24'b0,rx_byte};
                    8'h18:if(EXPOSE_BOOT_STATUS)bus.rdata<=model_ready;
                    8'h1c:if(EXPOSE_BOOT_STATUS)bus.rdata<=boot_error;
                    8'h20:if(EXPOSE_BOOT_STATUS)bus.rdata<=boot_done;
                    8'h28:if(EXPOSE_BOOT_STATUS)bus.rdata<=selftest;
                    8'h2c:if(EXPOSE_BOOT_STATUS)bus.rdata<=directory_count;
                    8'h24:bus.rdata<=card_generation;
                    8'h34:bus.rdata<={31'b0,ddr_ready};
                    8'h3c:bus.rdata<={24'b0,fifo[rd_ptr]};
                    default: ;
                endcase
            end
            // Preserve the stream launch priority over a simultaneous manual
            // TX write; its AXI response still acknowledges the write as before.
            if(start_byte)begin
                tx_shift<=stream_start?8'hff:bus.wdata[7:0];rx_shift<=0;
                busy<=1;state<=1;timer<=divider;bit_count<=7;
            end else begin
                if(finish_byte)busy<=0;
                if(sample_bit)rx_shift<={rx_shift[6:0],miso};
                if(shift_bit)begin bit_count<=bit_count-1;tx_shift<={tx_shift[6:0],1'b1};end
                if(busy)begin
                    timer<=timer!=0?timer-1'b1:divider;
                    if(timer==0)case(state)
                        1:begin sck<=1;state<=2;end
                        2:begin sck<=0;state<=bit_count==0?3:1;end
                        3:begin rx_byte<=rx_shift;state<=0;end
                        default:state<=0;
                    endcase
                end
            end
            if(stream_start)begin streaming<=1;stream_left<=stream_left-1'b1;end
            else begin
                if(finish_byte&&streaming)streaming<=0;
                if(set_stream)stream_left<=bus.wdata[9:0];
            end
            // Read and receive events update FIFO storage/count exactly once.
            if(fifo_pop)rd_ptr<=(rd_ptr+1)%16;
            if(fifo_push)begin fifo[wr_ptr]<=rx_shift;wr_ptr<=(wr_ptr+1)%16;end
            case({fifo_push,fifo_pop})
                2'b10:fifo_count<=fifo_count+1;
                2'b01:fifo_count<=fifo_count-1;
                default: ;
            endcase

        end
    end
endmodule
