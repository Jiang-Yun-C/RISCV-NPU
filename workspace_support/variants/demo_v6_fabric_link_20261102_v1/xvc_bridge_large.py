from pathlib import Path
import socket,struct,json,time,os
Q=Path.cwd()/'evidence/DEMO_V6_FABRIC_LINK/20261102-v1/hardware-link'
from guard_large import Guard
g=Guard()
for line in Path('/mnt/c/codex_tmp/demo-v6-fabric-link-20261102-v1/hardware-link/vectors.jsonl').read_text().splitlines():
 row=json.loads(line)
 if row['status']=='SHIFT_COMPLETE':
  after,_=g.inspect(row['n'],bytes.fromhex(row['tms']),bytes.fromhex(row['tdi']));g.commit(after)
def exact(c,n):
 b=b''
 while len(b)<n:
  x=c.recv(n-len(b))
  if not x:raise EOFError()
  b+=x
 return b
print('XVC_BRIDGE_READY',os.getpid(),flush=True)
with socket.socket()as srv:
 srv.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1);srv.bind(('127.0.0.1',25431));srv.listen()
 while True:
  c,_=srv.accept();ipc=socket.socket(socket.AF_UNIX);ipc.connect(str(Q/'bridge.sock'))
  with c,ipc,ipc.makefile('rwb',buffering=0)as f,(Q/'xvc-wire-v2.jsonl').open('a')as log:
   try:
    while True:
     cmd=b''
     while not cmd.endswith(b':'):cmd+=exact(c,1)
     if cmd==b'getinfo:':c.sendall(b'xvcServer_v1.0:2048\n')
     elif cmd==b'settck:':exact(c,4);c.sendall(struct.pack('<I',10000))
     elif cmd==b'shift:':
      n=struct.unpack('<I',exact(c,4))[0];assert n<=1048576;nb=(n+7)//8;tms=exact(c,nb);tdi=exact(c,nb)
      after,events=g.inspect(n,tms,tdi)  # Entire vector is checked before the first hardware chunk.
      log.write(json.dumps(dict(event='BEGIN',epoch=time.time(),n=n,IR_updates=events))+'\n');log.flush();tdo=bytearray()
      for offset in range(0,n,2048):
       count=min(2048,n-offset);byte=offset//8;size=(count+7)//8;x=dict(cmd='shift',n=count,tms=tms[byte:byte+size].hex(),tdi=tdi[byte:byte+size].hex());f.write(json.dumps(x).encode()+b'\n');r=json.loads(f.readline());assert r['ok'],r;tdo.extend(bytes.fromhex(r['tdo']))
      assert len(tdo)==nb;g.commit(after);log.write(json.dumps(dict(event='COMPLETE',epoch=time.time(),n=n,tdo_sha256=__import__('hashlib').sha256(tdo).hexdigest()))+'\n');log.flush();c.sendall(tdo)
     else:raise ValueError(cmd)
   except Exception as e:log.write(json.dumps(dict(end=repr(e),epoch=time.time()))+'\n');log.flush()
