`timescale 1ns/1ps
module tb_cpu;
    localparam integer CLOCK_NS = 10;
    localparam integer BIT_NS = CLOCK_NS * 16;
    reg clk = 0;
    always #(CLOCK_NS/2) clk = ~clk;
    reg reset = 1;
    reg [31:0] seed;
    wire uart_tx, retire_valid, exception_pending, csr_redirect, timer_irq, exit_valid;
    wire [31:0] retire_pc, retire_instruction, csr_target, signature, exit_code;
    t03_soc dut (.*);
    integer uart_fd, trace_fd, events_fd, result_fd;
    integer cycles = 0, retired = 0, uart_bytes = 0, redirects = 0, exception_cycles = 0;
    integer max_cycles;
    reg monitor_busy = 0;
    reg [7:0] received;
    integer bit_index;

    initial begin
        if (!$value$plusargs("seed=%d", seed)) $fatal(1, "missing seed");
        if (!$value$plusargs("max_cycles=%d", max_cycles)) max_cycles = 200000;
        uart_fd = $fopen("uart.log", "w");
        trace_fd = $fopen("retire.csv", "w");
        events_fd = $fopen("events.csv", "w");
        if (!uart_fd || !trace_fd || !events_fd) $fatal(1, "cannot open observation logs");
        $fwrite(trace_fd, "cycle,pc,instruction\n");
        $fwrite(events_fd, "cycle,target,exception_pending,timer_irq\n");
        $dumpfile("cpu.vcd");
        $dumpvars(0, clk, reset, uart_tx, retire_valid, retire_pc, retire_instruction,
                  exception_pending, csr_redirect, csr_target, timer_irq, signature, exit_valid, exit_code);
        repeat (10) @(negedge clk);
        // Negative control: a held-reset CPU must never produce results.
        if (!$test$plusargs("hold_cpu_reset")) reset = 0;
        $display("T03_START mode=PRELOAD seed=%0d", seed);
    end

    // Decode only the physical TX pin: 8 data bits, LSB first, one stop bit.
    initial forever begin
        @(negedge uart_tx);
        if (!reset) begin
            monitor_busy = 1;
            #(BIT_NS/2);
            if (uart_tx !== 0) $fatal(1, "UART invalid start bit");
            for (bit_index = 0; bit_index < 8; bit_index = bit_index+1) begin
                #(BIT_NS);
                if (uart_tx !== 0 && uart_tx !== 1) $fatal(1, "UART unknown data");
                received[bit_index] = uart_tx;
            end
            #(BIT_NS);
            if (uart_tx !== 1) $fatal(1, "UART framing error");
            $fwrite(uart_fd, "%c", received);
            uart_bytes = uart_bytes + 1;
            monitor_busy = 0;
        end
    end

    always @(posedge clk) begin
        cycles = cycles+1;
        if (cycles > max_cycles) $fatal(1, "T03_TIMEOUT cycles=%0d retired=%0d uart_bytes=%0d", cycles, retired, uart_bytes);
        if (!reset) begin
            if (retire_valid) begin
                if ($isunknown({retire_pc, retire_instruction})) $fatal(1, "unknown retired instruction");
                retired = retired+1;
                $fwrite(trace_fd, "%0d,%08x,%08x\n", cycles, retire_pc, retire_instruction);
            end
            if (exception_pending) exception_cycles = exception_cycles+1;
            if (csr_redirect) begin
                redirects = redirects+1;
                $fwrite(events_fd, "%0d,%08x,%0d,%0d\n", cycles, csr_target, exception_pending, timer_irq);
            end
            if (exit_valid) begin
                $fclose(uart_fd); $fclose(trace_fd); $fclose(events_fd);
                result_fd = $fopen("simulation.json", "w");
                $fwrite(result_fd, "{\"cycles\":%0d,\"retired\":%0d,\"uart_bytes\":%0d,\"signature\":%0d,\"exit_code\":%0d,\"redirects\":%0d,\"exception_cycles\":%0d}\n",
                        cycles, retired, uart_bytes, signature, exit_code, redirects, exception_cycles);
                $fclose(result_fd);
                if (exit_code !== 32'h600d0003 || monitor_busy || retired < 100 || uart_bytes < 20)
                    $fatal(1, "T03_BAD_EXIT code=%08x signature=%08x retired=%0d", exit_code, signature, retired);
                $display("T03_CPU_EXIT code=%08x signature=%08x retired=%0d cycles=%0d", exit_code, signature, retired, cycles);
                $finish;
            end
        end
    end
endmodule
