from pathlib import Path
import socket,os,subprocess,json,time,select,fcntl,traceback
R=Path.cwd();E=R/'evidence/DEMO_V6_FABRIC_LINK/20261102-v1';Q=E/'hardware-link';Q.mkdir();S=Path('/mnt/c/codex_tmp/demo-v6-fabric-link-20261102-v1');lock=(R/'build/t27-physical-board.lock').open('a+');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
assert not(E/'HARDWARE_LINK_ATTEMPT.json').exists();(E/'HARDWARE_LINK_ATTEMPT.json').write_text(json.dumps(dict(epoch=time.time(),scope='Native Debugger XVC guarded existing ATK; no reconfiguration'),indent=2))
args=['/mnt/c/Users/cyqh1/AppData/Local/Programs/Python/Python312/python.exe','-u','C:/codex_tmp/demo-v6-fabric-link-20261102-v1/windows_guarded_jtag.py','C:/codex_tmp/demo-v6-fabric-link-20261102-v1/hardware-link']
err=(Q/'windows-stderr.log').open('xb');p=subprocess.Popen(args,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=err,start_new_session=True,bufsize=0)
def read_line(timeout):
 b=b'';end=time.time()+timeout
 while not b.endswith(b'\n'):
  assert time.time()<end,'Windows response timeout; preserve scene'
  rr,_,_=select.select([p.stdout],[],[],min(1,end-time.time()))
  if rr:
   part=p.stdout.read(1);assert part,'Windows worker closed';b+=part
 return json.loads(b)
try:
 ready=read_line(60);assert ready['status']=='READY_GUARDED_ATK',ready;(Q/'READY.json').write_text(json.dumps(ready,indent=2))
 (Q/'PIDS.json').write_text(json.dumps(dict(host_pid=os.getpid(),linux_interop_pid=p.pid,Windows_pid=ready['pid'],argv=args),indent=2))
 with socket.socket(socket.AF_UNIX)as srv:
  path=str(Q/'bridge.sock');srv.bind(path);os.chmod(path,0o600);srv.listen();srv.settimeout(1);end=time.time()+7200
  while time.time()<end and not(Q/'STOP').exists():
   try:c,_=srv.accept()
   except socket.timeout:continue
   with c,c.makefile('rwb',buffering=0)as f:
    for line in f:
     x=json.loads(line);assert x['cmd']=='shift';p.stdin.write(json.dumps(x).encode()+b'\n');r=read_line(60);f.write(json.dumps(r).encode()+b'\n')
finally:
 if p.poll()is None:
  try:p.stdin.write(b'{"cmd":"close"}\n');p.stdin.close();p.wait(timeout=15)
  except Exception:(Q/'CLEANUP_ERROR.txt').write_text(traceback.format_exc())
 err.close();(Q/'HOST_CLOSED.json').write_text(json.dumps(dict(epoch=time.time(),host_pid=os.getpid(),Windows_exit=p.poll()),indent=2));lock.close()
