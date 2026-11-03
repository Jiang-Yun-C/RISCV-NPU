"""Fixed user shortcuts for all four LEDs; no model output or generated code."""
from datetime import datetime, timezone
import os,re,threading,time,traceback
from rhythm_effect import BridgeLink,model_plan
from twinkle_plan import Link as BankLink,write
MASK=45

def validate_switch_call(body):
    if not isinstance(body,dict) or set(body)!={'call_id','action'}:
        raise ValueError('灯光操作字段无效')
    if not isinstance(body['call_id'],str) or not re.fullmatch(r'[A-Za-z0-9-]{16,80}',body['call_id']):
        raise ValueError('灯光操作标识无效')
    if body['action'] not in ('on','off'):
        raise ValueError('仅支持四灯开灯或关灯')
    return dict(body)

class SwitchLink(BridgeLink):
    def __init__(self,bridge,owner,out,call):
        self.bridge=bridge;self.owner=owner;self.out=out;out.mkdir(parents=True)
        self.healthy=True;self.start=time.perf_counter_ns()
        self.state=dict(id=out.name,call_id=call['call_id'],action=call['action'],target_values=MASK if call['action']=='on' else 0,
            status='RUNNING',source='USER_QUICK_ACTION_NOT_MODEL_INFERENCE',commands=[],uart_baud=115200,
            physical_LED='NOT_OBSERVED',programming=0,model_loads=0,SD_writes=0,resets=0,reloads=0,
            windows_pid=os.getpid(),CPU_stores=0,started_ns=str(self.start),confirmed=False,held=False,
            released_automatic=False,log_directory=str(out))
        self.raw=(out/'uart.bin').open('xb');self.tx=(out/'tx.bin').open('xb');self.journal=(out/'rx-chunks.jsonl').open('x',encoding='utf8')
    def bank(self,name,command,mask,values,owned,writes=1):
        receipt=BankLink.bank(self,name,command,mask,values,owned,writes)
        self.state['last_bank']=receipt;self.state['CPU_stores']+=writes
        write(self.out/'manifest.json',self.state)
        return receipt

def install_light_switch(base):
    class LightSwitchBridge(base):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs);self.switch_invocations={}
        def light_switch_status(self,call_id,owner):
            with self.lock:
                self._check_owner(owner)
                saved=self.switch_invocations.get(call_id)
                if not saved or saved['owner']!=owner:raise ValueError('未找到本窗口的灯光操作')
                link=saved['link'];state=link.state
                keys=('id','call_id','action','target_values','status','source','CPU_stores','confirmed','held','last_bank','last_rx_seq','failure','log_directory')
                return dict({k:state[k] for k in keys if k in state},active=self.effect_link is link and bool(self.effect_thread and self.effect_thread.is_alive()))
        def light_switch(self,body,owner):
            call=validate_switch_call(body)
            with self.lock:
                self._check_owner(owner)
                previous=self.switch_invocations.get(call['call_id'])
                if previous:
                    if previous['owner']!=owner or previous['call']!=call:raise ValueError('操作标识不能绑定另一请求')
                    return dict(self.light_switch_status(call['call_id'],owner),deduplicated=True)
                if len(self.switch_invocations)>=256:raise ValueError('本次展示操作数量已达到上限')
                if self.effect_thread and self.effect_thread.is_alive():raise ValueError('请先等待当前灯光操作完成')
                if not self.device or self.pending or not self.synced or self.halted or self.bank_mask!=MASK:
                    raise ValueError('请先连接并同步四灯设备')
                if self.effect_link and not self.effect_link.healthy:raise ValueError('前次链路故障，禁止继续发送')
                tag='switch-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')
                link=SwitchLink(self,owner,self.effect_log_root/tag,call)
                self.effect_link=link;self.effect_stop=threading.Event()
                self.switch_invocations[call['call_id']]=dict(owner=owner,call=call,link=link)
                self.effect_thread=threading.Thread(target=self._switch_run,args=(link,),daemon=True)
                self.effect_thread.start()
                return dict(self.light_switch_status(call['call_id'],owner),deduplicated=False)
        def _switch_run(self,link):
            try:
                identity=model_plan()['entry']['observedIdentity']
                lines=link.request('verify-current-model-identity',':identity')
                if lines.count('T25 MODEL '+identity['model']+' TOKENIZER '+identity['tokenizer'])!=1:
                    raise ValueError('当前设备身份与展示配置不匹配')
                value=link.state['target_values']
                link.bank('set-all-lights',':ledm 45 '+str(value),MASK,value,MASK,1)
                link.bank('verify-held-lights',':ledm?',MASK,value,MASK,0)
                link.state.update(status='PASS_SWITCH_CPU_READBACK',confirmed=True,held=True)
            except BaseException:
                link.healthy=False
                with self.lock:self.synced=False
                link.state.update(status='FAIL_PRESERVE_NO_RETRY',confirmed=False,held=False,failure=traceback.format_exc())
            finally:link.close()
    return LightSwitchBridge
