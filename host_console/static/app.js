import { T25Parser, commandFor, cancelCommand, CLOCK, LED_CHANNELS, LED_BANK_MASK, validLedMask, ledBankCommand } from './protocol.js';
import { CACHE_LIMITS, createFromRun, parseImport, exportCache, restoreCache, saveCache, findExact, mergeEntries } from './demo-cache.js';
const $ = id => document.getElementById(id);
const enc = new TextEncoder();
const serialize = value => JSON.stringify(value, (_, v) => typeof v === 'bigint' ? v.toString() : v, 2);
const clone = value => JSON.parse(serialize(value));
const owner = sessionStorage.getItem('led-console-owner') || crypto.randomUUID();
sessionStorage.setItem('led-console-owner', owner);
let token, baseline, connected = false, ready = false, polling = 0, cursor = 0, pending = null, parser;
let mode = 'text', replay = false, current = null, recorder = null, display = null;
let capabilities = {}, ledCapabilities = {}, cancelSent = false, attachedBusy = false;
let bankCapabilities = null, targetMask = 1;
let preparing = false, writing = false, pendingCompletion = null, boardHalted = false;
let cancelWriting = false, cancelRun = null;
let currentIdentity = null, prefixEnabled = null, activeDraftSnapshot = null;
let streamConfirmed = false, streamRevision = 0, warmupRevision = 0;
let warmupState = { status:'unknown', detail:'尚未确认聊天前缀' };
let rhythmDoc = null, rhythmBusy = false;
let cacheEntries = [], cachePlayback = null, cacheTimer = null, cacheGeneration = 0;
let cacheTail = Promise.resolve(), cacheJobs = 0;
let history = []; try { history = JSON.parse(localStorage.getItem('led-console-v3-history') || '[]'); } catch { /* corrupt local cache does not affect UART */ }
const ledger = { schema: 'nexusrv-led-console/3', hostVersion: 'host-chat-rhythm-20261102-v1', captureMode: 'external_phone', videoEvidenceAttached: false, source: 'live', createdAt: new Date().toISOString(), browserClock: { clock: 'performance.now milliseconds', timeOrigin: performance.timeOrigin }, events: [], chunks: [], runs: [], observations: [], errors: [], cacheEvents:[], cachePresentations:[] };
function stamp() { return { monotonic_ms: performance.now(), wall: new Date().toISOString() }; }
function event(type, detail = {}) { const e = { ...stamp(), type, ...clone(detail) }; ledger.events.push(e); const run=pending || cancelRun; if (run) run.events.push(e); return e; }
function cancellationPending() { return cancelWriting || !!cancelRun; }
function notice(message, error = false) { $('notice').textContent = message; $('notice').classList.toggle('error', error); }
// Presentation only: every phase is assigned at the same actual event boundary
// as the textual result. Color/icon never grants completion authority.
function visualState(target, phase) {
  $(target + '-card').dataset.phase = phase;
  if (target === 'receipt') {
    const icon = { success: 'success', rejected: 'rejected', cancelled:'rejected', error: 'error',
      waiting: 'waiting', pending: 'waiting', timeout: 'waiting', chat: 'chat', direct: 'chat', idle: 'idle' }[phase] || 'idle';
    $('receipt-symbol').setAttribute('href', '#status-' + icon);
  }
}
function modelText(text, actual = true) {
  $('model-output').textContent = text;
  $('model-output').dataset.content = actual ? 'output' : 'placeholder';
  const length = [...text].length;
  $('model-output').dataset.size = length <= 18 ? 'short' : length <= 64 ? 'medium' : 'long';
}
function setWarmup(status, detail, extra = {}, invalidate = true) {
  if (invalidate && (status === 'unknown' || status === 'invalid')) ++warmupRevision;
  warmupState = { status, detail, ...extra };
  $('warmup-status').textContent = detail;
  $('warmup-status').dataset.status = status;
}
function invalidateStream(reason) {
  streamConfirmed = false; ++streamRevision;
  $('stream-confirmation').textContent = '流式待确认';
  event('stream_confirmation_invalidated', { reason, revision:streamRevision });
}
function confirmPreparedState(run) {
  // Capability advertisements never establish the current setting. Newer
  // CONFIG receipts can confirm it; legacy firmware is confirmed only after
  // this run's real stream, complete result, READY and HTTP write ACK agree.
  const proven = run?.status === 'complete' && !run.errors.length && !run.timedOut && !run.cancelRequested &&
    connected && ready && !boardHalted && !pending && !writing && !cancellationPending() &&
    run.latency.ready_ms !== undefined && run.latency.bridge_write_confirmed_ms !== undefined;
  if (!proven) return;
  if (run.command === ':stream 1' && run.streamConfiguration === 1 && run.streamRevision === streamRevision) {
    streamConfirmed = true; $('stream-confirmation').textContent = '本连接流式已确认';
    event('stream_confirmation_ready', { runId:run.id, revision:streamRevision });
  }
  if (['text','action'].includes(run.kind) && run.streamRevision === streamRevision &&
      run.streamBeginSession === run.session && run.streamEnded && run.result?.complete && run.result.modelComplete &&
      run.result.request?.sessionHex === run.session) {
    streamConfirmed = true; $('stream-confirmation').textContent = '本连接流式已确认';
    event('stream_confirmation_ready', { runId:run.id, revision:streamRevision, evidence:'completed_stream' });
  }
  const prefix = run.result?.prefix;
  if (run.kind === 'text' && run.warmupRevision === warmupRevision && prefixEnabled !== false &&
      run.result?.complete && run.result.modelComplete && prefix?.tokens > 0 && (prefix.hit === 1 || prefix.captured === 1)) {
    setWarmup('ready', `聊天已预热 · ${prefix.tokens} 个前缀 token 已确认`,
      { session:run.session, tokens:prefix.tokens, confirmedAt:new Date().toISOString() });
  }
}
function cacheStatus(message, error = false) {
  $('demo-cache-status').textContent = message;
  $('demo-cache-status').classList.toggle('error', error);
}
function cacheEvent(type, detail = {}) {
  const e = { ...stamp(), type, presentationSource:'prepared_cache', isLiveInference:false, ...clone(detail) };
  ledger.cacheEvents.push(e); return e;
}
function matchCache(prompt = $('prompt').value, maximum = Number($('max-new').value)) {
  try { return findExact(cacheEntries, prompt, maximum, currentIdentity); }
  catch { return { entry:null, status:'miss', reason:'问题或生成上限无效' }; }
}
function canSaveAnswer(run = current) {
  return !!run && run.kind === 'text' && run.source === 'live' && run.requestSource === 'board_model' &&
    run.status === 'complete' && !run.warmup && run.purpose !== 'warmup' && !run.preparation &&
    !run.cancelRequested && !run.timedOut && !run.errors?.length && run.result?.complete === true &&
    run.result.modelComplete === true && run.result.metrics?.stop === 1 && !run.result.action;
}
function cacheSourceLabel(entry) {
  return entry.source === 'synthetic_fixture' ? '模拟夹具 · 非实板回答' :
    entry.source === 'historical_import' ? '导入历史 · 非当前推理' : '本机预生成 · 非当前推理';
}
function renderCacheList() {
  $('demo-cache-list').replaceChildren();
  $('prepared-questions').replaceChildren();
  $('prepared-questions-label').hidden = !cacheEntries.length;
  if (!cacheEntries.length) {
    const empty = document.createElement('p'); empty.className = 'muted'; empty.textContent = '问答列表为空；没有预置模型答案。';
    $('demo-cache-list').append(empty);
  }
  for (const entry of cacheEntries) {
    const quick = document.createElement('button'); quick.className = 'prepared-question';
    quick.dataset.preparedEntry = entry.id; quick.textContent = entry.prompt;
    quick.title = `${cacheSourceLabel(entry)} · 点击展示已有回答`;
    quick.onclick = () => {if(!rhythmBusy)playCached(entry);}; $('prepared-questions').append(quick);
    const row = document.createElement('div'); row.className = 'cache-item';
    const description = document.createElement('div'); description.className = 'cache-item-title'; description.textContent = entry.prompt;
    const info = document.createElement('small'); info.className = 'cache-item-info';
    info.textContent = `${cacheSourceLabel(entry)} · ${entry.maxNewTokens} token 上限 · ${entry.capturedAt}`;
    description.append(info);
    const controls = document.createElement('div'); controls.className = 'cache-item-actions';
    const play = document.createElement('button'); play.textContent = '播放'; play.onclick = () => playCached(entry);
    const fill = document.createElement('button'); fill.textContent = '填入'; fill.onclick = () => {
      if (replay || ((pending || preparing || writing || cancellationPending()) && mode !== 'text')) return cacheStatus('请在当前操作结束后切换普通对话，再填入这道问题。', true);
      if (mode !== 'text') showMode('text');
      $('prompt').value = entry.prompt; $('max-new').value = String(entry.maxNewTokens); paintControls();
      cacheStatus('问题和原生成上限已填入草稿；尚未发送。');
    };
    const remove = document.createElement('button'); remove.textContent = '删除'; remove.onclick = () => removeCached(entry.id);
    controls.append(play, fill, remove); row.append(description, controls); $('demo-cache-list').append(row);
  }
  paintControls();
}
async function changeCache(transform) {
  cacheJobs++; paintControls();
  const job = cacheTail.then(async () => {
    const next = await transform(cacheEntries);
    const saved = await saveCache(next, localStorage);
    cacheEntries = saved; renderCacheList(); return saved;
  });
  cacheTail = job.catch(() => {});
  try { return await job; } finally { cacheJobs--; paintControls(); }
}
async function removeCached(id) {
  try {
    await changeCache(entries => entries.filter(entry => entry.id !== id));
    if (cachePlayback?.entryId === id) stopCachePlayback();
    cacheEvent('cache_deleted', { entryId:id }); cacheStatus('该问答已删除。');
  } catch (e) { cacheStatus('删除未保存：' + e.message, true); }
}
function stopCachePlayback() {
  ++cacheGeneration;
  if (cacheTimer !== null) clearTimeout(cacheTimer);
  cacheTimer = null;
  if (cachePlayback?.state === 'playing') {
    cachePlayback.state = 'stopped'; cachePlayback.stoppedAt = stamp();
    cacheEvent('cache_playback_stopped', { entryId:cachePlayback.entryId, displayedCharacters:cachePlayback.cursor });
  }
  paintControls();
}
function showFullCache() {
  if (!cachePlayback) return;
  stopCachePlayback();
  cachePlayback.cursor = cachePlayback.characters.length; cachePlayback.state = 'complete';
  $('demo-cache-output').textContent = cachePlayback.characters.join('');
  cacheEvent('cache_full_text', { entryId:cachePlayback.entryId }); paintControls();
}
function showBoardOutput() {
  stopCachePlayback();
  $('live-model-view').hidden = false; $('cache-model-view').hidden = true;
  $('model-card').dataset.presentation = 'live'; $('metrics-source-note').hidden = true;
}
function playCached(entry) {
  const identity = findExact([entry], entry.prompt, entry.maxNewTokens, currentIdentity);
  stopCachePlayback();
  const generation = cacheGeneration, characters = [...entry.text];
  const requestedMode = $('cache-playback-mode').value;
  const playbackMode = ['instant','fast','typewriter'].includes(requestedMode) ? requestedMode : 'instant';
  const boundary = characters.findIndex(character => /[。！？!?\n]/u.test(character));
  const firstCount = playbackMode === 'instant' ? characters.length : playbackMode === 'fast' ?
    Math.min(characters.length, boundary >= 0 ? Math.min(boundary + 1,48) : 24) : Math.min(1,characters.length);
  const interval = playbackMode === 'typewriter' ? 45 : 60;
  const batchSize = playbackMode === 'fast' ? Math.max(1,Math.ceil((characters.length - firstCount) / 8)) : 1;
  cachePlayback = { entryId:entry.id, source:entry.source, capturedAt:entry.capturedAt, sourceRunId:entry.sourceRunId,
    prompt:entry.prompt, maxNewTokens:entry.maxNewTokens, characters, cursor:firstCount, state:'playing', playbackMode };
  $('live-model-view').hidden = true; $('cache-model-view').hidden = false;
  $('model-card').dataset.presentation = 'cache'; $('metrics-source-note').hidden = false;
  const identityNote = identity.status === 'identity_mismatch' ? '；与当前板卡身份不同 · 仅显式历史展示' :
    identity.status === 'unverified_identity' ? '；采集或当前身份未完整核验' : '；身份记录匹配，不代表本次推理';
  $('demo-cache-source').textContent = `${cacheSourceLabel(entry)}\n原始采集：${entry.capturedAt}${identityNote}`;
  $('demo-cache-prompt').textContent = `问题：${entry.prompt}\n原生成上限：${entry.maxNewTokens} token`;
  $('demo-cache-output').textContent = characters.slice(0, cachePlayback.cursor).join('');
  const presentation = { ...stamp(), entryId:entry.id, prompt:entry.prompt, text:entry.text, source:entry.source,
    capturedAt:entry.capturedAt, sourceRunId:entry.sourceRunId, observedIdentity:entry.observedIdentity,
    kind:'cache_playback', isLiveInference:false, playbackMode, interval_ms:playbackMode === 'instant' ? 0 : interval,
    first_batch_characters:firstCount, batch_characters:batchSize, planned_duration_ms:playbackMode === 'instant' ? 0 : Math.ceil((characters.length-firstCount)/batchSize)*interval };
  ledger.cachePresentations.push(presentation);
  cacheEvent('cache_playback_started', { entryId:entry.id, source:entry.source, capturedAt:entry.capturedAt });
  function advance() {
    if (generation !== cacheGeneration || cachePlayback?.entryId !== entry.id || cachePlayback.state !== 'playing') return;
    if (cachePlayback.cursor < characters.length) {
      cachePlayback.cursor = Math.min(characters.length,cachePlayback.cursor + batchSize);
      $('demo-cache-output').textContent = characters.slice(0,cachePlayback.cursor).join('');
    }
    if (cachePlayback.cursor >= characters.length) { cachePlayback.state = 'complete'; cacheTimer = null; paintControls(); }
    else cacheTimer = setTimeout(advance, interval);
  }
  if (cachePlayback.cursor >= characters.length) cachePlayback.state = 'complete';
  else cacheTimer = setTimeout(advance, interval);
  cacheStatus(playbackMode === 'instant' ? '已有回答已完整显示；来源与原采集时间见回答卡片。' : '正在展示已有回答；来源与原采集时间见回答卡片。'); paintControls();
  $('model-card').scrollIntoView?.({ block:'nearest' });
}
function latency(run, name, element, observed = performance.now()) {
  if (!run || run.latency[name] !== undefined) return;
  const value = Math.max(0, observed - run.interactionStarted_ms);
  run.latency[name] = value;
  if (element) $(element).textContent = (value / 1000).toFixed(3) + ' s';
}
const targetNames = mask => LED_CHANNELS.filter(channel => mask & (1 << channel.bit)).map(channel => channel.label).join('、');
function resetTargets() {
  targetMask = 1;
  document.querySelectorAll('[data-led-bit]').forEach(input => { input.checked = Number(input.dataset.ledBit) === 0; });
}
function clearRegister() {
  $('register-value').textContent = '未知'; $('bulb').setAttribute('class','');
  for (const channel of LED_CHANNELS) $('bank-state-' + channel.bit).textContent = '未读回';
  $('single-register').hidden = !!bankCapabilities; $('bank-states').hidden = !bankCapabilities;
}
function beginPresentation(kind, interaction, selected = targetMask) {
  const direct = kind === 'direct';
  if (!direct) { stopCachePlayback(); showBoardOutput(); }
  visualState('model', 'waiting'); visualState('receipt', kind === 'text' ? 'chat' : 'waiting');
  modelText(direct ? '正在发送控制命令' : '收到，正在发送…', false);
  $('model-status').textContent = '展示台已收到 · 等待板端';
  $('model-source').textContent = direct ? targetNames(selected) + ' · 直接控制，不经过模型' : '界面即时反馈 · 等待模型正文';
  $('model-title').textContent = direct ? '指令直达 CPU' : 'FPGA 真实生成';
  $('action-status').textContent = kind === 'text' ? '普通对话' : '等待实际回执';
  $('action-detail').textContent = direct ? '直接命令已选择，CPU 读回后才显示状态。' : kind === 'text' ? '本请求未要求 LED 动作。' : 'TOKEN、JSON 预览和 END 均不代表执行成功。';
  $('token-count').textContent = direct ? '不适用' : '0';
  for (const id of ['first-token','decode-time','first-visible','action-latency','writes']) $(id).textContent = '—';
  $('eos').textContent = direct ? '不适用 · 直接控制' : '待确认';
  $('session-label').textContent = direct ? '直接命令' : '等待 REQUEST';
  clearRegister();
  $('physical-status').textContent = '尚未确认'; $('last-event').textContent = '展示台已收到操作';
  interaction.uiFeedback_ms = performance.now() - interaction.started_ms;
  $('ui-feedback').textContent = interaction.uiFeedback_ms.toFixed(1) + ' ms';
  event('ui_acknowledgment', { kind, latency_ms: interaction.uiFeedback_ms, source:'local_ui', modelOutput:false });
}
function paintControls() {
  const targetReady = validLedMask(targetMask) && (bankCapabilities || targetMask === 1);
  const liveBlocked = rhythmBusy || replay || !connected || !ready || boardHalted || !!pending || preparing || writing || cancellationPending();
  const demoEnabled = mode === 'text' && $('demo-cache-enabled').checked;
  const cacheHit = demoEnabled ? matchCache() : null;
  const cacheSend = demoEnabled && (cacheHit?.entry || !connected);
  $('connection-label').textContent = connected ? boardHalted ? '已连接 · 板端停止' : cancellationPending() ? '已连接 · 等待取消结论' : ready ? '已连接 · READY' : '已连接 · 等待 READY' : '未连接';
  $('connect-button').disabled = connected || !!pending || preparing || writing || cancellationPending() || replay;
  $('disconnect-button').disabled = !connected || rhythmBusy;
  $('sync-button').disabled = !connected || !!pending || preparing || writing || cancellationPending() || boardHalted || attachedBusy || replay;
  $('send-button').disabled = replay || mode === 'direct' || (!cacheSend && (liveBlocked || (mode === 'action' ? !ledCapabilities.action || !targetReady : !capabilities.textMax)));
  $('send-button').textContent = isRhythmChat() ? '对话并播放小星星 →' : demoEnabled && cacheHit?.entry ? '播放缓存回答 →' : demoEnabled && !connected ? '查找演示缓存 →' : '发送给 FPGA →';
  $('abort-button').disabled = !pending || !pending.session || !capabilities.cancel || cancelSent || !connected || boardHalted || !['action', 'text'].includes(pending.kind);
  for (const id of ['mode-action','mode-text','mode-direct','ensure-stream']) $(id).disabled = !!pending || preparing || writing || cancellationPending() || replay;
  // Editing is local: the command already in flight uses its captured snapshot.
  $('prompt').disabled = replay || mode === 'direct';
  $('max-new').disabled = replay;
  document.querySelectorAll('[data-example]').forEach(b => b.disabled = replay);
  document.querySelectorAll('[data-token-limit]').forEach(b => {
    b.disabled = replay;
    b.classList.toggle('selected', Number(b.dataset.tokenLimit) === Number($('max-new').value));
    b.setAttribute('aria-pressed', String(Number(b.dataset.tokenLimit) === Number($('max-new').value)));
  });
  document.querySelectorAll('[data-direct]').forEach(b => b.disabled = replay || !connected || !ready || boardHalted || !!pending || preparing || writing || cancellationPending() || !ledCapabilities.direct || (b.dataset.direct !== ':led?' && !targetReady) || (b.dataset.direct === ':ledauto' && !bankCapabilities));
  document.querySelectorAll('[data-control]').forEach(b => b.disabled = replay || !connected || !ready || boardHalted || !!pending || preparing || writing || cancellationPending() || !capabilities.stream);
  document.querySelectorAll('[data-observe]').forEach(b => b.disabled = replay || !current || !['action','text','direct'].includes(current.kind));
  document.querySelectorAll('[data-led-bit]').forEach(input => {
    input.disabled = replay || !!pending || preparing || writing || cancellationPending() || mode === 'text' || !connected || (!bankCapabilities && Number(input.dataset.ledBit) !== 0);
  });
  $('target-capability').textContent = !connected ? '连接后核对可用灯' : bankCapabilities ? '四灯独立通道已声明' : '当前仅开放 LED0';
  $('target-summary').textContent = validLedMask(targetMask) ? '仅对 ' + targetNames(targetMask) + ' 执行开 / 关' : '请选择至少一个目标灯';
  $('chat-warmup').disabled = liveBlocked || mode !== 'text' || warmupState.status === 'ready' || !capabilities.stream || !capabilities.textMax || !capabilities.prefix;
  $('chat-warmup').textContent = warmupState.status === 'ready' ? '聊天已预热' : prefixEnabled === false ? '启用并预热聊天' : '聊天预热';
  $('demo-cache-generate').disabled = liveBlocked || mode !== 'text' || !capabilities.stream || !capabilities.textMax || !!cacheJobs;
  $('demo-cache-save').disabled = replay || !!pending || preparing || writing || cancellationPending() || !!cacheJobs || !canSaveAnswer();
  $('demo-cache-export').disabled = !cacheEntries.length || !!cacheJobs;
  $('demo-cache-import').disabled = !!cacheJobs;$('demo-cache-load-prepared').disabled = !!cacheJobs;
  $('demo-cache-now').disabled = !cachePlayback || cachePlayback.state === 'complete';
  $('demo-cache-stop').disabled = cachePlayback?.state !== 'playing';
  $('demo-cache-summary').textContent = cachePlayback?.state === 'playing' ? '缓存播放中 · 非当前推理' :
    `${$('demo-cache-enabled').checked ? '匹配缓存已开启' : '匹配缓存关闭'} · ${cacheEntries.length} 条 · 非当前推理`;
  $('active-request-label').hidden = !activeDraftSnapshot;
  if (activeDraftSnapshot) {
    const label = activeDraftSnapshot.purpose === 'warmup' ? '预热中' : '当前已提交';
    const summary = `${label}：${activeDraftSnapshot.prompt}${activeDraftSnapshot.kind === 'text' ? `（上限 ${activeDraftSnapshot.maximum} token）` : ''}；上方可编辑下一条草稿，不会自动发送。`;
    $('active-request-label').textContent = summary; $('active-request-label').title = summary;
  }
}
function showMode(next) {
  mode = next; $('input-card').dataset.mode = next;
  for (const name of ['action','text','direct']) { $('mode-' + name).classList.toggle('selected', next === name); $('mode-' + name).setAttribute('aria-pressed', String(next === name)); }
  $('model-input').hidden = next === 'direct'; $('direct-input').hidden = next !== 'direct';
  $('led-targets').hidden = next === 'text';
  for (const id of ['send-button','send-hint','abort-button']) $(id).hidden = next === 'direct';
  $('input-title').textContent = next === 'direct' ? '直接控灯' : next === 'text' ? '普通对话' : '中文指令';
  $('input-caption').textContent = next === 'text' ? '问题原文 / 下一条草稿' : '原文指令 / 下一条草稿';
  $('chat-tools').hidden = next !== 'text';
  $('max-label').hidden = next !== 'text';
  $('mode-help').textContent = next === 'action' ? '模型判断开 / 关，仅作用于上方勾选目标。' : '原文直接发送；较小上限会更早结束，也可能截断回答。';
  paintControls();
}
function updateRegister(receipt) {
  $('single-register').hidden = !!receipt.bank; $('bank-states').hidden = !receipt.bank;
  if (receipt.bank) {
    for (const channel of LED_CHANNELS) {
      const bit = 1 << channel.bit;
      $('bank-state-' + channel.bit).textContent = receipt.values === null || receipt.owned === null ? '未知' :
        !(receipt.owned & bit) ? '自动指示' : (receipt.values & bit) ? '接管 · 开' : '接管 · 关';
    }
    $('register-note').textContent = 'GPIO 状态读回；未接管灯保留原指示功能';
    $('writes').textContent = `${receipt.writes} 次`;
    return;
  }
  $('register-value').textContent = receipt.state === 1 ? '1 · 高电平' : receipt.state === 0 ? '0 · 低电平' : '未知';
  $('bulb').setAttribute('class', receipt.state === 1 ? 'on' : receipt.state === 0 ? 'off' : '');
  $('register-note').textContent = 'CPU 回执有效读回';
  $('writes').textContent = `${receipt.writes} 次`;
}
function renderResult(result, run) {
  run.result = clone(result);
  modelText(result.text || '未收到完整正文', !!result.text);
  visualState('model', result.modelComplete ? result.metrics.stop === 1 ? 'success' : 'pending' : 'error');
  visualState('receipt', run.timedOut ? 'timeout' : run.kind === 'action' || result.action ? result.actionSucceeded ? 'success' : result.action ? 'rejected' : 'error' : 'chat');
  $('model-status').textContent = result.modelComplete ? result.metrics.stop === 1 ? '模型完成 · EOS' : run.warmup ? '预热计算结束 · 等待确认' : '达到生成上限 · 回答可能未完' : '模型结果不完整';
  $('eos').textContent = result.modelComplete && result.metrics.stop === 1 ? 'EOS 已核对' : run.warmup && result.modelComplete ? '预热上限 1 token · 无需 EOS' : '未确认 EOS';
  if (result.metrics) {
    $('first-token').textContent = (result.metrics.first_token_ticks / CLOCK).toFixed(3) + ' s';
    $('decode-time').textContent = (result.metrics.decode_ticks / CLOCK).toFixed(3) + ' s';
  }
  if (result.action) updateRegister(result.action);
  if (run.kind === 'action' || result.action) {
    $('action-status').textContent = result.actionSucceeded ? 'CPU 报告执行成功' : result.action ? `动作未成功 · ${result.action.status}` : '缺少 CPU 动作回执';
    $('action-detail').textContent = result.actionSucceeded ? `完整回执已核对：${result.action.bank ? targetNames(result.action.mask) + '，' : ''}${result.action.writes} 次写入，寄存器读回匹配。` : result.error || `CPU 状态 ${result.action?.status}，报告写入 ${result.action?.writes ?? '未知'} 次。`;
  } else { $('action-status').textContent = run.warmup ? '聊天预热 · 未执行灯控' : '普通对话'; $('action-detail').textContent = run.warmup ? '真实生成上限 1 token；实际 READY 与前缀统计齐全后才确认预热。' : '本请求未要求 LED 动作，不将文本解释为灯控。'; }
  if (run.timedOut) { $('action-status').textContent = '主机超时后收到回执'; $('action-detail').textContent = '超时事件已保留；不记为按时完成。请查看实际回执与错误。'; }
}
function renderTermination(termination, run, settled = false) {
  const cancelled = termination.status === 'cancelled';
  visualState('model', cancelled ? 'cancelled' : 'timeout'); visualState('receipt', cancelled ? 'cancelled' : 'timeout');
  modelText(termination.text || '本次请求没有完整回答', !!termination.text);
  $('model-source').textContent = '板端终止记录 · 原始预览保留';
  $('model-status').textContent = settled ? cancelled ? '已取消 · 板端已恢复' : '板端超时 · 已安全恢复' : '请求已停止 · 等待 READY / 写入确认';
  $('action-status').textContent = settled ? cancelled ? '已取消' : '板端超时' : '终止恢复待确认';
  $('action-detail').textContent = settled ? '旧会话终止、恢复记录和 READY 已核对；未发布执行成功。' : '已收到同会话恢复记录；后续请求继续锁定。';
  $('eos').textContent = termination.ids?.at(-1) === 151645 ? '预览曾含 EOS · 请求已终止' : '请求已终止 · 非完整回答';
  if (termination.action) updateRegister(termination.action);
  else { clearRegister(); $('writes').textContent = '未报告'; }
}
function settleCancellation(run = cancelRun) {
  if (!run || cancelRun !== run || !run.cancelWriteConfirmed || cancelWriting || writing || !connected || boardHalted ||
      run.latency.ready_ms === undefined || !run.cancelReadyConfirmed) return false;
  const recovered = run.termination && ['cancelled','timeout'].includes(run.termination.status);
  const finished = run.cancelControl?.status === 'finished' && run.normalReadySeen && run.reportedResult?.complete;
  if (!recovered && !finished) return false;
  run.cancelSettled = true;
  run.status = recovered ? run.termination.status === 'cancelled' ? 'cancelled' : 'board-timeout' : 'completed-before-cancel';
  latency(run, 'cancel_settled_ms', null);
  event('cancel_settled', { runId:run.id, session:run.session, status:run.status });
  cancelRun = null;
  if (recovered) {
    renderTermination(run.termination, run, true);
    notice(run.status === 'cancelled' ? '已取消；板端已恢复并完成写入确认，可以发送下一条。' : '板端超时已安全终止；取消回复与写入确认齐全，可以发送下一条。');
  } else {
    visualState('model', 'cancelled'); visualState('receipt', 'cancelled');
    $('model-status').textContent = '取消未生效：请求已完成';
    $('action-status').textContent = '取消未生效：请求已完成';
    $('action-detail').textContent = '已核对原请求最终回执、同会话 finished、READY 与写入确认；取消不会撤销已经提交的动作。';
    notice('取消未生效：请求已完成。取消回复也已结束，可以发送下一条。');
  }
  if (!pending) saveHistory(run);
  paintControls(); return true;
}
function onProtocol(e) {
  event('protocol', { event: e });
  if (e.type === 'line') {
    $('raw-log').textContent += e.line + '\n';
    $('raw-log').scrollTop = $('raw-log').scrollHeight;
    if (/^(?:T25 (?:RESET|RELOAD|APP|SERVICE)|D27 BUILD)\b/.test(e.line)) {
      invalidateStream('board_restart');
      setWarmup('invalid', '已观察到板端重置 / 启动，聊天前缀需重新确认');
      prefixEnabled = null;
      if (pending && ['text','action','direct'].includes(pending.kind)) pending.errors.push('请求期间观察到板端重置 / 启动');
      if (!/^T25 RESET\b/.test(e.line)) {
        currentIdentity = null; ready = false; attachedBusy = true;
        capabilities = {}; ledCapabilities = {}; bankCapabilities = null; resetTargets();
        $('observed-ready').textContent = '服务重载 / 启动后的 READY：未观察';
        $('observed-caps').textContent = '服务重载 / 启动后的能力：未观察';
      }
    }
    if (/^(T25 APP|D27 BUILD|T25 SERVICE|T25 MODEL)/.test(e.line)) {
      ledger.observedIdentity ||= []; ledger.observedIdentity.push(e.line);
      $('observed-identity').textContent = '当前连接实收身份：' + ledger.observedIdentity.join(' / ');
    }
  } else if (e.type === 'capabilities') {
    capabilities = e; $('observed-caps').textContent = '当前连接 T25 能力：' + serialize(e);
  } else if (e.type === 'identity') {
    const next = { model:e.model, tokenizer:e.tokenizer };
    if (currentIdentity && (currentIdentity.model !== next.model || currentIdentity.tokenizer !== next.tokenizer)) {
      invalidateStream('identity_changed');
      setWarmup('invalid', '板端模型身份改变，请重新预热');
    }
    currentIdentity = next;
  } else if (e.type === 'configuration') {
    if (Object.hasOwn(e.values, 'stream')) {
      const matchingSetting = pending && /^:stream [01]$/.test(pending.command) && pending.streamRevision === streamRevision;
      invalidateStream('stream_configuration');
      if (matchingSetting) {
        pending.streamConfiguration = e.values.stream;
        pending.streamRevision = streamRevision;
      }
    }
    if (Object.hasOwn(e.values, 'prefix')) {
      prefixEnabled = e.values.prefix === 1;
      if (!(warmupState.status === 'warming' && pending?.command === ':prefix 1' && pending?.purpose === 'warmup_setup'))
        setWarmup('invalid', prefixEnabled ? '前缀设置已更新，请重新预热' : '聊天前缀已关闭；可点击启用并预热');
    }
  } else if (e.type === 'led_capabilities') {
    ledCapabilities = e.capabilities; $('observed-caps').textContent = '当前连接能力：T25 ' + serialize(capabilities) + ' / T27 ' + serialize(ledCapabilities);
  } else if (e.type === 'led_bank_capabilities') {
    bankCapabilities = e.capabilities;
    $('observed-caps').textContent = '当前连接能力：T25 ' + serialize(capabilities) + ' / T27 ' + serialize(ledCapabilities) + ' / 多灯 ' + serialize(bankCapabilities);
  } else if (e.type === 'control') {
    const run = cancelRun || pending;
    if (run?.session === e.session) {
      run.cancelControl = { session:e.session, status:e.status, late:!!e.late };
      if (e.status === 'accepted') {
        latency(run, 'cancel_accepted_ms', null, e.chunk?.monotonic_ms);
        $('model-status').textContent = '取消已接受 · 等待旧会话停止';
        $('action-status').textContent = '取消处理中 · 未取得终止结论';
        notice('板端已接受取消；等待 ABORT、恢复记录及真实 READY。');
      } else if (e.status === 'finished') {
        $('model-status').textContent = '取消未生效 · 等待完整结束确认';
        notice('板端报告请求已结束；继续核对原请求结果、READY 和取消写入确认。');
      } else notice(`取消回复 ${e.status}；不将该回复当成取消成功或恢复完成。`, true);
    }
  } else if (e.type === 'request_aborted') {
    invalidateStream('request_aborted');
    if (pending) { pending.abort = clone(e.abort); latency(pending, 'abort_ms', null, e.chunk?.monotonic_ms); }
    setWarmup('invalid', '请求已终止，聊天前缀需重新确认');
    visualState('model', e.status === 'cancelled' ? 'cancelled' : 'timeout'); visualState('receipt', 'waiting');
    $('model-status').textContent = e.status === 'cancelled' ? '旧会话已停止 · 等待安全恢复' : '板端超时 · 等待安全恢复';
    $('action-status').textContent = '等待恢复完成记录';
    $('action-detail').textContent = 'ABORT 只确认旧请求停止；还不能发送下一条。';
  } else if (e.type === 'termination_diagnostic') {
    ledger.errors.push({ ...stamp(), message:e.message, category:'expected_termination', session:e.session });
    if (pending) { pending.terminationDiagnostics ||= []; pending.terminationDiagnostics.push(e.message); }
  } else if (e.type === 'request_end') {
    if (pending) { pending.recovery = clone(e.termination); latency(pending, 'request_end_ms', null, e.chunk?.monotonic_ms); }
    $('model-status').textContent = '恢复记录已收到 · 等待真实 READY';
    $('action-status').textContent = '恢复完成待 READY';
  } else if (e.type === 'terminated') {
    if (pending) {
      pending.termination = clone(e); pending.result = { ...clone(e), complete:false };
      pending.status = e.status === 'cancelled' ? 'cancelled' : 'board-timeout';
      renderTermination(e, pending);
    }
  } else if (e.type === 'received') {
    latency(pending, 'board_received_ms', null, e.chunk?.monotonic_ms);
    $('model-status').textContent = '板端已收到 · 准备推理';
    $('last-event').textContent = 'RECEIVED · 板端已收到完整请求';
  } else if (e.type === 'phase') {
    const labels = { prefill:'正在处理输入', decode:'正在生成正文', validating:'正在校验完整结果', executing:'准备执行 · 等待读回' };
    if (pending) pending.phases.push({ stage:e.stage, at_ms:performance.now() - pending.interactionStarted_ms, session:e.session });
    $('model-status').textContent = labels[e.stage];
    $('last-event').textContent = '板端阶段 · ' + labels[e.stage];
    if (e.stage === 'executing') $('action-status').textContent = '准备执行 · 等待读回';
  } else if (e.type === 'request' || e.type === 'stream_begin') {
    visualState('model', 'waiting');
    const session = e.request?.sessionHex || e.session;
    if (pending) pending.session = session;
    if (pending && e.type === 'stream_begin' && ['text','action'].includes(pending.kind)) pending.streamBeginSession = session;
    if (e.type === 'request' && warmupState.status === 'ready' && e.request.prefix_hit !== 1)
      setWarmup('invalid', '本次请求未命中已确认前缀；等待本次前缀统计', {}, false);
    $('session-label').textContent = session;
    $('model-status').textContent = e.type === 'request' ? '板端开始处理输入' : '流式已开始 · 等待模型首字';
    latency(pending, 'board_request_ms', null, e.chunk?.monotonic_ms);
    $('last-event').textContent = e.type === 'request' ? '已收到 REQUEST · 板端开始处理' : '已收到 BEGIN · 等待真实 TOKEN';
  } else if (e.type === 'token') {
    visualState('model', 'generating');
    if (pending) pending.tokens = (pending.tokens || 0) + 1;
    latency(pending, 'first_uart_token_ms', null, e.chunk?.monotonic_ms);
    $('token-count').textContent = String(pending?.tokens || e.index);
    $('last-event').textContent = `实收 TOKEN · index ${e.index}`;
  } else if (e.type === 'preview') {
    visualState('model', 'generating');
    modelText(e.text);
    $('model-source').textContent = 'FPGA 模型 · 实收正文';
    if (e.visible) {
      latency(pending, 'first_visible_receive_ms', null, e.chunk?.monotonic_ms);
      latency(pending, 'first_visible_dom_ms', 'first-visible');
      const run = pending;
      if (run && !run.firstPaintScheduled) {
        run.firstPaintScheduled = true;
        requestAnimationFrame(() => latency(run, 'first_visible_frame_ms', null));
      }
    }
    $('model-status').textContent = '生成预览 · 尚未完成';
    $('last-event').textContent = e.buffered ? '实收长度封装正文 · 等待最终回执' : '实收 TEXT · UTF-8 已解码';
  } else if (e.type === 'stream_end') {
    if (pending && pending.streamBeginSession === pending.session) pending.streamEnded = true;
    visualState('model', 'pending');
    $('model-status').textContent = '收到 END · 等待完整回执';
    $('last-event').textContent = 'END 不代表 CPU 执行成功';
  } else if (e.type === 'action_receipt') {
    latency(pending, 'action_receipt_ms', 'action-latency', e.chunk?.monotonic_ms);
    visualState('receipt', 'pending');
    $('action-status').textContent = `收到 ${e.receipt.kind} · ${e.receipt.status}`;
    $('action-detail').textContent = '等待最终统计与 READY，尚未发布执行结论。';
  } else if (e.type === 'direct_result') {
    visualState('receipt', e.receipt.status === 'OK' ? 'direct' : 'rejected');
    updateRegister(e.receipt); if (pending) { pending.directReceipt = clone(e.receipt); pending.session = e.receipt.session; }
    $('action-status').textContent = '直接控制回执 · ' + e.receipt.status;
    $('action-detail').textContent = e.receipt.bank ? '目标 ' + targetNames(e.receipt.mask) + '；直接控制，未经过模型。' : '本次直接控制 LED0（A20），未经过模型。';
    $('model-status').textContent = '直接命令已完成 · 未运行模型';
    modelText(e.receipt.status === 'OK' ? e.receipt.bank ? pending?.command.startsWith(':ledauto ') ? '已恢复自动指示' : pending?.command === ':ledm?' ? '已收到各灯状态' : '选定状态已读回' : e.receipt.state === 1 ? 'CPU 已读回：开' : 'CPU 已读回：关' : 'CPU 返回：' + e.receipt.status, false);
  } else if (e.type === 'result') {
    if (pending) {
      if (pending.cancelRequested) {
        pending.reportedResult = clone(e);
        renderResult({ ...e, actionSucceeded:false }, pending); pending.status = 'cancel-unconfirmed';
        visualState('model', 'waiting'); visualState('receipt', 'waiting');
        $('model-status').textContent = '原请求结果已收到 · 取消待确认';
        $('action-status').textContent = '取消待确认 · 未发布执行成功';
      } else { renderResult(e, pending); pending.status = e.complete ? 'complete' : 'incomplete'; }
    }
    else { notice('收到未绑定本窗口请求的结果，已保留原始数据。', true); }
  } else if (e.type === 'error') {
    invalidateStream('protocol_error');
    visualState('model', 'error'); if (pending) visualState('receipt', 'error');
    ledger.errors.push({ ...stamp(), message: e.message }); if (pending) pending.errors.push(e.message);
    setWarmup('invalid', '板端 / 协议异常，聊天预热状态已失效');
    if (e.message === 'D27 HALTED' || e.message.startsWith('T25 TRAP ')) { boardHalted = true; ready = false; attachedBusy = true; }
    notice(e.message, true); $('model-status').textContent = boardHalted ? '板端致命故障 · 已停止' : '板端 / 协议错误';
    if (boardHalted) $('action-status').textContent = '致命故障 · 发送已锁定';
  } else if (e.type === 'ready') {
    if (boardHalted) { notice('本连接已观察到板端停止，不能用后续 READY 自动恢复发送。', true); paintControls(); return; }
    if (e.safeToSend === false) { invalidateStream('unsafe_ready'); ready = false; attachedBusy = true; notice('旧请求异常终止且没有可验证的恢复记录；保持锁定，请断开后检查板端。', true); paintControls(); return; }
    ready = true; attachedBusy = false; ledger.observedReady = stamp(); $('observed-ready').textContent = '当前连接 READY：实际已收到';
    if (cancelRun && e.controlSession === cancelRun.session) {
      cancelRun.cancelReadyConfirmed = true; latency(cancelRun, 'cancel_ready_ms', null, e.chunk?.monotonic_ms);
    }
    if (pending) {
      latency(pending, 'ready_ms', null);
      if (pending.cancelRequested && pending.reportedResult?.complete && !pending.termination) pending.normalReadySeen = true;
      if (pending.kind === 'direct' && !pending.directReceipt) pending.errors.push('缺少直接控制回执');
      if (pending.termination) pending.status = pending.termination.status === 'cancelled' ? 'cancelled' : 'board-timeout';
      else if (pending.cancelRequested) pending.status = 'cancel-unconfirmed';
      else if (pending.timedOut) pending.status = 'host-timeout';
      else if (pending.errors.length) pending.status = 'error';
      else if (!pending.status) pending.status = ['sync','control'].includes(pending.kind) || pending.directReceipt ? 'complete' : 'incomplete';
      settleCancellation(pending); finishRun();
    }
    settleCancellation();
  }
  paintControls();
}
function resetParser() { parser = new T25Parser(onProtocol); }
function saveHistory(run) {
  history = history.filter(item => item.id !== run.id);
  history.unshift(clone(run)); history = history.slice(0,20);
  try { localStorage.setItem('led-console-v3-history', serialize(history)); }
  catch { notice('浏览器历史存储空间不足，请导出完整记录。', true); }
  renderHistory();
}
function renderHistory() {
  $('history-list').replaceChildren();
  history.forEach(run => { const b = document.createElement('button'); b.textContent = `${run.createdAt} · ${run.command || '空行同步'} · ${run.status || '进行中'}`; b.onclick = () => loadReplay(run, '本机历史记录'); $('history-list').append(b); });
}
function finishRun(reason) {
  if (!pending) return;
  const run = pending; if (reason) { run.status = 'incomplete'; run.errors.push(reason); }
  if (!['complete','completed-before-cancel'].includes(run.status)) {
    invalidateStream('incomplete_request');
    setWarmup('invalid', '请求未完整成功，聊天前缀需重新确认');
  }
  run.ended_ms = performance.now(); run.elapsed_ms = run.ended_ms - run.interactionStarted_ms;
  run.observedCapabilities = clone({ t25: capabilities, t27: ledCapabilities, bank:bankCapabilities });
  if (reason) latency(run, 'disconnected_ms', null);
  const completion = pendingCompletion; pendingCompletion = null;
  pending = null; current = run; saveHistory(run);
  if (run.kind === 'sync' && run.status === 'complete') notice(capabilities.textMax && ledCapabilities.action ? 'READY 与能力已收到，可以发送原文。' : '已收到 READY；所需能力尚未观察，发送保持禁用。');
  else if (run.status === 'complete') { notice(run.warmup ? '预热回执已收到，正在核对前缀和写入确认。' : run.kind === 'text' ? '普通对话回执已收齐；未执行灯控。' : '完整回执已收齐；实物亮灭单独确认。'); $('last-event').textContent = '收到 READY · 本次完整回执核对结束'; }
  else if (run.status === 'cancelled' || run.status === 'board-timeout') {
    if (!run.cancelRequested && !writing) renderTermination(run.termination, run, true);
    if (!run.cancelSettled) notice(run.cancelRequested ? '已收到终止后的 READY；仍在等待取消回复或写入确认，暂不能发送下一条。' : '板端超时已终止并恢复；等待写入确认后可继续。');
    $('last-event').textContent = '终止后的 READY 已收到';
  }
  else if (run.status === 'completed-before-cancel') notice('取消未生效：请求已完成。取消回复也已结束，可以发送下一条。');
  else if (run.status === 'cancel-unconfirmed') notice('原请求已经到 READY；取消回复尚未完整确认，继续保持发送锁。');
  else if (!reason) notice(run.timedOut ? '主机超时已记录；请查看后续实际回执。' : run.result?.error || run.errors.at(-1) || '本次记录不完整', true);
  paintControls();
  completion?.(run);
}
async function api(path, body) {
  const response = await fetch('/api/' + path, { method: body === undefined ? 'GET' : 'POST', headers: { 'Content-Type':'application/json', 'X-Console-Token': token || '', 'X-Console-Owner':owner }, body: body === undefined ? undefined : JSON.stringify(body) });
  const data = await response.json(); if (!response.ok) throw new Error(data.error || '本地服务错误'); return data;
}
async function refreshPorts() {
  const ports = await api('ports'); $('port-options').replaceChildren(); $('python-port').replaceChildren();
  $('connect-message').textContent = ports.message || '请选择当前系统中的目标串口。';
  for (const p of ports.ports || []) {
    if (!p.expected || p.device.toUpperCase() === 'COM9') continue;
    const option = document.createElement('option'); option.value = p.device; option.textContent = `${p.device} · ${p.description} · ${p.serial}`; $('python-port').append(option);
    const label = document.createElement('label'); label.className = 'port-option'; const radio = document.createElement('input'); radio.type = 'radio'; radio.name = 'port'; radio.value = p.device; radio.checked = !$('port-options').childElementCount; label.append(radio, document.createTextNode(' ' + option.textContent)); $('port-options').append(label);
  }
  if (!$('python-port').options.length) $('connect-message').textContent = ports.message || '未找到目标 CP2102。WSL 服务看不到 Windows COM10 时，请在 Windows 启动本目录服务。';
  $('confirm-connect').disabled = !$('python-port').options.length;
}
async function openDialog() { if (connected || pending || writing || cancellationPending() || replay) return; $('connect-dialog').showModal(); try { await refreshPorts(); } catch (e) { $('connect-message').textContent = e.message; } }
async function connect() {
  const port = document.querySelector('input[name=port]:checked')?.value || $('python-port').value;
  if (!port || connected || writing || cancellationPending()) return;
  $('confirm-connect').disabled = true;
  try {
    const info = await api('connect', { port, baud:115200 });
    connected = true; ready = false; boardHalted = false; attachedBusy = !!info.pending; cursor = info.resumed ? info.after : 0;
    invalidateStream('new_connection');
    currentIdentity = null; prefixEnabled = null; setWarmup('unknown', '新连接尚未确认聊天前缀');
    capabilities = {}; ledCapabilities = {}; bankCapabilities = null; resetTargets(); ledger.observedIdentity = []; ledger.connection = { ...stamp(), ...info };
    $('observed-identity').textContent = '当前连接身份：未观察（中途附着可能没有启动 banner）';
    $('observed-ready').textContent = '当前连接 READY：未观察'; $('observed-caps').textContent = '当前连接能力：未观察';
    clearRegister(); $('register-note').textContent = '尚无本连接有效读回';
    resetParser(); event('connect', info); $('connect-dialog').close();
    if (info.resumed && info.pending) { notice('既有串口仍有未完成操作；仅恢复接收，等待 READY，不自动重发。', true); }
    else notice('串口已打开，未发送字节。点击“同步 READY”附着当前服务。');
    const generation = ++polling; paintControls(); receive(generation);
  } catch (e) { $('connect-message').textContent = e.message; $('confirm-connect').disabled = false; }
}
async function receive(generation) {
  try {
    while (connected && generation === polling) {
      const data = await api('read?after=' + cursor + '&wait=20');
      if (generation !== polling) return;
      for (const chunk of data.chunks) {
        if (chunk.seq !== cursor + 1) throw new Error('UART chunk 游标不连续，记录不完整');
        cursor = chunk.seq;
        const meta = { ...stamp(), seq: chunk.seq, data: chunk.data, received_ns: chunk.received_ns, clock:data.clock };
        ledger.chunks.push(meta); const run = pending || cancelRun; if (run) run.chunks.push(meta);
        const bytes = Uint8Array.from(atob(chunk.data), c => c.charCodeAt(0));
        if (!rhythmBusy) parser.feed(bytes, meta);
      }
      if (!data.connected) throw new Error(data.error || '串口已断开');
    }
  } catch (e) { if (generation === polling && connected) await disconnect(e.message); }
}
async function disconnect(reason = '用户断开连接') {
  ++polling; connected = false; ready = false;
  invalidateStream('disconnected');
  currentIdentity = null; prefixEnabled = null; setWarmup('invalid', '连接已断开，聊天预热状态需重新确认');
  try { parser?.finish(); } catch (e) { ledger.errors.push({ ...stamp(), message:e.message }); }
  event('disconnect', { reason });
  if (pending || cancelRun) {
    visualState('model', 'error'); visualState('receipt', 'error');
    $('model-status').textContent = boardHalted ? '板端致命故障 · 已停止' : '连接中断 · 结果不完整';
    $('action-status').textContent = boardHalted ? '致命故障 · 发送已锁定' : '连接中断 · 未取得完整结论';
    if (pending) finishRun(reason);
    else { cancelRun.status = 'incomplete'; cancelRun.errors.push(reason); saveHistory(cancelRun); }
  }
  cancelRun = null;
  try { await api('disconnect', {}); } catch (e) { ledger.errors.push({ ...stamp(), message:e.message }); }
  notice(reason, reason !== '用户断开连接'); $('register-note').textContent = '上次回执读回（连接已断开）'; paintControls();
}
async function send(command, kind, options = {}) {
  if (!connected || pending || writing || cancellationPending() || replay || boardHalted || (!ready && kind !== 'sync')) return null;
  const seconds = Number($('timeout-seconds').value);
  if (!Number.isFinite(seconds) || seconds < 1 || seconds > 86400) { notice('等待期限应为1–86400秒', true); return null; }
  const interaction = options.interaction || { started_ms:performance.now() };
  if (['action','text','direct'].includes(kind) && !options.preservePresentation) beginPresentation(kind, interaction, options.targetMask ?? targetMask);
  const run = { id:crypto.randomUUID(), source:'live', kind, command, createdAt:new Date().toISOString(), started_ms:performance.now(),
    interactionStarted_ms:interaction.started_ms, latency:{}, phases:[], timeoutSeconds:seconds, browserClock:ledger.browserClock,
    requestSource:kind === 'direct' ? 'direct_uart' : ['action','text'].includes(kind) ? 'board_model' : 'service_control',
    targetMask:['direct','action'].includes(kind) ? options.targetMask ?? targetMask : null,
    purpose:options.purpose || 'interactive', warmup:options.purpose === 'warmup',
    warmupRevision, streamRevision,
    prompt:options.prompt, maxNewTokens:options.maxNewTokens,
    observedIdentity:currentIdentity ? { ...currentIdentity } : null, testFixture:!!ledger.testFixture,
    preparation:!!options.preparation, chunks:[], events:[], errors:[], observations:[] };
  if (interaction.uiFeedback_ms !== undefined) run.latency.ui_feedback_ms = interaction.uiFeedback_ms;
  try { parser.expectRequest(kind, command); } catch (e) { invalidateStream('request_parser_rejected'); setWarmup('invalid', '请求校验失败，聊天前缀需重新确认'); notice(e.message, true); return null; }
  const completed = new Promise(resolve => { pendingCompletion = resolve; });
  pending = current = run; ledger.runs.push(run); ready = false; cancelSent = false; writing = true;
  if (/^:stream [01]$/.test(command) || kind === 'sync') {
    invalidateStream(kind === 'sync' ? 'synchronization' : 'stream_command'); run.streamRevision = streamRevision;
  }
  event('command', { command, kind, runId:run.id }); paintControls();
  notice(kind === 'sync' ? '正在发送同步请求，等待实际 READY 与能力信息。' : options.preparation ? '正在确认流式设置；收到 READY 后发送原文。' : '正在发送到板端，等待读回。');
  try {
    const response = await api('write', { command }); run.writeTiming = response.timing;
    latency(run, 'bridge_write_confirmed_ms', null);
    event('uart_write_confirmed', { runId:run.id, timing:response.timing });
    // UART can reply before the HTTP acknowledgment. Never replace a later
    // board phase, model preview or final result with this earlier milestone.
    if (pending === run && !run.session && !run.tokens && run.latency.board_received_ms === undefined) {
      $('last-event').textContent = 'UART 写入已确认 · 等待板端响应';
      if (['action','text','direct'].includes(kind)) $('model-status').textContent = '请求已发往板端';
    }
  } catch (e) {
    ledger.errors.push({ ...stamp(), message:e.message }); run.errors.push(e.message);
    // A real READY can beat the HTTP write response. Keep writes locked until
    // that response settles; an uncertain write never advances a preflight.
    await disconnect('写入失败 / 状态不确定：' + e.message);
    run.status = 'write-uncertain'; saveHistory(run);
    visualState('model', 'error'); visualState('receipt', 'error');
    $('model-status').textContent = '写入状态不确定 · 连接已关闭';
  } finally {
    writing = false; settleCancellation();
    if (run.termination && !run.cancelRequested && run.status !== 'write-uncertain' && connected && ready && !boardHalted) renderTermination(run.termination, run, true);
    paintControls();
  }
  const result = await completed;
  confirmPreparedState(result); paintControls();
  return result;
}
function captureDraft(kind = mode, prompt = $('prompt').value, maximum = Number($('max-new').value), purpose = 'interactive', forceStream = false) {
  const selected = targetMask;
  return { kind, prompt, maximum, purpose, targetMask:selected,
    command:commandFor(kind, prompt, maximum, { textMax:true,ledBank:!!bankCapabilities,targetMask:selected }),
    ensureStream:forceStream || $('ensure-stream').checked };
}
async function runModelRequest(snapshot, enablePrefix = false) {
  if (replay || !connected || !ready || boardHalted || pending || preparing || writing || cancellationPending()) return null;
  if (snapshot.kind === 'text' ? !capabilities.textMax : !ledCapabilities.action) return null;
  if (snapshot.ensureStream && !capabilities.stream) { notice('当前连接尚未声明流式能力；请同步或取消流式确认选项。', true); return null; }
  const interaction = { started_ms:performance.now() };
  preparing = true; activeDraftSnapshot = snapshot;
  if (snapshot.kind === 'action') setWarmup('invalid', '模型灯控使用另一前缀；下次聊天前可重新预热');
  beginPresentation(snapshot.kind, interaction, snapshot.targetMask); paintControls();
  const usableSetup = run => run?.status === 'complete' && run.streamRevision === streamRevision && connected && ready && !boardHalted && !pending && !replay && !cancellationPending();
  try {
    if (enablePrefix) {
      const enabled = await send(':prefix 1', 'control', { interaction, preparation:true, purpose:'warmup_setup' });
      if (!usableSetup(enabled) || prefixEnabled !== true) {
        notice('前缀开启未完整确认，预热请求尚未发送。', true); return null;
      }
    }
    if (snapshot.ensureStream && !streamConfirmed) {
      const setup = await send(':stream 1', 'control', { interaction, preparation:true, purpose:snapshot.purpose + '_setup' });
      // send resolves only after both the real READY and the HTTP write ACK.
      // This setting's READY must never release the original request lock.
      if (!usableSetup(setup) || setup.streamRevision !== streamRevision ||
          (setup.streamConfiguration !== undefined && setup.streamConfiguration !== 1)) {
        notice('流式设置未完整确认 READY 与写入确认，原文尚未发送。', true); return null;
      }
    } else if (snapshot.ensureStream) {
      event('stream_confirmation_reused', { revision:streamRevision });
    }
    return await send(snapshot.command, snapshot.kind, { interaction, preservePresentation:true,
      targetMask:snapshot.targetMask, purpose:snapshot.purpose, prompt:snapshot.prompt,
      maxNewTokens:snapshot.kind === 'text' ? snapshot.maximum : undefined });
  } finally { preparing = false; activeDraftSnapshot = null; paintControls(); }
}
async function sendInput() {
  if ($('send-button').disabled) return;
  if(isRhythmChat())return startRhythmChat();
  let snapshot;
  try { snapshot = captureDraft(); } catch (e) { notice(e.message, true); return; }
  if (snapshot.kind === 'text' && $('demo-cache-enabled').checked) {
    const hit = matchCache(snapshot.prompt, snapshot.maximum);
    if (hit.entry) { playCached(hit.entry); return; }
    if (!connected) { cacheStatus('离线未命中完全匹配的缓存；请连接板卡生成，或填入已有问题及原生成上限。', true); $('demo-cache-panel').open = true; return; }
    cacheStatus(hit.status === 'identity_mismatch' ? '缓存身份与当前板端不同；本次发送真实推理。' : '未命中缓存；本次发送真实推理。');
  }
  return runModelRequest(snapshot);
}
async function warmupChat() {
  if ($('chat-warmup').disabled) return null;
  const snapshot = captureDraft('text', '你好', 1, 'warmup', true);
  const enablePrefix = prefixEnabled === false;
  setWarmup('warming', enablePrefix ? '正在启用聊天前缀并预热…' : '真实预热中 · 等待前缀统计和 READY');
  const run = await runModelRequest(snapshot, enablePrefix);
  const prefix = run?.result?.prefix;
  if (warmupState.status === 'ready' && run?.warmupRevision === warmupRevision && prefixEnabled !== false && run?.status === 'complete' && run.result?.complete && run.result?.modelComplete &&
      run.latency.ready_ms !== undefined && prefix?.tokens > 0 && (prefix.hit === 1 || prefix.captured === 1) &&
      !run.errors.length && !run.timedOut && !run.cancelRequested && connected && ready && !boardHalted) {
    setWarmup('ready', `聊天已预热 · ${prefix.tokens} 个前缀 token 已确认`,
      { session:run.session, tokens:prefix.tokens, confirmedAt:new Date().toISOString() });
    $('model-status').textContent = '聊天预热完成 · 前缀已确认'; visualState('model', 'success');
    notice('聊天预热已确认；原问题和生成上限未改动，可以点击发送。');
  } else {
    setWarmup('invalid', '尚未确认有效聊天前缀；请查看回执，或确认固件已开启 prefix');
  }
  paintControls(); return run;
}
async function storeAnswer(run) {
  const entry = await createFromRun(run);
  await changeCache(entries => mergeEntries(entries, [entry]));
  cacheEvent('cache_saved', { entryId:entry.id, source:entry.source, sourceRunId:entry.sourceRunId, capturedAt:entry.capturedAt });
  cacheStatus(`${cacheSourceLabel(entry)}已保存；原始采集 ${entry.capturedAt}。`);
  return entry;
}
async function precomputeCurrent() {
  if ($('demo-cache-generate').disabled) return null;
  let snapshot;
  try { snapshot = captureDraft('text', $('prompt').value, Number($('max-new').value), 'precompute', true); }
  catch (e) { cacheStatus('预生成失败：' + e.message, true); return null; }
  cacheStatus('正在发送真实板端请求；只有完整 EOS 回答才会保存。');
  const run = await runModelRequest(snapshot);
  if (!run) { cacheStatus('预生成未完成，未保存缓存。', true); return null; }
  if (run.status === 'complete' && run.result?.modelComplete && run.result.metrics?.stop !== 1) {
    cacheStatus('回答达到生成上限、尚无 EOS，未保存缓存；请调大生成上限后重新预生成。', true); return null;
  }
  try { return await storeAnswer(run); }
  catch (e) { cacheStatus('预生成保存失败：' + e.message, true); return null; }
}
async function saveCurrentToCache() {
  if ($('demo-cache-save').disabled || pending || preparing || writing || cancellationPending() || replay || !canSaveAnswer()) return null;
  const run = current; // A later user action may replace current during hashing.
  try { return await storeAnswer(run); }
  catch (e) { cacheStatus('保存失败：' + e.message, true); return null; }
}
async function importCacheFile(file) {
  if (!file) return null;
  if (file.size > CACHE_LIMITS.maxImportBytes) { cacheStatus('导入失败：文件超过 2 MiB。', true); return null; }
  try {
    const raw = new TextDecoder('utf-8', { fatal:true }).decode(new Uint8Array(await file.arrayBuffer()));
    const incoming = await parseImport(raw);
    await changeCache(entries => mergeEntries(entries, incoming));
    cacheEvent('cache_imported', { count:incoming.length, sources:[...new Set(incoming.map(e => e.source))] });
    cacheStatus(`已导入 ${incoming.length} 条历史问答；原始采集时间保留，非当前推理。`);
    return incoming;
  } catch (e) { cacheStatus('导入失败：' + e.message, true); return null; }
}
async function exportCacheFile() {
  try {
    const data = await exportCache(cacheEntries);
    download('nexusrv-demo-cache-' + Date.now() + '.json', data);
    cacheEvent('cache_exported', { count:cacheEntries.length });
    cacheStatus('问答及原始 UART 证据已导出；来源与原始采集时刻均保留。');
  } catch (e) { cacheStatus('导出失败：' + e.message, true); }
}
function sendDirect(command) {
  if (preparing || cancellationPending()) return null;
  try {
    if (bankCapabilities) {
      if (command === ':led?') return send(ledBankCommand('query', LED_BANK_MASK), 'direct', { targetMask:LED_BANK_MASK });
      const wire = command === ':ledauto' ? ledBankCommand('auto', targetMask) : ledBankCommand('set', targetMask, command === ':led 1' ? targetMask : 0);
      return send(wire, 'direct', { targetMask });
    }
    if (command === ':ledauto' || (command !== ':led?' && targetMask !== 1)) throw new Error('当前固件仅开放 LED0，未提供多灯或恢复自动功能');
    return send(command, 'direct', { targetMask:1 });
  } catch (e) { notice(e.message, true); return null; }
}
async function cancel() {
  if ($('abort-button').disabled || cancelRun || cancelWriting) return;
  const run = pending, command = cancelCommand(run.session);
  cancelSent = true; cancelRun = run; cancelWriting = true; run.cancelRequested = true;
  invalidateStream('cancel_requested'); setWarmup('invalid', '取消处理中，聊天前缀需重新确认');
  latency(run, 'cancel_requested_ms', null); paintControls();
  event('command', { command, kind:'cancel', session:run.session });
  notice('取消请求已发起；等待板端接受、终止、恢复及 READY。');
  try {
    const response = await api('write', { command }); run.cancelWriteConfirmed = true; run.cancelWriteTiming = response.timing;
    latency(run, 'cancel_write_confirmed_ms', null); event('cancel_write', { runId:run.id, ...response });
  } catch (e) {
    ledger.errors.push({ ...stamp(), message:e.message, category:'cancel_write_uncertain' }); run.errors.push(e.message);
    await disconnect('取消写入失败 / 状态不确定：' + e.message);
    run.status = 'write-uncertain'; saveHistory(run);
    $('model-status').textContent = boardHalted ? '板端致命故障 · 已停止' : '取消写入状态不确定 · 连接已关闭';
  } finally { cancelWriting = false; settleCancellation(run); paintControls(); }
}
function download(name, data, type = 'application/json') { const url = URL.createObjectURL(new Blob([data],{type})); const a = document.createElement('a'); a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000); }
function exportRecord() { event('export'); ledger.baseline = baseline; ledger.displaySource = replay ? 'historical_replay' : ledger.testFixture ? 'fake_serial' : 'live'; ledger.current = current ? { ...current, presentationSource:ledger.displaySource } : null; ledger.cachePresentation = cachePlayback ? { ...cachePlayback, isLiveInference:false, presentationSource:'prepared_cache' } : null; download('nexusrv-led-' + Date.now() + '.json', serialize(ledger)); }
function rawFrom(run) { return (run.chunks || []).map(c => Uint8Array.from(atob(c.data), x=>x.charCodeAt(0))); }
async function loadReplay(run, source) {
  if (connected || pending || writing || cancellationPending()) return notice('请先断开现场连接并等待写入确认结束，再查看历史回放。', true);
  stopCachePlayback(); showBoardOutput();
  replay = true; current = run; visualState('model', 'idle'); visualState('receipt', 'idle'); $('source-banner').hidden = false; $('source-label').textContent = source + ' · 来源未经当前连接核验';
  $('model-title').textContent = '历史结果回放';
  for (const id of ['ui-feedback','first-visible','action-latency']) $(id).textContent = '—';
  $('model-source').textContent = '历史回放 · 非当前执行'; $('model-status').textContent = '回放解析中'; modelText('', false);
  $('action-status').textContent = '历史记录 · 未取得完整结论'; $('action-detail').textContent = '重新核对原始UART，不信任导入的成功标记。';
  clearRegister();$('writes').textContent='—';$('eos').textContent='待确认';$('first-token').textContent=$('decode-time').textContent=$('token-count').textContent='—';
  $('physical-status').textContent = '回放中的观察仅见导出记录';
  const parts = rawFrom(run); let result = null, direct = null, termination = null;
  const p = new T25Parser(e => { if (e.type === 'preview') modelText(e.text); if(e.type==='result')result=e; if(e.type==='direct_result')direct=e.receipt; if(e.type==='terminated')termination=e; });
  try {
    if (run.command?.startsWith(':act ') || run.command?.startsWith(':actm ')) p.expectRequest('action', run.command);
    else if (run.kind === 'direct' || [':led?',':led 0',':led 1',':ledm?'].includes(run.command) || /^:(ledm|ledauto) /.test(run.command || '')) p.expectRequest('direct', run.command);
    for (const bytes of parts) p.feed(bytes); p.finish();
    if (termination) { renderTermination(termination, run, true); $('model-status').textContent = termination.status === 'cancelled' ? '历史请求 · 已取消' : '历史请求 · 板端超时'; }
    else if (result) {
      renderResult(run.cancelRequested ? { ...result, actionSucceeded:false } : result, { kind:/^:actm? /.test(run.command || '') ? 'action':'text', timedOut:run.timedOut });
      if (run.cancelRequested) { visualState('receipt','cancelled'); $('action-status').textContent = '历史取消请求 · 不作为执行成功'; }
    }
    else if (direct) {
      updateRegister(direct); visualState('receipt', direct.status === 'OK' ? 'direct' : 'rejected');
      $('model-status').textContent = '历史直接命令 · 未运行模型'; modelText('直接控制记录', false);
      $('action-status').textContent = '历史直接控制 · ' + direct.status;
      $('action-detail').textContent = '重新核对历史 UART 回执；不代表当前现场状态。';
      $('eos').textContent = '不适用 · 直接控制';
    } else throw new Error('未找到完整模型请求或直接控制回执');
    notice('历史回放已重新解析；不代表当前现场执行。');
  } catch (e) { visualState('model','error'); visualState('receipt','error'); $('model-status').textContent='回放不完整 / 协议错误';$('action-status').textContent='回放未取得完整执行结论';notice(e.message,true); }
  $('register-note').textContent='历史回执读回 · 非当前现场状态';
  const flat = new Uint8Array(parts.reduce((n,b)=>n+b.length,0)); let pos=0;for(const b of parts){flat.set(b,pos);pos+=b.length;}
  const digest = [...new Uint8Array(await crypto.subtle.digest('SHA-256',flat))].map(x=>x.toString(16).padStart(2,'0')).join('');
  event('replay', { source, raw_sha256:digest, runId:run.id }); paintControls();
}
async function importFile(file) {
  if (!file) return; if (connected || pending || writing || cancellationPending()) return notice('请先断开现场连接并等待写入确认结束，再导入回放。',true);
  if (file.size > 16*1024*1024) return notice('导入文件超过16 MiB',true);
  try {
    const bytes=new Uint8Array(await file.arrayBuffer());let run;
    if(file.name.endsWith('.json')){const data=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(bytes));run=data.current || data.runs?.at(-1) || data;if(!Array.isArray(run.chunks))throw new Error('JSON缺少原始UART chunks');}
    else {let s='';for(const byte of bytes)s+=String.fromCharCode(byte);run={chunks:[{data:btoa(s)}],command:'',kind:'unknown',id:crypto.randomUUID()};}
    await loadReplay(run,'导入文件 ' + file.name);
  } catch(e){notice('导入失败：'+e.message,true);}
}
async function toggleRecording(){
  if(recorder && recorder.state!=='inactive'){recorder.stop();return;}
  try{
    if(!navigator.mediaDevices?.getDisplayMedia||!window.MediaRecorder)throw new Error('浏览器不支持屏幕录制');
    display=await navigator.mediaDevices.getDisplayMedia({video:true,audio:false});
    const options=MediaRecorder.isTypeSupported('video/webm;codecs=vp9')?{mimeType:'video/webm;codecs=vp9'}:{};
    recorder=new MediaRecorder(display,options);const chunks=[];recorder.ondataavailable=e=>{if(e.data.size)chunks.push(e.data);};
    recorder.onstop=()=>{display.getTracks().forEach(t=>t.stop());download('nexusrv-demo-'+Date.now()+'.webm',new Blob(chunks,{type:recorder.mimeType}),recorder.mimeType);$('record-button').textContent='● 网页录屏';$('record-status').textContent='录屏已结束';event('recording_stopped');};
    display.getVideoTracks()[0].onended=()=>{if(recorder.state!=='inactive')recorder.stop();};
    recorder.start(1000);$('record-button').textContent='■ 停止录屏';$('record-status').textContent='正在录屏';event('recording_started');
  }catch(e){display?.getTracks().forEach(t=>t.stop());notice('录屏未开始：'+e.message,true);event('recording_error',{message:e.message});}
}
$('connect-button').onclick=openDialog;$('confirm-connect').onclick=connect;$('refresh-ports').onclick=()=>refreshPorts().catch(e=>notice(e.message,true));
$('sync-button').onclick=()=>send('','sync');$('disconnect-button').onclick=()=>disconnect();$('send-button').onclick=sendInput;$('abort-button').onclick=cancel;
$('mode-action').onclick=()=>showMode('action');$('mode-text').onclick=()=>showMode('text');$('mode-direct').onclick=()=>showMode('direct');
document.querySelectorAll('[data-example]').forEach(b=>b.onclick=()=>{$('prompt').value=b.dataset.example;paintControls();});
document.querySelectorAll('[data-token-limit]').forEach(b=>b.onclick=()=>{if(!b.disabled){$('max-new').value=b.dataset.tokenLimit;paintControls();}});
$('prompt').oninput=paintControls;$('max-new').oninput=paintControls;
$('chat-warmup').onclick=warmupChat;
$('demo-cache-generate').onclick=precomputeCurrent;$('demo-cache-save').onclick=saveCurrentToCache;
$('demo-cache-now').onclick=showFullCache;$('demo-cache-stop').onclick=stopCachePlayback;
$('demo-cache-live').onclick=showBoardOutput;
$('demo-cache-export').onclick=exportCacheFile;$('demo-cache-import').onclick=()=>$('demo-cache-file').click();
$('demo-cache-file').onchange=e=>{importCacheFile(e.target.files[0]);e.target.value='';};
$('demo-cache-enabled').onchange=()=>{cacheStatus($('demo-cache-enabled').checked?'演示匹配已开启；仅原文、生成上限和身份条件满足时使用缓存，来源始终显示。':'演示匹配已关闭；普通对话发送到板端。');cacheEvent('cache_preference',{enabled:$('demo-cache-enabled').checked});paintControls();};
document.querySelectorAll('[data-direct]').forEach(b=>b.onclick=()=>{if(!b.disabled)sendDirect(b.dataset.direct);});
document.querySelectorAll('[data-led-bit]').forEach(input=>input.onchange=()=>{targetMask=0;document.querySelectorAll('[data-led-bit]').forEach(item=>{if(item.checked)targetMask|=1<<Number(item.dataset.ledBit);});paintControls();});
document.querySelectorAll('[data-control]').forEach(b=>b.onclick=()=>send(b.dataset.control,'control'));
document.querySelectorAll('[data-observe]').forEach(b=>b.onclick=()=>{if(!current||replay)return;const observation={...stamp(),runId:current.id,session:current.session||null,value:b.dataset.observe,source:'人工现场目视',captureMode:'external_phone',videoEvidenceAttached:false};current.observations.push(observation);ledger.observations.push(observation);$('physical-status').textContent='人工观察：'+b.dataset.observe;event('physical_observation',observation);if(!pending){const cached=history.find(r=>r.id===current.id);if(cached)cached.observations=clone(current.observations);try{localStorage.setItem('led-console-v3-history',serialize(history));}catch{}}});
$('record-button').onclick=toggleRecording;
$('fullscreen-button').onclick=async()=>{try{if(document.fullscreenElement)await document.exitFullscreen();else await document.documentElement.requestFullscreen();event('fullscreen',{active:!!document.fullscreenElement});}catch(e){notice('全屏失败：'+e.message,true);}};
$('export-button').onclick=exportRecord;$('raw-export').onclick=()=>{const parts=ledger.chunks.map(c=>Uint8Array.from(atob(c.data),x=>x.charCodeAt(0)));download('nexusrv-uart-'+Date.now()+'.bin',new Blob(parts),'application/octet-stream');};
$('import-button').onclick=()=>$('import-file').click();$('import-file').onchange=e=>{importFile(e.target.files[0]);e.target.value='';};
$('return-live').onclick=()=>{stopCachePlayback();showBoardOutput();replay=false;current=null;visualState('model','idle');visualState('receipt','idle');$('elapsed').textContent='00:00';$('last-event').textContent='尚未收到事件';$('source-banner').hidden=true;$('model-source').textContent='现场 UART · 等待数据';modelText('等待板端输出',false);$('model-status').textContent='尚未发送';$('action-status').textContent='等待实际回执';$('action-detail').textContent='模型预览不能证明执行完成。';clearRegister();$('register-note').textContent='尚无本连接有效读回';$('physical-status').textContent='尚未确认';$('writes').textContent=$('first-token').textContent=$('decode-time').textContent=$('token-count').textContent=$('session-label').textContent=$('ui-feedback').textContent=$('first-visible').textContent=$('action-latency').textContent='—';$('eos').textContent='待确认';notice('已返回现场；不会自动连接或发送。');paintControls();};
document.addEventListener('keydown',e=>{if(e.ctrlKey&&e.key==='Enter'){e.preventDefault();sendInput();}});
setInterval(()=>{const run=pending||current;if(!run||replay)return;const ms=pending?performance.now()-run.interactionStarted_ms:run.elapsed_ms;if(!Number.isFinite(ms))return;const seconds=Math.floor(ms/1000);$('elapsed').textContent=String(Math.floor(seconds/60)).padStart(2,'0')+':'+String(seconds%60).padStart(2,'0');if(pending&&!run.timedOut&&ms>run.timeoutSeconds*1000){run.timedOut=true;invalidateStream('host_timeout');setWarmup('invalid','请求等待超时，聊天前缀需重新确认');visualState('model','timeout');visualState('receipt','timeout');run.errors.push('主机等待超时；未自动取消 / 重发');event('host_timeout',{runId:run.id});$('model-status').textContent='主机等待超时 · 现场保留';$('action-status').textContent='未取得按时完成结论';notice('等待超时，继续被动收取回执；新请求已锁定。可导出或主动断开。',true);}},250);
resetParser();renderHistory();showMode('text');
try{const config=await api('bootstrap');token=config.token;$('fixture-banner').hidden=!config.test_fixture;ledger.testFixture=!!config.test_fixture;baseline=await(await fetch('binding.json')).json();$('baseline-cid').textContent=baseline.source_content_id;$('baseline-software').textContent=baseline.software_source_projection;$('baseline-eid').textContent=baseline.physical_evidence_id;}catch(e){notice('本地服务初始化失败：'+e.message,true);}
try{cacheEntries=await restoreCache(localStorage);renderCacheList();if(cacheEntries.length)cacheStatus(`已恢复 ${cacheEntries.length} 条历史问答；匹配默认关闭，未播放或发送。`);}catch(e){cacheStatus('恢复缓存失败：'+e.message,true);renderCacheList();}

async function loadPreparedQuestions() {
  try {
    const response=await fetch('prepared-qa.json');
    if(!response.ok)throw new Error('未找到准备问答');
    const payload=await response.text();
    return await importCacheFile(new File([payload],'demo-v5-prepared-qa.json',{type:'application/json'}));
  } catch(error) { cacheStatus('载入准备问答失败：'+error.message,true); return null; }
}
$('demo-cache-load-prepared').onclick=loadPreparedQuestions;
if(!cacheEntries.length)await loadPreparedQuestions();

function isRhythmChat(){return mode==='text' && rhythmDoc && $('rhythm-fast').checked &&
  $('prompt').value.trim().replace(/[。.!！?？]+$/u,'')===rhythmDoc.user_prompt.replace(/[。.!！?？]+$/u,'');}
const rhythmSleep=ms=>new Promise(resolve=>setTimeout(resolve,ms));
function renderRhythm(s){
  $('rhythm-chat-status').textContent=s.active?`小星星执行中 · ${s.notes_completed || 0}/42 个音符`:
    s.status==='PASS_RHYTHM_CPU_READBACK'?'小星星完成 · 已恢复自动指示':s.status==='STOPPED_BY_USER'?'已停止 · 已恢复自动指示':'灯效未完成 · 查看原始记录';
  if(s.last_bank)updateRegister({...s.last_bank,bank:true});
  $('writes').textContent=`${s.CPU_stores || 0} 次`;
  $('action-status').textContent=s.active?'CPU 正在执行模型计划':s.released_automatic?'CPU 灯效已结束并释放':'灯效未取得完整结论';
  $('action-detail').textContent='模型计划来自真实板端预生成；此刻灯控由主机执行，实际亮灭尚未目视确认。';
  if(s.first_CPU_on_receipt_seconds!==undefined)$('rhythm-first-effect').textContent=`本次首灯 CPU 回执 ${(s.first_CPU_on_receipt_seconds*1000).toFixed(1)} ms（服务端）`;
  visualState('receipt',s.active?'pending':s.released_automatic?'success':'error');
}
async function startRhythmChat(){
  if(rhythmBusy||preparing||pending||writing||!connected||!ready||replay||boardHalted||!bankCapabilities)return;
  rhythmBusy=true;preparing=true;let began=false;const clicked=performance.now();
  playCached(rhythmDoc.entry);$('rhythm-chat-status').textContent='已取得模型计划 · 正在启动四灯';
  $('rhythm-first-effect').textContent='正在等待本次真实 CPU 回执';
  for(const id of ['first-token','decode-time','token-count','first-visible','action-latency'])$(id).textContent='—';
  $('rhythm-stop').disabled=false;paintControls();
  try{
    began=true;let s=await api('rhythm/start',{prompt:$('prompt').value});
    const rec={...stamp(),prompt:$('prompt').value,modelEntry:rhythmDoc.entry.id,modelSource:'prepared_real_board_model',isCurrentInference:false,id:s.id,states:[]};(ledger.rhythmRuns ||= []).push(rec);
    while(true){
      s=await api('rhythm/status');rec.states.push({...stamp(),...s});renderRhythm(s);
      if(s.first_CPU_on_receipt_seconds!==undefined&&rec.firstStatusVisible_ms===undefined)rec.firstStatusVisible_ms=performance.now()-clicked;
      if(!s.active)break;await rhythmSleep(100);
    }
    const end=performance.now()+5000;
    while(cursor<(s.last_rx_seq||0)&&connected&&performance.now()<end)await rhythmSleep(10);
    if(cursor<(s.last_rx_seq||0))throw Error('灯效UART记录尚未收齐，现场保留');
    if(!s.released_automatic||!['PASS_RHYTHM_CPU_READBACK','STOPPED_BY_USER'].includes(s.status))throw Error('灯效未取得正常释放和READY');
    rhythmBusy=false;ready=false;resetParser();
    const sync=await send('','sync',{preservePresentation:true,purpose:'after_rhythm_sync'});
    if(sync?.status!=='complete')throw Error('灯效结束后的同步未完成');
    renderRhythm(s);notice('模型计划已执行，四灯已释放。可继续对话。');rec.status=s.status;
  }catch(e){
    if(began){ready=false;attachedBusy=true;}
    $('rhythm-chat-status').textContent='停止：'+e.message;notice(e.message,true);event('rhythm_failure',{message:e.message,began});
  }finally{rhythmBusy=false;preparing=false;$('rhythm-stop').disabled=true;paintControls();}
}
$('rhythm-question').onclick=()=>{if(preparing||pending||replay)return;showMode('text');$('prompt').value=rhythmDoc.user_prompt;$('rhythm-fast').checked=true;paintControls();};
$('rhythm-fast').onchange=paintControls;
$('rhythm-stop').onclick=async()=>{if(!rhythmBusy)return;$('rhythm-stop').disabled=true;try{await api('rhythm/stop',{});}catch(e){notice(e.message,true);}};
try{
  const response=await fetch('rhythm-model.json');if(!response.ok)throw Error('模型计划未准备');rhythmDoc=await response.json();
  const verified=await parseImport(JSON.stringify({schema:'nexusrv-demo-cache',version:1,exportedAt:rhythmDoc.entry.capturedAt,entries:[rhythmDoc.entry]}));
  const rawIntent=JSON.parse(verified[0].text);const intent=Array.isArray(rawIntent)&&rawIntent.length===1?rawIntent[0]:rawIntent;
  if(verified.length!==1||JSON.stringify(intent)!==JSON.stringify(rhythmDoc.intent))throw Error('模型计划校验失败');
  $('rhythm-question').disabled=false;$('prompt').value=rhythmDoc.user_prompt;$('max-new').value='128';paintControls();
}catch(e){rhythmDoc=null;$('rhythm-chat-status').textContent=e.message;}
