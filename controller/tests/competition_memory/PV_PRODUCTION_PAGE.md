# PV production-address CE regression

This reproducer exercises the reported `length=1` failure through the actual
CE register file, descriptor checker, PV controller, synchronous scratch, FP
datapath and DMA. The external MMIO master and DDR slave are behavioral models.
The existing wrapper holds external guard/adapter state idle, drained and free
of faults; this is not a complete SoC/PHY or board experiment.

## Inputs and checks

The two production output addresses are `0xAC00A800` and `0xAC00AF00`. Each
call has seven query heads, 64 FP32 output dimensions and length/padded length
one. The two KV group sources are `0xA8000000` and `0xA8000100`, with the
production 512-byte row stride. V values are synthetic, finite, independently
specified test data. They are not the report's frozen W or real model assets.

P is loaded through the real MMIO P-window protocol: BEGIN, geometry and
session/sequence metadata, all 448 words, then PUBLISH. Every head's sole
active P is one. No DDR P reads occur; each call reads exactly 256 bytes of V.
Output words are compared against independently rounded host FP32 multiply
results using the bytes actually accepted on the modeled AXI W channel.

The test verifies:

- The original v3 returns `[0, -11]`. The second call has `valid=0`, no output
  AW/W and no modified destination bytes. Its 256-byte V read still completes.
- The fixed v4 returns `[0, 0]`; the two calls compare 896 actual output words.
  The second output's accepted bursts are exactly 256/512/512/512 bytes.
- Every accepted AR/AW stays within 4 KiB; all R and B transactions retire
  before the completion is consumed. Actual payload counters match the
  completion record.
- Completion epoch, session, sequence and both generation fields match.
  ACK unlocks/revokes the local P-window before the next request.
- A third ordinary request succeeds after ACK in the same live session. In
  v4 it also uses legal short-V base `0xA8000FF0`, requiring exact 16/240-byte
  read splitting. This is not a test of firmware session-reset recovery.

Both `ENHANCED=0` (default `LONG_PV=0`) and `ENHANCED=1` are built. The former
still supports short PV and the P-window even though the new long-PV capability
is zero. The test does not mistake a zero long-PV capability for absent short PV.

## Commands

Run from the delivered `source` directory, using new output directories:

```sh
python3 tests/competition_memory/run_ce_production_page.py \
  --verilator /path/to/verilator \
  --verilator-root /path/to/share/verilator \
  --enhanced 0 --out /tmp/t27-pv-page-fixed0

python3 tests/competition_memory/run_ce_production_page.py \
  --verilator /path/to/verilator \
  --verilator-root /path/to/share/verilator \
  --enhanced 1 --out /tmp/t27-pv-page-fixed1

# To reproduce the negative on the preserved v3 source:
python3 tests/competition_memory/run_ce_production_page.py \
  --rtl-source /path/to/v3/source --expect-old-failure \
  --verilator /path/to/verilator \
  --verilator-root /path/to/share/verilator \
  --enhanced 0 --out /tmp/t27-pv-page-original0
```

The runner rebuilds from the selected source and records every input hash,
build/run command, tool version, executable hash, raw output, and input
stability. `EXPECTED_OLD_FAILURE_REPRODUCED` means the negative assertion was
observed, not that the old production design passes.

As in the existing CE integration test, Verilator 5.006 uses the documented
per-element FP register simulation representation. Original source, generated
copy and transformation patch are retained. Production FP logic and DMA
acceptance criteria are unchanged, and no `BLKANDNBLK` waiver is used. This
test does not close the separate general FP output-backpressure failure,
the report's first-Q root cause, real-model W comparison, timing/resources,
authenticated boot, native DDR adapter behavior or physical board validation.
