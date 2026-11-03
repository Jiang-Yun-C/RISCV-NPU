"""Independent tree boundaries and fixture integrity, without EDA tools."""
import numpy as np
from tests.opt12.fixture import tree,quantize

def test_group_roots_preserve_the_frozen_tree():
    rng=np.random.default_rng(20261019)
    for n in (1,3,63,64,65,127,128,129,896,4864):
        x=rng.normal(size=n).astype('f4');size=1<<(n-1).bit_length()
        padded=np.pad(x,(0,size-n))
        if n>64:
            roots=np.asarray([tree(padded[i:i+64]) for i in range(0,size,64)],dtype='f4')
            assert tree(roots).view('u4')==tree(x).view('u4')
        assert np.isfinite(tree(x))

def test_reordering_is_not_bitwise_equivalence():
    x=np.asarray([1e20,1,-1e20,1],dtype='f4')
    sequential=np.float32(0)
    for value in x:sequential=np.float32(sequential+value)
    assert sequential!=tree(x)

def test_quantization_half_integer_and_tail():
    x=np.asarray([127,-127,.5,1.5,2.5,-.5,-1.5,-2.5],dtype='f4')
    q,s=quantize(x)
    assert s==1 and q[:8].tolist()==[127,-127,0,2,2,0,-2,-2]
    assert not q[8:].any()


def test_numeric_failure_preserves_serializable_first_mismatch(tmp_path):
    import json,sys
    from pathlib import Path
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'cocotb'))
    from tests.opt12.checks import Checks
    c=Checks()
    try:c.equal(b'abc',b'aBc','numeric','golden')
    except AssertionError:pass
    else:raise AssertionError('bad golden was accepted')
    dest=tmp_path/'checks.json';c.save(dest)
    report=json.loads(dest.read_text())
    assert report['status']=='FAIL' and report['check_count']==1
    assert report['first_failure']['detail']['first_mismatch']==1
