#!/usr/bin/env python3
"""Independent v2 splits: authored phrase families and labels, frozen before training."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import random

HERE = Path(__file__).resolve().parent
SETS = {s: [] for s in ("train", "dev", "heldout")}


def reference(program, state):
    # Dataset-author oracle: deliberately independent of production execution.
    actions, readings = [], {}
    stack = list(reversed(program))
    while stack:
        node = stack.pop()
        if node[0] == "reject":
            return {"actions": [], "readings": {}, "error": "UNSUPPORTED"}
        if node[0] == "pwm" and (node[1] < 0 or node[1] > 100):
            return {"actions": [], "readings": {}, "error": "RANGE"}
        if node[0] == "read":
            readings[node[1]] = state[node[1]]
        elif node[0] == "if":
            _, sensor, relation, threshold, yes, no = node
            lhs = state[sensor]
            if relation == ">": flag = lhs > threshold
            elif relation == "<": flag = lhs < threshold
            elif relation == ">=": flag = lhs >= threshold
            elif relation == "<=": flag = lhs <= threshold
            else: raise ValueError(relation)
            stack.extend(reversed(yes if flag else no))
        else:
            actions.append(node)
    return {"actions": actions, "readings": readings, "error": None}


def add(split, category, family, text, plan, rng, state=None, pair=None):
    state = state or {"temperature": rng.randint(5, 42), "light": rng.randint(0, 1500), "led": rng.randrange(2), "pwm": rng.randint(0, 100)}
    expected = reference(plan, state)
    rows = SETS[split]
    rows.append({"id": f"v2-{split}-{len(rows)+1:04d}", "category": category,
                 "family": f"{split}-{family}", "instruction": text, "program": plan,
                 "state": state, "state_source": "DESKTOP_SENSOR_FIXTURE",
                 "pair_id": pair, "legal": expected["error"] is None, "expected": expected})


def atom(rng, split, kind=None):
    kind = kind or rng.choice(["on", "off", "pwm", "temp", "light"])
    lamp = rng.choice(["灯", "LED", "指示灯"])
    fan = rng.choice(["风扇", "PWM"])
    n = rng.randint(0, 100)
    forms = {
        "train": {"on": [f"打开{lamp}", f"开启{lamp}", f"点亮{lamp}"],
                  "off": [f"关闭{lamp}", f"熄灭{lamp}", f"关掉{lamp}"],
                  "pwm": [f"把{fan}设为{n}%", f"将{fan}占空比调整到{n}%", f"{fan}调到{n}%"],
                  "temp": ["读取温度", "报告温度", "查询当前温度"],
                  "light": ["读取光照", "报告光照", "查询当前光照"]},
        "dev": {"on": [f"请让{lamp}亮起来"], "off": [f"请让{lamp}灭掉"],
                "pwm": [f"请将{fan}的占空比设置成{n}%"], "temp": ["请给出现在的温度值"], "light": ["请给出现在的光照值"]},
        "heldout": {"on": [f"我想让{lamp}保持点亮"], "off": [f"我想让{lamp}保持熄灭"],
                    "pwm": [f"{fan}的目标占空比取{n}%"], "temp": ["告诉我此时温度传感器的示数"], "light": ["告诉我此时光照传感器的示数"]}}
    program = {"on": ["led", 1], "off": ["led", 0], "pwm": ["pwm", n],
               "temp": ["read", "temperature"], "light": ["read", "light"]}[kind]
    return rng.choice(forms[split][kind]), program


def make_split(split):
    rng = random.Random({"train": 30031, "dev": 30047, "heldout": 30059}[split])
    counts = {"train": [384, 512, 512, 256, 256, 128], "dev": [10, 10, 10, 10, 5, 5], "heldout": [40, 40, 40, 40, 20, 20]}[split]
    for i in range(counts[0]):
        text, node = atom(rng, split, ["on", "off", "pwm", "temp", "light"][i%5])
        add(split, "single", "single", text + "。", [node], rng)
    relations = [("高于", ">"), ("低于", "<"), ("不低于", ">="), ("不高于", "<=")]
    for i in range(counts[1]//2):
        sensor = "temperature" if i%2==0 else "light"
        sensor_text = "温度" if sensor=="temperature" else "光照"
        threshold = rng.randint(15, 38) if sensor=="temperature" else rng.randint(5, 90)*10
        phrase, cmp = relations[(i//2)%4]
        if split == "dev": phrase = {">":"超过", "<":"小于", ">=":"达到", "<=":"小于或等于"}[cmp]
        if split == "heldout": phrase = {">":"大于", "<":"低于", ">=":"大于或等于", "<=":"不超过"}[cmp]
        yes_text, yes = atom(rng, split, "on" if i%3==0 else "pwm")
        no_text, no = atom(rng, split, "off" if i%3==0 else "pwm")
        if yes == no: no = ["pwm", 0 if yes[1] else 100]; no_text = f"PWM设为{no[1]}%"
        no_branch = [] if i%5==4 else [no]
        endings = {"train": f"，否则{no_text}", "dev": f"，不满足时{no_text}", "heldout": f"，其余情况则{no_text}"}
        endings_empty = {"train": "，否则不操作", "dev": "，不满足时不做任何操作", "heldout": "，其余情况不要采取动作"}
        starts = {"train": "如果", "dev": "当", "heldout": "仅在"}
        text = f"{starts[split]}{sensor_text}{phrase}{threshold}{'度' if sensor=='temperature' else '勒克斯'}时，{yes_text}" + (endings[split] if no_branch else endings_empty[split]) + "。"
        plan = [["if", sensor, cmp, threshold, [yes], no_branch]]
        vals = {">": (threshold+1, threshold), "<": (threshold-1, threshold), ">=": (threshold, threshold-1), "<=": (threshold, threshold+1)}[cmp]
        for val in vals:
            state = {"temperature": 24, "light": 360, "led": 0, "pwm": 0}; state[sensor] = val
            add(split, "conditional", "condition", text, plan, rng, state, f"v2-{split}-pair-{i:03d}")
    for i in range(counts[2]):
        nodes = [atom(rng, split, kind) for kind in [["on", "pwm"], ["pwm", "off"], ["off", "temp"], ["pwm", "temp", "light"], ["on", "off"], ["light", "pwm", "on"], ["pwm", "pwm"], ["temp", "light"]][i%8]]
        prefix, join = {"train": ("先", "，再"), "dev": ("请依次", "，然后"), "heldout": ("按照这个顺序：", "；随后")}[split]
        add(split, "multi", "sequence", prefix + join.join(t for t, _ in nodes) + "。", [n for _, n in nodes], rng)
    synonyms = {
        "train": [("让灯亮起来", [["led",1]]), ("让灯灭掉", [["led",0]]), ("风扇全速", [["pwm",100]]), ("风扇半速", [["pwm",50]]), ("停止风扇", [["pwm",0]]), ("现在多少摄氏度", [["read","temperature"]]), ("现在照度多少", [["read","light"]]), ("风扇调至百分之二十五", [["pwm",25]])],
        "dev": [("亮起指示灯", [["led",1]]), ("熄掉指示灯", [["led",0]]), ("让风扇以最大占空比工作", [["pwm",100]]), ("风扇用百分之五十运行", [["pwm",50]]), ("风扇停止运转", [["pwm",0]]), ("温度传感器测得了多少", [["read","temperature"]]), ("照度传感器测得了多少", [["read","light"]]), ("风扇以四分之一占空比运行", [["pwm",25]])],
        "heldout": [("将指示灯切换到亮起状态", [["led",1]]), ("将指示灯切换到熄灭状态", [["led",0]]), ("把风扇的占空比开满", [["pwm",100]]), ("风扇占空比减至一半", [["pwm",50]]), ("让风扇不再转动", [["pwm",0]]), ("目前环境温度的数值是多少", [["read","temperature"]]), ("目前环境照度的数值是多少", [["read","light"]]), ("把风扇占空比改成百分之二十五", [["pwm",25]])]}
    for i in range(counts[3]):
        text, plan = synonyms[split][i%8]
        # Varied politeness is training augmentation, not a fake independent sample.
        prefix = rng.choice(["", "请", "麻烦", "现在"]) if split=="train" else ""
        add(split, "synonym", f"synonym-{i%8}", prefix+text+"。", plan, rng)
    unknown = {"train": ["空调", "电视", "水泵", "摄像头", "窗帘", "舵机", "机械臂", "加湿器", "门锁", "电暖器", "投影仪", "冰箱", "气压", "湿度", "二氧化碳传感器", "音响"],
               "dev": ["洗衣机", "收音机", "雨量传感器", "电饭锅", "净水器"],
               "heldout": ["咖啡机", "烤箱", "扫地机", "电磁炉", "抽油烟机", "洗碗机", "热水器", "路由器", "空气净化器", "打印机", "土壤湿度传感器", "烟雾传感器", "血压计", "风速传感器", "噪声传感器", "电动门", "自动晾衣架", "显示器", "饮水机", "电动窗"]}[split]
    for i in range(counts[4]):
        device = unknown[i%len(unknown)]
        action = "读取" if "传感器" in device or device in ("湿度", "气压") else rng.choice(["打开", "关闭"])
        text = f"{action}{device}"
        if i%3 == 1: text = atom(rng, split, "on")[0] + "，然后" + text
        if i%3 == 2: text += "，再" + atom(rng, split, "pwm")[0]
        add(split, "illegal_device", "unknown", text+"。", [["reject", "UNSUPPORTED"]], rng)
    for i in range(counts[5]):
        low, high = {"train": (-30, 140), "dev": (-34, 149), "heldout": (-47, 169)}[split]
        value = rng.randint(low, -1) if i%2==0 else rng.randint(101, high)
        text = {"train": f"把PWM设为{value}%", "dev": f"请将风扇占空比设置成{value}%", "heldout": f"风扇的目标占空比取{value}%"}[split]
        plan = [["pwm", value]]
        if i%3==1: text = atom(rng, split, "on")[0]+"，然后"+text; plan.insert(0,["led",1])
        add(split, "out_of_range", "range", text+"。", plan, rng)


def main():
    if (HERE/"dataset-lock.json").exists():
        raise SystemExit("v2 corpus already frozen; refusing overwrite")
    for split in SETS: make_split(split)
    assert [len(SETS[s]) for s in SETS] == [2048, 50, 200]
    for a,b in [("train","dev"),("train","heldout"),("dev","heldout")]:
        assert not ({r["instruction"] for r in SETS[a]} & {r["instruction"] for r in SETS[b]})
    files={}
    for split, rows in SETS.items():
        data=''.join(json.dumps(r,ensure_ascii=False,separators=(',',':'))+'\n' for r in rows).encode()
        (HERE/f"{split}.jsonl").write_bytes(data)
        files[f"{split}.jsonl"]={"sha256":hashlib.sha256(data).hexdigest(),"count":len(rows),
                                "categories":dict(Counter(r['category'] for r in rows)),
                                "unique_instructions":len({r['instruction'] for r in rows})}
    (HERE/'dataset-lock.json').write_text(json.dumps({"version":2,"files":files,"policy":"train-only gradient updates; dev-only model selection; heldout unopened for inference until release freeze; v1 heldout never reused for selection"},ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(files,ensure_ascii=False,indent=2))


if __name__=='__main__': main()
