/** Offline protocol tests; byte fixtures never perform model inference or UART IO. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import { T25Parser, commandFor, cancelCommand, hasVisibleCharacter, metricValues } from '../static/protocol.js';
const enc = new TextEncoder();
const hex = value => BigInt(value).toString(16).padStart(16, '0');
const dataHex = value => Buffer.from(value).toString('hex');
let checks = 0;
function check(value, name) { assert.ok(value, name); checks++; }
function frame(kind, index = 0, token = 0, text = '', error = 0, ticks = 10 + index * 10) {
  return `T25 STREAM 1 ${kind} session=${hex(1)} sequence=${hex(1)} index=${hex(index)} ticks=${hex(ticks)} token=${hex(token)} error=${hex(error)} data=${kind === 'TEXT' ? dataHex(text) : '-'}\n`;
}
function final(text, ids) {
  const fields = { session: 1, prompt: 3, generated: ids.length, stop: 2, kv: 3 + Math.max(0, ids.length - 1),
    total_ticks: 200, first_token_ticks: 10, prefill_ticks: 10, decode_ticks: 20, ce_calls: 4, fallback_calls: 0 };
  return `T25 IDS ${ids.map(x => x.toString(16).padStart(8, '0')).join(' ')} \nT25 TEXTLEN 1 bytes=${hex(enc.encode(text).length)} \nT25 TEXT ${text}\nT25 METRICS ${Object.entries(fields).map(([k, v]) => `${k}=${hex(v)}`).join(' ')} \nT25 READY\n`;
}
function trace(parts) {
  const ids = parts.map((_, i) => 100 + i);
  return frame('BEGIN') + parts.map((part, i) => frame('TOKEN', i + 1, ids[i]) + (part ? frame('TEXT', i + 1, ids[i], part) : '')).join('') + frame('END', ids.length) + final(parts.join(''), ids);
}
function parse(raw, size = 65536) {
  const events = [], parser = new T25Parser(e => events.push(e)), bytes = enc.encode(raw);
  for (let i = 0; i < bytes.length; i += size) parser.feed(bytes.slice(i, i + size), { browserReceive: i });
  parser.finish(); return events;
}
function rejects(raw, name) {
  let events = [], failure = false;
  try { events = parse(raw, 1); } catch { failure = true; }
  check(failure || !events.some(e => e.type === 'result' && e.complete), name);
}
for (const parts of [['你', '好', '！'], [' \n', '\u200B', '你'], ['', ''], ['A', '\uFEFFB'], ['e', '\u0301', '🌍']]) {
  for (const size of [1, 2, 7, 97, 65536]) {
    const events = parse(trace(parts), size), result = events.find(e => e.type === 'result');
    check(result?.complete && result.text === parts.join(''), `stream split ${size} ${JSON.stringify(parts)}`);
  }
}
{
  const events = [], parser = new T25Parser(e => events.push(e));
  parser.feed(enc.encode(frame('BEGIN') + frame('TOKEN', 1, 100)));
  const wire = frame('TEXT', 1, 100, '你');
  const head = wire.slice(0, wire.indexOf('data=') + 5);
  parser.feed(enc.encode(head + 'e4bd'), { browserReceive: 1 });
  check(!events.some(e => e.type === 'preview'), 'incomplete Chinese UTF-8 is not displayed');
  parser.feed(enc.encode('a'), { browserReceive: 2 });
  check(!events.some(e => e.type === 'preview'), 'half a hex byte is not displayed');
  parser.feed(enc.encode('0'), { browserReceive: 3 });
  const preview = events.find(e => e.type === 'preview');
  check(preview?.text === '你' && preview.chunk.browserReceive === 3, 'first Chinese character displayed before LF');
  check(!events.some(e => e.type === 'result'), 'preview has no final success authority');
  parser.feed(enc.encode('\n' + frame('END', 1) + final('你', [100]))); parser.finish();
  check(events.find(e => e.type === 'result')?.complete, 'same stream eventually passes final checks');
}
check(!hasVisibleCharacter(' \n\r\t\u200B\uFEFF\u0301\uFFFD'), 'blank/control/format/mark/replacement do not count');
check(hasVisibleCharacter('你') && hasVisibleCharacter('🌍'), 'Chinese and supplementary scalar count');
check(!parse(trace(['', ''])).some(e => e.type === 'preview'), 'empty EOS-like pieces have no visible TTFT');
{
  const body = '你好\nT25 READY\nT25 METRICS generated=0000000000000001\n\r结束';
  const events = parse(trace([body]), 1);
  check(events.filter(e => e.type === 'ready').length === 1, 'control-looking text never becomes READY');
  check(events.find(e => e.type === 'result')?.text === body, 'byte-counted multiline body remains exact');
}
const good = trace(['你', '好']);
rejects(good.replace('stop=0000000000000002', 'stop=0000000000000000'), 'invalid stop reason');
rejects(good.replace('stop=0000000000000002', 'stop=0000000000000001'), 'EOS stop without EOS');
rejects(good.replace('stop=0000000000000002', 'stop=0000000000000003'), 'context stop before full context');
rejects(good.replace('stop=0000000000000002 ', ''), 'missing stop reason');
rejects(good.replace(frame('END', 2), ''), 'missing END');
rejects(good.replace('T25 READY\n', ''), 'missing READY');
rejects(good.replace(frame('TOKEN', 2, 101), ''), 'missing TOKEN');
rejects(good.replace(frame('TOKEN', 2, 101), frame('TOKEN', 1, 101)), 'duplicate token index');
rejects(good.replace(frame('TEXT', 2, 101, '好'), frame('TEXT', 2, 101, '错')), 'preview and final body mismatch');
rejects(good.replace('T25 IDS 00000064 00000065', 'T25 IDS 00000064 00000066'), 'final token mismatch');
rejects(good.replace('bytes=0000000000000006', 'bytes=0000000000000005'), 'truncated UTF-8 length');
rejects(good.replace('data=e4bda0', 'data=e4bda0gg'), 'malformed suffix after valid preview');
rejects(good.replace('data=e4bda0', 'data=c0af'), 'overlong UTF-8 rejected');
rejects(good.replace(frame('TEXT', 1, 100, '你'), frame('TEXT', 1, 100, '你').replace('session=' + hex(1), 'session=' + hex(2))), 'wrong session');
rejects(good.replace(frame('END', 2), frame('END', 2) + frame('ABORT', 2, 0, '', 0xfffffffd)), 'END followed by ABORT never succeeds');
rejects(frame('BEGIN') + frame('TOKEN', 1, 100) + frame('TEXT', 1, 100, '你') + frame('ABORT', 1, 0, '', 0xfffffffd) + 'T25 ERROR fffffffd\nT25 READY\n', 'abort after visible preview');
{
  const events = parse(final('仅最终正文', [100]), 1);
  check(events.find(e => e.type === 'result')?.complete, 'stream-off length-framed service needs no STEP');
  check(events.some(e => e.type === 'preview' && e.buffered), 'stream-off final body rendered on arrival');
}
const samples = JSON.parse(fs.readFileSync(new URL('../static/replays.json', import.meta.url)));
for (const sample of samples) for (const size of [1, 2, 7, 31, 65536])
  check(parse(sample.raw, size).filter(e => e.type === 'result' && e.complete).length === 1, `legacy ${sample.id} ${size}`);
check(commandFor('text', '你好', 32, { textMax: true }) === ':text 32 你好', 'capability-gated text maximum');
check(commandFor('text', '你好', 32) === '你好', 'old firmware text command unchanged');
for (const path of process.argv.slice(2)) {
  const events = parse(fs.readFileSync(path, 'utf8'), 7);
  check(events.some(e => e.type === 'result' && e.complete), `production main trace ${path}`);
}
check(metricValues({ generated: 0, first_token_ticks: 0 }).first === null, 'zero generated tokens has no first-token sample');
check(metricValues({ generated: 1, first_token_ticks: 125000000 }).first === 1, 'internal first-token conversion');
{
  const caps = 'T25 CAPABILITIES stream=1 text_max=1 cancel=1 prefix=1 profile=1 timeout=1 identity=1\n';
  const request = `T25 REQUEST 1 session=${hex(1)} timeout_ticks=${hex(125000000)} prefix_hit=${hex(0)} prefix_tokens=${hex(2)} \n`;
  const fields = values => Object.entries(values).map(([k,v]) => `${k}=${hex(v)} `).join('');
  const profiles = ['REQUEST','PREFILL','DECODE','CUMULATIVE'].map((phase,j) => `T25 PROFILE 1 ${phase} session=${hex(1)} ` +
    Array.from({length:8}, (_,i) => `${i.toString(16).padStart(8,'0')} ticks=${hex([30,20,10,60][j])} calls=${hex([3,2,1,6][j])} `).join('') + '\n').join('');
  const prefix = 'T25 PREFIX 1 ' + fields({session:1,hit:0,captured:1,tokens:2,prepare_ticks:4,restore_ticks:1}) + '\n';
  const counters = ['cycles','retired','execute_stall','branches','mispredicts','i_ar','i_r_beats','i_r_bytes','i_address_blocked',
    'd_ar','d_r_beats','d_r_bytes','d_aw','d_w_beats','d_w_bytes','d_address_blocked','ce_ar','ce_r_beats','ce_r_bytes','ce_aw','ce_w_beats','ce_w_bytes','ce_address_blocked','response_errors'];
  const pmu = 'T25 PMU 1 STATUS ' + fields({session:1,available:1,valid:1}) + '\n' +
    ['REQUEST','PREFILL','DECODE'].map((phase,j) => 'T25 PMU 1 ' + phase + ' ' + fields({session:1,tag:1,sequence:j===1?1:2,
      ...Object.fromEntries(counters.map(k=>[k,[90,60,30][j]]))}) + '\n').join('');
  const transfer = 'T25 TRANSFER 1 ' + fields({session:1,input_staged_bytes:64,input_saved_bytes:128,output_copy_bytes:64,
    output_saved_bytes:128,input_staging_ticks:5,output_copy_ticks:3,backend_cycles:7,completed_calls:4,
    kv_output_saved_bytes:256,head_read_saved_bytes:512}) + '\n';
  const wire = caps + request + good.replace('T25 READY\n', profiles + prefix + pmu + transfer + 'T25 READY\n');
  const result = parse(wire, 1).find(e=>e.type==='result');
  check(result?.complete && result.profiles.REQUEST[0].ticks === 30 && result.pmu.DECODE.cycles === 30,
    'enhanced integer stage/PMU wire is bound to the request');
  check(cancelCommand('fedcba9876543210') === ':cancel fedcba9876543210', 'cancel command preserves every session bit');
  check(result.transfer.input_saved_bytes === 128 && result.prefix.captured === 1, 'copy estimates and cold preparation exported');
  check(result.transfer.kv_output_saved_bytes === 256 && result.transfer.head_read_saved_bytes === 512,
    'K/V copy savings and head read savings retain distinct counters');
  rejects(wire.replace(request,request.replace('prefix_tokens='+hex(2)+' ','')), 'missing declared prefix length');
  rejects(wire.replace(request,request.replace('session='+hex(1),'session='+hex(2))), 'request announcement bound to stream');
  rejects(wire.replace('T25 METRICS session='+hex(1),'T25 METRICS session='+hex(2)), 'final metrics bound to request');
  rejects(wire.replace(profiles,''), 'declared stage profile cannot disappear');
  rejects(wire.replace('T25 PROFILE 1 DECODE','T25 PROFILE 1 PREFILL'), 'duplicate stage group');
  rejects(wire.replace('ticks='+hex(30),'ticks='+hex(31)), 'request counts must equal stage differences');
  rejects(wire.replace(prefix,prefix.replace('tokens='+hex(2),'tokens='+hex(1))), 'prefix report must match announcement');
  rejects(wire.replace(pmu,pmu.replace('tag='+hex(1),'tag='+hex(2))), 'PMU tag must match request identity');
  rejects(wire.replace('T25 PMU 1 DECODE','T25 PMU 1 REQUEST'), 'PMU duplicate stage rejected');
  rejects(wire.replace('cycles='+hex(90),'cycles='+hex(91)), 'PMU snapshot differences must sum');
  rejects(wire.replace('input_staged_bytes='+hex(64)+' ',''), 'partial transfer record rejected');
  rejects(request, 'request without final boundary remains incomplete');
  rejects(wire.replace('T25 PMU 1 STATUS','T25 PMU 2 STATUS'), 'unknown PMU version rejected');
  rejects(wire.replace('stream=1 text_max=1','stream=1 stream=1 text_max=1'), 'duplicate capability rejected');
  const unsupported = wire.replace(pmu,'T25 PMU 1 STATUS '+fields({session:1,available:0,valid:0})+'\n');
  check(parse(unsupported).find(e=>e.type==='result')?.pmu.STATUS.valid === 0, 'older bitstream PMU is explicitly unsupported');
}
console.log(`PASS ${checks} streaming/UTF-8/framing/legacy assertions; offline fixtures, no UART/model performance claim`);
