"""Small task-independent command runner; never overwrite a previous run."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import time
import uuid


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def content_id(files):
    return hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class StepFailure(Exception):
    def __init__(self, name, exit_code):
        super().__init__(f"{name}: exit {exit_code}")
        self.exit_code = exit_code if exit_code in (124, 127, 130) else 1


class EvidenceRun:
    def __init__(self, root, task, run_id=None):
        self.root = Path(root).resolve()
        self.run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ-") + uuid.uuid4().hex[:8]
        for component in (task, self.run_id):
            if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,100}", component):
                raise ValueError("task/run-id must be a simple filename component")
        self.path = self.root / "evidence" / task / self.run_id
        self.build = self.root / "build" / task / self.run_id
        if self.build.exists():
            raise FileExistsError(f"build already exists: {self.build}")
        self.path.mkdir(parents=True, exist_ok=False)
        self.build.mkdir(parents=True, exist_ok=False)
        (self.path / "logs").mkdir()
        self.steps = []
        self.checks = []
        self.manifest = {"schema_version": 1, "task_id": task, "run_id": self.run_id,
                         "started_at": utc_now(), "status": "RUNNING", "exit_code": None}
        self.flush()

    def flush(self):
        write_json(self.path / "commands.json", self.steps)
        write_json(self.path / "checks.json", {"schema_version": 1, "checks": self.checks})
        write_json(self.path / "manifest.json", self.manifest)

    def check(self, name, condition, detail):
        self.checks.append({"name": name, "status": "PASS" if condition else "FAIL", "detail": detail})
        self.flush()
        if not condition:
            raise StepFailure(name, 1)

    @staticmethod
    def _kill_group(process):
        # VCS launches compiler and simulator children; kill the entire session on timeout.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()

    def execute(self, name, argv, timeout, cwd=None):
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]*", name) or any(s["name"] == name for s in self.steps):
            raise ValueError("step names must be unique simple filenames")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        argv = [str(arg) for arg in argv]
        record = {"name": name, "argv": argv, "cwd": str(cwd or self.build),
                  "timeout_seconds": timeout, "started_at": utc_now(), "status": "RUNNING",
                  "stdout": f"logs/{name}.stdout.log", "stderr": f"logs/{name}.stderr.log"}
        self.steps.append(record)
        self.flush()
        start = time.monotonic()
        with (self.path / record["stdout"]).open("w") as stdout, (self.path / record["stderr"]).open("w") as stderr:
            process = None
            try:
                process = subprocess.Popen(argv, cwd=record["cwd"], stdout=stdout, stderr=stderr,
                                           start_new_session=True)
                code = process.wait(timeout=timeout)
                record["process_returncode"] = code
            except subprocess.TimeoutExpired:
                self._kill_group(process)
                code = 124
                record["process_returncode"] = process.returncode
                stderr.write(f"TIMEOUT after {timeout} seconds; process group killed\n")
            except OSError as error:
                code = 127
                stderr.write(str(error) + "\n")
            except KeyboardInterrupt:
                if process is not None:
                    self._kill_group(process)
                code = 130
                stderr.write("INTERRUPTED; process group killed\n")
        record.update(exit_code=code, finished_at=utc_now(), duration_seconds=round(time.monotonic() - start, 3),
                      status="PASS" if code == 0 else "FAIL")
        self.checks.append({"name": name, "status": record["status"], "detail": {"exit_code": code}})
        self.flush()
        if code != 0:
            raise StepFailure(name, code)
        return self.path / record["stdout"]

    def finish(self, exit_code):
        if exit_code == 0 and (any(item["status"] != "PASS" for item in self.steps)
                               or any(item["status"] != "PASS" for item in self.checks)):
            exit_code = 1
        self.manifest.update(status="PASS" if exit_code == 0 else "FAIL", exit_code=exit_code, finished_at=utc_now())
        self.flush()
        (self.path / "exit-status.txt").write_text(str(exit_code) + "\n")
        return exit_code
