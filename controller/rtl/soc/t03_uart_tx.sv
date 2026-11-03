module t03_uart_tx #(parameter integer DIVISOR = 16) (
    input wire clk, reset, valid,
    input wire [7:0] data,
    output wire busy,
    output wire tx
);
    reg [9:0] shift;
    reg [3:0] bits_left;
    reg [$clog2(DIVISOR)-1:0] divider;
    assign busy = bits_left != 0;
    assign tx = busy ? shift[0] : 1'b1;
    always @(posedge clk) begin
        if (reset) begin
            shift <= 10'h3ff;
            bits_left <= 0;
            divider <= 0;
        end else if (!busy) begin
            if (valid) begin
                shift <= {1'b1, data, 1'b0};
                bits_left <= 10;
                divider <= DIVISOR-1;
            end
        end else if (divider == 0) begin
            shift <= {1'b1, shift[9:1]};
            bits_left <= bits_left - 1'b1;
            divider <= DIVISOR-1;
        end else divider <= divider - 1'b1;
    end
endmodule
