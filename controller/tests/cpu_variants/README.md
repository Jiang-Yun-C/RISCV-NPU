# Actual generated CPU execution checks

Run from `source/`. Outputs must be new directories/files. An RV32 toolchain with the matching ILP32F libgcc and Verilator are required.

```sh
python3 tests/cpu_variants/run.py firmware --cc /absolute/riscv32-gcc --output /absolute/new/probes
python3 tests/cpu_variants/run.py build --rtl /absolute/cpu-build/lru_btb/T09Cpu.v --output /absolute/new/cpu-sim
python3 tests/cpu_variants/run.py run --sim /absolute/cpu-sim --binary /absolute/probes/0/firmware.bin --output /absolute/new/probe0.json
```

Repeat `run` for probes 0 through 4. Cases cover interleaved two-set data conflicts, a hot line with competing lines in one set, instruction-line conflicts, byte stores plus cache invalidation/FENCE.I/self-modifying code, and alternating conditional branches/indirect calls. Checksums are computed by actual RV32 execution and checked against the mathematical expectations in the test. The harness does not inject results or replace CPU computation. Region markers bound event counters.

Existing `firmware/coremark` performance and validation binaries can also be supplied. The runner accepts the documented 10-iteration, 2000-byte short regression and validates seed, list, matrix, state and final CRCs. Formal CoreMark score is always `null` here: the timing environment is a bounded behavioral AXI model, not a physical board, and the short run does not satisfy the formal duration rule.

Build records bind the generated RTL, register initialization image and C++ harness. Runs verify those inputs, record the executable and binary SHA-256 and check that neither executable nor binary changes during execution. Historical runs created before the executable build-receipt field was introduced still carry the exact executable hash at execution. The original ISA interface and the read-only trace signals are used. A successful directed regression is useful targeted evidence; it is not a complete ISA proof or timing-closure claim.
