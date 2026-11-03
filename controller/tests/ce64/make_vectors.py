"""Build E0 stimuli from immutable T16 payloads and independent edge cases."""
import json
from pathlib import Path
import random
import sys
import numpy as np
from reference import bits, number, mul, add, restore, finite
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
from evidence import sha256,write_json

def make(dest):
    dest=Path(dest);dest.mkdir(parents=True,exist_ok=True)
    base=ROOT/'evidence/T16/acceptance-20261007-v3/artifacts/images/control'
    fixture=json.loads((base/'fixture.json').read_text());golden=json.loads((base/'golden.json').read_text())
    identity=json.loads((ROOT/'exports/T24_PRO_REVIEW/architecture-review-20261013-v2/reports/t16-image-identities.json').read_text())['control']
    assert sha256(base/'fixture.json')==identity['parent_fixture_sha256']
    assert sha256(base/'golden.json')==identity['parent_golden_sha256']
    payloads={}
    for r in fixture['regions']:
        path=Path(r['path']);assert sha256(path)==r['sha256'];payloads.setdefault(r['address'],[]).append(path)
    def payload(address,size):
        matches=[p for p in payloads[address] if p.stat().st_size==size]
        assert matches,(hex(address),size)
        assert len({sha256(p) for p in matches})==1,'ambiguous payload'
        return matches[0]
    parents={'fixture':sha256(base/'fixture.json'),'golden':sha256(base/'golden.json'),
             'threshold':sha256(ROOT/'configs/t05-thresholds.json'),'ELF':fixture['elf_sha256'],
             'numeric_contract':sha256(ROOT/'docs/spec/numeric-v1.md'),'expected_payloads':{}}
    groups=[];fvec=[];oracle_checks=0;golden_outputs=0
    for c in golden['jobs']:
        if c['status'] or c['mode'] or 'expected_path' not in c: continue
        path=Path(c['expected_path']);assert sha256(path)==c['expected_sha256']
        parents['expected_payloads'][str(path)]=c['expected_sha256']
        data=np.load(path);aq=data['aq'];sa=data['sa'];m,k=aq.shape;n=c['job']['wq']['shape'][0];g=(k+63)//64
        wq=np.fromfile(payload(c['job']['wq']['address'],n*k),dtype=np.int8).reshape(n,k)
        sw=np.fromfile(payload(c['job']['sw']['address'],n*g*4),dtype='<f4').reshape(n,g)
        bias=np.fromfile(payload(c['job']['bias']['address'],n*4),dtype='<f4') if c['job']['bias'].get('address',0) else None
        for row in range(n):
            for token in range(m):
                acc=0
                for group in range(g):
                    a=aq[token,64*group:64*(group+1)].astype('i1').tolist();w=wq[row,64*group:64*(group+1)].tolist()
                    dot=sum(int(x)*int(y) for x,y in zip(a,w));sb=bits(sa[token,group]);wb=bits(sw[row,group])
                    expected=restore(dot,sb,wb,acc)
                    assert expected[3]==0
                    groups.append((a,w,sb,wb,acc,dot,*expected))
                    fvec.append((dot,sb,wb,acc,0,*expected))
                    acc=expected[2]
                if bias is not None: acc=add(acc,bits(bias[row]))[0]
                target=bits(data['y'][token,row])
                threshold=golden['thresholds']
                # Preserve the actual frozen threshold; E0 normally also matches bits.
                assert np.isclose(number(acc),number(target),rtol=threshold['rtol'],atol=threshold['atol']),c['name']
                golden_outputs+=1
    rng=random.Random(0xce641)
    scales=[0,0x00800000,0x00800001,0x00800002,0x3eaaaaab,0x3f000000,0x3f800000,0x3f800001,0x40000000,0x7f7fffff,
            0x80000000,1,0x007fffff,0xbf800000,0x7f800000,0xff800000,0x7fc00000,0x7f800001]
    for i in range(5000):
        dot=rng.randint(-1032256,1032256)
        if i<1000: dot=[0,1,-1,3,-3,1032256,-1032256][i%7]
        sb=rng.choice(scales) if i<2000 else rng.randrange(1,255)<<23|rng.getrandbits(23)
        wb=rng.choice(scales) if i<2000 else rng.randrange(1,255)<<23|rng.getrandbits(23)
        acc=rng.getrandbits(32) if i%3 else [0,0x80000000,1,0x807fffff,0x3f800000,0xbf800000,0x7f7fffff][i%7]
        initial=6 if i%71==0 else 0
        expected=restore(dot,sb,wb,acc,initial);fvec.append((dot,sb,wb,acc,initial,*expected))
    for i in range(1500):
        count=(i%64)+1;a=[rng.randint(-127,127) for _ in range(count)];w=[rng.randint(-127,127) for _ in range(count)]
        sb=0x3eaaaaab;wb=0x3f800001;initial=0
        if i%29==0: a[0]=-128;initial=7
        elif i%31==0: sb=0;initial=8
        elif i%37==0: sb=0x80000000;initial=1
        elif i%41==0: wb=0x7f800000;initial=1
        dot=sum(x*y for x,y in zip(a,w));acc=0x80000000 if i%3==0 else bits(-0.25)
        expected=restore(dot,sb,wb,acc,initial)
        groups.append((a,w,sb,wb,acc,dot,*expected))
    # Independent numpy cross-check of each separate operation, including NaN
    # canonicalization. Only the oracle creates expectations; DUT never enters it.
    with np.errstate(all='ignore'):
        for dot,sb,wb,acc,initial,p,v,y,status,flags in fvec:
            np_p=bits(np.float32(np.float32(dot)*np.float32(number(sb))))
            np_v=bits(np.float32(np.float32(number(p))*np.float32(number(wb))))
            np_y=bits(np.float32(np.float32(number(acc))+np.float32(number(v))))
            for exact,numpy in [(p,np_p),(v,np_v),(y,np_y)]:
                assert exact==numpy or (not finite(exact) and exact&0x7fffff and not finite(numpy) and numpy&0x7fffff),(hex(exact),hex(numpy))
                oracle_checks+=1
    def packed(seq):
        return int.from_bytes(bytes(x&255 for x in seq)+b'\x80'*(64-len(seq)),'little')
    (dest/'groups.txt').write_text(''.join('%d %0128x %0128x %08x %08x %08x %08x %08x %08x %08x %x %02x\n'%
        (len(a),packed(a),packed(w),sb,wb,acc,dot&0xffffffff,p,v,y,status,flags)
        for a,w,sb,wb,acc,dot,p,v,y,status,flags in groups))
    (dest/'restore.txt').write_text(''.join(' '.join(f'{x&0xffffffff:08x}' for x in row)+'\n' for row in fvec))
    result={'groups':len(groups),'restore':len(fvec),'frozen_output_elements':golden_outputs,
            'oracle_numpy_checks':oracle_checks,'parents':parents,'scope':'E0 arithmetic modules, not a new T16 route'}
    write_json(dest/'vectors.json',result);return result

if __name__=='__main__': print(json.dumps(make(sys.argv[1]),indent=2))
