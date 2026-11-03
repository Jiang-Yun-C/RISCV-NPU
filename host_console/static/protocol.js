/* T25 UART framing. No model inference, invented tokens or timer-based progress. */
export const CLOCK = 125000000;
export const LED_BANK_MASK = 0x2d;
export const LED_CHANNELS = Object.freeze([
  { bit:0, label:'LED0', pin:'A20' }, { bit:2, label:'LED2', pin:'C19' },
  { bit:3, label:'LED3', pin:'E18' }, { bit:5, label:'LED5', pin:'A18' }
]);
export function validLedMask(mask) {
  return Number.isInteger(mask) && mask > 0 && mask <= LED_BANK_MASK && (mask & ~LED_BANK_MASK) === 0;
}
export function ledBankCommand(operation, mask, values = 0) {
  if (!validLedMask(mask)) throw new Error('请勾选至少一个已支持的灯');
  if (operation === 'query') return ':ledm?';
  if (operation === 'auto') return ':ledauto ' + mask;
  if (operation !== 'set' || !Number.isInteger(values) || values < 0 || values > LED_BANK_MASK || (values & ~mask) !== 0) throw new Error('灯控值不属于勾选目标');
  return `:ledm ${mask} ${values}`;
}
function bankRequest(command) {
  if (command === ':ledm?') return { operation:'query', mask:LED_BANK_MASK };
  let m = /^:ledm ([0-9]+) ([0-9]+)$/.exec(command || '');
  if (m) { const mask=Number(m[1]),values=Number(m[2]); ledBankCommand('set',mask,values); return { operation:'set',mask,values }; }
  m = /^:(ledauto|actm) ([0-9]+)(?: (.*))?$/.exec(command || '');
  if (!m) return null;
  const mask=Number(m[2]); if(!validLedMask(mask) || (m[1] === 'ledauto' ? m[3] !== undefined : !m[3]?.trim())) throw new Error('多灯请求目标或正文无效');
  return { operation:m[1] === 'actm' ? 'action' : 'auto', mask };
}
export const MODEL = 'f55c1a1efd0188a3b792e695fb9f404080f0ffd10cae44d1831b595af6b37f71';
export const TOKENIZER = 'b0c60e70506c92e541c550f6e467eb60827f71415a16bf5cdf19d868535de6f1';

export function commandFor(kind, text, maximum = 1, capabilities = {}) {
  if (kind === 'action') {
    if (!text.trim() || /[\x00-\x1f\x7f]/.test(text)) throw new Error('请输入非空单行原文');
    const mask = capabilities.targetMask ?? 1;
    if (!validLedMask(mask) || (!capabilities.ledBank && mask !== 1)) throw new Error('当前固件不支持所选灯');
    const command = capabilities.ledBank ? `:actm ${mask} ${text}` : ':act ' + text;
    if (new TextEncoder().encode(command).length > 4096) throw new Error('包含命令头后超过4096 UTF-8字节');
    return command;
  }
  if (kind === 'ids') {
    const parts = text.trim().split(/\s+/);
    if (!parts.length || parts.length > 512 || parts.some(x => !/^\d+$/.test(x) || Number(x) > 151935))
      throw new Error('请输入 1–512 个十进制 token ID，每个 ID 在 0–151935 之间');
    if (!Number.isInteger(maximum) || maximum < 1 || maximum > 128) throw new Error('生成上限应为 1–128');
    const command = `:ids ${maximum} ${parts.map(Number).join(' ')}`;
    if (new TextEncoder().encode(command).length > 4096) throw new Error('请求超过 4096 字节');
    return command;
  }
  if (!text.trim() || (!capabilities.textMax && text.startsWith(':')) || /[\x00-\x1f\x7f]/.test(text))
    throw new Error('请输入单行中文或英文，请勿输入串口控制命令');
  if (new TextEncoder().encode(text).length > 4096) throw new Error('请求超过 4096 UTF-8 字节');
  if (capabilities.textMax) {
    if (!Number.isInteger(maximum) || maximum < 1 || maximum > 128) throw new Error('生成上限应为 1–128');
    const command = `:text ${maximum} ${text}`;
    if (new TextEncoder().encode(command).length > 4096) throw new Error('包含文本命令头后请求超过 4096 字节');
    return command;
  }
  return text;
}
export function cancelCommand(session) {
  if (typeof session !== 'string' || !/^[0-9a-f]{16}$/.test(session) || BigInt('0x' + session) === 0n)
    throw new Error('尚未取得当前板端会话身份');
  return ':cancel ' + session;
}

export function hexFields(text) {
  const result = {};
  for (const part of text.trim().split(/\s+/)) {
    const m = /^(\w+)=([0-9a-f]{16})$/.exec(part);
    if (!m || Object.hasOwn(result, m[1])) throw new Error('板端计数字段不完整或重复');
    const value = BigInt(`0x${m[2]}`);
    if (value > BigInt(Number.MAX_SAFE_INTEGER)) throw new Error('计数超出页面精确表示范围');
    result[m[1]] = Number(value);
  }
  return result;
}

// A chunk timestamp is the instant the transport's read returned. Rendering is
// separate: this parser never treats a preview, metadata, or hex digit as success.
const encoder = new TextEncoder();
const REQUEST_ABORT_STATUS = new Map([[0xfffffff5, 'cancelled'], [0xfffffff9, 'timeout']]);
const ascii = bytes => new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }).decode(bytes);
const STREAM_HEADER = /^T25 STREAM 1 (BEGIN|TOKEN|TEXT|END|ABORT) session=([0-9a-f]{16}) sequence=([0-9a-f]{16}) index=([0-9a-f]{16}) ticks=([0-9a-f]{16}) token=([0-9a-f]{16}) error=([0-9a-f]{16}) data=/;
export function hasVisibleCharacter(text) {
  // Unicode separators, controls/format characters, isolated combining marks,
  // variation selectors and replacement characters do not count as a first glyph.
  return [...text].some(c => !/[\s\p{C}\p{M}\uFFFD]/u.test(c));
}
function streamHeader(line) {
  const m = STREAM_HEADER.exec(line);
  if (!m) return null;
  const [kind, session, sequence, indexHex, ticksHex, tokenHex, errorHex] = m.slice(1);
  const index = BigInt('0x' + indexHex), token = BigInt('0x' + tokenHex), error = BigInt('0x' + errorHex);
  if (index > 128n || token > 0xffffffffn || error > 0xffffffffn || BigInt('0x' + session) === 0n || BigInt('0x' + sequence) === 0n)
    throw new Error('流式事件字段超出范围');
  return { kind, session, sequence, index: Number(index), ticks: BigInt('0x' + ticksHex), token: Number(token), error: Number(error), headerBytes: m[0].length };
}

export class T25Parser {
  constructor(emit = () => {}) { this.emit = emit; this.reset(); }
  reset() {
    this.buffer = new Uint8Array(); this.capabilities = {}; this.ledCapabilities = null; this.bankCapabilities = null; this.bankSnapshot = null; this.previousIdentity = null;
    this.chunk = null; this.recoveryFloor = null; this.lastCompletedRequest = null;
    this.lateControlSession = null; this.halted = false; this.unrecoveredAbort = false; this.clearRequest();
  }
  clearRequest() {
    this.text = this.ids = this.metrics = null; this.failed = null; this.steps = [];
    this.collectingText = false; this.activity = false; this.stream = null;
    this.partial = null; this.textLength = null; this.finalFrame = null; this.timing = null;
    this.requestInfo = null; this.profiles = {}; this.prefix = null; this.pmu = {}; this.transfer = null;
    this.actionReceipt = null; this.directReceipt = null; this.expectedMode = null;
    this.expectedDirect = null; this.expectedBank = null; this.received = null; this.phase = null;
    this.abortInfo = null; this.requestEnd = null; this.cancelControl = null;
    this.terminationDiagnostics = []; this.unexpectedFailure = false; this.unprovenTermination = false;
  }
  expectRequest(mode, command = null) {
    if (this.activity || this.requestInfo || this.expectedMode || this.lateControlSession || this.halted || this.unrecoveredAbort) throw new Error('已有未完成请求或板端未确认恢复');
    const bank = bankRequest(command);
    if (bank && ((mode === 'action') !== (bank.operation === 'action') || !['direct','action'].includes(mode))) throw new Error('多灯请求模式不匹配');
    if (mode === 'direct' && command !== null && !bank && ![':led?', ':led 0', ':led 1'].includes(command)) throw new Error('直接控制命令无效');
    this.expectedMode = mode; this.expectedBank = bank;
    if (bank && this.bankSnapshot) bank.previous = { ...this.bankSnapshot };
    if (mode === 'direct' && !bank) this.expectedDirect = command;
  }
  send(event) { this.emit({ ...event, chunk: this.chunk }); }
  feed(bytes, chunk = null) {
    if (!(bytes instanceof Uint8Array)) bytes = new Uint8Array(bytes);
    this.chunk = chunk;
    try {
      const joined = new Uint8Array(this.buffer.length + bytes.length);
      joined.set(this.buffer); joined.set(bytes, this.buffer.length); this.buffer = joined;
      for (;;) {
        if (this.finalFrame) { if (!this.consumeFinal()) break; continue; }
        const index = this.buffer.indexOf(10);
        if (index < 0) { this.previewPartial(this.buffer, false); break; }
        const raw = this.buffer.slice(0, index);
        this.previewPartial(raw, true);
        const line = ascii(raw).replace(/\r$/, '');
        this.buffer = this.buffer.slice(index + 1);
        this.line(line); this.partial = null;
      }
      if (this.buffer.length > 65536) throw new Error('板端输出行超过 64 KiB');
    } catch (error) {
      this.failed = error.message;
      this.send({ type: 'error', message: error.message, fatal: true });
      throw error;
    }
  }
  finish() {
    if (this.buffer.length || this.finalFrame || this.partial) throw new Error('记录以不完整串口帧结束');
    if (this.activity || this.requestInfo || this.expectedMode || this.directReceipt || this.received || this.lateControlSession) throw new Error('记录缺少完成请求的 T25 READY');
  }
  validateHeader(e) {
    const s = this.stream;
    if (!s || (s.ended && e.kind !== 'ABORT') || s.aborted || e.session !== s.session || e.sequence !== s.sequence)
      throw new Error('流式事件的会话身份或顺序不匹配');
    if (e.ticks < s.lastTicks) throw new Error('流式事件时钟倒退');
    if (e.kind !== 'ABORT' && e.error !== 0) throw new Error('成功流式事件带有错误码');
    if (e.kind === 'TOKEN') {
      if (s.flushed) throw new Error('结束解码后出现新的 token');
      if (e.index !== s.ids.length + 1 || e.token > 151935) throw new Error('流式 token 缺失、重复或越界');
    } else if (e.index !== s.ids.length) throw new Error('流式事件 token 索引不匹配');
    if (e.kind === 'TEXT' && (s.flushed || (s.lastTextIndex === e.index && e.token !== 0xffffffff))) throw new Error('重复的流式文本帧');
    if (e.kind === 'TEXT' && (e.token !== 0xffffffff && (!s.ids.length || e.token !== s.ids.at(-1))))
      throw new Error('流式文本不属于最近的 token');
  }
  previewPartial(raw, final) {
    if (this.collectingText || !raw.length) return;
    // Headers are ASCII; avoid decoding a partially received legacy UTF-8 line.
    const prefix = 'T25 STREAM 1 TEXT ';
    for (let i = 0; i < Math.min(prefix.length, raw.length); i++) if (raw[i] !== prefix.charCodeAt(i)) return;
    if (raw.length < prefix.length) return;
    const line = String.fromCharCode(...raw);
    if (!this.partial) {
      const e = streamHeader(line);
      if (!e) { if (final) throw new Error('流式文本头不完整'); return; }
      this.validateHeader(e);
      this.partial = { ...e, consumed: 0, text: '', decoder: new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }) };
    }
    const p = this.partial, data = line.slice(p.headerBytes);
    if (!/^[0-9a-f]*$/.test(data) || (final && (!data.length || data.length % 2))) throw new Error('流式文本不是完整的十六进制字节');
    if (data.length > 32768) throw new Error('流式文本超出容量');
    const end = data.length - data.length % 2;
    if (end > p.consumed) {
      const bytes = Uint8Array.from(data.slice(p.consumed, end).match(/../g), x => parseInt(x, 16));
      const fragment = p.decoder.decode(bytes, { stream: true }); p.consumed = end;
      if (fragment) {
        p.text += fragment; this.stream.text += fragment;
        if (encoder.encode(this.stream.text).length > 16384) throw new Error('流式正文超出容量');
        this.send({ type: 'preview', text: this.stream.text, fragment, visible: hasVisibleCharacter(fragment), provisional: true, index: p.index });
      }
    }
    if (final) {
      const tail = p.decoder.decode(); // A TEXT frame must end on a complete UTF-8 scalar.
      if (tail) throw new Error('流式文本末尾解码状态异常');
    }
  }
  consumeFinal() {
    const f = this.finalFrame, prefix = encoder.encode('T25 TEXT ');
    if (f.stage === 'prefix') {
      for (let i = 0; i < Math.min(prefix.length, this.buffer.length); i++)
        if (this.buffer[i] !== prefix[i]) throw new Error('TEXTLEN 后缺少正文头');
      if (this.buffer.length < prefix.length) return false;
      this.buffer = this.buffer.slice(prefix.length); f.stage = 'body';
    }
    if (f.stage === 'body') {
      const count = Math.min(f.remaining, this.buffer.length);
      if (count) {
        const fragment = f.decoder.decode(this.buffer.slice(0, count), { stream: true });
        f.text += fragment; f.remaining -= count; this.buffer = this.buffer.slice(count);
        if (fragment && !this.stream)
          this.send({ type: 'preview', text: f.text, fragment, visible: hasVisibleCharacter(fragment), provisional: true, buffered: true });
      }
      if (f.remaining) return false;
      f.text += f.decoder.decode(); f.stage = 'newline';
    }
    if (!this.buffer.length) return false;
    if (this.buffer[0] !== 10) throw new Error('正文长度与 TEXTLEN 不一致');
    this.buffer = this.buffer.slice(1); this.text = f.text; this.finalFrame = null;
    this.send({ type: 'line', line: 'T25 TEXT ' + this.text });
    if (this.stream && this.text !== this.stream.text) throw new Error('流式预览与最终正文不一致');
    return true;
  }
  streamLine(line) {
    const e = streamHeader(line);
    if (!e) throw new Error('流式事件头不完整');
    const data = line.slice(e.headerBytes);
    if (e.kind !== 'TEXT' && data !== '-') throw new Error('非文本流式事件包含正文');
    if (this.requestEnd) throw new Error('恢复完成记录之后出现旧流式事件');
    if (e.kind === 'BEGIN') {
      if (this.stream || this.activity || e.index !== 0 || e.token !== 0 || e.error !== 0) throw new Error('无效或重复的流式 BEGIN');
      if (this.previousIdentity && (e.session < this.previousIdentity.session ||
          (e.session === this.previousIdentity.session && e.sequence <= this.previousIdentity.sequence))) throw new Error('重复或过期的流式会话');
      if (this.requestInfo && this.requestInfo.sessionHex !== e.session) throw new Error('请求声明与流式会话不匹配');
      if (this.recoveryFloor && e.session < this.recoveryFloor) throw new Error('流式会话早于已恢复会话');
      this.previousIdentity = { session: e.session, sequence: e.sequence };
      this.stream = { session: e.session, sequence: e.sequence, ids: [], text: '', ended: false, aborted: false, lastTicks: e.ticks };
      this.activity = true; this.send({ type: 'stream_begin', session: e.session, sequence: e.sequence });
      return;
    }
    // Stream-off requests still publish one terminal ABORT. It acknowledges
    // the real request identity; its index does not invent received tokens.
    if (e.kind === 'ABORT' && !this.stream) {
      if (!this.requestInfo || this.requestInfo.sessionHex !== e.session || this.abortInfo ||
          !e.error || e.token !== 0 || !REQUEST_ABORT_STATUS.has(e.error) ||
          (this.ids !== null && this.ids.length !== e.index)) throw new Error('非流式终止帧缺少匹配请求或原因');
      this.activity = true; this.abortInfo = { ...e, streamed:false };
      this.failed = `板端请求终止（0x${e.error.toString(16)}）`;
      this.send({ type:'request_aborted', abort:this.abortInfo, status:REQUEST_ABORT_STATUS.get(e.error), provisional:true });
      return;
    }
    this.validateHeader(e); const s = this.stream; s.lastTicks = e.ticks;
    if (e.kind === 'TOKEN') { s.ids.push(e.token); this.send({ type: 'token', index: e.index, token: e.token }); }
    else if (e.kind === 'TEXT') { if (!this.partial) throw new Error('流式文本未解码'); s.lastTextIndex = e.index; if (e.token === 0xffffffff) s.flushed = true; }
    else if (e.kind === 'END') { s.ended = true; this.send({ type: 'stream_end' }); }
    else {
      if (!e.error || e.token !== 0) throw new Error('ABORT 缺少错误码或 token 字段无效');
      s.aborted = true; this.failed = `板端流式请求终止（0x${e.error.toString(16)}）`;
      this.abortInfo = { ...e, streamed:true };
      if (REQUEST_ABORT_STATUS.has(e.error))
        this.send({ type:'request_aborted', abort:this.abortInfo, status:REQUEST_ABORT_STATUS.get(e.error), provisional:true });
      else { this.unexpectedFailure = true; this.send({ type: 'error', message: this.failed, fatal: false }); }
    }
  }
  line(line) {
    this.send({ type: 'line', line });
    // Legacy recordings have no byte length. Preserve their existing METRICS boundary.
    if (this.collectingText && !line.startsWith('T25 METRICS ')) { this.text += '\n' + line; return; }
    if (this.requestEnd && /^(?:T25 (?:REQUEST |REQUEST_END |CONTROL |STREAM |PHASE |RECEIVED |TEXTLEN |IDS |METRICS |TEXT )|T27 (?:ACTION|ACTION_BANK|LED|LED_BANK) )/.test(line))
      throw new Error('恢复完成记录之后出现重复终止或旧请求数据');
    if (line.startsWith('T27 LED_BANK_CAPABILITIES ')) {
      const m = /^T27 LED_BANK_CAPABILITIES 1 mask=([0-9a-f]{16}) atomic=1 targets=explicit$/.exec(line);
      if (!m || BigInt('0x'+m[1]) !== BigInt(LED_BANK_MASK)) throw new Error('多灯能力或目标掩码不匹配');
      this.bankCapabilities = { mask:LED_BANK_MASK, atomic:true, targets:'explicit' };
      this.send({ type:'led_bank_capabilities', capabilities:this.bankCapabilities });
    } else if (/^T27 (LED_BANK|ACTION_BANK) /.test(line)) {
      const m = /^T27 (LED_BANK|ACTION_BANK) 1 session=([0-9a-f]{16}) status=(OK|FORMAT|RANGE|UNSUPPORTED|STATE|STALE|NACK|TIMEOUT|DUPLICATE|REQUEST_ID|CANCELLED|INCOMPLETE) writes=([0-9a-f]{16}) mask=([0-9a-f]{16}) values=([0-9a-f]{16}) owned=([0-9a-f]{16})\s*$/.exec(line);
      if (!m) throw new Error('多灯回执格式错误');
      const numbers=m.slice(4).map(v=>BigInt('0x'+v));
      if (numbers.some(v=>v>0xffffffffn)) throw new Error('多灯回执数值越界');
      const [writes,mask,rawValues,rawOwned]=numbers.map(Number), unknown=0xffffffff;
      if (writes>8 || !validLedMask(mask) ||
          (rawValues !== unknown && (rawValues & ~LED_BANK_MASK) !== 0) ||
          (rawOwned !== unknown && (rawOwned & ~LED_BANK_MASK) !== 0) ||
          (rawValues !== unknown && rawOwned !== unknown && (rawValues & ~rawOwned) !== 0) ||
          (m[3] === 'OK' && (rawValues === unknown || rawOwned === unknown))) throw new Error('多灯回执字段无效');
      const receipt={ kind:m[1],session:m[2],status:m[3],writes,mask,values:rawValues===unknown?null:rawValues,owned:rawOwned===unknown?null:rawOwned,bank:true,raw:line };
      const expected=this.expectedBank;
      if (this.expectedMode && (!expected || expected.mask !== mask)) throw new Error('多灯回执与勾选目标不一致');
      if (receipt.status === 'OK' && expected?.previous) {
        const outside = LED_BANK_MASK & ~mask;
        if (((receipt.values ^ expected.previous.values) & outside) || ((receipt.owned ^ expected.previous.owned) & outside))
          throw new Error('回执改变了未选灯的接管或状态字');
      }
      if (m[1] === 'ACTION_BANK') {
        if (this.actionReceipt || this.text === null || (!this.requestInfo && !this.stream) ||
            m[2] !== (this.requestInfo?.sessionHex || this.stream.session) || this.expectedMode === 'text' || this.expectedMode === 'direct') throw new Error('多灯动作会话或顺序不匹配');
        this.actionReceipt=receipt;
      } else {
        if (this.directReceipt || this.activity || this.requestInfo || (this.expectedMode && this.expectedMode !== 'direct') || writes>1) throw new Error('多灯直接回执与当前操作不匹配');
        if (this.recoveryFloor && receipt.session < this.recoveryFloor) throw new Error('直接回执早于已恢复会话');
        if (receipt.status === 'OK' && expected) {
          if (writes !== (expected.operation === 'query' ? 0 : 1)) throw new Error('多灯直接写次数不匹配');
          if (expected.operation === 'set' && ((receipt.owned & mask) !== mask || (receipt.values & mask) !== expected.values)) throw new Error('多灯接管或目标读回不匹配');
          if (expected.operation === 'auto' && ((receipt.owned & mask) !== 0 || (receipt.values & mask) !== 0)) throw new Error('多灯恢复自动指示未确认');
        }
        this.directReceipt=receipt;
      }
      this.send({type:'action_receipt',receipt,provisional:true});
    } else if (line.startsWith('T27 LED_CAPABILITIES ')) {
      const m = /^T27 LED_CAPABILITIES 1 direct=([01]) action=([01]) abi=LED1 pin=A20 active_high=1$/.exec(line);
      if (!m) throw new Error('灯控能力协议不匹配');
      this.ledCapabilities = { direct: m[1] === '1', action: m[2] === '1', abi: 'LED1', pin: 'A20', activeHigh: true };
      this.send({ type: 'led_capabilities', capabilities: this.ledCapabilities });
    } else if (/^T27 (ACTION|LED) /.test(line)) {
      if (this.expectedBank) throw new Error('单灯回执不能代替多灯目标回执');
      const m = /^T27 (ACTION|LED) 1 session=([0-9a-f]{16}) status=(OK|FORMAT|RANGE|UNSUPPORTED|STATE|STALE|NACK|TIMEOUT|DUPLICATE|REQUEST_ID|CANCELLED|INCOMPLETE) writes=([0-9a-f]{16})(?: state=([0-9a-f]{16}))?\s*$/.exec(line);
      if (!m) throw new Error('灯控回执格式错误');
      const writes = BigInt('0x' + m[4]), state = m[5] === undefined ? null : BigInt('0x' + m[5]);
      if (writes > 8n || (state !== null && ![0n, 1n, 0xffffffffn].includes(state)) ||
          (state === null && (!['TIMEOUT','CANCELLED','INCOMPLETE'].includes(m[3]) || writes !== 0n))) throw new Error('灯控回执字段越界');
      const receipt = { kind: m[1], session: m[2], status: m[3], writes: Number(writes), state: state === null || state === 0xffffffffn ? null : Number(state), raw: line };
      if (m[1] === 'ACTION') {
        if (this.actionReceipt || this.text === null || (!this.requestInfo && !this.stream) ||
            m[2] !== (this.requestInfo?.sessionHex || this.stream.session) || this.expectedMode === 'text') throw new Error('动作回执会话或顺序不匹配');
        this.actionReceipt = receipt;
      } else {
        if (this.directReceipt || this.activity || this.requestInfo || (this.expectedMode && this.expectedMode !== 'direct')) throw new Error('直接控制回执与当前操作不匹配');
        if (this.recoveryFloor && receipt.session < this.recoveryFloor) throw new Error('直接回执早于已恢复会话');
        if (receipt.writes > 1 || (receipt.status === 'OK' && receipt.state === null)) throw new Error('直接控制写次数或读回无效');
        if (this.expectedDirect && receipt.status === 'OK' &&
            (receipt.writes !== (this.expectedDirect === ':led?' ? 0 : 1) ||
             (this.expectedDirect !== ':led?' && receipt.state !== Number(this.expectedDirect.at(-1)))))
          throw new Error('直接控制回执与请求的写次数或目标状态不一致');
        this.directReceipt = receipt;
      }
      this.send({ type: 'action_receipt', receipt, provisional: true });
    } else if (line.startsWith('T27 ')) {
      throw new Error('不支持的T27灯控协议');
    } else if (/^T25 (ERROR |TRAP |SD ERROR |NOT_READY )/.test(line) || line === 'D27 HALTED') {
      const code = /^T25 ERROR ([0-9a-f]{8})$/.exec(line);
      if (code && this.abortInfo && parseInt(code[1], 16) === this.abortInfo.error && REQUEST_ABORT_STATUS.has(this.abortInfo.error)) {
        if (this.requestEnd || this.terminationDiagnostics.length) throw new Error('重复或迟到的终止错误诊断');
        this.terminationDiagnostics.push(line);
        this.send({ type:'termination_diagnostic', message:line, session:this.abortInfo.session, status:REQUEST_ABORT_STATUS.get(this.abortInfo.error) });
        return;
      }
      this.failed = line;
      if (code && this.requestInfo && REQUEST_ABORT_STATUS.has(parseInt(code[1], 16))) this.unprovenTermination = true;
      this.unexpectedFailure = true;
      if (line === 'D27 HALTED' || line.startsWith('T25 TRAP ')) this.halted = true;
      this.send({ type: 'error', message: line, fatal: this.halted });
    } else if (/^D27 (?:RECOVERY|FAULT|TRAP)\b/.test(line)) {
      this.unexpectedFailure = true; this.failed = line;
      this.send({ type:'error', message:line, fatal:false });
    } else if (line.startsWith('T25 SERVICE ')) {
      this.send({ type: 'service', value: line.slice(12) });
    } else if (line.startsWith('T25 CAPABILITIES ')) {
      const fields = {}, mapping = { stream: 'stream', text_max: 'textMax', cancel: 'cancel', prefix: 'prefix', profile: 'profile', timeout: 'timeout', identity: 'identity', received: 'received', phase: 'phase' };
      for (const item of line.slice(17).split(' ')) {
        const m = /^(\w+)=([01])$/.exec(item);
        if (!m || !Object.hasOwn(mapping, m[1]) || Object.hasOwn(fields, m[1])) throw new Error('能力声明格式错误');
        fields[m[1]] = m[2] === '1';
      }
      if (!Object.hasOwn(fields, 'stream') || !Object.hasOwn(fields, 'text_max')) throw new Error('能力声明缺少基础字段');
      this.capabilities = Object.fromEntries(Object.entries(mapping).map(([k, v]) => [v, fields[k] === true]));
      this.send({ type: 'capabilities', ...this.capabilities });
    } else if (line.startsWith('T25 RECEIVED ')) {
      const m = /^T25 RECEIVED 1 kind=(text|action)$/.exec(line);
      if (!m || this.received || this.requestInfo || this.activity ||
          (this.expectedMode && this.expectedMode !== m[1])) throw new Error('接收确认种类或顺序无效');
      this.received = m[1]; this.send({ type: 'received', kind: m[1] });
    } else if (line.startsWith('T25 PHASE ')) {
      const m = /^T25 PHASE 1 session=([0-9a-f]{16}) stage=(prefill|decode|validating|executing)$/.exec(line);
      const stages = ['prefill','decode','validating','executing'];
      if (!m || !this.requestInfo || m[1] !== this.requestInfo.sessionHex ||
          stages.indexOf(m[2]) <= stages.indexOf(this.phase) ||
          (m[2] === 'executing' && this.expectedMode === 'text')) throw new Error('处理阶段会话或顺序无效');
      this.phase = m[2]; this.send({ type: 'phase', stage: m[2], session: m[1] });
    } else if (line.startsWith('T25 REQUEST 1 ')) {
      if (this.requestInfo || this.activity || this.unrecoveredAbort) throw new Error('重复、迟到或恢复未确认的请求声明');
      const fields = hexFields(line.slice(14)), match = /(?:^| )session=([0-9a-f]{16})(?: |$)/.exec(line.slice(14));
      if (!match || !fields.session || !fields.timeout_ticks || ![0, 1].includes(fields.prefix_hit) ||
          !Number.isInteger(fields.prefix_tokens) || fields.prefix_tokens > 512 || (fields.prefix_hit && !fields.prefix_tokens)) throw new Error('请求声明字段无效');
      if (this.recoveryFloor && match[1] < this.recoveryFloor) throw new Error('请求会话早于已恢复会话');
      this.requestInfo = { ...fields, sessionHex: match[1] };
      this.send({ type: 'request', request: this.requestInfo });
    } else if (line.startsWith('T25 CONTROL 1 ')) {
      const m = /^T25 CONTROL 1 session=([0-9a-f]{16}) status=(accepted|finished|stale|rejected)$/.exec(line);
      if (!m) throw new Error('取消响应格式错误');
      const active = this.requestInfo?.sessionHex === m[1];
      if (m[2] === 'accepted') {
        if (!active || this.cancelControl || this.abortInfo || this.requestEnd) throw new Error('取消响应会话或顺序不匹配');
        this.cancelControl = { session:m[1], status:m[2] };
      } else if (m[2] === 'finished') {
        if (this.cancelControl || this.abortInfo || this.requestEnd || (!active && (this.expectedMode ||
            (!this.lastCompletedRequest?.complete && !['cancelled','timeout'].includes(this.lastCompletedRequest?.status)) || this.lastCompletedRequest.session !== m[1])))
          throw new Error('已完成取消响应缺少同会话正常结果');
        if (active) this.cancelControl = { session:m[1], status:m[2] };
        else {
          if (this.lateControlSession) throw new Error('重复的迟到取消回复');
          this.lateControlSession = m[1];
        }
      } else if (!this.requestInfo && this.lastCompletedRequest?.session === m[1]) {
        if (this.lateControlSession) throw new Error('重复的迟到取消回复');
        this.lateControlSession = m[1];
      }
      this.send({ type: 'control', session: m[1], status: m[2], late:!this.requestInfo });
    } else if (line.startsWith('T25 REQUEST_END ')) {
      const m = /^T25 REQUEST_END 1 session=([0-9a-f]{16}) next_session=([0-9a-f]{16}) status=(cancelled|timeout)\s*$/.exec(line);
      if (!m || !this.requestInfo || !this.abortInfo || this.requestEnd || this.unexpectedFailure || this.halted ||
          m[1] !== this.requestInfo.sessionHex || m[1] !== this.abortInfo.session ||
          BigInt('0x' + m[2]) !== BigInt('0x' + m[1]) + 1n ||
          REQUEST_ABORT_STATUS.get(this.abortInfo.error) !== m[3] || this.metrics ||
          (this.actionReceipt && (this.actionReceipt.writes !== 0 || this.actionReceipt.status !== (m[3] === 'cancelled' ? 'CANCELLED' : 'TIMEOUT'))))
        throw new Error('请求恢复完成记录的身份、原因、顺序或零写入条件不匹配');
      this.requestEnd = { session:m[1], nextSession:m[2], status:m[3] };
      this.send({ type:'request_end', termination:this.requestEnd, provisional:true });
    } else if (line.startsWith('T25 CONFIG 1 ')) {
      this.send({ type: 'configuration', values: hexFields(line.slice(13)) });
    } else if (line.startsWith('T25 STREAM 1 ')) {
      this.streamLine(line);
    } else if (line.startsWith('T25 STREAM ')) {
      throw new Error('不支持的流式协议版本');
    } else if (line.startsWith('T25 TEXTLEN ')) {
      const m = /^T25 TEXTLEN 1 bytes=([0-9a-f]{16})\s*$/.exec(line);
      if (!m || this.textLength !== null || this.text !== null || BigInt('0x' + m[1]) > 16384n) throw new Error('正文长度记录无效');
      this.textLength = Number(BigInt('0x' + m[1])); this.activity = true;
      this.finalFrame = { stage: 'prefix', remaining: this.textLength, text: '', decoder: new TextDecoder('utf-8', { fatal: true, ignoreBOM: true }) };
    } else if (line.startsWith('T25 TIME 1 ')) {
      if (this.timing) throw new Error('重复的流式计时记录');
      const parts = line.slice(11).trim().split(/\s+/), fields = {};
      for (const part of parts) {
        const m = /^(\w+)=(.*)$/.exec(part);
        if (!m || Object.hasOwn(fields, m[1])) throw new Error('流式计时字段无效');
        if (m[1] === 'tokens') {
          if (m[2] !== '-' && !/^[0-9a-f]{16}(,[0-9a-f]{16})*$/.test(m[2])) throw new Error('token 计时数组无效');
          fields.tokens = m[2] === '-' ? [] : m[2].split(',');
        } else { if (!/^[0-9a-f]{16}$/.test(m[2])) throw new Error('流式计时字段无效'); fields[m[1]] = m[2]; }
      }
      if (this.stream && (fields.session !== this.stream.session || fields.sequence !== this.stream.sequence)) throw new Error('计时会话不匹配');
      this.timing = fields; this.send({ type: 'timing', timing: fields });
    } else if (line.startsWith('T25 MODEL ')) {
      const m = /^T25 MODEL ([0-9a-f]{64}) TOKENIZER ([0-9a-f]{64})$/.exec(line);
      if (!m) throw new Error('模型身份记录格式错误');
      this.send({ type: 'identity', model: m[1], tokenizer: m[2], matches: m[1] === MODEL && m[2] === TOKENIZER });
    } else if (line.startsWith('T25 STEP ')) {
      const m = /^T25 STEP ([0-9a-f]{8}) ([0-9a-f]{8})$/.exec(line);
      if (!m) throw new Error('STEP 记录格式错误');
      const prefilled = parseInt(m[1], 16), generated = parseInt(m[2], 16), previous = this.steps.at(-1);
      if (prefilled > 512 || generated > 128 || (previous && (prefilled < previous.prefilled || generated < previous.generated))) throw new Error('STEP 计数超出范围或倒退');
      this.activity = true; this.steps.push({ prefilled, generated });
      this.send({ type: 'step', prefilled, generated, forwards: this.steps.length });
    } else if (line.startsWith('T25 IDS ')) {
      if (this.ids !== null) throw new Error('重复的输出 token 记录');
      const values = line.slice(8).trim();
      if (values && !/^[0-9a-f]{8}( [0-9a-f]{8})*$/.test(values)) throw new Error('输出 token 格式错误');
      this.ids = values ? values.split(' ').map(x => parseInt(x, 16)) : [];
      if (this.ids.length > 128 || this.ids.some(x => x > 151935)) throw new Error('输出 token 超出范围');
      if (this.stream && (this.ids.length !== this.stream.ids.length || this.ids.some((x, i) => x !== this.stream.ids[i]))) throw new Error('流式 token 与最终输出不一致');
      this.activity = true;
    } else if (line.startsWith('T25 TEXT ')) {
      if (this.text !== null || this.textLength !== null || this.stream) throw new Error('缺失正文长度或重复的输出文字记录');
      this.text = line.slice(9); this.collectingText = true; this.activity = true;
    } else if (line.startsWith('T25 METRICS ')) {
      if (this.metrics) throw new Error('重复的请求统计');
      this.collectingText = false; this.metrics = hexFields(line.slice(12));
      const m = this.metrics, required = ['prompt', 'generated', 'stop', 'kv', 'total_ticks', 'first_token_ticks', 'prefill_ticks', 'decode_ticks', 'ce_calls', 'fallback_calls'];
      if (required.some(x => !Object.hasOwn(m, x))) throw new Error('板端缺少关键请求统计');
      if (this.ids === null || this.text === null || m.generated !== this.ids.length || m.prompt < 1 || m.prompt + m.generated > 512 || m.generated > 128 || m.kv !== m.prompt + Math.max(0, m.generated - 1)) throw new Error('输出与请求统计不一致');
      const eos = this.ids.indexOf(151645);
      if (![1, 2, 3].includes(m.stop) || (eos >= 0 && (eos !== this.ids.length - 1 || m.stop !== 1)) ||
          (m.stop === 1 && eos !== this.ids.length - 1) || (m.stop === 1 && !m.generated) ||
          (m.stop === 2 && !m.generated) || (m.stop === 3 && m.prompt + m.generated !== 512) ||
          (!m.generated && m.prompt !== 512)) throw new Error('停止原因、EOS 或上下文长度不一致');
      if (this.requestInfo && m.session !== this.requestInfo.session) throw new Error('请求声明与最终统计身份不匹配');
      if (this.stream && (!this.stream.ended || this.stream.aborted || this.stream.text !== this.text || (m.session !== undefined && BigInt(m.session) !== BigInt('0x' + this.stream.session)))) throw new Error('流式请求尚未完整结束或身份不符');
      if (this.textLength === null) {
        const last = this.steps.at(-1);
        if (m.kv !== this.steps.length || !last || last.prefilled !== m.prompt || last.generated !== m.generated) throw new Error('计算步与最终请求统计不一致');
      }
      this.activity = true;
    } else if (line.startsWith('T25 PROFILE CUMULATIVE ')) {
      const pattern = /([0-9a-f]{8}) ticks=([0-9a-f]{16}) calls=([0-9a-f]{16})/g;
      const profile = [...line.matchAll(pattern)].map(m => ({ index: parseInt(m[1], 16), ...hexFields(`ticks=${m[2]} calls=${m[3]}`) }));
      if (profile.length !== 8 || profile.some((p, i) => p.index !== i)) throw new Error('算子统计缺项或乱序');
      this.send({ type: 'profile', profile, cumulative: true });
    } else if (line.startsWith('T25 PROFILE 1 ')) {
      const m = /^T25 PROFILE 1 (REQUEST|PREFILL|DECODE|CUMULATIVE) session=([0-9a-f]{16}) (.*)$/.exec(line);
      if (!m || this.profiles[m[1]] || !this.metrics || BigInt('0x' + m[2]) !== BigInt(this.metrics.session)) throw new Error('阶段统计身份或顺序无效');
      const pattern = /([0-9a-f]{8}) ticks=([0-9a-f]{16}) calls=([0-9a-f]{16}) /g;
      const matches = [...m[3].matchAll(pattern)];
      if (matches.map(x => x[0]).join('') !== m[3]) throw new Error('阶段统计格式错误');
      const profile = matches.map(x => ({ index: parseInt(x[1], 16), ...hexFields(`ticks=${x[2]} calls=${x[3]}`) }));
      if (profile.length !== 8 || profile.some((p, i) => p.index !== i)) throw new Error('阶段统计缺项或乱序');
      this.profiles[m[1]] = profile;
      this.send({ type: 'profile', profile, phase: m[1], cumulative: m[1] === 'CUMULATIVE' });
    } else if (line.startsWith('T25 PREFIX 1 ')) {
      if (this.prefix || !this.metrics) throw new Error('前缀统计顺序无效');
      const fields = hexFields(line.slice(13));
      if (fields.session !== this.metrics.session || ![0, 1].includes(fields.hit) || ![0, 1].includes(fields.captured) ||
          !Number.isInteger(fields.tokens) || fields.tokens > this.metrics.prompt || (fields.hit && (!fields.tokens || fields.captured)) ||
          !Object.hasOwn(fields, 'prepare_ticks') || !Object.hasOwn(fields, 'restore_ticks')) throw new Error('前缀统计字段无效');
      if (this.requestInfo && (fields.hit !== this.requestInfo.prefix_hit || fields.tokens !== this.requestInfo.prefix_tokens)) throw new Error('前缀命中统计不一致');
      this.prefix = fields; this.send({ type: 'prefix', prefix: fields });
    } else if (line.startsWith('T25 PMU 1 ')) {
      const m = /^T25 PMU 1 (STATUS|REQUEST|PREFILL|DECODE) (.*)$/.exec(line);
      if (!m || this.pmu[m[1]] || !this.requestInfo) throw new Error('PMU 记录顺序无效');
      const fields = hexFields(m[2]);
      if (fields.session !== this.requestInfo.session) throw new Error('PMU 请求身份不匹配');
      if (m[1] === 'STATUS') {
        if (![0, 1].includes(fields.available) || ![0, 1].includes(fields.valid) || (fields.valid && !fields.available)) throw new Error('PMU 状态无效');
      } else {
        const required = ['cycles','retired','execute_stall','branches','mispredicts','i_ar','i_r_beats','i_r_bytes','i_address_blocked',
          'd_ar','d_r_beats','d_r_bytes','d_aw','d_w_beats','d_w_bytes','d_address_blocked','ce_ar','ce_r_beats','ce_r_bytes',
          'ce_aw','ce_w_beats','ce_w_bytes','ce_address_blocked','response_errors'];
        if (!this.pmu.STATUS?.valid || fields.tag !== fields.session || !fields.sequence || required.some(k => !Object.hasOwn(fields,k))) throw new Error('PMU 快照身份或字段无效');
      }
      this.pmu[m[1]] = fields; this.send({ type: 'pmu', phase: m[1], values: fields });
    } else if (line.startsWith('T25 TRANSFER 1 ')) {
      if (this.transfer || !this.metrics) throw new Error('搬运统计顺序无效');
      const fields = hexFields(line.slice(15));
      const required = ['input_staged_bytes','input_saved_bytes','output_copy_bytes','output_saved_bytes',
        'input_staging_ticks','output_copy_ticks','backend_cycles','completed_calls','kv_output_saved_bytes','head_read_saved_bytes'];
      if (fields.session !== this.metrics.session || required.some(k => !Object.hasOwn(fields,k))) throw new Error('搬运统计会话或字段不匹配');
      this.transfer = fields; this.send({ type: 'transfer', values: fields });
    } else if (/^T25 (REQUEST|REQUEST_END|CONTROL|CONFIG|PROFILE|PREFIX|PMU|TRANSFER) /.test(line)) {
      throw new Error('不支持的服务统计协议版本');
    } else if (line.startsWith('T25 MEMORY committed_bytes=')) {
      this.send({ type: 'memory', values: hexFields(line.slice(11)) });
    } else if (line === 'T25 READY') {
      if (this.halted) throw new Error('板端已停止，READY 不能解除故障状态');
      if ((this.abortInfo && REQUEST_ABORT_STATUS.has(this.abortInfo.error)) || this.cancelControl?.status === 'accepted' || this.unprovenTermination) {
        if (!this.requestEnd || this.unexpectedFailure) throw new Error('终止后缺少同会话 REQUEST_END，不能恢复发送');
        const ended = this.requestEnd;
        this.recoveryFloor = ended.nextSession;
        this.lastCompletedRequest = { session:ended.session, complete:false, status:ended.status };
        this.bankSnapshot = null;
        this.send({ type:'terminated', ...ended, modelComplete:false, actionSucceeded:false,
          abort:this.abortInfo, action:this.actionReceipt, diagnostics:this.terminationDiagnostics,
          text:this.text ?? this.stream?.text ?? '', ids:this.ids, metrics:null, request:this.requestInfo });
        const controlSession = this.cancelControl?.session || null;
        this.clearRequest(); this.send({ type:'ready', terminalStatus:ended.status, session:ended.session, controlSession });
        return;
      }
      if (this.requestInfo && this.metrics && !this.failed) {
        if (this.capabilities.profile && Object.keys(this.profiles).length !== 4) throw new Error('声明支持的阶段统计缺失');
        if (this.capabilities.prefix && !this.prefix) throw new Error('声明支持的前缀统计缺失');
      }
      if (this.pmu.STATUS?.valid) {
        if (!this.pmu.REQUEST || !this.pmu.PREFILL || !this.pmu.DECODE || this.pmu.PREFILL.sequence > this.pmu.REQUEST.sequence || this.pmu.DECODE.sequence !== this.pmu.REQUEST.sequence) throw new Error('PMU 区间不完整');
        for (const key of Object.keys(this.pmu.REQUEST)) if (!['session','tag','sequence'].includes(key))
          if (this.pmu.REQUEST[key] !== this.pmu.PREFILL[key] + this.pmu.DECODE[key]) throw new Error('PMU 区间差分不一致');
      }
      if (Object.keys(this.profiles).length) {
        const all = ['REQUEST', 'PREFILL', 'DECODE', 'CUMULATIVE'];
        if (all.some(k => !this.profiles[k])) throw new Error('阶段统计不完整');
        for (let i = 0; i < 8; i++) for (const k of ['ticks', 'calls'])
          if (this.profiles.REQUEST[i][k] !== this.profiles.PREFILL[i][k] + this.profiles.DECODE[i][k] ||
              this.profiles.CUMULATIVE[i][k] < this.profiles.REQUEST[i][k]) throw new Error('请求与阶段计数不一致');
      }
      if (this.directReceipt) {
        this.bankSnapshot = this.directReceipt.bank && this.directReceipt.status === 'OK' ? { values:this.directReceipt.values, owned:this.directReceipt.owned } : null;
        this.send({ type: 'direct_result', receipt: this.directReceipt });
      }
      if (this.activity || this.failed || this.requestInfo || this.received || ['action','text'].includes(this.expectedMode)) {
        const modelComplete = !this.failed && this.metrics !== null && this.text !== null && this.ids !== null && (!this.stream || this.stream.ended);
        const actionExpected = this.expectedMode === 'action' || this.actionReceipt !== null;
        const action = this.actionReceipt;
        if (action && this.metrics && BigInt('0x' + action.session) !== BigInt(this.metrics.session)) throw new Error('动作与最终统计会话不匹配');
        let actionSucceeded = false;
        if (action?.status === 'OK') {
          let program; try { program = JSON.parse(this.text); } catch { throw new Error('OK回执缺少完整JSON'); }
          if (!Array.isArray(program) || program.length < 1 || program.length > 8 ||
              program.some(a => !Array.isArray(a) || a.length !== 2 || a[0] !== 'led' || ![0,1].includes(a[1])) ||
              action.writes !== program.length ||
              (action.bank ? (action.owned & action.mask) !== action.mask || (action.values & action.mask) !== (program.at(-1)[1] ? action.mask : 0) : action.state !== program.at(-1)[1]) ||
              this.metrics?.stop !== 1 || this.ids?.at(-1) !== 151645) throw new Error('动作OK回执与EOS/完整程序/写次数/读回不一致');
          actionSucceeded = modelComplete;
        }
        const complete = modelComplete && (!actionExpected || action !== null);
        const completedSession = this.requestInfo?.sessionHex || this.stream?.session;
        if (completedSession) this.lastCompletedRequest = { session:completedSession, complete };
        if (actionExpected || this.failed) this.bankSnapshot = actionSucceeded && action.bank ? { values:action.values, owned:action.owned } : null;
        this.send({ type: 'result', complete, modelComplete, actionSucceeded, action,
          error: this.failed || (!complete ? actionExpected && !action ? '缺少CPU ACTION回执' : '记录缺少完整输出或统计' : null),
          text: this.text ?? this.stream?.text ?? '', ids: this.ids, metrics: this.metrics, timing: this.timing, steps: this.steps, profiles: this.profiles, prefix: this.prefix, request: this.requestInfo, pmu: this.pmu, transfer: this.transfer });
      }
      const controlSession = this.cancelControl?.status === 'finished' ? this.cancelControl.session : this.lateControlSession;
      const safeToSend = !this.abortInfo && !this.unrecoveredAbort;
      if (!safeToSend) this.unrecoveredAbort = true;
      this.lateControlSession = null;
      this.clearRequest(); this.send({ type: 'ready', controlSession, safeToSend });
    } else if (line.startsWith('T25 SD ') || line.startsWith('T25 LOAD ')) {
      this.send({ type: 'boot', line });
    }
  }
}

export function metricValues(m) {
  if (!m) return null;
  return { seconds: m.total_ticks / CLOCK, first: m.generated ? m.first_token_ticks / CLOCK : null,
    speed: m.generated > 1 && m.decode_ticks > 0 ? (m.generated - 1) * CLOCK / m.decode_ticks : null,
    calls: m.ce_calls, fallback: m.fallback_calls };
}
