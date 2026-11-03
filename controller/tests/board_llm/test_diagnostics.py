import subprocess
from pathlib import Path


def test_production_diagnostic_controls(tmp_path):
    root = Path(__file__).resolve().parents[2]
    binary = tmp_path / 'diagnostics'
    subprocess.run(['gcc', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                    '-Wno-unused-function', '-fno-strict-aliasing',
                    '-I', str(root/'firmware/runtime/board'),
                    '-I', str(root/'firmware/runtime/port'),
                    str(root/'tests/board_llm/diagnostics.c'), '-o', str(binary)], check=True)
    result = subprocess.run([str(binary)], check=True, capture_output=True, text=True)
    assert 'T25_DIAGNOSTICS_PASS' in result.stdout
