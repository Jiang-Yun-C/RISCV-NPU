/* JSON-lines transport for the exact console parser; no independent UART grammar. */
import readline from 'node:readline';
import {T25Parser} from '../demo_console/static/protocol.js';

let events = [];
const parser = new T25Parser(event => {
  if (['ready','result','identity','capabilities','request','error'].includes(event.type)) events.push(event);
});
let failed = false;
for await (const line of readline.createInterface({input: process.stdin, crlfDelay: Infinity})) {
  events = [];
  try {
    if (failed) throw new Error('parser already failed; reconnect before another request');
    const input = JSON.parse(line);
    if (input.operation === 'feed') {
      for (const chunk of input.chunks) {
        const bytes = Buffer.from(chunk.data, 'base64');
        if (bytes.toString('base64') !== chunk.data || bytes.length !== chunk.bytes) throw new Error('invalid receive chunk');
        parser.feed(bytes, chunk);
      }
    } else if (input.operation === 'finish') parser.finish();
    else throw new Error('unknown parser operation');
    process.stdout.write(JSON.stringify({events}) + '\n');
  } catch (error) {
    failed = true;
    process.stdout.write(JSON.stringify({events, error: error.message}) + '\n');
  }
}
