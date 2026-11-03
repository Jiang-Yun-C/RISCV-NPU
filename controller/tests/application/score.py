"""Strict, model-independent JSON action/readout scoring. No output repair."""
from collections import Counter, defaultdict
import json
import math


def no_duplicate_keys(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def wire_response(expected):
    """Compact wire format; labels remain the same normalized semantic objects."""
    if expected["error"] is not None:
        return [["error", expected["error"]]]
    return expected["actions"] + [[key, value] for key, value in expected["readings"].items()]


def parse_response(text):
    # A model-authored explanation may precede a final RESULT= line. Only that
    # explicitly delimited command array is executable; no JSON extraction/repair.
    if "RESULT=" in text:
        if text.count("RESULT=") != 1 or not text.splitlines()[-1].startswith("RESULT="):
            raise ValueError("RESULT must occur once on the final line")
        text = text.splitlines()[-1][len("RESULT="):]
    commands = json.loads(text, object_pairs_hook=no_duplicate_keys,
                     parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)))
    if type(commands) is not list or len(commands) > 10:
        raise ValueError("expected a JSON command array")
    obj = {"actions": [], "readings": {}, "error": None}
    for command in commands:
        if type(command) is not list or len(command) != 2 or type(command[0]) is not str:
            raise ValueError("invalid command pair")
        key, value = command
        if key == "error":
            if len(commands) != 1 or value not in ("RANGE", "UNSUPPORTED"):
                raise ValueError("refusal must be the only command")
            obj["error"] = value
        elif key in ("temperature", "light"):
            if key in obj["readings"]:
                raise ValueError("duplicate readout")
            obj["readings"][key] = value
        else:
            obj["actions"].append(command)
    if type(obj) is not dict or set(obj) != {"actions", "readings", "error"}:
        raise ValueError("expected exactly actions/readings/error")
    if type(obj["actions"]) is not list or len(obj["actions"]) > 8:
        raise ValueError("invalid action list")
    for action in obj["actions"]:
        if type(action) is not list or len(action) != 2:
            raise ValueError("invalid action tuple")
        device, value = action
        if device not in ("led", "pwm") or type(value) is not int:
            raise ValueError("unknown device or noninteger value")
        if not 0 <= value <= (1 if device == "led" else 100):
            raise ValueError("out of range action")
    if type(obj["readings"]) is not dict or not set(obj["readings"]) <= {"temperature", "light"}:
        raise ValueError("unknown readout")
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in obj["readings"].values()):
        raise ValueError("nonnumeric reading")
    if obj["error"] not in (None, "RANGE", "UNSUPPORTED"):
        raise ValueError("unknown error")
    if obj["error"] is not None and (obj["actions"] or obj["readings"]):
        raise ValueError("refusal must not contain actions or readings")
    return obj


def score(case, text, stop_reason):
    try:
        parsed = parse_response(text)
    except (ValueError, TypeError) as error:
        return {"pass": False, "schema_valid": False, "reason": str(error), "parsed": None}
    ok = parsed == case["expected"] and stop_reason == "eos"
    return {"pass": ok, "schema_valid": True, "parsed": parsed,
            "reason": "exact_match" if ok else ("missing_eos" if stop_reason != "eos" else "semantic_mismatch")}


def summarize(cases, records):
    if len(cases) != len(records) or [c["id"] for c in cases] != [r["id"] for r in records]:
        raise ValueError("missing, reordered or extra results")
    groups = defaultdict(list)
    pairs = defaultdict(list)
    for case, record in zip(cases, records):
        result = score(case, record["output"], record["stop_reason"])
        groups[case["category"]].append(result["pass"])
        groups["legal" if case["legal"] else "illegal"].append(result["pass"])
        if case["pair_id"]:
            pairs[case["pair_id"]].append((case, result))
    metrics = {k: {"passed": sum(v), "total": len(v), "rate": sum(v)/len(v)} for k, v in groups.items()}
    pair_results = {}
    for key, rows in pairs.items():
        if len(rows) != 2 or rows[0][0]["instruction"] != rows[1][0]["instruction"]:
            raise ValueError("invalid counterfactual pair")
        if rows[0][0]["expected"]["actions"] == rows[1][0]["expected"]["actions"]:
            raise ValueError("counterfactual labels must change")
        pair_results[key] = all(r["pass"] for _, r in rows)
    return {"metrics": metrics, "sensor_pairs": {"passed": sum(pair_results.values()),
            "total": len(pair_results), "results": pair_results},
            "stop_reasons": dict(Counter(r["stop_reason"] for r in records)),
            "count": len(records)}
