// T03 temporary PRELOAD platform: unified 64 KiB RAM, no caches or DMA.
// Stores complete when accepted; I/D reads return one clock later.
module t03_soc (
    input wire clk, reset,
    input wire [31:0] seed,
    output wire uart_tx,
    output wire retire_valid,
    output wire [31:0] retire_pc, retire_instruction,
    output wire exception_pending, csr_redirect,
    output wire [31:0] csr_target,
    output wire timer_irq,
    output reg [31:0] signature, exit_code,
    output reg exit_valid
);
    localparam [31:0] RAM_BASE = 32'h80000000;
    localparam integer RAM_WORDS = 16384;
    reg [31:0] ram [0:RAM_WORDS-1];
    wire i_valid, i_ready;
    wire [31:0] i_pc;
    reg i_rsp_valid, i_rsp_error;
    reg [31:0] i_rsp_data;
    wire d_valid, d_ready, d_write;
    wire [31:0] d_address, d_data;
    wire [3:0] d_mask;
    wire [1:0] d_size;
    reg d_rsp_ready, d_rsp_error;
    reg [31:0] d_rsp_data;
    wire i_in_ram = i_pc >= RAM_BASE && i_pc < RAM_BASE + RAM_WORDS*4;
    wire d_in_ram = d_address >= RAM_BASE && d_address < RAM_BASE + RAM_WORDS*4;
    wire uart_busy;
    reg [63:0] mtime, mtimecmp;
    wire uart_store = d_valid && d_ready && d_write && d_address == 32'h10000000;
    assign i_ready = !reset;
    assign d_ready = !reset && !(d_write && d_address == 32'h10000000 && uart_busy);
    assign timer_irq = mtime >= mtimecmp;
    t03_uart_tx uart (.clk(clk), .reset(reset), .valid(uart_store), .data(d_data[7:0]),
                      .busy(uart_busy), .tx(uart_tx));
    T03Cpu cpu (
        .clk(clk), .reset(reset),
        .iBus_cmd_valid(i_valid), .iBus_cmd_ready(i_ready), .iBus_cmd_payload_pc(i_pc),
        .iBus_rsp_valid(i_rsp_valid), .iBus_rsp_payload_error(i_rsp_error), .iBus_rsp_payload_inst(i_rsp_data),
        .dBus_cmd_valid(d_valid), .dBus_cmd_ready(d_ready), .dBus_cmd_payload_wr(d_write),
        .dBus_cmd_payload_mask(d_mask), .dBus_cmd_payload_address(d_address),
        .dBus_cmd_payload_data(d_data), .dBus_cmd_payload_size(d_size),
        .dBus_rsp_ready(d_rsp_ready), .dBus_rsp_error(d_rsp_error), .dBus_rsp_data(d_rsp_data),
        .timerInterrupt(timer_irq), .externalInterrupt(1'b0), .softwareInterrupt(1'b0),
        .trace_retire(retire_valid), .trace_pc(retire_pc), .trace_instruction(retire_instruction),
        .trace_exception_pending(exception_pending), .trace_csr_redirect(csr_redirect), .trace_csr_target(csr_target)
    );

    // Simulation-only initialization. No TB code writes result registers or
    // changes memory after preload. The CPU alone performs all test operations.
    // synthesis translate_off
    string firmware;
    integer image_words, word_index;
    initial begin
        if (!$value$plusargs("firmware=%s", firmware)) $fatal(1, "missing PRELOAD firmware");
        if (!$value$plusargs("image_words=%d", image_words) || image_words < 1 || image_words > RAM_WORDS)
            $fatal(1, "invalid image size");
        for (word_index = 0; word_index < RAM_WORDS; word_index = word_index+1) ram[word_index] = 32'ha5a5a5a5;
        $readmemh(firmware, ram, 0, image_words-1);
    end
    // synthesis translate_on

    integer lane;
    always @(posedge clk) begin
        if (reset) begin
            i_rsp_valid <= 0; i_rsp_error <= 0; i_rsp_data <= 0;
            d_rsp_ready <= 0; d_rsp_error <= 0; d_rsp_data <= 0;
            mtime <= 0; mtimecmp <= 64'hffffffffffffffff;
            signature <= 0; exit_code <= 0; exit_valid <= 0;
        end else begin
            mtime <= mtime + 1;
            i_rsp_valid <= i_valid && i_ready;
            i_rsp_error <= !i_in_ram;
            if (i_valid && i_ready) i_rsp_data <= i_in_ram ? ram[i_pc[15:2]] : 32'hffffffff;
            d_rsp_ready <= d_valid && d_ready && !d_write;
            d_rsp_error <= 0;
            if (d_valid && d_ready) begin
                if (d_in_ram) begin
                    if (d_write) begin
                        for (lane = 0; lane < 4; lane = lane+1)
                            if (d_mask[lane]) ram[d_address[15:2]][lane*8 +: 8] <= d_data[lane*8 +: 8];
                    end else d_rsp_data <= ram[d_address[15:2]];
                end else if (!d_write) begin
                    case (d_address)
                        32'h10000004: d_rsp_data <= {31'b0, uart_busy};
                        32'h10000008: d_rsp_data <= mtime[31:0];
                        32'h1000000c: d_rsp_data <= mtime[63:32];
                        32'h10000010: d_rsp_data <= mtimecmp[31:0];
                        32'h10000014: d_rsp_data <= mtimecmp[63:32];
                        32'h10000018: d_rsp_data <= seed;
                        default: begin d_rsp_data <= 0; d_rsp_error <= 1; end
                    endcase
                end else begin
                    case (d_address)
                        32'h10000000: ; // UART receives the same accepted bus write.
                        32'h10000010: mtimecmp[31:0] <= d_data;
                        32'h10000014: mtimecmp[63:32] <= d_data;
                        32'h1000001c: signature <= d_data;
                        32'h10000020: begin exit_code <= d_data; exit_valid <= 1; end
                        default: begin
                            // DBusSimple does not acknowledge stores; fail the
                            // simulation rather than silently discard a bad one.
                            // synthesis translate_off
                            $fatal(1, "unmapped CPU store address=%08x", d_address);
                            // synthesis translate_on
                        end
                    endcase
                end
            end
        end
    end
endmodule
