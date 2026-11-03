"""Fresh, guarded existing-V6 Fabric session. Never programs, resets, or opens UART."""
from pathlib import Path
import argparse,hashlib,json,os,re,shutil,subprocess,sys,time,traceback
V=Path(__file__).resolve().parent;R=V.parents[1]
a=argparse.ArgumentParser();a.add_argument('--run-id',required=True);a.add_argument('--headless',action='store_true');a.add_argument('--probe',action='store_true');a.add_argument('--prepare-only',action='store_true');a.add_argument('--seconds',type=int,default=3600);a.add_argument('--xvc-port',type=int,default=25431);a.add_argument('--server-port',type=int,default=65428);args=a.parse_args()
assert re.fullmatch('[A-Za-z0-9_-]{1,24}',args.run_id)and 5<=args.seconds<=7200
assert all(1024<=p<=65535 for p in [args.xvc_port,args.server_port])and args.xvc_port!=args.server_port
b=json.loads((R/'configs/demo-v6-board-current.json').read_text());assert b['source_content_id']=='3ebbf449cb622e28baa59e02e02da20ba79a4a4b03d3278aacfa650ecbcb413a'
fic=R/'exports/demo-v6-irq-offline-20261102-v1/hardware/demo-v6-irq-debug.fic';assert hashlib.sha256(fic.read_bytes()).hexdigest()=='942492fef6ac719f20162ce5f79baeaec686aa7a120fbeec1ecfa0491322c148'
E=R/'evidence/DEMO_V6_FABRIC_LINK'/args.run_id;E.mkdir(exist_ok=False);T=E/'runtime';T.mkdir();S=Path('/mnt/c/codex_tmp')/('v6-fabric-'+args.run_id);S.mkdir(exist_ok=False);Q=E/'hardware-link';assert len(str(Q/'bridge.sock').encode())<108
save=lambda p,x:Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n')
for n in ['guard.py','guard_large.py']:shutil.copy2(V/n,T/n)
for n in ['guard.py','windows_guarded_jtag.py']:shutil.copy2(V/n,S/n)
shutil.copy2(R/'variants/demo_v6_board_20261102_v1/windows_cmsis_jtag.py',S/'windows_cmsis_jtag.py')
x=(V/'host_bridge.py').read_text().replace("E=R/'evidence/DEMO_V6_FABRIC_LINK/20261102-v1'",'E=Path('+repr(str(E))+')').replace('demo-v6-fabric-link-20261102-v1',S.name);(T/'host.py').write_text(x)
x=(V/'xvc_bridge_large.py').read_text();start=x.index('for line in Path(');end=x.index('def exact(',start);x=x[:start]+x[end:];x=x.replace("Q=Path.cwd()/'evidence/DEMO_V6_FABRIC_LINK/20261102-v1/hardware-link'",'Q=Path('+repr(str(Q))+')').replace('25431',str(args.xvc_port));(T/'xvc.py').write_text(x)
(T/'connect.tcl').write_text(f'dbg_connect -ip 127.0.0.1 -port {args.server_port}\n')
native='''from pathlib import Path
import subprocess,os,time,signal,json
T=Path(__file__).resolve().parent;E=T.parent
config=json.loads((E/'SESSION.json').read_text());children=[]
def start(n,argv):
 f=(E/(n+'.log')).open('wb');p=subprocess.Popen(argv,cwd=E,env=dict(os.environ,QT_QPA_PLATFORM='xcb'),stdout=f,stderr=subprocess.STDOUT,start_new_session=True);children.append((p,f));return p
try:
 server=start('server',['/software/eda/pango/PDS_2024.2/bin/cdt_js','-work_dir',str(E),'-port',str(config['server_port'])])
 proxy=start('xvc',['/usr/bin/python3','-B','-u',str(T/'xvc.py')]);time.sleep(1)
 gui=None
 if not config['headless']:gui=start('debugger',['/software/eda/pango/PDS_2024.2/bin/cdt_dbg','-file',str(T/'connect.tcl')])
 (E/'NATIVE_PIDS.json').write_text(json.dumps(dict(supervisor=os.getpid(),children=[p.pid for p,_ in children]),indent=2))
 end=time.time()+config['seconds']+60
 while time.time()<end and not(E/'STOP').exists():
  assert server.poll()is None and proxy.poll()is None,'Native backend exited'
  if gui and gui.poll()is not None:break
  time.sleep(.2)
finally:
 for p,f in reversed(children):
  if p.poll()is None:os.killpg(p.pid,signal.SIGTERM);p.wait(timeout=10)
  f.close()
 (E/'NATIVE_CLOSED.json').write_text(json.dumps(dict(epoch=time.time(),children=[dict(pid=p.pid,exit_code=p.poll())for p,_ in children]),indent=2))
'''
(T/'native.py').write_text(native)
probe='''import socket,struct,json,sys
p=int(sys.argv[1]);s=socket.create_connection(('127.0.0.1',p),10)
def rx(n):
 b=b''
 while len(b)<n:
  x=s.recv(n-len(b));assert x;b+=x
 return b
s.sendall(b'getinfo:');info=b''
while not info.endswith(b'\\n'):info+=rx(1)
assert info.startswith(b'xvcServer_v1.0:')
def shift(n,m,d):
 s.sendall(b'shift:'+struct.pack('<I',n)+m+d);return rx((n+7)//8)
shift(7,b'\\x7f',b'\\0');shift(4,b'\\x02',b'\\0')
n=4000;tms=bytearray((n+7)//8);tms[-1]=128;r=shift(n,tms,bytes(len(tms)));assert int.from_bytes(r[:4],'little')==0x10603899 and not any(r[4:])
shift(2,b'\\x01',b'\\0');s.close();print(json.dumps(dict(status='PASS_REAL_ATK_XVC_4000_BIT_READ_ONLY_IDCODE',idcode='0x10603899',payload_bytes=len(r),configuration_commands=0)))
'''
(T/'probe.py').write_text(probe)
session=dict(run_id=args.run_id,source_content_id=b['source_content_id'],FIC=str(fic),stage=str(S),xvc_port=args.xvc_port,server_port=args.server_port,seconds=args.seconds,headless=args.headless,GUI_steps=['Next/Add Pango Virtual Cable','host127.0.0.1 port'+str(args.xvc_port),'Finish, scan chain, confirm exact PG2L200H','Import matching FIC; configure trigger; Run/Export; never Program'],programming_commands=0,UART_open=False);save(E/'SESSION.json',session)
if args.prepare_only:print(json.dumps(dict(status='PREPARED_NO_HARDWARE',evidence=str(E))));raise SystemExit(0)
host=native=None;handles=[];code=1
try:
 for name,argv in [('host',[sys.executable,'-B',str(T/'host.py')])]:
  f=(E/(name+'.log')).open('wb');handles.append(f);host=subprocess.Popen(argv,cwd=R,stdout=f,stderr=subprocess.STDOUT)
 deadline=time.time()+90
 while not(Q/'READY.json').exists():assert host.poll()is None and time.time()<deadline,'Host did not arm; inspect original logs';time.sleep(.1)
 f=(E/'native-launch.log').open('wb');handles.append(f);native=subprocess.Popen(['/usr/local/bin/pds2024-run','/usr/bin/python3','-B',str(T/'native.py')],cwd=R,stdout=f,stderr=subprocess.STDOUT)
 deadline=time.time()+30
 while not(E/'NATIVE_PIDS.json').exists():assert native.poll()is None and time.time()<deadline;time.sleep(.1)
 print('READY',str(E),'PDS server',args.server_port,'virtual cable',args.xvc_port,flush=True)
 if args.probe:
  p=subprocess.run(['/usr/local/bin/pds2024-run','/usr/bin/python3',str(T/'probe.py'),str(args.xvc_port)],cwd=R,capture_output=True,text=True,timeout=90);(E/'probe.stdout.log').write_text(p.stdout);(E/'probe.stderr.log').write_text(p.stderr);assert p.returncode==0,p.stderr;save(E/'PROBE.json',json.loads(p.stdout));print(p.stdout.strip());code=0
 else:
  deadline=time.time()+args.seconds
  while time.time()<deadline and not(E/'STOP').exists()and native.poll()is None:time.sleep(.5)
  code=0
except KeyboardInterrupt:code=0
except BaseException:(E/'FAILURE.txt').write_text(traceback.format_exc());raise
finally:
 (E/'STOP').write_text('Close this native debugger/bridge session only; retain FPGA and model')
 if native:
  try:native.wait(timeout=30)
  except subprocess.TimeoutExpired:(E/'NATIVE_CLEANUP_PENDING').write_text('Inspect same PIDs; do not reprogram')
 (Q/'STOP').write_text('Native endpoint closed; release same ATK owner')if Q.exists()else None
 if host:
  try:host.wait(timeout=30)
  except subprocess.TimeoutExpired:(E/'HOST_CLEANUP_PENDING').write_text('Inspect same Windows PID; do not reprogram')
 for f in handles:f.close()
 save(E/'FINAL.json',dict(status='CLOSED'if code==0 else'FAILED_PRESERVED',host_exit=host.poll()if host else None,native_exit=native.poll()if native else None,epoch=time.time(),FPGA_reset=0,programming=0,model_loads=0,UART_TX=0))
raise SystemExit(code)
