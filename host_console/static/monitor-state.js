// Passive view model. All device values enter through the existing validated
// parser or the existing strict executor status. No API, UART or device timers.
const stageNames={prefill:'预填充',decode:'逐步生成',validating:'校验结果',executing:'执行动作'};
export class RuntimeState {
  constructor(sourceId,now=()=>Date.now(),changed=()=>{}){this.now=now;this.changed=changed;this.state={schema:'nexusrv-runtime-v1',sourceId,revision:0,publishedAt:null,fixture:false,connection:{connected:false,synced:false,pending:false},transport:{bytes:0,chunks:0,lastRxAt:null,bins:[]},task:this.emptyTask(),cpu:{label:'等待设备',observed:false},npu:{label:'尚无推理回执',observed:false},leds:null,events:[]};}
  emptyTask(){return{kind:'idle',label:'等待一个新的任务',status:'idle',startedAt:null,finishedAt:null,stage:null,action:null,session:null,generated:null,stores:null,notes:null,ceCalls:null,fallbackCalls:null,metrics:null};}
  touch(){this.state.revision++;this.changed();}
  log(title,source='host',detail=null){this.state.events.push({at:this.now(),title,source,detail});if(this.state.events.length>48)this.state.events.shift();}
  fixture(value){this.state.fixture=!!value;this.touch();}
  connection(value){const previous=this.state.connection;this.state.connection={connected:!!value.connected,synced:!!value.synced,pending:!!value.pending};if(previous.connected!==!!value.connected)this.log(value.connected?'设备连接已建立':'设备连接已断开');if(!value.connected){this.state.leds=null;this.state.cpu={label:'连接已断开',observed:false};this.state.npu={label:'当前状态未知',observed:false};}if(value.connected&&value.synced&&!value.pending&&(!previous.synced||previous.pending)){this.state.cpu={label:'服务已就绪',observed:true};this.log('设备报告服务就绪','device');}this.touch();}
  chunk(chunk){const count=atob(chunk.data).length,t=this.state.transport,now=this.now(),second=Math.floor(now/1000)*1000;t.bytes+=count;t.chunks++;t.lastRxAt=now;t.bins=t.bins.filter(x=>now-x.at<60000);let bin=t.bins.at(-1);if(!bin||bin.at!==second){bin={at:second,bytes:0};t.bins.push(bin);}bin.bytes+=count;this.touch();}
  begin(kind,label,action=null){this.state.task={...this.emptyTask(),kind,action,label:String(label).slice(0,120),status:kind==='replay'?'complete':'pending',startedAt:this.now(),finishedAt:kind==='replay'?this.now():null};this.state.leds=null;this.state.cpu={label:kind==='replay'?'未触发设备请求':'等待设备回执',observed:false};this.state.npu={label:kind==='live'?'等待推理阶段回执':'本次未触发推理',observed:false};this.log(kind==='replay'?'展示已保存的回复':kind==='replay_device'?'准备灯光任务':kind==='direct_device'?'提交设备控制请求':'提交实时对话','host');this.touch();}
  command(command){this.log(command===''?'请求同步设备':command===':prefix 1'?'请求清理设备上下文':command===':stream 1'?'开启流式回复':'发送服务请求','host',{command});this.touch();}
  parser(event){const t=this.state.task;if(t.kind!=='live')return;
    if(event.type==='received'){this.log('设备确认收到请求','device',{kind:event.kind});this.state.cpu={label:'已接收请求',observed:true};}
    else if(event.type==='request'){t.session=event.request.sessionHex;t.status='running';this.log('CPU 服务已接受请求','device',event.request);this.state.cpu={label:'服务请求已接受',observed:true};}
    else if(event.type==='phase'){t.stage=event.stage;t.status='running';this.log('进入'+stageNames[event.stage]+'阶段','device',{session:event.session,stage:event.stage});this.state.npu={label:stageNames[event.stage]||event.stage,observed:true};}
    else if(event.type==='token'&&t.kind==='live'){t.generated=event.index;if(event.index===1||event.index%16===0)this.log(event.index===1?'收到首个生成片段':'已收到 '+event.index+' 个生成片段','device',{index:event.index});}
    else if(event.type==='step'&&t.kind==='live'){t.generated=event.generated;}
    else if(event.type==='result'){if(event.complete&&event.modelComplete){t.status='complete';t.finishedAt=this.now();t.metrics=event.metrics;t.generated=event.metrics?.generated??t.generated;t.ceCalls=event.metrics?.ce_calls??null;t.fallbackCalls=event.metrics?.fallback_calls??null;this.state.npu={label:'本次推理已完成',observed:true};this.log('完整回复与结束记录已核对','device',event.metrics);}else{this.fail(event.error||'回复未完整结束');return;}}
    else if(event.type==='error'){this.fail(event.message);return;}
    else if(event.type==='ready'){this.state.cpu={label:'服务已就绪',observed:true};this.log('设备报告服务就绪','device');}
    else if(['profile','pmu','transfer','prefix'].includes(event.type))this.log(({profile:'收到阶段统计',pmu:'收到性能计数',transfer:'收到传输统计',prefix:'收到上下文复用统计'})[event.type],'device',event);
    else return;
    this.touch();
  }
  effect(status){const t=this.state.task,previousNotes=t.notes;
    t.notes=status.notes_completed??null;t.stores=status.CPU_stores??null;
    if(status.last_bank)this.state.leds={...status.last_bank,observedAt:this.now()};
    if(status.last_bank){this.state.cpu={label:'灯光写入已确认',observed:true};t.status=status.active?'running':t.status;}
    if(t.notes!==previousNotes&&t.notes!==null&&t.notes>0)this.log('设备已执行第 '+t.notes+' 个音符','device',{notes:t.notes,stores:t.stores});
    if(!status.active){
      if(['PASS_RHYTHM_CPU_READBACK','STOPPED_BY_USER'].includes(status.status)&&status.released_automatic){t.status=status.status==='STOPPED_BY_USER'?'stopped':'complete';t.finishedAt=this.now();this.state.cpu={label:'已恢复默认灯光',observed:true};this.log(t.status==='stopped'?'任务已停止并释放灯光':'灯光任务已完成并释放','device',{status:status.status,stores:t.stores});}
      else if(status.status!=='IDLE'){this.fail(status.failure||'缺少完整释放记录');return;}
    }
    this.touch();
  }
  switchState(status){const t=this.state.task;t.action=status.action;t.stores=status.CPU_stores??null;
    if(status.last_bank){this.state.leds={...status.last_bank,observedAt:this.now()};this.state.cpu={label:'灯光写入已确认',observed:true};t.status='running';}
    if(!status.active){
      if(status.status==='PASS_SWITCH_CPU_READBACK'&&status.confirmed&&status.held&&status.CPU_stores===1&&status.last_bank?.owned===45&&status.last_bank?.values===status.target_values){
        t.status='complete';t.finishedAt=this.now();this.state.cpu={label:status.action==='on'?'四灯常亮已确认':'四灯熄灭已确认',observed:true};this.log(status.action==='on'?'四盏灯已打开并保持':'四盏灯已关闭并保持','device',{action:status.action,stores:t.stores,bank:status.last_bank});
      }else{this.fail(status.failure||'缺少目标灯光确认');return;}
    }
    this.touch();
  }
  fail(message){this.state.task.status='error';this.state.task.finishedAt=this.now();this.state.cpu={label:'执行状态待检查',observed:false};this.state.npu={label:'当前状态未知',observed:false};this.state.leds=null;this.log('操作未完成','host',{message:String(message).slice(0,1000)});this.touch();}
  clear(){this.state.task=this.emptyTask();this.state.events=[];this.state.leds=null;this.state.npu={label:'尚无推理回执',observed:false};this.log('当前对话上下文已清空');this.touch();}
  snapshot(){return structuredClone({...this.state,publishedAt:this.now()});}
}
export function attachRuntimeMonitor(anchorId){
  const id=crypto.randomUUID(),anchor=document.getElementById(anchorId);if(anchor)anchor.href='monitor.html?source='+encodeURIComponent(id);
  let channel=null,timer=null,lastSubscriber=0;
  const state=new RuntimeState(id,()=>Date.now(),()=>{if(channel&&Date.now()-lastSubscriber<15000&&!timer)timer=setTimeout(publish,250);});
  function publish(){clearTimeout(timer);timer=null;try{channel?.postMessage({type:'snapshot',value:state.snapshot()});}catch{ /* Monitoring never interrupts a task. */ }}
  try{channel=new BroadcastChannel('nexusrv-runtime-'+id);channel.onmessage=e=>{if(e.data?.type==='request'){lastSubscriber=Date.now();publish();}};}catch{ /* The main console remains usable without BroadcastChannel. */ }
  addEventListener('pagehide',()=>{try{channel?.postMessage({type:'closed'});channel?.close();}catch{}clearTimeout(timer);},{once:true});
  return Object.fromEntries(['fixture','connection','chunk','begin','command','parser','effect','switchState','fail','clear'].map(name=>[name,(...args)=>{try{state[name](...args);}catch{ /* Passive observation cannot change device control. */ }}]));
}
