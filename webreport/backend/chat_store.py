"""Durable chats and messages, separate from checkpoints and the conversation archive."""

import asyncio
import base64
import binascii
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Literal, TypedDict
import unicodedata
from uuid import uuid4

import aiosqlite
from fastapi.encoders import jsonable_encoder
from timestamps import normalize_timestamp, utc_now as _now


def _dump_json(value: object) -> str:
    """Encode whole payloads through FastAPI before any database transaction.

    The store's protected set-rejection contract is the sole encoder override.
    Unencodable objects raise TypeError; non-finite numbers fail strict JSON.
    """
    def reject_set(item: object) -> None:
        raise TypeError(f"Object of type {type(item).__name__} is not JSON serializable")

    try:
        encoded = jsonable_encoder(value, custom_encoder={set: reject_set, frozenset: reject_set})
    except ValueError as error:
        raise TypeError("Payload is not JSON serializable") from error
    return json.dumps(encoded, ensure_ascii=False, allow_nan=False)


class Chat(TypedDict):
    id: str
    title: str
    auto_title: bool
    created_at: str
    updated_at: str
    last_message_at: str | None
    report_count: int


class Message(TypedDict):
    id: str
    request_id: str
    role: Literal["user", "assistant"]
    content: str
    reasoning: str | None
    state: Literal["succeeded", "failed", "cancelled", "interrupted"] | None
    report_id: str | None
    created_at: str


class Run(TypedDict):
    request_id: str
    chat_id: str
    state: Literal["running", "cancelling", "succeeded", "failed", "cancelled", "interrupted"]
    created_at: str
    finished_at: str | None
    error: dict[str, str] | None
    response: dict[str, Any] | None


class ReportCard(TypedDict):
    id: str
    chat_id: str | None
    title: str
    question: str
    tool: str
    args: dict[str, object]
    generated_at: str
    version: int
    saved_at: str | None
    row_count: int | None
    created_at: str


class Report(ReportCard):
    data: object


class RunConflict(RuntimeError):
    """A different active run already owns this chat."""


class RequestConflict(RuntimeError):
    """The request id belongs to a different chat or message."""


class RequestExists(RuntimeError):
    """The request id already identifies this exact turn."""

    def __init__(self, run: Run) -> None:
        super().__init__(run["request_id"])
        self.run: Run = run


class ReportNotFound(LookupError):
    """The requested report does not exist."""


class ChatBusy(RuntimeError):
    """The chat has an active run and cannot be cleared or deleted."""


class ChatNotFound(LookupError):
    """The requested chat does not exist."""


def _searchable(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _title(value: str) -> str:
    collapsed = " ".join(value.split())
    if not 1 <= len(collapsed) <= 80:
        raise ValueError("Chat title must contain 1-80 characters")
    return collapsed


def _decode_cursor(cursor: str) -> tuple[str, str]:
    try:
        raw = base64.b64decode(
            cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True
        )
        timestamp, chat_id = raw.decode("utf-8").split("|", 1)
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if (
            not chat_id
            or "|" in chat_id
            or parsed.tzinfo != timezone.utc
            or not timestamp.endswith("Z")
        ):
            raise ValueError("Invalid chat cursor")
        return normalize_timestamp(timestamp, timespec="microseconds"), chat_id
    except (ValueError, UnicodeError, binascii.Error) as error:
        raise ValueError("Invalid chat cursor") from error


class ChatStore:
    """Use one serialized SQLite connection for chats, runs and reports."""

    def __init__(self, path: str | Path) -> None:
        self.path: Path = Path(path)
        self.connection: aiosqlite.Connection | None = None
        self._write_lock: asyncio.Lock = asyncio.Lock()

    async def setup(self) -> None:
        async with self._write_lock:
            if self.connection is not None:
                return
            connection = await aiosqlite.connect(self.path)
            try:
                connection.row_factory = aiosqlite.Row
                await connection.execute("PRAGMA busy_timeout=5000")
                await connection.execute("PRAGMA journal_mode=WAL")
                await connection.execute("PRAGMA foreign_keys=ON")
                await connection.execute("PRAGMA synchronous=NORMAL")
                await connection.create_function(
                    "utc_timestamp", 1,
                    lambda value: normalize_timestamp(value, timespec="microseconds"),
                    deterministic=True,
                )
                await connection.execute(
                    """CREATE TABLE IF NOT EXISTS chats (
  id TEXT PRIMARY KEY, title TEXT NOT NULL, auto_title INTEGER NOT NULL DEFAULT 1 CHECK (auto_title IN (0,1)),
  search_text TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL, last_message_at TEXT);"""
                )
                await connection.execute(
                    "CREATE INDEX IF NOT EXISTS chats_recent ON chats(updated_at DESC, id DESC);"
                )
                await connection.execute(
                    """CREATE TABLE IF NOT EXISTS runs (
  request_id TEXT PRIMARY KEY, chat_id TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
  message TEXT NOT NULL, state TEXT NOT NULL CHECK (state IN ('running','cancelling','succeeded','failed','cancelled','interrupted')),
  boot_id TEXT NOT NULL, response_json TEXT CHECK (response_json IS NULL OR json_valid(response_json)),
  error_code TEXT, error_message TEXT, created_at TEXT NOT NULL, finished_at TEXT);"""
                )
                await connection.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS runs_one_active ON runs(chat_id) WHERE state IN ('running','cancelling');"
                )
                await connection.execute(
                    "CREATE INDEX IF NOT EXISTS runs_chat ON runs(chat_id, created_at);"
                )
                await connection.execute(
                    """CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY, chat_id TEXT NOT NULL REFERENCES chats(id) ON DELETE CASCADE,
  request_id TEXT NOT NULL REFERENCES runs(request_id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('user','assistant')), content TEXT NOT NULL, reasoning TEXT,
  state TEXT CHECK (state IS NULL OR state IN ('succeeded','failed','cancelled','interrupted')),
  report_id TEXT, created_at TEXT NOT NULL);"""
                )
                await connection.execute(
                    "CREATE INDEX IF NOT EXISTS messages_chat ON messages(chat_id, created_at, id);"
                )
                await connection.execute(
                    """CREATE TABLE IF NOT EXISTS reports (
  id TEXT PRIMARY KEY, chat_id TEXT REFERENCES chats(id) ON DELETE SET NULL,
  request_id TEXT, title TEXT NOT NULL, question TEXT NOT NULL,
  tool TEXT NOT NULL, args_json TEXT NOT NULL CHECK (json_valid(args_json)),
  data_json TEXT NOT NULL CHECK (json_valid(data_json)), row_count INTEGER,
  version INTEGER NOT NULL DEFAULT 1, generated_at TEXT NOT NULL, created_at TEXT NOT NULL, saved_at TEXT);"""
                )
                await connection.execute(
                    "CREATE INDEX IF NOT EXISTS reports_chat ON reports(chat_id, created_at DESC);"
                )
                await connection.execute(
                    "CREATE INDEX IF NOT EXISTS reports_saved ON reports(saved_at DESC) WHERE saved_at IS NOT NULL;"
                )
                await connection.commit()
                for path in (self.path, Path(f"{self.path}-wal"), Path(f"{self.path}-shm")):
                    if path.exists():
                        os.chmod(path, 0o600)
                self.connection = connection
            except BaseException:
                await connection.close()
                raise

    async def close(self) -> None:
        async with self._write_lock:
            if self.connection is not None:
                await self.connection.close()
                self.connection = None

    def _require_connection(self) -> aiosqlite.Connection:
        if self.connection is None:
            raise RuntimeError("Chat store is not open")
        return self.connection

    @asynccontextmanager
    async def _transaction(self) -> AsyncIterator[aiosqlite.Connection]:
        async with self._write_lock:
            connection = self._require_connection()
            await connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
                await connection.commit()
            except BaseException:
                await connection.rollback()
                raise

    async def _get_chat(self, connection: aiosqlite.Connection, chat_id: str) -> Chat | None:
        cursor = await connection.execute(
            """SELECT chats.id, title, auto_title, created_at, updated_at, last_message_at,
                      (SELECT COUNT(*) FROM reports WHERE chat_id = chats.id) AS report_count
               FROM chats WHERE id = ?""",
            (chat_id,),
        )
        try:
            row = await cursor.fetchone()
        finally:
            await cursor.close()
        return self._chat(row) if row is not None else None

    @staticmethod
    def _chat(row: aiosqlite.Row) -> Chat:
        return {
            "id": row["id"],
            "title": row["title"],
            "auto_title": bool(row["auto_title"]),
            "created_at": normalize_timestamp(row["created_at"]),
            "updated_at": normalize_timestamp(row["updated_at"]),
            "last_message_at": normalize_timestamp(row["last_message_at"]),
            "report_count": row["report_count"],
        }

    async def create_chat(self, title: str | None = None) -> Chat:
        auto = title is None
        clean = "Новый чат" if title is None else _title(title)
        chat_id, now = uuid4().hex, _now()
        async with self._transaction() as connection:
            await connection.execute(
                """INSERT INTO chats (id, title, auto_title, search_text, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (chat_id, clean, int(auto), _searchable(clean), now, now),
            )
            chat = await self._get_chat(connection, chat_id)
        assert chat is not None
        return chat

    async def get_chat(self, chat_id: str) -> Chat | None:
        async with self._write_lock:
            return await self._get_chat(self._require_connection(), chat_id)

    async def list_chats(
        self, q: str | None = None, limit: int = 50, cursor: str | None = None
    ) -> tuple[list[Chat], str | None]:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("Chat list limit must be between 1 and 100")
        where: list[str] = []
        params: list[object] = []
        if q:
            where.append("instr(search_text, ?) > 0")
            params.append(_searchable(q))
        if cursor is not None:
            timestamp, chat_id = _decode_cursor(cursor)
            where.append("(utc_timestamp(chats.updated_at), chats.id) < (?, ?)")
            params.extend((timestamp, chat_id))
        clause = " WHERE " + " AND ".join(where) if where else ""
        async with self._write_lock:
            connection = self._require_connection()
            result = await connection.execute(
                """SELECT chats.id, title, auto_title, created_at, updated_at, last_message_at,
                          (SELECT COUNT(*) FROM reports WHERE chat_id = chats.id) AS report_count
                   FROM chats""" + clause + " ORDER BY utc_timestamp(chats.updated_at) DESC, chats.id DESC LIMIT ?",
                (*params, limit + 1),
            )
            try:
                rows = await result.fetchall()
            finally:
                await result.close()
        items = [self._chat(row) for row in rows[:limit]]
        next_cursor = None
        if len(rows) > limit:
            last = items[-1]
            next_cursor = (
                base64.urlsafe_b64encode(f"{last['updated_at']}|{last['id']}".encode("utf-8"))
                .decode("ascii")
                .rstrip("=")
            )
        return items, next_cursor

    async def rename_chat(self, chat_id: str, title: str) -> Chat:
        clean = _title(title)
        async with self._transaction() as connection:
            cursor = await connection.execute(
                "SELECT content FROM messages WHERE chat_id = ? ORDER BY utc_timestamp(created_at), id",
                (chat_id,),
            )
            try:
                contents = [row["content"] for row in await cursor.fetchall()]
            finally:
                await cursor.close()
            updated = await connection.execute(
                """UPDATE chats SET title = ?, auto_title = 0, search_text = ?, updated_at = ?
                   WHERE id = ?""",
                (
                    clean,
                    " ".join(_searchable(text) for text in (clean, *contents)),
                    _now(),
                    chat_id,
                ),
            )
            count = updated.rowcount
            await updated.close()
            if count == 0:
                raise ChatNotFound(chat_id)
            chat = await self._get_chat(connection, chat_id)
        assert chat is not None
        return chat

    async def _check_not_busy(self, connection: aiosqlite.Connection, chat_id: str) -> None:
        cursor = await connection.execute(
            "SELECT 1 FROM runs WHERE chat_id = ? AND state IN ('running','cancelling') LIMIT 1",
            (chat_id,),
        )
        try:
            if await cursor.fetchone() is not None:
                raise ChatBusy(chat_id)
        finally:
            await cursor.close()

    async def delete_chat(self, chat_id: str) -> list[str]:
        async with self._transaction() as connection:
            await self._check_not_busy(connection, chat_id)
            await connection.execute(
                "DELETE FROM reports WHERE chat_id = ? AND saved_at IS NULL", (chat_id,)
            )
            cursor = await connection.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
            count = cursor.rowcount
            await cursor.close()
            if count == 0:
                raise ChatNotFound(chat_id)
        return [chat_id]

    async def append_message(
        self,
        chat_id: str,
        request_id: str,
        role: Literal["user", "assistant"],
        content: str,
        reasoning: str | None,
        state: Literal["succeeded", "failed", "cancelled", "interrupted"] | None,
        report_id: str | None,
    ) -> Message:
        message: Message = {
            "id": uuid4().hex,
            "request_id": request_id,
            "role": role,
            "content": content,
            "reasoning": reasoning,
            "state": state,
            "report_id": report_id,
            "created_at": _now(),
        }
        async with self._transaction() as connection:
            await self._insert_message(connection, chat_id, message)
        return message

    async def _insert_message(
        self, connection: aiosqlite.Connection, chat_id: str, message: Message
    ) -> None:
        role = message["role"]
        content = message["content"]
        first_user = False
        if role == "user":
            cursor = await connection.execute(
                """SELECT 1 FROM chats WHERE id = ? AND auto_title = 1
                   AND NOT EXISTS (SELECT 1 FROM messages WHERE chat_id = ? AND role = 'user')""",
                (chat_id, chat_id),
            )
            try:
                first_user = await cursor.fetchone() is not None
            finally:
                await cursor.close()
        await connection.execute(
            """INSERT INTO messages (id, chat_id, request_id, role, content, reasoning,
                                     state, report_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                message["id"], chat_id, message["request_id"], role, content,
                message["reasoning"], message["state"], message["report_id"], message["created_at"],
            ),
        )
        if first_user and content.split():
            clean = " ".join(content.split())[:80]
            await connection.execute(
                """UPDATE chats SET title = ?, search_text = ?, updated_at = ?, last_message_at = ?
                   WHERE id = ?""",
                (
                    clean,
                    _searchable(clean) + " " + _searchable(content),
                    message["created_at"], message["created_at"], chat_id,
                ),
            )
        else:
            await connection.execute(
                """UPDATE chats SET search_text = search_text || ' ' || ?,
                       updated_at = ?, last_message_at = ? WHERE id = ?""",
                (_searchable(content), message["created_at"], message["created_at"], chat_id),
            )

    async def list_messages(self, chat_id: str) -> list[Message]:
        async with self._write_lock:
            cursor = await self._require_connection().execute(
                """SELECT id, request_id, role, content, reasoning, state, report_id, created_at
                   FROM messages WHERE chat_id = ? ORDER BY utc_timestamp(created_at), id""",
                (chat_id,),
            )
            try:
                return [
                    {
                        "id": row["id"],
                        "request_id": row["request_id"],
                        "role": row["role"],
                        "content": row["content"],
                        "reasoning": row["reasoning"],
                        "state": row["state"],
                        "report_id": row["report_id"],
                        "created_at": normalize_timestamp(row["created_at"]),
                    }
                    for row in await cursor.fetchall()
                ]
            finally:
                await cursor.close()

    async def set_message_state(
        self, message_id: str, state: Literal["succeeded", "failed", "cancelled", "interrupted"]
    ) -> None:
        async with self._transaction() as connection:
            await connection.execute(
                "UPDATE messages SET state = ? WHERE id = ? AND role = 'assistant'",
                (state, message_id),
            )

    async def clear_chat(self, chat_id: str) -> None:
        async with self._transaction() as connection:
            await self._check_not_busy(connection, chat_id)
            cursor = await connection.execute("SELECT title FROM chats WHERE id = ?", (chat_id,))
            try:
                row = await cursor.fetchone()
            finally:
                await cursor.close()
            await connection.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))
            await connection.execute("DELETE FROM runs WHERE chat_id = ?", (chat_id,))
            if row is not None:
                await connection.execute(
                    """UPDATE chats SET search_text = ?, last_message_at = NULL, updated_at = ?
                       WHERE id = ?""",
                    (_searchable(row["title"]), _now(), chat_id),
                )

    @staticmethod
    def _run(row: aiosqlite.Row) -> Run:
        response = json.loads(row["response_json"]) if row["response_json"] is not None else None
        if response is not None:
            if "timestamp" in response:
                response["timestamp"] = normalize_timestamp(response["timestamp"])
            if response.get("report") is not None:
                for field in ("created_at", "generated_at", "saved_at"):
                    response["report"][field] = normalize_timestamp(response["report"].get(field))
        return {
            "request_id": row["request_id"],
            "chat_id": row["chat_id"],
            "state": row["state"],
            "created_at": normalize_timestamp(row["created_at"]),
            "finished_at": normalize_timestamp(row["finished_at"]),
            "error": (
                {"code": row["error_code"], "message": row["error_message"]}
                if row["error_code"] is not None else None
            ),
            "response": response,
        }

    @staticmethod
    def _report_card(row: aiosqlite.Row) -> ReportCard:
        return {
            "id": row["id"],
            "chat_id": row["chat_id"],
            "title": row["title"],
            "question": row["question"],
            "tool": row["tool"],
            "args": json.loads(row["args_json"]),
            "generated_at": normalize_timestamp(row["generated_at"]),
            "version": row["version"],
            "saved_at": normalize_timestamp(row["saved_at"]),
            "row_count": row["row_count"],
            "created_at": normalize_timestamp(row["created_at"]),
        }

    @classmethod
    def _report(cls, row: aiosqlite.Row) -> Report:
        return {**cls._report_card(row), "data": json.loads(row["data_json"])}

    async def _get_run(self, connection: aiosqlite.Connection, request_id: str) -> Run | None:
        cursor = await connection.execute("SELECT * FROM runs WHERE request_id = ?", (request_id,))
        try:
            row = await cursor.fetchone()
        finally:
            await cursor.close()
        return self._run(row) if row is not None else None

    async def _get_report(self, connection: aiosqlite.Connection, report_id: str) -> Report | None:
        cursor = await connection.execute("SELECT * FROM reports WHERE id = ?", (report_id,))
        try:
            row = await cursor.fetchone()
        finally:
            await cursor.close()
        return self._report(row) if row is not None else None

    async def create_run(
        self, chat_id: str, request_id: str, message: str, boot_id: str,
        *, with_user_message: bool = False,
    ) -> Run:
        now = _now()
        try:
            async with self._transaction() as connection:
                cursor = await connection.execute(
                    "SELECT chat_id, message FROM runs WHERE request_id = ?", (request_id,)
                )
                try:
                    existing = await cursor.fetchone()
                finally:
                    await cursor.close()
                if existing is not None:
                    if (existing["chat_id"], existing["message"]) == (chat_id, message):
                        run = await self._get_run(connection, request_id)
                        assert run is not None
                        raise RequestExists(run)
                    raise RequestConflict(request_id)
                await connection.execute(
                    """INSERT INTO runs (request_id, chat_id, message, state, boot_id, created_at)
                       VALUES (?, ?, ?, 'running', ?, ?)""",
                    (request_id, chat_id, message, boot_id, now),
                )
                if with_user_message:
                    await self._insert_message(connection, chat_id, {
                        "id": uuid4().hex, "request_id": request_id, "role": "user",
                        "content": message, "reasoning": None, "state": None,
                        "report_id": None, "created_at": now,
                    })
                run = await self._get_run(connection, request_id)
        except sqlite3.IntegrityError as error:
            if "runs.request_id" not in str(error) and "runs.chat_id" not in str(error):
                raise
            # SQLite may report the partial index before the primary key when both
            # collide. Inspect the id only AFTER the failed insert, never before it.
            async with self._write_lock:
                cursor = await self._require_connection().execute(
                    "SELECT * FROM runs WHERE request_id = ?", (request_id,)
                )
                try:
                    existing = await cursor.fetchone()
                finally:
                    await cursor.close()
            if existing is not None:
                if (existing["chat_id"], existing["message"]) == (chat_id, message):
                    raise RequestExists(self._run(existing)) from error
                raise RequestConflict(request_id) from error
            if "runs.chat_id" in str(error):
                raise RunConflict(chat_id) from error
            raise
        assert run is not None
        return run

    async def get_run(self, request_id: str) -> Run | None:
        async with self._write_lock:
            return await self._get_run(self._require_connection(), request_id)

    async def get_request(self, request_id: str) -> tuple[Run, str] | None:
        """Return the public run and its original input for retry identity checks."""
        async with self._transaction() as connection:
            cursor = await connection.execute(
                "SELECT * FROM runs WHERE request_id = ?", (request_id,)
            )
            try:
                row = await cursor.fetchone()
            finally:
                await cursor.close()
            return (self._run(row), row["message"]) if row is not None else None

    async def finish_run(
        self, request_id: str, state: str, response: Mapping[str, Any] | None,
        error: tuple[str, str] | None,
    ) -> None:
        response_json = _dump_json(response) if response is not None else None
        code, message = error if error is not None else (None, None)
        async with self._transaction() as connection:
            cursor = await connection.execute(
                """UPDATE runs SET state = ?, response_json = ?, error_code = ?,
                       error_message = ?, finished_at = ?
                   WHERE request_id = ? AND state IN ('running','cancelling')""",
                (state, response_json, code, message, _now(), request_id),
            )
            await cursor.close()

    async def force_fail_run(self, request_id: str) -> None:
        """Minimal terminal write if normal run finalisation raised before committing."""
        async with self._transaction() as connection:
            cursor = await connection.execute(
                """UPDATE runs SET state = 'failed', error_code = 'internal:finalise',
                          error_message = 'Внутренняя ошибка', finished_at = ?
                   WHERE request_id = ? AND state IN ('running','cancelling')""",
                (_now(), request_id),
            )
            await cursor.close()

    async def set_run_state(self, request_id: str, state: str) -> None:
        async with self._transaction() as connection:
            cursor = await connection.execute(
                "UPDATE runs SET state = ? WHERE request_id = ? AND state = 'running'",
                (state, request_id),
            )
            await cursor.close()

    async def active_run(self, chat_id: str) -> Run | None:
        async with self._write_lock:
            cursor = await self._require_connection().execute(
                """SELECT * FROM runs WHERE chat_id = ?
                   AND state IN ('running','cancelling')""", (chat_id,)
            )
            try:
                row = await cursor.fetchone()
            finally:
                await cursor.close()
        return self._run(row) if row is not None else None

    async def last_run(self, chat_id: str) -> Run | None:
        async with self._write_lock:
            cursor = await self._require_connection().execute(
                """SELECT * FROM runs WHERE chat_id = ?
                   AND state NOT IN ('running','cancelling')
                   ORDER BY utc_timestamp(created_at) DESC, request_id DESC LIMIT 1""", (chat_id,)
            )
            try:
                row = await cursor.fetchone()
            finally:
                await cursor.close()
        return self._run(row) if row is not None else None

    async def sweep_interrupted(self, boot_id: str) -> list[Run]:
        async with self._transaction() as connection:
            cursor = await connection.execute(
                """SELECT request_id FROM runs WHERE boot_id != ?
                   AND state IN ('running','cancelling') ORDER BY utc_timestamp(created_at), request_id""",
                (boot_id,),
            )
            try:
                ids = [row["request_id"] for row in await cursor.fetchall()]
            finally:
                await cursor.close()
            if not ids:
                return []
            await connection.execute(
                """UPDATE runs SET state = 'interrupted', finished_at = ?
                   WHERE boot_id != ? AND state IN ('running','cancelling')""",
                (_now(), boot_id),
            )
            runs = [await self._get_run(connection, request_id) for request_id in ids]
        return [run for run in runs if run is not None]

    async def publish_result(
        self, request_id: str, *, assistant: Mapping[str, Any], report: Mapping[str, Any] | None,
        response: Mapping[str, Any], state: Literal["succeeded", "failed"],
    ) -> bool:
        """Commit the assistant, prepared report and response as one terminal outcome.

        A report supplies id, title, question, tool, args, data and generated_at.
        """
        # Reject non-JSON report data before even opening the transaction.
        now = _now()
        report_id = report["id"] if report is not None else None
        if report is not None:
            args_json = _dump_json(report["args"])
            data_json = _dump_json(report["data"])
        else:
            args_json = data_json = None
        # Validate the entire envelope too, not only the marked report's rows.
        prepared_response = json.loads(_dump_json(response))
        if "timestamp" in prepared_response:
            prepared_response["timestamp"] = normalize_timestamp(prepared_response["timestamp"])
        async with self._transaction() as connection:
            cursor = await connection.execute(
                "SELECT chat_id FROM runs WHERE request_id = ?", (request_id,)
            )
            try:
                run_row = await cursor.fetchone()
            finally:
                await cursor.close()
            # The state-guarded UPDATE remains the publication arbiter. A terminal run
            # may be observed here, but no assistant/report row can be inserted for it.
            chat_id = run_row["chat_id"] if run_row is not None else None
            card: ReportCard | None = None
            if report is not None:
                assert args_json is not None
                card = ReportCard(
                    id=report["id"], chat_id=chat_id,
                    title=report["title"], question=report["question"],
                    tool=report["tool"], args=json.loads(args_json),
                    generated_at=normalize_timestamp(report["generated_at"]), version=1,
                    saved_at=None,
                    row_count=len(report["data"]) if isinstance(report["data"], list) else None,
                    created_at=normalize_timestamp(report.get("created_at", now)),
                )
            response_json = _dump_json({**prepared_response, "report": card})
            updated = await connection.execute(
                """UPDATE runs SET state = ?, response_json = ?, finished_at = ?
                   WHERE request_id = ? AND state IN ('running','cancelling')""",
                (state, response_json, now, request_id),
            )
            count = updated.rowcount
            await updated.close()
            if count == 0:
                return False
            message_id = uuid4().hex
            await connection.execute(
                """INSERT INTO messages (id, chat_id, request_id, role, content, reasoning,
                                         state, report_id, created_at)
                   VALUES (?, ?, ?, 'assistant', ?, ?, ?, NULL, ?)""",
                (message_id, chat_id, request_id, assistant["content"],
                 assistant.get("reasoning"), state, now),
            )
            if report is not None:
                assert card is not None
                await connection.execute(
                    """INSERT INTO reports (id, chat_id, request_id, title, question, tool,
                                            args_json, data_json, row_count, generated_at, created_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (report_id, chat_id, request_id, card["title"], card["question"],
                     card["tool"], args_json, data_json, card["row_count"],
                     card["generated_at"], card["created_at"]),
                )
                await connection.execute(
                    "UPDATE messages SET report_id = ? WHERE id = ?", (report_id, message_id)
                )
            await connection.execute(
                """UPDATE chats SET search_text = search_text || ' ' || ?,
                       updated_at = ?, last_message_at = ? WHERE id = ?""",
                (_searchable(assistant["content"]), now, now, chat_id),
            )
        return True

    async def get_report(self, report_id: str) -> Report | None:
        async with self._write_lock:
            return await self._get_report(self._require_connection(), report_id)

    async def list_reports(self, chat_id: str) -> list[ReportCard]:
        async with self._write_lock:
            cursor = await self._require_connection().execute(
                """SELECT id, chat_id, title, question, tool, args_json, row_count,
                          version, generated_at, created_at, saved_at
                   FROM reports WHERE chat_id = ? ORDER BY utc_timestamp(created_at) DESC, id DESC""",
                (chat_id,),
            )
            try:
                return [self._report_card(row) for row in await cursor.fetchall()]
            finally:
                await cursor.close()

    async def list_saved_reports(self) -> list[ReportCard]:
        async with self._write_lock:
            cursor = await self._require_connection().execute(
                """SELECT id, chat_id, title, question, tool, args_json, row_count,
                          version, generated_at, created_at, saved_at
                   FROM reports WHERE saved_at IS NOT NULL ORDER BY utc_timestamp(saved_at) DESC, id DESC"""
            )
            try:
                return [self._report_card(row) for row in await cursor.fetchall()]
            finally:
                await cursor.close()

    async def set_saved(self, report_id: str, saved: bool) -> ReportCard:
        async with self._transaction() as connection:
            cursor = await connection.execute(
                """UPDATE reports SET saved_at = CASE WHEN ? THEN COALESCE(saved_at, ?) ELSE NULL END
                   WHERE id = ?""",
                (int(saved), _now(), report_id),
            )
            count = cursor.rowcount
            await cursor.close()
            if count == 0:
                raise ReportNotFound(report_id)
            cursor = await connection.execute(
                """SELECT id, chat_id, title, question, tool, args_json, row_count,
                          version, generated_at, created_at, saved_at
                   FROM reports WHERE id = ?""", (report_id,)
            )
            try:
                row = await cursor.fetchone()
            finally:
                await cursor.close()
            assert row is not None
            card = self._report_card(row)
        return card

    async def replace_report_data(
        self, report_id: str, data: object, generated_at: str, expected_version: int
    ) -> Report | None:
        data_json = _dump_json(data)
        row_count = len(data) if isinstance(data, list) else None
        async with self._transaction() as connection:
            cursor = await connection.execute(
                """UPDATE reports SET data_json = ?, row_count = ?, generated_at = ?,
                       version = version + 1 WHERE id = ? AND version = ?""",
                (data_json, row_count, generated_at, report_id, expected_version),
            )
            count = cursor.rowcount
            await cursor.close()
            return await self._get_report(connection, report_id) if count else None
