/* Reuse the shipped wire parser. JSON metadata is not a substitute for bytes. */
import fs from 'node:fs';
import crypto from 'node:crypto';
import {T25Parser, CLOCK, MODEL, TOKENIZER, commandFor} from '../demo_console/static/protocol.js';

const inputs = JSON.parse(fs.readFileSync(0, 'utf8'));
if (inputs.action === 'commands') {
  console.log(JSON.stringify({parser_contract: {clock_hz: CLOCK, model: MODEL, tokenizer: TOKENIZER},
    commands: inputs.cases.map(c => ({case_id: c.id, command: commandFor('text', c.prompt, inputs.max_new, {textMax: true})}))}));
  process.exit(0);
}
const digest = bytes => crypto.createHash('sha256').update(bytes).digest('hex');
const parsed = [];
for (const input of inputs) {
  const result = {case_id: input.case_id, protocol_accepted: false, issues: [],
    declared_source: null, model_identity: null, first_visible_chunk: null, request_result: null};
  try {
    const bytes = fs.readFileSync(input.path);
    if (bytes.length > 8 * 1024 * 1024) throw new Error('export exceeds 8 MiB');
    result.export_sha256 = digest(bytes);
    const record = JSON.parse(bytes.toString('utf8'));
    result.declared_source = record.source ?? null;
    result.fixture = record.fixture === true || record.source === 'fixture';
    result.command = record.command;
    result.clock_hz = record.clockHz ?? null;
    result.record_identity = record.identity ?? null;
    result.export_timing = record.timing ?? null;
    if (record.schema !== 'nexusrv-demo-v1') throw new Error('unsupported console export schema');
    if (record.command !== input.expected_command) throw new Error('request command does not match frozen case');
    const events = [], collected = [];
    const parser = new T25Parser(event => {
      events.push(event);
      if (event.type === 'preview' && event.visible && !result.first_visible_chunk)
        result.first_visible_chunk = event.chunk;
    });
    if (Array.isArray(record.rawChunks) && record.rawChunks.length) {
      if (record.rawChunks.length > 65536) throw new Error('too many receive chunks');
      let previousSeq = null, previousHost = null, previousBrowser = null, size = 0;
      for (const chunk of record.rawChunks) {
        if (chunk.discardIncomplete) throw new Error('discarded reconnect fragments cannot qualify a request');
        if (typeof chunk.data !== 'string' || !/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(chunk.data))
          throw new Error('invalid chunk base64');
        const data = Buffer.from(chunk.data, 'base64');
        if (data.toString('base64') !== chunk.data || data.length !== chunk.bytes) throw new Error('chunk length/encoding mismatch');
        size += data.length;if (size > 2 * 1024 * 1024) throw new Error('wire exceeds 2 MiB');
        if (chunk.seq !== undefined) {
          if (!Number.isSafeInteger(chunk.seq) || (previousSeq !== null && chunk.seq !== previousSeq + 1))
            throw new Error('missing or duplicate chunk sequence');
          previousSeq = chunk.seq;
        }
        if (chunk.received_ns !== undefined) {
          if (typeof chunk.received_ns !== 'string' || !/^\d+$/.test(chunk.received_ns)) throw new Error('bad host timestamp');
          const t = BigInt(chunk.received_ns);
          if (previousHost !== null && t < previousHost) throw new Error('host clock moved backwards');
          previousHost = t;
        }
        if (chunk.browserReceive !== undefined) {
          if (!Number.isFinite(chunk.browserReceive) || (previousBrowser !== null && chunk.browserReceive < previousBrowser))
            throw new Error('browser clock moved backwards');
          previousBrowser = chunk.browserReceive;
        }
        collected.push(data);parser.feed(data, chunk);
      }
      result.used_raw_chunks = true;
      const wire = Buffer.concat(collected);
      const decoded = new TextDecoder('utf-8', {fatal: true, ignoreBOM: true}).decode(wire);
      if (typeof record.raw !== 'string' || decoded !== record.raw) throw new Error('raw text disagrees with raw chunks');
      result.wire_sha256 = digest(wire);result.wire_bytes = wire.length;
    } else {
      if (typeof record.raw !== 'string' || Buffer.byteLength(record.raw) > 2 * 1024 * 1024)
        throw new Error('missing or oversized raw transcript');
      const wire = Buffer.from(record.raw, 'utf8');
      parser.feed(wire);result.used_raw_chunks = false;
      result.wire_sha256 = digest(wire);result.wire_bytes = wire.length;
    }
    parser.finish();
    const requests = events.filter(e => e.type === 'result');
    if (requests.length !== 1) throw new Error('export must contain exactly one completed request attempt');
    const request = requests[0];
    if (!request.complete) throw new Error(request.error || 'incomplete request');
    if (events.some(e => e.type === 'error')) throw new Error('wire contains an error');
    result.request_result = {text: request.text, ids: request.ids, metrics: request.metrics, timing: request.timing,
      profiles: request.profiles, prefix: request.prefix, pmu: request.pmu, transfer: request.transfer};
    result.model_identity = events.filter(e => e.type === 'identity').at(-1) ?? null;
    result.protocol_accepted = true;
    // All summary fields above come from reparsing bytes; ignore record.complete
    // and record.metrics even when they claim success or contain different text.
  } catch (error) { result.issues.push(error.message); }
  parsed.push(result);
}
console.log(JSON.stringify({parser_contract: {clock_hz: CLOCK, model: MODEL, tokenizer: TOKENIZER}, records: parsed}));
