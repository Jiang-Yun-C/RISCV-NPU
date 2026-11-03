#!/usr/bin/env python3
"""Public-dev semantic evidence from existing demo-console exports; no board I/O."""
import argparse
from collections import Counter, defaultdict
import ctypes
import hashlib
import json
import math
from pathlib import Path
import statistics
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATASET = HERE / "cases.json"
STATUSES = ["OK", "FORMAT", "RANGE", "UNSUPPORTED", "STATE", "STALE", "NACK",
            "TIMEOUT", "DUPLICATE", "REQUEST_ID"]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:raise ValueError("duplicate JSON key: " + key)
        result[key] = value
    return result


def load(path):
    return json.loads(Path(path).read_text(encoding="utf8"), object_pairs_hook=unique_object,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON constant")))


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def node(payload):
    run = subprocess.run(["node", str(HERE / "parse_export.mjs")], input=encode(payload),
                         text=True, capture_output=True, timeout=30)
    if run.returncode:raise ValueError("wire parser failed: " + run.stderr[-2000:])
    return json.loads(run.stdout)


def cases_and_commands():
    dataset = load(DATASET);cases = dataset["cases"]
    if len(cases) != 24 or len({c["id"] for c in cases}) != len(cases):raise ValueError("bad frozen development set")
    rows = []
    for case in cases:
        state = case["state"]
        if set(state) != {"temperature", "light"} or any(type(v) is not int for v in state.values()):
            raise ValueError("virtual sensor states must be exact integers")
        prompt = dataset["prompt_prefix"] + "状态：" + encode(state) + "。指令：" + case["instruction"]
        rows.append({"id": case["id"], "prompt": prompt})
    generated = node({"action": "commands", "max_new": dataset["max_new"], "cases": rows})
    commands = {row["case_id"]: row["command"] for row in generated["commands"]}
    return dataset, commands, generated["parser_contract"], {row["id"]: row["prompt"] for row in rows}


def make_plan(directory):
    directory = Path(directory).resolve();directory.mkdir(parents=True, exist_ok=False)
    (directory / "exports").mkdir()
    dataset, commands, contract, prompts = cases_and_commands()
    manifest = {"schema": "competition-semantic-run-v1", "dataset_sha256": sha(DATASET),
                "suite": dataset["schema"], "scope": dataset["scope"], "expected": contract,
                "declared_artifacts": {"firmware_sha256": None, "bitstream_sha256": None,
                                       "capture_notes": "Fill actual deployment identities; this tool does not attest hardware."},
                "records": [{"case_id": case["id"], "export": "exports/" + case["id"] + ".json",
                             "attempt_status": "pending"} for case in dataset["cases"]]}
    (directory / "run.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    with (directory / "requests.jsonl").open("w", encoding="utf8") as output:
        for case in dataset["cases"]:
            output.write(encode({"case_id": case["id"], "prompt": prompts[case["id"]],
                                 "command": commands[case["id"]], "max_new": dataset["max_new"],
                                 "state_source": "PUBLIC_DEV_VIRTUAL_STATE"}) + "\n")
    (directory / "COPY_PROMPTS.txt").write_text(
        "PUBLIC DEVELOPMENT DIAGNOSTIC — virtual states, no physical actions.\n"
        "Paste only the prompt line into demo text input; max_new=128. Export each result immediately.\n"
        + "\n\n".join(case["id"] + " -> exports/" + case["id"] + ".json\n" + prompts[case["id"]]
                         for case in dataset["cases"]) + "\n", encoding="utf8")
    return directory / "run.json"


class Executor:
    def __init__(self, directory):
        library = Path(directory) / "application-oracle.so"
        app = ROOT / "firmware/application/application.c"
        header = app.with_suffix(".h")
        bridge = HERE / "executor_bridge.c"
        self.sources = {str(p.relative_to(ROOT)): sha(p) for p in (app, header, bridge)}
        command = ["gcc", "-std=c11", "-O2", "-shared", "-fPIC", "-Wall", "-Wextra", "-Werror",
                   "-Wno-misleading-indentation", "-I", str(app.parent), str(app), str(bridge), "-o", str(library)]
        subprocess.run(command, check=True, capture_output=True, timeout=30)
        self.lib = ctypes.CDLL(str(library))
        self.lib.competition_evaluate.argtypes = [ctypes.c_char_p, ctypes.c_size_t,
            ctypes.c_int32, ctypes.c_uint32, ctypes.POINTER(ctypes.c_uint32)]
        self.lib.competition_evaluate.restype = ctypes.c_int
        self.command = command

    def execute(self, text, state):
        data = text.encode("utf8");out = (ctypes.c_uint32 * 19)()
        code = self.lib.competition_evaluate(data, len(data), state["temperature"], state["light"], out)
        if not 0 <= code < len(STATUSES) or out[1] > 8:raise ValueError("unexpected application oracle result")
        readings = {}
        if out[2] & 1:readings["temperature"] = state["temperature"]
        if out[2] & 2:readings["light"] = state["light"]
        return {"validation": STATUSES[code],
                "actions": [["pwm" if out[3 + 2*i] else "led", int(out[4 + 2*i])] for i in range(out[1])],
                "readings": readings}


def finite_difference(end, start, scale=1.0):
    if isinstance(end, bool) or isinstance(start, bool):return None
    if not isinstance(end, (float, int)) or not isinstance(start, (float, int)):return None
    value = (end - start) / scale
    return value if math.isfinite(value) and value >= 0 else None


def latencies(parsed, clock_hz):
    result = {};request = parsed.get("request_result")
    if not parsed.get("protocol_accepted") or not request:return result
    m = request["metrics"]
    if parsed.get("clock_hz") == clock_hz:
        for name, field in (("runtime_total_s", "total_ticks"), ("runtime_decode_s", "decode_ticks"),
                            ("runtime_prefill_s", "prefill_ticks")):
            value = finite_difference(m.get(field), 0, clock_hz)
            if value is not None:result[name] = value
        if m.get("generated"):
            value = finite_difference(m.get("first_token_ticks"), 0, clock_hz)
            if value is not None:result["runtime_first_token_s"] = value
    chunk = parsed.get("first_visible_chunk") or {}
    timing = parsed.get("export_timing") or {};host = timing.get("host") or {};browser = timing.get("browser") or {}
    if host.get("clock") == "python.time.monotonic_ns":
        try:
            start, end = host.get("write_start"), chunk.get("received_ns")
            if type(start) is str and start.isdigit() and type(end) is str and end.isdigit():
                value = finite_difference(int(end), int(start), 1e9)
                if value is not None:result["host_first_visible_s"] = value
        except (ValueError, OverflowError):pass
    if browser.get("clock") == "browser.performance.now_ms":
        value = finite_difference(chunk.get("browserReceive"), browser.get("write_start"), 1000)
        if value is not None:result["browser_first_visible_s"] = value
    # DOM timestamps are not reconstructed from serial bytes, so intentionally
    # do not score them or combine browser and host clock origins.
    return result


def distribution(values):
    if not values:return {"n": 0, "median": None, "p95_nearest_rank": None, "min": None, "max": None}
    values = sorted(values)
    return {"n": len(values), "median": statistics.median(values),
            "p95_nearest_rank": values[math.ceil(.95 * len(values)) - 1], "min": values[0], "max": values[-1]}


def score_run(manifest_path):
    manifest_path = Path(manifest_path).resolve();manifest = load(manifest_path)
    dataset, commands, contract, _ = cases_and_commands();cases = dataset["cases"]
    if manifest.get("schema") != "competition-semantic-run-v1" or manifest.get("dataset_sha256") != sha(DATASET):
        raise ValueError("run does not bind the frozen public development set")
    if manifest.get("expected") != contract:raise ValueError("run clock/model/tokenizer differs from current parser contract")
    records = manifest.get("records", [])
    if len(records) != len(cases) or {r.get("case_id") for r in records} != {c["id"] for c in cases}:
        raise ValueError("run must retain every frozen case exactly once")
    indexed = {r["case_id"]: r for r in records};inputs = [];missing = {};paths = set()
    for case in cases:
        record = indexed[case["id"]]
        if record.get("attempt_status") not in ("pending", "completed", "timeout", "disconnected", "failed"):
            raise ValueError("unknown attempt status")
        path = (manifest_path.parent / record["export"]).resolve()
        if not path.is_relative_to(manifest_path.parent) or path in paths:
            raise ValueError("export paths must be distinct files inside this run")
        paths.add(path)
        if path.is_file():inputs.append({"case_id": case["id"], "path": str(path), "expected_command": commands[case["id"]]})
        else:missing[case["id"]] = record["attempt_status"]
    parsed = {r["case_id"]: r for r in node(inputs)["records"]}
    evaluated = [];groups = defaultdict(list);pairs = defaultdict(list);timed = defaultdict(lambda: defaultdict(list))
    live_attempts = 0;live_passes = 0
    with tempfile.TemporaryDirectory(prefix="competition-semantic-oracle-") as scratch:
        executor = Executor(scratch)
        for case in cases:
            expected = executor.execute(encode(case["program"]), case["state"])
            row = {"case_id": case["id"], "category": case["category"], "pair_id": case.get("pair_id"),
                   "state_source": "PUBLIC_DEV_VIRTUAL_STATE", "expected": expected,
                   "protocol_accepted": False, "semantic_pass": False, "live_model_pass": False,
                   "physical_action_verified": False, "issues": []}
            observed = parsed.get(case["id"])
            if not observed:
                row["issues"] = ["no export: " + missing[case["id"]]]
                row["capture_source"] = "missing";row["latencies_s"] = {}
            else:
                row.update(protocol_accepted=observed["protocol_accepted"],
                           capture_source=observed.get("declared_source"),
                           export_sha256=observed.get("export_sha256"), wire_sha256=observed.get("wire_sha256"),
                           used_raw_chunks=observed.get("used_raw_chunks", False), issues=observed["issues"].copy())
                live = observed.get("declared_source") == "live" and not observed.get("fixture")
                live_attempts += int(live)
                identity = observed.get("model_identity") or observed.get("record_identity") or {}
                identity_ok = identity.get("model") == contract["model"] and identity.get("tokenizer") == contract["tokenizer"]
                row["identity_matches"] = identity_ok
                row["identity_scope"] = "wire" if observed.get("model_identity") else "console_metadata_unattested"
                if observed["protocol_accepted"]:
                    request = observed["request_result"];output = request["text"]
                    actual = executor.execute(output, case["state"])
                    try:
                        ast = json.loads(output, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                    except (ValueError, TypeError, RecursionError):ast = None
                    plan_match = ast == case["program"]
                    eos = request["metrics"]["stop"] == 1
                    # A matching rejection code alone does not prove the model
                    # retained the requested device or exact out-of-range value.
                    semantic = actual == expected and eos and plan_match
                    row.update(output=output, virtual_execution=actual, program_match=plan_match,
                               stop_reason=request["metrics"]["stop"], semantic_pass=semantic)
                    row["live_model_pass"] = bool(semantic and live and identity_ok and row["used_raw_chunks"])
                    if not eos:row["issues"].append("model did not stop with EOS")
                    if not semantic:row["issues"].append("program or virtual execution differs from label")
                    if live and not identity_ok:row["issues"].append("model/tokenizer identity unavailable or mismatched")
                    if live and not row["used_raw_chunks"]:row["issues"].append("live export lacks exact receive chunks")
                row["latencies_s"] = latencies(observed, contract["clock_hz"])
                for key, value in row["latencies_s"].items():timed[str(row["capture_source"])][key].append(value)
            live_passes += int(row["live_model_pass"])
            groups[case["category"]].append(row["semantic_pass"])
            if case.get("pair_id"):pairs[case["pair_id"]].append((case, row))
            evaluated.append(row)
        pair_results = {}
        for key, entries in pairs.items():
            if len(entries) != 2 or entries[0][0]["instruction"] != entries[1][0]["instruction"]:
                raise ValueError("invalid paired case")
            if entries[0][1]["expected"] == entries[1][1]["expected"]:raise ValueError("pair must change virtual outcome")
            pair_results[key] = {"semantic_pair_pass": all(r["semantic_pass"] for _, r in entries),
                                 "live_model_pair_pass": all(r["live_model_pass"] for _, r in entries),
                                 "physical_sensor_pair_verified": False}
        report = {"schema": "competition-semantic-report-v1", "dataset_sha256": sha(DATASET),
                  "run_sha256": sha(manifest_path), "scope": dataset["scope"],
                  "status": "NO_CAPTURE_DATA" if not parsed else "RECORDS_ANALYZED_NOT_HARDWARE_ATTESTED",
                  "required_cases": len(cases), "export_files": len(parsed), "missing_exports": len(missing),
                  "protocol": {"accepted": sum(r["protocol_accepted"] for r in evaluated), "total": len(cases)},
                  "semantic_scope": "Strict reference-program AST and existing C virtual-execution agreement; not general natural-language equivalent-program accuracy.",
                  "diagnostic_semantic_agreement": {"passed": sum(r["semantic_pass"] for r in evaluated),
                       "total": len(cases), "rate_including_missing_as_fail": sum(r["semantic_pass"] for r in evaluated)/len(cases)},
                  "declared_live_model_semantics": {"eligible_successes": live_passes, "total_frozen_cases": len(cases),
                      "declared_live_attempts": live_attempts, "accuracy_including_missing_and_failed": live_passes/len(cases) if live_attempts else None,
                      "qualification": "DECLARED_LIVE_EXPORTS_ONLY_NOT_INDEPENDENT_HARDWARE_ATTESTATION" if live_attempts else "NOT_MEASURED"},
                  "categories": {key: {"passed": sum(v), "total": len(v)} for key, v in groups.items()},
                  "paired_virtual_states": pair_results,
                  "latency_by_declared_source": {source: {key: distribution(v) for key, v in values.items()} for source, values in timed.items()},
                  "latency_scope": "Completed protocol records including semantic failures; runtime mcycle/CLOCK, host monotonic and browser performance clocks stay separate; no missing latency imputed as zero.",
                  "physical_evidence": {"sensor_integrated": "NOT_VERIFIED", "gpio_or_pwm_action": "NOT_VERIFIED",
                      "display_device": "NOT_VERIFIED", "actuator_operations_by_this_tool": 0},
                  "declared_artifacts": manifest.get("declared_artifacts"),
                  "evidence_bindings": {"application_sources": executor.sources,
                      "wire_parser_sha256": sha(ROOT / "software/demo_console/static/protocol.js"),
                      "export_adapter_sha256": sha(HERE / "parse_export.mjs"), "scorer_sha256": sha(Path(__file__))},
                  "records": evaluated}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    plan = sub.add_parser("plan");plan.add_argument("--output", required=True, type=Path)
    score = sub.add_parser("score");score.add_argument("--run", required=True, type=Path)
    score.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.action == "plan":print(make_plan(args.output));return
    if args.output.exists():parser.error("refusing to overwrite an existing report")
    report = score_run(args.run);args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    print(json.dumps({k: report[k] for k in ("status", "required_cases", "protocol", "diagnostic_semantic_agreement", "declared_live_model_semantics")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":main()
