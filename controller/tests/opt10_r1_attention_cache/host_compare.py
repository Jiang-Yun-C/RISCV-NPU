"""Immutable old/new C and independent GQA oracle over causal boundaries."""
import argparse,ctypes as C,json,sys,xml.etree.ElementTree as ET
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2];sys.path[:0]=[str(ROOT)]
from model_tools.numeric_v1 import attention

def main():
    p=argparse.ArgumentParser();p.add_argument('--old',required=True);p.add_argument('--new',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();a.output.mkdir()
    libs=[C.CDLL(x) for x in [a.old,a.new]]
    for lib in libs:lib.attention_probe.argtypes=[C.c_void_p]*4+[C.c_int,C.c_int];lib.attention_probe.restype=C.c_int
    thresholds=json.loads((ROOT/'configs/t05-thresholds.json').read_text())['operators']['attention']
    suite=ET.Element('testsuite',name='actual_C_attention_cache');results=[];elements=0
    for seed in [1,7,19,20261020]:
      rng=np.random.default_rng(seed)
      for total in [1,2,3,63,64,65,127,128,129,255,256,257,511,512,513,640]:
       for rows in [1,4]:
        if rows>total:continue
        for kind in ['normal','large','zero']:
         scale=8 if kind=='large' else 1
         q=rng.normal(size=(rows,14,64)).astype('<f4')*np.float32(scale);k=rng.normal(size=(640,2,64)).astype('<f4')*np.float32(scale);v=rng.normal(size=(640,2,64)).astype('<f4')
         if kind=='zero':q.fill(0);k.fill(0);v[::2]*=np.float32(-1)
         # Future poison must never be consumed by any causal row.
         k[total:]=np.nan;v[total:]=np.nan
         outputs=[];codes=[]
         for lib in libs:
          out=np.full((rows,896),np.nan,dtype='<f4');codes.append(lib.attention_probe(q.ctypes.data,k.ctypes.data,v.ctypes.data,out.ctypes.data,rows,total-rows));outputs.append(out)
         label=f's{seed}-len{total}-m{rows}-{kind}'
         if codes!=[0,0] or not np.array_equal(outputs[0].view('u4'),outputs[1].view('u4')):raise AssertionError((label,'old/new C bitwise mismatch',codes))
         gold,_=attention(q,k[:total],v[:total],total-rows);err=np.abs(outputs[1].astype('f8')-gold.astype('f8'));nrmse=float(np.sqrt(np.mean(err**2))/max(np.sqrt(np.mean(gold.astype('f8')**2)),1e-12))
         if not np.all(np.isfinite(outputs[1])) or not np.all(err<=thresholds['atol']+thresholds['rtol']*np.abs(gold.astype('f8'))) or nrmse>thresholds['nrmse']:raise AssertionError((label,'original independent attention thresholds',float(err.max()),nrmse))
         elements+=outputs[0].size;results.append(dict(case=label,max_abs=float(err.max()),nrmse=nrmse,old_new_exact=True));ET.SubElement(suite,'testcase',name=label)
    # Failed numerical results have no value contract; status must still match.
    for kind in ['nan-Q','infinite-K','finite-overflow']:
     q=np.ones((1,14,64),dtype='<f4');k=np.ones((640,2,64),dtype='<f4');v=np.ones_like(k)
     if kind=='nan-Q':q[0,0,0]=np.nan
     elif kind=='infinite-K':k[0,0,0]=np.inf
     else:q.fill(np.finfo('f4').max);k.fill(np.finfo('f4').max)
     codes=[]
     for lib in libs:
      out=np.zeros((1,896),dtype='<f4');codes.append(lib.attention_probe(q.ctypes.data,k.ctypes.data,v.ctypes.data,out.ctypes.data,1,127))
     if codes[0]!=codes[1] or codes[0]==0:raise AssertionError((kind,'numerical error not preserved',codes))
     ET.SubElement(suite,'testcase',name=kind)
    suite.set('tests',str(len(suite)));ET.ElementTree(suite).write(a.output/'results.xml',encoding='utf-8',xml_declaration=True)
    (a.output/'results.json').write_text(json.dumps(dict(cases=len(suite),exact_old_new_elements=elements,results=results,scope='HOST_COMPLETE_ATTENTION_OPERATOR_NOT_MODEL_OR_RTL_CYCLES'),indent=2)+'\n')
if __name__=='__main__':main()
