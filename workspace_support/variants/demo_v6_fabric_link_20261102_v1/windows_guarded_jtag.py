from pathlib import Path
import sys,json,os,time,traceback,hashlib
from guard import Guard,sequences,combine
from windows_cmsis_jtag import Jtag
out=Path(sys.argv[1]);out.mkdir(exist_ok=False);audit=(out/'vectors.jsonl').open('x');g=Guard();j=None
try:
 j=Jtag(r'C:\codex_tmp\pds-board-probe-20261009-v1\python-deps',100000);status=j.register(0x159)
 assert j.idcode==0x10603899 and status&0x1000 and not status&((1<<27)|3),'Wrong/failed actual target'
 ready=dict(status='READY_GUARDED_ATK',pid=os.getpid(),idcode=hex(j.idcode),status_register=hex(status),programming=False,Flash=False,NVM=False,FPGA_reset=False,hz=100000,epoch=time.time());(out/'READY.json').write_text(json.dumps(ready,indent=2));print(json.dumps(ready),flush=True)
 for line in sys.stdin:
  x=json.loads(line)
  if x['cmd']=='close':break
  assert x['cmd']=='shift';n=x['n'];tms=bytes.fromhex(x['tms']);tdi=bytes.fromhex(x['tdi']);before=g.state
  try:after,events=g.inspect(n,tms,tdi)
  except AssertionError as e:
   audit.write(json.dumps(dict(status='BLOCKED_BEFORE_HARDWARE',input=x,reason=str(e),epoch=time.time()))+'\n');audit.flush();print(json.dumps(dict(ok=False,error=str(e))),flush=True);continue
  seq=sequences(n,tms,tdi);reply=[]
  for i in range(0,len(seq),100):reply.extend(j.sequences(seq[i:i+100]))
  tdo=combine(seq,reply);g.commit(after);j.state=after[0]
  row=dict(status='SHIFT_COMPLETE',n=n,tms=tms.hex(),tdi=tdi.hex(),tdo=tdo.hex(),IR_updates=events,before=before,after=g.state,epoch=time.time());audit.write(json.dumps(row)+'\n');audit.flush();print(json.dumps(dict(ok=True,tdo=tdo.hex())),flush=True)
except BaseException:
 (out/'FAILURE.txt').write_text(traceback.format_exc());print(json.dumps(dict(ok=False,error=traceback.format_exc())),flush=True)
finally:
 if j:j.close()
 audit.close();(out/'CLOSED.json').write_text(json.dumps(dict(epoch=time.time(),pid=os.getpid(),HID_closed=True,programming=False,Flash=False,NVM=False,FPGA_reset=False),indent=2))
