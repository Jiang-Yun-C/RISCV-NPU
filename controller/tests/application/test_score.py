import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from score import parse_response, score, summarize, wire_response


class ScoringTests(unittest.TestCase):
    def test_strict_invalid_outputs(self):
        for value in ["```json\n{}\n```", '{}', '{"actions":[],"actions":[],"readings":{},"error":null}',
                      '{"actions":[["led",true]],"readings":{},"error":null}',
                      '{"actions":[["pwm",101]],"readings":{},"error":null}',
                      '{"actions":[["servo",50]],"readings":{},"error":null}',
                      '{"actions":[["led",1]],"readings":{},"error":"RANGE"}',
                      '{"actions":[],"readings":{"temperature":NaN},"error":null}',
                      '{"actions":[],"readings":{"temperature":1e999},"error":null}',
                      '{"actions":[],"readings":{"humidity":20},"error":null}',
                      '[["led",true]]', '[["pwm",101]]', '[["pwm",12.5]]',
                      '[["temperature",1e999]]', '[["error","RANGE"],["led",1]]',
                      '[["light",10],["light",10]]', '[["servo",20]]', '[["humidity",10]]']:
            with self.subTest(value=value), self.assertRaises((ValueError, TypeError)):
                parse_response(value)

    def test_order_readout_and_eos(self):
        wanted = {"actions": [["led", 1], ["pwm", 20]], "readings": {"temperature": 26}, "error": None}
        case = {"expected": wanted}
        self.assertTrue(score(case, json.dumps(wire_response(wanted)), "eos")["pass"])
        self.assertFalse(score(case, json.dumps(wire_response(wanted)), "max_new_tokens")["pass"])
        for bad in [dict(wanted, actions=list(reversed(wanted["actions"]))),
                    dict(wanted, readings={"temperature": 25}), dict(wanted, actions=[["led", 1]])]:
            self.assertFalse(score(case, json.dumps(wire_response(bad)), "eos")["pass"])

    def test_explanation_delimiter_never_repairs_actions(self):
        case = {"expected": {"actions": [["led", 0]], "readings": {}, "error": None}}
        self.assertTrue(score(case, '温度低于阈值。\nRESULT=[["led",0]]', "eos")["pass"])
        self.assertFalse(score(case, '应该关灯。\nRESULT=[["led",1]]', "eos")["pass"])
        for text in ['RESULT=[["led",0]]\nextra', 'RESULT=[]\nRESULT=[["led",0]]',
                     '```\nRESULT=[["led",0]]\n```', '说明[["led",0]]']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_response(text)

    def test_dataset_labels_and_separation(self):
        here = Path(__file__).resolve().parent
        sets = {s: [json.loads(x) for x in (here / f"{s}.jsonl").read_text().splitlines()] for s in ["dev", "heldout"]}
        self.assertEqual([len(sets[s]) for s in sets], [50, 200])
        self.assertFalse({r["instruction"] for r in sets["dev"]} & {r["instruction"] for r in sets["heldout"]})
        self.assertFalse({r["family"] for r in sets["dev"]} & {r["family"] for r in sets["heldout"]})
        for split, rows in sets.items():
            self.assertEqual(len({r["id"] for r in rows}), len(rows))
            records = []
            for row in rows:
                self.assertEqual(parse_response(json.dumps(wire_response(row["expected"]))), row["expected"])
                self.assertEqual(row["legal"], row["expected"]["error"] is None)
                for sensor, value in row["expected"]["readings"].items():
                    self.assertEqual(row["state"][sensor], value)
                records.append({"id": row["id"], "output": json.dumps(wire_response(row["expected"])), "stop_reason": "eos"})
            summary = summarize(rows, records)
            self.assertEqual(summary["metrics"]["legal"]["rate"], 1)
            self.assertEqual(summary["sensor_pairs"]["total"], 5 if split == "dev" else 20)
            with self.assertRaises(ValueError):
                summarize(rows, records[:-1])


if __name__ == "__main__":
    unittest.main()
