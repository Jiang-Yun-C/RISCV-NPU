"""Read-only v3 reproduction: an old passing test permits a halted service.

The original service/main/runtime/tokenizer/stream and reduced real model run
on the host. This is protocol/control-flow evidence, never board performance.
The frozen source is imported but never edited; generated files stay in --out.
"""
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import shutil
import sys


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", type=Path, required=True,
                        help="Frozen v3 package root (read-only)")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    controller = args.baseline.resolve() / "code/controller"
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(controller))
    module = importlib.import_module("tests.production_streaming.test_enhancements")
    cls = module.ServiceEnhancementTests
    cls.setUpClass()
    try:
        names = [
            "test_cancel_stops_publication_at_current_production_fail_stop_boundary",
            "test_action_cancel_cannot_publish_or_execute",
        ]
        old_results = []
        for name in names:
            case = cls(name)
            case.debug()
            old_results.append({"name": name, "status": "PASS"})
        case = cls(names[0])
        commands = ":text 4 hello\n:text 2 hello\n"
        wire, states = case.run_service(commands, "cancel")
        (out / "v3-cancel-then-next.commands.txt").write_text(commands)
        (out / "v3-cancel-then-next.uart.txt").write_text(wire)
        (out / "v3-cancel-then-next.states.json").write_text(json.dumps(states, indent=2) + "\n")
        shutil.copy2(cls.directory / "service", out / "v3-native-service")
        facts = {
            "requested_model_commands": 2,
            "observed_request_records": wire.count("T25 REQUEST 1 "),
            "observed_metrics_records": wire.count("T25 METRICS "),
            "accepted_cancel": "status=accepted" in wire,
            "stream_abort_count": wire.count("T25 STREAM 1 ABORT "),
            "halted": "D27 HALTED" in wire,
            "ready_count_including_boot": wire.count("T25 READY\n"),
            "legacy_stores": states[-1]["legacy_stores"],
            "bank_stores": states[-1]["bank_stores"],
            "last_runtime_state": states[-1]["state"],
        }
        strict_pass = (not facts["halted"] and facts["observed_request_records"] == 2
                       and facts["observed_metrics_records"] >= 1)
        if strict_pass:
            raise AssertionError("Frozen v3 unexpectedly satisfies the stricter next-request oracle")
        if not all([facts["accepted_cancel"], facts["halted"], facts["observed_request_records"] == 1]):
            raise AssertionError("The reported v3 failure was not reproduced")
        files = ["firmware/runtime/board/main.c", "firmware/runtime/board/service_options.h",
                 "firmware/runtime/port/runtime.c", "firmware/runtime/port/stream.c",
                 "tests/production_streaming/native_main.c",
                 "tests/production_streaming/test_enhancements.py"]
        report = {
            "scope": "offline native production service + synthetic reduced model; no hardware/performance claim",
            "baseline": str(args.baseline.resolve()),
            "old_tests": old_results,
            "observed": facts,
            "strict_cancel_then_next_result": "FAIL_EXPECTED_REPRODUCED",
            "false_pass_reason": "The old tests explicitly require HALTED and do not require the queued next request to execute.",
            "source_sha256": {name: digest(controller / name) for name in files},
            "uart_sha256": digest(out / "v3-cancel-then-next.uart.txt"),
            "native_binary_sha256": digest(out / "v3-native-service"),
        }
        (out / "V3_REPRODUCTION.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
        print(json.dumps(report, indent=2, ensure_ascii=False))
    finally:
        cls.tearDownClass()


if __name__ == "__main__":
    main()
