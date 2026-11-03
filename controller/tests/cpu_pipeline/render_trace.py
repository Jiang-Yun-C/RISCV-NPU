#!/usr/bin/env python3
"""Render a small, explicitly simulated waveform excerpt from checked raw samples."""
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import tempfile


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("result", type=Path)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--before", type=int, default=12)
    p.add_argument("--cycles", type=int, default=36)
    a = p.parse_args()
    if not 8 <= a.cycles <= 64 or not 0 <= a.before < a.cycles:
        p.error("use 8..64 displayed cycles and a smaller nonnegative pretrigger")
    receipt = a.output.with_suffix(a.output.suffix + ".json")
    if a.output.exists() or receipt.exists():
        p.error("refusing to overwrite a figure")
    from check_profile import validate
    checked = validate(a.result)
    result = json.loads(a.result.read_text())
    csv_path = a.result.parent / result["trace_files"]["csv"]["name"]
    with csv_path.open(newline="") as stream:
        rows = [{k: int(v) for k, v in row.items()} for row in csv.DictReader(stream)]
    trigger = checked["trace"]["trigger_cycle"]
    first = max(rows[0]["cycle"], trigger - a.before)
    selected = [r for r in rows if first <= r["cycle"] < first + a.cycles]
    if len(selected) != a.cycles:
        p.error("requested excerpt exceeds stored bounded samples")
    os.environ.setdefault("MPLCONFIGDIR", tempfile.mkdtemp(prefix="t09-matplotlib-"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle, Patch
    fig = plt.figure(figsize=(20, 9.5))
    grid = fig.add_gridspec(2, 1, height_ratios=[5.2, 5.4], hspace=0.23)
    top, wave = fig.add_subplot(grid[0]), fig.add_subplot(grid[1])
    labels = ["F: fetch response", "D: decode", "E: execute", "M: memory", "W: writeback"]
    pcs = ["fetch_pc", "decode_pc", "execute_pc", "memory_pc", "writeback_pc"]
    colors = {"empty": "#f1f5f9", "fire": "#d6eadf", "held": "#f9dfa2", "removed": "#f2bac0"}
    for col, row in enumerate(selected):
        for stage, pc in enumerate(pcs):
            valid = (row["valid_mask"] >> stage) & 1
            held = (row["stuck_mask"] >> stage) & 1
            remove = stage and (row["remove_mask"] >> (stage - 1)) & 1
            state = "empty" if not valid else "removed" if remove else "held" if held else "fire"
            top.add_patch(Rectangle((col, stage), 1, 1, facecolor=colors[state], edgecolor="white", linewidth=0.5))
            if valid:
                top.text(col + .5, stage + .50, f"{row[pc]:08x}", ha="center", va="center", fontsize=5.6, family="monospace")
    top.set_xlim(0, a.cycles); top.set_ylim(5, 0)
    top.set_yticks([i + .5 for i in range(5)], labels)
    top.set_xticks([i + .5 for i in range(0, a.cycles, 2)], [f"{selected[i]['cycle']-trigger:+d}" for i in range(0, a.cycles, 2)])
    trigger_label = {"mispredict": "conditional-branch misprediction", "retire": "retirement", "data-wait": "data-response wait"}[checked["trace"]["trigger_kind"]]
    top.set_xlabel("Cycles relative to actual " + trigger_label + " trigger")
    for spine in top.spines.values(): spine.set_visible(False)
    top.tick_params(length=0)
    top.legend(handles=[Patch(facecolor=colors[k], label=v) for k,v in
        [("fire", "Valid / transfer"),("held", "Valid / held"),("removed", "Valid / removed"),("empty", "Invalid")]],
        loc="lower left", bbox_to_anchor=(0,1.02), ncol=4, frameon=False, fontsize=9)
    signals = [("conditional_branch", "Conditional branch", "#345a89"), ("mispredict", "Mispredict", "#ba263c"),
        ("retire", "Retire", "#328056"), ("execute_stall", "Execute stall", "#bd7b14"),
        ("i_read_wait", "I response wait", "#6b58a1"), ("d_read_wait", "D response wait", "#328b92"),
        ("data_bus_hazard", "D write-order hazard", "#ad5e2b"), ("fetch_flush", "Frontend flush level", "#805880")]
    for lane, (key, label, color) in enumerate(signals):
        vals = [row[key] for row in selected]
        x = list(range(a.cycles + 1))
        y = [lane + .75 - .5 * v for v in vals + [vals[-1]]]
        wave.step(x, y, where="post", color=color, linewidth=1.5)
        wave.axhline(lane + .9, color="#e3e7ec", linewidth=.5)
    wave.set_xlim(0,a.cycles);wave.set_ylim(len(signals),0)
    wave.set_yticks([i+.5 for i in range(len(signals))], [s[1] for s in signals])
    wave.set_xticks(list(range(0,a.cycles,2)), [str(selected[i]["cycle"]) for i in range(0,a.cycles,2)], rotation=45, ha="right")
    wave.set_xlabel("Actual simulator cycle number; every sample is taken before the rising edge")
    for spine in wave.spines.values():spine.set_visible(False)
    wave.tick_params(length=0)
    trigger_col=trigger-first
    for axes in (top,wave):axes.axvline(trigger_col, color="#b6283d", linestyle="--", linewidth=1)
    fig.suptitle("T09 CPU: actual RTL simulation samples — NOT a physical ILA capture", fontsize=17, weight="bold", y=.985)
    fig.text(.5,.945, f"{a.result.stem}  |  {checked['symbol']['name']} trigger at cycle {trigger:,}  |  bounded behavioral AXI memory", ha="center",fontsize=10)
    fig.text(.5,.018,"F is one fetch-response observation point; PC text is meaningful only when valid. Event counters overlap. This excerpt is not a CoreMark/MHz or board timing result.",ha="center",fontsize=9)
    fig.subplots_adjust(left=.115,right=.99,top=.85,bottom=.12)
    a.output.parent.mkdir(parents=True,exist_ok=True)
    fig.savefig(a.output,dpi=160)
    plt.close(fig)
    digest=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
    receipt.write_text(json.dumps({"scope":"actual cycle samples; simulation only; physical_ila_performed=false",
        "result_file":a.result.name,"result_sha256":digest(a.result),"csv_sha256":digest(csv_path),
        "figure_sha256":digest(a.output),"first_cycle":first,"last_cycle":first+a.cycles-1,
        "trigger_cycle":trigger,"renderer_sha256":digest(Path(__file__))},indent=2)+"\n")
    print(a.output)


if __name__ == "__main__":
    main()
