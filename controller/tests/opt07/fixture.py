"""Inputs and independent double-exp golden, written before any CPU run."""
import json
from pathlib import Path
import numpy as np
from tests.opt07.host import samples,independent
from scripts.evidence import write_json,sha256

def generate(dest,long=False,mode=None):
    dest=Path(dest);dest.mkdir(parents=True)
    data=list(samples())
    if long:
        _,g,u=next(x for x in data if x[0]=='T11-layer0')
    else:
        g=np.concatenate([data[0][1],data[1][1][:20],data[9][1][:20]])
        u=np.concatenate([data[0][2],data[1][2][:20],data[9][2][:20]])
    rows=[]
    for name,x in [('gate',g),('up',u)]:
        rows.append('static const uint32_t input_'+name+'[] = {'+','.join('0x%08xu'%int(v) for v in x.view('u4'))+'};')
    (dest/'inputs.h').write_text('#define INPUT_N %d\n#define LONG_RUN %d\n#define ONLY_MODE %d\n'%(len(g),long,-1 if mode is None else mode)+'\n'.join(rows)+'\n')
    golden=dict(schema_version=1,case_id='width4864' if long else 'edges65',group_size=64,layout_id='NOT_APPLICABLE_CPU_CONTIGUOUS',
        dtype='<f4',shape=[len(g)],stride_bytes=[4],logical_view='SwiGLU gate/up',gate_bits=g.view('u4').tolist(),up_bits=u.view('u4').tolist(),
        expected_bits=independent(g,u).view('u4').tolist(),thresholds='configs/t05-thresholds.json',generator='tests/opt07/fixture.py',
        golden_provenance='Independent NumPy binary64 exp rounded to FP32; FP32 sign branch, (gate*sigmoid)*up',
        expected_nonfinite_status=-2,seed=20261019,only_mode=mode)
    write_json(dest/'golden.json',golden)
    write_json(dest/'manifest.json',dict(inputs_sha256=sha256(dest/'inputs.h'),golden_sha256=sha256(dest/'golden.json'),**{k:v for k,v in golden.items() if k not in ('gate_bits','up_bits','expected_bits')}))
    return dest
