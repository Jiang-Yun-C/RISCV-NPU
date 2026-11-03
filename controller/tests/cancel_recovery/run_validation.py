"""Cancellation recovery evidence from production C sources, without hardware.

Run from code/controller, or pass this file directly. Assets use the existing
two-block real Transformer geometry. Explicit next-ID fixtures provide JSON
and EOS only to exercise lifecycle/commit gates; no semantic or speed claim.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from tests.production_streaming.fixtures import write_assets

SOURCE_FILES = [
    "firmware/runtime/board/main.c", "firmware/runtime/board/service_options.h",
    "firmware/runtime/board/ce64_platform.c", "firmware/runtime/board/ce64_platform.h",
    "firmware/runtime/port/runtime.c", "firmware/runtime/port/runtime.h",
    "firmware/runtime/port/stream.c", "firmware/runtime/port/stream.h",
    "firmware/runtime/port/model.c", "firmware/runtime/port/prefix.c",
    "firmware/runtime/port/control.c", "firmware/runtime/port/tokenizer.c",
    "firmware/runtime/reference/nx_reference.c", "firmware/runtime/board/led_control.c",
    "firmware/drivers/accel/ce64_linear.c", "firmware/drivers/accel/ce64_linear.h",
    "firmware/drivers/accel/linear_api.c", "firmware/runtime/board/diag.c",
    "tests/production_streaming/native_main.c", "tests/production_streaming/fixtures.py",
    "tests/production_streaming/test_enhancements.py",
    "tests/cancel_recovery/run_validation.py", "tests/cancel_recovery/native_ce64_gates.c",
]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    temporary.replace(path)


def source_hashes():
    return {name: sha(ROOT / name) for name in SOURCE_FILES if (ROOT / name).exists()}


def fields(line):
    return {key: int(value, 16) for key, value in re.findall(r"(\w+)=([0-9a-f]{16})", line)}


def rows(wire, prefix):
    return [(index, line, fields(line)) for index, line in enumerate(wire.splitlines()) if line.startswith(prefix)]


def build_service(directory, enhanced=True, bank=False):
    directory.mkdir(parents=True, exist_ok=True)
    write_assets(directory, text_encoding=enhanced)
    macros = ["_GNU_SOURCE=", "NX_PORTABLE", "NX_OPT13_TEST", "NX_T25_UART", "NX_T25_SERVICE_TEST", "NX_DIAG_HOST"]
    if enhanced:
        macros += ["NX_T27_SERVICE_ENHANCEMENTS=1", "NX_PROFILE_INTEGER=1", "NX_PREFIX_CAPTURE=1"]
        spec = importlib.util.spec_from_file_location("recovery_build_identity", ROOT / "scripts/build_t27_streaming.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        _, header = module.runtime_identity(ROOT, ["-DNX_OPT13_TEST", "-DNX_PROFILE_INTEGER=1"], "synthetic-native-cancel-recovery")
        (directory / "t27_runtime_identity.h").write_text(header)
    if bank:
        macros.append("NX_LED_BANK=1")
    command = ["gcc", "-std=c11", "-O2", "-fno-strict-aliasing", "-ffp-contract=off", "-fno-fast-math",
               "-Wall", "-Wextra", "-Werror", "-Wno-misleading-indentation", "-Wno-unknown-pragmas"]
    command += ["-D" + value for value in macros]
    command += ["-include", str(ROOT / "firmware/runtime/board/diag.h"),
                "-idirafter", str(ROOT / "firmware/drivers/accel"), "-idirafter", str(ROOT / "software/include"),
                "-I", str(directory), "-I", str(ROOT / "firmware/runtime/port"),
                "-I", str(ROOT / "firmware/runtime/reference"),
                str(ROOT / "tests/production_streaming/native_main.c"), str(directory / "tokenizer.S")]
    names = ["runtime", "model", "tokenizer", "stream"] + (["prefix", "control"] if enhanced else [])
    command += [str(ROOT / ("firmware/runtime/port/" + name + ".c")) for name in names]
    command += [str(ROOT / path) for path in ["firmware/runtime/reference/nx_reference.c",
                "firmware/runtime/board/diag.c", "firmware/runtime/board/led_control.c", "firmware/application/application.c"]]
    binary = directory / "native-service"
    command += ["-lm", "-o", str(binary)]
    built = subprocess.run(command, capture_output=True, text=True, timeout=60)
    (directory / "compile.log").write_text(built.stdout + built.stderr)
    write_json(directory / "compile.json", {"argv": command, "macros": macros, "exit_code": built.returncode})
    if built.returncode:
        raise RuntimeError(built.stderr)
    binary.chmod(0o755)
    return {"binary": str(binary), "binary_sha256": sha(binary), "macros": macros,
            "enhancements_default_off": not enhanced,
            "compile_command": str(directory / "compile.json"),
            "fixture_model_header_sha256": sha(directory / "full_weights.h"),
            "fixture_tokenizer_sha256": sha(directory / "synthetic.nxt")}


CASES = [
    {"id": "text_prefill", "mode": "recovery-prefill", "phase": 1},
    {"id": "text_decode", "mode": "recovery-decode", "phase": 2},
    {"id": "text_stream0", "mode": "recovery-decode", "phase": 2, "stream0": True},
    {"id": "action_prefill", "mode": "recovery-prefill", "phase": 1, "action": True},
    {"id": "action_decode", "mode": "recovery-decode", "phase": 2, "action": True},
    {"id": "action_after_eos", "mode": "recovery-final", "phase": 3, "action": True, "after_eos": True},
    {"id": "action_stream0_after_eos", "mode": "recovery-final", "phase": 3, "action": True, "after_eos": True, "stream0": True},
    {"id": "bank_action_after_eos", "mode": "recovery-final", "phase": 3, "action": True, "after_eos": True, "bank": True},
    {"id": "cancel_then_action", "mode": "recovery-decode", "phase": 2, "action": True, "next_action": True},
    {"id": "bank_cancel_then_action", "mode": "recovery-decode", "phase": 2, "action": True, "next_action": True, "bank": True},
    {"id": "duplicate_stale", "mode": "recovery-duplicate", "phase": 2, "duplicate": True},
    {"id": "stale_only", "mode": "recovery-stale", "phase": 2, "stale_only": True},
    {"id": "partial_cancel_across_eos", "mode": "recovery-partial-eos", "partial": 16},
    {"id": "partial_cancel_lf_only", "mode": "recovery-partial-lf", "partial": 24},
    {"id": "partial_cancel_across_timeout", "mode": "recovery-partial-timeout", "partial": 16, "phase": 2, "terminal": "timeout"},
    {"id": "timeout_prefill", "mode": "recovery-timeout-prefill", "phase": 1, "terminal": "timeout"},
    {"id": "timeout_decode", "mode": "recovery-timeout-decode", "phase": 2, "terminal": "timeout"},
    {"id": "timeout_action_after_eos", "mode": "recovery-timeout-final", "action": True, "after_eos": True, "terminal": "timeout"},
    {"id": "timeout_compat_text", "mode": "recovery-timeout-text", "after_eos": True, "terminal": "timeout"},
    {"id": "fault_model_callback", "mode": "recovery-model-fault", "fatal": True},
    {"id": "fault_stack_guard", "mode": "recovery-stack-failure", "fatal": True},
    {"id": "fault_runtime_invalidation", "mode": "recovery-reset-failure", "fatal": True},
    {"id": "fault_recovery_reset", "mode": "recovery-recover-failure", "fatal": True},
    {"id": "fault_recovery_cancel_code", "mode": "recovery-recover-cancel-code", "fatal": True,
     "soft_error": "fffffff5", "reset_error": -11, "reset_at": 2},
    {"id": "fault_recovery_timeout_code", "mode": "recovery-recover-timeout-code", "fatal": True,
     "soft_error": "fffffff9", "reset_error": -7, "reset_at": 3},
]


def verify_case(case, wire, states):
    checks = []

    def require(value, name, observed=None):
        checks.append({"check": name, "passed": bool(value), "observed": observed})
        if not value:
            raise AssertionError(name + (": " + repr(observed) if observed is not None else ""))

    request = rows(wire, "T25 REQUEST 1 ")
    terminal = rows(wire, "T25 REQUEST_END 1 ")
    metrics = rows(wire, "T25 METRICS ")
    abort = rows(wire, "T25 STREAM 1 ABORT ")
    ready = [i for i, line in enumerate(wire.splitlines()) if line == "T25 READY"]
    summary = {
        "request_sessions": [row[2].get("session") for row in request],
        "metrics": [row[2] for row in metrics], "terminal_records": [row[1] for row in terminal],
        "abort_sessions": [row[2].get("session") for row in abort], "ready_line_indices": ready,
        "halted": "D27 HALTED" in wire,
        "store_counts": {"legacy": states[-1]["legacy_stores"], "bank": states[-1]["bank_stores"]} if states else None,
        "checks": checks,
    }
    try:
        require(bool(states), "native state snapshots are present")
        require(all(s.get("fixture_main_entries") == 1 and s.get("fixture_model_loads") == 1 for s in states),
                "all requests share one main entry and one model load", states)
        require(len(request) >= 1, "first actual model request was announced")
        old = request[0][2]["session"]
        if case.get("fatal"):
            require(summary["halted"], "genuine fault retains HALTED boundary")
            require(len(request) == 1 and not metrics and not terminal,
                    "failed protection gate cannot announce recovery or execute queued next request")
            require(not any(i > request[0][0] for i in ready), "no READY follows a failed protection gate", ready)
            require(states[-1]["legacy_stores"] == states[-1]["bank_stores"] == 0, "fault path performs zero LED stores")
            if case.get("soft_error"):
                lines = wire.splitlines()
                soft = [i for i, line in enumerate(lines) if line == "T25 ERROR " + case["soft_error"]]
                hard = [i for i, line in enumerate(lines) if line == "T25 ERROR fffffff8"]
                halt = next(i for i, line in enumerate(lines) if line == "D27 HALTED")
                require(states[-1].get("fixture_reset_error") == case["reset_error"]
                        and states[-1].get("fixture_reset_error_at") == case["reset_at"],
                        "real recovery reset callback returns the intended overlapping error code", states[-1])
                require(len(soft) == 1, "recovery failure never repeats a soft terminal error", soft)
                require(len(hard) == 1 and soft[0] < hard[0] < halt,
                        "overlapping recovery error becomes an explicit hard fault before HALTED",
                        {"soft_error": soft, "hard_error": hard, "halted": halt})
            summary["passed"] = True
            return summary
        require(not summary["halted"], "ordinary cancellation/timeout never halts healthy service")
        require(len(request) == 2, "queued next model request actually runs", len(request))
        new = request[1][2]["session"]
        require(new > old, "new request has a fresh increasing session", [old, new])
        summary["next_actual_request_session"] = new
        complete_first = case.get("stale_only") or (case.get("partial") and not case.get("terminal"))
        expected_metrics = 2 if complete_first else 1
        require(len(metrics) == expected_metrics, "only successful model requests have METRICS", len(metrics))
        require(metrics[-1][2]["session"] == new and metrics[-1][2]["stop"] == 1,
                "next actual request reaches EOS with its own METRICS", metrics[-1][2])
        second = "\n".join(wire.splitlines()[request[1][0]:])
        ids = rows(second, "T25 IDS ")
        require(len(ids) == 1 and ids[0][1].split()[-1] == "0002505d", "next result carries actual final EOS ID")
        require(any(i > metrics[-1][0] for i in ready), "next request has real READY after final metrics", ready)
        require(states[-1]["state"] == 3 and states[-1]["stop"] == 1,
                "runtime is STOPPED by EOS after next real model execution", states[-1])
        expected_stores = 1 if case.get("next_action") else 0
        require(states[-1]["bank_stores"] == (expected_stores if case.get("bank") else 0)
                and states[-1]["legacy_stores"] == (0 if case.get("bank") else expected_stores),
                "only an explicitly requested successful next action may store", summary["store_counts"])
        if complete_first:
            if case.get("stale_only"):
                require("status=stale" in wire and "status=accepted" not in wire, "wrong-session cancel is observed as stale")
            require(not abort and not terminal and "T25 ERROR" not in wire, "non-accepted cancel does not terminate either request")
        else:
            require(len(abort) == 1 and abort[0][2]["session"] == old,
                    "old stream emits exactly one ABORT bound to old session", summary["abort_sessions"])
            require(len(terminal) == 1 and terminal[0][2]["session"] == old,
                    "exactly one checked REQUEST_END belongs to cancelled request", summary["terminal_records"])
            require(terminal[0][2]["next_session"] == old + 1,
                    "terminal records recovered idle session (not next model begin)", terminal[0][2])
            status = case.get("terminal", "cancelled")
            require("status=" + status in terminal[0][1], "terminal reason is explicit", terminal[0][1])
            require(new > terminal[0][2]["next_session"], "next model begin occurs after recovered idle session")
            inter_ready = [i for i in ready if terminal[0][0] < i < request[1][0]]
            require(abort[0][0] < terminal[0][0] and bool(inter_ready),
                    "old ABORT then recovery terminal then READY precede next request",
                    {"abort": abort[0][0], "terminal": terminal[0][0], "ready": inter_ready, "next_request": request[1][0]})
            require(not any(request[0][0] < i < terminal[0][0] for i in ready),
                    "no early READY precedes complete recovery checks")
            first_snapshot = next(s for s in states if s["fixture_commands"] == (2 if case.get("stream0") else 1))
            require(first_snapshot["state"] == 0 and first_snapshot["kv"] == 0 and first_snapshot["generated"] == 0,
                    "recovered cancelled request is IDLE without stale KV/publication", first_snapshot)
            require(first_snapshot["legacy_stores"] == first_snapshot["bank_stores"] == 0,
                    "cancelled request itself performs zero LED stores", first_snapshot)
            require(request[1][2]["prefix_hit"] == 0, "next request cannot reuse invalidated cancelled prefix")
            if case.get("phase"):
                require(first_snapshot["fixture_injected_phase"] == case["phase"],
                        "cancellation/timeout was injected at the intended real phase", first_snapshot["fixture_injected_phase"])
            before_next = "\n".join(wire.splitlines()[:request[1][0]])
            require("T25 METRICS " not in before_next, "cancelled preview cannot acquire final model metrics")
            if case.get("after_eos"):
                require("0002505d" in before_next, "final-boundary fixture actually reached EOS before cancellation/timeout")
                if not case.get("stream0"):
                    end = rows(before_next, "T25 STREAM 1 END ")
                    require(len(end) == 1 and end[0][0] < abort[0][0], "ABORT revokes an already emitted END")
            if case.get("stream0"):
                require("T25 STREAM 1 BEGIN" not in wire and "T25 STREAM 1 TOKEN" not in wire and "T25 STREAM 1 TEXT" not in wire,
                        "stream0 preserves disabled previews while emitting terminal ABORT")
            if case.get("duplicate"):
                require(wire.count("status=accepted") == 1 and "status=finished" in before_next and "status=stale" in second,
                        "duplicate is finished at idle and old replay is stale in next session")
        if case.get("partial"):
            handed_off = next(s for s in states if s["fixture_commands"] == 1)
            require(handed_off["control_partial_used"] == case["partial"],
                    "actual active parser retains partial cancel bytes across READY", handed_off)
            completed_cancel = [row for row in rows(wire, "T25 CONTROL 1 ") if "status=finished" in row[1] and row[2]["session"] == old]
            require(len(completed_cancel) == 1, "idle suffix completes exactly one cancel for the finished session")
            boundary_ready = [i for i in ready if request[0][0] < i < completed_cancel[0][0]]
            require(bool(boundary_ready) and completed_cancel[0][0] < request[1][0],
                    "partial cancel yields finished after READY and before next model request")
            require("status=accepted" not in wire and "status=rejected" not in wire,
                    "split valid cancel never becomes a malformed or new active request")
        summary["passed"] = True
    except AssertionError as error:
        summary["passed"] = False
        summary["failure"] = str(error)
    return summary


def run_case(case, build, out):
    directory = out / "uart"
    directory.mkdir(parents=True, exist_ok=True)
    first = ":actm 36 打开灯" if case.get("bank") else ":act 打开灯" if case.get("action") else ":text 8 first request"
    second = (":actm 36 打开灯" if case.get("bank") else ":act 打开灯") if case.get("next_action") else ":text 8 next real request"
    commands = (":stream 0\n" if case.get("stream0") else "") + first + "\n" + second + "\n"
    run = subprocess.run([build["binary"], case["mode"]], input=commands.encode(), capture_output=True, timeout=30)
    wire = run.stdout.decode("utf-8")
    states = [json.loads(line) for line in run.stderr.decode().splitlines()] if run.returncode == 0 else []
    stem = directory / case["id"]
    Path(str(stem) + ".uart.txt").write_bytes(run.stdout)
    Path(str(stem) + ".stderr.txt").write_bytes(run.stderr)
    Path(str(stem) + ".commands.txt").write_text(commands)
    write_json(str(stem) + ".states.json", states)
    result = verify_case(case, wire, states) if run.returncode == 0 else {"passed": False, "failure": "native exit " + str(run.returncode)}
    result.update({"id": case["id"], "fixture_mode": case["mode"], "scope": "production main/runtime/stream + reduced real model + explicit next-ID fixture",
                   "build": "bank" if case.get("bank") else "legacy", "exit_code": run.returncode,
                   "raw_uart": str(Path(str(stem) + ".uart.txt")), "raw_uart_sha256": hashlib.sha256(run.stdout).hexdigest(),
                   "state_snapshots": str(Path(str(stem) + ".states.json")), "commands": str(Path(str(stem) + ".commands.txt"))})
    write_json(str(stem) + ".result.json", result)
    print(("PASS " if result["passed"] else "FAIL ") + case["id"] + (": " + result["failure"] if not result["passed"] else ""))
    return result


def feature_off(build, out):
    commands = ":stream 0\n:ids 3 1 2 3\n"
    run = subprocess.run([build["binary"], "stack-failure"], input=commands.encode(), capture_output=True, timeout=20)
    wire = run.stdout.decode()
    path = out / "feature_off.uart.txt"
    path.write_bytes(run.stdout)
    states = [json.loads(line) for line in run.stderr.decode().splitlines()]
    passed = (run.returncode == 0 and "T25 ERROR" in wire and "T25 STREAM 1" not in wire
              and "T25 REQUEST_END" not in wire and "D27 HALTED" not in wire
              and states[-1]["state"] == 4 and states[-1]["legacy_stores"] == 0)
    result = {"id": "default_feature_off_stream0_fault", "passed": passed,
              "scope": "enhancements macro omitted; original stream0 failure wire compatibility",
              "macros": build["macros"], "raw_uart": str(path), "raw_uart_sha256": sha(path), "states": states}
    write_json(out / "feature_off.result.json", result)
    print(("PASS " if passed else "FAIL ") + result["id"])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--skip-ce64", action="store_true", help="Only during development; recorded as NOT_RUN")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    write_json(out / "RESULT.json", {"passed": False, "status": "RUNNING", "scope": "offline native validation"})
    before = source_hashes()
    builds = {"legacy": build_service(out / "build/legacy"),
              "bank": build_service(out / "build/bank", bank=True),
              "feature_off": build_service(out / "build/feature_off", enhanced=False)}
    results = [run_case(case, builds["bank" if case.get("bank") else "legacy"], out) for case in CASES]
    results.append(feature_off(builds["feature_off"], out))
    gates = {"status": "NOT_RUN", "reason": "explicit --skip-ce64 development run"}
    if not args.skip_ce64:
        gates = run_ce64_gates(out)
    after = source_hashes()
    stable = before == after
    report = {"schema": "nexusrv-cancel-recovery-validation/1", "scope": "offline C/native protocol and protection gates; synthetic model/ID/MMIO fixtures; no board or speed measurement",
              "passed": all(row["passed"] for row in results) and gates.get("passed", False) and stable,
              "production_service_cases_passed": sum(row["passed"] for row in results),
              "production_service_case_count": len(results), "source_unchanged_during_run": stable,
              "source_sha256": before, "source_sha256_after": after, "builds": builds,
              "cases": results, "ce64_protection_gates": gates,
              "not_run": ["real FPGA", "physical LEDs", "production 0.5B model", "full-board RTL simulation", "PnR/bitstream/ELF deployment"]}
    write_json(out / "RESULT.json", report)
    print(json.dumps({"result": str(out / "RESULT.json"), "passed": report["passed"],
                      "service_cases": f"{report['production_service_cases_passed']}/{len(results)}", "source_stable": stable}, indent=2))
    return 0 if report["passed"] else 1


def run_ce64_gates(out):
    directory = out / "build/ce64"
    directory.mkdir(parents=True, exist_ok=True)
    binary = directory / "native-ce64-gates"
    command = ["gcc", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror", "-Wno-misleading-indentation",
               "-ffunction-sections", "-fdata-sections", "-DNX_DIAG_HOST", "-DNX_PORTABLE",
               "-include", str(ROOT / "firmware/runtime/board/diag.h"),
               "-I", str(ROOT / "firmware/drivers/accel"), "-I", str(ROOT / "firmware/runtime/port"),
               "-I", str(ROOT / "firmware/runtime/reference"),
               "-idirafter", str(ROOT / "software/include"),
               str(HERE / "native_ce64_gates.c"), str(ROOT / "firmware/drivers/accel/ce64_linear.c"),
               str(ROOT / "firmware/drivers/accel/linear_api.c"), str(ROOT / "firmware/runtime/board/diag.c"),
               "-Wl,--gc-sections", "-lm", "-o", str(binary)]
    built = subprocess.run(command, capture_output=True, text=True, timeout=60)
    (directory / "compile.log").write_text(built.stdout + built.stderr)
    write_json(directory / "compile.json", {"argv": command, "exit_code": built.returncode})
    if built.returncode:
        return {"passed": False, "failure": "CE64 gate fixture compile failed", "compile_log": str(directory / "compile.log")}
    binary.chmod(0o755)
    raw_out, raw_err, results, checks = [], [], [], []
    for case in ["health", "healthy_reset", "quarantine", "drain_timeout", "epoch_timeout", "sticky_bridge_fault", "release_failure"]:
        run = subprocess.run([str(binary), case], capture_output=True, text=True, timeout=20)
        raw_out.append(run.stdout)
        raw_err.append(run.stderr)
        parsed = [json.loads(line) for line in run.stdout.splitlines()]
        checks.extend(parsed)
        results.append({"case": case, "exit_code": run.returncode, "checks": len(parsed)})
        print(("PASS " if run.returncode == 0 else "FAIL ") + "ce64_" + case)
    (out / "ce64_gates.stdout.jsonl").write_text("".join(raw_out))
    (out / "ce64_gates.stderr.txt").write_text("".join(raw_err))
    return {"passed": all(row["exit_code"] == 0 for row in results) and bool(checks) and all(row["passed"] for row in checks),
            "scope": "actual nx_ce64_idle_safe/reset_session/linear_input_invalidate with controlled MMIO bus responses; no RTL model",
            "compile_command": str(directory / "compile.json"), "binary_sha256": sha(binary),
            "raw_checks": str(out / "ce64_gates.stdout.jsonl"), "cases": results, "checks": checks}


if __name__ == "__main__":
    raise SystemExit(main())
