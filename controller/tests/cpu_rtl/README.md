# Isolated T09 CPU execution

`run_cpu.py` compiles the **unchanged** supplied `t27/cpu/T09Cpu.v` with
Verilator and executes a real RV32 binary at `0xb4000000`. A two-instruction ROM
hands off to the normal application entry; the CPU executes its own startup,
register/FPU initialization, BSS initialization, benchmark, UART stores and exit.

The bounded behavioral memory contains 8 MiB program storage, the existing
64 KiB SRAM stack, and 2 MiB uncached workspace at `0xac000000`. Independent
I/D AXI reads and D writes obey ready/valid handshakes. SRAM and UART have short
local latency; other read/write response latency is an explicit experiment
parameter. The CLI `--read-latency` and `--write-latency` values are **extra
wait cycles**, not total AXI transaction latency: a value of 3 permits the first
R/B handshake no earlier than 4 cycles after AR/last-W acceptance. A burst can
then deliver one R beat per cycle. The local extra wait is 1 cycle. UART is an
immediate byte sink, **not** physical serial timing.

This model does **not** instantiate CE64, the shared DDR fabric, native1024
drain/readback, HMIC, PHY, contention, or actual UART. Its measurements are
isolated CPU RTL cycles and observed AXI beats under the stated model. They
are not board CoreMark scores, full-model speedups, or production timing signoff.

```sh
python3 tests/cpu_rtl/run_cpu.py build --directory /new/cpu-sim --verilator verilator
python3 tests/cpu_rtl/run_cpu.py run --directory /new/cpu-sim \
  --binary /build/application.bin --output /new/result.json \
  --read-latency 3 --write-latency 3 --max-cycles 20000000
```

Each run records binary, RTL, register-init, and harness hashes. Firmware exit
must be `0xc021`; unknown memory access, malformed bursts, missing completion,
and cycle limits fail. `--hold-reset` is a negative control and must fail without
retirements, UART text, or successful exit. Memory probes can bracket one window
with writes `1`/`2` to test-only address `0x100000f0`; counters include the marker
stop handshake and exclude its start handshake. They differ slightly from
firmware `mcycle` sampling boundaries. Require one complete marker pair for a
memory result, and additionally verify firmware status/token. CPU completion
alone is not algorithm validation: every CoreMark run must also pass the
CoreMark log parser's CRC, type, timing and iteration checks; a short run is
never a formal score.
