import base64
import json
import threading
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import patch

from software.demo_console.server import ConsoleServer, SerialBridge, validate_command


class CommandTests(unittest.TestCase):
    def test_bounded_service_commands(self):
        for text in ["", "你好", ":ids 1 0 255 1023", ":ids 128 151935", ":memory", ":telemetry", ":identity", ":cancel 0000000000000001", ":prefix 1", ":timeout 86400"]:
            self.assertEqual(validate_command(text), text.encode() + b"\n")

    def test_control_and_framing_rejected(self):
        for text in [":reload", ":reset", ":pressure on", ":verify 32 0", "你好\n:reload", "hi\r", "a\x00b", "a\b", "a\x7f",
                     "中" * 1366, ":ids 0 1", ":ids 129 1", ":ids 1 151936", ":ids 1 -1", ":ids 1", ":ids 1 " + "0 " * 513,
                     ":cancel 0000000000000000", ":cancel 1", ":timeout 0", ":timeout 86401", None]:
            with self.subTest(text=str(text)[:40]):
                with self.assertRaises(ValueError):
                    validate_command(text)


class FakePort:
    def __init__(self, *args, **kwargs):
        self.dtr = self.rts = True
        self.opened = False
        self.writes = []
        self.pending = bytearray()
    def open(self):
        assert self.dtr is False and self.rts is False
        self.opened = True
    def close(self):
        self.opened = False
    @property
    def in_waiting(self):
        return len(self.pending)
    def read(self, size):
        if not self.pending:
            time.sleep(.002)
            return b""
        data = bytes(self.pending[:size]); del self.pending[:size]
        return data
    def write(self, data):
        self.writes.append(data)
        return len(data)
    def flush(self):
        pass


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.port = FakePort()
        self.bridge = SerialBridge(serial_factory=lambda *a, **k: self.port)
        self.bridge.ports = lambda: {"ports": [dict(device="COM10", expected=True)]}
        self.owner = "owner-123456789012345"
        self.bridge.connect("COM10", self.owner)
    def tearDown(self):
        self.bridge.disconnect()
    def ready(self):
        self.port.pending.extend(b"T25 READY\n")
        limit = time.monotonic() + 2
        while not self.bridge.synced and time.monotonic() < limit:
            time.sleep(.005)
        self.assertTrue(self.bridge.synced)
    def test_no_reset_on_connect_and_one_pending_request(self):
        self.assertEqual(self.port.writes, [])
        with self.assertRaises(ValueError): self.bridge.write("你好", self.owner)
        self.bridge.write("", self.owner)
        with self.assertRaises(ValueError): self.bridge.write("", self.owner)
        self.ready()
        self.bridge.write("你好", self.owner)
        self.assertEqual(self.port.writes, [b"\n", "你好\n".encode()])
        with self.assertRaises(ValueError): self.bridge.write("again", self.owner)
    def test_cancel_is_only_exception_to_one_pending_command(self):
        self.ready(); self.bridge.write('hello', self.owner)
        with self.assertRaises(ValueError): self.bridge.write(':cancel 0000000000000002', self.owner)
        with self.bridge.lock:
            self.bridge._consume_ready(b'T25 CAPABILITIES stream=1 text_max=1 cancel=1\nT25 REQUEST 1 session=0000000000000002 timeout_ticks=0000000000000100 prefix_hit=0000000000000000 prefix_tokens=0000000000000000 \n')
        with self.assertRaises(ValueError): self.bridge.write(':cancel 0000000000000003', self.owner)
        self.bridge.write(':cancel 0000000000000002', self.owner)
        self.assertTrue(self.bridge.pending)
        self.assertEqual(self.port.writes[-1], b':cancel 0000000000000002\n')
        with self.assertRaises(ValueError): self.bridge.write(':timeout 5', self.owner)
        with self.bridge.lock: self.bridge._consume_ready(b'T25 READY\n')
        with self.assertRaises(ValueError): self.bridge.write(':cancel 0000000000000002', self.owner)
    def test_owner_target_and_bounded_buffer(self):
        with self.assertRaises(ValueError): self.bridge.read(0, "a-different-owner")
        self.assertTrue(self.bridge.connect("COM10", self.owner)["resumed"])
        with self.assertRaises(ValueError): self.bridge.connect("COM10", "another-owner-123456789")
        self.ready()
        chunks = self.bridge.read(0, self.owner)["chunks"]
        self.assertEqual(base64.b64decode(chunks[0]["data"]), b"T25 READY\n")
        self.bridge.chunks.clear(); self.bridge.chunks.append((20, ""))
        with self.assertRaises(ValueError): self.bridge.read(0, self.owner)

    def test_ready_inside_model_text_does_not_unlock_uart(self):
        self.ready()
        self.bridge.write("你好", self.owner)
        self.port.pending.extend(b"T25 TEXT hello\nT25 READY\nworld\n")
        time.sleep(.03)
        self.assertTrue(self.bridge.pending)
        self.port.pending.extend(b"T25 METRICS generated=0000000000000001\nT25 READY\n")
        deadline = time.monotonic() + 1
        while self.bridge.pending and time.monotonic() < deadline:
            time.sleep(.005)
        self.assertFalse(self.bridge.pending)

    def test_monotonic_timing_and_raw_chunk_metadata(self):
        self.ready()
        timing = self.bridge.write("你好", self.owner)
        self.assertEqual(timing["clock"], "python.time.monotonic_ns")
        self.assertLessEqual(int(timing["write_start"]), int(timing["write_return"]))
        self.assertLessEqual(int(timing["write_return"]), int(timing["flush_end"]))
        self.assertEqual(timing["bytes"], len("你好\n".encode()))
        record = self.bridge.read(0, self.owner)
        self.assertTrue(record["pending"])
        self.assertGreater(int(record["chunks"][0]["received_ns"]), 0)

    def test_long_poll_wakes_on_partial_frame_without_newline(self):
        self.ready()
        after = self.bridge.seq
        result, started, finished = [], threading.Event(), threading.Event()
        def read():
            started.set()
            result.append(self.bridge.read(after, self.owner, wait=1))
            finished.set()
        thread = threading.Thread(target=read)
        thread.start(); self.assertTrue(started.wait(1))
        self.port.pending.extend(b"T25 STREAM 1 TEXT ")
        self.assertTrue(finished.wait(.5), "receive should wake long poll on a chunk, not wait for LF")
        thread.join()
        self.assertEqual(base64.b64decode(result[0]["chunks"][0]["data"]), b"T25 STREAM 1 TEXT ")
        self.assertEqual(result[0]["chunks"][0]["seq"], after + 1)

    def test_exact_length_body_owns_embedded_control_lines(self):
        self.ready(); self.bridge.write("你好", self.owner)
        body = "你\nT25 METRICS fake\nT25 READY\n好".encode()
        wire = f"T25 TEXTLEN 1 bytes={len(body):016x} \n".encode() + b"T25 TEXT " + body + b"\n"
        self.port.pending.extend(wire)
        deadline = time.monotonic() + 1
        while self.port.pending and time.monotonic() < deadline:
            time.sleep(.002)
        self.assertTrue(self.bridge.pending)
        self.port.pending.extend(b"T25 METRICS generated=0000000000000001\nT25 READY\n")
        deadline = time.monotonic() + 1
        while self.bridge.pending and time.monotonic() < deadline:
            time.sleep(.002)
        self.assertFalse(self.bridge.pending)

    def test_resume_declares_pending_and_cursor_but_no_completed_result(self):
        self.ready(); self.bridge.write("你好", self.owner)
        resumed = self.bridge.connect("COM10", self.owner)
        self.assertTrue(resumed["resumed"] and resumed["pending"])
        self.assertEqual(resumed["after"], self.bridge.seq)
        self.assertNotIn("result", resumed)

    def test_baud_configuration_and_cursor_validation(self):
        self.assertEqual(self.bridge.baud, 115200)
        with self.assertRaises(ValueError): self.bridge.connect("COM10", self.owner, 9600)
        with self.assertRaises(ValueError): self.bridge.read(self.bridge.seq + 1, self.owner)
        with self.assertRaises(ValueError): self.bridge.read(-1, self.owner)
        with self.assertRaises(ValueError): self.bridge.read(0, self.owner, wait=26)



class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.server = ConsoleServer(("127.0.0.1", 0))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}"
    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()
    def test_offline_assets_and_authentication(self):
        with urlopen(self.url) as response:
            self.assertEqual(response.status, 200)
            self.assertIn(b"NexusRV", response.read())
            self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])
        with urlopen(self.url + "/api/bootstrap") as response:
            token = json.load(response)["token"]
        for path in ["/../../README.md", "/%2e%2e/server.py"]:
            with self.assertRaises(HTTPError) as error: urlopen(self.url + path)
            self.assertEqual(error.exception.code, 404)
        request = Request(self.url + "/api/connect", data=b'{"port":"COM10"}', headers={"Content-Type": "application/json"})
        with self.assertRaises(HTTPError): urlopen(request)
        request = Request(self.url + "/api/read", headers={"X-Console-Token": token, "X-Console-Owner": "not-the-owner"})
        with self.assertRaises(HTTPError): urlopen(request)
    def test_external_host_rejected(self):
        request = Request(self.url, headers={"Host": "untrusted.example"})
        with self.assertRaises(HTTPError) as error: urlopen(request)
        self.assertEqual(error.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
