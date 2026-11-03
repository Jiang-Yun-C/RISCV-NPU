#!/usr/bin/env python3
"""NexusRV local demo console. Serves offline assets and an optional UART bridge."""
import argparse
import base64
from collections import deque
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
from pathlib import Path
import secrets
import threading
import time
from urllib.parse import parse_qs, urlsplit, unquote
import webbrowser

ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"


def validate_command(command):
    """Only expose bounded service input; never programming/reset/pressure commands."""
    if not isinstance(command, str):
        raise ValueError("请求必须是文字")
    encoded = command.encode("utf-8")
    if len(encoded) > 4096 or any(ord(c) < 32 or ord(c) == 127 for c in command):
        raise ValueError("请使用不超过 4096 UTF-8 字节的单行请求")
    if command in ("", ":memory", ":telemetry", ":stream 0", ":stream 1", ":identity"):
        return encoded + b"\n"
    if command.startswith(":ids "):
        parts = command.split(" ")
        if len(parts) < 3 or any(not s.isascii() or not s.isdecimal() for s in parts[1:]):
            raise ValueError("Token 请求格式错误")
        maximum, *ids = map(int, parts[1:])
        if not 1 <= maximum <= 128 or not 1 <= len(ids) <= 512 or any(i > 151935 for i in ids):
            raise ValueError("生成数应为 1–128，输入应为 1–512 个有效 token")
    elif command.startswith(":text "):
        match = re.fullmatch(r":text ([0-9]+) (.+)", command)
        if not match or not 1 <= int(match[1]) <= 128 or not match[2].strip():
            raise ValueError("文本请求需要 1–128 的生成上限与非空正文")
    elif re.fullmatch(r":cancel [0-9a-f]{16}", command) and int(command[8:], 16):
        pass
    elif command in (":prefix 0", ":prefix 1"):
        pass
    elif re.fullmatch(r":timeout [0-9]+", command) and 1 <= int(command[9:]) <= 86400:
        pass
    elif command.startswith(":"):
        raise ValueError("演示台不提供此控制命令")
    elif not command.strip():
        raise ValueError("请输入请求")
    return encoded + b"\n"


class SerialBridge:
    """One explicit owner, bounded receive buffer and one outstanding command."""
    def __init__(self, serial_factory=None):
        self.lock = threading.RLock()
        self.changed = threading.Condition(self.lock)
        self.device = None
        self.owner = None
        self.port = None
        self.seq = 0
        self.chunks = deque(maxlen=2048)
        self.error = None
        self.pending = False
        self.synced = False
        self.line = bytearray()
        self.thread = None
        self.serial_factory = serial_factory
        self.text_output = False
        self.text_remaining = None
        self.text_prefix = False
        self.active_session = None
        self.cancel_supported = False

    def ports(self):
        try:
            from serial.tools import list_ports
        except ImportError:
            return {"available": False, "ports": [], "message": "Python 串口连接需要 pyserial；也可使用 Chrome/Edge 浏览器直连"}
        return {"available": True, "ports": [dict(device=p.device, description=p.description,
            vid=p.vid, pid=p.pid, serial=p.serial_number,
            expected=p.vid == 0x10c4 and p.pid == 0xea60 and p.serial_number == "0001")
            for p in list_ports.comports()]}

    def connect(self, port, owner, baud=115200):
        if baud not in (115200, 500000):
            raise ValueError("串口波特率应为 115200 或 500000，与板端配置一致")
        with self.lock:
            if self.device:
                if self.owner == owner and self.port == port and self.baud == baud:
                    return dict(port=port, baud=self.baud, resumed=True, pending=self.pending, after=self.seq)
                raise ValueError("串口已被一个演示窗口连接，请先在该窗口断开")
            ports = self.ports()
            matches = [p for p in ports["ports"] if p["device"] == port and p["expected"]]
            if len(matches) != 1:
                raise ValueError("未找到指定的 CP2102（10c4:ea60，serial 0001）")
            if self.serial_factory is None:
                import serial
                factory = serial.Serial
            else:
                factory = self.serial_factory
            dev = factory(None, baudrate=baud, timeout=.1, write_timeout=5)
            dev.dtr = False
            dev.rts = False
            dev.port = port
            if hasattr(dev, "exclusive"):
                dev.exclusive = True
            try:
                dev.open()
            except Exception:
                dev.close()
                raise
            self.device, self.owner, self.port = dev, owner, port
            self.baud = baud
            self.seq = 0
            self.chunks.clear()
            self.error = None
            self.pending = self.synced = False
            self.line.clear()
            self.text_output = False
            self.text_remaining = None
            self.text_prefix = False
            self.active_session = None
            self.cancel_supported = False
            self.thread = threading.Thread(target=self._reader, args=(dev,), daemon=True)
            self.thread.start()
            return {"port": port, "baud": baud}

    def _consume_ready(self, data):
        """Only recognize control lines outside byte-counted final model text."""
        self.line.extend(data)
        while self.line:
            if self.text_remaining is not None:
                prefix = b"T25 TEXT "
                if self.text_prefix:
                    head = bytes(self.line[:len(prefix)])
                    if not prefix.startswith(head):
                        raise ValueError("TEXTLEN 后缺少正文头")
                    if len(self.line) < len(prefix):
                        break
                    del self.line[:len(prefix)]
                    self.text_prefix = False
                count = min(self.text_remaining, len(self.line))
                del self.line[:count]
                self.text_remaining -= count
                if self.text_remaining or not self.line:
                    break
                if self.line[0] != 10:
                    raise ValueError("正文与 TEXTLEN 长度不一致")
                del self.line[:1]
                self.text_remaining = None
                continue
            if b"\n" not in self.line:
                break
            line, _, rest = self.line.partition(b"\n")
            self.line = bytearray(rest)
            if self.text_output:
                if line.startswith(b"T25 METRICS "):
                    self.text_output = False
                else:
                    continue
            elif line.startswith(b"T25 TEXTLEN "):
                match = re.fullmatch(rb"T25 TEXTLEN 1 bytes=([0-9a-f]{16}) *", line)
                if not match or int(match[1], 16) > 16384:
                    raise ValueError("正文长度记录无效")
                self.text_remaining = int(match[1], 16)
                self.text_prefix = True
                continue
            elif line.startswith(b"T25 TEXT "):
                self.text_output = True
                continue
            if line.startswith(b"T25 CAPABILITIES "):
                self.cancel_supported = b"cancel=1" in line.split()
            if line.startswith(b"T25 REQUEST 1 "):
                match = re.search(rb"(?:^| )session=([0-9a-f]{16})(?: |$)", line)
                if not match or int(match[1], 16) == 0:
                    raise ValueError("请求会话身份无效")
                self.active_session = match[1].decode("ascii")
            if line.rstrip(b"\r") == b"T25 READY":
                self.pending = False
                self.synced = True
                self.active_session = None
        if len(self.line) > 65536:
            raise ValueError("板端输出行超过 64 KiB，连接已关闭")

    def _reader(self, dev):
        try:
            while self.device is dev:
                # Waiting for one byte returns immediately when it arrives;
                # never read a fixed large count and wait for timeout/fill/LF.
                data = dev.read(min(dev.in_waiting or 1, 32768))
                received_at = time.monotonic_ns()
                if not data:
                    continue
                with self.changed:
                    if self.device is not dev:
                        break
                    self.seq += 1
                    self.chunks.append((self.seq, base64.b64encode(data).decode("ascii"), str(received_at)))
                    self._consume_ready(data)
                    self.changed.notify_all()
        except Exception as exc:
            with self.changed:
                if self.device is dev:
                    self.error = str(exc)
                    self.device = None
                    self.changed.notify_all()
        finally:
            dev.close()

    def _check_owner(self, owner):
        if not self.owner or not hmac.compare_digest(self.owner, owner):
            raise ValueError("串口属于另一个演示窗口")

    def write(self, command, owner):
        data = validate_command(command)
        with self.lock:
            self._check_owner(owner)
            if not self.device:
                raise ValueError("串口未连接")
            cancel = command.startswith(":cancel ")
            if cancel and not (self.pending and self.cancel_supported and command[8:] == self.active_session):
                raise ValueError("取消命令必须绑定正在执行的板端会话")
            if self.pending and not cancel:
                raise ValueError("等待当前操作的 T25 READY 后再发送")
            if not self.synced and command != "":
                raise ValueError("请先同步板端服务")
            self.pending = True
            try:
                write_start = time.monotonic_ns()
                written = self.device.write(data)
                write_return = time.monotonic_ns()
                if written != len(data):
                    raise IOError("串口写入不完整，请重新同步")
                self.device.flush()
                flush_end = time.monotonic_ns()
                return dict(clock="python.time.monotonic_ns", write_start=str(write_start),
                            write_return=str(write_return), flush_end=str(flush_end), bytes=len(data))
            except Exception:
                # Do not allow another command after an ambiguous partial write.
                self.synced = False
                raise

    def read(self, after, owner, wait=0):
        if after < 0 or not 0 <= wait <= 25:
            raise ValueError("串口读取游标或等待时间无效")
        with self.changed:
            self._check_owner(owner)
            if after > self.seq:
                raise ValueError("串口读取游标超出当前连接")
            if wait and self.seq <= after and self.device is not None:
                self.changed.wait_for(lambda: self.seq > after or self.device is None, timeout=wait)
                self._check_owner(owner)
            if self.chunks and after < self.chunks[0][0] - 1:
                raise ValueError("接收缓冲已溢出，记录不完整；请重新连接")
            return dict(chunks=[dict(seq=item[0], data=item[1], received_ns=item[2])
                               for item in self.chunks if item[0] > after],
                        clock="python.time.monotonic_ns", connected=self.device is not None, error=self.error,
                        pending=self.pending, synced=self.synced)

    def disconnect(self, owner=None):
        with self.lock:
            if owner is not None:
                self._check_owner(owner)
            dev, self.device = self.device, None
            self.owner = None
            self.changed.notify_all()
            if dev:
                dev.close()


class ConsoleServer(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, address, bridge=None):
        self.bridge = bridge or SerialBridge()
        self.token = secrets.token_urlsafe(32)
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        if args and str(args[1] if len(args) > 1 else "") not in ("200", "304"):
            super().log_message(fmt, *args)

    def _local(self):
        host = urlsplit("http://" + self.headers.get("Host", "")).hostname
        if host not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError("仅允许通过 localhost 访问")

    def _send(self, value, code=200):
        self._bytes(json.dumps(value, ensure_ascii=False).encode(), "application/json; charset=utf-8", code)

    def _bytes(self, data, kind, code=200):
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; connect-src 'self'; frame-ancestors 'none'")
        self.send_header("Permissions-Policy", "serial=(self), camera=(self), display-capture=(self)")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        try:
            self._local()
            route = urlsplit(self.path)
            if route.path == "/api/bootstrap":
                return self._send({"token": self.server.token, "baud": 115200})
            if route.path == "/api/ports":
                return self._send(self.server.bridge.ports())
            if route.path == "/api/read":
                self._authorize()
                after = int(parse_qs(route.query).get("after", ["0"])[0])
                wait = float(parse_qs(route.query).get("wait", ["0"])[0])
                return self._send(self.server.bridge.read(after, self.headers.get("X-Console-Owner", ""), wait))
            name = unquote(route.path).lstrip("/") or "index.html"
            path = (STATIC / name).resolve()
            if STATIC.resolve() not in path.parents or not path.is_file():
                return self._send({"error": "文件不存在"}, 404)
            mime = {".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
                ".js": "text/javascript; charset=utf-8", ".json": "application/json; charset=utf-8", ".svg": "image/svg+xml"}
            self._bytes(path.read_bytes(), mime.get(path.suffix, "application/octet-stream"))
        except (ValueError, OSError) as exc:
            self._send({"error": str(exc)}, 400)

    def _authorize(self):
        if not hmac.compare_digest(self.headers.get("X-Console-Token", ""), self.server.token):
            raise ValueError("请刷新页面以重新获取连接凭据")

    def do_POST(self):
        try:
            self._local()
            self._authorize()
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 32768:
                raise ValueError("请求大小无效")
            body = json.loads(self.rfile.read(length))
            owner = self.headers.get("X-Console-Owner", "")
            if len(owner) < 16:
                raise ValueError("窗口标识缺失")
            path = urlsplit(self.path).path
            if path == "/api/connect":
                value = self.server.bridge.connect(body.get("port"), owner, body.get("baud", 115200))
            elif path == "/api/write":
                timing = self.server.bridge.write(body.get("command"), owner)
                value = {"ok": True, "timing": timing}
            elif path == "/api/disconnect":
                self.server.bridge.disconnect(owner)
                value = {"ok": True}
            else:
                return self._send({"error": "接口不存在"}, 404)
            self._send(value)
        except (ValueError, OSError, TypeError) as exc:
            self._send({"error": str(exc)}, 400)
        except Exception as exc:
            self._send({"error": str(exc)}, 503)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", help="Open the local console in your browser")
    args = parser.parse_args()
    server = ConsoleServer(("127.0.0.1", args.port))
    url = f"http://localhost:{server.server_port}"
    print(f"NexusRV 676 console: {url}\nChrome / Edge: browser UART; Python UART: pip install pyserial\nCtrl+C to stop.", flush=True)
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.bridge.disconnect()
        server.server_close()


if __name__ == "__main__":
    main()
