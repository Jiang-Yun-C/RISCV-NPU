# VCS + cocotb task framework

Run from the repository root:

```sh
make t09-smoke
make t09
make -f tests/cocotb/Makefile full
npu-python scripts/run_cocotb.py --task T09 --suite regression --seed 7
npu-python scripts/run_cocotb.py --verify-archive evidence/T09/<run-id>
make t09-test
make t12
npu-python scripts/run_cocotb.py --task T12 --suite smoke
npu-python scripts/run_t12.py --verify-archive evidence/T12/<run-id>
```

T09 and T12–T22 are registered. T09 `regression`/`full` rebuild soft/hard/nopredict
profiles, run soft/hard seeds 1/7/19, repeat seed 1, and require four isolated
negative runs. `smoke` and a seed-filtered run do not close the full task.
`full` currently equals T09 regression; later task owners add their own matrices.
`--run-id` must name a new directory. No previous results are accepted.

`run_cocotb.py` exports the locked VexRiscv commit, applies the three reviewed
patches in `cpu_gen/patches/`, generates RTL, compiles ELF/ABI-matched libraries,
builds VCS with the project venv VPI, and creates `cocotb/<case-id>` directories.
The compilation is shared only within that run; runtime ROM initialization
files are copied and hashed per case. The source snapshot and tools are locked.
Both the command timeout (120 s) and simulation limit (200,000 cycles) apply.

The CPU is real RTL. Python drives only reset, clock, a synchronous boot ROM,
AXI slave responses and external interrupt pins. The I/D AXI ports share one
sparse byte memory. The separate passive monitor checks channel stability,
transfer size, byte strobes and response counts. The scoreboard observes CPU
MMIO writes, branch/retire ports and AXI refills. Its integer reference reuses
T03's independent Python arithmetic; trap addresses/encodings come from the ELF,
not CPU output. `common/waveform.py` additionally compares the actual VCD
handshakes and retirement with VPI observations.

The memory BFM implements the aligned INCR subset emitted by this CPU, not the
entire T04 model. `fixtures/t04-memory-subset.json` binds 1,371 independently
observed T04 VCS read beats and their stimuli; the unit suite checks byte/lane
semantics against them. T08's reserved window intentionally returns DECERR.
FIXED/WRAP, IDs, AXI arbitration between CPU and Coral, and physical DDR are
outside this testbench. There is exactly one response driver per port.

T09 UART evidence is the byte stream at UART MMIO, not a new serial-pin test;
T03 preserves the prior real UART TX-pin baseline. Interrupt requests are
scheduled asynchronously by the external environment, and real CPU firmware
reads/records CSRs, acknowledges each input and executes MRET.

For T09, `cocotb_case.py` requires exactly `test_cpu.cpu_execution`, no skip/failure/error,
fresh XML/checks/observations/VCD, every required check category, a matching
run/case/input identity, VCS/cocotb banners and a clean simulator log. XML test
count is not assertion count. Held-reset/bad-golden/empty/missing-XML failures
remain raw FAIL/nonzero in `evidence/T09_NEGATIVE`; the parent verifies the
specific expected reason. Unit controls also reject malformed/duplicate/stale
results and protocol violations. The archive verifier rechecks hashes, source
snapshot, the registered matrix, per-case XML/checks and VCD.

For another RTL task, register its task/suite/required cases, fixture identity,
firmware and generated top in the runner; reuse `Checks`, the result gate,
isolated process execution and waveform checks. Add a test module with
independent expected results and nonzero category counts. Do not reuse a CPU
PASS as evidence for an unregistered backend or board task.

T12 uses the same locked generator, VPI bootstrap, `Checks`, fresh-result gate,
command timeouts and evidence format. Its registered test is
`test_runtime.runtime_execution`. Native T04 `axi_sparse_mem` responders share
one backing store for the real CPU's I/D ports, avoiding a Python callback for
every clock of a long software runtime. Cocotb compares passive AXI MMIO output
against original-tokenizer golden and independent numeric fixtures, reads guard
words and scans the actual stack sentinel. Four independent simulator processes
can run concurrently; they have distinct ROM/ELF/image/seed/log/XML identities.
Only the initial 10000-cycle VCD is retained; all results and bus/protection
counts span the full execution. T12 checks tokenizer, 512-token request/session
limits, a T11 tile, full-width RMSNorm and a reduced same-source numerical graph.
It does not install or claim a Coral driver. See
[runtime contract](../../docs/spec/runtime-v1.md) and
[runtime fixtures](fixtures/runtime/README.md).

T11 已发布 [golden manifest](fixtures/golden/manifest.json)。桌面自验：

```bash
npu-python tests/reference/fixture_io.py tests/cocotb/fixtures/golden/manifest.json
```

实际消费者可导出相同字段的 candidate NPZ，传入 `--candidate <file> --case <manifest-path>`，或导入 `tests/reference/fixture_io.py` 的 `load`/`compare_case`。完整 prefix_ids 可重建选定步骤的前置 KV；缺字段、错误整数/scale、非有限值或冻结误差超限均失败。生产端自验不代表 RTL 已消费。

T13 runs `make t13` / `make t13-smoke`, or the common runner with `--task T13`.
It rebuilds the real cached CPU, native 32-to-128 Coral bridge, AXI permission/drain
guard, and RV32 driver. The backend is explicitly `CORAL_NATIVE_TRANSACTION_TEST_DOUBLE`:
its native CSR/TCM interface accepts the CPU-uploaded probe image but does not execute
instructions. Numerical capability masks remain zero. T16 must replace it with real
Coral RVV and the T14/T15 production kernels. The four registered runs use seeds
1/7/19 and replay 1; all cover normal/reused buffers, response delay, faults, lost/late
IRQ, timeouts and failed-then-successful drain recovery. Separate component stimulus
checks guard bursts, AW/W ordering and isolation. Full backend VCD handshakes/payload
are cross-checked with passive CSV; checks compare actual CPU output against independent
unsigned arithmetic. Held-reset, stale endpoint data, deliberately early completion,
empty test and missing XML stay raw FAIL in isolated negative archives.
See [T13 contract](../../docs/spec/accel-t13-contract.md); archive verifier:
`npu-python scripts/run_t13.py --verify-archive evidence/T13/<run-id>`.

T15 uses `make t15`, `make t15-regression`, `make t15-smoke`, or the common
runner with `--task T15`. Its registered test is `test_linear.linear_execution`.
The wrapper executes the locked real Coral RVV core, guard and sparse AXI memory;
the native slave receives an operator request and the microprogram computes every
group, scale restoration, reduction and bias. VexRiscv transport remains T16.
The shared CPU_C/CORAL_RVV provider has separate host C checks via `make t15-test`.

The full matrix contains 590 cases; regression contains 441 cases. Short boundary
cases use seeds 1/7/19 and an exact trace replay of seed 1. Real T05/T10 projections
cover Q/K/V/O/gate/up/down at M=1/4/8. The M1 head covers all 151936 rows through
149 disjoint directed partitions; M4/M8 head checks the first, middle and last
ranges. The coverage gate rejects missing or overlapping partitions. This is a
full directional output dataset, with each partition executing all K groups;
the single uninterrupted complete head request is an integration check for T16.

The independent streaming scoreboard checks every handshake, source byte, strobe,
guard, output element, integer dot, restoration intermediate and partial sum.
Qualification audit records include their transfer/cycle cost. Production requests
disable audit and return only final logits. Seven isolated negative cases retain
raw FAIL/nonzero results for reset, output/integer/restoration/reduction corruption,
empty test and missing XML. Archive replay validates the frozen source/configuration,
full required matrix, XML, hashes, complete traces and numeric outputs:

```sh
npu-python scripts/run_t15.py --verify-archive evidence/T15/<run-id>
```

See the [linear component contract](../../docs/spec/linear-t15-contract.md),
[support matrix](../../docs/spec/linear-t15-support.json) and
[T15 report](../../docs/reports/T15.md) for qualification status and measured costs.

T14 uses `make t14` or the common runner with `--task T14`. The wrapper retains
the framework top name `tb_cpu`, but contains real RvvCoreMiniAxi, T13 guard and
T04 memory; VexRiscv execution is the T16 gate. Nine registered cases include
seeds 1/7/19, replay, all three T10 packages, maximum M4/K4864 staging, byte tails,
non-16B output row pitch, SLVERR/DECERR and recovery. Four raw negative cases and
whole-trace/RTL counters are required. See [streaming report](../../docs/reports/backend-streaming.md).
# T17 UART boot

`make t17` or `npu-python scripts/run_cocotb.py --task T17 --suite full` runs
the registered UART protocol boot matrix. `make t17-smoke` is a connectivity
check; `make t17-test` checks the desktop protocol and host retry tool.
The CPU, UART and bus router are real RTL. PROTOCOL_BOOT initializes only ROM,
then the host drives RX pins; the passive scoreboard reconstructs AXI writes,
execution signatures and current-image instructions. PRELOAD uses the same
Boot ELF with an explicit loading-source log. See
[protocol](../../docs/spec/uart-boot-v1.md),
[matrix](../../configs/t17-uart-boot.json) and
[frozen fixtures](fixtures/uart_boot/manifest.json).

# T20 sensor control

`make t20` or `npu-python scripts/run_cocotb.py --task T20 --suite full`
runs 22 registered CPU/UART/I²C/GPIO/PWM cases. `make t20-smoke` checks the
short interface path; `make t20-test` runs 25 desktop contract/archive tests.
The full frozen W8 model runs on desktop C, with all candidate calls and raw
outputs recorded. The real VexRiscv executor consumes those bytes through real
UART RTL. I²C, GPIO and PWM devices are virtual; firmware is PRELOAD. Model
requests in the development and multi-condition groups have separate CPU
actuator preconditions, independently checked against their model snapshots.
Rejected requests must have no output writes, with immediate recovery checks.
The matrix requires three seeds, deterministic replay, five isolated checker
failures, startup CPU VCD and full peripheral-pin VCD.

See the [control contract](../../docs/spec/application-t20.md),
[matrix](../../configs/t20-application.json) and
[acceptance report](../../docs/reports/T20.md). Archive replay:

```sh
npu-python scripts/run_t20.py --verify-archive evidence/T20/acceptance-20261008-v3
```

## T22 platform components

```sh
make t22-smoke ARGS='--run-id NEW_SMOKE_ID'
make t22 ARGS='--run-id NEW_REGRESSION_ID'
npu-python scripts/run_cocotb.py --task T22 --verify-archive evidence/T22/NEW_REGRESSION_ID
```

The registered matrix runs seeds 1/7/19 and a seed1 repeat, plus held-reset,
bad-golden, empty-test and missing-XML negative controls. It uses the actual
`minimal_bist` and a byte-identical snapshot of native110-v7's BIST, including
its diagnostic outputs. RAM latency/read-first/write-enable/reset/UART,
simplified DDR request delays/read-valid gaps, 32 byte strobes, six fault classes
and interrupted-write recovery are checked independently. VCD/VPI accepted
traffic must agree.

The 4KiB memory and PLL clock/lock are explicit external environments. These
results qualify the components, while physical PHY, generic AXI bridging,
multiple IDs and CPU/NPU concurrency have separate acceptance obligations.
`make t22-acceptance` audits implementation and board receipts independently;
see [T22 report](../../docs/reports/T22.md) for the current board and timing limits.
