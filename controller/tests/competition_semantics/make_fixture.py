#!/usr/bin/env python3
"""Create clearly marked synthetic console exports to test the evaluator only."""
import argparse
import base64
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from software.competition_semantics import evaluate


def raw_result(text, eos=True):
    ids = [100, 151645 if eos else 101]
    fields = {"session": 1, "prompt": 3, "generated": 2, "stop": 1 if eos else 2, "kv": 4,
              "total_ticks": 250000000, "first_token_ticks": 125000000,
              "prefill_ticks": 125000000, "decode_ticks": 125000000,
              "ce_calls": 1, "fallback_calls": 0}
    return ("T25 IDS " + " ".join(f"{i:08x}" for i in ids) + " \n"
            + f"T25 TEXTLEN 1 bytes={len(text.encode('utf8')):016x}\nT25 TEXT " + text + "\n"
            + "T25 METRICS " + " ".join(f"{k}={v:016x}" for k, v in fields.items())
            + " \nT25 READY\n")


def export_record(command, text, contract, eos=True):
    raw = raw_result(text, eos);data = raw.encode("utf8")
    chunks = []
    for index, start in enumerate(range(0, len(data), 37)):
        part = data[start:start + 37]
        chunks.append({"seq": index + 1, "data": base64.b64encode(part).decode(), "bytes": len(part),
                       "browserReceive": 2000 + index, "received_ns": str(2000000000 + index * 1000000),
                       "transport": "fixture", "discardIncomplete": False})
    return {"schema": "nexusrv-demo-v1", "source": "fixture", "fixture": True,
            "fixture_note": "SYNTHETIC EXPECTED ANSWERS: evaluator test, never model inference or board accuracy.",
            "command": command, "raw": raw, "rawChunks": chunks, "complete": True,
            "clockHz": contract["clock_hz"],
            "identity": {"model": contract["model"], "tokenizer": contract["tokenizer"]},
            "metrics": {"deliberately_untrusted": True},
            "timing": {"host": {"clock": "python.time.monotonic_ns", "write_start": "1000000000"},
                       "browser": {"clock": "browser.performance.now_ms", "write_start": 1000}}}


def make(directory):
    manifest = evaluate.make_plan(directory)
    dataset, commands, contract, _ = evaluate.cases_and_commands()
    for case in dataset["cases"]:
        path = manifest.parent / "exports" / (case["id"] + ".json")
        path.write_text(json.dumps(export_record(commands[case["id"]], evaluate.encode(case["program"]), contract),
                                   ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args();print(make(args.output))
