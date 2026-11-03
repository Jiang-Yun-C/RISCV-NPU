#!/usr/bin/env python3
"""Bounded service smoke probe: exact UART identity, LF sync, :memory, disconnect.

Optional --one-token submits the retained :ids 1 0 255 1023 smoke case.
Never programs devices, resets, reloads SD, or enables pressure.
Every attempt requires a new output directory; partial evidence is retained.
"""
import argparse
import base64
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import threading
import time
import traceback
from urllib.request import Request, urlopen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--serial-deps")
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument("--one-token", action="store_true")
    args = parser.parse_args()
    output = Path(args.output); output.mkdir(parents=True, exist_ok=False)
    if args.serial_deps:
        sys.path.insert(0, args.serial_deps)
    from server import ConsoleServer
    server = ConsoleServer(("127.0.0.1", 0))
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    owner = "nexusrv-demo-bounded-probe"
    base = f"http://127.0.0.1:{server.server_port}"
    token = server.token
    raw = bytearray(); seq = 0
    report = dict(status="FAIL", startedAt=datetime.now(timezone.utc).isoformat(), commands=[],
        scope="Actual UART service synchronization and MEMORY readback only; no inference or programming",
        programmingPerformed=False, resetPerformed=False, modelInferencePerformed=False)
    def api(path, body=None):
        request = Request(base + path, data=None if body is None else json.dumps(body).encode(),
            headers={"Content-Type":"application/json", "X-Console-Token":token, "X-Console-Owner":owner})
        with urlopen(request, timeout=10) as response:
            return json.load(response)
    def ready(timeout=None):
        nonlocal seq
        segment = bytearray(); deadline = time.monotonic() + (timeout or args.timeout)
        while time.monotonic() < deadline:
            data = api(f"/api/read?after={seq}")
            for chunk in data["chunks"]:
                seq = chunk["seq"]
                value = base64.b64decode(chunk["data"]); raw.extend(value); segment.extend(value)
            if not data["connected"]:
                raise RuntimeError(data["error"] or "UART disconnected")
            if segment.endswith(b"T25 READY\n"):
                return segment.decode("utf-8")
            time.sleep(.05)
        raise TimeoutError("No complete T25 READY in bounded probe window; board may be busy or not ready")
    try:
        ports = api("/api/ports"); report["ports"] = ports
        api("/api/connect", {"port":args.port})
        report["port"] = args.port
        api("/api/write", {"command":""}); report["commands"].append("\n"); ready()
        api("/api/write", {"command":":memory"}); report["commands"].append(":memory\n")
        text = ready()
        match = re.search(r"^T25 MEMORY (committed_bytes=.*)$", text, re.M)
        if not match:
            raise ValueError("Missing complete board MEMORY record")
        counters = {k:int(v,16) for k,v in re.findall(r"(\w+)=([0-9a-f]{16})", match[1])}
        if set(counters) != {"committed_bytes","peak_committed_bytes","regions","runtime_write_readback_bytes"}:
            raise ValueError("Incomplete MEMORY counters")
        report.update(status="PASS_UART_SYNC_MEMORY_ONLY", memory=counters)
        if args.one_token:
            command = ":ids 1 0 255 1023"
            report["scope"] = "Actual HTTP UART bridge: LF sync, MEMORY and retained one-output inference smoke case; no numerical tensor qualification"
            api("/api/write", {"command":command}); report["commands"].append(command + "\n")
            text = ready(timeout=240)
            match = re.search(r"^T25 METRICS (.*)$", text, re.M)
            if not match or re.search(r"^T25 IDS 00000105 *$", text, re.M) is None or "T25 TEXT er\n" not in text:
                raise ValueError("Short request does not match retained one-token board reference")
            metrics = {k:int(v,16) for k,v in re.findall(r"(\w+)=([0-9a-f]{16})", match[1])}
            if metrics.get("generated") != 1 or metrics.get("prompt") != 3 or metrics.get("ce_calls") != 507 or metrics.get("fallback_calls") != 0:
                raise ValueError("Unexpected short-request routing or output count")
            report.update(status="PASS_UART_MEMORY_ONE_TOKEN_SMOKE", modelInferencePerformed=True, metrics=metrics,
                reference="T25_DIAG_SESSIONS/t25-sd-gap-sequence-20261016-v1-sessions after-reload; ID 261 / text er")
    except Exception:
        report["status"] = "FAIL"
        report["error"] = traceback.format_exc()
    finally:
        server.bridge.disconnect(); server.shutdown(); server.server_close(); thread.join()
        (output / "uart.bin").write_bytes(raw)
        report.update(finishedAt=datetime.now(timezone.utc).isoformat(), rawBytes=len(raw), rawSha256=hashlib.sha256(raw).hexdigest())
        (output / "result.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(dict(status=report["status"], bytes=len(raw), memory=report.get("memory")), ensure_ascii=False))
    return 0 if report["status"].startswith("PASS_") else 1


if __name__ == "__main__":
    raise SystemExit(main())
