# PV page-boundary regression (v4)

## Finding and bounded fix

The v3 `nx_pv_control` still has the reported short-PV output defect. Its shared
P/Y chunk expression applies the page remainder only when `length > 64`. A
legal short call with seven heads and Y at `0xAC00AF00` therefore requests a
512-byte write across `0xAC00B000`. The DMA page contract rejects it and the
controller reports `status=-11`, `success=0`.

The read-only review also found two manifestations accepted by the existing ABI:

* Short external P accepts 16-byte alignment, but its 512-byte commands can
  cross a page. P is read by DMA; this controller has no P DMA write path.
* Short V accepts 16-byte alignment, but each row was always read as one
  256-byte command. `V=0xA8000FF0` crosses a page in the first row; other valid
  starting offsets encounter the boundary in a later row because stride is 512.

The v4 production patch removes the long-only condition for P/Y and splits a
short V row at the page boundary, advancing the scratch address by the same
row offset. It retains the 16-byte short-V ABI. The long path's existing
256-byte V alignment and 64-byte dimension tiles remain unchanged. The
descriptor shape, address regions, overlap check, local-P identity check,
completion identity, arithmetic order, timeout and drain predicates are retained.

The only changed production input to this fixture is
`rtl/sfu/nx_opt11_dispatch.sv`:

| Version | SHA-256 |
| --- | --- |
| v3 original | `4fcfaffeac4af7771d3f763ab46d5d44ecbeb46b65494fcfc9a091b74028d936` |
| v4 fixed | `7a89be214c2920c7853e5d2b56c2e9951d35521c44d0fb4c4ed3cd45d62adc98` |

## Fixture and meaning of its results

`pv_boundary_component.sv` instantiates the real `nx_pv_control` and
`nx_opt11_fp`. Its C++ environment provides synchronous scratch memory, sealed
local P-window data, external memory, randomly stalled DMA command acceptance,
random response delays and a separate delayed transport-drain indication.
Held DMA command fields must stay stable through stalls. Completion must wait
until all responses and transport drain have finished.

This is a controller-level fixture. It does **not** instantiate
`nx_ce64_dma`, the SoC guard/arbiter or a native DDR PHY. The environment models
the DMA's page-rejection contract: an illegal crossing command returns DECERR
without transferring external payload. Full-CE testing is a separate gate.

Every successful call checks all 448 FP32 output words against independently
rounded multiplication followed by the complete, padded adjacent-pair sum tree.
P/V input and Y output word coverage must be exact, without omissions or
duplicates; V row padding must not be read. Surrounding Y sentinels must stay
unchanged. Completion session, sequence, epoch, generation and byte counters
are checked as well.

The same fixture can read production RTL from either source tree. The
`--expect-v3-defect` mode accepts only a specifically named P, V or Y page
rejection with `status=-11`, `success=0`; it records `EXPECTED_NEGATIVE`.
Its zero process exit means that the reproduction met its expectations. It
does **not** mean the original RTL succeeded. Explicit injected failures are
recorded separately as `EXPECTED_FAILURE`.

The Verilator 5.006 runs use the already established, simulation-only
`lower_fp_pipeline.py` per-element register representation conversion. Original
FP source, converted source, patch and hashes are retained. Arithmetic,
latency, enable/reset expressions and the fixed-ready FP interface are unchanged;
there is no `BLKANDNBLK` waiver in this mode. These tests do not qualify general
FP output backpressure or investigate the separate first-Q issue from REPORT.md.

## Matrix and observed results

Both source versions were compiled with `MAX_LENGTH=64` and `MAX_LENGTH=512`.
There are 33 cases for MAX64 and 38 for MAX512, per source version.

| Coverage | Cases |
| --- | --- |
| Normal short path | Length 1, 63, 64; external P and page-aligned Y |
| Production local-P output | First group Y=`0xAC00A800`; second group Y=`0xAC00AF00` |
| Short Y split | Length 1, 63, 64; offsets `0xF00`, `0xFF0` |
| Short P split | Length 1, 63, 64; offsets `0xF00`, `0xFF0` |
| Short V split | Length 1, 63, 64 at `0xFF0`; exact fit at `0xF00`; 240/16 split at `0xF10`; later-row crossing from `0x1F0` |
| Long path | Length 65 and 512; P offset `0xE00`; Y offsets 0, `0xF00`, `0xFF0` |
| Existing shape restrictions | MAX64 rejects length 65/512; long misaligned external P remains rejected |
| Fault handling | P, V and Y response errors; short-PV timeout and stop |
| V fragment lifetime | Error or stop while second fragment is pending; no Y publication; next successful submit **without resetting the DUT** |

Observed totals:

| Source | Numeric successes | Named page-rejection negatives | Other expected failures | Bitwise-checked output words |
| --- | ---: | ---: | ---: | ---: |
| v3 original | 20 | 38 | 13 | 8,960 |
| v4 fixed | 54 | 0 | 17 | 24,192 |

The difference in the last failure category is intentional: four v3 cases stop
at the first illegal V command before reaching the requested second-fragment
error/stop point. On v4 those points are reached and checked directly.

`compare_pv_boundaries.py` verifies 20 originally successful cases retain the
same DMA-command and output digests, with the same source operands and payload
counts. It also requires six specific before/after pairs (P/V/Y for each MAX
parameter) to change from page rejection to bitwise success. The observed
command sequences include:

| Path | Original rejected command | Fixed command byte counts |
| --- | --- | --- |
| Y at `0xAC00AF00`, seven heads | 512 bytes | 256, 512, 512, 512 |
| P at `0xAC100FF0`, seven heads | 512 bytes | 16, 512, 512, 512, 240 |
| V at `0xA8000FF0`, one row | 256 bytes | 16, 240 |

The fixed run observed 25,321 command-ready stall cycles and 22,691 cycles with
DMA idle but external drain delayed. These are fixture coverage counts, not
performance measurements. All 17 intentional fixed-source failures retain
`success=0`; input failures, stop and timeout issue no Y command. A Y response
error may have transferred payload, but must not publish a valid completion.

## Reproduction

Run from the v4 source directory. `--rtl-source` supplies production RTL; all
fixture files are loaded from this runner's own directory, so both runs use
exactly the same fixture. Substitute the source/output/tool paths as needed.

```sh
python3 tests/competition_memory/run_pv_boundaries.py \
  --rtl-source /path/to/v3/source --out /tmp/pv-before \
  --verilator /path/to/verilator --verilator-root /path/to/share/verilator \
  --split-fp-registers --expect-v3-defect

python3 tests/competition_memory/run_pv_boundaries.py \
  --rtl-source /path/to/v4/source --out /tmp/pv-after \
  --verilator /path/to/verilator --verilator-root /path/to/share/verilator \
  --split-fp-registers

python3 tests/competition_memory/compare_pv_boundaries.py \
  --before /tmp/pv-before --after /tmp/pv-after --out /tmp/pv-comparison.json
```

Each run saves the build and run commands, input hashes, immutable copies of the
controller and fixture inputs, build logs, per-case JSON results, full accepted
DMA command JSON traces, FP compatibility evidence and artifact hashes. The
runner verifies that source inputs did not change during execution. The
comparison saves both receipt hashes and the exact production source delta.

Current evidence is under `v4_pv_boundaries/{v3-negative,v4-fixed}` alongside
`comparison.json`. Preserve the named negative results. No board download,
authenticated boot, PnR/timing, real DDR measurement, full-model W pass, or
first-Q root-cause claim follows from this controller regression.
