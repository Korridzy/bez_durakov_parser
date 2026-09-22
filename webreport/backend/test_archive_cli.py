"""Regression tests for the conversation archive administration CLI."""

import asyncio
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import requests

import archive_cli
from archive import ArchiveSettings, ConversationArchive


SETTINGS = ArchiveSettings(
    enabled=True,
    retention_days=0,
    store_reasoning=True,
    reasoning_retention_days=30,
    sweep_interval_seconds=0,
)
COLUMNS = (
    "id",
    "request_id",
    "trace_id",
    "session_id",
    "user_id",
    "boot_id",
    "status",
    "error",
    "scope_verdict",
    "model",
    "user_message",
    "assistant_message",
    "reasoning",
    "tool_calls",
    "report",
    "created_at",
    "completed_at",
)
LIST_COLUMNS = (
    "id",
    "created_at",
    "status",
    "error",
    "session_id",
    "request_id",
    "trace_id",
)
DEFAULT_ROWS: tuple[dict[str, object], ...] = (
    {
        "id": 1,
        "request_id": "request-one",
        "trace_id": "1" * 32,
        "session_id": "session-one",
        "user_id": "u1",
        "boot_id": "boot-one",
        "status": "ok",
        "error": None,
        "scope_verdict": "in_scope",
        "model": "test-model",
        "user_message": "private user message one",
        "assistant_message": "private assistant message one",
        "reasoning": "private reasoning one",
        "tool_calls": '[{"tool":"lookup","args":{"value":1}}]',
        "report": '{"tool":"lookup","args":{"value":1},"row_count":1,"columns":["value"]}',
        "created_at": "2025-01-01T00:00:00.000000Z",
        "completed_at": "2025-01-01T00:00:01.000000Z",
    },
    {
        "id": 2,
        "request_id": "request-two",
        "trace_id": "2" * 32,
        "session_id": "session-one",
        "user_id": "u2",
        "boot_id": "boot-one",
        "status": "failed",
        "error": "timeout",
        "scope_verdict": None,
        "model": "test-model",
        "user_message": "private user message two",
        "assistant_message": "private assistant message two",
        "reasoning": "private reasoning two",
        "tool_calls": "[]",
        "report": '{"tool":null,"args":null,"row_count":0,"columns":[]}',
        "created_at": "2025-12-31T23:59:59.000000Z",
        "completed_at": "2026-01-01T00:00:00.000000Z",
    },
    {
        "id": 3,
        "request_id": "request-three",
        "trace_id": "3" * 32,
        "session_id": "session-two",
        "user_id": "u1",
        "boot_id": "boot-two",
        "status": "ok",
        "error": None,
        "scope_verdict": "in_scope",
        "model": "test-model",
        "user_message": "private user message three",
        "assistant_message": "private assistant message three",
        "reasoning": "private reasoning three",
        "tool_calls": "[]",
        "report": '{"tool":null,"args":null,"row_count":0,"columns":[]}',
        "created_at": "2026-02-01T00:00:00.000000Z",
        "completed_at": "2026-02-01T00:00:01.000000Z",
    },
)


async def _seed(path: Path, rows: list[dict[str, object]]) -> None:
    archive = ConversationArchive(path, settings=SETTINGS)
    await archive.setup()
    assert archive.connection is not None
    placeholders = ", ".join("?" for _ in COLUMNS)
    await archive.connection.executemany(
        f"INSERT INTO turns ({', '.join(COLUMNS)}) VALUES ({placeholders})",
        [tuple(row[column] for column in COLUMNS) for row in rows],
    )
    await archive.connection.commit()
    await archive.close()


async def _matching_count(path: Path, column: str, value: object) -> int:
    archive = ConversationArchive(path, settings=SETTINGS)
    await archive.setup()
    assert archive.connection is not None
    cursor = await archive.connection.execute(
        f"SELECT count(*) FROM turns WHERE {column} = ?", (value,)
    )
    row = await cursor.fetchone()
    await cursor.close()
    await archive.close()
    assert row is not None
    return int(row[0])


class ArchiveCliTests(unittest.TestCase):
    archive_path = Path()

    def setUp(self) -> None:
        temp_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temp_directory.cleanup)
        self.archive_path = Path(temp_directory.name) / "archive.db"
        asyncio.run(_seed(self.archive_path, list(DEFAULT_ROWS)))

    def run_cli(
        self, argv: list[str], *, langfuse_enabled: bool = False
    ) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch.object(archive_cli, "ARCHIVE_DB_PATH", str(self.archive_path)),
            patch.object(archive_cli, "LANGFUSE_ENABLED", langfuse_enabled),
            patch.object(archive_cli, "LANGFUSE_HOST", "https://langfuse.example.test/"),
            patch.object(archive_cli, "LANGFUSE_PUBLIC_KEY", "pk-test"),
            patch.object(archive_cli, "LANGFUSE_SECRET_KEY", "sk-test"),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            exit_code = archive_cli.main(argv)
        return exit_code, stdout.getvalue(), stderr.getvalue()

    def test_list_prints_only_operational_columns_and_one_line_per_row(self) -> None:
        exit_code, stdout, stderr = self.run_cli(
            ["list", "--session", "session-one"]
        )
        lines = stdout.rstrip("\n").splitlines()

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(lines[0].split("\t"), list(LIST_COLUMNS))
        self.assertEqual(
            lines[1].split("\t"),
            [
                "2",
                DEFAULT_ROWS[1]["created_at"],
                "failed",
                "timeout",
                "session-one",
                "request-two",
                "2" * 32,
            ],
        )
        self.assertEqual(
            lines[2].split("\t"),
            [
                "1",
                DEFAULT_ROWS[0]["created_at"],
                "ok",
                "",
                "session-one",
                "request-one",
                "1" * 32,
            ],
        )
        self.assertEqual(len(lines), 3)
        for row in DEFAULT_ROWS:
            self.assertNotIn(str(row["user_message"]), stdout)
            self.assertNotIn(str(row["assistant_message"]), stdout)
            self.assertNotIn(str(row["reasoning"]), stdout)

    def test_list_uses_the_configured_database_when_recording_is_disabled(self) -> None:
        overlay_path = self.archive_path.parent / "archive-disabled.toml"
        _ = overlay_path.write_text(
            "[webreport]\narchive_enabled = false\n", encoding="utf-8"
        )
        environment = os.environ.copy()
        _ = environment.pop("BD_CONFIG_FILE", None)
        environment["BD_CONFIG_LOCAL_FILE"] = str(overlay_path)
        environment["BD_ARCHIVE_DB_PATH"] = str(self.archive_path)

        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).with_name("archive_cli.py")),
                "list",
                "--session",
                "session-one",
            ],
            cwd=Path(__file__).parent,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=60,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stderr, "")
        self.assertIn("request-one", result.stdout)
        self.assertIn("request-two", result.stdout)
        self.assertNotIn("Conversation archive is disabled", result.stdout)

    def test_show_prints_json_with_every_archive_column(self) -> None:
        exit_code, stdout, stderr = self.run_cli(["show", "--id", "1"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(json.loads(stdout), DEFAULT_ROWS[0])
        self.assertEqual(set(json.loads(stdout)), set(COLUMNS))

    def test_delete_by_session_reports_exact_local_count(self) -> None:
        exit_code, stdout, stderr = self.run_cli(
            ["delete", "--session", "session-one"]
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout, "Deleted 2 local rows\n")
        self.assertEqual(stderr, "")
        self.assertEqual(
            asyncio.run(
                _matching_count(self.archive_path, "session_id", "session-one")
            ),
            0,
        )

    def test_delete_by_user_reports_exact_local_count(self) -> None:
        exit_code, stdout, stderr = self.run_cli(["delete", "--user", "u1"])

        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout, "Deleted 2 local rows\n")
        self.assertEqual(stderr, "")
        self.assertEqual(
            asyncio.run(_matching_count(self.archive_path, "user_id", "u1")), 0
        )

    def test_delete_by_date_reports_exact_local_count(self) -> None:
        exit_code, stdout, stderr = self.run_cli(
            ["delete", "--before", "2026-01-01"]
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout, "Deleted 2 local rows\n")
        self.assertEqual(stderr, "")
        self.assertEqual(
            asyncio.run(_matching_count(self.archive_path, "request_id", "request-three")),
            1,
        )

    def test_langfuse_deletion_uses_basic_auth_and_batches_of_at_most_thirty(
        self,
    ) -> None:
        rows = []
        for index in range(65):
            row = dict(DEFAULT_ROWS[0])
            row.update(
                id=100 + index,
                request_id=f"batch-request-{index}",
                trace_id=f"{100 + index:032x}",
                session_id="batch-session",
            )
            rows.append(row)
        asyncio.run(_seed(self.archive_path, rows))
        response = Mock(status_code=202)

        with patch.object(archive_cli.requests, "delete", return_value=response) as delete:
            exit_code, stdout, stderr = self.run_cli(
                ["delete", "--session", "batch-session"], langfuse_enabled=True
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertIn("Deleted 65 local rows", stdout)
        self.assertIn(
            "Submitted 65 traces for deletion in Langfuse (asynchronous)", stdout
        )
        self.assertEqual(delete.call_count, 3)
        submitted_trace_ids = []
        for request_call in delete.call_args_list:
            self.assertEqual(
                request_call.args, ("https://langfuse.example.test/api/public/traces",)
            )
            self.assertEqual(request_call.kwargs["auth"], ("pk-test", "sk-test"))
            self.assertEqual(request_call.kwargs["timeout"], 60)
            batch = request_call.kwargs["json"]["traceIds"]
            self.assertLessEqual(len(batch), 30)
            submitted_trace_ids.extend(batch)
        self.assertCountEqual(
            submitted_trace_ids, [str(row["trace_id"]) for row in rows]
        )

    def test_langfuse_request_exception_reports_local_success_and_remote_failure(
        self,
    ) -> None:
        with patch.object(
            archive_cli.requests,
            "delete",
            side_effect=requests.ConnectionError("offline"),
        ):
            exit_code, stdout, stderr = self.run_cli(
                ["delete", "--session", "session-one"], langfuse_enabled=True
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(stderr, "")
        self.assertIn("Deleted 2 local rows", stdout)
        self.assertIn("Langfuse deletion failed", stdout)
        self.assertEqual(
            asyncio.run(
                _matching_count(self.archive_path, "session_id", "session-one")
            ),
            0,
        )

    def test_langfuse_http_500_reports_local_success_and_remote_failure(self) -> None:
        with patch.object(
            archive_cli.requests, "delete", return_value=Mock(status_code=500)
        ):
            exit_code, stdout, stderr = self.run_cli(
                ["delete", "--session", "session-one"], langfuse_enabled=True
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(stderr, "")
        self.assertIn("Deleted 2 local rows", stdout)
        self.assertIn("Langfuse deletion failed", stdout)
        self.assertEqual(
            asyncio.run(
                _matching_count(self.archive_path, "session_id", "session-one")
            ),
            0,
        )

    def test_delete_without_selector_is_an_argparse_usage_error(self) -> None:
        stderr = io.StringIO()
        with redirect_stderr(stderr), self.assertRaises(SystemExit) as raised:
            archive_cli.main(["delete"])

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("usage:", stderr.getvalue())

    def test_local_storage_error_exits_one_without_a_success_line(self) -> None:
        with patch.object(
            archive_cli.ConversationArchive,
            "delete_session",
            new=AsyncMock(side_effect=OSError("storage unavailable")),
        ):
            exit_code, stdout, stderr = self.run_cli(
                ["delete", "--session", "session-one"]
            )

        self.assertEqual(exit_code, 1)
        self.assertNotIn("Deleted", stdout)
        self.assertIn("storage unavailable", stderr)


if __name__ == "__main__":
    unittest.main()
