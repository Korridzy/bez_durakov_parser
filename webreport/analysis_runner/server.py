"""Private transport for disposable Python analyses; no dataset mounts or credentials."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOCK = threading.Lock()
MAX_INPUT = 8 * 1024 * 1024


def execute(payload):
    code = payload.get("code")
    inputs = payload.get("inputs")
    if not isinstance(code, str) or not 1 <= len(code) <= 32000 or not isinstance(inputs, dict):
        return {"ok": False, "error": "Expected code (1–32000 characters) and named inputs"}
    if len(inputs) > 8:
        return {"ok": False, "error": "Use at most eight input datasets"}
    with tempfile.TemporaryDirectory(prefix="analysis-") as folder:
        os.chown(folder, 65534, 65534)
        env = {"PATH": "/usr/local/bin:/usr/bin", "HOME": folder, "TMPDIR": folder,
               "OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
               "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8"}
        with tempfile.TemporaryFile() as output:
            process = subprocess.Popen(
                [sys.executable, "-I", "/runner/worker.py"], cwd=folder, env=env,
                stdin=subprocess.PIPE, stdout=output, stderr=output, close_fds=True,
                user=65534, group=65534, extra_groups=[], start_new_session=True,
            )
            try:
                process.communicate(json.dumps(payload).encode(), timeout=22)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()
                return {"ok": False, "error": "Analysis exceeded 22 seconds. Reduce the data or computation."}
            output.seek(0)
            log = output.read(6000).decode("utf-8", errors="replace")
        target = Path(folder, "result.json")
        if process.returncode or not target.is_file() or target.is_symlink():
            return {"ok": False, "error": "Analysis stopped (resource limit or execution error).", "log": log}
        if target.stat().st_size > 4 * 1024 * 1024:
            return {"ok": False, "error": "Analysis result exceeds 4 MiB"}
        try:
            result = json.loads(target.read_text(encoding="utf-8"))
            if not isinstance(result, dict) or not isinstance(result.get("ok"), bool):
                raise ValueError("Invalid result")
        except (ValueError, OSError):
            return {"ok": False, "error": "Analysis did not return a valid JSON result"}
        return {**result, "log": log}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # Never log submitted code or data.

    def reply(self, status, value):
        body = json.dumps(value, ensure_ascii=False, allow_nan=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        self.reply(200 if self.path == "/health" else 404, {"ready": self.path == "/health"})

    def do_POST(self):
        self.connection.settimeout(30)
        if self.path != "/execute":
            return self.reply(404, {"error": "Unknown endpoint"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_INPUT:
                return self.reply(413, {"error": "Input exceeds 8 MiB"})
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("Expected object")
        except (ValueError, OSError):
            return self.reply(400, {"error": "Invalid analysis input"})
        if not LOCK.acquire(blocking=False):
            return self.reply(429, {"error": "Another analysis is running; retry shortly"})
        try:
            self.reply(200, execute(payload))
        except Exception:
            self.reply(500, {"error": "Analysis executor unavailable"})
        finally:
            LOCK.release()


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", 8080), Handler).serve_forever()
