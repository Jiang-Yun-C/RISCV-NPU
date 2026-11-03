"""Bounded host-timed four-LED Twinkle rhythm; no model or programming."""
import argparse,hashlib,json,os,re,signal,sys,time,traceback,threading
from datetime import datetime,timezone
from pathlib import Path
from framing import ResponseFramer
NOTES=(1,1,5,5,6,6,5,4,4,3,3,2,2,1,5,5,4,4,3,3,2,5,5,4,4,3,3,2,1,1,5,5,6,6,5,4,4,3,3,2,2,1)
DURATIONS=(1,1,1,1,1,1,2)*6
LEDS=(0,2,3,5);MASK=0x2d
def plan(bpm=120,repeats=1):
 if not 60<=bpm<=180 or not 1<=repeats<=5:raise ValueError('BPM限60–180，遍数限1–5')
 beat=60/bpm;out=[];cursor=0.
 for repeat in range(repeats):
  for i,(pitch,beats)in enumerate(zip(NOTES,DURATIONS)):
   out.append(dict(index=len(out),repeat=repeat+1,pitch=pitch,beats=beats,LED=LEDS[i%4],mask_value=1<<LEDS[i%4],on_seconds=cursor,off_seconds=cursor+beats*beat-.08));cursor+=beats*beat
 return dict(bpm=bpm,repeats=repeats,mask=MASK,LED_order=list(LEDS),notes=out,total_seconds=cursor,gap_seconds=.08,source='HOST_TIMED_DIRECT_UART_NO_MODEL',sound=False)
def write(p,x):
 p=Path(p);t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf8');end=time.monotonic()+2
 while True:
  try:t.replace(p);return
  except PermissionError:
   if time.monotonic()>end:raise
   time.sleep(.005)
class Link:
 def __init__(self,out,device=None):
  self.out=out;out.mkdir(parents=True,exist_ok=False);self.state=dict(status='RUNNING',source='HOST_TIMED_DIRECT_UART_NO_MODEL',commands=[],uart_baud=115200,physical_LED='NOT_OBSERVED',programming=0,model_loads=0,SD_writes=0,resets=0,reloads=0,windows_pid=os.getpid());self.healthy=True;self.owned_lock=False;self.lock=Path(r'C:\codex_tmp\competition-opt-v1-serial.lock');self.dev=None
  self.raw=(out/'uart.bin').open('xb');self.tx=(out/'tx.bin').open('xb');self.journal=(out/'rx-chunks.jsonl').open('x',encoding='utf8')
  if device is not None:self.dev=device;return
  try:
   import serial,serial.tools.list_ports
   ports=[p for p in serial.tools.list_ports.comports()if(p.device,p.vid,p.pid,p.serial_number)==('COM10',0x10c4,0xea60,'0001')]
   if len(ports)!=1:raise RuntimeError('找不到唯一CP2102 COM10/0001')
   self.lock.parent.mkdir(parents=True,exist_ok=True)
   fd=os.open(self.lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.write(fd,str(os.getpid()).encode());os.close(fd);self.owned_lock=True
   self.dev=serial.Serial(None,baudrate=115200,timeout=.02,write_timeout=2);self.dev.dtr=False;self.dev.rts=False;self.dev.port='COM10';self.dev.open()
  except BaseException:self.state.update(status='FAIL_OPEN_NO_COMMAND',failure=traceback.format_exc());self.close();raise
 def request(self,name,command,timeout=10):
  if not self.healthy:raise RuntimeError('链路已停止；不重发')
  wire=(command+'\n').encode('utf8');a=dict(name=name,command=command,started_ns=str(time.perf_counter_ns()),started_epoch=time.time(),rx_start=self.raw.tell(),tx_start=self.tx.tell(),status='RUNNING');self.state['commands'].append(a);write(self.out/'manifest.json',self.state)
  try:
   n=self.dev.write(wire);self.tx.write(wire[:n]);self.tx.flush()
   if n!=len(wire):raise RuntimeError('UART短写，不重发')
   self.dev.flush();fr=ResponseFramer();deadline=time.monotonic()+timeout
   while not fr.ready and not fr.halted:
    if time.monotonic()>deadline:raise TimeoutError('未收到完整READY；停止，不复位或重发')
    b=self.dev.read(min(self.dev.in_waiting or 1,65536))
    if b:
     row=dict(offset=self.raw.tell(),bytes=len(b),received_ns=str(time.perf_counter_ns()),sha256=hashlib.sha256(b).hexdigest());self.raw.write(b);self.raw.flush();self.journal.write(json.dumps(row)+'\n');self.journal.flush();fr.feed(b)
   if fr.error or not fr.ready:raise RuntimeError('板端错误；停止后续灯命令')
   a.update(status='PASS_RESPONSE_READY',rx_end=self.raw.tell(),finished_ns=str(time.perf_counter_ns()));write(self.out/'manifest.json',self.state);return fr.lines
  except BaseException:self.healthy=False;a['status']='FAIL_NO_RETRY';raise
 def bank(self,name,command,mask,values,owned,writes=1):
  lines=self.request(name,command);rows=[x for x in lines if x.startswith('T27 LED_BANK 1 ')]
  m=re.fullmatch(r'T27 LED_BANK 1 session=([0-9a-f]{16}) status=OK writes=([0-9a-f]{16}) mask=([0-9a-f]{16}) values=([0-9a-f]{16}) owned=([0-9a-f]{16})\s*',rows[0])if len(rows)==1 else None
  if not m or tuple(int(m[i],16)for i in(2,3,4,5))!=(writes,mask,values,owned):self.healthy=False;raise RuntimeError('灯控回执或未选位状态不匹配；停止')
  return dict(session=m[1],writes=writes,mask=mask,values=values,owned=owned)
 def close(self):
  if self.dev:
   try:self.dev.close()
   except Exception:pass
  for f in(self.raw,self.tx,self.journal):
   if not f.closed:f.close()
  if self.owned_lock and self.lock.exists()and self.lock.read_text().strip()==str(os.getpid()):self.lock.unlink()
  self.state.update(serial_closed=True,own_lock_released=not self.owned_lock or not self.lock.exists())
  write(self.out/'manifest.json',self.state)
def play(link,music,stop=None,clock=time.perf_counter,sleep=time.sleep):
 stop=stop or threading.Event();acquired=False;origin=None;events=[]
 def wait(t):
  while not stop.is_set():
   delay=t-clock()
   if delay<=0:return
   sleep(min(delay,.02))
 try:
  lines=link.request('sync-existing','')
  if'T27 LED_BANK_CAPABILITIES 1 mask=000000000000002d atomic=1 targets=explicit'not in lines:raise RuntimeError('当前配置没有四灯合同')
  link.bank('acquire-all-off',':ledm 45 0',45,0,45);acquired=True;origin=clock()+.1
  for note in music['notes']:
   wait(origin+note['on_seconds'])
   if stop.is_set():break
   lateness=clock()-origin-note['on_seconds']
   if lateness>.15:raise RuntimeError('主机调度落后超过150ms，停止灯效')
   before=clock();link.bank('note-'+str(note['index'])+'-on',':ledm 45 '+str(note['mask_value']),45,note['mask_value'],45);events.append(dict(**note,actual_on_seconds=before-origin,lateness_seconds=lateness))
   wait(origin+note['off_seconds'])
   if stop.is_set():break
   link.bank('note-'+str(note['index'])+'-off',':ledm 45 0',45,0,45)
  if not stop.is_set():wait(origin+music['total_seconds'])
  link.state.update(status='STOPPED_BY_USER'if stop.is_set()else'PASS_RHYTHM_CPU_READBACK',events=events,planned_seconds=music['total_seconds'],actual_seconds=clock()-origin)
 finally:
  if acquired and link.healthy:
   link.bank('release-automatic',':ledauto 45',45,0,0);link.bank('final-bank-query',':ledm?',45,0,0,0);link.state['released_automatic']=True
  write(link.out/'manifest.json',link.state)
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--bpm',type=float,default=120);ap.add_argument('--repeat',type=int,default=1);ap.add_argument('--dry-run',action='store_true');ap.add_argument('--out',type=Path);a=ap.parse_args();music=plan(a.bpm,a.repeat)
 if a.dry_run:print(json.dumps(music,ensure_ascii=False,indent=2));return 0
 base=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'NexusRVDemo/twinkle';out=a.out or base/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');link=None;stop=threading.Event()
 signal.signal(signal.SIGINT,lambda *_:stop.set())
 print('四灯顺序 LED0→LED2→LED3→LED5；小星星节奏，一遍约24秒。Ctrl+C停止并恢复自动。',flush=True)
 print('展示台需先点“断开”；本程序只控制四个板载LED。日志：'+str(out),flush=True)
 try:
  link=Link(out);write(out/'PLAN.json',music);play(link,music,stop);print(link.state['status'],flush=True);return 0
 except BaseException as e:
  if link:link.state.update(status='FAIL_PRESERVE_NO_RETRY',failure=traceback.format_exc());write(out/'manifest.json',link.state)
  print('停止：'+str(e)+'。若串口占用，请先在展示台点断开，再手动运行。',flush=True);return 1
 finally:
  if link:link.close()
if __name__=='__main__':
 code=main()
 if getattr(sys,'frozen',False)and len(sys.argv)==1:
  try:input('按Enter关闭窗口。')
  except EOFError:pass
 raise SystemExit(code)
