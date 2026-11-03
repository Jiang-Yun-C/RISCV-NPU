"""Interpret a bounded JSON program. Never parse or classify natural language."""
import json
import math


class ProgramError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def parse(text):
    def reject_constant(_):
        raise ProgramError("FORMAT")
    try:
        value = json.loads(text, parse_constant=reject_constant)
    except (ValueError, TypeError, RecursionError):
        raise ProgramError("FORMAT") from None
    return value


def validate(program, depth=0, budget=None):
    if budget is None:
        budget = [32]
    if type(program) is not list or depth > 2 or len(program) > 8:
        raise ProgramError("FORMAT")
    for node in program:
        budget[0] -= 1
        if budget[0] < 0 or type(node) is not list or not node or type(node[0]) is not str:
            raise ProgramError("FORMAT")
        op = node[0]
        if op in ("led", "pwm"):
            if len(node) != 2 or type(node[1]) is not int:
                raise ProgramError("FORMAT")
            if not 0 <= node[1] <= (1 if op == "led" else 100):
                raise ProgramError("RANGE")
        elif op == "read":
            if len(node) != 2 or type(node[1]) is not str:
                raise ProgramError("FORMAT")
            if node[1] not in ("temperature", "light"):
                raise ProgramError("UNSUPPORTED")
        elif op == "if":
            if len(node) != 6:
                raise ProgramError("FORMAT")
            _, sensor, cmp, threshold, yes, no = node
            if type(sensor) is not str or type(cmp) is not str:
                raise ProgramError("FORMAT")
            if sensor not in ("temperature", "light"):
                raise ProgramError("UNSUPPORTED")
            if cmp not in (">", "<", ">=", "<=") or type(threshold) is not int or not -100000 <= threshold <= 100000:
                raise ProgramError("FORMAT")
            validate(yes, depth+1, budget)
            validate(no, depth+1, budget)
        elif op == "reject":
            if node != ["reject", "UNSUPPORTED"]:
                raise ProgramError("FORMAT")
            raise ProgramError("UNSUPPORTED")
        else:
            raise ProgramError("FORMAT")


def execute(program, state):
    """Validate the entire program before collecting any actions (atomic rejection)."""
    result = {"actions": [], "readings": {}, "error": None}
    try:
        validate(program)
        if type(state) is not dict:
            raise ProgramError("STATE")
        for sensor, lo, hi in [("temperature", -40, 125), ("light", 0, 100000)]:
            value = state.get(sensor)
            if type(value) not in (int, float) or not lo <= value <= hi or not math.isfinite(value):
                raise ProgramError("STATE")

        def visit(nodes):
            for node in nodes:
                op = node[0]
                if op in ("led", "pwm"):
                    result["actions"].append(node.copy())
                elif op == "read":
                    result["readings"][node[1]] = state[node[1]]
                elif op == "if":
                    _, sensor, cmp, threshold, yes, no = node
                    x = state[sensor]
                    condition = {">": x > threshold, "<": x < threshold,
                                 ">=": x >= threshold, "<=": x <= threshold}[cmp]
                    visit(yes if condition else no)
        visit(program)
        if len(result["actions"]) > 8:
            raise ProgramError("FORMAT")
    except ProgramError as error:
        return {"actions": [], "readings": {}, "error": error.code}
    return result


def score(case, output, stop_reason):
    try:
        program = parse(output)
        actual = execute(program, case["state"])
    except ProgramError:
        program = None
        actual = {"actions": [], "readings": {}, "error": "FORMAT"}
    # Legal tasks additionally require the correct program, not just a lucky
    # branch outcome on this one state. Illegal tasks require the correct refusal.
    plan_match = program == case["program"]
    passed = actual == case["expected"] and stop_reason == "eos" and (not case["legal"] or plan_match)
    return {"pass": passed, "program_match": plan_match, "program": program, "actual": actual}
