"""Durable conversation archive independent of checkpoints and fail-open on writes."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import time
from typing import cast
from uuid import uuid4

import aiosqlite
import structlog

from agents.report_contracts import ReportResponse


logger = structlog.get_logger(__name__)
_TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
_DELETE_BATCH_SIZE = 500


class ArchiveConfigError(RuntimeError):
    """Raised when a conversation archive setting has an unusable value."""

    def __init__(self, message: str, *, key: str, observed: object, permitted: object) -> None:
        super().__init__(message)
        self.key = key
        self.observed = observed
        self.permitted = permitted


@dataclass(frozen=True)
class ArchiveSettings:
    enabled: bool
    retention_days: int
    store_reasoning: bool
    reasoning_retention_days: int
    sweep_interval_seconds: int

    @classmethod
    def validate(
        cls,
        *,
        enabled: object,
        retention_days: object,
        store_reasoning: object,
        reasoning_retention_days: object,
        sweep_interval_seconds: object,
    ) -> "ArchiveSettings":
        bool_values = (
            ("archive_enabled", enabled),
            ("archive_store_reasoning", store_reasoning),
        )
        for key, value in bool_values:
            if type(value) is not bool:
                raise ArchiveConfigError(
                    f"Invalid archive setting {key}: observed {value!r} "
                    f"({type(value).__name__}); must be a boolean",
                    key=key,
                    observed=value,
                    permitted="boolean",
                )

        integer_values = (
            ("archive_retention_days", retention_days),
            ("archive_reasoning_retention_days", reasoning_retention_days),
            ("archive_sweep_interval_seconds", sweep_interval_seconds),
        )
        for key, value in integer_values:
            if not (type(value) is int and value >= 0):
                raise ArchiveConfigError(
                    f"Invalid archive setting {key}: observed {value!r} "
                    f"({type(value).__name__}); must be a non-negative integer",
                    key=key,
                    observed=value,
                    permitted=0,
                )

        return cls(
            enabled=cast(bool, enabled),
            retention_days=cast(int, retention_days),
            store_reasoning=cast(bool, store_reasoning),
            reasoning_retention_days=cast(int, reasoning_retention_days),
            sweep_interval_seconds=cast(int, sweep_interval_seconds),
        )

    @classmethod
    def from_config(cls) -> "ArchiveSettings":
        from bd_shared import config

        return cls.validate(
            enabled=config.ARCHIVE_ENABLED,
            retention_days=config.ARCHIVE_RETENTION_DAYS,
            store_reasoning=config.ARCHIVE_STORE_REASONING,
            reasoning_retention_days=config.ARCHIVE_REASONING_RETENTION_DAYS,
            sweep_interval_seconds=config.ARCHIVE_SWEEP_INTERVAL_SECONDS,
        )


@dataclass(frozen=True)
class SweepResult:
    rows_deleted: int = 0
    reasoning_cleared: int = 0


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime(_TIMESTAMP_FORMAT)


def _report_summary(response: ReportResponse) -> dict[str, object]:
    query_info = response["query_info"]
    last_query = query_info[-1] if query_info else None
    data = response["data"]
    columns: list[str] = []
    if isinstance(data, list) and data and all(isinstance(row, dict) for row in data):
        columns = sorted(data[0].keys())
    return {
        "tool": last_query["tool"] if last_query is not None else None,
        "args": dict(last_query["args"]) if last_query is not None else None,
        "row_count": len(data) if isinstance(data, list) else int(data is not None),
        "columns": columns,
    }


class ConversationArchive:
    """Own an async SQLite archive connection and fail open on request writes."""

    def __init__(
        self,
        path: str | Path,
        *,
        settings: ArchiveSettings,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.path = Path(path)
        self.settings = settings
        self._clock = clock
        self._now = now
        self._boot_id = uuid4().hex
        self._last_sweep_at: float | None = None
        self._sweep_task: asyncio.Task[SweepResult] | None = None
        self.connection: aiosqlite.Connection | None = None

    async def setup(self) -> None:
        """Open the archive and create its version-one schema."""
        if self.connection is not None:
            return
        connection = await aiosqlite.connect(self.path)
        self.connection = connection
        try:
            connection.row_factory = aiosqlite.Row
            # These connection-local/file-header settings must precede WAL negotiation:
            # WAL mode changes bypass the busy handler and also freeze auto-vacuum layout.
            await connection.execute("PRAGMA busy_timeout=5000")
            await connection.execute("PRAGMA auto_vacuum=INCREMENTAL")
            for attempt in range(5):
                try:
                    await connection.execute("PRAGMA journal_mode=WAL")
                    break
                except aiosqlite.OperationalError as error:
                    transient = str(error) in {"database is locked", "disk I/O error"}
                    if not transient or attempt == 4:
                        raise
                    await asyncio.sleep(0.01 * (2**attempt))
            await connection.execute("PRAGMA synchronous=NORMAL")
            await connection.execute("PRAGMA busy_timeout=5000")
            await connection.execute("PRAGMA auto_vacuum=INCREMENTAL")
            await connection.execute(
                """CREATE TABLE IF NOT EXISTS turns (
                    id INTEGER PRIMARY KEY,
                    request_id TEXT NOT NULL,
                    trace_id TEXT NOT NULL CHECK (
                        length(trace_id) = 32
                        AND trace_id NOT GLOB '*[^0-9a-f]*'
                    ),
                    session_id TEXT NOT NULL,
                    user_id TEXT NULL,
                    boot_id TEXT NOT NULL,
                    status TEXT NOT NULL CHECK (status IN ('started', 'ok', 'failed')),
                    error TEXT NULL,
                    scope_verdict TEXT NULL,
                    model TEXT NOT NULL,
                    user_message TEXT NULL,
                    assistant_message TEXT NULL,
                    reasoning TEXT NULL,
                    tool_calls TEXT NULL CHECK (
                        tool_calls IS NULL OR json_valid(tool_calls)
                    ),
                    report TEXT NULL CHECK (report IS NULL OR json_valid(report)),
                    created_at TEXT NOT NULL,
                    completed_at TEXT NULL
                )"""
            )
            await connection.execute(
                "CREATE INDEX IF NOT EXISTS turns_request_id ON turns(request_id)"
            )
            await connection.execute(
                """CREATE INDEX IF NOT EXISTS turns_session_id
                   ON turns(session_id, created_at)"""
            )
            await connection.execute(
                """CREATE INDEX IF NOT EXISTS turns_user_id
                   ON turns(user_id, created_at) WHERE user_id IS NOT NULL"""
            )
            await connection.execute(
                "CREATE INDEX IF NOT EXISTS turns_created_at ON turns(created_at)"
            )
            await connection.execute(
                """CREATE INDEX IF NOT EXISTS turns_started
                   ON turns(boot_id) WHERE status = 'started'"""
            )
            await connection.execute("PRAGMA user_version=1")
            await connection.commit()
            self._chmod_store_files()
        except Exception:
            await connection.close()
            self.connection = None
            raise

    async def recover_interrupted(self, boot_id: str) -> None:
        """Fail unfinished rows from earlier boots and select the current boot id."""
        self._boot_id = boot_id
        try:
            connection = self._require_connection()
            await connection.execute(
                """UPDATE turns
                   SET status = 'failed', error = 'interrupted_at_restart',
                       completed_at = ?
                   WHERE status = 'started' AND boot_id != ?""",
                (_timestamp(self._now()), boot_id),
            )
            await connection.commit()
        except Exception:
            logger.error(
                "archive_recover_failed",
                operation="recover_interrupted",
                boot_id=boot_id,
                exc_info=True,
            )

    async def begin(
        self,
        *,
        request_id: str,
        trace_id: str,
        session_id: str,
        user_id: str | None,
        model: str,
        user_message: str | None,
    ) -> int | None:
        """Start a turn, returning no id when the archive is unavailable."""
        await self.maybe_sweep()
        try:
            connection = self._require_connection()
            cursor = await connection.execute(
                """INSERT INTO turns (
                       request_id, trace_id, session_id, user_id, boot_id, status,
                       model, user_message, created_at
                   ) VALUES (?, ?, ?, ?, ?, 'started', ?, ?, ?)""",
                (
                    request_id,
                    trace_id,
                    session_id,
                    user_id,
                    self._boot_id,
                    model,
                    user_message,
                    _timestamp(self._now()),
                ),
            )
            await connection.commit()
            row_id = cursor.lastrowid
            await cursor.close()
            return int(row_id) if row_id is not None else None
        except Exception:
            logger.error(
                "archive_write_failed",
                operation="begin",
                request_id=request_id,
                session_id=session_id,
                exc_info=True,
            )
            return None

    async def complete(
        self, row_id: int | None, response: ReportResponse | None
    ) -> None:
        """Complete a started row without allowing archive failures to affect chat."""
        if row_id is None or response is None:
            return
        try:
            connection = self._require_connection()
            reasoning = response["reasoning"] if self.settings.store_reasoning else None
            await connection.execute(
                """UPDATE turns
                   SET status = ?, error = ?, scope_verdict = ?,
                       assistant_message = ?, reasoning = ?, tool_calls = ?,
                       report = ?, completed_at = ?
                   WHERE id = ?""",
                (
                    "ok" if response["success"] else "failed",
                    response.get("error"),
                    response["verdict"],
                    response["message"],
                    reasoning,
                    json.dumps(
                        response["query_info"],
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    json.dumps(
                        _report_summary(response),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    _timestamp(self._now()),
                    row_id,
                ),
            )
            await connection.commit()
        except Exception:
            logger.error(
                "archive_write_failed",
                operation="complete",
                row_id=row_id,
                exc_info=True,
            )

    async def delete_session(self, session_id: str) -> int:
        connection = self._require_connection()
        cursor = await connection.execute(
            "DELETE FROM turns WHERE session_id = ?", (session_id,)
        )
        await connection.commit()
        count = cursor.rowcount
        await cursor.close()
        return count

    async def delete_user(self, user_id: str) -> int:
        connection = self._require_connection()
        cursor = await connection.execute(
            "DELETE FROM turns WHERE user_id = ?", (user_id,)
        )
        await connection.commit()
        count = cursor.rowcount
        await cursor.close()
        return count

    async def delete_before(self, cutoff: datetime) -> int:
        connection = self._require_connection()
        cursor = await connection.execute(
            "DELETE FROM turns WHERE created_at < ?", (_timestamp(cutoff),)
        )
        await connection.commit()
        count = cursor.rowcount
        await cursor.close()
        return count

    async def sweep(self, now: datetime) -> SweepResult:
        """Apply row and reasoning retention, deleting rows in bounded batches."""
        deleted = 0
        reasoning_cleared = 0
        try:
            connection = self._require_connection()
            if self.settings.retention_days > 0:
                cutoff = _timestamp(now - timedelta(days=self.settings.retention_days))
                while True:
                    cursor = await connection.execute(
                        """DELETE FROM turns WHERE id IN (
                               SELECT id FROM turns
                               WHERE status != 'started' AND created_at < ?
                               LIMIT 500
                           )""",
                        (cutoff,),
                    )
                    batch_count = cursor.rowcount
                    await cursor.close()
                    deleted += batch_count
                    if batch_count < _DELETE_BATCH_SIZE:
                        break
            if self.settings.reasoning_retention_days > 0:
                reasoning_cutoff = _timestamp(
                    now - timedelta(days=self.settings.reasoning_retention_days)
                )
                cursor = await connection.execute(
                    """UPDATE turns SET reasoning = NULL
                       WHERE reasoning IS NOT NULL AND created_at < ?""",
                    (reasoning_cutoff,),
                )
                reasoning_cleared = cursor.rowcount
                await cursor.close()
            await connection.commit()
            await connection.execute("PRAGMA incremental_vacuum")
            return SweepResult(deleted, reasoning_cleared)
        except Exception:
            logger.error(
                "archive_sweep_failed",
                operation="sweep",
                exc_info=True,
            )
            return SweepResult()

    async def maybe_sweep(self) -> None:
        """Schedule at most one opportunistic sweep per configured interval."""
        if self.settings.sweep_interval_seconds == 0:
            return
        if self._sweep_task is not None and not self._sweep_task.done():
            return
        try:
            current = self._clock()
            if (
                self._last_sweep_at is not None
                and current - self._last_sweep_at < self.settings.sweep_interval_seconds
            ):
                return
            self._last_sweep_at = current
            self._sweep_task = asyncio.create_task(self.sweep(self._now()))
        except Exception:
            logger.error(
                "archive_sweep_failed",
                operation="maybe_sweep",
                exc_info=True,
            )

    async def list_turns(
        self,
        session_id: str | None = None,
        user_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, object]]:
        connection = self._require_connection()
        if session_id is not None and user_id is not None:
            query = """SELECT * FROM turns
                       WHERE session_id = ? AND user_id = ?
                       ORDER BY id DESC LIMIT ?"""
            parameters: tuple[object, ...] = (session_id, user_id, limit)
        elif session_id is not None:
            query = """SELECT * FROM turns WHERE session_id = ?
                       ORDER BY id DESC LIMIT ?"""
            parameters = (session_id, limit)
        elif user_id is not None:
            query = """SELECT * FROM turns WHERE user_id = ?
                       ORDER BY id DESC LIMIT ?"""
            parameters = (user_id, limit)
        else:
            query = "SELECT * FROM turns ORDER BY id DESC LIMIT ?"
            parameters = (limit,)
        cursor = await connection.execute(query, parameters)
        try:
            return [dict(row) for row in await cursor.fetchall()]
        finally:
            await cursor.close()

    async def get_turn(self, row_id: int) -> dict[str, object] | None:
        connection = self._require_connection()
        cursor = await connection.execute("SELECT * FROM turns WHERE id = ?", (row_id,))
        try:
            row = await cursor.fetchone()
            return dict(row) if row is not None else None
        finally:
            await cursor.close()

    async def close(self) -> None:
        if self._sweep_task is not None:
            await self._sweep_task
            self._sweep_task = None
        if self.connection is not None:
            await self.connection.close()
            self.connection = None

    def _require_connection(self) -> aiosqlite.Connection:
        if self.connection is None:
            raise RuntimeError("Conversation archive is not open")
        return self.connection

    def _chmod_store_files(self) -> None:
        for path in (self.path, Path(f"{self.path}-wal"), Path(f"{self.path}-shm")):
            if path.exists():
                os.chmod(path, 0o600)


class NullArchive:
    """Conversation archive implementation used when durable storage is disabled."""

    async def setup(self) -> None:
        return None

    async def recover_interrupted(self, boot_id: str) -> None:
        return None

    async def begin(
        self,
        *,
        request_id: str,
        trace_id: str,
        session_id: str,
        user_id: str | None,
        model: str,
        user_message: str | None,
    ) -> None:
        return None

    async def complete(
        self, row_id: int | None, response: ReportResponse | None
    ) -> None:
        return None

    async def delete_session(self, session_id: str) -> int:
        return 0

    async def delete_user(self, user_id: str) -> int:
        return 0

    async def delete_before(self, cutoff: datetime) -> int:
        return 0

    async def sweep(self, now: datetime) -> SweepResult:
        return SweepResult()

    async def maybe_sweep(self) -> None:
        return None

    async def list_turns(
        self,
        session_id: str | None = None,
        user_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, object]]:
        return []

    async def get_turn(self, row_id: int) -> None:
        return None

    async def close(self) -> None:
        return None
