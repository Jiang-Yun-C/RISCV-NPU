# T14 real Coral streaming component

`make t14` rebuilds the accepted RvvCoreMiniAxi RTL and the autonomous RVV
microprogram, then runs the registered VCS/cocotb matrix. Native AXI subordinate
writes upload and read back the entire 8KiB ITCM and 32KiB DTCM; external inputs
use the immutable T10 package addresses. No expected output is preloaded.

The three producer packages keep their whole-file hashes, tensor file offsets,
physical padding and SoC addresses. Independent byte checks cover each unique
weights-region payload; embedding/head aliases share one source. Tokenizer
payloads remain outside Coral permissions. K65 padding is copied and checked;
its arithmetic request is rejected under T08. `prepare.py` also rejects all 21
bad packs before any native submission and labels this desktop validation.

`check.py` reconstructs real R/W payloads and output ownership from passive
SystemVerilog AXI CSV. It verifies IDs, burst legality, last, strobes, exact
output bytes/strides, firmware payload counts and RTL handshake counters.
`waveform.py` independently checks the upload/first-20000-core-cycle VCD window
against this trace. `test_scoreboard.py` deliberately corrupts evidence to prove
that missing/duplicated data and forged counters fail.

Component scope: real Coral RVV + T13 guard + T04 sparse memory. T16 remains the
real VexRiscv-to-Coral submission/ownership loop; T15 remains full numerical
operator and vocabulary projection qualification. See
[streaming contract](../../docs/spec/streaming-t14-contract.md).
