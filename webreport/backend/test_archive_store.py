import asyncio
from datetime import datetime, timedelta, timezone
import io
import json
from pathlib import Path
import re
import tempfile
import threading
import unittest
from unittest.mock import AsyncMock, patch

import aiosqlite

from bd_shared import logging_setup

from agents.report_support import failure, success
from archive import (
    ArchiveConfigError,
    ArchiveSettings,
    ConversationArchive,
    NullArchive,
    SweepResult,
)


UTC = timezone.utc
BASE_NOW = datetime(2026, 1, 31, 12, 0, tzinfo=UTC)


def settings(
    *,
    retention_days: int = 0,
    store_reasoning: bool = True,
    reasoning_retention_days: int = 30,
    sweep_interval_seconds: int = 0,
) -> ArchiveSettings:
    return ArchiveSettings.validate(
        enabled=True,
        retention_days=retention_days,
        store_reasoning=store_reasoning,
        reasoning_retention_days=reasoning_retention_days,
        sweep_interval_seconds=sweep_interval_seconds,
    )


class ConversationArchiveTests(unittest.IsolatedAsyncioTestCase):
    temp_dir: tempfile.TemporaryDirectory[str]
    path: Path
    archives: list[ConversationArchive]

    async def asyncSetUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "archive.db"
        self.archives: list[ConversationArchive] = []

    async def asyncTearDown(self) -> None:
        for archive in reversed(self.archives):
            await archive.close()
        logging_setup._reset_for_tests()
        self.temp_dir.cleanup()

    async def open_archive(
        self,
        archive_settings: ArchiveSettings | None = None,
        *,
        now=lambda: BASE_NOW,
        clock=lambda: 0.0,
        boot_id: str = "boot-a",
    ) -> ConversationArchive:
        archive = ConversationArchive(
            self.path,
            settings=archive_settings or settings(),
            now=now,
            clock=clock,
        )
        await archive.setup()
        await archive.recover_interrupted(boot_id)
        self.archives.append(archive)
        return archive

    async def rows(
        self,
        archive: ConversationArchive,
        sql: str,
        parameters: tuple[object, ...] = (),
    ) -> list[tuple[object, ...]]:
        assert archive.connection is not None
        cursor = await archive.connection.execute(sql, parameters)
        try:
            return [tuple(row) for row in await cursor.fetchall()]
        finally:
            await cursor.close()

    async def begin(
        self,
        archive: ConversationArchive,
        *,
        request_id: str = "request-1",
        trace_id: str = "0123456789abcdef0123456789abcdef",
        session_id: str = "session-1",
        user_id: str | None = "user-1",
    ) -> int:
        row_id = await archive.begin(
            request_id=request_id,
            trace_id=trace_id,
            session_id=session_id,
            user_id=user_id,
            model="fixture-model",
            user_message="question",
        )
        self.assertIs(type(row_id), int)
        return row_id

    async def test_concurrent_setup_on_new_path_creates_persistent_schema(self):
        first = ConversationArchive(self.path, settings=settings())
        second = ConversationArchive(self.path, settings=settings())
        self.archives.extend((first, second))
        original_execute = aiosqlite.Connection._execute
        wal_barrier = threading.Barrier(2)
        wal_arrivals = 0

        async def synchronized_execute(connection, function, *args, **kwargs):
            nonlocal wal_arrivals
            if args and args[0] == "PRAGMA journal_mode=WAL" and wal_arrivals < 2:
                wal_arrivals += 1
                sqlite_execute = function

                def execute_at_barrier(*call_args, **call_kwargs):
                    wal_barrier.wait(timeout=1)
                    return sqlite_execute(*call_args, **call_kwargs)

                function = execute_at_barrier
            return await original_execute(connection, function, *args, **kwargs)

        with patch.object(aiosqlite.Connection, "_execute", new=synchronized_execute):
            tasks = (
                asyncio.create_task(first.setup()),
                asyncio.create_task(second.setup()),
            )
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True), timeout=2
            )

        self.assertEqual(wal_arrivals, 2)
        self.assertEqual(results, [None, None])
        self.assertEqual(await self.rows(first, "PRAGMA auto_vacuum"), [(2,)])
        self.assertEqual(await self.rows(second, "PRAGMA auto_vacuum"), [(2,)])
        await first.close()
        await second.close()
        self.archives.clear()

        reopened = ConversationArchive(self.path, settings=settings())
        self.archives.append(reopened)
        await reopened.setup()
        self.assertEqual(await self.rows(reopened, "PRAGMA auto_vacuum"), [(2,)])
        self.assertEqual(await self.rows(reopened, "PRAGMA user_version"), [(1,)])
        indexes = await self.rows(reopened, "PRAGMA index_list(turns)")
        self.assertEqual(
            {row[1] for row in indexes},
            {
                "turns_request_id",
                "turns_session_id",
                "turns_user_id",
                "turns_created_at",
                "turns_started",
            },
        )

    async def test_setup_creates_version_one_schema_five_indexes_and_private_file(self):
        archive = await self.open_archive()

        version = await self.rows(archive, "PRAGMA user_version")
        indexes = await self.rows(archive, "PRAGMA index_list(turns)")

        self.assertEqual(version, [(1,)])
        self.assertEqual(await self.rows(archive, "PRAGMA auto_vacuum"), [(2,)])
        self.assertEqual(
            {row[1] for row in indexes},
            {
                "turns_request_id",
                "turns_session_id",
                "turns_user_id",
                "turns_created_at",
                "turns_started",
            },
        )
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    async def test_begin_returns_integer_and_writes_started_row_and_fixed_utc_time(
        self,
    ):
        archive = await self.open_archive()

        row_id = await self.begin(archive)
        row = (
            await self.rows(
                archive,
                "SELECT id, status, boot_id, created_at FROM turns WHERE id = ?",
                (row_id,),
            )
        )[0]

        self.assertEqual(row[:3], (row_id, "started", "boot-a"))
        self.assertEqual(row[3], "2026-01-31T12:00:00.000000Z")
        self.assertRegex(
            row[3], re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z$")
        )

    async def test_complete_success_stores_summary_but_never_report_rows(self):
        archive = await self.open_archive()
        row_id = await self.begin(archive)
        response = success(
            "answer",
            [
                {"tool": "first", "args": {"ignored": True}},
                {"tool": "last", "args": {"region": "north"}},
            ],
            [{"z": "ROW_SENTINEL", "a": 1}, {"z": "other", "a": 2}],
            reasoning="private chain",
            verdict="in_scope",
        )

        await archive.complete(row_id, response)
        row = (
            await self.rows(
                archive,
                """SELECT status, error, scope_verdict, assistant_message, reasoning,
                      tool_calls, report, completed_at
               FROM turns WHERE id = ?""",
                (row_id,),
            )
        )[0]
        report = json.loads(row[6])

        self.assertEqual(row[:5], ("ok", None, "in_scope", "answer", "private chain"))
        self.assertEqual(json.loads(row[5]), response["query_info"])
        self.assertEqual(
            report,
            {
                "tool": "last",
                "args": {"region": "north"},
                "row_count": 2,
                "columns": ["a", "z"],
            },
        )
        self.assertNotIn("ROW_SENTINEL", row[6])
        self.assertEqual(row[7], "2026-01-31T12:00:00.000000Z")

    async def test_complete_failure_sets_failed_error_and_empty_report_shape(self):
        archive = await self.open_archive()
        row_id = await self.begin(archive)

        await archive.complete(
            row_id,
            failure("could not answer", "timeout", reasoning="partial"),
        )
        row = (
            await self.rows(
                archive,
                "SELECT status, error, assistant_message, tool_calls, report FROM turns WHERE id = ?",
                (row_id,),
            )
        )[0]

        self.assertEqual(row[:3], ("failed", "timeout", "could not answer"))
        self.assertEqual(json.loads(row[3]), [])
        self.assertEqual(
            json.loads(row[4]),
            {"tool": None, "args": None, "row_count": 0, "columns": []},
        )

    async def test_complete_omits_reasoning_when_disabled_and_none_is_no_op(self):
        archive = await self.open_archive(settings(store_reasoning=False))
        completed_id = await self.begin(archive, request_id="complete")
        started_id = await self.begin(archive, request_id="no-op")

        await archive.complete(
            completed_id,
            success("answer", [], {"scalar": "value"}, reasoning="must not persist"),
        )
        await archive.complete(started_id, None)
        rows = await self.rows(
            archive,
            "SELECT request_id, status, reasoning, completed_at, report FROM turns ORDER BY id",
        )

        self.assertEqual(rows[0][1:4], ("ok", None, "2026-01-31T12:00:00.000000Z"))
        self.assertEqual(json.loads(rows[0][4])["row_count"], 1)
        self.assertEqual(rows[1][1:], ("started", None, None, None))

    async def test_restart_sees_rows_and_recovers_only_another_boot_started_rows(self):
        old_archive = await self.open_archive(boot_id="old-boot")
        old_started = await self.begin(old_archive, request_id="old-started")
        old_complete = await self.begin(old_archive, request_id="old-complete")
        await old_archive.complete(
            old_complete,
            success("done", [], None, reasoning=None),
        )
        await old_archive.close()
        self.archives.remove(old_archive)

        restarted = await self.open_archive(boot_id="new-boot")
        new_started = await self.begin(restarted, request_id="new-started")
        await restarted.recover_interrupted("new-boot")
        rows = await self.rows(
            restarted,
            "SELECT id, status, error, completed_at FROM turns ORDER BY id",
        )

        self.assertEqual(rows[0][0], old_started)
        self.assertEqual(rows[0][1:3], ("failed", "interrupted_at_restart"))
        self.assertIsNotNone(rows[0][3])
        self.assertEqual(rows[1][0:3], (old_complete, "ok", None))
        self.assertEqual(rows[2], (new_started, "started", None, None))

    async def test_delete_methods_return_counts_and_leave_unselected_rows(self):
        current = BASE_NOW - timedelta(days=2)
        archive = await self.open_archive(now=lambda: current)
        await self.begin(archive, request_id="one", session_id="s1", user_id="u1")
        await self.begin(archive, request_id="two", session_id="s1", user_id="u2")
        await self.begin(archive, request_id="three", session_id="s2", user_id="u1")
        await self.begin(archive, request_id="four", session_id="s3", user_id="u3")
        current = BASE_NOW
        kept_id = await self.begin(
            archive, request_id="five", session_id="s4", user_id="u4"
        )

        self.assertEqual(await archive.delete_session("s1"), 2)
        self.assertEqual(await archive.delete_user("u1"), 1)
        self.assertEqual(await archive.delete_before(BASE_NOW - timedelta(days=1)), 1)
        remaining = await self.rows(archive, "SELECT id, request_id FROM turns")

        self.assertEqual(remaining, [(kept_id, "five")])

    async def test_sweep_zero_row_retention_only_clears_old_reasoning_strictly_before_boundary(
        self,
    ):
        current = BASE_NOW - timedelta(days=31)
        archive = await self.open_archive(
            settings(retention_days=0, reasoning_retention_days=30),
            now=lambda: current,
        )
        old_id = await self.begin(archive, request_id="old")
        await archive.complete(
            old_id, success("old", [], [], reasoning="old reasoning")
        )
        current = BASE_NOW - timedelta(days=30)
        boundary_id = await self.begin(archive, request_id="boundary")
        await archive.complete(
            boundary_id,
            success("boundary", [], [], reasoning="boundary reasoning"),
        )

        result = await archive.sweep(BASE_NOW)
        rows = await self.rows(archive, "SELECT id, reasoning FROM turns ORDER BY id")

        self.assertEqual(result, SweepResult(rows_deleted=0, reasoning_cleared=1))
        self.assertEqual(rows, [(old_id, None), (boundary_id, "boundary reasoning")])

    async def test_sweep_deletes_only_old_completed_rows_and_keeps_boundary_and_started(
        self,
    ):
        current = BASE_NOW - timedelta(days=2)
        archive = await self.open_archive(
            settings(retention_days=1, reasoning_retention_days=0),
            now=lambda: current,
        )
        old_completed = await self.begin(archive, request_id="old-completed")
        await archive.complete(old_completed, success("done", [], None, reasoning=None))
        old_started = await self.begin(archive, request_id="old-started")
        current = BASE_NOW - timedelta(days=1)
        boundary = await self.begin(archive, request_id="boundary")
        await archive.complete(boundary, failure("failed", "fixture"))

        result = await archive.sweep(BASE_NOW)
        rows = await self.rows(archive, "SELECT id, status FROM turns ORDER BY id")

        self.assertEqual(result.rows_deleted, 1)
        self.assertEqual(rows, [(old_started, "started"), (boundary, "failed")])

    async def test_sweep_removes_more_than_one_batch(self):
        archive = await self.open_archive(
            settings(retention_days=1, reasoning_retention_days=0)
        )
        assert archive.connection is not None
        old_stamp = "2026-01-01T00:00:00.000000Z"
        await archive.connection.execute(
            """WITH RECURSIVE numbers(n) AS (
                   SELECT 1 UNION ALL SELECT n + 1 FROM numbers WHERE n < 501
               )
               INSERT INTO turns (
                   request_id, trace_id, session_id, user_id, boot_id, status,
                   model, created_at
               )
               SELECT printf('request-%d', n),
                      '0123456789abcdef0123456789abcdef',
                      'batch', NULL, 'boot-a', 'ok', 'model', ?
               FROM numbers""",
            (old_stamp,),
        )
        await archive.connection.commit()

        result = await archive.sweep(BASE_NOW)
        remaining = await self.rows(archive, "SELECT count(*) FROM turns")

        self.assertEqual(result.rows_deleted, 501)
        self.assertEqual(remaining, [(0,)])

    async def test_maybe_sweep_is_single_flight_and_respects_interval(self):
        monotonic = 10.0
        archive = await self.open_archive(
            settings(sweep_interval_seconds=10), clock=lambda: monotonic
        )
        calls: list[datetime] = []
        entered = asyncio.Event()
        release = asyncio.Event()

        async def observed_sweep(now: datetime) -> SweepResult:
            calls.append(now)
            entered.set()
            await release.wait()
            return SweepResult()

        with patch.object(archive, "sweep", side_effect=observed_sweep):
            await archive.maybe_sweep()
            await asyncio.wait_for(entered.wait(), timeout=1)
            await archive.maybe_sweep()
            self.assertEqual(len(calls), 1)
            release.set()
            assert archive._sweep_task is not None
            await asyncio.wait_for(archive._sweep_task, timeout=1)

            await archive.maybe_sweep()
            self.assertEqual(len(calls), 1)
            monotonic = 19.99
            await archive.maybe_sweep()
            self.assertEqual(len(calls), 1)
            monotonic = 20.0
            entered.clear()
            await archive.maybe_sweep()
            await asyncio.wait_for(entered.wait(), timeout=1)
            self.assertEqual(len(calls), 2)

    async def test_zero_sweep_interval_never_schedules_but_explicit_sweep_works(self):
        archive = await self.open_archive(settings(sweep_interval_seconds=0))

        with patch.object(archive, "sweep", wraps=archive.sweep) as sweep:
            await archive.maybe_sweep()
            sweep.assert_not_awaited()
            self.assertIsNone(archive._sweep_task)
            self.assertEqual(await archive.sweep(BASE_NOW), SweepResult())
            sweep.assert_awaited_once_with(BASE_NOW)

    async def test_fail_open_operations_log_structured_ids_without_message(self):
        stream = io.StringIO()
        logging_setup.configure_logging(
            "test-archive-store", log_format="json", stream=stream
        )
        archive = await self.open_archive()
        assert archive.connection is not None

        with patch.object(
            archive.connection,
            "execute",
            new=AsyncMock(side_effect=RuntimeError("write sentinel")),
        ):
            row_id = await archive.begin(
                request_id="request-log",
                trace_id="0123456789abcdef0123456789abcdef",
                session_id="session-log",
                user_id=None,
                model="model",
                user_message="MESSAGE_SENTINEL",
            )
            await archive.complete(42, failure("MESSAGE_SENTINEL", "failure"))
            result = await archive.sweep(BASE_NOW)

        records = [json.loads(line) for line in stream.getvalue().splitlines()]
        begin_record = next(
            record
            for record in records
            if record.get("event") == "archive_write_failed"
            and record.get("operation") == "begin"
        )
        self.assertIsNone(row_id)
        self.assertEqual(result, SweepResult())
        self.assertEqual(begin_record["request_id"], "request-log")
        self.assertEqual(begin_record["session_id"], "session-log")
        self.assertIn("exception", begin_record)
        self.assertNotIn("message", begin_record)
        self.assertNotIn("MESSAGE_SENTINEL", json.dumps(records))

    async def test_closed_connection_writes_fail_open_but_delete_raises(self):
        archive = await self.open_archive()
        row_id = await self.begin(archive)
        assert archive.connection is not None
        await archive.connection.close()

        self.assertIsNone(
            await archive.begin(
                request_id="closed",
                trace_id="0123456789abcdef0123456789abcdef",
                session_id="closed",
                user_id=None,
                model="model",
                user_message="question",
            )
        )
        await archive.complete(row_id, failure("failed", "closed"))
        self.assertEqual(await archive.sweep(BASE_NOW), SweepResult())
        with self.assertRaises(ValueError):
            await archive.delete_session("closed")

    async def test_list_and_get_support_cli_filters_without_mutating_rows(self):
        archive = await self.open_archive()
        first = await self.begin(
            archive, request_id="first", session_id="session-a", user_id="user-a"
        )
        await self.begin(
            archive, request_id="second", session_id="session-b", user_id="user-a"
        )
        await self.begin(
            archive, request_id="third", session_id="session-a", user_id="user-b"
        )

        by_session = await archive.list_turns(session_id="session-a", limit=1)
        by_user = await archive.list_turns(user_id="user-a")
        row = await archive.get_turn(first)

        self.assertEqual(len(by_session), 1)
        self.assertEqual(by_session[0]["request_id"], "third")
        self.assertEqual([item["request_id"] for item in by_user], ["second", "first"])
        assert row is not None
        self.assertEqual(row["id"], first)
        self.assertIsNone(await archive.get_turn(999_999))


class ArchiveSettingsTests(unittest.TestCase):
    def test_validate_rejects_non_integer_and_negative_integer_settings(self):
        defaults = {
            "enabled": True,
            "retention_days": 0,
            "store_reasoning": True,
            "reasoning_retention_days": 30,
            "sweep_interval_seconds": 600,
        }
        for argument, key in (
            ("retention_days", "archive_retention_days"),
            ("reasoning_retention_days", "archive_reasoning_retention_days"),
            ("sweep_interval_seconds", "archive_sweep_interval_seconds"),
        ):
            for value in (True, "1", -1):
                with self.subTest(argument=argument, value=value):
                    values = defaults | {argument: value}
                    with self.assertRaises(ArchiveConfigError) as raised:
                        ArchiveSettings.validate(**values)
                    self.assertEqual(raised.exception.key, key)
                    self.assertIn(key, str(raised.exception))

    def test_validate_rejects_non_boolean_settings(self):
        defaults = {
            "enabled": True,
            "retention_days": 0,
            "store_reasoning": True,
            "reasoning_retention_days": 30,
            "sweep_interval_seconds": 600,
        }
        for argument, key in (
            ("enabled", "archive_enabled"),
            ("store_reasoning", "archive_store_reasoning"),
        ):
            for value in (1, "true", None):
                with self.subTest(argument=argument, value=value):
                    values = defaults | {argument: value}
                    with self.assertRaises(ArchiveConfigError) as raised:
                        ArchiveSettings.validate(**values)
                    self.assertEqual(raised.exception.key, key)
                    self.assertIn(key, str(raised.exception))


class NullArchiveTests(unittest.IsolatedAsyncioTestCase):
    async def test_all_methods_are_safe_no_ops(self):
        archive = NullArchive()
        response = success("answer", [], None, reasoning=None)

        self.assertIsNone(await archive.setup())
        self.assertIsNone(await archive.recover_interrupted("boot"))
        self.assertIsNone(
            await archive.begin(
                request_id="request",
                trace_id="0123456789abcdef0123456789abcdef",
                session_id="session",
                user_id=None,
                model="model",
                user_message="question",
            )
        )
        self.assertIsNone(await archive.complete(None, response))
        self.assertEqual(await archive.delete_session("session"), 0)
        self.assertEqual(await archive.delete_user("user"), 0)
        self.assertEqual(await archive.delete_before(BASE_NOW), 0)
        self.assertEqual(await archive.sweep(BASE_NOW), SweepResult())
        self.assertIsNone(await archive.maybe_sweep())
        self.assertEqual(await archive.list_turns(), [])
        self.assertIsNone(await archive.get_turn(1))
        self.assertIsNone(await archive.close())


if __name__ == "__main__":
    unittest.main(verbosity=2)
