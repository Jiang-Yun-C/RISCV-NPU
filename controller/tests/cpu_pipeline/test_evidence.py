#!/usr/bin/env python3
"""Reject deliberate corruption of actual profile artifacts, without target reruns."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from check_profile import validate


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("result", type=Path)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    if a.output.exists():
        p.error("refusing to overwrite test record")
    original = json.loads(a.result.read_text())
    validate(a.result)
    passed = ["actual unmodified profile validates"]
    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()
    def exercise(name, change, file_change=None):
        data = copy.deepcopy(original)
        with tempfile.TemporaryDirectory(prefix="t09-profile-negative-") as tmp:
            directory = Path(tmp)
            for item in data["trace_files"].values():
                shutil.copy2(a.result.parent / item["name"], directory / item["name"])
            change(data)
            if file_change:
                kind, edit = file_change
                path = directory / data["trace_files"][kind]["name"]
                path.write_text(edit(path.read_text()))
                # Keep the content hash consistent to test semantic checks as well.
                data["trace_files"][kind]["sha256"] = digest(path)
            path = directory / "case.json"
            path.write_text(json.dumps(data))
            try:
                validate(path)
            except ValueError:
                passed.append(name)
            else:
                raise AssertionError("corruption was accepted: " + name)
    def noop(data):
        pass
    exercise("changed current RTL identity rejected", lambda d:d.update(rtl_sha256="0"*64))
    exercise("changed retirement count rejected", lambda d:d["pipeline_profile"]["whole_program"].update(retired=1))
    exercise("wrong branch denominator rejected", lambda d:d["pipeline_profile"]["whole_program"].update(conditional_branches=1))
    exercise("incomplete capture rejected", lambda d:d["pipeline_profile"]["trace"].update(complete=False))
    exercise("trace hash mismatch rejected", lambda d:d["trace_files"]["csv"].update(sha256="0"*64))
    exercise("claimed formal build rejected", lambda d:d.update(uart=d["uart"].replace("CM_PORT version=1 formal=0", "CM_PORT version=1 formal=1")))
    exercise("trigger outside function rejected", lambda d:d["pipeline_profile"]["trace"].update(symbol_start=0,symbol_end_exclusive=1))
    def wrong_cycle(text):
        lines=text.splitlines();cells=lines[2].split(',');cells[0]=str(int(cells[0])+1);lines[2]=','.join(cells)
        return '\n'.join(lines)+'\n'
    exercise("CSV discontinuity rejected despite updated hash", noop, ("csv",wrong_cycle))
    def wrong_fire(text):
        lines=text.splitlines();cells=lines[1].split(',');cells[9]=str(int(cells[9])^16);lines[1]=','.join(cells)
        return '\n'.join(lines)+'\n'
    exercise("incorrect stage transfer rejected despite updated hash", noop, ("csv",wrong_fire))
    def wrong_vcd(text):
        lines=text.splitlines()
        for i,line in enumerate(lines):
            if line.startswith('b') and line.endswith(' s1'):
                value,key=line[1:].split();lines[i]='b'+value[:-1]+('0' if value[-1]=='1' else '1')+' '+key;break
        return '\n'.join(lines)+'\n'
    exercise("VCD/CSV mismatch rejected despite updated hash", noop, ("vcd",wrong_vcd))
    record={"status":"PASS","passed":len(passed),"checks":passed,
            "actual_result_file":a.result.name,"actual_result_sha256":digest(a.result),
            "checker_sha256":digest(Path(__file__).with_name("check_profile.py")),
            "test_sha256":digest(Path(__file__))}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps(record,indent=2))


if __name__ == "__main__":
    main()
