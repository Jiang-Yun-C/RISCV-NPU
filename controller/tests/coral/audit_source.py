#!/usr/bin/env python3
"""Inspect the locked BUILD/flags AST without executing upstream Starlark.

This is source evidence, never a substitute for elaboration or execution.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import subprocess


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def literal(node, names):
    if isinstance(node, ast.Name):
        return names[node.id]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return literal(node.left, names) + literal(node.right, names)
    if isinstance(node, ast.Dict):
        return {literal(k, names): literal(v, names) for k, v in zip(node.keys, node.values)}
    if isinstance(node, ast.List):
        return [literal(v, names) for v in node.elts]
    return ast.literal_eval(node)


def audit(repo):
    names = {}
    flags_path = repo / 'hdl/chisel/src/coralnpu/flags.bzl'
    for statement in ast.parse(flags_path.read_text()).body:
        if isinstance(statement, ast.Assign):
            names[statement.targets[0].id] = literal(statement.value, names)
    build_path = repo / 'hdl/chisel/src/coralnpu/BUILD'
    targets = {}
    wanted = ('core_mini_axi_cc_library', 'rvv_core_mini_axi_cc_library',
              'vme_core_mini_axi_cc_library')
    for node in ast.walk(ast.parse(build_path.read_text())):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'template_rule':
            if isinstance(node.args[0], ast.Name) and node.args[0].id == 'chisel_cc_library':
                for name, value in literal(node.args[1], names).items():
                    if name in wanted:
                        targets[name] = dict(value, build_line=node.lineno,
                            target='//hdl/chisel/src/coralnpu:' + name + '_emit_verilog')
    if set(targets) != set(wanted):
        raise ValueError('missing scalar/RVV/VME target definitions')
    scalar, rvv, vme = [targets[k]['gen_flags'] for k in wanted]
    if '--enableRvv=True' in scalar or '--enableRvv=True' not in rvv:
        raise ValueError('unexpected scalar/RVV selection')
    if '--enableVme=True' in rvv or '--enableVme=True' not in vme:
        raise ValueError('unexpected VME selection')
    paths = ['.bazelversion', '.bazelrc', 'MODULE.bazel', 'MODULE.bazel.lock',
        'hdl/chisel/src/coralnpu/BUILD', 'hdl/chisel/src/coralnpu/flags.bzl',
        'hdl/chisel/src/coralnpu/Parameters.scala', 'hdl/chisel/src/coralnpu/Core.scala',
        'hdl/chisel/src/coralnpu/CoreAxi.scala', 'hdl/chisel/src/coralnpu/CoreAxiCSR.scala',
        'hdl/chisel/src/coralnpu/rvv/RvvCore.scala',
        'hdl/verilog/rvv/design/rvv_backend.sv', 'hdl/verilog/rvv/design/Zvt/zvt.sv',
        'hdl/verilog/rvv/design/Zvt/zvt_pe_array.sv', 'hdl/verilog/Sram.v',
        'hdl/verilog/ClockGate.sv', 'hdl/verilog/RstSync.sv', 'rules/repo_defs.bzl',
        'rules/chisel.bzl', 'toolchain/cc_toolchain_config.bzl',
        'examples/hello_world_add_floats.cc', 'examples/rvv_add_intrinsic.cc']
    return {
        'schema_version': 1, 'qualification': 'SOURCE_INSPECTION_ONLY',
        'commit': subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip(),
        'bazel_version': (repo / '.bazelversion').read_text().strip(),
        'targets': targets,
        'selected_target': targets[wanted[1]]['target'],
        'matrix_unit': {'source_present': True, 'source': paths[12:14],
                        'enabled_in_selected_target': False, 'execution': 'NOT_RUN'},
        'files': {p: digest(repo / p) for p in paths},
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('repo', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    result = audit(args.repo)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'status': 'PASS', 'qualification': result['qualification'],
                      'commit': result['commit'], 'selected_target': result['selected_target']}))
