"""Stdlib stub of the report backend used by the offline Playwright lane.

Serves the three reasoning fixtures the e2e tests drive, shaped exactly like
``ChatResponse`` (webreport/backend/main.py) plus the ``reasoning`` field.
No third-party dependency, no network egress: it binds loopback only.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

REASONING_FULL = (
    "Шаг 1: выбираю инструмент выборки очков.\n\n"
    "Шаг 2: сортирую команды и оформляю таблицу."
)
REASONING_PARTIAL = "Шаг 1: выбираю инструмент выборки очков."

ANSWER_WITH_REASONING = "Отчёт по очкам команд готов."
ANSWER_WITHOUT_REASONING = "Отчёт без рассуждений готов."
FAILURE_MESSAGE = "Не удалось построить отчёт: превышено время ожидания."

REPORT_ROWS: list[dict[str, Any]] = [
    {"team": "Суровая реальность", "total_points": 42},
    {"team": "Белградские тигры", "total_points": 37},
]


def _chat_response(
    *,
    success: bool,
    message: str,
    reasoning: str | None,
    error: str | None = None,
    data: Any = None,
) -> dict[str, Any]:
    return {
        "success": success,
        "session_id": "e2e-stub-session",
        "data": data,
        "query_info": [],
        "message": message,
        "timestamp": datetime.now().isoformat(),
        "error": error,
        "reasoning": reasoning,
    }


def fixture_with_reasoning() -> dict[str, Any]:
    """Fixture 1: successful answer carrying full reasoning."""
    return _chat_response(
        success=True,
        message=ANSWER_WITH_REASONING,
        reasoning=REASONING_FULL,
        data=REPORT_ROWS,
    )


def fixture_without_reasoning() -> dict[str, Any]:
    """Fixture 2: successful answer with no reasoning at all."""
    return _chat_response(
        success=True,
        message=ANSWER_WITHOUT_REASONING,
        reasoning=None,
        data=REPORT_ROWS,
    )


def fixture_failure_partial() -> dict[str, Any]:
    """Fixture 3: failed request carrying best-effort partial reasoning."""
    return _chat_response(
        success=False,
        message=FAILURE_MESSAGE,
        reasoning=REASONING_PARTIAL,
        error=FAILURE_MESSAGE,
    )


ROUTES: tuple[tuple[str, Callable[[], dict[str, Any]]], ...] = (
    ("сбой", fixture_failure_partial),
    ("без", fixture_without_reasoning),
    ("обычный", fixture_with_reasoning),
)


def select_fixture(message: str) -> dict[str, Any]:
    lowered = message.lower()
    for keyword, builder in ROUTES:
        if keyword in lowered:
            return builder()
    return _chat_response(
        success=False,
        message=f"Неизвестный сценарий: {message}",
        reasoning=None,
        error="unknown fixture",
    )


class RecordingServer(ThreadingHTTPServer):
    """Loopback HTTP server that remembers which endpoints were hit."""

    daemon_threads = True

    def __init__(self, address: tuple[str, int], handler: type[BaseHTTPRequestHandler]) -> None:
        super().__init__(address, handler)
        self.received: list[tuple[str, str]] = []


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 - stdlib signature
        return

    def do_GET(self) -> None:
        if self.path == "/health":
            self._record("GET", self.path)
            self._send({"status": "ok", "service": "stub-backend"})
            return
        self._send({"detail": "not found"}, status=404)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        self._record("POST", self.path)
        if self.path == "/api/chat":
            payload = json.loads(raw.decode("utf-8"))
            message = payload.get("message", "")
            self._send(select_fixture(message if isinstance(message, str) else ""))
            return
        if self.path.startswith("/api/clear/"):
            self._send({"success": True})
            return
        self._send({"detail": "not found"}, status=404)

    def _record(self, method: str, path: str) -> None:
        server = self.server
        if isinstance(server, RecordingServer):
            server.received.append((method, path))

    def _send(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class StubBackend:
    """Loopback-only stub server running in a daemon thread."""

    def __init__(self) -> None:
        self._server = RecordingServer(("127.0.0.1", 0), _Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def port(self) -> int:
        return int(self._server.server_address[1])

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    @property
    def received(self) -> list[tuple[str, str]]:
        return self._server.received

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)
