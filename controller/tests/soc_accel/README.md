T16 connects the generated cached/FPU VexRiscv to the byte-identical accepted
T15 Coral RVV program through nx_accel_bridge and nx_accel_guard. Three T04
memory ports share one sparse store; CPU firmware is the only submitter.

`make t16-smoke` starts three actual CPU-driven projection jobs. `make t16-regression` runs the complete short normal/fault matrix at seeds 1/7/19,
seed-1 replay, five isolated failing controls and the project tests. `make t16`
also runs a single continuous 151936-row head request. The head case can take
several days in this detailed RTL simulator. It has a 950M-cycle limit and a
finite 168-hour wall limit; an actual timeout is a failure, never a pass.

Every normal/fault case has a CPU-built ELF, pinned T05/T10/T11 fixture, absolute
cycle transaction trace, independent checks, XML and indexed VCD. A correct
error response and recovery can pass. Deliberately broken checker/DUT evidence
retains a separate raw FAIL under evidence/T16_NEGATIVE.

`make t16-test` runs transport control unit tests without an RTL license.
`npu-python scripts/run_t16.py --verify-archive evidence/T16/<run-id>` repeats
hashes, source/config inventories, complete registered matrix, waveform/AXI
correlation and independent arithmetic/output-set checks.

PRELOAD boot, simulation clocks and behavioral memory are explicit. Hardware
DDRx, physical timing and full-model inference remain downstream tasks.
