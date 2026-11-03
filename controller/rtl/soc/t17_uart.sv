// Synthesizable 8N1 UART with RX FIFO and independent AXI address/data phases.
module t17_uart #(parameter integer DIVISOR=64, FIFO_DEPTH=64) (
    input logic clk, reset, rx, input logic [31:0] boot_mode, preload_bytes,
    output wire tx, output wire rx_pending, output logic [31:0] app_signature, app_data_signature, source_mode,
    output logic [31:0] fault_code,
    axi4_if.slave bus
);
    assign rx_pending=(count!=0)||framing_error||overflow;
    wire busy; logic tx_valid; logic [7:0] tx_data;
    t03_uart_tx #(.DIVISOR(DIVISOR)) transmitter(.clk,.reset,.valid(tx_valid),.data(tx_data),.busy,.tx);
    logic rx_meta,rx_sync;
    logic [7:0] fifo [0:FIFO_DEPTH-1],rx_shift;
    integer rd_ptr,wr_ptr,count,rx_state,rx_timer,rx_bit;
    logic framing_error,overflow,aw_pending;
    logic [31:0] aw_address;
    logic [1:0] aw_error;
    wire take_aw=bus.awvalid&&bus.awready;
    wire take_w=bus.wvalid&&bus.wready;
    wire take_ar=bus.arvalid&&bus.arready;
    wire pop=take_ar&&bus.arlen==0&&bus.arsize==2&&bus.araddr[1:0]==0
             &&bus.araddr[7:0]==8'h08&&count!=0;
    wire push=rx_state==3&&rx_timer==0&&rx_sync;
    // A simultaneous read frees a slot even when the FIFO starts full.
    wire accept_push=push&&(count<FIFO_DEPTH||pop);
    assign bus.awready=!reset&&!aw_pending&&!bus.bvalid;
    assign bus.wready=!reset&&aw_pending&&!bus.bvalid&&(aw_address[7:0]!=0||!busy);
    assign bus.arready=!reset&&!bus.rvalid;
    assign bus.bid=0;assign bus.rid=0;assign bus.rlast=1;
    always_comb begin
        tx_valid=take_w&&aw_address[7:0]==0&&aw_error==0&&bus.wstrb==15&&bus.wlast;
        tx_data=bus.wdata[7:0];
    end
    always @(posedge clk) begin
        if(reset)begin
            rx_meta<=1;rx_sync<=1;rx_state<=0;rx_timer<=0;rx_bit<=0;rx_shift<=0;
            rd_ptr<=0;wr_ptr<=0;count<=0;framing_error<=0;overflow<=0;
            aw_pending<=0;aw_address<=0;aw_error<=0;
            bus.bvalid<=0;bus.bresp<=0;bus.rvalid<=0;bus.rdata<=0;bus.rresp<=0;
            app_signature<=0;app_data_signature<=0;source_mode<=0;fault_code<=0;
        end else begin
            rx_meta<=rx;rx_sync<=rx_meta;
            // Address capture and completion cannot coincide under AWREADY.
            if(take_w)aw_pending<=0;else if(take_aw)aw_pending<=1;
            if(take_w)bus.bvalid<=1;else if(bus.bvalid&&bus.bready)bus.bvalid<=0;
            if(take_ar)bus.rvalid<=1;else if(bus.rvalid&&bus.rready)bus.rvalid<=0;
            if(take_aw)begin
                aw_address<=bus.awaddr;
                aw_error<=bus.awlen!=0||bus.awsize!=2||bus.awaddr[1:0]!=0?2:0;
            end
            if(take_w)begin
                bus.bresp<=aw_error;
                if(!bus.wlast||bus.wstrb!=15)bus.bresp<=2;
                else if(aw_error==0)case(aw_address[7:0])
                    8'h00: ;
                    8'h18:begin if(bus.wdata[2])framing_error<=0;if(bus.wdata[3])overflow<=0;end
                    8'h20: fault_code<=bus.wdata;
                    8'h24: app_signature<=bus.wdata;
                    8'h28: app_data_signature<=bus.wdata;
                    8'h30: source_mode<=bus.wdata;
                    default:bus.bresp<=3;
                endcase
            end
            if(take_ar)begin
                bus.rresp<=0;bus.rdata<=0;
                if(bus.arlen!=0||bus.arsize!=2||bus.araddr[1:0]!=0)bus.rresp<=2;
                else case(bus.araddr[7:0])
                    8'h04:bus.rdata<={28'b0,overflow,framing_error,(count!=0),busy};
                    8'h08:if(count!=0)bus.rdata<={24'b0,fifo[rd_ptr]};
                    8'h10:bus.rdata<=boot_mode;
                    8'h14:bus.rdata<=preload_bytes;
                    default:bus.rresp<=3;
                endcase
            end
            case(rx_state)
                0:if(!rx_sync)begin rx_state<=1;rx_timer<=DIVISOR/2-1;end
                1:if(rx_timer==0)begin
                    if(rx_sync)rx_state<=0;
                    else begin rx_state<=2;rx_timer<=DIVISOR-1;rx_bit<=0;end
                end else rx_timer<=rx_timer-1;
                2:if(rx_timer==0)begin
                    rx_shift[rx_bit]<=rx_sync;rx_timer<=DIVISOR-1;
                    if(rx_bit==7)rx_state<=3;else rx_bit<=rx_bit+1;
                end else rx_timer<=rx_timer-1;
                3:if(rx_timer==0)begin
                    if(!rx_sync)framing_error<=1;
                    rx_state<=0;
                end else rx_timer<=rx_timer-1;
                default:rx_state<=0;
            endcase
            if(pop)rd_ptr<=(rd_ptr+1)%FIFO_DEPTH;
            if(accept_push)begin fifo[wr_ptr]<=rx_shift;wr_ptr<=(wr_ptr+1)%FIFO_DEPTH;end
            case({accept_push,pop})
                2'b10:count<=count+1;
                2'b01:count<=count-1;
                default: ;
            endcase
            if(push&&!accept_push)overflow<=1;
        end
    end
endmodule
