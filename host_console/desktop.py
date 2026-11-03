"""Double-click Windows launcher. Startup never enumerates or opens a UART."""
import argparse
import json
import os
from pathlib import Path
import socket
import sys
import threading
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import urlopen
import webbrowser

import server as console

APP_ID = "NexusRV.Industrial.Console.Desktop"
VERSION = "host-minimal-console-20261102-v1"
TITLE = "NexusRV · 智能助手"


class DesktopHandler(console.Handler):
    def do_GET(self):
        if urlsplit(self.path).path == "/api/desktop":
            try:
                self._local()
                return self._send({"app": APP_ID, "version": VERSION})
            except ValueError as exc:
                return self._send({"error": str(exc)}, 400)
        return super().do_GET()


class DesktopServer(console.ConsoleServer):
    allow_reuse_address = False

    def server_bind(self):
        # Windows SO_REUSEADDR can admit a second listener on the same port.
        # Keep one explicit local owner; never race two UART bridges.
        if os.name == "nt":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        return super().server_bind()

    def finish_request(self, request, client_address):
        DesktopHandler(request, client_address, self)


def existing_desktop(port):
    try:
        with urlopen(f"http://127.0.0.1:{port}/api/desktop", timeout=1) as response:
            identity = json.load(response)
        return identity.get("app") == APP_ID and identity.get("version") == VERSION
    except (OSError, URLError, ValueError):
        return False


class DesktopApp:
    def __init__(self, root, service, open_browser=True, opener=None):
        import tkinter as tk
        from tkinter import ttk
        self.root, self.service = root, service
        self.opener = opener or webbrowser.open
        self.url = f"http://localhost:{service.server_port}"
        self.closed = False
        root.title(TITLE)
        root.geometry("540x315")
        root.resizable(False, False)
        root.configure(background="#f1f4ef")
        icon = console.ROOT / "desktop-icon.png"
        if icon.exists():
            self.icon = tk.PhotoImage(file=str(icon))
            root.iconphoto(True, self.icon)
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("Launch.TButton", font=("Microsoft YaHei UI", 11), padding=(16, 10))
        tk.Label(root, text="NEXUSRV", bg="#f1f4ef", fg="#147d69",
                 font=("Microsoft YaHei UI", 12, "bold")).pack(anchor="w", padx=30, pady=(24, 4))
        tk.Label(root, text="工控机演示平台", bg="#f1f4ef", fg="#173c34",
                 font=("Microsoft YaHei UI", 23, "bold")).pack(anchor="w", padx=28)
        self.status = tk.StringVar(value="本地服务已启动 · 等待你在网页连接板卡")
        tk.Label(root, textvariable=self.status, bg="#f1f4ef", fg="#375b50",
                 font=("Microsoft YaHei UI", 10)).pack(anchor="w", padx=30, pady=(12, 5))
        tk.Label(root, text=self.url, bg="#f1f4ef", fg="#147d69",
                 font=("Consolas", 12)).pack(anchor="w", padx=30)
        row = tk.Frame(root, bg="#f1f4ef")
        row.pack(anchor="w", padx=30, pady=(18, 10))
        self.open_button = ttk.Button(row, text="打开展示页面", style="Launch.TButton", command=self.open_page)
        self.open_button.pack(side="left", padx=(0, 12))
        self.exit_button = ttk.Button(row, text="退出展示台", style="Launch.TButton", command=self.close)
        self.exit_button.pack(side="left")
        tk.Label(root, text="手机拍摄屏幕和实物灯 · 窗口保持运行", bg="#f1f4ef", fg="#65786f",
                 font=("Microsoft YaHei UI", 9)).pack(anchor="w", padx=30)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.thread = threading.Thread(target=service.serve_forever, daemon=True)
        self.thread.start()
        root.after(500, self.update_status)
        if open_browser:
            root.after(200, self.open_page)

    def open_page(self):
        self.opener(self.url)

    def update_status(self):
        if self.closed:
            return
        with self.service.bridge.lock:
            bridge = self.service.bridge
            if bridge.device is None:
                value = "本地服务已启动 · 等待你在网页连接板卡"
            elif bridge.pending:
                value = f"已连接 {bridge.port} · 正在等待板端回执"
            else:
                value = f"已连接 {bridge.port} · 操作请在网页完成"
        self.status.set(value)
        self.root.after(500, self.update_status)

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.service.shutdown()
        self.service.bridge.disconnect()
        self.service.server_close()
        self.thread.join(timeout=2)
        self.root.destroy()


def write_result(path, result):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def smoke_test(path):
    """Explicit offline package check; no serial enumeration/open or browser."""
    import hashlib
    import serial
    import serial.tools.list_ports
    result = {"status": "FAIL", "version": VERSION, "frozen": bool(getattr(sys, "frozen", False)),
              "serial_version": serial.VERSION, "hardware_actions": 0, "checks": []}
    calls = []
    bridge = console.SerialBridge(serial_factory=lambda *a, **k: calls.append("open"))
    bridge.ports = lambda: calls.append("enumerate")
    service = DesktopServer(("127.0.0.1", 0), bridge)
    thread = threading.Thread(target=service.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{service.server_port}"
        bundle = json.loads((console.ROOT / "BUNDLE.json").read_text(encoding="utf-8"))
        for name, digest in bundle["static_files"].items():
            with urlopen(base + "/" + name, timeout=5) as response:
                assert hashlib.sha256(response.read()).hexdigest() == digest, name
        result["checks"].append("all_embedded_assets_exact_http_hashes")
        with urlopen(base + "/api/bootstrap", timeout=5) as response:
            value = json.load(response)
            assert value["baud"] == 115200 and not value["test_fixture"]
            assert "camera=()" in response.headers["Permissions-Policy"]
        result["checks"].append("production_bootstrap_115200_no_camera")
        assert existing_desktop(service.server_port)
        result["checks"].append("recognizes_own_running_instance")
        try:
            duplicate = DesktopServer(("127.0.0.1", service.server_port))
        except OSError:
            result["checks"].append("duplicate_cannot_bind_same_port")
        else:
            duplicate.server_close()
            raise AssertionError("Duplicate listener unexpectedly bound")
        assert console.validate_command(":act 打开灯。") == ":act 打开灯。\n".encode("utf-8")
        for command in (":reload", ":reset", ":W"):
            try:
                console.validate_command(command)
            except ValueError:
                pass
            else:
                raise AssertionError("Maintenance command accepted")
        result["checks"].append("original_utf8_and_maintenance_commands_rejected")
        from tool_dispatch import validated_call
        data=json.loads((console.STATIC/'prepared-tool-tokens.json').read_text(encoding='utf8'))
        validated_call(dict(call_id='offline-tool-check-0001',tool='twinkle',arguments=data['arguments'],source_entry_id=data['entry_id'],source_uart_sha256=data['original_uart_sha256']))
        result['checks'].append('registered_code_package_files_and_prepared_token_identity')
        from light_switch import validate_switch_call
        for action in ('on','off'):
            assert validate_switch_call(dict(call_id='offline-switch-check-001',action=action))['action']==action
        result['checks'].append('fixed_on_off_shortcut_module_available_offline')
        assert not calls and bridge.device is None
        result["checks"].append("no_automatic_serial_enumeration_open_or_write")
        result["status"] = "PASS_WINDOWS_EXE_OFFLINE_ONLY"
    except Exception as exc:
        result["error"] = repr(exc)
    finally:
        service.shutdown()
        bridge.disconnect()
        service.server_close()
        thread.join(timeout=2)
        result["service_thread_stopped"] = not thread.is_alive()
        write_result(path, result)
    return 0 if result["status"].startswith("PASS") else 1


def gui_test(path):
    """Create the actual native window and click its buttons; never use hardware."""
    import tkinter as tk
    result = {"status": "FAIL", "version": VERSION, "frozen": bool(getattr(sys, "frozen", False)),
              "hardware_actions": 0, "checks": []}
    calls = []
    bridge = console.SerialBridge(serial_factory=lambda *a, **k: calls.append("serial_open"))
    bridge.ports = lambda: calls.append("serial_enumeration")
    service = DesktopServer(("127.0.0.1", 0), bridge)
    root = tk.Tk()
    app = DesktopApp(root, service, open_browser=False, opener=lambda url: calls.append(url))

    def check():
        try:
            assert root.winfo_viewable() and root.winfo_width() == 540
            result["checks"].append("native_tk_window_visible")
            assert not calls
            result["checks"].append("startup_no_browser_or_hardware_in_test_mode")
            app.open_button.invoke()
            assert calls == [app.url]
            result["checks"].append("open_button_targets_current_local_page")
            assert service.bridge.device is None
            result["checks"].append("window_status_does_not_enumerate_or_open_serial")
            result["window"] = {"width": root.winfo_width(), "height": root.winfo_height(),
                                "title": root.title(), "status": app.status.get()}
            app.exit_button.invoke()
            assert not app.thread.is_alive()
            result["checks"].append("exit_button_stops_service")
            result["status"] = "PASS_WINDOWS_NATIVE_WINDOW_OFFLINE_ONLY"
        except Exception as exc:
            result["error"] = repr(exc)
            app.close()
        finally:
            write_result(path, result)
    root.after(1000, check)
    root.mainloop()
    return 0 if result["status"].startswith("PASS") else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8769)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--smoke-test", metavar="JSON")
    parser.add_argument("--ui-smoke-test", metavar="JSON")
    args = parser.parse_args()
    if args.smoke_test:
        return smoke_test(args.smoke_test)
    if args.ui_smoke_test:
        return gui_test(args.ui_smoke_test)
    import tkinter as tk
    from tkinter import messagebox
    root = tk.Tk()
    root.withdraw()
    try:
        if not 1 <= args.port <= 65535:
            raise ValueError("端口应在 1–65535 之间")
        try:
            service = DesktopServer(("127.0.0.1", args.port))
        except OSError as exc:
            if existing_desktop(args.port):
                if not args.no_browser:
                    webbrowser.open(f"http://localhost:{args.port}")
                root.destroy()
                return 0
            raise RuntimeError(f"端口 {args.port} 已被其他程序占用。请先关闭旧版展示台，再双击启动。") from exc
        app = DesktopApp(root, service, open_browser=not args.no_browser)
        root.deiconify()
        root.mainloop()
        return 0
    except Exception as exc:
        messagebox.showerror(TITLE, str(exc), parent=root)
        root.destroy()
        return 1


if __name__ == "__main__":
    # PyInstaller --windowed has no console streams. Preserve local HTTP errors.
    if sys.stderr is None or sys.stdout is None:
        folder = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "NexusRVDemo"
        folder.mkdir(parents=True, exist_ok=True)
        log = (folder / "desktop.log").open("a", encoding="utf-8", buffering=1)
        if sys.stderr is None:
            sys.stderr = log
        if sys.stdout is None:
            sys.stdout = log
    raise SystemExit(main())
