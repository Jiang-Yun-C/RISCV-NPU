# Exact CPU greedy/uncached-memory A/B probe

This probe links the actual production `nx_greedy` from each source tree at full
vocabulary size **151936**. It uses the same T27 startup, hard-float ABI and
linker map for both variants. It does not replace the function with a benchmark
copy or change the production model geometry.

The logits occupy `0xac000000`, the uncached workspace. Stack is the existing
64 KiB SRAM at `0x20000`; program entry is `0xb4000000`. Initialization is before
the measurement window. A volatile store of 1 to `0x100000f0` starts external
counters; 2 ends the window. Firmware also reads 64-bit `mcycle` around the real
function. External marker cycles include the CSR/fence/call boundary overhead,
so they need not equal the firmware delta. Compare matching boundaries.

## Build

```sh
python3 tests/cpu_memory_rtl/build.py \
  --baseline-source /original-streaming-package/source \
  --source /optimized-package/source \
  --cc /path/to/riscv32-unknown-elf-gcc \
  --output /new/probe-builds \
  --case all --optimization both
```

The compiler must supply the normal C headers and the RV32IMF/ILP32F libgcc
selected for `rv32imf_zicsr_zifencei`. A relocated validation toolchain may need a
wrapper to select its include/library directories; the receipt records the
wrapper identity and compiler version. This tool never fetches dependencies.

Each independent build produces a checked ELF, its single PT_LOAD binary, map,
compile log, and source/compiler identities. `BUILD_PASS_EXECUTION_REQUIRED`
only confirms compilation. It is not CPU execution or board evidence.

## Cases and result checks

| Case | Input | Expected result |
|---|---|---|
| `valid` | Full finite array, unique maximum at 151934 | `NX_OK`, token 151934 |
| `tie` | Equal maxima at 19 and 151934 | `NX_OK`, first maximum 19 |
| `signed_zero` | Negative values, -0 at 23, +0 at 151934 | `NX_OK`, first zero 23 |
| `late_nan` | Quiet NaN at the final element after a valid maximum | `NX_NUMERIC`, caller's token sentinel unchanged |

Firmware prints one `MEMBENCH` line (all integer fields hexadecimal), then writes
`0xc021` to `0x10000020` for success or `0xbad` for failure. A CPU trap also fails.
Do not accept a simulator's cycle count unless this line reports `pass=00000001`
and the success completion was observed.

## Interpret execution results

Run each binary with the same exact `T09Cpu.v` and the same explicitly recorded
behavioral memory latencies in `tests/cpu_rtl`. Keep baseline/candidate compiler,
optimization flags, inputs and initial CPU state identical. O2-to-O3 comparisons
are a separate axis from the source change.

For the main valid case, compare the marker-window CPU cycles and uncached logits
read transactions/bytes. Firmware initialization and UART output are outside
this window. The edge cases verify that the one-pass scan preserves tie,
signed-zero and failure-publication rules.

The memory model is not the board DDR controller, native write-drain path,
accelerator fabric or complete LLM workload. These measurements demonstrate CPU
instruction execution and data-traffic reduction for this function under the
chosen memory model. They are **not** a CoreMark score, board latency or TTFT
prediction.
