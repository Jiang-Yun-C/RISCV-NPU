import {isTwinkleRequest,verifyTokens} from './tool-tokens.js';
import {resolveLightRequest,isNegatedLightRequest} from './light-presets.js';
import {PRESENTATION,presentReply,finishPreparation} from './presentation.js';
import {parseImport} from './demo-cache.js';
import {T25Parser} from './protocol.js';
import {attachRuntimeMonitor} from './monitor-state.js';
const monitor=attachRuntimeMonitor('monitor-link');
const $=id=>document.getElementById(id),sleep=ms=>new Promise(r=>setTimeout(r,ms));
const owner=sessionStorage.getItem('nexusrv-tool-chat-owner')||crypto.randomUUID();
sessionStorage.setItem('nexusrv-tool-chat-owner',owner);
const clearKey='nexusrv-context-clear-pending';
const welcome=$('conversation').firstElementChild.cloneNode(true);
let token,prepared,qa=[],connected=false,cursor=0,busy=false,receiveGeneration=0,latest={},liveParser=null;
let pendingContextClear=sessionStorage.getItem(clearKey)==='1';
const newLedger=()=>({schema:'model-token-tool-chat-v1',created_at:new Date().toISOString(),events:[],chunks:[],calls:[],conversations:[],is_live_inference:false});
let ledger=newLedger();
const stamp=()=>({wall:new Date().toISOString(),monotonic_ms:performance.now()});
function record(type,detail={}){ledger.events.push({...stamp(),type,...detail});$('debug').textContent=JSON.stringify(ledger.events.slice(-14),null,2);}
async function api(path,body){const r=await fetch('/api/'+path,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json','X-Console-Token':token||'','X-Console-Owner':owner},body:body===undefined?undefined:JSON.stringify(body)});const d=await r.json();if(!r.ok)throw Error(d.error||'请求失败');return d;}
function scroll(){const area=$('conversation');area.scrollTop=area.scrollHeight;}
function message(role,title,text='',source=''){
  const a=document.createElement('article');a.className='message '+role;
  const box=document.createElement('div');
  if(role!=='user'){const avatar=document.createElement('span');avatar.className='avatar';avatar.textContent=role==='tool'?'↗':'N';a.append(avatar);}
  const heading=document.createElement('b');heading.textContent=title;if(title)box.append(heading);
  if(source){const badge=document.createElement('span');badge.className='badge';badge.textContent=source;box.append(badge);}
  const p=document.createElement('p');p.textContent=text;box.append(p);a.append(box);$('conversation').append(a);scroll();return{article:a,box,p,heading};
}
function controls(){
  $('send').disabled=busy||!prepared;
  $('connection').disabled=busy;$('connection').textContent=connected?'设备已连接':'连接设备';
  $('disconnect').disabled=!connected||busy;
  $('clear-context').disabled=busy;
  $('clear-context').title=busy?'请等待当前操作完成，或先停止灯光':'清除对话与输入内容，开始新的对话';
}
async function pump(g){try{while(connected&&g===receiveGeneration){const d=await api('read?after='+cursor+'&wait=20');if(g!==receiveGeneration)return;for(const c of d.chunks){if(c.seq!==cursor+1)throw Error('串口记录不连续');cursor=c.seq;monitor.chunk(c);ledger.chunks.push({...c,observed:stamp()});if(liveParser)liveParser.feed(Uint8Array.from(atob(c.data),x=>x.charCodeAt(0)),{...stamp(),received_ns:c.received_ns});}latest=d;monitor.connection(d);if(!d.connected)throw Error(d.error||'串口已断开');}}catch(e){if(g===receiveGeneration){connected=false;monitor.connection({connected:false});record('receive_error',{message:e.message});$('connection-status').textContent='设备连接中断 · 请重新连接';controls();}}}
async function waitReady(){const end=performance.now()+10000;while(!latest.synced||latest.pending){if(!connected||performance.now()>end)throw Error('未取得板卡READY，不重发');await sleep(5);}}
async function serviceCommand(command){monitor.command(command);latest={...latest,pending:true};await api('write',{command});await waitReady();}
async function clearBoardContext(){
  // The deployed service invalidates its prefix on either :prefix setting,
  // even when the requested enabled value has not changed. Keep reuse enabled.
  await waitReady();const start=ledger.chunks.length;
  await serviceCommand(':prefix 1');
  const wire=ledger.chunks.slice(start).map(c=>atob(c.data)).join('').replace(/\r/g,'');
  if(!/^T25 CONFIG 1 prefix=0000000000000001 *$/m.test(wire))throw Error('设备尚未确认上下文清理');
  pendingContextClear=false;sessionStorage.removeItem(clearKey);
  record('device_context_cleared',{command:':prefix 1',confirmed:true});
}
async function ensureConnection(){
  if(!connected){
    const ports=await api('ports');const list=(ports.ports||[]).filter(p=>p.expected&&p.device==='COM10'&&p.serial==='0001');
    if(list.length!==1)throw Error('未找到唯一CP2102 COM10/0001');
    await api('connect',{port:'COM10',baud:115200});connected=true;cursor=0;latest={pending:true,synced:false};pump(++receiveGeneration);
    await serviceCommand('');record('explicit_chat_connection_ready');
  }else await waitReady();
  if(pendingContextClear){await clearBoardContext();$('context-status').textContent='上下文已清空，可以开始新的对话。';}
  $('connection-status').textContent='设备已就绪';controls();
}
async function clearContext(){
  if(busy)return;
  busy=true;controls();$('context-status').classList.remove('error');$('context-status').textContent='正在清空上下文…';
  pendingContextClear=true;sessionStorage.setItem(clearKey,'1');
  try{
    if(connected)await clearBoardContext();
    ledger=newLedger();liveParser=null;
    $('conversation').replaceChildren(welcome.cloneNode(true));$('prompt').value='';$('debug').textContent='';$('records').open=false;
    monitor.clear();record('context_cleared',{device:pendingContextClear?'deferred_until_connection':'confirmed'});
    $('context-status').textContent=pendingContextClear?'对话已清空。设备上下文将在下次连接时清理。':'上下文已清空，可以开始新的对话。';
    $('prompt').focus();
  }catch(e){record('context_clear_failed',{message:e.message});$('context-status').classList.add('error');$('context-status').textContent='设备尚未确认清理，对话已保留。请检查连接后重试。';}
  finally{busy=false;controls();scroll();}
}
function ordinaryCache(text){const s=text.trim().replace(/[。.!！?？]+$/u,'');if(/工控机/u.test(s)&&/做|什么|介绍|用途/u.test(s))return qa.find(e=>e.prompt.includes('工控机'));if(/传感器/u.test(s)&&/作用|介绍|什么/u.test(s))return qa.find(e=>e.prompt.includes('传感器'));if(/边缘计算/u.test(s))return qa.find(e=>e.prompt.includes('边缘计算'));if(/^(你好|向现场操作员问好|打个招呼)$/u.test(s))return qa.find(e=>e.prompt.includes('问好'));return qa.find(e=>e.prompt===text.trim());}
async function streamTool(call){
  const displayStarted=performance.now();
  const msg=message('assistant','智能助手','正在准备小星星灯光…','缓存命中');
  const rec={...stamp(),source:'PREGENERATED_VERIFIED_MODEL_TOKENS',is_live_inference:false,source_entry_id:prepared.entry_id,original_uart_sha256:prepared.original_uart_sha256,tokens:[]};ledger.conversations.push(rec);
  let result='';const dec=new TextDecoder('utf8',{fatal:true});
  for(const t of prepared.tokens){const bytes=Uint8Array.from(t.text_hex.match(/../g)||[],h=>parseInt(h,16));result+=dec.decode(bytes,{stream:true});rec.tokens.push({...stamp(),index:t.index,token_id:t.token_id,text_hex:t.text_hex});}
  result+=dec.decode();const parsed=JSON.parse(result),item=Array.isArray(parsed)&&parsed.length===1?parsed[0]:parsed;
  if(JSON.stringify(item)!==JSON.stringify(call.arguments))throw Error('调用token未形成匹配的工具参数');
  await finishPreparation(displayStarted);
  rec.presentation={kind:'REPLAY_PRESENTATION_ONLY',minimum_prepare_ms:PRESENTATION.toolPreparationMs,actual_ms:performance.now()-displayStarted};
  msg.p.textContent='准备好了，让四盏灯跟着小星星的节奏轮流闪烁。';
  rec.complete=true;record('tool_tokens_complete',{call_id:call.call_id,token_count:rec.tokens.length});return rec;
}
async function executeTool(text){
  const clicked=performance.now();const call={call_id:crypto.randomUUID(),tool:'twinkle',arguments:prepared.arguments,source_entry_id:prepared.entry_id,source_uart_sha256:prepared.original_uart_sha256};
  monitor.begin('replay_device',text);await ensureConnection();await streamTool(call);
  const msg=message('tool','小星星 · 四灯轮转','','缓存命中');msg.p.textContent='正在开始播放…';
  const progress=document.createElement('div'),bar=document.createElement('i');progress.className='progress';progress.append(bar);msg.box.append(progress);
  const leds=document.createElement('div');leds.className='led-row';const lamps={};
  for(const [index,bit] of [0,2,3,5].entries()){const l=document.createElement('span');l.className='led';const dot=document.createElement('i');l.append(dot,document.createTextNode('灯 '+(index+1)));lamps[bit]=l;leds.append(l);}msg.box.append(leds);
  const foot=document.createElement('div'),note=document.createElement('small'),stop=document.createElement('button');foot.className='tool-foot';note.textContent='进度根据设备反馈更新';stop.textContent='停止';
  stop.onclick=async()=>{stop.disabled=true;try{await api('rhythm/stop',{});record('user_stop',{call_id:call.call_id});}catch(e){record('stop_failure',{message:e.message});note.textContent='停止未完成，请检查设备连接';}};
  foot.append(note,stop);msg.box.append(foot);
  const run={...stamp(),call,source:'MODEL_TOKENS_TO_REGISTERED_PACKAGE',current_model_inference:false,states:[]};ledger.calls.push(run);let submitted=false;
  try{
    submitted=true;const start=await api('tools/invoke',call);run.effect_id=start.id;if(start.deduplicated)throw Error('此调用已经提交，不重复执行');
    while(true){
      const s=await api('rhythm/status');run.states.push({...stamp(),...s});if(s.id!==run.effect_id)throw Error('执行ID不匹配');
      monitor.effect(s);const n=s.notes_completed||0;bar.style.width=(n/42*100)+'%';
      msg.p.textContent=s.active?`正在播放 · ${n}/42 个音符`:s.status==='STOPPED_BY_USER'?'已停止 · 灯光已恢复默认状态':'播放完成 · 灯光已恢复默认状态';
      if(s.last_bank)for(const bit of[0,2,3,5])lamps[bit].classList.toggle('on',!!(s.last_bank.owned&(1<<bit))&&!!(s.last_bank.values&(1<<bit)));
      if(s.first_CPU_on_receipt_seconds!==undefined&&run.first_current_CPU_visible_ms===undefined)run.first_current_CPU_visible_ms=performance.now()-clicked;
      if(!s.active){
        if(!['PASS_RHYTHM_CPU_READBACK','STOPPED_BY_USER'].includes(s.status)||!s.released_automatic)throw Error('灯效未取得完整释放记录');
        const end=performance.now()+5000;while(cursor<(s.last_rx_seq||0)&&performance.now()<end)await sleep(5);
        if(cursor<(s.last_rx_seq||0))throw Error('原始UART记录未收齐');
        await waitReady();run.status=s.status;run.final_CPU_stores=s.CPU_stores;break;
      }
      await sleep(80);
    }
    record('tool_complete',{call_id:call.call_id,status:run.status});
  }catch(e){run.status='FAIL_PRESERVE_NO_RETRY';run.failure=e.message;monitor.fail(e.message);msg.p.textContent='播放已中断，请检查设备连接。';msg.p.classList.add('error');if(submitted)latest={...latest,pending:true,synced:false};record('tool_failure',{call_id:call.call_id,message:e.message});throw e;}
  finally{stop.disabled=true;scroll();}
}
async function realChat(text){
  monitor.begin('live',text);await ensureConnection();await serviceCommand(':stream 1');const msg=message('assistant','智能助手','','实时回复');let resolve,complete;const done=new Promise(r=>resolve=r);
  liveParser=new T25Parser(e=>{monitor.parser(e);if(e.type==='preview')msg.p.textContent=e.text;if(e.type==='result'){complete=e;if(e.text)msg.p.textContent=e.text;}if(e.type==='error')record('model_error',{message:e.message});if(e.type==='ready')resolve();});
  const command=':text 128 '+text;liveParser.expectRequest('text',command);latest={...latest,pending:true};
  try{await api('write',{command});await done;await waitReady();if(!complete?.complete||!complete.modelComplete)throw Error('模型未完整结束');ledger.conversations.push({...stamp(),source:'CURRENT_BOARD_INFERENCE',is_live_inference:true,prompt:text,result:complete});}
  finally{liveParser=null;}scroll();
}
async function executeSwitch(text,preset){
  monitor.begin('direct_device',text,preset.action);
  const msg=message('tool',preset.title,'正在连接并准备灯光…','缓存命中');
  const leds=document.createElement('div');leds.className='led-row';const lamps={};
  for(const [index,bit] of [0,2,3,5].entries()){const lamp=document.createElement('span'),dot=document.createElement('i');lamp.className='led';lamp.append(dot,document.createTextNode('灯 '+(index+1)));lamps[bit]=lamp;leds.append(lamp);}msg.box.append(leds);
  const note=document.createElement('small');note.textContent='等待设备确认';msg.box.append(note);
  const call={call_id:crypto.randomUUID(),action:preset.action};
  const run={...stamp(),call,source:'USER_QUICK_ACTION_NOT_MODEL_INFERENCE',cache:{kind:'CONTROL_INSTRUCTION',hit:true},current_model_inference:false,states:[]};ledger.calls.push(run);let submitted=false;
  try{
    await ensureConnection();submitted=true;
    const started=await api('lights/switch',call);if(started.deduplicated)throw Error('此操作已提交，不重复执行');run.effect_id=started.id;
    msg.p.textContent=preset.action==='on'?'正在打开四盏灯…':'正在关闭四盏灯…';
    const deadline=performance.now()+20000;
    while(true){
      const state=await api('lights/status?call_id='+encodeURIComponent(call.call_id));run.states.push({...stamp(),...state});
      if(state.id!==run.effect_id||state.call_id!==call.call_id||state.action!==preset.action||state.target_values!==preset.values)throw Error('灯光操作身份不匹配');
      monitor.switchState(state);
      if(!state.active){
        if(state.status!=='PASS_SWITCH_CPU_READBACK'||!state.confirmed||!state.held||state.CPU_stores!==1||state.last_bank?.values!==preset.values||state.last_bank?.owned!==45)throw Error('设备未确认目标灯光状态');
        const drained=performance.now()+5000;while(cursor<(state.last_rx_seq||0)&&performance.now()<drained)await sleep(5);
        if(cursor<(state.last_rx_seq||0))throw Error('原始设备记录未收齐');await waitReady();
        for(const bit of[0,2,3,5])lamps[bit].classList.toggle('on',!!(state.last_bank.values&(1<<bit)));
        msg.p.textContent=preset.success;note.textContent='设备反馈已确认 · 保持此设置，直到下次灯光操作';
        run.status=state.status;run.final_CPU_stores=state.CPU_stores;record('light_switch_complete',{call_id:call.call_id,action:preset.action});break;
      }
      if(performance.now()>deadline)throw Error('设备确认超时');await sleep(80);
    }
  }catch(e){run.status='FAIL_PRESERVE_NO_RETRY';run.failure=e.message;monitor.fail(e.message);msg.p.textContent='灯光操作未完成，请检查设备连接。';msg.p.classList.add('error');note.textContent='当前灯光状态尚未确认';if(submitted)latest={...latest,pending:true,synced:false};record('light_switch_failed',{message:e.message,call_id:call.call_id});throw e;}
}
async function send(text){
  text=text.trim();if(!text||busy||!prepared)return;busy=true;controls();$('prompt').value='';$('context-status').textContent='';message('user','',text);record('user_chat',{text});
  try{
    const preset=resolveLightRequest(text);
    if(preset)await executeSwitch(text,preset);
    else if(isNegatedLightRequest(text))message('assistant','智能助手','好的，保持当前灯光设置。');
    else if(isTwinkleRequest(text))await executeTool(text);
    else{const hit=ordinaryCache(text);if(hit){
      monitor.begin('replay',text);const msg=message('assistant','智能助手','…','缓存命中');
      const rec={...stamp(),source:'PREGENERATED_REAL_BOARD_ANSWER',entry_id:hit.id,prompt:text,text:hit.text,is_live_inference:false,presentation:{kind:'REPLAY_PRESENTATION_ONLY',complete:false}};
      ledger.conversations.push(rec);const started=performance.now();
      const timing=await presentReply(hit.text,visible=>{msg.p.textContent=visible;scroll();});
      Object.assign(rec.presentation,{complete:true,initial_ms:timing.initial,interval_ms:timing.interval,planned_ms:timing.plannedMs,actual_ms:performance.now()-started});
      record('replay_presentation_complete',{entry_id:hit.id,display_ms:rec.presentation.actual_ms});
    }else await realChat(text);}
  }catch(e){monitor.fail(e.message);message('system','操作未完成','请检查设备连接后再试。详细信息可在运行记录中查看。');record('request_failure',{message:e.message});}
  finally{busy=false;controls();scroll();}
}
$('composer').onsubmit=e=>{e.preventDefault();send($('prompt').value);};
$('prompt').onkeydown=e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.isComposing){e.preventDefault();send($('prompt').value);}};
$('clear-context').onclick=clearContext;
$('connection').onclick=async()=>{if(busy)return;busy=true;controls();try{await ensureConnection();}catch(e){message('system','连接未完成','请检查设备是否已接好，再重新连接。');record('connection_failure',{message:e.message});}finally{busy=false;controls();}};
$('disconnect').onclick=async()=>{if(busy)return;++receiveGeneration;try{await api('disconnect',{});}finally{connected=false;monitor.connection({connected:false});latest={};$('connection-status').textContent='设备已断开';controls();}};
$('export').onclick=()=>{const blob=new Blob([JSON.stringify(ledger,null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='nexusrv-session-'+Date.now()+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),0);};
try{
  const boot=await api('bootstrap');token=boot.token;monitor.fixture(boot.test_fixture);
  if(boot.test_fixture){const mark=document.createElement('p');mark.className='fixture-banner';mark.textContent='模拟设备验证';document.body.append(mark);}
  prepared=await(await fetch('prepared-tool-tokens.json')).json();const doc=await(await fetch('rhythm-model.json')).json();
  const verified=await parseImport(JSON.stringify({schema:'nexusrv-demo-cache',version:1,exportedAt:doc.entry.capturedAt,entries:[doc.entry]}));
  if(verified.length!==1||prepared.entry_id!==doc.entry.id||prepared.original_uart_sha256!==doc.entry.uart.sha256||!prepared.verified_eos||prepared.is_live_inference!==false)throw Error('工具token来源未核验');
  const text=new TextDecoder('utf8',{fatal:true}).decode(Uint8Array.from(prepared.tokens.flatMap(t=>(t.text_hex.match(/../g)||[]).map(h=>parseInt(h,16)))));
  if(text!==doc.entry.text||prepared.tokens.length!==19||prepared.tokens.some((t,i)=>t.index!==i+1))throw Error('工具token序列不完整');
  verifyTokens(prepared,doc.entry);qa=await parseImport(await(await fetch('prepared-qa.json')).text());record('prepared_tokens_ready',{source:prepared.source,entry_id:prepared.entry_id,token_count:prepared.tokens.length});
}catch(e){prepared=null;message('system','准备未完成','演示内容暂时无法读取，请重新打开展示台。');record('initialization_failure',{message:e.message});}
controls();
