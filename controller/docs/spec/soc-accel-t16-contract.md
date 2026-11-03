# T16 CPU / Coral linear transport contract v1

Producer=T16; consumers=T19/T21/T24. Uses unchanged backend-api-v1,
linear-t15-v1, model-pack-v1, numeric-v1 and T08 physical addresses.
Implementation availability does not establish acceptance; DONE requires the
registered full matrix and independently rechecked archive.

The actual T09 hard-float VexRiscv boots from ROM at 0x10000, copies its static
input from CPU-private memory into the uncached workspace, and executes the
shared provider's FP32 quantization. The real shared memory fabric arbitrates
CPU I/D and Coral AW/W, AR, R and B channels. Its three controller user ports
preserve native widths and share the same behavioral DDR backing store;
accepted late B does not block unrelated CPU-private traffic. CPU native AXI writes upload and read back
the byte-identical accepted T15 Coral ELF (8KiB ITCM, 32KiB DTCM). No testbench
writes Coral TCM, submits work, initializes golden outputs or forces completion.

coral_linear.c acquires the bridge owner, clears old result/IRQ state, writes
all 96 request bytes and starts the real Coral core. Halt is notification; the
transport requires fault-free status, actual guard drain, a complete 104-byte
result, matching session/sequence and the required output row/tile counts before
release. On IO/core/numeric/identity error or timeout it isolates and retains
ownership. nx_reset_session drains accepted R/B before resetting the core,
reuploads ITCM, clears old completion, increments session and invalidates KV.

Optional wait returns periodically even when the completion IRQ is lost. The
qualification firmware uses real WFI plus externally supplied periodic machine
timer input (65536 cycles). Hardware integration must supply a working timer or
use the default polling path. IRQ acknowledgement never substitutes for status
and drain. The TB may mask/delay the halt notification or inject memory errors;
CPU instructions still submit, poll and consume results.

The provider's optional model_sealed callback accepts only exact immutable T10
views whose source payload and numeric validity were checked during PRELOAD.
It implements the existing loader seal in backend-api-v1; absent a seal, the
standalone full scan remains. Tensor bounds, all dynamic activation data,
quantization and Coral's per-weight/per-scale numeric checks remain mandatory.
Both CPU router and backend guard prohibit writes to model weights. PRELOAD is
a distinct test mode; UART/SD loading remains T17/T18.

Registered short regression uses seeds 1/7/19 plus exact seed-1 trace replay.
It covers all projection families with actual T05 inputs, a T11 Q fixture,
M1/M4/M8, reused workspace, N129 tail, lost/delayed IRQ, read SLVERR, write DECERR,
an accepted held B with timeout and unsuccessful premature reset, corrupted
private descriptions and a correct task after each error. The full suite adds
one uninterrupted M1/N151936/K896 head call. Every result store and every CPU
result read is independently matched to frozen producer output. No partitioned
run substitutes for the full submission.

Each case preserves absolute-cycle CPU/native/backend transactions, CPU reports,
XML, independent checks, input/output hashes and a VCD correlation report. Short
cases retain the whole VCD; head retains initial and completion/readback windows
while all AXI transactions remain in CSV. Cycle limit and wall-clock limit are
both finite. Isolated held-reset, wrong-reference, stale-completion, empty-test
and missing-XML controls must retain raw FAIL results.

Entry: make t16, make t16-regression, make t16-smoke. Archive verifier:
`npu-python scripts/run_t16.py --verify-archive evidence/T16/<run-id>`.
Board DDR/IP, FPGA timing and complete model/layer execution remain downstream.
