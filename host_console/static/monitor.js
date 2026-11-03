// This page has no API client and no device-control capabilities. It only asks
// the originating conversation tab for a bounded, in-memory observation snapshot.
const $=id=>document.getElementById(id),source=new URLSearchParams(location.search).get('source');
const validSource=/^[0-9a-f-]{36}$/i.test(source||'');
let channel=null,lastSeen=0,closed=false,paused=false,latest=null,displayed=null,filter='all',eventSignature='',lastCacheKey='';
const shortTime=value=>value?new Date(value).toLocaleTimeString('zh-CN',{hour12:false}):'—';
const count=value=>Number.isSafeInteger(value)&&value>=0?value.toLocaleString('zh-CN'):'—';
const stages={prefill:'预填充',decode:'逐步生成',validating:'校验结果',executing:'执行动作'};
function text(id,value){$(id).textContent=value;}
function accepted(value){return value?.schema==='nexusrv-runtime-v1'&&value.sourceId===source&&Number.isSafeInteger(value.revision)&&value.connection&&value.transport&&value.task&&value.cpu&&value.npu&&Array.isArray(value.events)&&value.events.length<=48;}
function freshness(){
  const fresh=!!latest&&!closed&&Date.now()-lastSeen<7000;
  document.body.classList.toggle('stale',!fresh||paused);
  $('sync-status').classList.toggle('fresh',fresh&&!paused);
  const label=paused?'显示已暂停':closed?'对话页已关闭':fresh?'会话已同步':latest?'同步已暂停':'等待会话';
  $('sync-status').lastChild.textContent=label;
  if(displayed)text('as-of',(paused?'显示截至 ':!fresh?'数据截至 ':'会话同步 ')+shortTime(displayed.publishedAt));
  if(displayed&&!fresh){text('cpu-status','当前状态未知');text('npu-status','当前状态未知');text('task-state','历史状态');$('task-state').className='state-label';text('phase-note','仅保留最后一次同步记录，设备当前状态未知。');}
  if(!fresh||paused){text('lamp-note',displayed?.leds?'历史读回 · 当前灯光状态未知':'尚无灯光读回 · 未知状态');}
  else if(displayed)text('lamp-note',displayed.leds?'设备最近读回 · '+shortTime(displayed.leds.observedAt)+' · 非光学测量':'尚无灯光读回 · 未知状态');
}
function events(values){
  const signature=filter+JSON.stringify(values);if(signature===eventSignature)return;eventSignature=signature;
  const opened=new Set([...$('events').querySelectorAll('details[open]')].map(d=>d.dataset.key));
  const selected=values.filter(e=>filter==='all'||e.source===filter).slice().reverse(),fragment=document.createDocumentFragment();
  if(!selected.length){const empty=document.createElement('li');empty.className='event-empty';empty.textContent='暂无对应来源的事件。';fragment.append(empty);}
  for(const e of selected){
    const li=document.createElement('li'),row=document.createElement(e.detail?'summary':'div'),time=document.createElement('time'),label=document.createElement('span'),badge=document.createElement('span');
    time.textContent=shortTime(e.at);time.dateTime=new Date(e.at).toISOString();label.textContent=e.title;badge.className='event-source '+e.source;badge.textContent=e.source==='device'?'设备回执':'主机事件';row.append(time,label,badge);
    if(e.detail){const details=document.createElement('details'),raw=document.createElement('pre');details.dataset.key=e.at+':'+e.title;details.open=opened.has(details.dataset.key);raw.textContent=JSON.stringify(e.detail,null,2);details.append(row,raw);li.append(details);}else li.append(row);
    fragment.append(li);
  }
  $('events').replaceChildren(fragment);
}
function chart(transport){
  const now=Math.floor(Date.now()/1000)*1000,bins=new Map((transport.bins||[]).map(b=>[b.at,b.bytes]));
  const values=Array.from({length:60},(_,i)=>bins.get(now-(59-i)*1000)||0),peak=Math.max(...values,0),fragment=document.createDocumentFragment();
  for(let i=0;i<values.length;i++){const bar=document.createElement('i');bar.className=values[i]?'':'zero';bar.style.height=(peak?values[i]/peak*100:0)+'%';bar.title=shortTime(now-(59-i)*1000)+' · '+values[i]+' B';fragment.append(bar);}
  $('rx-chart').replaceChildren(fragment);$('no-activity').hidden=peak>0;
  $('rx-chart').setAttribute('aria-label','最近60秒实际设备接收数据，峰值每秒 '+peak+' 字节');
  text('last-rx',transport.lastRxAt?'最近 '+shortTime(transport.lastRxAt):'尚未接收');
  const bytes=transport.bytes||0;text('rx-bytes',bytes>=1024?(bytes/1024).toFixed(1):String(bytes));text('rx-unit',bytes>=1024?'KiB':'B');text('rx-note','当前会话 · '+(transport.chunks||0)+' 个接收块');
}
function cacheFeature(task){
  const cached=['replay','replay_device','direct_device'].includes(task.kind),feature=$('cache-feature');
  feature.hidden=!cached;
  if(!cached){feature.classList.remove('cache-hit');lastCacheKey='';return;}
  text('cache-note',task.kind==='direct_device'?'命中已保存指令，操作结果由当前设备确认。':task.kind==='replay_device'?'读取已保存计划，操作进度来自当前设备。':'直接读取已保存内容，呈现回复。');
  text('cache-destination',['replay_device','direct_device'].includes(task.kind)?'确认':'呈现');text('cache-time','记录于 '+shortTime(task.startedAt));
  const key=task.kind+':'+task.startedAt;
  if(key!==lastCacheKey){lastCacheKey=key;feature.classList.remove('cache-hit');
    if(Date.now()-task.startedAt<5000){void feature.offsetWidth;feature.classList.add('cache-hit');}
  }
}
function render(state){
  displayed=state;const t=state.task,c=state.connection;cacheFeature(t);
  $('fixture').hidden=!state.fixture;$('export-monitor').disabled=false;
  text('mode',({idle:'等待任务',replay:'缓存命中',replay_device:'缓存命中',direct_device:'缓存命中',live:'设备实时推理'})[t.kind]||'等待任务');
  text('connection',!c.connected?'设备未连接':c.pending?'设备已连接 · 等待回执':c.synced?'设备已连接 · 服务就绪':'设备已连接 · 等待同步');
  text('cpu-status',state.cpu.label);text('npu-status',state.npu.label);
  $('host-node').classList.toggle('observed',t.kind!=='idle');$('cpu-node').classList.toggle('observed',state.cpu.observed&&c.connected);$('npu-node').classList.toggle('observed',state.npu.observed&&c.connected&&t.kind==='live');
  text('task-label',t.label);text('task-state',({idle:'等待开始',pending:'等待确认',running:'执行中',complete:'已完成',stopped:'已停止',error:'需检查'})[t.status]||'等待开始');$('task-state').className='state-label '+t.status;
  let phase='等待回执',note='连接设备后，在这里查看执行过程。';
  if(t.kind==='replay'){phase='缓存命中';note='回复来自已保存的内容，本次未触发实时推理。';}
  else if(t.kind==='replay_device'){phase=t.status==='complete'?'播放完成':t.status==='stopped'?'播放已停止':t.notes>0?'灯光执行':'准备灯光';note='已读取缓存内容；执行进度来自当前设备回执。';}
  else if(t.kind==='direct_device'){phase=t.status==='complete'?(t.action==='on'?'四灯保持常亮':'四灯保持熄灭'):(t.action==='on'?'正在开灯':'正在关灯');note='收到设备确认后保持当前设置。';}
  else if(t.kind==='live'){phase=t.status==='complete'?'推理已完成':stages[t.stage]||'等待设备接收';note=t.status==='complete'?'完整回复与结束记录已核对。':'推理阶段由设备报告，算子占用率尚未采集。';}
  if(t.status==='error'){phase='操作未完成';note='详细原因保留在下方事件记录中。';}
  $('phase').replaceChildren(document.createTextNode(phase));const cursor=document.createElement('span');cursor.textContent='_';$('phase').append(cursor);text('phase-note',note);
  const switching=t.kind==='direct_device';text('progress-label',switching?'目标灯光确认':'灯光执行进度');text('note-count',switching?(t.status==='complete'?'4 / 4':'— / 4'):count(t.notes)+' / 42');$('progress-fill').style.width=(switching?(t.status==='complete'?100:0):t.notes!==null?Math.max(0,Math.min(42,t.notes))/42*100:0)+'%';
  for(const lamp of $('lamps').children){const bit=Number(lamp.dataset.bit),known=!!state.leds&&c.connected;lamp.classList.toggle('known',known);lamp.classList.toggle('on',known&&!!(state.leds.owned&(1<<bit))&&!!(state.leds.values&(1<<bit)));}
  text('generated',t.kind==='live'?count(t.generated):'—');text('generated-note',t.kind==='live'?(t.status==='complete'?'完整请求已确认':'已接收 · 等待完整结束'):'本次未进行实时推理');text('ce-calls',t.kind==='live'?count(t.ceCalls):'—');text('stores',count(t.stores));
  chart(state.transport);events(state.events);freshness();
}
function request(){try{channel?.postMessage({type:'request'});}catch{}freshness();}
if(validSource){try{channel=new BroadcastChannel('nexusrv-runtime-'+source);channel.onmessage=e=>{if(e.data?.type==='closed'){closed=true;freshness();return;}if(e.data?.type!=='snapshot'||!accepted(e.data.value))return;latest=e.data.value;lastSeen=Date.now();closed=false;if(!paused)render(latest);};request();}catch{text('as-of','当前浏览器不支持会话监控');$('session-hint').hidden=false;}}
else $('session-hint').hidden=false;
setInterval(request,2000);setInterval(freshness,1000);
$('follow').onclick=()=>{paused=!paused;document.body.classList.toggle('paused',paused);$('follow').textContent=paused?'继续跟随':'暂停跟随';$('follow').setAttribute('aria-pressed',String(paused));if(!paused&&latest)render(latest);else freshness();};
document.querySelectorAll('[data-filter]').forEach(button=>button.onclick=()=>{filter=button.dataset.filter;document.querySelectorAll('[data-filter]').forEach(b=>{b.classList.toggle('selected',b===button);b.setAttribute('aria-pressed',String(b===button));});if(displayed)events(displayed.events);});
$('export-monitor').onclick=()=>{if(!displayed)return;const blob=new Blob([JSON.stringify({...displayed,monitor_exported_at:new Date().toISOString(),view_paused:paused},null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='nexusrv-runtime-'+Date.now()+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
$('fullscreen').onclick=async()=>{try{if(document.fullscreenElement)await document.exitFullscreen();else await document.documentElement.requestFullscreen();}catch{text('as-of','当前窗口不支持全屏，请使用浏览器全屏功能。');}};
addEventListener('fullscreenchange',()=>{$('fullscreen').textContent=document.fullscreenElement?'退出全屏':'全屏展示';});
$('return-chat').onclick=()=>{window.close();$('return-chat').textContent='请切回对话标签页';};
addEventListener('pagehide',()=>channel?.close(),{once:true});
