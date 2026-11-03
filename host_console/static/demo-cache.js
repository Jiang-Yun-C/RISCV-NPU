/* Pre-generated plain-text demonstrations only. No UART, DOM, timers or model
 * execution lives here. UART re-parsing checks record completeness, not the
 * authenticity of hardware or imported provenance. */
import { T25Parser, hasVisibleCharacter } from './protocol.js';

export const CACHE_SCHEMA = 'nexusrv-demo-cache';
export const CACHE_VERSION = 1;
export const CACHE_STORAGE_KEY = 'nexusrv-demo-cache-v1';
export const CACHE_LIMITS = Object.freeze({
  maxEntries: 16,
  maxWireBytes: 256 * 1024,
  maxChunks: 2048,
  maxTotalBytes: 2 * 1024 * 1024,
  maxImportBytes: 2 * 1024 * 1024,
  maxPromptBytes: 4096,
  maxTextBytes: 16384,
});
const enc = new TextEncoder();
const HEX = /^[0-9a-f]{64}$/;
const SOURCES = new Set(['pre_generated', 'historical_import', 'synthetic_fixture']);
const FIXTURE_SOURCES = new Set(['fake_serial', 'synthetic_fixture', 'test_fixture', 'testFixture']);
const entryKeys = ['id','kind','prompt','maxNewTokens','command','text','capturedAt','sourceRunId','observedIdentity','source','uart'];
const fail = message => { throw new Error(message); };
const object = value => value !== null && typeof value === 'object' && !Array.isArray(value);
const bytes = value => enc.encode(value).length;

function exactKeys(value, keys, name) {
  if (!object(value) || Object.keys(value).length !== keys.length || keys.some(key => !Object.hasOwn(value, key)))
    fail(name + '字段缺失或不受支持');
}
function unicode(text, name) {
  if (typeof text !== 'string') fail(name + '必须是文字');
  for (let i = 0; i < text.length; i++) {
    const code = text.charCodeAt(i);
    if (code >= 0xd800 && code <= 0xdbff) {
      const next = text.charCodeAt(++i);
      if (!(next >= 0xdc00 && next <= 0xdfff)) fail(name + '包含不完整 Unicode 字符');
    } else if (code >= 0xdc00 && code <= 0xdfff) fail(name + '包含不完整 Unicode 字符');
  }
  return text;
}
function request(prompt, maximum) {
  unicode(prompt, '问题');
  if (!prompt.trim() || /[\x00-\x1f\x7f\u0085\u2028\u2029]/u.test(prompt)) fail('问题必须是非空单行原文');
  if (!Number.isInteger(maximum) || maximum < 1 || maximum > 128) fail('生成上限必须为 1–128');
  const command = `:text ${maximum} ${prompt}`;
  if (bytes(command) > CACHE_LIMITS.maxPromptBytes) fail('包含命令头后问题超过 4096 UTF-8 字节');
  return command; // Never trim, normalize or case-fold an exact cache key.
}
function parseCommand(command) {
  if (typeof command !== 'string') fail('缺少原始普通文字命令');
  const match = /^:text ([1-9][0-9]{0,2}) ([\s\S]*)$/.exec(command);
  if (!match) fail('只能缓存 :text 普通文字请求');
  const maximum = Number(match[1]);
  if (request(match[2], maximum) !== command) fail('普通文字命令不一致');
  return { prompt: match[2], maxNewTokens: maximum, command };
}
function identity(value) {
  if (value == null) return null;
  exactKeys(value, ['model', 'tokenizer'], '已观测身份');
  if (!HEX.test(value.model) || !HEX.test(value.tokenizer)) fail('模型或分词器身份格式无效');
  return Object.freeze({ model: value.model, tokenizer: value.tokenizer });
}
const identityKey = value => value ? value.model + '/' + value.tokenizer : 'unobserved';
const key = entry => JSON.stringify([entry.prompt, entry.maxNewTokens, identityKey(entry.observedIdentity)]);
function timestamp(value) {
  if (typeof value !== 'string' || !/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$/.test(value) ||
      !Number.isFinite(Date.parse(value)) || new Date(value).toISOString() !== value) fail('采集时间必须是有效 ISO UTC 时间');
  return value;
}
function runId(value) {
  if (typeof value !== 'string' || !/^[A-Za-z0-9._:-]{1,128}$/.test(value)) fail('原始请求 ID 无效');
  return value;
}
function base64(raw) {
  if (typeof raw !== 'string' || !raw.length || raw.length % 4 ||
      raw.length > Math.ceil(CACHE_LIMITS.maxWireBytes / 3) * 4 ||
      !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(raw)) fail('UART Base64 数据无效或超限');
  let binary;
  try { binary = globalThis.atob(raw); } catch { fail('UART Base64 数据无效'); }
  if (globalThis.btoa(binary) !== raw) fail('UART Base64 编码不规范');
  return Uint8Array.from(binary, ch => ch.charCodeAt(0));
}
function wire(chunks) {
  if (!Array.isArray(chunks) || !chunks.length || chunks.length > CACHE_LIMITS.maxChunks) fail('UART 接收块数量无效或超限');
  const parts = []; let total = 0;
  for (const chunk of chunks) {
    const part = base64(chunk); total += part.length;
    if (total > CACHE_LIMITS.maxWireBytes) fail('单条 UART 证据超过 256 KiB');
    parts.push(part);
  }
  const all = new Uint8Array(total); let offset = 0;
  for (const part of parts) { all.set(part, offset); offset += part.length; }
  return { parts, all, total };
}
async function sha256(value) {
  if (!globalThis.crypto?.subtle) fail('当前浏览器不支持安全摘要，无法保存缓存证据');
  const digest = await globalThis.crypto.subtle.digest('SHA-256', value);
  return Array.from(new Uint8Array(digest), n => n.toString(16).padStart(2, '0')).join('');
}
function reparse(parts, command, maximum, observed) {
  let result = null, results = 0, ready = 0, invalid = null, sawLength = false, wireIdentity = null;
  const parser = new T25Parser(event => {
    if (['error','control','configuration','action_receipt','direct_result'].includes(event.type))
      invalid = 'UART 包含错误、取消、配置或设备执行记录';
    if (event.type === 'result') { result = event; results++; }
    if (event.type === 'ready') ready++;
    if (event.type === 'identity') {
      const next = identity({ model:event.model, tokenizer:event.tokenizer });
      if (wireIdentity && identityKey(next) !== identityKey(wireIdentity)) invalid = 'UART 中模型身份发生变化';
      wireIdentity = next;
    }
    if (event.type === 'line') {
      if (event.line.startsWith('T25 TEXTLEN 1 ')) sawLength = true;
      // A framed TEXT body may contain these words. It starts with T25 TEXT,
      // so this check never reinterprets body text as a control record.
      if (/^(?:D27 (?:HALTED|SNAPSHOT|RECOVERY|FAULT)|T25 (?:RESET|RELOAD|NOT_READY))\b/.test(event.line))
        invalid = 'UART 包含恢复、复位或停止记录';
    }
  });
  parser.expectRequest('text', command);
  for (const part of parts) parser.feed(part);
  parser.finish();
  if (invalid) fail(invalid);
  if (ready !== 1 || results !== 1 || !result?.complete || !result.modelComplete || result.error || result.action)
    fail('缓存需要唯一一次完整普通文字结果和真实 READY');
  if (!sawLength || result.metrics?.stop !== 1 || result.ids?.at(-1) !== 151645 ||
      !Number.isSafeInteger(result.metrics.session) || result.metrics.session < 1 ||
      result.metrics.generated < 1 || result.metrics.generated > maximum)
    fail('缓存需要完整长度封装、EOS、会话以及符合生成上限的结果');
  unicode(result.text, '回答');
  if (bytes(result.text) > CACHE_LIMITS.maxTextBytes || !hasVisibleCharacter(result.text)) fail('回答为空或超过缓存长度上限');
  if (observed && wireIdentity && identityKey(observed) !== identityKey(wireIdentity)) fail('记录身份与 UART 身份不一致');
  return { text:result.text, observedIdentity:observed || wireIdentity };
}
async function entryId(command, observed, digest) {
  return 'dc-' + await sha256(enc.encode(JSON.stringify([command, identityKey(observed), digest])));
}
function freezeEntry(entry) {
  Object.freeze(entry.uart.chunks); Object.freeze(entry.uart); return Object.freeze(entry);
}
function envelope(entries) {
  return { schema:CACHE_SCHEMA, version:CACHE_VERSION, exportedAt:new Date().toISOString(), entries };
}
function bounded(entries) {
  if (!Array.isArray(entries) || entries.length > CACHE_LIMITS.maxEntries) fail('缓存最多保留 16 条，请先删除不需要的条目');
  const size = bytes(JSON.stringify(envelope(entries)));
  if (size > CACHE_LIMITS.maxTotalBytes) fail('缓存总容量超过 2 MiB，请先删除不需要的条目');
  return entries;
}
async function validateEntry(raw, imported) {
  exactKeys(raw, entryKeys, '缓存条目');
  if (raw.kind !== 'text' || !SOURCES.has(raw.source)) fail('缓存条目不是已声明来源的普通文字');
  const command = request(raw.prompt, raw.maxNewTokens);
  if (command !== raw.command) fail('缓存问题、上限与原始命令不一致');
  timestamp(raw.capturedAt); runId(raw.sourceRunId);
  const observed = identity(raw.observedIdentity);
  exactKeys(raw.uart, ['chunks','sha256','byteLength'], 'UART 证据');
  if (!HEX.test(raw.uart.sha256)) fail('UART SHA-256 格式无效');
  const data = wire(raw.uart.chunks);
  if (data.total !== raw.uart.byteLength) fail('UART 字节长度不一致');
  const digest = await sha256(data.all);
  if (digest !== raw.uart.sha256) fail('UART 摘要不一致');
  const checked = reparse(data.parts, command, raw.maxNewTokens, observed);
  if (checked.text !== raw.text) fail('缓存正文与重新解析的 UART 不一致');
  if (identityKey(checked.observedIdentity) !== identityKey(observed)) fail('缓存遗漏了 UART 中已观测身份');
  const id = await entryId(command, observed, digest);
  if (raw.id !== id) fail('缓存条目 ID 与命令、身份或证据不一致');
  return freezeEntry({ id, kind:'text', prompt:raw.prompt, maxNewTokens:raw.maxNewTokens, command,
    text:checked.text, capturedAt:raw.capturedAt, sourceRunId:raw.sourceRunId,
    observedIdentity:observed, source:raw.source === 'synthetic_fixture' ? 'synthetic_fixture' : imported ? 'historical_import' : raw.source,
    uart:{ chunks:[...raw.uart.chunks], sha256:digest, byteLength:data.total } });
}
async function validateEntries(entries, imported = false) {
  bounded(entries); const result = [], seen = new Set(), ids = new Set();
  for (const raw of entries) {
    const entry = await validateEntry(raw, imported), cacheKey = key(entry);
    if (seen.has(cacheKey) || ids.has(entry.id)) fail('导入包含重复问题、上限和身份的条目');
    seen.add(cacheKey); ids.add(entry.id); result.push(entry);
  }
  return bounded(result);
}

/** Capture only a completed live ordinary-text run. Stored run.result fields
 * are deliberately ignored: the original received bytes are re-parsed. */
export async function createFromRun(run) {
  if (!object(run) || run.kind !== 'text' || !(run.source === 'live' || FIXTURE_SOURCES.has(run.source)) ||
      run.requestSource !== 'board_model' || run.status !== 'complete' ||
      run.preparation || run.warmup || run.isWarmup || run.purpose === 'warmup' ||
      run.cancelRequested || run.cancelled || run.timedOut ||
      !Array.isArray(run.errors) || run.errors.length ||
      (run.presentationSource && run.presentationSource !== 'live' && !FIXTURE_SOURCES.has(run.presentationSource)))
    fail('只能收录已完成、无取消或超时的普通文字请求；预热与设备操作不可缓存');
  if (Array.isArray(run.events) && run.events.some(event => event &&
      (['host_timeout','disconnect','cancel_write','cancel_write_confirmed'].includes(event.type) ||
       (event.type === 'command' && (event.kind === 'cancel' || /^:cancel /.test(event.command || ''))))))
    fail('本次请求包含取消、断线或超时记录');
  const parsed = parseCommand(run.command);
  if ((run.prompt !== undefined && run.prompt !== parsed.prompt) ||
      (run.maxNewTokens !== undefined && run.maxNewTokens !== parsed.maxNewTokens)) fail('原文或生成上限记录不一致');
  const observed = identity(run.observedIdentity);
  if (!Array.isArray(run.chunks) || run.chunks.some(chunk => !object(chunk) || typeof chunk.data !== 'string'))
    fail('缺少原始 UART 接收块');
  const chunks = run.chunks.map(chunk => chunk.data), data = wire(chunks);
  const checked = reparse(data.parts, parsed.command, parsed.maxNewTokens, observed);
  const digest = await sha256(data.all);
  const source = run.testFixture === true || run.fixture === true || FIXTURE_SOURCES.has(run.source) || FIXTURE_SOURCES.has(run.presentationSource)
    ? 'synthetic_fixture' : 'pre_generated';
  return freezeEntry({ id:await entryId(parsed.command, checked.observedIdentity, digest), kind:'text', ...parsed,
    text:checked.text, capturedAt:timestamp(run.createdAt), sourceRunId:runId(run.id),
    observedIdentity:checked.observedIdentity, source,
    uart:{ chunks, sha256:digest, byteLength:data.total } });
}

async function parseDocument(jsonText, imported) {
  unicode(jsonText, '导入文件');
  if (bytes(jsonText) > CACHE_LIMITS.maxImportBytes) fail('导入文件超过 2 MiB');
  let document;
  try { document = JSON.parse(jsonText); } catch { fail('缓存文件不是有效 JSON'); }
  exactKeys(document, ['schema','version','exportedAt','entries'], '缓存文件');
  if (document.schema !== CACHE_SCHEMA || document.version !== CACHE_VERSION) fail('不支持的缓存文件版本');
  timestamp(document.exportedAt);
  return validateEntries(document.entries, imported);
}
export async function parseImport(jsonText) { return parseDocument(jsonText, true); }
export async function exportCache(entries) {
  const checked = await validateEntries(entries);
  const payload = JSON.stringify(envelope(checked), null, 2);
  if (bytes(payload) > CACHE_LIMITS.maxImportBytes) fail('导出文件超过 2 MiB');
  return payload;
}
export async function restoreCache(storage = globalThis.localStorage) {
  if (!storage || typeof storage.getItem !== 'function') fail('浏览器缓存存储不可用');
  let payload;
  try { payload = storage.getItem(CACHE_STORAGE_KEY); } catch (error) { fail('读取本地缓存失败：' + error.message); }
  return payload === null ? [] : parseDocument(payload, false);
}
export async function saveCache(entries, storage = globalThis.localStorage) {
  if (!storage || typeof storage.setItem !== 'function') fail('浏览器缓存存储不可用');
  const checked = await validateEntries(entries), payload = JSON.stringify(envelope(checked));
  if (bytes(payload) > CACHE_LIMITS.maxTotalBytes) fail('缓存总容量超过 2 MiB');
  try { storage.setItem(CACHE_STORAGE_KEY, payload); } catch (error) { fail('缓存未保存，浏览器空间或权限不足：' + error.message); }
  return checked; // Caller changes its active list only after this resolves.
}

/** Merge validated entries without partial writes or silent eviction. */
export function mergeEntries(existing, incoming) {
  bounded(existing); bounded(incoming);
  const merged = new Map(existing.map(entry => [key(entry), entry]));
  for (const entry of incoming) { const cacheKey = key(entry); merged.delete(cacheKey); merged.set(cacheKey, entry); }
  return bounded([...merged.values()].sort((a, b) => b.capturedAt.localeCompare(a.capturedAt)));
}
export function findExact(entries, prompt, maxNewTokens, currentIdentity = null) {
  request(prompt, maxNewTokens); bounded(entries);
  const current = identity(currentIdentity);
  const candidates = entries.filter(entry => entry.prompt === prompt && entry.maxNewTokens === maxNewTokens);
  if (!candidates.length) return { entry:null, status:'miss', reason:'没有原文与生成上限完全一致的演示缓存' };
  if (current) {
    const match = candidates.find(entry => entry.observedIdentity && identityKey(entry.observedIdentity) === identityKey(current));
    if (match) return { entry:match, status:'match', reason:'模型与分词器记录一致；内容仍是历史预生成，不是当前执行' };
    const unknown = candidates.find(entry => !entry.observedIdentity);
    if (!unknown) return { entry:null, status:'identity_mismatch', reason:'当前模型或分词器身份不同，禁止自动命中旧缓存' };
    return { entry:unknown, status:'unverified_identity', reason:'缓存采集时未核验身份；仅可作为明确标注的历史演示' };
  }
  return { entry:candidates[0], status:'unverified_identity', reason:'当前未观测模型身份；仅可作为明确标注的历史演示' };
}
