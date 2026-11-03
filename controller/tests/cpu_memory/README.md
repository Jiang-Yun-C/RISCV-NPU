# CPU memory-path differential checks

These tests exercise the two bounded changes in `nx_reference.c` against an
independently supplied, unchanged baseline source tree. They do not fetch or
substitute model weights and never access a board.

## Changes under test

1. `nx_greedy` validates and selects in one traversal, retaining the current
   maximum in a local float. It still rejects every nonfinite value, leaves the
   output token untouched on failure, publishes only after the complete scan,
   and uses strict `>` so the first equal value wins, including signed zero.
   There is no new `restrict` or output/input nonaliasing requirement.
2. Softmax writes each independently rounded FP32 exponential into both the
   probability row and the destructive reduction scratch as it is produced.
   This removes the subsequent copy scan. The fallback path pads only the
   scratch because no consumer reads padded probabilities. Exponential call
   order, input subtraction, rounding, adjacent-pair reduction, division order,
   PV routing and all tensor/arena sizes remain unchanged.

No approximate math, FMA contraction, cacheability change, extra tensor buffer,
DMA ownership change or shared-memory coherence change is introduced.

## Run

From the candidate `source/` directory:

```bash
python tests/cpu_memory/verify.py \
  --baseline-source /absolute/path/to/unchanged/source \
  --output /absolute/path/to/new/evidence-directory \
  --benchmark
```

Requirements: Python with NumPy, GCC, and Linux support for the established
native production-main fixture's fixed-address anonymous mappings. The output
directory must not already exist. All compiler invocations, source hashes,
individual cases and results are recorded in `RESULTS.json`. Source hashes are
checked again at the end to detect changes during the run. `--benchmark` is
optional and can be omitted from correctness runs.

The three separately built versions are baseline `-O2`, candidate `-O2` and
candidate `-O3`, all with `-ffp-contract=off`, `-fno-fast-math`,
`-fno-strict-aliasing` and `-fno-builtin`. An O3 correctness result is not an O3
performance recommendation for the RV32 instruction cache or board.

## Checks and scope

- 33 full-production-vocabulary greedy cases (151,936 logits): deterministic
  random values, arbitrary finite float bit patterns, ascending/descending and
  negative values, ties, signed zeros, subnormals, finite extremes, early/middle/
  late quiet or signaling NaNs and infinities, null arguments and output aliasing.
  Expected valid tokens are independently checked, and failures must leave the
  token unchanged. Floating-point exception flags are also compared.
- 304 native attention cases with production H896/D64/14:2 GQA geometry:
  rows 1 through 4, sequence lengths 1 through 640, tree/cache/GQA boundaries
  including 32/33, 64/65, 128/129, 256/257 and 512/513, future-KV NaN poisoning,
  large values, signed zeros, subnormals, NaN/Inf/overflow failures, input
  immutability and output guards. Valid output bits, error codes and floating-point
  exception flags must match. There are 561,792 valid output FP32 words compared
  for each candidate build.
- A host-only PV callback checks that exact probability bytes, routing and error
  handling match at length 64/65. Its ordered CPU arithmetic is an oracle for
  the handoff; it does **not** qualify CE64 hardware or measure its latency.
- Three actual-production-main suites cover streaming on, streaming off and
  failed final stack validation. They compile the real main/runtime/model/
  tokenizer/stream source with the existing `NX_OPT13_TEST` two-layer synthetic
  fixture, compare the entire UART transcript and the raw valid token/logit/KV
  bytes, and cover varied prompt lengths, invalid-input recovery and a full
  512-token context. The clock, UART and stack observations are host fixtures.

These checks establish scoped numerical and interface equivalence. They do not
establish 24-layer real-weight model quality, production RV32 timing, CoreMark,
DDR traffic, CE64 timing or actual board first-character latency.

## Structural memory-access reduction

The following counts describe source-level scalar accesses before compiler
optimization. They are **not** CPU cache misses, AXI/native DDR bytes or cycles.

For a successful greedy call with `V` logits:

| Source-level operation | Baseline float reads | Candidate float reads |
|---|---:|---:|
| Separate finite-only traversal | V | 0 |
| Selection traversal, including initial value | V - 1 | V |
| `logits[best]` in comparisons | V - 1 | 0 |
| Total explicit source expressions | 3V - 2 | V |

For V=151,936 that is 1,823,224 versus 607,744 bytes of explicitly expressed
reads. A compiler may already keep the old best value in a register, so the
source count must not be advertised as measured bus savings. Even excluding all
old best-value rereads, two sequential traversals become one, removing 607,740
bytes of duplicate source reads per successful output-token selection.

For each cached softmax head of length `len`, the removed copy saves `4*len`
source bytes read while retaining the same number of probability/scratch writes.
For the fallback head, with `padded=next_power_of_two(len)`, it saves `4*padded`
source bytes read and `4*(padded-len)` bytes of unused probability-padding writes.
These arrays are the existing temporary stack workspace; these reductions must
not be counted as measured external DDR savings.

The optional benchmark times actual greedy calls from C on a hot 607,744-byte
native-host array, rotating the build order over seven samples. It reports raw
samples and medians with no correctness/performance gate. Its speed ratios are
specific to that native compiler, CPU and cache state and must not be extrapolated
to CPU CoreMark, full inference, streaming TTFT or RV32 cycles.
