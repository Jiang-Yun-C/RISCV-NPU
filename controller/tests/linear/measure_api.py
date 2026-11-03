"""Measured host API validation/quantization/reference cost; never RTL cycles."""
import argparse,json,sys
from pathlib import Path
import numpy as np
from test_api import API,ROOT
def measure(vectors,out):
    API.setUpClass();api=API();rows=[]
    try:
        for family in ('q','down','head'):
            for m in (1,4,8):
                # Head M1 is full CPU API; batched head measurement is bounded
                # to 128 physical rows and explicitly labeled in the result.
                folder=Path(vectors)/f'{family}-m{m}';wf=Path(vectors)/'weights'/family
                x=np.load(folder/'x.npy',allow_pickle=False);w=np.load(wf/'q.npy',allow_pickle=False);sw=np.load(wf/'scale.npy',allow_pickle=False)
                if family=='head' and m>1:w=w[:128].copy();sw=sw[:128].copy()
                bp=wf/'bias.npy';bias=np.load(bp,allow_pickle=False) if bp.exists() else None
                status,y,aq,sa,stats=api.run_api((x,w,sw,bias));assert status==0,status
                n=w.shape[0];ref=np.load(folder/'y.npy',allow_pickle=False)[:,:n];assert np.array_equal(y,ref),'CPU API output'
                assert np.array_equal(aq,np.load(folder/'aq.npy',allow_pickle=False)) and np.array_equal(sa,np.load(folder/'sa.npy',allow_pickle=False)),'CPU API quantization'
                rows.append(dict(family=family,m=m,n=n,k=w.shape[1],ticks_unit='host CLOCK_MONOTONIC ns',stats={k:getattr(stats,k) for k,_ in stats._fields_},all_output_elements_compared=m*n))
        result=dict(status='PASS',qualification='DESKTOP_CPU_API_COST_ONLY',cases=rows)
        Path(out).write_text(json.dumps(result,indent=2)+'\n');return result
    finally:API.tearDownClass()
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('vectors');p.add_argument('output');a=p.parse_args();measure(a.vectors,a.output)
