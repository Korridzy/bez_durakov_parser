"""Fixtures for the offline stub-backed Playwright lane.

Starts the stdlib stub backend and a real Streamlit process, both on loopback
ports, and enforces offline behaviour on BOTH sides: the browser context aborts
every non-loopback request, and the Streamlit child runs with the
``_sitecustomize`` socket guard prepended to its PYTHONPATH.
"""

from __future__ import annotations

import importlib
import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import pytest

TESTS_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = TESTS_DIR.parent
SITECUSTOMIZE_DIR = TESTS_DIR / "_sitecustomize"

sys.path.insert(0, str(TESTS_DIR))

# importlib, not a direct import: tests_e2e is a sys.path dir, not a package.
stub_backend_module = importlib.import_module("stub_backend")
StubBackend = stub_backend_module.StubBackend

LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
STREAMLIT_BOOT_TIMEOUT_SECONDS = 120.0


@dataclass(frozen=True)
class Payloads:
    """Text the stub backend serves, exposed to tests without cross-imports."""

    answer_with_reasoning: str
    answer_without_reasoning: str
    failure_message: str
    reasoning_full: str
    reasoning_partial: str


@dataclass(frozen=True)
class StreamlitApp:
    """The live Streamlit child under test."""

    url: str
    pid: int
    guard_marker: Path
    guard_dir: Path

    def child_environ(self) -> dict[str, str]:
        """Environment of the RUNNING child, read from /proc (Linux only)."""
        raw = Path(f"/proc/{self.pid}/environ").read_bytes()
        entries = (item.decode("utf-8", "replace") for item in raw.split(b"\0") if item)
        return dict(entry.split("=", 1) for entry in entries if "=" in entry)


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def _streamlit_ready(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=2) as response:
            return response.status == 200
    except (urllib.error.URLError, OSError):
        return False


def _wait_until_ready(process: subprocess.Popen[bytes], port: int, log_path: Path) -> None:
    deadline = time.monotonic() + STREAMLIT_BOOT_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(
                f"Streamlit exited with code {process.returncode} during startup.\n"
                f"--- child log ---\n{log_path.read_text(encoding='utf-8', errors='replace')}"
            )
        if _streamlit_ready(port):
            return
        time.sleep(0.5)
    raise RuntimeError(
        f"Streamlit did not become ready on port {port} within "
        f"{STREAMLIT_BOOT_TIMEOUT_SECONDS:.0f}s.\n"
        f"--- child log ---\n{log_path.read_text(encoding='utf-8', errors='replace')}"
    )


def _terminate(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    group = os.getpgid(process.pid)
    os.killpg(group, signal.SIGTERM)
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        os.killpg(group, signal.SIGKILL)
        process.wait(timeout=15)


@pytest.fixture(scope="session", autouse=True)
def require_chromium(playwright) -> None:
    try:
        executable = Path(playwright.chromium.executable_path)
    except Exception as error:  # pragma: no cover - depends on host install state
        pytest.fail(f"Chromium unavailable ({error}). Run: cd webreport && make test-e2e-setup", pytrace=False)
    if not executable.exists():
        pytest.fail(f"Chromium missing at {executable}. Run: cd webreport && make test-e2e-setup", pytrace=False)


@pytest.fixture(scope="session")
def stub_backend() -> Iterator[StubBackend]:
    backend = StubBackend()
    backend.start()
    yield backend
    backend.stop()


@pytest.fixture(scope="session")
def socket_guard_marker(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return tmp_path_factory.mktemp("socket-guard") / "connections.log"


@pytest.fixture(scope="session")
def streamlit_app(
    stub_backend: StubBackend,
    socket_guard_marker: Path,
    tmp_path_factory: pytest.TempPathFactory,
) -> Iterator[StreamlitApp]:
    port = _free_port()
    log_path = tmp_path_factory.mktemp("streamlit") / "streamlit.log"
    pythonpath = os.pathsep.join(
        path for path in (str(SITECUSTOMIZE_DIR), os.environ.get("PYTHONPATH", "")) if path
    )
    env = {
        **os.environ,
        "API_BASE_URL": stub_backend.base_url,
        "CHAT_REQUEST_TIMEOUT_SECONDS": "70",
        "STREAMLIT_BROWSER_GATHER_USAGE_STATS": "false",
        "PYTHONPATH": pythonpath,
        "E2E_SOCKET_GUARD_MARKER": str(socket_guard_marker),
    }
    command = [
        "poetry",
        "run",
        "streamlit",
        "run",
        "main.py",
        "--server.headless",
        "true",
        "--server.port",
        str(port),
    ]
    with log_path.open("wb") as log_file:
        process = subprocess.Popen(
            command,
            cwd=FRONTEND_DIR,
            env=env,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            _wait_until_ready(process, port, log_path)
            yield StreamlitApp(
                url=f"http://127.0.0.1:{port}",
                pid=process.pid,
                guard_marker=socket_guard_marker,
                guard_dir=SITECUSTOMIZE_DIR,
            )
        finally:
            _terminate(process)


@pytest.fixture(scope="session")
def payloads() -> Payloads:
    return Payloads(
        answer_with_reasoning=stub_backend_module.ANSWER_WITH_REASONING,
        answer_without_reasoning=stub_backend_module.ANSWER_WITHOUT_REASONING,
        failure_message=stub_backend_module.FAILURE_MESSAGE,
        reasoning_full=stub_backend_module.REASONING_FULL,
        reasoning_partial=stub_backend_module.REASONING_PARTIAL,
    )


@pytest.fixture
def blocked_requests() -> list[str]:
    return []


@pytest.fixture(autouse=True)
def block_external_requests(context, blocked_requests: list[str]) -> None:
    """Abort every browser request that would leave the loopback interface."""

    def handler(route, request) -> None:
        host = urlparse(request.url).hostname
        if host in LOOPBACK_HOSTS:
            route.continue_()
            return
        blocked_requests.append(request.url)
        route.abort()

    context.route("**/*", handler)


@pytest.fixture
def app_page(page, streamlit_app: StreamlitApp):
    page.goto(streamlit_app.url)
    page.get_by_placeholder("Опишите нужный отчёт...").wait_for(timeout=30_000)
    return page
