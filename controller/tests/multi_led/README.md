# Four onboard LED bank: RTL check

The selected physical channels are LED0/A20, LED2/C19, LED3/E18 and
LED5/A18. Their bit positions are 0, 2, 3 and 5; capability mask is `0x2d`.
The FDC pin constraints remain unchanged.

`nx_ce64_local` owns two eight-bit registers, exported through `nx_t25_local`
and `nx_t25_board_logic` to the selected physical top. LED0 defaults off.
LED2, LED3 and LED5 default to the original error, heartbeat and BIST displays.
The physical top's display selector changes only the output pins. Its status
bus still observes the original internal error, heartbeat and BIST signals.

## Register contract

All addresses below require aligned 32-bit, single-beat accesses. Writes
require all four byte strobes. Unsupported values, size, alignment, read-only
writes, and invalid single-write framing return DECERR without a register
update. This is the existing CPU single-beat MMIO boundary; arbitrary malformed
multi-beat AXI streams are outside this check's scope.

| Address | Access | Meaning |
| --- | --- | --- |
| `0x10000400` | Read | Legacy ID `0x3144454c` |
| `0x10000404` | Read/write | Legacy LED0 value, `0` or `1`; writing reacquires LED0 |
| `0x10000408` | Read | Bank ID `0x3244454c` |
| `0x1000040c` | Read | Capability mask `0x2d` |
| `0x10000410` | Read | Latched manual values, initially `0` |
| `0x10000414` | Read | Manual ownership mask, initially `1` |
| `0x10000418` | Write | Atomic apply: `(mask << 8) | values` |
| `0x1000041c` | Write | Release selected bits to their automatic display |

APPLY requires a nonzero mask contained in `0x2d`, values contained in the
mask, and zero upper 16 bits. It updates the selected values and acquires the
selected ownership bits on one clock edge. Unselected bits remain unchanged.
RELEASE requires a nonzero supported mask and zero upper 24 bits; it clears
both the selected ownership bits and their shadow values. VALUES reports the
manual shadow, not a sampled automatic pin state. Reads of write-only
registers return DECERR.

## Reproduce

From `code/controller`, using an installed Verilator with a C++20 compiler:

```sh
python tests/multi_led/run_rtl.py --output /absolute/new-output-directory
```

The output directory must be new. `--verilator` selects a specific executable.
`--make-flags` optionally supplies local C++ make configuration. The isolated
Python wheel used for this review needed `CFG_CXXFLAGS_PCH_I=-include`; this
fixes that wheel's generated precompiled-header include option and does not
change RTL semantics or suppress a design diagnostic. The result records the
actual simulator version string, package version when available, full command
lines, source hashes, and whether inputs stayed unchanged.

`tb_bank.sv` instantiates the production `nx_ce64_local` and the actual
`nx_led_display_override` module from `led_native_top.v`. Both
`LOCAL_READ_PIPELINE=0` and `1` are simulated. Each configuration checks:

- All 80 nonempty supported-mask/value combinations, mixed per-lamp values,
  selection preservation, release, reset, and legacy LED0 reacquisition.
- Every unsupported or empty eight-bit mask, values outside the selection,
  reserved high bits, partial writes, wrong size/alignment, read-only writes,
  and invalid AWLEN/WLAST metadata for a single supplied write.
- Separate AW/W arrival order, response backpressure, atomic updates, and an
  already offered read response remaining stable during an independent write.
- All eight error/heartbeat/BIST status combinations under each tested manual
  ownership/value state.

The test does not substitute a software register bank, replay old output, or
run a vendor DDR/PLL model. The outer physical top is parsed to compile its
display selector, but is not elaborated as a complete board. Separately,
`tests/local_memory_v3/lint_board.py` can elaborate the real digital wrappers;
its existing FP diagnostic compatibility setting is documented by that tool.

No result here qualifies FPGA synthesis, place and route, timing, a generated
bitstream, physical LED observations, or real-board latency. The existing
vendor flow must regenerate the bound wrapper from the modified
`nx_t25_board_logic` and connect the two new buses before a new FPGA build.
