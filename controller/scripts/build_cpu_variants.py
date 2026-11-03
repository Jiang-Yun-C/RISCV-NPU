#!/usr/bin/env python3
"""Generate reproducible T09 Cache/BTB candidates from pinned Scala sources.

Only writes a new output directory; never programs hardware or edits t27/cpu.
The original generator's configuration was reconstructed from archived source
lines. This is a new complete generator, not a claim of historical file recovery.
"""
import argparse,hashlib,json,os,shutil,subprocess,tarfile,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
GEN=ROOT/'cpu_gen'
UPSTREAM_SHA='344f4177144e96cffdeab5230c688e443644df9fb0f7bc65f278126e509343d7'
VARIANTS={'global':('global','dynamic'),'rr':('rr','dynamic'),'lru':('lru','dynamic'),
          'btb':('global','btb'),'lru_btb':('lru','btb')}
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('--output',type=Path,required=True)
 p.add_argument('--variant',choices=['all',*VARIANTS],default='all')
 p.add_argument('--sbt',default='sbt');p.add_argument('--sbt-launcher',type=Path)
 p.add_argument('--dependency-cache',type=Path)
 p.add_argument('--cache-kib',type=int,choices=[8,16,32],default=16)
 p.add_argument('--history-log2',type=int,choices=range(6,11),default=8)
 a=p.parse_args();out=a.output.resolve()
 if out.exists():p.error('refusing existing output')
 if out.is_relative_to(GEN.resolve()):p.error('output must be outside cpu_gen to avoid recursive copying')
 if any(ch.isspace() for ch in str(out)):p.error('output path cannot contain whitespace because sbt runMain tokenizes its command')
 archive=GEN/'upstream/VexRiscv-pinned.tar.gz'
 if not archive.is_file() or sha(archive)!=UPSTREAM_SHA:p.error('pinned upstream archive missing or modified')
 out.mkdir(parents=True); upstream=out/'upstream';upstream.mkdir()
 with tarfile.open(archive) as t:
  for m in t.getmembers():
   if m.issym() or m.islnk() or not (upstream/m.name).resolve().is_relative_to(upstream):
    raise ValueError('unsafe upstream archive member')
  t.extractall(upstream,filter='data')
 vex=next(upstream.iterdir())
 patches=sorted((GEN/'patches').glob('*.patch'))
 commands=[]
 for patch in patches:
  cmd=['patch','--batch','--fuzz=0','-p1','--input',str(patch)]
  r=subprocess.run(cmd,cwd=vex,capture_output=True,text=True,check=True)
  (out/(patch.stem+'.log')).write_text(r.stdout+r.stderr);commands.append(cmd)
 project=out/'project';shutil.copytree(GEN,project,ignore=shutil.ignore_patterns('target','upstream','evidence','generated','__pycache__'))
 opts=[f'-Dnexusrv.vex.source={vex}']
 env=dict(os.environ)
 if a.dependency_cache:
  cache=a.dependency_cache.resolve();cache.mkdir(parents=True,exist_ok=True)
  env['COURSIER_CACHE']=str(cache/'coursier')
  opts += [f'-Dsbt.boot.directory={cache}/sbt-boot',f'-Dsbt.global.base={cache}/sbt-global',f'-Dsbt.ivy.home={cache}/ivy']
  repo=cache/'repositories'
  repo.write_text('[repositories]\nlocal\nmaven-central: https://repo.maven.apache.org/maven2/\n')
  opts += ['-Dsbt.override.build.repos=true',f'-Dsbt.repository.config={repo}']
 if a.sbt_launcher:
  cmd=['java','-XX:ActiveProcessorCount=2','-Xmx2G',*opts,'-jar',str(a.sbt_launcher.resolve())]
 else:cmd=[a.sbt,*opts,'-J-Xmx2G','-batch']
 variants=VARIANTS if a.variant=='all' else {a.variant:VARIANTS[a.variant]}
 for name,(policy,prediction) in variants.items():
  cmd.append(f'runMain nexusrv.GenT09 {out / name} hard {policy} {prediction} {a.cache_kib} {a.history_log2}')
 start=time.monotonic()
 with (out/'generate.log').open('w') as log:r=subprocess.run(cmd,cwd=project,env=env,stdout=log,stderr=subprocess.STDOUT,timeout=1200)
 record={'scope':'RTL generation only, not physical timing or benchmark','upstream_sha256':sha(archive),
  'patches':{p.name:sha(p) for p in patches},'generator_sha256':sha(GEN/'src/main/scala/nexusrv/GenT09.scala'),
  'build_sbt_sha256':sha(GEN/'build.sbt'),'command':cmd,'exit_code':r.returncode,'host_seconds':time.monotonic()-start,
  'cache_kib_each':a.cache_kib,'ways':2,'line_bytes':32,'history_log2':a.history_log2,'variants':{}}
 for name,(policy,prediction) in variants.items():
  files={p.name:sha(p) for p in (out/name).glob('T09Cpu*') if p.is_file()}
  record['variants'][name]={'replacement':policy,'prediction':prediction,'files':files}
 (out/'GENERATION.json').write_text(json.dumps(record,indent=2)+'\n')
 if r.returncode or any('T09Cpu.v' not in x['files'] for x in record['variants'].values()):raise SystemExit('generation failed; see generate.log')
 print(json.dumps(record,indent=2))
if __name__=='__main__':main()
