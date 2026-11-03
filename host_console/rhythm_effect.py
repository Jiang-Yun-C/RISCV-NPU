"""Prepared real-model intent -> bounded live LED commands on the same UART."""
import base64,hashlib,json,os,threading,time,traceback
from datetime import datetime,timezone
from pathlib import Path
from framing import ResponseFramer
from twinkle_plan import Link as BankLink,plan,play,write

ROOT=Path(__file__).resolve().parent
def phrase(s):return s.strip().rstrip('。.!！?？') if isinstance(s,str)else ''
def model_plan():
    doc=json.loads((ROOT/'static/rhythm-model.json').read_text(encoding='utf8'))
    entry=doc['entry'];raw=b''.join(base64.b64decode(c,validate=True)for c in entry['uart']['chunks'])
    if hashlib.sha256(raw).hexdigest()!=entry['uart']['sha256']:raise ValueError('模型原始记录摘要不匹配')
    intent=json.loads(entry['text'].strip())
    if isinstance(intent,list)and len(intent)==1:intent=intent[0]
    if intent!={'effect':'twinkle','bpm':120,'repeat':1}or doc['intent']!=intent:raise ValueError('模型未生成可执行的小星星计划')
    if entry['prompt']!=doc['model_prompt']or entry['source']!='pre_generated':raise ValueError('模型计划来源无效')
    return doc

class BridgeLink:
    def __init__(self,bridge,owner,out,doc,start):
        self.bridge=bridge;self.owner=owner;self.out=out;out.mkdir(parents=True)
        self.healthy=True;self.start=start
        self.state=dict(id=out.name,status='RUNNING',source='PREPARED_REAL_MODEL_INTENT_NOT_CURRENT_INFERENCE',model_entry_id=doc['entry']['id'],model_raw_sha256=doc['entry']['uart']['sha256'],model_identity=doc['entry']['observedIdentity'],user_prompt=doc['user_prompt'],commands=[],uart_baud=115200,physical_LED='NOT_OBSERVED',programming=0,model_loads=0,SD_writes=0,resets=0,reloads=0,windows_pid=os.getpid(),CPU_stores=0,notes_completed=0,started_ns=str(start),released_automatic=False,log_directory=str(out))
        self.raw=(out/'uart.bin').open('xb');self.tx=(out/'tx.bin').open('xb');self.journal=(out/'rx-chunks.jsonl').open('x',encoding='utf8')
    def request(self,name,command,timeout=5):
        if not self.healthy:raise RuntimeError('链路异常，禁止重试')
        a=dict(name=name,command=command,started_ns=str(time.perf_counter_ns()),rx_start=self.raw.tell(),status='RUNNING');self.state['commands'].append(a)
        try:
            with self.bridge.lock:cursor=self.bridge.seq
            a['write_timing']=self.bridge.write(command,self.owner);self.tx.write((command+'\n').encode('utf8'));self.tx.flush()
            fr=ResponseFramer();deadline=time.monotonic()+timeout
            while not fr.ready and not fr.halted:
                if time.monotonic()>deadline:raise TimeoutError('未取得完整READY，停止且不重发')
                data=self.bridge.read(cursor,self.owner,wait=min(.25,max(0,deadline-time.monotonic())))
                if not data['connected']:raise RuntimeError(data.get('error')or'串口断开')
                for chunk in data['chunks']:
                    if chunk['seq']!=cursor+1:raise RuntimeError('UART记录不连续')
                    cursor=chunk['seq'];b=base64.b64decode(chunk['data'],validate=True)
                    row=dict(chunk,offset=self.raw.tell(),bytes=len(b));self.raw.write(b);self.raw.flush();self.journal.write(json.dumps(row)+'\n');self.journal.flush();fr.feed(b)
            if fr.error or not fr.ready:raise RuntimeError('板端错误，不再发送')
            fr.terminal();a.update(status='PASS_RESPONSE_READY',rx_end=self.raw.tell(),finished_ns=str(time.perf_counter_ns()))
            self.state['last_rx_seq']=cursor;write(self.out/'manifest.json',self.state);return fr.lines
        except BaseException:
            self.healthy=False;a['status']='FAIL_NO_RETRY'
            with self.bridge.lock:self.bridge.synced=False
            raise
    def bank(self,name,command,mask,values,owned,writes=1):
        receipt=BankLink.bank(self,name,command,mask,values,owned,writes)
        self.state['last_bank']=receipt;self.state['CPU_stores']+=writes
        if name.endswith('-on'):
            self.state['notes_completed']+=1
            if 'first_on_seconds'not in self.state:
                a=self.state['commands'][-1];self.state['first_on_seconds']=(int(a['started_ns'])-self.start)/1e9;self.state['first_CPU_on_receipt_seconds']=(time.perf_counter_ns()-self.start)/1e9
        write(self.out/'manifest.json',self.state);return receipt
    def close(self):
        for f in(self.raw,self.tx,self.journal):f.close()
        self.state['raw_sha256']=hashlib.sha256((self.out/'uart.bin').read_bytes()).hexdigest();write(self.out/'manifest.json',self.state)

def make_bridge(base):
    class EffectBridge(base):
        def __init__(self,serial_factory=None,log_root=None):
            super().__init__(serial_factory);self.effect_thread=None;self.effect_stop=threading.Event();self.effect_link=None
            self.effect_log_root=Path(log_root)if log_root else Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'NexusRVDemo/chat-rhythm'
            self.global_lock=Path(r'C:\codex_tmp\competition-opt-v1-serial.lock')if os.name=='nt'else None;self.global_lock_value=None
        def connect(self,port,owner,baud=115200):
            with self.lock:
                if self.device:return super().connect(port,owner,baud)
                if self.global_lock:
                    self.global_lock.parent.mkdir(parents=True,exist_ok=True);value=str(os.getpid())+' '+owner
                    fd=os.open(self.global_lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY);os.write(fd,value.encode());os.close(fd);self.global_lock_value=value
                try:return super().connect(port,owner,baud)
                except BaseException:self._release_lock();raise
        def _release_lock(self):
            if self.global_lock_value and self.global_lock.exists()and self.global_lock.read_text()==self.global_lock_value:self.global_lock.unlink()
            self.global_lock_value=None
        def write(self,command,owner):
            with self.lock:
                if self.effect_thread and self.effect_thread.is_alive()and threading.current_thread()is not self.effect_thread:raise ValueError('灯效执行中，请先停止灯效')
                if self.effect_link and not self.effect_link.healthy:raise ValueError('灯效链路异常，保留现场，不再发送')
                return super().write(command,owner)
        def rhythm_status(self,owner):
            with self.lock:
                self._check_owner(owner)
                if not self.effect_link:return {'status':'IDLE','active':False}
                state=self.effect_link.state
                keys=('id','status','source','model_entry_id','notes_completed','CPU_stores','first_on_seconds','first_CPU_on_receipt_seconds','released_automatic','last_bank','last_rx_seq','actual_seconds','failure','log_directory')
                return dict({k:state[k]for k in keys if k in state},active=bool(self.effect_thread and self.effect_thread.is_alive()))
        def rhythm_start(self,prompt,owner):
            with self.lock:
                self._check_owner(owner)
                if self.effect_thread and self.effect_thread.is_alive():raise ValueError('一次只执行一个灯效')
                if not self.device or self.pending or not self.synced or self.halted or self.bank_mask!=45:raise ValueError('请先连接并同步四灯READY')
                if self.effect_link and not self.effect_link.healthy:raise ValueError('前次链路故障，现场保留，禁止自动重试')
                doc=model_plan()
                if phrase(prompt)!=phrase(doc['user_prompt']):raise ValueError('当前准备的模型计划仅匹配小星星演示原句')
                start=time.perf_counter_ns();tag=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ');self.effect_link=BridgeLink(self,owner,self.effect_log_root/tag,doc,start);self.effect_stop=threading.Event()
                self.effect_thread=threading.Thread(target=self._rhythm_run,args=(self.effect_link,doc),daemon=True);self.effect_thread.start()
                return self.rhythm_status(owner)
        def _rhythm_run(self,link,doc):
            try:
                identity=doc['entry']['observedIdentity'];lines=link.request('verify-model-identity',':identity')
                if lines.count('T25 MODEL '+identity['model']+' TOKENIZER '+identity['tokenizer'])!=1:
                    link.healthy=False;raise ValueError('当前模型身份与缓存模型计划不匹配')
                from tool_packages.twinkle_v1 import build,run
                music=build(doc['intent']);write(link.out/'PLAN.json',music)
                run(link,music,self.effect_stop)
            except BaseException:link.state.update(status='FAIL_PRESERVE_NO_RETRY',failure=traceback.format_exc())
            finally:link.close()
        def rhythm_stop(self,owner):
            self._check_owner(owner);self.effect_stop.set();return self.rhythm_status(owner)
        def disconnect(self,owner=None):
            if owner is not None:self._check_owner(owner)
            if self.effect_thread and self.effect_thread.is_alive():
                self.effect_stop.set();self.effect_thread.join(7)
                if self.effect_thread.is_alive():raise ValueError('灯效正在结束当前命令，请等待READY')
            try:return super().disconnect(owner)
            finally:self._release_lock()
    return EffectBridge
