"""Independent integer/NumPy FP32 oracle for the host C fallback probe."""
import argparse
import json
from pathlib import Path
import struct
import numpy as np


def generate(directory):
    directory = Path(directory)
    data = bytearray()
    cases = []
    for seed in (1, 7, 19):
        rng = np.random.default_rng(seed)
        for m, n, k in ((1,8,896),(4,8,896),(1,8,4864),(4,8,4864),(4,3,65)):
            g = (k+63)//64
            a = rng.integers(-127,128,(m,k),dtype=np.int16).astype('i1')
            w = rng.integers(-127,128,(n,k),dtype=np.int16).astype('i1')
            sa = rng.uniform(.001,.025,(m,g)).astype('<f4')
            sw = rng.uniform(.002,.05,(n,g)).astype('<f4')
            bias = rng.uniform(-.5,.5,n).astype('<f4')
            if seed == 1:
                a[0,:64] = 0; sa[0,0] = 0
                w[0,-min(k,64):] = 127
            cases.append(dict(seed=seed,m=m,n=n,k=k,groups=g))
            data += struct.pack('<III',m,n,k)
            for x in (a,w,sa,sw,bias): data += x.tobytes()
    (directory/'fixture.bin').write_bytes(struct.pack('<I',len(cases))+data)
    (directory/'fixture.json').write_text(json.dumps(dict(cases=cases,
        scope='SYNTHETIC_VALID_T05_INTEGER_SCALE_INPUTS_NOT_FULL_MODEL_OR_RTL'),indent=2)+'\n')


def check(directory, output=None):
    directory = Path(directory)
    blob = memoryview((directory/'fixture.bin').read_bytes())
    count, = struct.unpack_from('<I',blob); offset = 4
    expected = {}
    for t in range(count):
        m,n,k = struct.unpack_from('<III',blob,offset);offset += 12
        g = (k+63)//64
        vals=[]
        for dtype,shape in [('i1',(m,k)),('i1',(n,k)),('<f4',(m,g)),('<f4',(n,g)),('<f4',(n,))]:
            size=int(np.prod(shape))*np.dtype(dtype).itemsize
            vals.append(np.frombuffer(blob[offset:offset+size],dtype=dtype).reshape(shape));offset+=size
        a,w,sa,sw,bias=vals
        y=np.zeros((m,n),dtype=np.float32)
        for h in range(g):
            # Independent 64-bit matrix product, not the C scalar loop.
            dots=a[:,64*h:64*(h+1)].astype(np.int64) @ w[:,64*h:64*(h+1)].astype(np.int64).T
            v=(dots.astype(np.float32)*sa[:,h,None]).astype(np.float32)
            v=(v*sw[None,:,h]).astype(np.float32)
            y=(y+v).astype(np.float32)
            for i in range(m):
                for j in range(n):expected[('D',t,i,j,h)]=int(dots[i,j])
        y=(y+bias[None,:]).astype(np.float32).view(np.uint32)
        for i in range(m):
            for j in range(n):expected[('Y',t,i,j)]=int(y[i,j])
    if offset!=len(blob) or count!=15:raise ValueError('fixture inventory/trailing bytes')
    lines=Path(output or directory/'probe.stdout.log').read_text().splitlines()
    if lines[:2] != ['SCALE 0 0.25','OPERAND 0004001000001234 00001234']:
        raise ValueError('upstream scale / RV32 operand witness')
    observed={}
    for line in lines[2:]:
        parts=line.split();tag=parts[0]
        if tag not in ('D','Y'):raise ValueError('unknown numeric record')
        key=(tag,*(int(x) for x in parts[1:-1]))
        if key in observed:raise ValueError('duplicate numeric record')
        observed[key]=int(parts[-1],16 if tag=='Y' else 10)
    if observed != expected:raise ValueError('independent G64 numeric mismatch or missing records')
    # Independent per-tensor counterexample: identical full-K INT32 sum zero,
    # differing per-group scales, so no single scaling of that sum can work.
    dots=np.array([64,-64],dtype=np.float32)
    y=np.float32(np.float32(dots[0]*np.float32(.5))*np.float32(.25))
    y=np.float32(y+np.float32(np.float32(dots[1]*np.float32(.25))*np.float32(1)))
    if int(dots.sum())!=0 or float(y)!=-8:raise ValueError('groupwise witness')
    return dict(status='PASS',cases=count,checks=len(expected)+3,
        exact_integer_and_fp32_matches=len(expected),upstream_small_output=.0,t05_float_output=.25,
        per_tensor_counterexample=dict(group_dots=[64,-64],sa=[.5,.25],sw=[.25,1],full_k_dot=0,t05_result=-8),
        scope='HOST_C_FALLBACK_AND_UPSTREAM_C_SCALE_MACRO_ONLY_NO_RTL_NO_TIMING')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['generate','check']);p.add_argument('directory',type=Path)
    a=p.parse_args()
    if a.mode=='generate':generate(a.directory)
    else:print(json.dumps(check(a.directory),indent=2))
