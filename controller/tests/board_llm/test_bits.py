import sys
from pathlib import Path
import numpy as np
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts'))
from check_t25_board_bits import check


def fixture():
    gold=dict(logits=np.array([[-0.0,1.0]],dtype='<f4'),kv=np.zeros((24,2,1,1),dtype='<f4'))
    lines=['T25 STEP 00000001 00000001','T25 LOGITS','80000000 3f800000']
    for l in range(24):
        for v in range(2):lines += [f'T25 KV {l:08x} {v:08x} 00000001','00000000']
    return lines,gold


def test_signed_zero_encoding_is_checked_independently_of_numeric_equality():
    lines,gold=fixture();assert check(lines,gold)['bit_mismatches']==0
    lines[2]='00000000 3f800000'
    assert check(lines,gold)['bit_mismatches']==1


def test_incomplete_and_reordered_fp32_blocks_are_rejected():
    lines,gold=fixture()
    with pytest.raises((ValueError,StopIteration)):check(lines[:-1],gold)
    lines[3]='T25 KV 00000000 00000001 00000001'
    with pytest.raises(ValueError):check(lines,gold)
