"""SpyGlass report acceptance and mechanical AXI boundary adapters.

Adapted from BSI's local harness: read real reports, preserve failures, probe
FlexNet in the execution context. No dependency on the BSI checkout at runtime.
"""
import collections
from pathlib import Path
import re

from evidence import sha256


def license_status(text, returncode, feature):
    low = text.lower()
    if any(s in low for s in ("operation not permitted", "(-15,570:1", "errno 1", "eperm")):
        return "execution_context_blocked"
    if returncode != 0:
        return "probe_failed"
    if "license server up" not in low or not re.search(r"snpslmd:\s+up\b", low):
        return "license_server_unavailable"
    match = re.search(r"Users of\s+" + re.escape(feature) +
                      r":\s*\(Total of\s+(\d+)\s+licenses? issued;\s*Total of\s+(\d+)\s+licenses? in use\)", text, re.I)
    if not match:
        return "feature_not_reported"
    issued, used = map(int, match.groups())
    return "ready" if issued > used else "feature_exhausted"


def strip_comments(text):
    return re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S)


def module_ports(text, top):
    """Parse only the simple ANSI port style used by this project's RTL."""
    match = re.search(r"\bmodule\s+" + re.escape(top) +
                      r"\s*(?:#\s*\(.*?\)\s*)?\((.*?)\)\s*;", strip_comments(text), re.S)
    if not match:
        raise ValueError(f"unsupported module header: {top}")
    ports, kind, width = [], None, ""
    for item in match[1].split(","):
        item = item.strip()
        declaration = re.fullmatch(r"(input|output|inout)\s+(?:(?:logic|wire|reg)\s*)?(\[[^]]+\])?\s*(\w+)", item)
        interface = re.fullmatch(r"(axi4_if(?:\.(?:master|slave))?)\s+(\w+)", item)
        if declaration:
            kind, width, name = declaration.groups()
            width = width or ""
        elif interface:
            kind, name = interface.groups()
            width = ""
        elif re.fullmatch(r"\w+", item) and kind:
            name = item
        else:
            raise ValueError(f"unsupported port declaration: {item}")
        ports.append((kind, width, name))
    return ports


def axi_fields(text, data_width, id_width):
    text = strip_comments(text)
    fields = {}
    for width, names in re.findall(r"\blogic\s*(\[[^]]+\])?\s*([\w,\s]+);", text):
        if width:
            dimensions = {"[31:0]": 32, "[7:0]": 8, "[2:0]": 3, "[1:0]": 2,
                          "[ID_W-1:0]": id_width, "[DATA_W-1:0]": data_width,
                          "[DATA_W/8-1:0]": data_width // 8}
            bits = dimensions[width]
            width = f"[{bits - 1}:0]"
        for name in names.split(","):
            fields[name.strip()] = width
    directions = {}
    master = re.search(r"modport\s+master\s*\((.*?)\);", text, re.S)
    if not master:
        raise ValueError("AXI master modport not found")
    kind = None
    for item in master[1].split(","):
        parts = item.split()
        if len(parts) == 2:
            kind, name = parts
        else:
            name = parts[0]
        if kind not in ("input", "output"):
            raise ValueError("unsupported AXI direction")
        directions[name] = kind
    if fields.keys() != directions.keys():
        raise ValueError("AXI field/modport mismatch; review the adapter")
    return [(name, width, directions[name]) for name, width in fields.items()]


def boundary_wrapper(top, source, interface_source, widths):
    ports = module_ports(source, top)
    declared = {name for kind, _, name in ports if kind.startswith("axi4_if")}
    if declared != widths.keys():
        raise ValueError(f"interface contract differs for {top}: {declared}")
    declarations, body, connections, inputs = [], [], [], []
    for kind, width, name in ports:
        connections.append(f".{name}({name})")
        if not kind.startswith("axi4_if"):
            if kind == "inout":
                raise ValueError("inout requires an explicit constraint model")
            declarations.append(f"{kind} wire {width} {name}")
            if kind == "input":
                inputs.append(name)
            continue
        dw, iw = widths[name]
        body.append(f"axi4_if #(.DATA_W({dw}), .ID_W({iw})) {name}(clk);")
        for signal, size, direction in axi_fields(interface_source, dw, iw):
            if kind == "axi4_if.slave":
                direction = "input" if direction == "output" else "output"
            elif kind == "axi4_if":
                direction = "input"  # Passive counters observe both channel directions.
            external = f"{name}__{signal}"
            declarations.append(f"{direction} wire {size} {external}")
            if direction == "input":
                inputs.append(external)
                body.append(f"assign {name}.{signal} = {external};")
            else:
                body.append(f"assign {external} = {name}.{signal};")
    wrapper_top = top + "_sg"
    body.append(f"{top} dut({', '.join(connections)});")
    return ("// Mechanical AXI port adapter; no stimulus or tied-off inputs.\nmodule " +
            wrapper_top + "(\n  " + ",\n  ".join(declarations) + ");\n" +
            "\n".join(body) + "\nendmodule\n", wrapper_top, inputs)


COUNTS = re.compile(r"Reported Messages:\s*(\d+)\s+Fatals?,\s*(\d+)\s+Errors?,\s*(\d+)\s+Warnings?,\s*(\d+)\s+Infos?", re.I)
DENIED = re.compile(r"failed to (?:check.?out|obtain).*license|unable to check.?out|license.*(?:denied|not available)|unavailability of .*license feature", re.I)
ROW = re.compile(r"^\[[0-9A-Fa-f]+\]\s+(\S+)\s+(?:(\S+)\s+)?(Fatal|Syntax|Error|Warning|Info|SynthesisError|SynthesisWarning|ElaborationError|ElaborationWarning)\s+(.+?)\s+(\d+)\s+(\d+)\s+(.*)$", re.M | re.I)


def accept_reports(directory, top, goals, returncode, execution_text, expected_version):
    """Require every named goal, complete reports, no waivers or truncation.

    Unknown/missing counts remain null. A zero process exit is never sufficient.
    Consolidated copies alone are counted, avoiding duplicates in per-goal trees.
    """
    directory = Path(directory)
    items, all_text = [], execution_text
    for goal in goals:
        parent = directory / "project" / "consolidated_reports" / (top + "_" + goal.replace("/", "_"))
        log, detail = parent / "spyglass.log", parent / "moresimple.rpt"
        item = dict(goal=goal, analysis_completed=False, fatals=None, errors=None,
                    warnings=None, warnings_by_rule={}, findings=[], reports=[], failed_checks=[])
        for path in (log, detail):
            if path.is_file():
                item["reports"].append(dict(path=str(path.relative_to(directory)), sha256=sha256(path)))
            else:
                item["failed_checks"].append("missing_" + path.name)
        if log.is_file():
            text = log.read_text(errors="replace")
            all_text += "\n" + text
            matches = COUNTS.findall(text)
            completed = "SpyGlass run completed at" in text and "SpyGlass Exit Code" in text
            if not matches:
                item["failed_checks"].append("missing_counts")
            else:
                f, e, w, info = map(int, matches[-1])
                item.update(fatals=f, errors=e, warnings=w, infos=info)
            if not completed:
                item["failed_checks"].append("analysis_incomplete")
            if "SpyGlass_v" + expected_version not in text:
                item["failed_checks"].append("version_mismatch")
        if detail.is_file():
            text = detail.read_text(errors="replace")
            all_text += "\n" + text
            for label in ("Waived", "Overlimit"):
                match = re.search(r"Number of " + label + r" Messages\s*:\s*(\d+)", text)
                if not match or int(match[1]) != 0:
                    item["failed_checks"].append(label.lower() + "_messages_or_missing_count")
            rows = ROW.findall(text)
            counted = collections.Counter("Fatal" if row[2].lower() == "syntax" else
                                          row[2].lower().removeprefix("synthesis").removeprefix("elaboration").capitalize() for row in rows)
            if item["fatals"] is not None:
                for severity, key in (("Fatal", "fatals"), ("Error", "errors"), ("Warning", "warnings"), ("Info", "infos")):
                    if counted[severity] != item[key]:
                        item["failed_checks"].append("detail_count_mismatch_" + key)
            for rule, alias, severity, file, line, weight, message in rows:
                if severity.lower() in ("syntax", "fatal", "synthesiserror", "elaborationerror") or rule == "ErrorAnalyzeBBox":
                    item["failed_checks"].append("elaboration_incomplete")
                if severity.lower() != "info":
                    item["findings"].append(dict(rule=rule, alias=alias, severity=severity,
                                                 file=file, line=int(line), message=message))
            item["warnings_by_rule"] = dict(collections.Counter(row[0] for row in rows if row[2].lower().endswith("warning")))
        item["failed_checks"] = list(dict.fromkeys(item["failed_checks"]))
        item["analysis_completed"] = not item["failed_checks"]
        if item["fatals"] or item["errors"] or item["warnings"]:
            item["failed_checks"].append("unreviewed_findings")
        items.append(item)
    # Rule catalogs list Ac_license01 even in successful runs. Only an actual
    # diagnostic or a reported violation establishes a license failure.
    denied = bool(DENIED.search(all_text)) or any(
        f["rule"] == "Ac_license01" and f["severity"] in ("Fatal", "Error")
        for item in items for f in item["findings"])
    complete = bool(items) and all(i["analysis_completed"] for i in items) and not denied and returncode in (0, 1)
    passed = complete and returncode == 0 and all(not i["failed_checks"] for i in items)
    return dict(decision="BLOCKED_LICENSE" if denied else "PASS" if passed else "FAIL",
                analysis_completed=complete, return_code=returncode, goals=items,
                acceptance="complete named goals; expected version; zero fatal/error/warning, waivers and overlimit messages")
