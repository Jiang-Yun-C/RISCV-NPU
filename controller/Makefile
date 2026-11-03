.DEFAULT_GOAL := opt05

.PHONY: opt16 opt16-prepare opt16-rtl opt16-negative opt16-numeric opt16-inputs opt16-memory opt16-static opt16-pds opt16-test opt16-verify opt16-accept opt16-finalize
opt16:
	$(PYTHON) scripts/run_opt16.py $(ARGS)
opt16-prepare:
	$(PYTHON) scripts/prepare_opt16.py $(ARGS)
opt16-rtl:
	$(PYTHON) scripts/run_opt16_rtl.py $(ARGS)
opt16-negative:
	$(PYTHON) scripts/run_opt16_negative.py $(ARGS)
opt16-numeric:
	$(PYTHON) scripts/run_opt16_numeric.py $(ARGS)
opt16-inputs:
	$(PYTHON) scripts/audit_opt16_inputs.py $(ARGS)
opt16-memory:
	$(PYTHON) scripts/audit_opt16_memory.py $(ARGS)
opt16-static:
	$(PYTHON) scripts/run_opt16_static.py $(ARGS)
opt16-pds:
	$(PYTHON) scripts/run_opt16_pds.py $(ARGS)
opt16-test:
	$(PYTHON) -m unittest tests.opt16.test_gate tests.optimization.test_opt05 -v
opt16-verify:
	$(PYTHON) scripts/verify_opt16.py $(ARGS)
opt16-accept:
	$(PYTHON) scripts/accept_opt16.py $(ARGS)
opt16-finalize:
	$(PYTHON) scripts/finalize_opt16.py $(ARGS)

.PHONY: opt15 opt15-test opt15-verify opt15-accept opt15-finalize
opt15:
	$(PYTHON) scripts/run_opt15.py $(ARGS)
opt15-test:
	$(PYTHON) -m unittest tests.opt15.test_assessment tests.optimization.test_opt05 -v
opt15-verify:
	$(PYTHON) scripts/verify_opt15.py $(ARGS)
opt15-accept:
	$(PYTHON) scripts/accept_opt15.py $(ARGS)
opt15-finalize:
	$(PYTHON) scripts/finalize_opt15.py $(ARGS)

.PHONY: opt14 opt14-baseline opt14-test opt14-verify opt14-finalize
opt14:
	$(PYTHON) scripts/run_opt14.py $(ARGS)
opt14-baseline:
	$(PYTHON) scripts/run_opt14_baseline.py $(ARGS)
opt14-test:
	$(PYTHON) -m unittest tests.opt14.test_assessment tests.optimization.test_opt05 -v
opt14-verify:
	$(PYTHON) scripts/verify_opt14.py $(ARGS)
opt14-finalize:
	$(PYTHON) scripts/finalize_opt14.py $(ARGS)

.PHONY: opt12 opt12-component opt12-numeric opt12-quality opt12-ooc opt12-negative opt12-accept opt12-verify opt12-finalize opt12-test
opt12:
	$(PYTHON) scripts/run_opt12.py $(ARGS)
opt12-component:
	$(PYTHON) scripts/run_opt12_component.py $(ARGS)
opt12-numeric:
	$(PYTHON) scripts/run_opt12_numeric.py $(ARGS)
opt12-quality:
	$(PYTHON) scripts/run_opt12_quality.py $(ARGS)
opt12-ooc:
	$(PYTHON) scripts/run_opt12_ooc.py $(ARGS)
opt12-negative:
	$(PYTHON) scripts/replay_opt12_negative.py $(ARGS)
opt12-accept:
	$(PYTHON) scripts/accept_opt12.py $(ARGS)
opt12-verify:
	$(PYTHON) scripts/verify_opt12.py $(ARGS)
opt12-finalize:
	$(PYTHON) scripts/finalize_opt12.py $(ARGS)
opt12-test:
	$(PYTHON) -m pytest -q tests/opt12/test_contract.py

.PHONY: opt11 opt11-component opt11-numeric opt11-quality opt11-ooc opt11-negative opt11-accept opt11-verify opt11-finalize
opt11:
	$(PYTHON) scripts/run_opt11.py $(ARGS)
opt11-component:
	$(PYTHON) scripts/run_opt11_component.py $(ARGS)
opt11-numeric:
	$(PYTHON) scripts/run_opt11_numeric.py $(ARGS)
opt11-quality:
	$(PYTHON) scripts/run_opt11_quality.py $(ARGS)
opt11-ooc:
	$(PYTHON) scripts/run_opt11_ooc.py $(ARGS)
opt11-negative:
	$(PYTHON) scripts/replay_opt11_negative.py $(ARGS)
opt11-accept:
	$(PYTHON) scripts/accept_opt11.py $(ARGS)
opt11-verify:
	$(PYTHON) scripts/verify_opt11.py $(ARGS)
opt11-finalize:
	$(PYTHON) scripts/finalize_opt11.py $(ARGS)

.PHONY: opt10 opt10-verify opt10-accept opt10-finalize
opt10:
	$(PYTHON) scripts/run_opt10.py $(ARGS)
opt10-verify:
	$(PYTHON) scripts/verify_opt10.py $(ARGS)
opt10-accept:
	$(PYTHON) scripts/accept_opt10.py $(ARGS)
opt10-finalize:
	$(PYTHON) scripts/finalize_opt10.py $(ARGS)

.PHONY: opt09 opt09-test opt09-numeric opt09-accept opt09-verify
opt09:
	$(PYTHON) scripts/run_opt09.py --stage rtl $(ARGS)
opt09-test:
	PYTHONPATH=$(CURDIR)/scripts:$(CURDIR) $(PYTHON) -m unittest tests.opt09.test_contract -v
opt09-numeric:
	$(PYTHON) scripts/run_opt09.py --stage numeric $(ARGS)
opt09-accept:
	$(PYTHON) scripts/accept_opt09.py $(ARGS)
opt09-verify:
	$(PYTHON) scripts/verify_opt09.py $(ARGS)

.PHONY: opt08 opt08-test opt08-numeric opt08-copy opt08-accept opt08-verify
opt08:
	$(PYTHON) scripts/run_opt08.py $(ARGS)
opt08-test:
	PYTHONPATH=$(CURDIR)/scripts:$(CURDIR) $(PYTHON) -m unittest tests.opt08.test_host tests.opt07.test_gate tests.opt06.test_gate -v
opt08-numeric:
	$(PYTHON) scripts/run_opt08_numeric.py $(ARGS)
opt08-copy:
	$(PYTHON) scripts/run_opt08_copy.py $(ARGS)
opt08-accept:
	$(PYTHON) scripts/accept_opt08.py $(ARGS)
opt08-verify:
	$(PYTHON) scripts/verify_opt08.py $(ARGS)

.PHONY: opt07 opt07-test opt07-verify opt07-batch opt07-accept
opt07:
	$(PYTHON) scripts/run_opt07.py $(ARGS)
opt07-test:
	$(PYTHON) -m unittest tests.opt07.test_host tests.opt07.test_gate -v
opt07-verify:
	$(PYTHON) scripts/verify_opt07.py $(ARGS)
opt07-batch:
	$(PYTHON) scripts/run_opt07_batch.py $(ARGS)
opt07-accept:
	$(PYTHON) scripts/accept_opt07.py $(ARGS)

.PHONY: opt06 opt06-test opt06-verify opt06-accept
opt06:
	$(PYTHON) scripts/run_opt06.py $(ARGS)
opt06-test:
	$(PYTHON) -m unittest tests.opt06.test_host tests.opt06.test_gate software.demo_console.tests.test_server tests.board_llm.test_competition_opt_v1_short -v
	$(PYTHON) scripts/test_opt06_browser.py
	$(PYTHON) scripts/test_opt06_ui.py
opt06-accept:
	$(PYTHON) scripts/accept_opt06.py $(ARGS)
opt06-verify:
	$(PYTHON) scripts/verify_opt06.py $(ARGS)

PYTHON ?= /home/Jiang/.local/bin/npu-python

.PHONY: opt05 opt05-test
opt05:
	$(PYTHON) scripts/run_opt05.py $(ARGS)
opt05-test:
	$(PYTHON) -m unittest tests.optimization.test_opt05 -v

.PHONY: smoke test acceptance t00 t02-fetch t02-dev t02 t02-test t02-v1-dev t02-v1 t02-train t03 t03-acceptance t04 t04-acceptance t04-test t05 t05-test t05-capacity t06 t07 t07-probe t08 t08-test t09 t09-smoke t09-test t10 t10-test clean help
smoke:
	$(PYTHON) scripts/run_smoke.py

.PHONY: pds-check pds2024-check
pds-check:
	$(PYTHON) scripts/check_pds.py $(ARGS)

pds2024-check:
	/usr/local/bin/pds2024-run $(PYTHON) scripts/check_pds.py --contract docs/spec/pds-toolchain-2024.2-global.json $(ARGS)

.PHONY: t22 t22-smoke t22-acceptance
t22:
	$(PYTHON) scripts/run_cocotb.py --task T22 --suite regression $(ARGS)
t22-smoke:
	$(PYTHON) scripts/run_cocotb.py --task T22 --suite smoke $(ARGS)
t22-acceptance:
	$(PYTHON) scripts/qualify_t22.py $(ARGS)

.PHONY: t23 t23-smoke t23-acceptance t23-verify t23-native t23-synth t23-test t23-netlist
t23:
	$(PYTHON) scripts/run_cocotb.py --task T23 --suite regression $(ARGS)
t23-smoke:
	$(PYTHON) scripts/run_cocotb.py --task T23 --suite smoke $(ARGS)
t23-native:
	$(PYTHON) scripts/run_t23_native.py $(ARGS)
t23-synth:
	$(PYTHON) scripts/run_t23_synth.py $(ARGS)
t23-netlist:
	$(PYTHON) scripts/run_t23_netlist.py $(ARGS)
t23-test:
	$(PYTHON) -m unittest discover -s tests/ddr -p 'test_*.py' -v

.PHONY: t23-board-prepare t23-board-sim t23-board
t23-board-prepare:
	$(PYTHON) scripts/pds/prepare_t23_board.py $(ARGS)

t23-board-sim:
	$(PYTHON) scripts/run_t23_board_sim.py $(ARGS)

t23-board:
	$(PYTHON) scripts/run_t23_board.py $(ARGS)
t23-verify:
	$(PYTHON) scripts/run_cocotb.py --task T23 --verify-archive $(ARCHIVE)
t23-acceptance:
	$(PYTHON) scripts/qualify_t23.py $(ARGS)

.PHONY: t24 t24-smoke t24-regression t24-verify t24-fabric t24-synth t24-static t24-test
t24:
	$(PYTHON) scripts/run_t24.py --suite full $(ARGS)
t24-smoke:
	$(PYTHON) scripts/run_t24.py --suite smoke $(ARGS)
t24-regression:
	$(PYTHON) scripts/run_t24.py --suite regression $(ARGS)
t24-verify:
	$(PYTHON) scripts/run_t24.py --verify-archive $(ARCHIVE)
t24-fabric:
	$(PYTHON) scripts/run_t24_fabric.py $(ARGS)
t24-synth:
	$(PYTHON) scripts/run_t24_synth.py $(ARGS)
t24-static:
	$(PYTHON) scripts/run_spyglass.py --config configs/t24-spyglass.json --stage all $(ARGS)
t24-test:
	$(PYTHON) -m unittest discover -s tests/board_soc -p 'test_*.py' -v

t00:
	$(PYTHON) scripts/run_t00.py

t03:
	$(PYTHON) scripts/run_t03.py

t03-acceptance:
	$(PYTHON) scripts/accept_t03.py

t04 t04-acceptance:
	$(PYTHON) scripts/run_t04.py

t04-test:
	$(PYTHON) -m unittest discover -s tests/models -p 'test_*.py' -v

t05:
	$(PYTHON) scripts/run_t05.py

t05-test:
	$(PYTHON) -m unittest discover -s tests/vectors -p 'test_*.py' -v

t05-capacity:
	$(PYTHON) model_tools/capacity.py

t06:
	$(PYTHON) scripts/run_t06.py

t07:
	$(PYTHON) scripts/run_t07.py

t07-probe:
	$(PYTHON) scripts/run_t07.py --probe

.PHONY: spyglass spyglass-lint spyglass-cdc spyglass-rdc spyglass-all spyglass-doctor spyglass-test
spyglass spyglass-lint:
	$(PYTHON) scripts/run_spyglass.py --stage lint $(ARGS)
spyglass-cdc:
	$(PYTHON) scripts/run_spyglass.py --stage cdc $(ARGS)
spyglass-rdc:
	$(PYTHON) scripts/run_spyglass.py --stage rdc $(ARGS)
spyglass-all:
	$(PYTHON) scripts/run_spyglass.py --stage all $(ARGS)
spyglass-doctor:
	$(PYTHON) scripts/run_spyglass.py --doctor --stage all $(ARGS)
spyglass-test:
	$(PYTHON) -m unittest discover -s tests/spyglass -p 'test_*.py' -v

t08:
	$(PYTHON) scripts/run_t08.py

.PHONY: t21 t21-smoke t21-regression t21-verify
t21:
	$(PYTHON) scripts/run_t21.py --suite full $(ARGS)
t21-smoke:
	$(PYTHON) scripts/run_t21.py --suite smoke $(ARGS)
t21-regression:
	$(PYTHON) scripts/run_t21.py --suite regression $(ARGS)
t21-verify:
	$(PYTHON) scripts/run_t21.py --verify-archive $(ARCHIVE)

t09:
	$(PYTHON) scripts/run_cocotb.py --task T09 --suite regression

t09-smoke:
	$(PYTHON) scripts/run_cocotb.py --task T09 --suite smoke

t09-test:
	$(PYTHON) -m unittest discover -s tests/cocotb/unit -v

t08-test:
	$(PYTHON) -m unittest discover -s tests/contracts -p 'test_*.py' -v

t10:
	$(PYTHON) scripts/run_t10.py

t10-test:
	$(PYTHON) -m unittest discover -s tests/model_pack -p 'test_*.py' -v

.PHONY: t11 t11-test
t11:
	$(PYTHON) scripts/run_t11.py

t11-test:
	$(PYTHON) -m unittest discover -s tests/reference -p 'test_*.py' -v

.PHONY: t12 t12-smoke t12-test t12-full-cpu
t12:
	$(PYTHON) scripts/run_t12.py

t12-smoke:
	$(PYTHON) scripts/run_t12.py --suite smoke

t12-test:
	$(PYTHON) -m unittest discover -s tests/streaming -p 'test_*.py' -v
	$(PYTHON) -m unittest discover -s tests/accel -p 'test_*.py' -v
	$(PYTHON) -m unittest discover -s tests/runtime -p 'test_*.py' -v

t12-full-cpu:
	$(PYTHON) software/runtime/run_cpu.py $(ARGS)

test:
	$(PYTHON) -m unittest discover -s tests/spyglass -p 'test_*.py' -v
	$(PYTHON) -m unittest discover -s tests/application/t20 -p 'test_*.py' -v
	$(PYTHON) -m unittest discover -s tests/end_to_end -p 'test_*.py' -v
	$(PYTHON) -m unittest discover -s tests/boot/sd -p 'test_*.py' -v
	$(PYTHON) -m unittest discover -s tests/boot/uart -p 'test_*.py' -v
	$(PYTHON) -m unittest discover -s tests/soc_accel -p 'test_*.py' -v
	$(PYTHON) -m unittest discover -s tests/linear -p 'test_*.py' -v
	$(PYTHON) -m unittest discover -s tests/streaming -p 'test_*.py' -v
	$(PYTHON) -m unittest discover -s tests/accel -p 'test_*.py' -v
	$(PYTHON) -m unittest discover -s tests/runtime -p 'test_*.py' -v
	$(PYTHON) -m unittest discover -s tests/reference -p 'test_*.py' -v
	$(PYTHON) -m unittest discover -s tests/model_pack -p 'test_*.py' -v
	$(PYTHON) -m unittest discover -s tests/cocotb/unit -v
	$(PYTHON) -m unittest discover -s tests/smoke -p 'test_*.py' -v
	$(PYTHON) -m unittest discover -s tests/application -p 'test_*.py' -v
	$(PYTHON) -m unittest discover -s tests/application/v2 -p 'test_*.py' -v
	$(PYTHON) -m unittest discover -s tests/models -p 'test_*.py' -v
	$(PYTHON) -m unittest discover -s tests/vectors -p 'test_*.py' -v
	$(PYTHON) -m unittest discover -s tests/contracts -p 'test_*.py' -v

t02-fetch:
	$(PYTHON) scripts/fetch_t02_model.py --revision 7ae557604adf67be50417f59c2c2f167def9a775

t02-dev:
	$(PYTHON) scripts/application_v2/run_eval.py --split dev

t02:
	$(PYTHON) scripts/application_v2/run_eval.py --split heldout

t02-v1-dev:
	$(PYTHON) scripts/run_t02.py --split dev

t02-v1:
	$(PYTHON) scripts/run_t02.py --split heldout

t02-train:
	$(PYTHON) scripts/application_v2/run_train.py

t02-test:
	$(PYTHON) -m unittest discover -s tests/application -p 'test_*.py' -v
	$(PYTHON) -m unittest discover -s tests/application/v2 -p 'test_*.py' -v

acceptance:
	$(PYTHON) tests/smoke/acceptance.py

clean:
	$(PYTHON) scripts/run_smoke.py --clean

help:
	@echo 'make t23 [ARGS=--run-id NEW_ID] : 32/64/128-bit DDR adapter VCS/cocotb matrix; physical acceptance remains separate'
	@echo 'make t23-native / t23-synth : native controller DFI integration / component ADS synthesis, no board operation'
	@echo 'make t22 [ARGS=--run-id NEW_ID] : VCS/cocotb platform component regression; board/timing acceptance remains separate'
	@echo 'make t22-acceptance ARGS="--run-id NEW_ID --component DIR --minimum DIR --native-replay DIR --minimum-board DIR --timing-coverage DIR" : formal T22 receipt gate'
	@echo 'make pds-check [ARGS=--synthesize] : global PDS identity, licensed Tcl and optional sandbox ADS synthesis; fresh evidence'
	@echo 'make pds2024-check [ARGS=--synthesize] : named global PDS 2024.2 in its isolated license namespace; fresh evidence'
	@echo 'make spyglass-lint / spyglass-cdc / spyglass-rdc / spyglass-all : fresh report-gated static analysis; ARGS supports --scope and --cpu-build'
	@echo 'make spyglass-doctor / spyglass-test : FlexNet readiness / acceptance negative controls without a license'
	@echo 'make t18 / t18-smoke / t18-test : real SPI SD boot, model streaming, errors and file-level full package checks'
	@echo 'make t17 / t17-smoke / t17-test : real UART RX/TX boot, recovery and cached reloading / protocol tests'
	@echo 'make t12 / t12-smoke / t12-test : RV32 static runtime, original tokenizer, real CPU + independent scoreboards'
	@echo 'make t12-full-cpu ARGS="--text 打开客厅灯。" : full frozen W8 model with the portable C runtime on host CPU'
	@echo 'make t10 / t10-test : full W8 package, independent roundtrip, fixtures, budget / reader fault regression'
	@echo 'make t08 / t08-test : backend contract, memory/API consistency, host/RV32 header checks / boundary tests'
	@echo 'make t00 : scope, unresolved qualifications, task handoff and source evidence audit'
	@echo 'make t07 / t07-probe : real RVV external-memory evaluation / one GEMV probe'
	@echo 'make t06 : locked Coral scalar/RVV RTL, AXI loading, VCS execution and negative controls'
	@echo 'make t05 : frozen W8A8 reference, full-shape vectors, independent checks and replay'
	@echo 'make t05-test / t05-capacity : numeric edge cases / logical model capacity and MACs'
	@echo 'make t04 / t04-acceptance : sparse AXI memory, VCS timing/image matrix and negative controls'
	@echo 'make t04-test : checked ELF/BIN loader regressions without VCS'
	@echo 'make t03 : generate RV32IM, build soft-float firmware, execute real CPU in VCS'
	@echo 'make t03-acceptance : two isolated rebuilds plus held-reset/corrupt-evidence negative controls'
	@echo 'make t02-fetch : verify/download official base; adapted release has its own model lock'
	@echo 'make t02-dev / t02 : frozen adapted FP32 release dev / heldout evaluation'
	@echo 'make t02-v1-dev / t02-v1 : preserve original unadapted baseline (quality failure expected)'
	@echo 'make t02-train : new adaptation experiment; never overwrites the frozen release'
	@echo 'make t02-test : application scorer and dataset regression (no GPU/model required)'
	@echo 'make smoke : T01 checks in fresh build/T01/<run-id> and evidence/T01/<run-id>'
	@echo 'make test  : runner/checker regression tests (no VCS license required)'
	@echo 'make acceptance : clean reruns and intentional failure/timeout checks'
	@echo 'make clean : remove only build/; preserve all evidence'

.PHONY: t13 t13-smoke t13-test
t13:
	$(PYTHON) scripts/run_cocotb.py --task T13 --suite regression

t13-smoke:
	$(PYTHON) scripts/run_cocotb.py --task T13 --suite smoke

t13-test:
	$(PYTHON) -m unittest discover -s tests/streaming -p 'test_*.py' -v
	$(PYTHON) -m unittest discover -s tests/accel -p 'test_*.py' -v

.PHONY: t14 t14-smoke t14-test
t14:
	$(PYTHON) scripts/run_t14.py

t14-smoke:
	$(PYTHON) scripts/run_t14.py --suite smoke

t14-test:
	$(PYTHON) -m unittest discover -s tests/streaming -p 'test_*.py' -v

.PHONY: t15 t15-smoke t15-regression t15-test
t15:
	$(PYTHON) scripts/run_t15.py --suite full

t15-smoke:
	$(PYTHON) scripts/run_t15.py --suite smoke

t15-regression:
	$(PYTHON) scripts/run_t15.py --suite regression

t15-test:
	$(PYTHON) -m unittest discover -s tests/linear -p 'test_*.py' -v

.PHONY: t16 t16-smoke t16-regression t16-test
t16:
	$(PYTHON) scripts/run_t16.py --suite full

t16-smoke:
	$(PYTHON) scripts/run_t16.py --suite smoke

t16-regression:
	$(PYTHON) scripts/run_t16.py --suite regression

t16-test:
	$(PYTHON) -m unittest discover -s tests/soc_accel -p 'test_*.py' -v

.PHONY: t17 t17-smoke t17-regression t17-test
t17:
	$(PYTHON) scripts/run_t17.py --suite full
t17-smoke:
	$(PYTHON) scripts/run_t17.py --suite smoke
t17-regression:
	$(PYTHON) scripts/run_t17.py --suite regression
t17-test:
	$(PYTHON) -m unittest discover -s tests/boot/uart -p 'test_*.py' -v

.PHONY: t18 t18-smoke t18-regression t18-test
t18:
	$(PYTHON) scripts/run_t18.py --suite full
t18-smoke:
	$(PYTHON) scripts/run_t18.py --suite smoke
t18-regression:
	$(PYTHON) scripts/run_t18.py --suite regression
t18-test:
	$(PYTHON) -m unittest discover -s tests/boot/sd -p 'test_*.py' -v

.PHONY: t19 t19-smoke t19-regression t19-test
t19:
	$(PYTHON) scripts/run_t19.py --suite full
t19-smoke:
	$(PYTHON) scripts/run_t19.py --suite smoke
t19-regression:
	$(PYTHON) scripts/run_t19.py --suite regression
t19-test:
	$(PYTHON) -m unittest discover -s tests/end_to_end -p 'test_*.py' -v

.PHONY: t20 t20-smoke t20-test
t20:
	$(PYTHON) scripts/run_cocotb.py --task T20 --suite full
t20-smoke:
	$(PYTHON) scripts/run_cocotb.py --task T20 --suite smoke
t20-test:
	$(PYTHON) -m unittest discover -s tests/application/t20 -p 'test_*.py' -v

.PHONY: t26-test t26-preflight
t26-test:
	$(PYTHON) -m unittest discover -s tests/application/t26 -p 'test_*.py' -v
t26-preflight:
	$(PYTHON) scripts/run_t26_preflight.py $(ARGS)

.PHONY: demo-console demo-console-test
demo-console:
	$(PYTHON) software/demo_console/server.py --open $(ARGS)
demo-console-test:
	$(PYTHON) -m unittest discover -s software/demo_console/tests -p 'test_*.py' -v

.PHONY: opt13 opt13-transport opt13-runtime opt13-host opt13-numeric opt13-verify
opt13: opt13-transport
opt13-transport:
	$(PYTHON) scripts/run_opt13_transport.py $(ARGS)
opt13-runtime:
	$(PYTHON) scripts/run_opt13_runtime.py $(ARGS)
opt13-host:
	$(PYTHON) scripts/run_opt13_host.py $(ARGS)
opt13-numeric:
	$(PYTHON) scripts/run_opt13_numeric.py $(ARGS)
opt13-verify:
	$(PYTHON) scripts/verify_opt13.py $(ARGS)
opt13-accept:
	$(PYTHON) scripts/accept_opt13.py $(ARGS)
opt13-finalize:
	$(PYTHON) scripts/finalize_opt13.py $(ARGS)
opt13-visible:
	$(PYTHON) scripts/run_opt13_visible.py $(ARGS)
opt13-host-adapter:
	$(PYTHON) scripts/run_opt13_host_adapter.py $(ARGS)
opt13-pack-wave:
	$(PYTHON) scripts/run_opt13_pack_wave.py $(ARGS)
