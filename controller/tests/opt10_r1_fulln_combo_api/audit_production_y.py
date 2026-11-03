#!/usr/bin/env python3
"""Read an entire terminal v41 raw; bind actual Y bulk alignment to parent54 layout."""
import argparse,csv,hashlib,json,sys,traceback
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'scripts'))
from evidence import EvidenceRun,sha256,write_json

def main():
 p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);a=p.parse_args();r=EvidenceRun(ROOT,'OPT10_R1_W_SW_API',a.run_id);code=1
 try:
  old=ROOT/'evidence/OPT10_R1_FULLGRAPH/opt10-r1-fullgraph-v41-token0-20261020-v1';manifest=json.loads((old/'manifest.json').read_text());raw=old/'cocotb/seed1/transactions.csv'
  parent=ROOT/'evidence/OPT16_CANDIDATE/opt10-r1-candidate-20261020-v54';pm=json.loads((parent/'manifest.json').read_text());repo=Path(pm['candidate_repo']);reference=repo/'firmware/runtime/reference/nx_reference.c';backend=repo/'firmware/runtime/port/ce64_backend.c';app=ROOT/'variants/opt10_r1_fullgraph_v30_v1/fullgraph.c'
  inputs={str(f.relative_to(ROOT)):sha256(f) for f in (old/'manifest.json',reference,backend,app,Path(__file__))}
  r.check('terminal-original-fullgraph-receipt',manifest['status']=='PASS',manifest['candidate_id'])
  layout=dict(q=dict(base=0xac007000,N=896,calls=24,expected_512B_bursts=168),staged_KV=dict(base=0xba120000,N=128,calls=48,expected_512B_bursts=48),b_o_down=dict(base=0xac00e000,N=896,calls=48,expected_512B_bursts=336),gate=dict(base=0xac011800,N=4864,calls=24,expected_512B_bursts=912),up=dict(base=0xac024800,N=4864,calls=24,expected_512B_bursts=912),head=dict(base=0xac037800,N=151936,calls=1,expected_512B_bursts=1187))
  contract=dict(scope='READONLY_ACTUAL_V41_Y_512B_AW_ALIGNMENT_AND_EXACT54_DETERMINISTIC_WORKSPACE_NOT_NEW_PERFORMANCE',input_hashes=inputs,raw_sha256_expected=manifest['artifacts']['cocotb/seed1/transactions.csv'],geometry=dict(M=4,H=896,F=4864,V=151936,workspace=0xac000000),layout=layout,checks=['entire raw bytes hash equals original terminal manifest','every actual BA 512B burst has a unique listed role and 512B alignment','3563 role counts and zero 4KB crossings','workspace allocation source unchanged in exact54 dependency closure'],qualification=False,GO=False)
  write_json(r.path/'contract.json',contract);digest=hashlib.sha256();records=bytes_=all_aw=wide=0;align=Counter();classes=Counter();cross=0;previous=-1
  with raw.open('rb') as stream:
   for line in stream:
    digest.update(line);records+=1;bytes_+=len(line)
    if b',BA,' not in line:continue
    row=next(csv.reader([line.decode('ascii')]));cycle=int(row[0]);address,length,size=[int(v,16) for v in row[2:5]];all_aw+=1
    r.check('ordered-AW-'+str(all_aw),cycle>=previous,'monotonic accepted BA cycles') if False else None
    if cycle<previous:raise ValueError('nonmonotonic actual AW')
    previous=cycle
    if length!=31 or size!=4:continue
    wide+=1;align[address%512]+=1;cross+=int((address&4095)+512>4096)
    owners=[name for name,v in layout.items() if v['base']<=address<v['base']+v['N']*4]
    if len(owners)!=1:raise ValueError('unclassified or overlapping actual Y512 burst '+hex(address))
    classes[owners[0]]+=1
  r.check('entire-raw-original-hash',digest.hexdigest()==contract['raw_sha256_expected'],dict(sha256=digest.hexdigest(),records=records,bytes=bytes_));r.check('all-actual-Y-bulk-addresses-aligned',dict(align)=={0:3563} and cross==0,dict(align=align,cross_4KB=cross))
  r.check('all-169-role-counts',{name:classes[name] for name in layout}=={name:v['expected_512B_bursts'] for name,v in layout.items()},dict(classes))
  text=reference.read_text();r.check('exact54-static-workspace-code','float *p=work;s->x=p;p+=M*H;s->z=p;p+=M*H;s->q=p;p+=M*H;s->a=p;p+=M*H;s->b=p;p+=M*H;' in text and 's->gate=p;p+=M*F;s->up=p;p+=M*F;s->logits=p;return s;' in text and '(void *)0xac000000,835072' in app.read_text(),inputs[str(reference.relative_to(ROOT))])
  write_json(r.path/'results.json',dict(scope=contract['scope'],entire_raw_checked=True,raw_sha256=digest.hexdigest(),raw_bytes=bytes_,raw_records=records,all_backend_AW=all_aw,actual_512B_bulks=wide,mod512_histogram=dict(align),cross_4KB=0,roles={name:dict(v,actual_512B_bursts=classes[name]) for name,v in layout.items()},new_candidate_performance_inherited=False,GO=False))
  r.check('source-inputs-after',all(sha256(ROOT/n)==h for n,h in inputs.items()),len(inputs));code=0
 except BaseException:(r.path/'failure.txt').write_text(traceback.format_exc());print(traceback.format_exc(),flush=True)
 finally:
  for f in (Path(__file__),):out=r.path/f.name;out.write_bytes(f.read_bytes())
  code=r.finish(code)
 print(r.manifest['status'],r.path,flush=True);return code
if __name__=='__main__':raise SystemExit(main())
