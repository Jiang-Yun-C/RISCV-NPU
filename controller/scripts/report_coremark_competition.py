#!/usr/bin/env python3
"""Pair physical-board CoreMark evidence without inventing an official score.

Inputs are a session manifest, exact raw logs/ELFs/binaries/build receipts,
clock counts or bitstream-bound input/PLL configuration, and optional scoped
resource/timing reports. Configured frequency is never labeled a measurement.
The checker establishes file identity and consistency. It cannot authenticate
the physical origin of arbitrary supplied files or approve competition results.
No hardware access, compilation, mutation of inputs, or network access occurs.
"""
import argparse
import csv
from decimal import Decimal, InvalidOperation
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import shlex
import sys

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("coremark_builder", ROOT / "scripts/build_coremark.py")
coremark = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(coremark)
SCHEMA = "t27-coremark-competition-session-v1"


class EvidenceError(ValueError):
    pass


def positive_int(value, label):
    if type(value) is not int or value <= 0:
        raise EvidenceError(label + " must be a positive integer")
    return value


def number(value, label):
    if isinstance(value, bool):
        raise EvidenceError(label + " must be finite numeric data")
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise EvidenceError(label + " must be finite numeric data") from exc
    if not result.is_finite():
        raise EvidenceError(label + " must be finite numeric data")
    return result


def string(value, label):
    if not isinstance(value, str) or not value.strip():
        raise EvidenceError(label + " must be a nonempty string")
    return value


def digest(data):
    return hashlib.sha256(data).hexdigest()


def one_line(text, name):
    matches = re.findall(r"^" + re.escape(name) + r"\s*:\s*([^\r\n]+)\r?$", text, re.M)
    if len(matches) != 1:
        raise EvidenceError("need one " + name + " line")
    return matches[0].strip()


class Files:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.verified = {}

    def read(self, ref, label):
        if not isinstance(ref, dict):
            raise EvidenceError(label + " needs a path/SHA256 reference")
        name = string(ref.get("path"), label + ".path")
        expected = string(ref.get("sha256"), label + ".sha256").lower()
        if not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise EvidenceError(label + " SHA256 is invalid")
        path = self.root / name
        if Path(name).is_absolute() or not path.resolve().is_relative_to(self.root):
            raise EvidenceError(label + " must stay inside the evidence directory")
        data = path.read_bytes()
        if not data or digest(data) != expected:
            raise EvidenceError(label + " file identity mismatch or empty artifact")
        self.verified[name] = expected
        return data

    def json(self, ref, label):
        result = json.loads(self.read(ref, label))
        if not isinstance(result, dict):
            raise EvidenceError(label + " must contain a JSON object")
        return result


def board_origin(record, hardware, label):
    if record.get("execution_origin") != "physical_board" or record.get("synthetic") is not False:
        raise EvidenceError(label + " is not declared physical-board, nonsynthetic evidence")
    for field in ("device_id", "bitstream_sha256", "cpu_rtl_sha256",
                  "clock_configuration_id", "memory_configuration_id"):
        if record.get(field) != hardware[field]:
            raise EvidenceError(label + " hardware/configuration identity mismatch: " + field)


def normalized_flags(flags):
    # The official performance and validation seeds intentionally differ. Auto
    # calibration may also select separate iteration counts. No other change is
    # silently normalized, including compiler tuning supplied by newer builders.
    return [token for token in shlex.split(flags)
            if not re.fullmatch(r"-D(?:PERFORMANCE_RUN|VALIDATION_RUN)=1", token)
            and not re.fullmatch(r"-DITERATIONS=\d+", token)]


def validate_run(files, run, mode, hardware):
    uart_bytes = files.read(run["uart"], mode + " UART")
    text = uart_bytes.decode("utf-8")
    if "T21_SHORT_DEBUG_ONLY" in text:
        raise EvidenceError(mode + " UART log explicitly declares a short debug run")
    receipt = files.json(run["build_receipt"], mode + " build receipt")
    capture = files.json(run["capture_receipt"], mode + " capture receipt")
    board_origin(capture, hardware, mode + " capture")
    string(capture.get("run_id"), mode + " run_id")
    string(capture.get("captured_at"), mode + " captured_at")
    if capture.get("uart_sha256") != digest(uart_bytes):
        raise EvidenceError(mode + " capture is not bound to the raw UART log")
    if receipt.get("schema") != "t27-coremark-build-v1" or receipt.get("status") != "BUILT_NOT_EXECUTED":
        raise EvidenceError(mode + " requires a successful benchmark build receipt")
    if receipt.get("build_exit_code") != 0 or receipt.get("source_inputs_stable") is not True:
        raise EvidenceError(mode + " build failed or input identity was unstable")
    if receipt.get("mode") != mode or receipt.get("run_seed_set") != mode:
        raise EvidenceError(mode + " needs the matching formal seed-set build, not debug")
    flags = string(receipt.get("reported_compiler_flags"), mode + " compiler flags")
    flag_tokens = shlex.split(flags)
    command = receipt.get("command", [])
    if command[1:1 + len(flag_tokens)] != flag_tokens:
        raise EvidenceError(mode + " reported flags are not the recorded common compiler command")
    for item in (receipt.get("compiler_sha256"), receipt.get("compiler_cc1", {}).get("sha256"),
                 receipt.get("libgcc", {}).get("sha256")):
        if not isinstance(item, str) or not re.fullmatch(r"[0-9a-f]{64}", item):
            raise EvidenceError(mode + " needs exact compiler/cc1/libgcc SHA256 identities")
    if any("COREMARK_HOST_TEST" in str(token) for token in receipt.get("command", [])):
        raise EvidenceError(mode + " build used a synthetic host test clock")
    required_flags = {"-DCOREMARK_FORMAL=1", "-DMULTITHREAD=1", "-DTOTAL_DATA_SIZE=2000",
                      "-DHAS_FLOAT=1", "-D" + mode.upper() + "_RUN=1"}
    if not required_flags <= set(shlex.split(flags)) or receipt.get("total_data_size") != 2000:
        raise EvidenceError(mode + " build does not carry the formal single-context contract")
    if flags != one_line(text, "Compiler flags"):
        raise EvidenceError(mode + " logged compiler flags differ from the build receipt")
    if receipt.get("memory_location") != one_line(text, "Memory location"):
        raise EvidenceError(mode + " logged memory placement differs from the build receipt")
    logged_version = one_line(text, "Compiler version")
    if not logged_version.startswith("GCC") or logged_version[3:] not in receipt.get("compiler_version", ""):
        raise EvidenceError(mode + " compiler version is not bound to the build receipt")
    elf_bytes = files.read(run["elf"], mode + " ELF")
    binary = files.read(run["binary"], mode + " binary")
    payload, elf = coremark.parse_elf(elf_bytes)
    if (digest(elf_bytes) != receipt.get("elf_sha256") or payload != binary
            or elf["bin_sha256"] != receipt.get("elf", {}).get("bin_sha256")
            or capture.get("binary_sha256") != digest(binary)):
        raise EvidenceError(mode + " build/ELF/deployed binary identity mismatch")
    if receipt.get("upstream_commit") != coremark.UPSTREAM_COMMIT:
        raise EvidenceError(mode + " uses an unrecognized upstream revision")
    official = coremark.check_upstream(coremark.PORT / "upstream")
    for name in (*coremark.ALGORITHMS, "coremark.h"):
        key = "firmware/coremark/upstream/" + name
        if receipt.get("source_sha256", {}).get(key) != official["files"][name]["sha256"]:
            raise EvidenceError(mode + " does not bind the unchanged official " + name)
    hz = positive_int(receipt.get("clock_hz"), mode + " declared clock")
    result = coremark.validate_log(text, expected_hz=hz, expected_mode=mode, require_formal=True)
    requested = receipt.get("iterations")
    log_requested = int(re.search(r"requested_iterations=(\d+)", text).group(1))
    if type(requested) is not int or requested < 0 or requested != log_requested:
        raise EvidenceError(mode + " requested iteration count differs from its build")
    if requested and requested != result["iterations"]:
        raise EvidenceError(mode + " actual iteration count differs from its explicit request")
    result["declared_timer_hz"] = result.pop("clock_hz")
    result["seconds_from_declared_timer"] = result.pop("seconds")
    result["iteration_rate_from_declared_timer"] = result.pop("coremark")
    result.pop("coremark_per_mhz")
    return result, receipt, capture, logged_version


def resolve_clock(files, record, hardware):
    board_origin(record, hardware, "clock measurement")
    method = record.get("method")
    details = {}
    if method == "independent_reference_counter":
        basis = "measured"
        reference = positive_int(record.get("reference_hz"), "reference_hz")
        string(record.get("reference_description"), "reference_description")
        files.read(record["reference_evidence"], "reference frequency evidence")
        raw = files.read(record["counter_capture"], "raw clock counts").decode("utf-8")
        reader = csv.DictReader(io.StringIO(raw))
        if reader.fieldnames != ["reference_ticks", "core_cycles"]:
            raise EvidenceError("clock CSV needs exactly reference_ticks,core_cycles")
        rows = list(reader)
        if len(rows) != 1:
            raise EvidenceError("clock CSV must contain one complete measurement window")
        reference_ticks = positive_int(int(rows[0]["reference_ticks"]), "reference_ticks")
        core_cycles = positive_int(int(rows[0]["core_cycles"]), "clock core_cycles")
        hz = Decimal(core_cycles) * reference / reference_ticks
        details.update(reference_hz=reference, reference_ticks=reference_ticks, core_cycles=core_cycles)
    elif method == "documented_clock_configuration":
        basis = "configured"
        source_hz = positive_int(record.get("input_clock_hz"), "input_clock_hz")
        multiplier = positive_int(record.get("effective_multiplier"), "effective_multiplier")
        divider = positive_int(record.get("effective_divider"), "effective_divider")
        string(record.get("input_clock_description"), "input_clock_description")
        files.read(record["input_clock_evidence"], "actual input clock evidence")
        files.read(record["configuration_evidence"], "actual PLL/divider configuration evidence")
        hz = Decimal(source_hz) * multiplier / divider
        details.update(input_clock_hz=source_hz, effective_multiplier=multiplier, effective_divider=divider)
    else:
        raise EvidenceError("clock needs independent reference counts or documented input/PLL configuration; a timing target alone is insufficient")
    uncertainty = record.get("uncertainty_ppm")
    if uncertainty is not None:
        uncertainty = number(uncertainty, "clock uncertainty_ppm")
        if uncertainty < 0 or uncertainty >= 1000000:
            raise EvidenceError("clock uncertainty must be >=0 and <1000000 ppm")
    elif basis == "measured":
        raise EvidenceError("independent reference measurements need an uncertainty bound")
    high_hz = hz * (1 + uncertainty / 1000000) if uncertainty is not None else None
    # Domain ratios must name the actual interface clock, not DDR transfers/s.
    domains = record["domains"]
    files.read(domains["evidence"], "clock domain relationship evidence")
    ratios = {}
    for name in ("icache_to_core", "dcache_to_core", "memory_interface_to_core"):
        value = domains[name]
        ratios[name] = {"numerator": positive_int(value["numerator"], name),
                        "denominator": positive_int(value["denominator"], name)}
    string(domains.get("memory_interface_name"), "memory_interface_name")
    return hz, high_hz, {"frequency_basis": basis, "method": method,
                        "frequency_hz": str(hz), "measured_hz": str(hz) if basis == "measured" else None,
                        "configured_hz": str(hz) if basis == "configured" else None,
                        "uncertainty_ppm": str(uncertainty) if uncertainty is not None else None,
                        "upper_hz_for_duration_check": str(high_hz) if high_hz is not None else None,
                        **details, "domain_ratios": ratios,
                        "memory_interface_name": domains["memory_interface_name"]}


def scoped_resources(files, references, hardware, score, frequency_basis):
    result = []
    seen = set()
    for ref in references:
        item = files.json(ref, "resource receipt")
        scope = item.get("scope")
        if scope not in ("cpu", "whole_soc") or scope in seen:
            raise EvidenceError("resource scope must be unique cpu or whole_soc")
        seen.add(scope)
        if item.get("bitstream_sha256") != hardware["bitstream_sha256"] or item.get("device_id") != hardware["device_id"]:
            raise EvidenceError("resource report belongs to different hardware")
        hierarchy = hardware["cpu_instance"] if scope == "cpu" else hardware["soc_top"]
        if item.get("hierarchy") != hierarchy or item.get("covers_entire_hierarchy") is not True:
            raise EvidenceError("resource denominator must cover the entire explicitly selected hierarchy")
        if item.get("implementation_stage") not in ("synthesis", "device_map", "post_route"):
            raise EvidenceError("resource report needs an explicit implementation stage")
        for key in ("tool_version", "lut_definition"):
            string(item.get(key), "resource " + key)
        lut = positive_int(item.get("lut_count"), "LUT count")
        files.read(item["raw_report"], "raw resource report")
        result.append({"scope": scope, "hierarchy": hierarchy, "lut_count": lut,
                       "lut_definition": item["lut_definition"],
                       "implementation_stage": item["implementation_stage"],
                       "tool_version": item["tool_version"],
                       "frequency_basis": frequency_basis,
                       "coremark_per_lut": str(score / lut) if frequency_basis == "measured" else None,
                       "configured_frequency_coremark_per_lut": str(score / lut) if frequency_basis == "configured" else None})
    return result


def timing_at_operating_point(files, reference, hardware, declared_hz):
    if reference is None:
        return {"status": "NOT_PROVIDED", "fmax_hz": None}
    timing = files.json(reference, "timing receipt")
    if timing.get("device_id") != hardware["device_id"] or timing.get("bitstream_sha256") != hardware["bitstream_sha256"]:
        raise EvidenceError("timing receipt belongs to different hardware")
    if timing.get("implementation_stage") != "post_route" or timing.get("routing_complete") is not True:
        raise EvidenceError("timing evidence must use complete post-route implementation")
    if timing.get("constrained_core_hz") != declared_hz or timing.get("unconstrained_endpoints") != 0:
        raise EvidenceError("timing target/constraint coverage does not match this operating point")
    for key in ("setup_wns_ns", "hold_wns_ns"):
        if number(timing.get(key), key) < 0:
            raise EvidenceError("timing does not close at this operating point")
    for key in ("setup_tns_ns", "hold_tns_ns"):
        if number(timing.get(key), key) != 0:
            raise EvidenceError("timing does not close at this operating point")
    string(timing.get("tool_version"), "timing tool_version")
    files.read(timing["raw_report"], "raw timing report")
    return {"status": "MATCHED_POST_ROUTE_TIMING_SUMMARY", "constrained_core_hz": declared_hz,
            "independently_authenticated_full_signoff": False,
            "fmax_hz": None, "reason": "A passing operating point is not a frequency sweep. WNS is never converted into a higher Fmax."}


def check_session(path):
    path = Path(path).resolve()
    session_bytes = path.read_bytes()
    session = json.loads(session_bytes)
    if session.get("schema") != SCHEMA:
        raise EvidenceError("unrecognized session schema")
    files = Files(path.parent)
    hardware = dict(session["hardware"])
    for field in ("device_id", "clock_configuration_id", "memory_configuration_id", "cpu_instance", "soc_top"):
        string(hardware.get(field), "hardware " + field)
    if hardware["cpu_instance"] == hardware["soc_top"]:
        raise EvidenceError("CPU instance and whole-SoC top must be distinct")
    hardware["bitstream_sha256"] = digest(files.read(hardware["bitstream"], "bitstream"))
    hardware["cpu_rtl_sha256"] = digest(files.read(hardware["cpu_rtl"], "CPU RTL"))
    clock = files.json(session["clock_measurement"], "clock receipt")
    frequency_hz, upper_hz, clock_report = resolve_clock(files, clock, hardware)
    frequency_basis = clock_report["frequency_basis"]
    runs = {mode: validate_run(files, session["runs"][mode], mode, hardware)
            for mode in ("performance", "validation")}
    performance, pbuild, pcapture, pversion = runs["performance"]
    validation, vbuild, vcapture, vversion = runs["validation"]
    if pcapture["run_id"] == vcapture["run_id"]:
        raise EvidenceError("performance and validation need distinct captured runs")
    for field in ("upstream_commit", "opt", "lto", "tuning", "clock_hz", "memory", "memory_location",
                  "compiler_sha256", "source_sha256"):
        if pbuild.get(field) != vbuild.get(field):
            raise EvidenceError("paired builds differ: " + field)
    for field in ("compiler_cc1", "libgcc"):
        psha = pbuild.get(field, {}).get("sha256")
        vsha = vbuild.get(field, {}).get("sha256")
        if not psha or psha != vsha:
            raise EvidenceError("paired toolchain binary identities differ: " + field)
    if pversion != vversion or normalized_flags(pbuild["reported_compiler_flags"]) != normalized_flags(vbuild["reported_compiler_flags"]):
        raise EvidenceError("paired compiler/version/options differ outside seeds and iteration counts")
    for mode, (run, *_rest) in runs.items():
        minimum_seconds = Decimal(run["cycles"]) / (upper_hz if upper_hz is not None else frequency_hz)
        if minimum_seconds < 10:
            raise EvidenceError(mode + " duration is below 10 seconds using the upper frequency uncertainty bound or configured nominal clock")
        seconds = str(Decimal(run["cycles"]) / frequency_hz)
        run["seconds_from_clock_basis"] = seconds
        run["seconds_from_independent_clock"] = seconds if frequency_basis == "measured" else None
        run["seconds_from_configured_clock"] = seconds if frequency_basis == "configured" else None
        run["minimum_seconds_with_clock_uncertainty"] = str(minimum_seconds) if upper_hz is not None else None
        run["duration_basis"] = frequency_basis + ("_with_uncertainty_bound" if upper_hz is not None else "_nominal_only")
    declared_hz = pbuild["clock_hz"]
    delta_ppm = (frequency_hz / declared_hz - 1) * 1000000
    tolerance = number(session.get("maximum_clock_deviation_ppm"), "maximum_clock_deviation_ppm")
    if tolerance < 0 or abs(delta_ppm) > tolerance:
        raise EvidenceError("declared timer frequency differs from the evidenced frequency beyond the explicit tolerance")
    score = Decimal(performance["iterations"]) * frequency_hz / performance["cycles"]
    per_mhz = Decimal(performance["iterations"]) * 1000000 / performance["cycles"]
    resources = scoped_resources(files, session.get("resources", []), hardware, score, frequency_basis)
    timing = timing_at_operating_point(files, session.get("timing"), hardware, declared_hz)
    return {"schema": "t27-coremark-competition-report-v1", "status": "EVIDENCE_CONSISTENT",
            "competition_approval": False, "independently_authenticated_board_origin": False,
            "trust_boundary": "Physical-board origin and instrument provenance are declared by the supplied capture receipts. Hash checks establish identity and internal consistency, not independent hardware authenticity or judging approval.",
            "session_sha256": digest(session_bytes), "hardware": hardware,
            "clock": {**clock_report, "declared_timer_hz": declared_hz, "deviation_ppm": str(delta_ppm),
                      "maximum_clock_deviation_ppm": str(tolerance)},
            "performance": performance, "validation": validation,
            "metrics": {"frequency_basis": frequency_basis,
                        "coremark_iterations_per_second": str(score) if frequency_basis == "measured" else None,
                        "configured_frequency_coremark_iterations_per_second": str(score) if frequency_basis == "configured" else None,
                        "coremark_per_mhz": str(per_mhz),
                        "normalization_basis": "actual iteration count and 64-bit core cycles; frequency cancels algebraically",
                        "resource_efficiency": resources, "fmax_hz": None},
            "timing": timing, "memory_location": pbuild["memory_location"],
            "compiler_version": pversion, "compiler_flags": normalized_flags(pbuild["reported_compiler_flags"]),
            "verified_files": files.verified,
            "remaining_evidence": ["Competition acceptance remains a judging decision.",
                                   "Fmax requires separately measured operating-point exploration; positive WNS does not establish a higher frequency.",
                                   "ILA algorithm wave analysis and AI/sensor/display evidence are separate scoring items."]}


def template(kind="session"):
    def ref(name):
        return {"path": name, "sha256": None}
    identity = {"execution_origin": None, "synthetic": None, "device_id": None,
                "bitstream_sha256": None, "cpu_rtl_sha256": None,
                "clock_configuration_id": None, "memory_configuration_id": None}
    if kind == "capture":
        return {**identity, "run_id": None, "captured_at": None,
                "binary_sha256": None, "uart_sha256": None}
    if kind == "clock":
        return {**identity, "method": "independent_reference_counter",
                "reference_hz": None, "reference_description": None,
                "reference_evidence": ref("clock/reference-evidence.txt"),
                "counter_capture": ref("clock/counter-capture.csv"), "uncertainty_ppm": None,
                "domains": {"icache_to_core": {"numerator": None, "denominator": None},
                            "dcache_to_core": {"numerator": None, "denominator": None},
                            "memory_interface_to_core": {"numerator": None, "denominator": None},
                            "memory_interface_name": None, "evidence": ref("clock/domain-evidence.txt")}}
    if kind == "clock-configured":
        result = template("clock")
        for key in ("reference_hz", "reference_description", "reference_evidence", "counter_capture"):
            result.pop(key)
        result.update(method="documented_clock_configuration", input_clock_hz=None,
                      input_clock_description=None, effective_multiplier=None, effective_divider=None,
                      input_clock_evidence=ref("clock/input-clock-evidence.txt"),
                      configuration_evidence=ref("clock/actual-pll-divider-configuration.txt"))
        return result
    if kind in ("resource-cpu", "resource-soc"):
        return {"scope": "cpu" if kind == "resource-cpu" else "whole_soc",
                "device_id": None, "bitstream_sha256": None, "hierarchy": None,
                "covers_entire_hierarchy": None, "implementation_stage": None,
                "tool_version": None, "lut_definition": None, "lut_count": None,
                "raw_report": ref("resources/raw-" + kind + ".txt")}
    if kind == "timing":
        return {"device_id": None, "bitstream_sha256": None, "implementation_stage": "post_route",
                "routing_complete": None, "constrained_core_hz": None, "unconstrained_endpoints": None,
                "setup_wns_ns": None, "hold_wns_ns": None, "setup_tns_ns": None, "hold_tns_ns": None,
                "tool_version": None, "raw_report": ref("timing/post-route.txt")}
    if kind != "session":
        raise EvidenceError("unknown template kind")
    return {"schema": SCHEMA, "maximum_clock_deviation_ppm": None,
            "hardware": {"device_id": None, "bitstream": ref("hardware/benchmark.bit"),
                         "cpu_rtl": ref("hardware/T09Cpu.v"), "cpu_instance": None, "soc_top": None,
                         "clock_configuration_id": None, "memory_configuration_id": None},
            "clock_measurement": ref("clock/receipt.json"),
            "runs": {mode: {"uart": ref(mode + "/uart.txt"),
                            "build_receipt": ref(mode + "/BUILD_RECEIPT.json"),
                            "capture_receipt": ref(mode + "/CAPTURE_RECEIPT.json"),
                            "elf": ref(mode + "/coremark.elf"), "binary": ref(mode + "/coremark.bin")}
                     for mode in ("performance", "validation")},
            "resources": [], "timing": None}


def render_markdown(report):
    metrics = report["metrics"]
    configured = metrics["frequency_basis"] == "configured"
    score = metrics["configured_frequency_coremark_iterations_per_second"] if configured else metrics["coremark_iterations_per_second"]
    qualifier = "配置频率名义值" if configured else "独立参考测得频率折算"
    lines = ["# CoreMark 比赛证据配对报告", "", "状态：两组证据内部一致（EVIDENCE_CONSISTENT）。",
             "", "这不是赛事认证；板端来源依据输入的采集声明，程序没有独立认证硬件或仪器。", "",
             "| 指标 | 数值 |", "|---|---:|",
             "| CoreMark（iterations/s，" + qualifier + "） | " + score + " |",
             "| CoreMark/MHz | " + metrics["coremark_per_mhz"] + " |",
             "| CPU Hz（" + qualifier + "） | " + report["clock"]["frequency_hz"] + " |",
             "| 性能轮数 | " + str(report["performance"]["iterations"]) + " |",
             "| 校验轮数 | " + str(report["validation"]["iterations"]) + " |",
             "| 性能测试秒数（" + qualifier + "） | " + report["performance"]["seconds_from_clock_basis"] + " |",
             "| 校验测试秒数（" + qualifier + "） | " + report["validation"]["seconds_from_clock_basis"] + " |", "",
             "## 资源分母", ""]
    if metrics["resource_efficiency"]:
        lines += ["| 范围 | 层级 | 阶段 | LUT | CoreMark/LUT（" + qualifier + "） | LUT定义 |", "|---|---|---|---:|---:|---|"]
        for item in metrics["resource_efficiency"]:
            score_key = "configured_frequency_coremark_per_lut" if configured else "coremark_per_lut"
            lines.append("| " + " | ".join(str(item[k]).replace("|", "\\|") for k in
                         ("scope", "hierarchy", "implementation_stage", "lut_count", score_key, "lut_definition")) + " |")
    else:
        lines.append("未提供匹配的 CPU/SoC 资源证据，CoreMark/LUT 保持空值。")
    lines += ["", "## 频率与复核范围", "", "Fmax 未测得；不从正 WNS 推算更高频率。",
              "", "存储条件：`" + report["memory_location"] + "`。",
              "", "完整 JSON 包含原始日志、程序、时钟计数和资源文件的 SHA256。ILA 算法波形分析、AI 应用与传感器/显示演示另行提供。", ""]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session", nargs="?", type=Path)
    parser.add_argument("--template", action="store_true")
    parser.add_argument("--template-kind", choices=("session", "clock", "clock-configured", "capture", "resource-cpu", "resource-soc", "timing"), default="session")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--markdown", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.template:
            print(json.dumps(template(args.template_kind), indent=2))
            return 0
        if not args.session:
            raise EvidenceError("provide a session manifest or --template")
        if any(path is not None and path.exists() for path in (args.output, args.markdown)):
            raise EvidenceError("output already exists; choose new filenames to retain old evidence")
        report = check_session(args.session)
        text = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
        if args.output:
            with args.output.open("x") as stream:
                stream.write(text)
        else:
            print(text, end="")
        if args.markdown:
            with args.markdown.open("x") as stream:
                stream.write(render_markdown(report))
        return 0
    except (ValueError, KeyError, TypeError, OSError) as exc:
        print("CoreMark competition evidence: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
