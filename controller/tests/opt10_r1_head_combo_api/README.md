This is the third experiment's head-only preparation, for the original
M1/N151936/K896 tied embedding at W=0x80000000, Sw=0x881d4000 and Y=0xac037800.
The baseline is exact frozen54; the intervention is exactly the seven-file
`a74c87ae4e8b0290abd825bfe8d1708323f95a2fc7619ada0638a010ea6c27bc` overlay.
RoPE is compiled as the real reference translation unit but never executed by
this one linear call. Its saving remains null.

`scripts/run_opt10_r1_head_combo_api.py --run-id NAME` prepares immutable shared
model inputs and compiles both actual RV32 firmware ELFs. It never builds or
executes a DUT by default. `--execute` requires an existing prepared contract
and a terminal independent gate/down budget acceptance file bound to the same
seven hashes and both earlier receipts. No such authorization is part of prep.
`--preflight --prepared-contract FILE --budget-acceptance FILE` performs only
read-only checks. The prepared contract itself must be bound by its terminal
PASS parent manifest artifact hash; both firmware arms, physical addresses and
the complete shared-input shape must also match before execution can start.

Input is the original independently frozen oracle's `24_final_norm`; golden
logits are independently frozen `24_logits`. The actual nxpack bytes and
production full_weights.h addresses must agree. Quantization, all integer dots
and separate FP32 product/value/ordered partials are regenerated independently
and checked against that golden. Both arms reference the same read-only files;
they have distinct actual firmware and load plans. These are postload fixture
regions, without an authenticated loader/startup/service claim.

The inherited original full-N/head observer contract used a 600M aggregate
cycle deadline and 10800s wall deadline. They are explicitly the head fixture's
verification envelope, distinct from the full169 600M verification envelope.
The production call protection remains 900M, complete API target remains 250M,
and clock remains 125MHz. Native stall limit65536 and write drain1024 are the
exact54 SoC settings; neither becomes a new timeout qualification.

All consumers and actual backend/native transport remain logged and reviewed.
The frozen streaming checker8d0e9c24… and its independent offline-v2 comparison
are required. Numeric JSON stores only summary values and an output.bin hash;
raw is retained completely, never copied into memory with list(csv.reader).
Two complete raw files for approximately2.13M groups will be large; prep makes
no runtime or head memory prediction. Any future run must seal raw only after
all writable-phase output/Aq/Sa inspections, terminal transport stability and
producer exit. The old ReadOnly-phase peek write is absent.

The original41 full graph took about5h49m; that is a historical full169 runtime,
not a prediction that component savings shorten this head or the next graph.
All prep performance, fullgraph, TTFT, frequency/resources and GO fields remain
null/false. This work creates no promotion candidate and does not authorize
OPT17 or any board operation.
