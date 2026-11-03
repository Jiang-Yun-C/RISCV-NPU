#!/usr/bin/env python3
"""Frozen exact54 registered guard A/B: protocol + actual native capture chain."""
import argparse,csv,json,re,shutil,sys,traceback
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from evidence import EvidenceRun,sha256,write_json,content_id

def protocol_result(path,text,refill):
    m=re.search(r'GUARD_PROTOCOL_PASS refill=(\d+) cases=(\d+) checks=(\d+) cycles=(\d+)',text)
    assert m and 'Fatal:' not in text and int(m[1])==refill
    rows=list(csv.reader(path.open()))
    return dict(cases=int(m[2]),checks=int(m[3]),cycles=int(m[4]),done=[x for x in rows if x[1]=='DONE'])

def chain_result(path,text):
    m=re.search(r'LINEAR_STREAM_CAPTURE_PASS enable=(\d+) cases=(\d+) checks=(\d+) cycles=(\d+) overlap=(\d+) AR=(\d+) R=(\d+) NAR=(\d+) NR=(\d+) SCR=(\d+)',text)
    assert m and 'Fatal:' not in text and int(m[1])==1
    rows=list(csv.reader(path.open()))
    cases=[dict(case=int(x[2]),component_cycles=int(x[3]),AR=int(x[4]),R=int(x[5]),native_AR=int(x[6]),native_R=int(x[7]),scratch_operations=int(x[8]),peeks=int(x[9]))for x in rows if x[1]=='DONE']
    stream=[x[2]for x in rows if x[1]=='BEGIN' and x[3]=='3'];assert len(stream)==1
    cmds=[int(x[0])for x in rows if x[1]=='CMD' and x[2]==stream[0]]
    return dict(cases=cases,total=dict(cases=int(m[2]),checks=int(m[3]),cycles=int(m[4]),peeks_while_native_pending=int(m[5]),AR=int(m[6]),R=int(m[7]),native_AR=int(m[8]),native_R=int(m[9]),scratch_operations=int(m[10])),stream_CMD=cmds,stream_intervals=[b-a for a,b in zip(cmds,cmds[1:])],CPU_API_cycles=None,frequency_signoff_hz=None,GO=False)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--run-id',required=True);a=ap.parse_args()
    r=EvidenceRun(ROOT,'OPT10_R1_GUARD_AB',a.run_id);code=1
    variant=ROOT/'variants/opt10_r1_guard_refill_v1'
    try:
        contract=json.loads((variant/'contract.json').read_text());identity=json.loads((variant/'identity.json').read_text())
        parent=ROOT/contract['parent'];pm=json.loads((parent/'manifest.json').read_text());repo=Path(pm['candidate_repo']);inv=json.loads((parent/'candidate-sources.json').read_text())
        r.check('exact54-parent',all(sha256(repo/n)==h for n,h in inv.items()),pm['candidate_id'])
        r.check('frozen-overlay',all(sha256(variant/n)==h for n,h in identity['overlay'].items()),identity)
        r.check('root-Makefile-frozen',sha256(ROOT/'Makefile')==contract['root_Makefile_sha256'],contract['root_Makefile_sha256'])
        for name in ('contract.json','identity.json','guard.patch'):
            shutil.copy2(variant/name,r.path/name)
        shutil.copy2(__file__,r.path/Path(__file__).name)
        actual=dict(parent_candidate_id=pm['candidate_id'],parent_manifest_sha256=sha256(parent/'candidate-sources.json'),overlay=identity['overlay'],runner_sha256=sha256(__file__),qualification=False)
        write_json(r.path/'experimental-identity.json',dict(**actual,experimental_content_id=content_id(actual)))
        r.manifest.update(candidate_id=pm['candidate_id'],qualification=False,GO=False,board_execution=False,scope='REGISTERED_GUARD_A_B_PROTOCOL_AND_NATIVE_COMPONENT_NOT_CPU_API_OR_SIGNOFF');r.flush()
        vcs=json.loads((ROOT/'docs/spec/toolchain-lock.json').read_text())['tools']['vcs']['path']
        results={}
        for mode in ('baseline','refill'):
            for kind in ('protocol','chain'):
                name=mode+'-'+kind;build=r.build/name;build.mkdir();out=r.path/name;out.mkdir();src=build/'sources';src.mkdir()
                names=['rtl/soc/nx_accel_map.sv','rtl/interfaces/axi4_if.sv']
                if kind=='chain':names+=['rtl/ce64/nx_ce64_math_pkg.sv','rtl/ce64/nx_ce64_dma.sv','rtl/ce64/nx_ce64_scratch.sv']
                names+=['rtl/ce64/common/nx_ce64_guard.sv']
                if kind=='chain':names+=['rtl/ce64/common/nx_ce64_ddr_adapter.sv']
                compiled=[]
                for n in names:
                    source=repo/n
                    if n=='rtl/ce64/common/nx_ce64_guard.sv'and mode=='refill':source=variant/n
                    if n=='rtl/ce64/nx_ce64_dma.sv':source=ROOT/'evidence/OPT10_R1_LINEAR_STREAM_CAPTURE/opt10-r1-linear-stream-native-capture-20261021-v5/sources'/n
                    target=src/n;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target);compiled.append(target)
                tb=src/'tb.sv';shutil.copy2(variant/(kind+'_tb.sv'),tb);compiled.append(tb)
                hashes={str(f.relative_to(src)):sha256(f)for f in compiled};write_json(out/'input-hashes.json',hashes)
                shutil.copytree(src,out/'sources')
                top='tb_guard_refill'if kind=='protocol'else'tb_linear_stream'
                params=['-pvalue+tb_guard_refill.REFILL='+str(int(mode=='refill'))]if kind=='protocol'else[]
                sim=build/'simv'
                r.execute(name+'-compile',[vcs,'-full64','-sverilog','-timescale=1ns/1ps',*compiled,'-top',top,*params,'-o',sim],contract['limits']['compile_wall_seconds'],cwd=build)
                log=r.execute(name+'-simulate',[sim,'-no_save'],contract['limits']['simulation_wall_seconds'],cwd=build).read_text()
                raw='protocol.csv'if kind=='protocol'else'ledger.csv';shutil.copy2(build/raw,out/raw)
                result=protocol_result(out/raw,log,int(mode=='refill'))if kind=='protocol'else chain_result(out/raw,log)
                write_json(out/'results.json',result);results[name]=result
                r.check(name+'-source-stable',all(sha256(src/n)==h for n,h in hashes.items()),hashes)
        # Same work; native fault and revoke cases preserved. Cadence is measured,
        # never obtained by subtracting a component estimate from CPU cycles.
        b=results['baseline-chain'];e=results['refill-chain']
        for k in ('AR','R','native_AR','native_R','scratch_operations'):
            r.check('same-chain-'+k,b['total'][k]==e['total'][k],[b['total'][k],e['total'][k]])
        r.check('measured-no-stall256B-46-to31',b['stream_intervals']==[46]*7 and e['stream_intervals']==[31]*7,[b['stream_intervals'],e['stream_intervals']])
        r.check('immutable-after',all(sha256(repo/n)==h for n,h in inv.items())and sha256(ROOT/'Makefile')==contract['root_Makefile_sha256'],pm['candidate_id'])
        write_json(r.path/'results.json',dict(results=results,CPU_API_cycles=None,fullN_saving_cycles=None,frequency_signoff_hz=None,GO=False))
        code=0
    except Exception:
        (r.path/'failure.txt').write_text(traceback.format_exc());print(traceback.format_exc(),flush=True)
    finally:
        # A failed compile or TB assertion keeps its exact sources and partial raw.
        for sub in r.build.iterdir():
            if sub.is_dir():
                out=r.path/sub.name;out.mkdir(exist_ok=True)
                for raw in ('protocol.csv','ledger.csv'):
                    if(sub/raw).exists()and not(out/raw).exists():shutil.copy2(sub/raw,out/raw)
        r.manifest['artifacts']={str(f.relative_to(r.path)):sha256(f)for f in r.path.rglob('*')if f.is_file()and f.name not in('manifest.json','commands.json','checks.json','exit-status.txt')}
        code=r.finish(code)
    print(r.manifest['status'],r.path,flush=True);return code
if __name__=='__main__':raise SystemExit(main())
