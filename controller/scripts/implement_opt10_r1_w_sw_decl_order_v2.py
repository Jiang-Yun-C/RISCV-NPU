#!/usr/bin/env python3
"""Preserve frozen v1; make only the VCS-required declaration ordering fix."""
import json,shutil,difflib,sys
from pathlib import Path
R=Path(__file__).resolve().parents[1];sys.path.insert(0,str(R/'scripts'))
from evidence import sha256,write_json,content_id
v1=R/'variants/opt10_r1_w_sw_integrated_v1';v2=R/'variants/opt10_r1_w_sw_integrated_v2'
i=json.loads((v1/'identity.json').read_text())
assert all(sha256(v1/n)==h for n,h in i['overlay'].items())
assert not v2.exists();shutil.copytree(v1,v2)
f=v2/'rtl/ce64/nx_ce64_control.sv';s=f.read_text()
assert s.count('  logic stream_active;')==1
s=s.replace('  logic stream_active;\n','')
assert s.count('  wire next_sw_read=')==1
s=s.replace('  wire next_sw_read=','  logic stream_active;\n  wire counter_clear;\n  wire next_sw_read=')
assert s.count('  wire counter_clear=')==1
s=s.replace('  wire counter_clear=','  assign counter_clear=');f.write_text(s)
repo=R/'build/OPT16_CANDIDATE/opt10-r1-candidate-20261020-v54/repo'
for f in(v2/'rtl').rglob('*.sv'):
 n=str(f.relative_to(v2));old=(repo/n).read_text()if(repo/n).exists()else''
 (v2/(f.name+'.patch')).write_text(''.join(difflib.unified_diff(old.splitlines(True),f.read_text().splitlines(True),fromfile='exact54/'+n,tofile='stream-v2/'+n)))
c=json.loads((v2/'contract.json').read_text());c['revision']={'parent_experimental_content_id':i['experimental_content_id'],'reason':'v1 retained FAIL at VCS parsing; move stream_active and counter_clear declarations before use; no cycle/architecture/threshold change'};write_json(v2/'contract.json',c)
j=dict(i);j.pop('experimental_content_id');j['overlay']={str(f.relative_to(v2)):sha256(f)for f in(v2/'rtl').rglob('*.sv')};j['architecture_contract_sha256']=sha256(v2/'contract.json');j['generator_sha256']=sha256(__file__);j['supersedes_experiment']=i['experimental_content_id'];j['experimental_content_id']=content_id(j);write_json(v2/'identity.json',j)
shutil.copy2(__file__,v2/'implementation.py')
print(j['experimental_content_id'],sha256(v2/'rtl/ce64/nx_ce64_control.sv'))
