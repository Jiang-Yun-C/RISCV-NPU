#!/usr/bin/env python3
"""Author the v1 corpus once. Never overwrite a frozen corpus or tune on heldout."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def build():
    sets = {"dev": [], "heldout": []}

    def add(split, category, family, instruction, actions=(), readings=None, error=None,
            temperature=26, light=300, pair=None):
        rows = sets[split]
        rows.append({"id": f"{split}-{len(rows)+1:03d}", "category": category,
                     "family": family, "instruction": instruction,
                     "state": {"temperature": temperature, "light": light, "led": 0, "pwm": 0},
                     "state_source": "DESKTOP_SENSOR_FIXTURE", "pair_id": pair,
                     "legal": error is None,
                     "expected": {"actions": [list(a) for a in actions],
                                  "readings": readings or {}, "error": error}})

    # Development wording only. Numeric/readout expectations are explicit labels.
    for instruction, actions, readings in [
        ("打开LED灯。", [("led", 1)], {}), ("关闭LED灯。", [("led", 0)], {}),
        ("把PWM设为40%。", [("pwm", 40)], {}), ("把风扇占空比设为0%。", [("pwm", 0)], {}),
        ("把风扇占空比设为100%。", [("pwm", 100)], {}),
        ("读取温度。", [], {"temperature": 26}), ("读取光照。", [], {"light": 300}),
        ("报告温度和光照。", [], {"temperature": 26, "light": 300}),
        ("将PWM设成25%。", [("pwm", 25)], {}), ("让风扇停止。", [("pwm", 0)], {}),
    ]:
        add("dev", "single", "dev-single", instruction, actions, readings)

    dev_conditions = [
        ("如果温度高于30度，打开灯，否则关闭灯。", "temperature", 35, 25, [("led", 1)], [("led", 0)]),
        ("如果光照低于200勒克斯，打开LED灯，否则关闭LED灯。", "light", 100, 400, [("led", 1)], [("led", 0)]),
        ("温度大于28度时将风扇设为60%，否则设为0%。", "temperature", 32, 24, [("pwm", 60)], [("pwm", 0)]),
        ("光照小于100勒克斯时打开灯。", "light", 50, 300, [("led", 1)], []),
        ("温度达到30度就开灯，否则关灯。", "temperature", 30, 29, [("led", 1)], [("led", 0)]),
    ]
    for i, (text, sensor, a, b, yes, no) in enumerate(dev_conditions):
        for value, actions in [(a, yes), (b, no)]:
            add("dev", "conditional", f"dev-cond-{i}", text, actions,
                pair=f"dev-pair-{i}", **{sensor: value})

    for text, actions, readings in [
        ("先打开灯，再把风扇设为50%。", [("led", 1), ("pwm", 50)], {}),
        ("先将PWM设为20%，再关灯。", [("pwm", 20), ("led", 0)], {}),
        ("先关灯，再停止风扇。", [("led", 0), ("pwm", 0)], {}),
        ("打开灯，并报告温度。", [("led", 1)], {"temperature": 26}),
        ("关闭灯，并报告光照。", [("led", 0)], {"light": 300}),
        ("先开灯再关灯。", [("led", 1), ("led", 0)], {}),
        ("先把风扇设为30%，再设为70%。", [("pwm", 30), ("pwm", 70)], {}),
        ("报告温度和光照，然后打开灯。", [("led", 1)], {"temperature": 26, "light": 300}),
        ("先关闭风扇，再打开灯。", [("pwm", 0), ("led", 1)], {}),
        ("先把PWM设为100%，然后关灯，再报告温度。", [("pwm", 100), ("led", 0)], {"temperature": 26}),
    ]:
        add("dev", "multi", "dev-multi", text, actions, readings)

    for text, actions, readings in [
        ("请把灯点亮。", [("led", 1)], {}), ("请把灯熄灭。", [("led", 0)], {}),
        ("风扇调至半速，也就是50%。", [("pwm", 50)], {}),
        ("让风扇全速运转。", [("pwm", 100)], {}),
        ("把风扇停下来。", [("pwm", 0)], {}),
        ("现在多少摄氏度？", [], {"temperature": 26}),
        ("现在的照度是多少？", [], {"light": 300}),
        ("把指示灯开启。", [("led", 1)], {}),
        ("把指示灯关掉。", [("led", 0)], {}),
        ("PWM占空比调整为百分之五十。", [("pwm", 50)], {}),
    ]:
        add("dev", "synonym", "dev-synonym", text, actions, readings)
    for text in ["打开空调。", "关闭电视。", "把舵机转到90度。", "读取湿度。", "先开灯，再打开门锁。"]:
        add("dev", "illegal_device", "dev-illegal", text, error="UNSUPPORTED")
    for text in ["把PWM设为101%。", "把PWM设为-1%。", "把风扇设为150%。", "把风扇设为-20%。", "先打开灯，再将PWM设为110%。"]:
        add("dev", "out_of_range", "dev-range", text, error="RANGE")

    # Independent heldout phrase families, never selected by model output.
    for i, (on, off) in enumerate([
        ("执行LED开启命令。", "执行LED关闭命令。"),
        ("我需要你打开板上的灯。", "我需要你关闭板上的灯。"),
        ("现在请开启LED。", "现在请关闭LED。"),
        ("将LED设置为开。", "将LED设置为关。"),
    ]):
        for temp in [19, 33]:
            add("heldout", "single", f"held-single-led-{i}", on, [("led", 1)], temperature=temp)
            add("heldout", "single", f"held-single-led-{i}", off, [("led", 0)], temperature=temp)
    for i, text in enumerate(["请输出{v}%的PWM占空比。", "风扇的占空比改成{v}%。", "设置PWM输出：{v}%。", "请将风扇调到{v}%。"]):
        for v in [0, 15, 65, 100]:
            add("heldout", "single", f"held-single-pwm-{i}", text.format(v=v), [("pwm", v)])
    for i, (text, sensor) in enumerate([("告诉我温度传感器的当前数值。", "temperature"), ("请返回光照传感器的读数。", "light")]):
        for v in ([0, 17, 31, 42] if sensor == "temperature" else [0, 75, 550, 1000]):
            add("heldout", "single", f"held-single-read-{i}", text, readings={sensor: v}, **{sensor: v})

    conditions = [
        ("温度超过{t}摄氏度就点亮LED，未超过就熄灭LED。", "temperature", 27, [("led", 1)], [("led", 0)], "gt"),
        ("当温度低于{t}度时关灯，不低于时开灯。", "temperature", 22, [("led", 0)], [("led", 1)], "lt"),
        ("照度小于{t}勒克斯则点亮指示灯，否则熄灭指示灯。", "light", 180, [("led", 1)], [("led", 0)], "lt"),
        ("光照高于{t}勒克斯就关闭LED，其余情况开启LED。", "light", 450, [("led", 0)], [("led", 1)], "gt"),
        ("温度不低于{t}度时把PWM设成80%，否则PWM设成10%。", "temperature", 29, [("pwm", 80)], [("pwm", 10)], "ge"),
        ("温度不高于{t}度时把风扇调到20%，否则调到70%。", "temperature", 25, [("pwm", 20)], [("pwm", 70)], "le"),
        ("仅当照度低于{t}勒克斯时开启LED，其他情况不操作。", "light", 120, [("led", 1)], [], "lt"),
        ("仅在温度超过{t}度时关闭灯，其他情况不操作。", "temperature", 32, [("led", 0)], [], "gt"),
        ("若光照小于或等于{t}勒克斯则开灯，否则关灯。", "light", 250, [("led", 1)], [("led", 0)], "le"),
        ("若温度大于或等于{t}度则将PWM设为90%，否则设为0%。", "temperature", 31, [("pwm", 90)], [("pwm", 0)], "ge"),
    ]
    for i, (text, sensor, threshold, yes, no, op) in enumerate(conditions):
        for j in range(2):
            t = threshold + j * (5 if sensor == "temperature" else 40)
            vals = {"gt": (t+3, t), "lt": (t-3, t), "ge": (t, t-1), "le": (t, t+1)}[op]
            for v, actions in zip(vals, (yes, no)):
                add("heldout", "conditional", f"held-cond-{i}", text.format(t=t), actions,
                    pair=f"held-pair-{i}-{j}", **{sensor: v})

    for i, v in enumerate([5, 35, 75, 95]):
        examples = [
            (f"按顺序执行：点亮LED；风扇占空比设为{v}%。", [("led", 1), ("pwm", v)], {}),
            (f"按顺序执行：风扇占空比设为{v}%；熄灭LED。", [("pwm", v), ("led", 0)], {}),
            (f"先熄灭指示灯，接着将PWM调成{v}%。", [("led", 0), ("pwm", v)], {}),
            (f"先设置{v}%的PWM，再点亮LED。", [("pwm", v), ("led", 1)], {}),
            (f"先点亮指示灯，随后设置{v}%的PWM，最后熄灭指示灯。", [("led", 1), ("pwm", v), ("led", 0)], {}),
            (f"PWM先输出{v}%，然后输出0%。", [("pwm", v), ("pwm", 0)], {}),
            ("把LED点亮，同时告诉我温度传感器读数。", [("led", 1)], {"temperature": 20+i}),
            ("把LED熄灭，同时告诉我光照传感器读数。", [("led", 0)], {"light": 80+i*100}),
            (f"风扇设置为{v}%，并返回当前温度与光照。", [("pwm", v)], {"temperature": 20+i, "light": 80+i*100}),
            (f"汇报当前温度后，先熄灭LED，再把风扇调为{v}%。", [("led", 0), ("pwm", v)], {"temperature": 20+i}),
        ]
        for k, (text, actions, readings) in enumerate(examples):
            add("heldout", "multi", f"held-multi-{k}", text, actions, readings, temperature=20+i, light=80+i*100)

    for i in range(4):
        for k, (text, actions, readings) in enumerate([
            ("让指示灯亮起来吧。", [("led", 1)], {}),
            ("麻烦把指示灯灭掉。", [("led", 0)], {}),
            ("风扇开到最大，也就是百分之百。", [("pwm", 100)], {}),
            ("风扇用一半占空比运行。", [("pwm", 50)], {}),
            ("不需要风扇转了，请停转。", [("pwm", 0)], {}),
            ("帮忙看一下现在的气温读数。", [], {"temperature": 18+i*4}),
            ("帮忙看一下此刻的光照强度。", [], {"light": 40+i*200}),
            ("PWM改为百分之二十五。", [("pwm", 25)], {}),
            ("使LED处于开启状态。", [("led", 1)], {}),
            ("使LED处于关闭状态。", [("led", 0)], {}),
        ]):
            add("heldout", "synonym", f"held-synonym-{k}", text, actions, readings, temperature=18+i*4, light=40+i*200)
    for i, text in enumerate([
        "启动加湿器。", "关掉电暖器。", "开启摄像头。", "解锁大门。", "打开窗帘。",
        "把机械臂抬高。", "播放音乐。", "把空调温度调到26度。", "查询空气湿度。", "读取二氧化碳浓度。",
        "点亮LED，然后启动水泵。", "停下风扇，再给手机充电。", "开灯并打开冰箱。",
        "设置PWM为50%，再启动电机二号。", "读取温度，再读取气压。", "打开投影仪。",
        "切换电视节目。", "运行扫地机器人。", "控制舵机旋转45度。", "把电饭锅关掉。",
    ]):
        add("heldout", "illegal_device", f"held-illegal-{i}", text, error="UNSUPPORTED")
    for i, text in enumerate(["PWM占空比请设定成{v}%。", "让风扇以{v}%占空比运行。", "点亮LED，随后设置PWM为{v}%。", "先设置风扇为{v}%，接着熄灭LED。"]):
        for v in [-100, -5, 102, 120, 200]:
            add("heldout", "out_of_range", f"held-range-{i}", text.format(v=v), error="RANGE")
    return sets


def main():
    corpus = build()
    assert len(corpus["dev"]) == 50 and len(corpus["heldout"]) == 200
    assert not ({r["instruction"] for r in corpus["dev"]} & {r["instruction"] for r in corpus["heldout"]})
    paths = [HERE / "dev.jsonl", HERE / "heldout.jsonl", HERE / "dataset-lock.json"]
    if any(p.exists() for p in paths):
        raise SystemExit("Frozen corpus exists; refusing overwrite. Version a new corpus explicitly.")
    hashes = {}
    for split, rows in corpus.items():
        data = "".join(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n" for r in rows).encode()
        (HERE / f"{split}.jsonl").write_bytes(data)
        hashes[f"{split}.jsonl"] = {"sha256": hashlib.sha256(data).hexdigest(), "count": len(rows)}
    (HERE / "dataset-lock.json").write_text(json.dumps({"version": 1, "seed": 20261002,
        "files": hashes, "policy": "Freeze before inference; dev-only tuning; heldout never used for prompt/quantization selection",
        "independence": "Disjoint Chinese instruction and phrase-family sets; same public device schema; authored fixtures, not a population sample"}, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
