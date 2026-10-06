"""Focused lifecycle and route tests for the durable conversation archive."""

import asyncio
import importlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from collections.abc import Mapping
from unittest.mock import AsyncMock, patch

import fastapi
import structlog

# Parent of the mounted bd_shared directory, matching the other backend route tests.
sys.path.insert(0, "/")

net_guard = importlib.import_module("test_net_guard")


def setUpModule() -> None:
    """Keep the in-process route tests offline."""
    net_guard.install()


def archive_settings():
    archive_module = importlib.import_module("archive")
    return archive_module.ArchiveSettings.validate(
        enabled=True,
        retention_days=0,
        store_reasoning=True,
        reasoning_retention_days=30,
        sweep_interval_seconds=0,
    )


def report_response(**overrides: object) -> dict[str, object]:
    response: dict[str, object] = {
        "success": True,
        "data": [{"game": 1}],
        "message": "готовый ответ",
        "query_info": [{"tool": "list_games", "args": {"limit": 1}}],
        "timestamp": "2026-09-21T00:00:00",
        "reasoning": "шаг",
        "verdict": "in_scope",
    }
    response.update(overrides)
    return response


class StubAgentSystem:
    def __init__(self, result: Mapping[str, object] | BaseException) -> None:
        self.result = result
        self.calls: list[tuple[str, str]] = []

    async def head_messages(self, _session_id: str) -> list[object]:
        return []

    async def process_user_request(
        self, user_message: str, session_id: str, history=()
    ) -> dict[str, object]:
        self.calls.append((user_message, session_id))
        if isinstance(self.result, BaseException):
            raise self.result
        return dict(self.result)


class StubSaver:
    def __init__(self, checkpoint_tuple: object = None) -> None:
        self.checkpoint_tuple = checkpoint_tuple
        self.deleted: list[str] = []

    async def aget_tuple(self, _config: Mapping[str, object]) -> object:
        return self.checkpoint_tuple

    async def adelete_thread(self, thread_id: str) -> None:
        self.deleted.append(thread_id)


class ArchiveRouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.main = importlib.import_module("main")
        self.archive_module = importlib.import_module("archive")
        self.session_store = importlib.import_module("session_store")
        self.request_context = importlib.import_module("request_context")
        self.temp_dir = tempfile.TemporaryDirectory()
        self.archive = self.archive_module.ConversationArchive(
            Path(self.temp_dir.name) / "turns.db",
            settings=archive_settings(),
        )
        await self.archive.setup()
        await self.archive.recover_interrupted("route-tests")
        self.saved = {
            name: getattr(self.main, name)
            for name in (
                "admission_lock",
                "agent_system",
                "archive",
                "checkpoint_saver",
                "chat_store",
                "registry",
                "pinned",
                "sessions",
                "tool_service",
            )
        }
        self.main.admission_lock = asyncio.Lock()
        self.main.agent_system = StubAgentSystem(report_response())
        self.main.archive = self.archive
        self.main.checkpoint_saver = StubSaver()
        self.main.pinned = {}
        self.main.sessions = self.session_store.SessionIndex(max_size=4, ttl=60)
        self.main.tool_service = object()
        await importlib.import_module("test_support").install_test_runtime(self.main, self.temp_dir.name)
        structlog.contextvars.clear_contextvars()

    async def asyncTearDown(self) -> None:
        structlog.contextvars.clear_contextvars()
        await self.main.registry.shutdown()
        await self.main.chat_store.close()
        await self.archive.close()
        for name, value in self.saved.items():
            setattr(self.main, name, value)
        self.temp_dir.cleanup()

    async def chat(self, message: str = "покажи игры", session_id: str = "session-1"):
        response = fastapi.Response()
        envelope = await self.main.chat(
            self.main.ChatMessage(message=message, session_id=session_id),
            response,
        )
        return response, envelope

    async def turns(self) -> list[dict[str, object]]:
        return await self.archive.list_turns(limit=20)

    async def test_successful_chat_archives_bound_context_and_result(self) -> None:
        request_id = "request-bound"
        trace_id = "0123456789abcdef0123456789abcdef"
        with structlog.contextvars.bound_contextvars(
            request_id=request_id,
            trace_id=trace_id,
        ):
            response, envelope = await self.chat(
                message="вопрос для архива",
                session_id="session-bound",
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(envelope.success)
        [row] = await self.turns()
        self.assertEqual(row["status"], "ok")
        self.assertEqual(row["request_id"], request_id)
        self.assertEqual(row["trace_id"], trace_id)
        self.assertEqual(row["session_id"], "session-bound")
        self.assertEqual(row["user_message"], "вопрос для архива")
        self.assertEqual(row["assistant_message"], "готовый ответ")
        self.assertEqual(
            json.loads(str(row["tool_calls"])),
            [{"tool": "list_games", "args": {"limit": 1}}],
        )

    async def test_failed_agent_result_is_archived_as_failed(self) -> None:
        support = importlib.import_module("agents.report_support")
        self.main.agent_system = StubAgentSystem(
            support.failure("не удалось", "timeout")
        )

        response, envelope = await self.chat(session_id="session-timeout")

        self.assertEqual(response.status_code, 200)
        self.assertFalse(envelope.success)
        [row] = await self.turns()
        self.assertEqual((row["status"], row["error"]), ("failed", "timeout"))

    async def test_agent_exception_returns_500_and_completes_failed_row(self) -> None:
        self.main.agent_system = StubAgentSystem(RuntimeError("agent exploded"))

        with self.assertRaises(fastapi.HTTPException) as raised:
            await self.chat(session_id="session-error")

        self.assertEqual(raised.exception.status_code, 500)
        [row] = await self.turns()
        self.assertEqual(
            (row["status"], row["error"]),
            ("failed", "internal:RuntimeError"),
        )

    async def test_model_unavailable_503_creates_no_archive_row(self) -> None:
        self.main.agent_system = None
        self.main.checkpoint_saver = None
        response = fastapi.Response()

        envelope = await self.main.chat(
            self.main.ChatMessage(message="недоступно", session_id="session-503"),
            response,
        )

        self.assertEqual(response.status_code, 503)
        self.assertEqual(envelope.error, "llm_proxy_unavailable")
        self.assertEqual(await self.turns(), [])

    async def test_clear_and_history_keep_archive_rows_unchanged(self) -> None:
        saver = StubSaver()
        self.main.checkpoint_saver = saver
        await self.chat(session_id="session-clear")
        before = await self.turns()

        history = await self.main.get_history("session-clear")
        cleared = await self.main.clear_history("session-clear")
        after = await self.turns()

        self.assertEqual(
            history,
            {"session_id": "session-clear", "history": []},
        )
        self.assertTrue(cleared["success"])
        self.assertEqual(saver.deleted, ["session-clear"])
        self.assertEqual(after, before)

    async def test_direct_chat_without_bound_ids_generates_archive_correlation(self) -> None:
        structlog.contextvars.clear_contextvars()

        response, envelope = await self.chat(session_id="session-generated")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(envelope.success)
        [row] = await self.turns()
        request_id = str(row["request_id"])
        self.assertRegex(request_id, re.compile(r"^[0-9a-f]{32}$"))
        self.assertEqual(
            row["trace_id"],
            self.request_context.derive_trace_id(request_id),
        )

    async def test_ttl_eviction_deletes_checkpoint_but_keeps_both_archive_rows(self) -> None:
        saver = StubSaver()
        self.main.checkpoint_saver = saver
        self.main.sessions = self.session_store.SessionIndex(max_size=1, ttl=0)

        await self.chat(message="первый", session_id="ttl-first")
        await self.chat(message="второй", session_id="ttl-second")

        self.assertEqual(saver.deleted, ["ttl-first"])
        self.assertEqual(
            {row["session_id"] for row in await self.turns()},
            {"ttl-first", "ttl-second"},
        )

    async def test_archive_write_error_fails_open_and_logs_structured_event(self) -> None:
        assert self.archive.connection is not None
        with (
            patch.object(
                self.archive.connection,
                "execute",
                new=AsyncMock(side_effect=RuntimeError("archive unavailable")),
            ),
            patch.object(self.archive_module.logger, "error") as error_log,
            structlog.contextvars.bound_contextvars(
                request_id="request-write-failure",
                trace_id="fedcba9876543210fedcba9876543210",
            ),
        ):
            response, envelope = await self.chat(session_id="session-write-failure")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(envelope.success)
        records = [
            call
            for call in error_log.call_args_list
            if call.args and call.args[0] == "archive_write_failed"
        ]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].kwargs["request_id"], "request-write-failure")
        self.assertNotIn("message", records[0].kwargs)


STARTUP_PROBE = """\
import asyncio
import sys
from unittest.mock import AsyncMock, MagicMock, patch
import main

mode = sys.argv[1]

async def probe():
    with patch.object(
        main,
        'initialize_tool_service_with_retry',
        new=AsyncMock(return_value=(None, object(), ())),
    ), patch.object(
        main, 'probe_llm_proxy', new=AsyncMock(return_value=True)
    ), patch.object(main, '_build_agent_system', new=MagicMock()):
        if mode == 'enabled-invalid-path':
            assert main.ARCHIVE_ENABLED is True
            try:
                await main.startup_event()
            except Exception:
                assert main.checkpoint_connection is None
                assert main.checkpoint_saver is None
                print('enabled archive startup raised')
            else:
                raise AssertionError('enabled archive accepted an unusable path')
            return

        assert mode == 'disabled-invalid-path'
        assert main.ARCHIVE_ENABLED is False
        await main.startup_event()
        assert isinstance(main.archive, main.NullArchive)
        await main.shutdown_event()
        print('disabled archive startup succeeded with NullArchive')

asyncio.run(probe())
"""

RECOVERY_PROBE = """\
import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch
import main

async def probe():
    old = main.ConversationArchive(
        main.ARCHIVE_DB_PATH,
        settings=main.ArchiveSettings.from_config(),
    )
    await old.setup()
    await old.recover_interrupted('older-boot')
    row_id = await old.begin(
        request_id='old-request',
        trace_id='0123456789abcdef0123456789abcdef',
        session_id='old-session',
        user_id=None,
        model=main.AGENT_MODEL,
        user_message='unfinished',
    )
    assert isinstance(row_id, int)
    await old.close()

    sweep_calls = []
    original_sweep = main.ConversationArchive.sweep

    async def observed_sweep(archive, now):
        assert isinstance(now, datetime)
        sweep_calls.append(now)
        return await original_sweep(archive, now)

    with patch.object(
        main,
        'initialize_tool_service_with_retry',
        new=AsyncMock(return_value=(None, object(), ())),
    ), patch.object(
        main, 'probe_llm_proxy', new=AsyncMock(return_value=True)
    ), patch.object(
        main, '_build_agent_system', new=MagicMock()
    ), patch.object(main.ConversationArchive, 'sweep', new=observed_sweep):
        await main.startup_event()

    assert isinstance(main.archive, main.ConversationArchive)
    [row] = await main.archive.list_turns()
    assert row['status'] == 'failed', row
    assert row['error'] == 'interrupted_at_restart', row
    assert len(sweep_calls) == 1, sweep_calls
    opened_archive = main.archive
    await main.shutdown_event()
    assert opened_archive.connection is None
    print('startup recovered interrupted row, swept, and shutdown closed archive')

asyncio.run(probe())
"""

CONFIG_ERROR_PROBE = """\
import asyncio
from unittest.mock import AsyncMock, patch
import main

async def probe():
    expected = main.ArchiveConfigError(
        'bad archive setting',
        key='archive_retention_days',
        observed=-1,
        permitted=0,
    )
    with patch.object(
        main,
        'initialize_tool_service_with_retry',
        new=AsyncMock(return_value=(None, object(), ())),
    ), patch.object(
        main.ArchiveSettings, 'from_config', side_effect=expected
    ) as settings, patch.object(main.logger, 'error') as error_log:
        try:
            await main.startup_event()
        except main.ArchiveConfigError as raised:
            assert raised is expected
        else:
            raise AssertionError('archive configuration error was swallowed')

    settings.assert_called_once_with()
    assert main.checkpoint_connection is None
    assert main.checkpoint_saver is None
    error_log.assert_called_once()
    print('archive configuration error logged, raised, and checkpoint closed')

asyncio.run(probe())
"""


class ArchiveStartupTests(unittest.TestCase):
    @staticmethod
    def scratch_config(directory: str, *, enabled: bool = True) -> Path:
        config_path = Path(directory) / "config.toml"
        enabled_value = "true" if enabled else "false"
        config_path.write_text(
            Path("/bd_shared/test_config.toml")
            .read_text(encoding="utf-8")
            .replace(
                "[webreport]\n",
                f"[webreport]\narchive_enabled = {enabled_value}\n",
                1,
            ),
            encoding="utf-8",
        )
        return config_path

    def run_probe(
        self,
        source: str,
        config_path: Path,
        archive_path: str,
        *arguments: str,
    ) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            probe_path = Path(directory) / "archive_startup_probe.py"
            probe_path.write_text(source, encoding="utf-8")
            environment = {
                **os.environ,
                "BD_CONFIG_FILE": str(config_path),
                "BD_CHECKPOINT_DB_PATH": str(Path(directory) / "checkpoints.db"),
                "BD_ARCHIVE_DB_PATH": archive_path,
                "PYTHONPATH": os.pathsep.join(
                    (str(Path(__file__).parent), os.environ.get("PYTHONPATH", ""))
                ),
            }
            environment.pop("BD_CONFIG_LOCAL_FILE", None)
            return subprocess.run(
                [sys.executable, str(probe_path), *arguments],
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=30,
            )

    def test_enabled_archive_bad_path_aborts_but_disabled_uses_null_archive(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            enabled_config = self.scratch_config(directory, enabled=True)
            enabled = self.run_probe(
                STARTUP_PROBE,
                enabled_config,
                "/nonexistent-dir/a.db",
                "enabled-invalid-path",
            )
            self.assertEqual(enabled.returncode, 0, enabled.stdout)
            self.assertIn("enabled archive startup raised", enabled.stdout)

            disabled_config = self.scratch_config(directory, enabled=False)
            disabled = self.run_probe(
                STARTUP_PROBE,
                disabled_config,
                "/nonexistent-dir/a.db",
                "disabled-invalid-path",
            )
            self.assertEqual(disabled.returncode, 0, disabled.stdout)
            self.assertIn(
                "disabled archive startup succeeded with NullArchive",
                disabled.stdout,
            )

    def test_startup_recovers_old_started_row_sweeps_and_shutdown_closes(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            config_path = self.scratch_config(directory)
            result = self.run_probe(
                RECOVERY_PROBE,
                config_path,
                str(Path(directory) / "archive.db"),
            )

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn(
            "startup recovered interrupted row, swept, and shutdown closed archive",
            result.stdout,
        )

    def test_archive_config_error_is_logged_raised_and_closes_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            config_path = self.scratch_config(directory)
            result = self.run_probe(
                CONFIG_ERROR_PROBE,
                config_path,
                str(Path(directory) / "archive.db"),
            )

        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn(
            "archive configuration error logged, raised, and checkpoint closed",
            result.stdout,
        )


if __name__ == "__main__":
    unittest.main()
