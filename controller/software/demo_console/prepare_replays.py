#!/usr/bin/env python3
"""Extract small, unchanged UART action slices from retained physical evidence."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASES = [
    ("greeting", "中文问候 · 真实板端输出", "evidence/T25_SESSION_RECOVERY/t25-sessions-recovery-20261016-v1", "utf8-text",
     "旧 v7 中文实板记录 · 已按未变路径正式复用 · 非当前候选重新执行"),
    ("one-token", "单步推理 · 最新候选", "evidence/T25_DIAG_SESSIONS/t25-sd-gap-sequence-20261016-v1-sessions", "after-reload",
     "当前验收候选 · 3 个输入 / 1 个输出 · 历史实测，非现场执行"),
    ("32-tokens", "连续 32 token · 数值测试输入", "evidence/T25_PRESSURE/t25-sd-gap-sequence-20261016-v1-pressure", "baseline-after-pressure",
     "当前验收候选 · 数值测试 token 输入，非聊天指令 · 历史实测"),
]


def main():
    samples = []
    for identifier, title, directory, name, note in CASES:
        path = ROOT / directory
        metadata = json.loads((path / "capture.json").read_text())
        action = next(a for a in metadata["actions"] if a["name"] == name)
        if action["status"] != "PASS":
            raise ValueError("Only retained successful board actions may be included")
        with (path / "capture.bin").open("rb") as source:
            source.seek(action["start_byte"])
            raw = source.read(action["end_byte"] - action["start_byte"])
        if not raw.endswith(b"T25 READY\n"):
            raise ValueError("Incomplete transcript slice")
        samples.append(dict(id=identifier, title=title, command=action["command"], raw=raw.decode("utf-8"), note=note,
            provenance=dict(file=directory + "/capture.bin", startByte=action["start_byte"], endByte=action["end_byte"],
                sha256=hashlib.sha256(raw).hexdigest(), sourceAction=name,
                timing="Event order only; original capture has no per-line timestamps")))
    output = Path(__file__).resolve().parent / "static/replays.json"
    output.write_text(json.dumps(samples, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Prepared {len(samples)} real-board replay slices ({output.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
