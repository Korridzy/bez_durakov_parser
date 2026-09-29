"""Durable chats and messages, separate from checkpoints and the conversation archive."""

import asyncio
import base64
import binascii
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Literal, TypedDict
import unicodedata
from uuid import uuid4

import aiosqlite


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


class ChatBusy(RuntimeError):
    """The chat has an active run and cannot be cleared or deleted."""


class ChatNotFound(LookupError):
    """The requested chat does not exist."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


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
        return timestamp, chat_id
    except (ValueError, UnicodeError, binascii.Error) as error:
        raise ValueError("Invalid chat cursor") from error


class ChatStore:
    """Use one serialized SQLite connection for chat and message operations."""

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
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "last_message_at": row["last_message_at"],
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
            where.append("(chats.updated_at, chats.id) < (?, ?)")
            params.extend((timestamp, chat_id))
        clause = " WHERE " + " AND ".join(where) if where else ""
        async with self._write_lock:
            connection = self._require_connection()
            result = await connection.execute(
                """SELECT chats.id, title, auto_title, created_at, updated_at, last_message_at,
                          (SELECT COUNT(*) FROM reports WHERE chat_id = chats.id) AS report_count
                   FROM chats""" + clause + " ORDER BY chats.updated_at DESC, chats.id DESC LIMIT ?",
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
                "SELECT content FROM messages WHERE chat_id = ? ORDER BY created_at, id",
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
                    message["id"], chat_id, request_id, role, content,
                    reasoning, state, report_id, message["created_at"],
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
        return message

    async def list_messages(self, chat_id: str) -> list[Message]:
        async with self._write_lock:
            cursor = await self._require_connection().execute(
                """SELECT id, request_id, role, content, reasoning, state, report_id, created_at
                   FROM messages WHERE chat_id = ? ORDER BY created_at, id""",
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
                        "created_at": row["created_at"],
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
