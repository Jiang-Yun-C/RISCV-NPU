"""Run production entry offline; native tiny-model timing is NOT board TTFT."""
import json
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

from .fixtures import write_assets

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent


class ProductionStreamingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="t27-production-stream-")
        cls.directory = Path(cls.temporary.name)
        write_assets(cls.directory)
        base = ["gcc", "-std=c11", "-O2", "-fno-strict-aliasing", "-ffp-contract=off",
                "-fno-fast-math", "-Wall", "-Wextra", "-Werror",
                "-Wno-misleading-indentation", "-Wno-unknown-pragmas", "-DNX_PORTABLE",
                "-DNX_DIAG_HOST", "-include", str(ROOT / "firmware/runtime/board/diag.h"),
                "-idirafter", str(ROOT / "firmware/drivers/accel"),
                "-idirafter", str(ROOT / "software/include"),
                "-DNX_OPT13_TEST", "-I", str(cls.directory),
                "-I", str(ROOT / "firmware/runtime/port"),
                "-I", str(ROOT / "firmware/runtime/reference")]
        common = [str(ROOT / p) for p in (
            "firmware/runtime/port/runtime.c", "firmware/runtime/port/model.c",
            "firmware/runtime/port/tokenizer.c", "firmware/runtime/port/stream.c",
            "firmware/runtime/reference/nx_reference.c", "firmware/runtime/board/diag.c",
            "firmware/runtime/board/led_control.c", "firmware/application/application.c")]
        cls.service = cls.directory / "production-main-native"
        cls.controls = cls.directory / "stream-controls-native"
        subprocess.run(base + ["-DNX_T25_UART", "-DNX_T25_SERVICE_TEST",
                       str(HERE / "native_main.c"), str(cls.directory / "tokenizer.S")]
                       + common + ["-lm", "-o", str(cls.service)], check=True, timeout=60)
        subprocess.run(base + [str(HERE / "native_stream.c")] + common
                       + ["-lm", "-o", str(cls.controls)], check=True, timeout=60)

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def run_service(self, commands, *args):
        run = subprocess.run([str(self.service), *args], input=commands.encode(),
                             capture_output=True, timeout=20, check=True)
        snapshots = [json.loads(line) for line in run.stderr.decode().splitlines()]
        return run.stdout, snapshots

    def test_actual_production_entry_streams_before_later_tokens(self):
        wire, states = self.run_service(":ids 8 1 3 4 5 6 7 8 9 10 11 12 13 14\n")
        self.assertNotIn(b"T25 ERROR", wire)
        self.assertNotIn(b"T25 STEP", wire)
        self.assertIn(b"T25 CAPABILITIES stream=1 text_max=1", wire)
        frames = re.findall(rb"T25 STREAM 1 (\w+) ([^\n]*)", wire)
        self.assertEqual(frames[0][0], b"BEGIN")
        self.assertEqual(frames[-1][0], b"END")
        text_first = next(i for i, frame in enumerate(frames) if frame[0] == b"TEXT")
        tokens = [i for i, frame in enumerate(frames) if frame[0] == b"TOKEN"]
        self.assertEqual(len(tokens), 8)
        self.assertLess(tokens[0], text_first)
        self.assertLess(text_first, tokens[1])
        self.assertIn(b"data=e4b8ad", frames[text_first][1])
        self.assertEqual(wire.count(b"T25 STREAM 1 TEXT "), 8)
        self.assertIn(b"T25 TEXTLEN 1 bytes=0000000000000018", wire)
        self.assertIn(b"T25 TEXT " + "中".encode() * 8 + b"\n", wire)
        self.assertEqual(states[-1]["state"], 3)
        self.assertEqual(states[-1]["generated"], 8)
        self.assertEqual(states[-1]["kv"], 20)

    def test_stream_on_off_preserve_real_model_ids_logits_and_kv_bits(self):
        command = ":ids 8 1 3 4 5 6 7 8 9 10 11 12 13 14\n"
        streamed, stream_state = self.run_service(command)
        buffered, buffer_state = self.run_service(":stream 0\n" + command)
        self.assertNotIn(b"T25 STREAM 1", buffered)
        self.assertEqual(re.findall(rb"T25 IDS [^\n]*", streamed),
                         re.findall(rb"T25 IDS [^\n]*", buffered))
        self.assertEqual(re.findall(rb"T25 TEXT [^\n]*", streamed),
                         re.findall(rb"T25 TEXT [^\n]*", buffered))
        self.assertEqual(stream_state[-1], buffer_state[-1])

    def test_failed_final_stack_check_aborts_preview_without_final_text(self):
        wire, states = self.run_service(":ids 3 1 2 3\n", "stack-failure")
        self.assertIn(b"T25 STREAM 1 TEXT", wire)
        self.assertIn(b"T25 STREAM 1 ABORT", wire)
        self.assertIn(b"T25 ERROR", wire)
        self.assertNotIn(b"T25 STREAM 1 END", wire)
        self.assertNotIn(b"T25 IDS ", wire)
        self.assertNotIn(b"T25 TEXT ", wire)
        self.assertEqual(states[-1]["state"], 4)
        self.assertEqual(states[-1]["generated"], 0)

    def test_stream_disabled_failure_does_not_publish_final_text(self):
        wire, _ = self.run_service(":stream 0\n:ids 3 1 2 3\n", "stack-failure")
        self.assertIn(b"T25 ERROR", wire)
        self.assertNotIn(b"T25 STREAM 1", wire)
        self.assertNotIn(b"T25 TEXT ", wire)

    def test_final_text_transport_timeout_revokes_success_after_end(self):
        wire, states = self.run_service(":ids 3 7\n", "final-timeout")
        self.assertIn(b"T25 STREAM 1 END", wire)
        self.assertIn(b"T25 TEXT ", wire)
        self.assertIn(b"T25 ERROR fffffff9", wire)
        self.assertNotIn(b"T25 METRICS", wire)
        self.assertEqual(states[-1]["state"], 4)
        self.assertEqual(states[-1]["generated"], 0)

    def test_invalid_prompt_has_no_preview_and_next_request_recovers(self):
        wire, states = self.run_service(":ids 1 151936\n:ids 1 7\n")
        self.assertEqual(wire.count(b"T25 ERROR"), 1)
        self.assertEqual(wire.count(b"T25 STREAM 1 BEGIN"), 1)
        self.assertEqual(wire.count(b"T25 STREAM 1 END"), 1)
        self.assertEqual(states[-1]["state"], 3)

    def test_success_invalid_begin_success_has_no_stale_stream_state(self):
        wire, states = self.run_service(":ids 2 7\n:ids 1 151936\n:ids 2 7\n")
        self.assertEqual(wire.count(b"T25 ERROR"), 1)
        self.assertEqual(wire.count(b"T25 STREAM 1 BEGIN"), 2)
        self.assertEqual(wire.count(b"T25 STREAM 1 END"), 2)
        self.assertEqual(wire.count(b"T25 STREAM 1 ABORT"), 0)
        self.assertEqual(states[0], states[-1])

    def test_production_wire_with_real_host_parser_and_partial_text_frame(self):
        streamed, _ = self.run_service(":ids 8 1 3 4 5 6 7 8 9 10 11 12 13 14\n")
        buffered, _ = self.run_service(":stream 0\n:ids 2 7\n")
        failed, _ = self.run_service(":ids 3 7\n", "stack-failure")
        program = r'''
import fs from 'node:fs';
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
const {T25Parser} = await import(pathToFileURL(process.argv[1]).href);
const [streamed,buffered,failed] = JSON.parse(fs.readFileSync(0,'utf8')).map(x=>Buffer.from(x,'base64'));
for(const raw of [streamed,buffered,failed])for(const size of [1,2,5,31,173,65536]) {
  const events=[];const parser=new T25Parser(e=>events.push(e));
  for(let i=0;i<raw.length;i+=size)parser.feed(raw.subarray(i,i+size),{received: i});
  parser.finish();
  const results=events.filter(e=>e.type==='result');assert.equal(results.length,1);
  assert.equal(results[0].complete,raw!==failed);
  if(raw===streamed){assert.equal(results[0].text,'中'.repeat(8));assert.equal(results[0].ids.length,8);}
  if(raw===buffered)assert.equal(results[0].text,'中'.repeat(2));
}
const events=[];const parser=new T25Parser(e=>events.push(e));
const needle=Buffer.from('data=e4b8ad');
const cut=streamed.indexOf(needle)+needle.length;assert.ok(cut>needle.length);
parser.feed(streamed.subarray(0,cut),{received:123});
assert.equal(events.filter(e=>e.type==='preview').at(-1).text,'中');
assert.equal(events.filter(e=>e.type==='token').length,1);
assert.equal(events.filter(e=>e.type==='result').length,0);
assert.equal(streamed[cut],10); // Still no TEXT frame LF when first glyph appears.
parser.feed(streamed.subarray(cut),{received:456});parser.finish();
assert.equal(events.filter(e=>e.type==='result').at(-1).complete,true);
console.log('PASS production main -> real stream encoder -> actual incremental host parser');
'''
        import base64
        run = subprocess.run(["node", "--input-type=module", "-e", program,
                              str(ROOT / "software/demo_console/static/protocol.js")],
                             input=json.dumps([base64.b64encode(x).decode() for x in
                                               (streamed, buffered, failed)]),
                             capture_output=True, text=True, timeout=20)
        self.assertEqual(run.returncode, 0, run.stderr)

    def test_full_context_stops_without_text_or_fabricated_first_token(self):
        wire, states = self.run_service(":ids 1 " + " ".join(["1"] * 512) + "\n")
        self.assertNotIn(b"T25 STREAM 1 TEXT", wire)
        self.assertIn(b"first_token=ffffffffffffffff", wire)
        self.assertIn(b"first_text=ffffffffffffffff", wire)
        self.assertIn(b"T25 TEXTLEN 1 bytes=0000000000000000", wire)
        self.assertEqual(states[-1]["generated"], 0)
        self.assertEqual(states[-1]["stop"], 3)

    def test_adversarial_stream_library_controls(self):
        run = subprocess.run([str(self.controls), str(self.directory / "synthetic.nxt")],
                             capture_output=True, timeout=10)
        self.assertEqual(run.returncode, 0, run.stderr.decode())
        self.assertIn(b"PASS:", run.stdout)


if __name__ == "__main__":
    unittest.main()
