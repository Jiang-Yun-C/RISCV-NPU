import { T25Parser, commandFor, cancelCommand, metricValues, CLOCK } from './protocol.js';

const $ = id => document.getElementById(id);
const icon = name => `<svg><use href="#i-${name}"/></svg>`;
const encoder = new TextEncoder();
const state = { mode: 'live', connected: false, ready: false, busy: false, pending: null, transport: null,
  log: '', request: null, result: null, profile: null, identity: null, replay: null, samples: [],
  replayIndex: 0, replayLines: [], replayTimer: null, replayPlaying: false, view: 'demo', started: 0,
  capabilities: {}, preview: '', chunks: [], profiles: {}, requestSession: null, cancelPending: false };
let toastTimer, bootstrap, recording, recordingStream, recordingStart, cameraStream, connecting = false;
let logDecoder = new TextDecoder('utf-8', { ignoreBOM: true });
let owner;
try { owner = sessionStorage.getItem('nexusrv-console-owner') || crypto.randomUUID(); sessionStorage.setItem('nexusrv-console-owner', owner); }
catch { owner = crypto.randomUUID(); }

function toast(message) {
  $('toast').textContent = message; $('toast').hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => $('toast').hidden = true, 4500);
}
function action(fn) { return async (...args) => { try { await fn(...args); } catch (e) { toast(e.message); } }; }
async function api(path, body) {
  const auth = await bootstrap;
  const response = await fetch(path, { method: body === undefined ? 'GET' : 'POST',
    headers: { 'Content-Type': 'application/json', 'X-Console-Token': auth.token, 'X-Console-Owner': owner },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }) });
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || `本地服务错误 ${response.status}`);
  return value;
}
function clip(text, count = 65) { return text.length > count ? text.slice(0, count) + '…' : text; }
function number(n, digits = 2) { return Number(n).toLocaleString('en-US', { maximumFractionDigits: digits, minimumFractionDigits: digits }); }
function download(content, name, type = 'application/json') {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const link = document.createElement('a'); link.href = url; link.download = name; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
function filename(suffix) { return `nexusrv-${new Date().toISOString().replace(/[:.]/g, '-')}.${suffix}`; }
function showView(view) {
  state.view = view;
  for (const name of ['demo', 'performance', 'history']) $(`view-${name}`).hidden = view !== name;
  document.querySelectorAll('[data-view]').forEach(button => {
    const active = button.dataset.view === view; button.classList.toggle('active', active);
    if (active) button.setAttribute('aria-current', 'page'); else button.removeAttribute('aria-current');
  });
  const titles = { demo: ['让智能，运行在板上。', '从一句指令到一次真实计算，直观看见 RISC-V 与 NPU 的协作。'],
    performance: ['每一个数字，都来自实测。', '区分请求计时、平台累计算子计时与当前设备身份。'],
    history: ['把演示，留成证据。', '回看现场任务，保留输入、原始串口记录和板端统计。'] };
  $('page-title').textContent = titles[view][0]; $('page-description').textContent = titles[view][1];
  if (view === 'history') renderHistory();
}

class BrowserTransport {
  async open() {
    if (!navigator.serial) throw new Error('此浏览器不支持 USB 串口，请使用 Chrome / Edge，或选择 Python 串口服务');
    this.port = await navigator.serial.requestPort({ filters: [{ usbVendorId: 0x10c4, usbProductId: 0xea60 }] });
    const info = this.port.getInfo();
    if (info.usbVendorId !== 0x10c4 || info.usbProductId !== 0xea60) throw new Error('请选择目标板卡的 CP2102 串口');
    try {
      this.baud = Number($('baud-rate').value);
      await this.port.open({ baudRate: this.baud, dataBits: 8, stopBits: 1, parity: 'none', flowControl: 'none', bufferSize: 65536 });
      await this.port.setSignals({ dataTerminalReady: false, requestToSend: false });
      this.reader = this.port.readable.getReader(); this.live = true;
      this.task = this.readLoop();
    } catch (error) { try { await this.port.close(); } catch {} throw error; }
    return `浏览器直连 · CP2102 10c4:ea60 · ${this.baud} baud`;
  }
  async readLoop() {
    try {
      while (this.live) {
        const { value, done } = await this.reader.read();
        if (done) break;
        if (value) receive(value, { browserReceive: performance.now(), transport: 'webserial' });
      }
      if (this.live) connectionLost('串口已关闭');
    } catch (error) { if (this.live) connectionLost(error.message); }
    finally { this.reader.releaseLock(); }
  }
  async write(command) {
    const writer = this.port.writable.getWriter();
    const timing = { clock: 'browser.performance.now_ms', request_start: performance.now(), write_start: null, write_return: null, flush_end: null };
    if (state.request?.command === command) state.request.timing.browser = timing;
    try {
      timing.write_start = performance.now();
      await writer.write(encoder.encode(command + '\n'));
      timing.write_return = performance.now();
      // Web Serial exposes no physical last-stop-bit/drain timestamp.
      return timing;
    } finally { writer.releaseLock(); }
  }
  async close() {
    this.live = false;
    try { await this.reader?.cancel(); } catch {}
    try { await this.task; await this.port?.close(); } catch {}
  }
}

class PythonTransport {
  async open() {
    const port = $('python-port').value;
    if (!port) throw new Error('未发现目标串口。Windows 用户可改用浏览器直连，或在 Windows 启动 Python 服务');
    this.baud = Number($('baud-rate').value);
    const result = await api('/api/connect', { port, baud: this.baud }); this.after = result.after || 0; this.live = true;
    this.resumedPending = this.resumeWait = !!result.pending;
    this.task = this.poll();
    return `本地串口 · ${port} · ${this.baud} baud · CP2102 serial 0001`;
  }
  async poll() {
    try {
      while (this.live) {
        const value = await api(`/api/read?after=${this.after}&wait=20`);
        const browserReceive = performance.now();
        if (!this.live) return;
        for (const item of value.chunks) {
          if (item.seq !== this.after + 1) throw new Error('串口 chunk 序号缺失或重复，记录不完整');
          this.after = item.seq;
          receive(Uint8Array.from(atob(item.data), c => c.charCodeAt(0)),
            { browserReceive, received_ns: item.received_ns, seq: item.seq, transport: 'python' }, this.resumeWait);
        }
        if (!value.connected) throw new Error(value.error || '串口已断开');
        if (this.resumeWait && !value.pending && value.synced) {
          this.resumeWait = false; parser.reset();
          state.ready = true; state.busy = false; state.pending = null;
          updateConnection(); outputStatus('此前任务已结束 · 旧结果未收齐，可提交新请求');
        }
      }
    } catch (error) { if (this.live) connectionLost(error.message); }
  }
  async write(command) {
    const timing = { clock: 'browser.performance.now_ms', request_start: performance.now(), request_return: null };
    const request = state.request?.command === command ? state.request : null;
    if (request) request.timing.browser = timing;
    const result = await api('/api/write', { command });
    timing.request_return = performance.now();
    if (request) request.timing.host = { ...request.timing.host, ...result.timing };
    return result.timing;
  }
  async close() { this.live = false; await api('/api/disconnect', {}); }
}

function setOutput(which) {
  for (const name of ['empty', 'running', 'result']) $(`output-${name}`).hidden = which !== name;
}
function resetDisplay() {
  state.log = ''; state.request = state.result = state.profile = null; state.failure = null;
  state.preview = ''; state.chunks = [];
  state.profiles = {}; state.requestSession = null; state.cancelPending = false;
  logDecoder = new TextDecoder('utf-8', { ignoreBOM: true }); parser.reset();
  $('raw-log').textContent = '等待串口数据…';
  setOutput('empty'); renderLatency(); renderMetrics(null); renderProfile(null); renderStats(null);
  for (const name of ['host', 'cpu', 'npu', 'result']) $(`node-${name}`).classList.remove('active', 'done');
  $('pipeline-caption').textContent = state.mode === 'live' ? '等待串口事件' : '历史实板记录 · 按事件顺序展示';
}
function updateConnection() {
  $('connection-status').classList.toggle('connected', state.connected);
  $('connection-label').textContent = state.connected ? (state.busy ? '板端计算中' : state.ready ? '板端服务就绪' : '串口已连接 · 待同步') : '设备未连接';
  $('connected-actions').hidden = !state.connected;
  $('connect-confirm').hidden = state.connected;
  $('transport-kind').disabled = $('baud-rate').disabled = state.connected;
  $('stream-enabled').disabled = !state.ready || state.busy || !!state.pending || !state.capabilities.stream;
  $('cancel-button').hidden = !state.capabilities.cancel || !state.busy;
  $('cancel-button').disabled = !state.requestSession || state.cancelPending;
  $('cancel-button').textContent = state.cancelPending ? '已请求停止，等待当前计算结束' : '停止生成';
  $('prefix-enabled').disabled = !state.ready || state.busy || !!state.pending || !state.capabilities.prefix;
  $('timeout-apply').disabled = !state.ready || state.busy || !!state.pending || !state.capabilities.timeout;
  $('connected-info').textContent = state.connected ? `${state.transportLabel}。断开串口不会取消板端正在执行的计算。` : '';
  $('sync-button').disabled = state.busy || state.pending !== null;
  $('memory-button').disabled = state.mode !== 'live' || !state.ready || state.busy || !!state.pending;
  $('mode-live').disabled = $('mode-replay').disabled = state.busy && state.mode === 'live';
  const run = $('run-button');
  run.disabled = connecting || (state.connected && (!state.ready || state.busy || !!state.pending));
  run.innerHTML = state.busy ? `${icon('clock')}<span>板端计算中，请稍候</span>` : state.connected ? `${icon('play')}<span>${state.ready && !state.pending ? '运行板端推理' : '等待板端 READY'}</span>${icon('arrow')}` : `${icon('plug')}<span>连接板卡，开始演示</span>${icon('arrow')}`;
  $('output-source').classList.toggle('replay', state.mode === 'replay');
  $('output-source').innerHTML = `<span></span> ${state.mode === 'replay' ? 'RECORDED UART' : 'LIVE UART'}`;
  $('footer-source').textContent = state.mode === 'replay' ? '历史实板 · 事件顺序回放' : state.connected ? `实时串口 · ${state.transport?.baud || 115200} baud` : '实时串口 · 尚未连接';
  $('identity-status').textContent = state.identity ? (state.identity.matches ? '已收到匹配的模型 / tokenizer 身份' : '与项目基线不同，请核对') : '尚未收到启动身份';
}
function outputStatus(text, active = false) {
  $('output-status').replaceChildren();
  const dot = document.createElement('span'); dot.className = 'status-dot';
  if (active) dot.style.background = '#91ba91';
  $('output-status').append(dot, document.createTextNode(text));
}
function bytesBase64(bytes) {
  let binary = '';
  for (let i = 0; i < bytes.length; i += 32768) binary += String.fromCharCode(...bytes.subarray(i, i + 32768));
  return btoa(binary);
}
function receive(bytes, chunk = null, discardIncomplete = false) {
  try {
    const received = chunk || { browserReceive: performance.now(), transport: 'replay' };
    // Keep exact bytes; UTF-8 log text alone cannot preserve malformed input.
    const record = { ...received, data: bytesBase64(bytes), bytes: bytes.length, discardIncomplete };
    state.chunks.push(record);
    const text = logDecoder.decode(bytes, { stream: true });
    if (state.log.length + text.length > 2 * 1024 * 1024 || state.chunks.length > 65536) throw new Error('记录超过容量，请导出已有记录后重新连接');
    state.log += text;
    if (!discardIncomplete) parser.feed(bytes, received);
    // Body is updated before diagnostic log DOM work.
    if ($('log-dialog').open) renderLog();
  } catch (error) {
    if (state.mode === 'replay') throw error;
    connectionLost(`串口记录无法继续解析：${error.message}`);
  }
}
function renderLatency() {
  const timing = state.request?.timing, browser = timing?.browser, host = timing?.host;
  let receive = null;
  if (host?.write_start && host?.first_visible_receive_ns)
    receive = Number(BigInt(host.first_visible_receive_ns) - BigInt(host.write_start)) / 1e6;
  else if (browser?.first_visible_receive != null && browser.write_start != null)
    receive = browser.first_visible_receive - browser.write_start;
  const origin = browser?.request_start;
  const dom = origin != null && browser?.first_dom_commit != null ? browser.first_dom_commit - origin : null;
  const frame = origin != null && browser?.next_frame_callback != null ? browser.next_frame_callback - origin : null;
  $('latency-receive').textContent = receive == null ? '—' : `${number(receive / 1000, 3)} s`;
  $('latency-dom').textContent = dom == null ? '—' : `${number(dom / 1000, 3)} s`;
  $('latency-frame').textContent = frame == null ? '—' : `${number(frame / 1000, 3)} s`;
  $('latency-receive-note').textContent = state.transport instanceof PythonTransport ? 'Python 写入开始 → 主机收到完整字符' : '串口写入开始 → 浏览器收到完整字符';
}
function showPreview(event) {
  state.preview = event.text;
  setOutput('result'); $('result-text').classList.remove('error'); $('result-text').textContent = event.text;
  const domCommit = performance.now();
  $('result-state').textContent = state.mode === 'replay' ? '历史流式预览' : '正在生成 · 预览';
  $('result-meta').textContent = '正文随板端输出更新，完成后核对完整结果。';
  outputStatus(state.mode === 'replay' ? '历史事件回放中' : '正在接收板端正文', true);
  const request = state.mode === 'live' ? state.request : null;
  if (request && event.visible && request.timing.browser?.first_visible_receive == null) {
    const browser = request.timing.browser;
    browser.first_visible_receive = event.chunk.browserReceive;
    browser.first_dom_commit = domCommit;
    browser.visibility_at_dom = document.visibilityState;
    browser.view_at_dom = state.view;
    if (event.chunk.received_ns) request.timing.host.first_visible_receive_ns = event.chunk.received_ns;
    requestAnimationFrame(() => {
      browser.next_frame_callback = performance.now(); // Scheduling evidence, never a pixel timestamp.
      persistTiming(request);
      if (state.request === request) renderLatency();
    });
    renderLatency();
  }
}
const parser = new T25Parser(event => {
  if (event.type === 'ready') {
    if (state.mode === 'live') {
      state.ready = true;
      if (state.busy && !state.result && !state.failure) displayError('板端返回 READY，但缺少完整输出，请检查原始日志');
      state.busy = false; state.pending = null;
      if (!state.result) outputStatus('板端服务就绪', true);
      updateConnection();
    }
  } else if (event.type === 'capabilities') {
    state.capabilities = { stream: event.stream, textMax: event.textMax, cancel: event.cancel, prefix: event.prefix, profile: event.profile, timeout: event.timeout }; updateInput(); updateConnection();
  } else if (event.type === 'request') {
    state.requestSession = event.request.sessionHex;
    $('timeout-seconds').value = event.request.timeout_ticks / CLOCK;
    if (state.request) state.request.boardRequest = event.request;
    updateConnection();
  } else if (event.type === 'control') {
    if (event.status === 'accepted') outputStatus('板端已接受停止请求，正在恢复就绪状态', true);
    else if (event.status === 'stale' || event.status === 'rejected') { state.cancelPending = false; toast('取消命令未匹配当前任务'); updateConnection(); }
  } else if (event.type === 'configuration') {
    if (event.values.timeout_ticks !== undefined) $('timeout-seconds').value = event.values.timeout_ticks / CLOCK;
    if (event.values.prefix !== undefined) $('prefix-enabled').checked = event.values.prefix === 1;
  } else if (event.type === 'prefix') {
    if (state.request) state.request.prefix = event.prefix;
  } else if (event.type === 'stream_begin') {
    $('running-title').textContent = '正在处理输入';
    $('running-detail').textContent = '第一个完整字符到达后立即显示。';
    $('node-host').classList.add('done'); $('node-cpu').classList.add('active');
  } else if (event.type === 'token') {
    $('pipeline-caption').textContent = `板端已生成 ${event.index} tokens`;
  } else if (event.type === 'preview') {
    showPreview(event);
  } else if (event.type === 'timing') {
    if (state.request) state.request.boardTiming = event.timing;
  } else if (event.type === 'step') {
    if (!state.preview) setOutput('running');
    $('running-title').textContent = event.generated ? '正在生成结果' : '正在处理输入';
    $('running-detail').textContent = `板端已报告 ${event.forwards} 次 forward · 输入 ${event.prefilled} · 输出 ${event.generated} tokens`;
    $('pipeline-caption').textContent = `已收到 ${event.forwards} 次真实计算步事件`;
    $('node-host').classList.add('done'); $('node-cpu').classList.add('active');
    outputStatus(state.mode === 'replay' ? '历史事件回放中' : '收到真实 STEP，等待完整结果', true);
  } else if (event.type === 'result') {
    if (event.complete) {
      state.result = event;
      renderResult(event); renderMetrics(event.metrics); renderStats(event.metrics);
      if (state.mode === 'live' && state.request && !state.request.writePending) saveSession(event);
    } else { displayError(event.error); if (state.mode === 'live' && state.request && !state.request.writePending) saveSession(null, event.error); }
    if (state.mode === 'live') state.busy = false;
  } else if (event.type === 'profile') {
    if (event.phase) {
      state.profiles[event.phase] = event.profile;
      const phase = $('profile-phase').value;
      if (state.profiles[phase]) renderProfile(state.profiles[phase], phase);
    } else { state.profile = event.profile; renderProfile(event.profile); }
  } else if (event.type === 'identity') {
    state.identity = event; updateConnection();
    if (!event.matches) toast('当前设备的模型身份与项目基线不同，运行前请核对');
  } else if (event.type === 'boot') {
    if (state.mode === 'live') {
      state.ready = false; state.identity = null; state.profile = null;
      outputStatus('板端启动 / 装载中'); updateConnection();
    }
  } else if (event.type === 'error') {
    displayError(event.message);
    // ERROR returns READY; TRAP / malformed UTF-8 does not permit another request.
    if (event.fatal) { state.ready = state.busy = false; state.pending = 'fault'; if (state.request) saveSession(null, event.message); updateConnection(); }
  } else if (event.type === 'memory') {
    const m = event.values;
    $('memory-status').textContent = `当前已提交 ${(m.committed_bytes / 1048576).toFixed(2)} MiB · 峰值 ${(m.peak_committed_bytes / 1048576).toFixed(2)} MiB · ${m.regions} 个区域（板端读回计数）`;
  }
});
function renderResult(result) {
  setOutput('result'); $('result-text').classList.remove('error');
  $('result-text').textContent = result.text || '（本次请求没有可显示的文本输出）';
  $('result-state').textContent = state.mode === 'replay' ? '历史实板输出' : state.request ? '板端请求完成' : '接入时收到的板端结果';
  const m = result.metrics;
  const stop = { 1: 'EOS', 2: '生成上限', 3: '上下文上限' }[m.stop] || `stop=${m.stop}`;
  $('result-meta').textContent = `${m.prompt} input  /  ${m.generated} output tokens  /  ${stop}`;
  $('pipeline-caption').textContent = state.mode === 'replay' ? '历史记录完成 · 原始耗时见上方实测指标' : '板端返回完整输出与统计';
  $('node-host').classList.add('done'); $('node-cpu').classList.remove('active'); $('node-cpu').classList.add('done');
  $('node-npu').classList.toggle('done', m.ce_calls > 0); $('node-result').classList.add('done');
  outputStatus(state.mode === 'replay' ? '历史记录 · 非现场执行' : '已收齐输出与统计', true);
}
function displayError(message) {
  state.failure = message;
  setOutput('result'); $('result-text').classList.add('error'); $('result-text').textContent = state.preview ? `${state.preview}\n\n〔未完成：${message}〕` : message;
  $('result-state').textContent = '请求未完成'; $('result-meta').textContent = '请展开串口日志查看原始记录。';
  outputStatus('板端异常 / 记录不完整');
  state.result = null;
}
function renderMetrics(metrics) {
  const m = metricValues(metrics);
  for (const [id, value, unit] of [['time', m ? number(m.seconds) : '—', 's'], ['first', m?.first != null ? number(m.first) : '—', 's'],
    ['speed', m?.speed != null ? number(m.speed, 4) : '—', 'tok/s'], ['calls', m ? number(m.calls, 0) : '—', '次']])
    $(`metric-${id}`).innerHTML = `${value}<small>${unit}</small>`;
  $('metric-fallback').textContent = `CPU 回退 ${m ? m.fallback : '—'} 次`;
}
function renderStats(m) {
  $('performance-stats').replaceChildren();
  if (!m) { const p = document.createElement('div'); p.className = 'empty-state'; p.textContent = '完成一次推理或查看实测回放后，这里会显示板端计数。'; $('performance-stats').append(p); return; }
  const values = [['输入 / 输出 token', `${m.prompt} / ${m.generated}`], ['KV 有效长度', m.kv],
    ['Prefill', `${number(m.prefill_ticks / CLOCK)} s`], ['Decode', `${number(m.decode_ticks / CLOCK)} s`],
    ['加速后端调用 / CPU 回退', `${m.ce_calls} / ${m.fallback_calls}`], ['栈峰值', m.stack_peak_bytes == null ? '—' : `${number(m.stack_peak_bytes / 1024)} KiB`],
    ['板端 session', m.session ?? '—']];
  const prefix = state.result?.prefix, pmu = state.result?.pmu, transfer = state.result?.transfer;
  if (prefix) {
    values.push(['固定前缀', `${prefix.hit ? '命中' : '冷请求'} · ${prefix.tokens} tokens`]);
    if (prefix.captured) values.push(['本次前缀准备计算', `${number(prefix.prepare_ticks / CLOCK)} s（已含在 Prefill 中）`]);
  }
  if (pmu?.STATUS) values.push(['硬件性能快照', pmu.STATUS.valid ? '有效区间记录（含期间串口 / 观测开销）' : pmu.STATUS.available ? '快照未通过一致性检查' : '当前位流未提供']);
  if (pmu?.REQUEST) values.push(['区间 CPU 退休指令', number(pmu.REQUEST.retired, 0)], ['区间 CPU 数据读取', `${number(pmu.REQUEST.d_r_bytes / 1024)} KiB`]);
  if (transfer) values.push(['本次输出回拷', `${number(transfer.output_copy_bytes / 1024)} KiB`],
    ['避免的私有缓冲回拷', `${number(transfer.output_saved_bytes / 1024)} KiB（软件统计）`],
    ['避免的 KV 尾部回拷', `${number(transfer.kv_output_saved_bytes / 1024)} KiB（软件统计）`],
    ['避免的 head 扫描读取', `${number(transfer.head_read_saved_bytes / 1024)} KiB（软件统计）`]);
  for (const [label, value] of values) {
    const row = document.createElement('div'); row.className = 'stat-row';
    const name = document.createElement('span'); name.textContent = label;
    const text = document.createElement('strong'); text.textContent = String(value);
    row.append(name, text); $('performance-stats').append(row);
  }
}
function renderProfile(profile, phase = 'CUMULATIVE') {
  $('profile-bars').replaceChildren();
  const phases = { REQUEST: '本次请求', PREFILL: '本次输入处理', DECODE: '本次逐 token 生成', CUMULATIVE: '平台启动以来累计，包含此前请求' };
  $('profile-caption').textContent = profile ? phases[phase] + '的算子时间；不包含串口展示。' : '等待板端算子统计。';
  if (!profile) return;
  const names = ['embedding', 'rmsnorm', 'linears', 'rope', 'attention', 'swiglu', 'residual', 'head'];
  const maximum = Math.max(1, ...profile.map(x => x.ticks));
  for (const p of profile) {
    const row = document.createElement('div'); row.className = 'profile-row';
    const label = document.createElement('span'); label.textContent = names[p.index];
    const track = document.createElement('div'); track.className = 'profile-track';
    const fill = document.createElement('div'); fill.className = 'profile-fill'; fill.style.width = `${Math.max(1, p.ticks / maximum * 100)}%`;
    track.append(fill); const value = document.createElement('span'); value.textContent = `${number(p.ticks / CLOCK)} s`;
    row.title = `${phases[phase]} ${p.calls} 次调用`; row.append(label, track, value); $('profile-bars').append(row);
  }
}

async function connectionLost(message) {
  if (!state.connected && !connecting) return;
  const transport = state.transport;
  state.connected = state.ready = state.busy = false; state.pending = null; state.transport = null;
  if (state.request && !state.request.saved) saveSession(null, message);
  updateConnection(); outputStatus('连接已断开'); toast(message);
  try { await transport?.close(); } catch {}
}
async function disconnect() {
  const running = state.busy;
  if (running && !confirm('断开串口不会取消板端计算。仍要断开并保存当前不完整记录吗？')) return;
  const transport = state.transport;
  if (state.request && !state.request.saved) saveSession(null, '串口在请求完成前断开');
  state.connected = state.ready = state.busy = false; state.pending = null; state.transport = null;
  updateConnection(); await transport?.close();
  outputStatus(running ? '连接已断开 · 板端可能仍在计算' : '串口已断开');
}
async function refreshPorts() {
  const data = await api('/api/ports'); $('python-port').replaceChildren();
  const ports = data.ports.filter(x => x.expected);
  if (!ports.length) { const option = new Option(data.available ? '未发现目标 CP2102 串口' : '请先安装 pyserial', ''); $('python-port').add(option); }
  for (const port of ports) $('python-port').add(new Option(`${port.device} · ${port.description} · ${port.serial}`, port.device));
  if (!data.available) $('connect-error').textContent = data.message;
}
async function transportChanged() {
  const python = $('transport-kind').value === 'python'; $('python-port-field').hidden = !python;
  $('transport-hint').textContent = python ? '服务运行在哪个系统，就列出哪个系统的串口。需要 pyserial，目标设备校验 serial 0001。' : '在系统弹窗中选择 CP2102。Windows 浏览器可直接连接 COM 口，无需把串口映射到 WSL。';
  if (python && !state.connected) await refreshPorts();
}
function openConnect() {
  $('connect-error').textContent = '';
  if (!state.connected) { $('transport-kind').value = navigator.serial ? 'browser' : 'python'; action(transportChanged)(); }
  updateConnection(); $('connect-dialog').showModal();
}
async function connect() {
  if (connecting || state.connected) return;
  if (state.mode !== 'live') await setMode('live');
  connecting = true; $('connect-confirm').disabled = true; $('connect-error').textContent = '';
  const transport = $('transport-kind').value === 'browser' ? new BrowserTransport() : new PythonTransport();
  try {
    resetDisplay(); state.identity = null; state.capabilities = {}; updateInput();
    state.transport = transport;
    state.transportLabel = await transport.open();
    state.connected = true; state.ready = false; state.pending = 'sync';
    if (!transport.resumedPending) await transport.write('');
    $('connect-dialog').close(); outputStatus(transport.resumedPending ? '已恢复接收，等待此前任务结束' : '已发送空行，等待板端 READY');
    toast('串口已连接。服务就绪后，点击运行板端推理。');
  } catch (error) {
    try { await transport.close(); } catch {}
    state.transport = null; state.connected = state.ready = false; state.pending = null;
    $('connect-error').textContent = error.name === 'NotFoundError' ? '尚未选择串口，可再次点击连接。' : error.message;
  } finally { connecting = false; $('connect-confirm').disabled = false; updateConnection(); }
}
function updateInput() {
  const ids = $('request-kind').value === 'ids';
  $('token-options').hidden = !ids && !state.capabilities.textMax;
  $('input-label').textContent = ids ? '十进制 token ID，以空格分隔' : '发送给板端模型的指令';
  $('byte-count').textContent = `${encoder.encode($('prompt').value).length} / 4096 bytes`;
  $('request-hint').textContent = ids ? '直接发送 token IDs · 跳过聊天模板，适合数值演示' : state.capabilities.textMax ? '板端完成分词与推理 · 可设置生成上限 · 正文实时更新' : '板端完成分词与推理 · 旧服务文本上限 128 tokens';
}
async function run() {
  if (!state.connected) return openConnect();
  if (!state.ready || state.busy || state.pending) throw new Error('请等待板端服务就绪');
  const command = commandFor($('request-kind').value, $('prompt').value, Number($('max-new').value), state.capabilities);
  resetDisplay();
  state.request = { schema: 'nexusrv-demo-v1', id: crypto.randomUUID(), source: 'live', command, createdAt: new Date().toISOString(),
    transport: state.transportLabel, identity: state.identity, clockHz: CLOCK, writePending: true,
    timing: { browser: { clock: 'browser.performance.now_ms' }, host: {} } };
  state.busy = true; state.ready = false; state.pending = 'request'; state.started = performance.now();
  setOutput('running'); $('running-title').textContent = '等待板端计算';
  $('running-detail').textContent = state.capabilities.stream ? '第一个完整字符到达后立即显示，后续正文逐步更新。' : '等待当前服务返回正文。';
  $('running-clock').textContent = '00:00'; $('node-host').classList.add('active');
  updateConnection(); outputStatus('请求已提交，等待板端输出', true);
  const request = state.request;
  try { await state.transport.write(command); renderLatency(); }
  catch (error) { await connectionLost(`请求发送失败：${error.message}`); }
  finally {
    request.writePending = false; persistTiming(request);
    if (state.request === request && (state.result || state.failure)) saveSession(state.result, state.failure || null);
  }
}

function stopPlayback() { clearTimeout(state.replayTimer); state.replayPlaying = false; updateReplayButton(); }
function updateReplayButton() { $('replay-play').innerHTML = state.replayPlaying ? `${icon('pause')}<span>暂停回放</span>` : `${icon('play')}<span>${state.replayIndex > 0 && state.replayIndex < state.replayLines.length ? '继续回放' : '播放记录'}</span>`; }
async function setMode(mode) {
  if (state.mode === mode) return;
  if (state.busy) throw new Error('当前板端任务正在执行，请完成后切换');
  if (state.connected) await disconnect();
  stopPlayback(); state.mode = mode; state.ready = false;
  $('mode-live').classList.toggle('selected', mode === 'live'); $('mode-replay').classList.toggle('selected', mode === 'replay');
  $('live-controls').hidden = mode !== 'live'; $('replay-controls').hidden = mode !== 'replay';
  $('source-banner').hidden = mode !== 'replay';
  resetDisplay(); updateConnection();
  if (mode === 'replay') selectReplay(true); else outputStatus('等待连接');
}
function selectReplay(showEnd = false) {
  stopPlayback(); state.replay = state.samples.find(x => x.id === $('replay-select').value);
  if (!state.replay) return;
  state.replayIndex = 0; state.replayLines = state.replay.raw.split(/(?<=\n)/).filter(Boolean);
  $('replay-prompt').textContent = state.replay.command || '未记录请求内容';
  $('source-title').textContent = state.replay.title;
  $('source-detail').textContent = state.replay.note || '导入记录 · 来源未经本工具独立核验 · 事件顺序回放';
  resetDisplay(); updateConnection();
  if (showEnd) finishReplay();
}
function replayTick() {
  if (!state.replayPlaying) return;
  try {
    const line = state.replayLines[state.replayIndex++];
    if (line !== undefined) receive(encoder.encode(line));
    $('running-clock').textContent = `事件 ${state.replayIndex} / ${state.replayLines.length}`;
    if (state.replayIndex < state.replayLines.length) state.replayTimer = setTimeout(replayTick, line?.startsWith('T25 STEP ') ? 150 : 35);
    else { parser.finish(); stopPlayback(); }
  } catch (error) { stopPlayback(); displayError(error.message); }
}
function playReplay() {
  if (!state.replay) throw new Error('暂无可回放记录');
  if (state.replayPlaying) return stopPlayback();
  if (state.replayIndex >= state.replayLines.length || state.replayIndex === 0) { resetDisplay(); state.replayIndex = 0; }
  state.replayPlaying = true; updateReplayButton(); setOutput('running');
  $('running-title').textContent = '历史实板事件回放'; $('running-detail').textContent = '按事件顺序呈现，不对应原始逐行时间。';
  replayTick();
}
function finishReplay() {
  stopPlayback(); if (!state.replay) return;
  resetDisplay(); receive(encoder.encode(state.replay.raw)); state.replayIndex = state.replayLines.length;
  try { parser.finish(); if (!state.result) throw new Error('记录中没有完整请求结果'); }
  catch (error) { displayError(error.message); }
  updateReplayButton();
}
function sessions() { try { const value = JSON.parse(localStorage.getItem('nexusrv-sessions-v1') || '[]'); return Array.isArray(value) ? value.slice(0, 20) : []; } catch { return []; } }
function persistTiming(request) {
  if (!request?.saved) return;
  try {
    const records = sessions().map(record => record.id === request.id ? { ...record, timing: request.timing } : record);
    localStorage.setItem('nexusrv-sessions-v1', JSON.stringify(records));
  } catch {}
}
function saveSession(result, error = null) {
  if (!state.request || state.request.saved) return;
  const record = { ...state.request, raw: state.log, rawChunks: state.chunks, complete: !!result?.complete, error, metrics: result?.metrics ?? null, profiles: result?.profiles ?? state.profiles, prefix: result?.prefix ?? null, pmu: result?.pmu ?? null, transfer: result?.transfer ?? null, finishedAt: new Date().toISOString() };
  state.request.saved = true; state.lastRecord = record;
  try { localStorage.setItem('nexusrv-sessions-v1', JSON.stringify([record, ...sessions()].slice(0, 20))); }
  catch { toast('浏览器存储空间不足，请导出本次记录留存'); }
}
function renderHistory() {
  $('history-list').replaceChildren(); const all = sessions();
  if (!all.length) { const empty = document.createElement('div'); empty.className = 'empty-state'; empty.textContent = '第一条现场推理完成后，会出现在这里。'; $('history-list').append(empty); }
  for (const record of all) {
    const row = document.createElement('div'); row.className = 'history-item';
    const info = document.createElement('div'); const title = document.createElement('strong'); title.textContent = clip(String(record.command || '未记录请求'));
    const meta = document.createElement('p'); meta.textContent = `${new Date(record.createdAt).toLocaleString('zh-CN')} · ${record.complete ? '输出完整' : '记录不完整'} · ${record.transport || '本地记录'}`;
    info.append(title, meta); const time = document.createElement('span'); time.className = 'history-time'; time.textContent = record.metrics ? `${number(record.metrics.total_ticks / CLOCK)} s` : '—';
    const button = document.createElement('button'); button.className = 'button secondary small'; button.textContent = '查看记录';
    button.addEventListener('click', action(async () => { await importRecord(record); showView('demo'); }));
    row.append(info, time, button); $('history-list').append(row);
  }
}
async function importRecord(record) {
  if (state.busy && state.mode === 'live') throw new Error('请等待板端任务完成后再打开回放');
  if (typeof record.raw !== 'string' || encoder.encode(record.raw).length > 2 * 1024 * 1024) throw new Error('记录缺少原始文本，或大小超过 2 MiB');
  const item = { id: 'import-' + crypto.randomUUID(), title: '导入记录 · ' + clip(String(record.command || '串口输出'), 25),
    command: String(record.command || ''), raw: record.raw,
    note: '本地导入 · 来源未经独立核验 · 按事件顺序展示' };
  state.samples.push(item); $('replay-select').add(new Option(item.title, item.id)); $('replay-select').value = item.id;
  await setMode('replay'); selectReplay(true); showView('demo');
}
function exportRecord() {
  if (!state.log) throw new Error('暂无记录可导出');
  const record = state.mode === 'live' && state.request ? { ...state.request, raw: state.log, rawChunks: state.chunks,
    complete: !!state.result?.complete, metrics: state.result?.metrics ?? null, profiles: state.result?.profiles ?? state.profiles,
    prefix: state.result?.prefix ?? null, pmu: state.result?.pmu ?? null, transfer: state.result?.transfer ?? null } :
    { schema: 'nexusrv-demo-v1', source: 'replay', command: state.replay?.command, provenance: state.replay?.provenance, raw: state.log, complete: !!state.result };
  download(JSON.stringify(record, null, 2), filename('json'));
}
function renderLog() { $('raw-log').textContent = state.log || '等待串口数据…'; $('log-source').textContent = `${state.mode === 'live' ? '现场串口' : '历史记录'} · ${encoder.encode(state.log).length.toLocaleString()} bytes`; }

document.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', () => showView(button.dataset.view)));
document.querySelectorAll('.close-dialog').forEach(button => button.addEventListener('click', () => button.closest('dialog').close()));
document.querySelectorAll('dialog').forEach(dialog => dialog.addEventListener('click', event => { if (event.target === dialog) { const r = dialog.getBoundingClientRect(); if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) dialog.close(); } }));
for (const id of ['connection-status', 'rail-connect']) $(id).addEventListener('click', openConnect);
$('connect-confirm').addEventListener('click', connect);
$('disconnect-button').addEventListener('click', action(disconnect));
$('sync-button').addEventListener('click', action(async () => { if (!state.connected || state.busy || state.pending) return; state.pending = 'sync'; state.ready = false; updateConnection(); await state.transport.write(''); }));
$('refresh-ports').addEventListener('click', action(refreshPorts));
$('transport-kind').addEventListener('change', action(transportChanged));
$('stream-enabled').addEventListener('change', action(async () => {
  if (!state.ready || state.busy || state.pending || !state.capabilities.stream) return;
  state.pending = 'stream'; state.ready = false; updateConnection();
  try { await state.transport.write(`:stream ${$('stream-enabled').checked ? 1 : 0}`); }
  catch (error) { await connectionLost(error.message); }
}));
$('cancel-button').addEventListener('click', action(async () => {
  if (!state.connected || !state.busy || !state.capabilities.cancel || state.cancelPending) return;
  const command = cancelCommand(state.requestSession);
  state.cancelPending = true; updateConnection();
  try { await state.transport.write(command); outputStatus('停止请求已发送，等待板端安全边界确认', true); }
  catch (error) { state.cancelPending = false; updateConnection(); throw error; }
}));
$('prefix-enabled').addEventListener('change', action(async () => {
  if (!state.ready || state.busy || state.pending || !state.capabilities.prefix) return;
  state.pending = 'prefix'; state.ready = false; updateConnection();
  try { await state.transport.write(`:prefix ${$('prefix-enabled').checked ? 1 : 0}`); }
  catch (error) { await connectionLost(error.message); }
}));
$('timeout-apply').addEventListener('click', action(async () => {
  const seconds = Number($('timeout-seconds').value);
  if (!Number.isInteger(seconds) || seconds < 1 || seconds > 86400) throw new Error('请求期限应为 1–86400 秒');
  if (!state.ready || state.busy || state.pending || !state.capabilities.timeout) return;
  state.pending = 'timeout'; state.ready = false; updateConnection();
  try { await state.transport.write(`:timeout ${seconds}`); }
  catch (error) { await connectionLost(error.message); }
}));
$('profile-phase').addEventListener('change', () => {
  const phase = $('profile-phase').value;
  renderProfile(state.profiles[phase] || (phase === 'CUMULATIVE' ? state.profile : null), phase);
});
$('run-button').addEventListener('click', action(run));
$('request-kind').addEventListener('change', updateInput); $('prompt').addEventListener('input', updateInput);
$('prompt').addEventListener('keydown', event => { if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) { event.preventDefault(); action(run)(); } });
document.querySelectorAll('[data-preset]').forEach(button => button.addEventListener('click', () => {
  document.querySelectorAll('[data-preset]').forEach(x => x.classList.toggle('selected', x === button));
  if (button.dataset.preset === 'token') { $('request-kind').value = 'ids'; $('prompt').value = '0 255 1023'; $('max-new').value = '1'; }
  else { $('request-kind').value = 'text'; $('max-new').value = '32'; $('prompt').value = button.dataset.preset === 'greeting' ? '你好' : ''; $('prompt').focus(); }
  updateInput();
}));
$('mode-live').addEventListener('click', action(() => setMode('live')));
$('mode-replay').addEventListener('click', action(() => setMode('replay')));
$('replay-select').addEventListener('change', () => selectReplay(true));
$('replay-play').addEventListener('click', action(playReplay)); $('replay-end').addEventListener('click', finishReplay);
$('log-button').addEventListener('click', () => { renderLog(); $('log-dialog').showModal(); });
$('export-button').addEventListener('click', action(exportRecord));
$('download-raw').addEventListener('click', action(() => { if (!state.log) throw new Error('暂无原始数据'); download(state.log, filename('txt'), 'text/plain;charset=utf-8'); }));
$('copy-result').addEventListener('click', action(async () => { if (!state.result) throw new Error('暂无完整结果'); await navigator.clipboard.writeText(state.result.text); toast('结果已复制'); }));
$('memory-button').addEventListener('click', action(async () => { if (!state.ready || state.busy || state.pending || state.mode !== 'live') return; state.pending = 'memory'; state.ready = false; updateConnection(); await state.transport.write(':memory'); }));
for (const id of ['import-button', 'history-import']) $(id).addEventListener('click', () => $('import-file').click());
$('import-file').addEventListener('change', action(async event => {
  const file = event.target.files[0]; event.target.value = ''; if (!file) return;
  if (file.size > 2 * 1024 * 1024) throw new Error('请选择 2 MiB 以内的记录');
  const text = new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer());
  await importRecord(file.name.endsWith('.json') ? JSON.parse(text) : { raw: text, command: file.name });
}));
$('present-button').addEventListener('click', action(async () => {
  if (document.fullscreenElement) await document.exitFullscreen(); else await document.documentElement.requestFullscreen();
}));
document.addEventListener('fullscreenchange', () => { $('present-button').querySelector('span').textContent = document.fullscreenElement ? '退出全屏' : '全屏演示'; });
$('record-button').addEventListener('click', action(async () => {
  if (recording?.state === 'recording') { recording.stop(); return; }
  if (!navigator.mediaDevices?.getDisplayMedia || !window.MediaRecorder) throw new Error('当前浏览器不支持页面录屏，请使用 Chrome/Edge 或系统录屏');
  recordingStream = await navigator.mediaDevices.getDisplayMedia({ video: { frameRate: 30 }, audio: false });
  const mimeType = ['video/webm;codecs=vp9', 'video/webm;codecs=vp8', 'video/webm'].find(x => MediaRecorder.isTypeSupported(x));
  recording = new MediaRecorder(recordingStream, mimeType ? { mimeType } : {});
  const chunks = []; recording.ondataavailable = e => { if (e.data.size) chunks.push(e.data); };
  recording.onstop = () => { download(new Blob(chunks, { type: recording.mimeType }), filename('webm'), recording.mimeType); recordingStream.getTracks().forEach(t => t.stop()); $('record-button').classList.remove('recording'); $('record-button').querySelector('span').textContent = '录制演示'; toast('录屏已保存'); };
  recording.onerror = () => { recordingStream.getTracks().forEach(t => t.stop()); toast('录屏发生错误，请使用系统录屏'); };
  recordingStream.getVideoTracks()[0].addEventListener('ended', () => { if (recording.state === 'recording') recording.stop(); });
  recording.start(1000); recordingStart = Date.now(); $('record-button').classList.add('recording');
  toast('正在录制，点击顶部按钮结束并保存');
}));
function closeCamera() { cameraStream?.getTracks().forEach(t => t.stop()); cameraStream = null; $('board-video').srcObject = null; $('camera-dock').hidden = true; }
$('camera-button').addEventListener('click', action(async () => {
  if (cameraStream) return closeCamera();
  if (!navigator.mediaDevices?.getUserMedia) throw new Error('当前浏览器无法访问摄像头');
  cameraStream = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 360 }, audio: false });
  $('board-video').srcObject = cameraStream; $('camera-dock').hidden = false;
}));
$('camera-close').addEventListener('click', closeCamera);
window.addEventListener('beforeunload', event => { if (state.busy || recording?.state === 'recording') { event.preventDefault(); event.returnValue = ''; } });
window.addEventListener('pagehide', () => { closeCamera(); recordingStream?.getTracks().forEach(t => t.stop()); });
setInterval(() => {
  if (state.busy && state.mode === 'live') { const seconds = Math.floor((performance.now() - state.started) / 1000); $('running-clock').textContent = `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`; }
  if (recording?.state === 'recording') { const s = Math.floor((Date.now() - recordingStart) / 1000); $('record-button').querySelector('span').textContent = `结束录制 ${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`; }
}, 500);

async function init() {
  bootstrap = fetch('/api/bootstrap').then(async response => { if (!response.ok) throw new Error('本地服务未就绪'); return response.json(); });
  const response = await fetch('replays.json'); if (!response.ok) throw new Error('内置实板回放加载失败');
  state.samples = await response.json();
  for (const sample of state.samples) $('replay-select').add(new Option(sample.title, sample.id));
  updateInput(); updateConnection(); renderStats(null); renderHistory();
  await bootstrap;
}
init().catch(error => toast(error.message));
