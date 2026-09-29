"""Contract tests for the durable chat and message store."""

import asyncio
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from chat_store import Chat, ChatBusy, ChatStore


class ChatStoreTests(unittest.IsolatedAsyncioTestCase):
    def __init__(self, methodName: str = "runTest") -> None:
        super().__init__(methodName)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "chats.db"
        self.store = ChatStore(self.path)

    async def asyncSetUp(self) -> None:
        await self.store.setup()

    async def asyncTearDown(self) -> None:
        await self.store.close()
        self.temp_dir.cleanup()

    async def existing_chat(self, chat_id: str) -> Chat:
        chat = await self.store.get_chat(chat_id)
        assert chat is not None
        return chat

    async def rows(self, sql: str, params: tuple[object, ...] = ()) -> list[tuple[object, ...]]:
        assert self.store.connection is not None
        cursor = await self.store.connection.execute(sql, params)
        try:
            return [tuple(row) for row in await cursor.fetchall()]
        finally:
            await cursor.close()

    async def insert_run(self, chat_id: str, request_id: str, state: str = "succeeded") -> None:
        assert self.store.connection is not None
        await self.store.connection.execute(
            """INSERT INTO runs (request_id, chat_id, message, state, boot_id, created_at)
               VALUES (?, ?, 'question', ?, 'boot', '2026-01-01T00:00:00Z')""",
            (request_id, chat_id, state),
        )
        await self.store.connection.commit()

    async def report(self, chat_id: str, report_id: str, saved: bool) -> None:
        assert self.store.connection is not None
        await self.store.connection.execute(
            """INSERT INTO reports (id, chat_id, title, question, tool, args_json,
                                    data_json, generated_at, created_at, saved_at)
               VALUES (?, ?, 'title', 'question', 'tool', ?, ?, ?, ?, ?)""",
            (
                report_id,
                chat_id,
                json.dumps({"arg": 1}),
                json.dumps([{"value": 1}]),
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:00:00Z",
                "2026-01-01T00:00:00Z" if saved else None,
            ),
        )
        await self.store.connection.commit()

    async def test_setup_idempotent_on_existing_database_and_private_file(self) -> None:
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        chat = await self.store.create_chat("Existing")
        await self.store.setup()
        await self.store.close()
        self.store = ChatStore(self.path)
        await self.store.setup()
        self.assertEqual((await self.existing_chat(chat["id"]))["title"], "Existing")
        self.assertEqual(await self.rows("PRAGMA foreign_keys"), [(1,)])
        self.assertEqual(await self.rows("PRAGMA journal_mode"), [("wal",)])
        self.assertEqual(await self.rows("PRAGMA synchronous"), [(1,)])
        self.assertEqual(len(await self.rows("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('chats','runs','messages','reports')")), 4)

    async def test_create_get_and_list_order_tied_updated_at_by_id(self) -> None:
        first = await self.store.create_chat(None)
        second = await self.store.create_chat("Second")
        self.assertEqual(first["title"], "Новый чат")
        self.assertTrue(first["auto_title"])
        self.assertFalse(second["auto_title"])
        self.assertEqual(first["report_count"], 0)
        self.assertIsNone(first["last_message_at"])
        self.assertIsNone(await self.store.get_chat("missing"))
        assert self.store.connection is not None
        await self.store.connection.execute("UPDATE chats SET updated_at='2026-01-01T00:00:00Z'")
        await self.store.connection.commit()
        items, cursor = await self.store.list_chats(None, 50, None)
        self.assertEqual([row["id"] for row in items], sorted((first["id"], second["id"]), reverse=True))
        self.assertIsNone(cursor)
        self.assertEqual(set(items[0]), {"id", "title", "auto_title", "created_at", "updated_at", "last_message_at", "report_count"})

    async def test_keyset_pagination_120_chats_without_gaps_or_duplicates(self) -> None:
        chats = [await self.store.create_chat(f"Chat {n}") for n in range(120)]
        assert self.store.connection is not None
        await self.store.connection.execute("UPDATE chats SET updated_at='2026-01-01T00:00:00Z'")
        await self.store.connection.commit()
        seen: list[str] = []
        cursor = None
        for size in (50, 50, 20):
            page, cursor = await self.store.list_chats(None, 50, cursor)
            self.assertEqual(len(page), size)
            seen.extend(chat["id"] for chat in page)
        self.assertIsNone(cursor)
        self.assertEqual(seen, sorted((chat["id"] for chat in chats), reverse=True))
        self.assertEqual(len(set(seen)), 120)

    async def test_search_normalizes_unicode_in_answer_and_ignores_reasoning(self) -> None:
        chat = await self.store.create_chat("Start")
        await self.insert_run(chat["id"], "request-answer")
        await self.store.append_message(chat["id"], "request-answer", "assistant", "однажды", "secret", "succeeded", None)
        items, _ = await self.store.list_chats("ОДНАЖДЫ", 50, None)
        self.assertEqual([item["id"] for item in items], [chat["id"]])
        self.assertEqual((await self.store.list_chats("SECRET", 50, None))[0], [])
        other = await self.store.create_chat("ＡＢＣ")
        self.assertEqual([item["id"] for item in (await self.store.list_chats("abc", 50, None))[0]], [other["id"]])

    async def test_first_user_message_sets_auto_title_once_and_truncates_codepoints(self) -> None:
        chat = await self.store.create_chat(None)
        await self.insert_run(chat["id"], "first")
        content = "  " + "🙂" * 81 + "  extra  "
        message = await self.store.append_message(chat["id"], "first", "user", content, None, None, None)
        self.assertEqual(message["content"], content)
        self.assertIsNone(message["state"])
        self.assertEqual(set(message), {"id", "request_id", "role", "content", "reasoning", "state", "report_id", "created_at"})
        updated = await self.existing_chat(chat["id"])
        self.assertEqual(updated["title"], "🙂" * 80)
        self.assertTrue(updated["auto_title"])
        self.assertIsNotNone(updated["last_message_at"])
        await self.store.append_message(chat["id"], "first", "user", "Second question", None, None, None)
        self.assertEqual((await self.existing_chat(chat["id"]))["title"], "🙂" * 80)

    async def test_rename_recomputes_search_and_disables_auto_title(self) -> None:
        chat = await self.store.create_chat("Old unique title")
        await self.insert_run(chat["id"], "renamed-run")
        await self.store.append_message(chat["id"], "renamed-run", "user", "persisted question", None, None, None)
        updated = await self.store.rename_chat(chat["id"], "  New   unique title  ")
        self.assertEqual(updated["title"], "New unique title")
        self.assertFalse(updated["auto_title"])
        self.assertEqual((await self.store.list_chats("Old unique", 50, None))[0], [])
        self.assertEqual([row["id"] for row in (await self.store.list_chats("new unique", 50, None))[0]], [chat["id"]])
        self.assertEqual([row["id"] for row in (await self.store.list_chats("persisted question", 50, None))[0]], [chat["id"]])
        await self.store.append_message(chat["id"], "renamed-run", "user", "later question", None, None, None)
        self.assertEqual((await self.existing_chat(chat["id"]))["title"], "New unique title")

    async def test_list_messages_and_set_message_state(self) -> None:
        chat = await self.store.create_chat(None)
        await self.insert_run(chat["id"], "messages-run")
        user = await self.store.append_message(chat["id"], "messages-run", "user", "hello", None, None, None)
        assistant = await self.store.append_message(chat["id"], "messages-run", "assistant", "world", "thinking", "succeeded", None)
        assert self.store.connection is not None
        await self.store.connection.execute(
            "UPDATE messages SET created_at = ? WHERE id = ?",
            ("2026-01-01T00:00:00Z", user["id"]),
        )
        await self.store.connection.execute(
            "UPDATE messages SET created_at = ? WHERE id = ?",
            ("2026-01-02T00:00:00Z", assistant["id"]),
        )
        await self.store.connection.commit()
        await self.store.set_message_state(assistant["id"], "failed")
        messages = await self.store.list_messages(chat["id"])
        self.assertEqual([message["id"] for message in messages], [user["id"], assistant["id"]])
        self.assertEqual(messages[0]["state"], None)
        self.assertEqual(messages[1]["state"], "failed")
        self.assertEqual(messages[1]["reasoning"], "thinking")
        self.assertEqual(await self.store.list_messages("absent"), [])

    async def test_clear_removes_messages_and_runs_but_keeps_both_reports_and_chat(self) -> None:
        chat = await self.store.create_chat("Keep title")
        await self.insert_run(chat["id"], "clear-run")
        await self.store.append_message(chat["id"], "clear-run", "user", "needle", None, None, None)
        await self.report(chat["id"], "saved", True)
        await self.report(chat["id"], "unsaved", False)
        await self.store.clear_chat(chat["id"])
        self.assertEqual(await self.store.list_messages(chat["id"]), [])
        self.assertEqual(await self.rows("SELECT request_id FROM runs"), [])
        self.assertEqual(await self.rows("SELECT id FROM reports ORDER BY id"), [("saved",), ("unsaved",)])
        current = await self.existing_chat(chat["id"])
        self.assertIsNone(current["last_message_at"])
        self.assertEqual(current["report_count"], 2)
        self.assertEqual((await self.store.list_chats("needle", 50, None))[0], [])
        self.assertEqual([row["id"] for row in (await self.store.list_chats("KEEP TITLE", 50, None))[0]], [chat["id"]])

    async def test_clear_busy_preserves_all_rows(self) -> None:
        chat = await self.store.create_chat(None)
        await self.insert_run(chat["id"], "active-clear", "running")
        with self.assertRaises(ChatBusy):
            await self.store.clear_chat(chat["id"])
        self.assertEqual(await self.rows("SELECT request_id FROM runs"), [("active-clear",)])
        self.assertIsNotNone(await self.store.get_chat(chat["id"]))

    async def test_delete_busy_preserves_chat(self) -> None:
        chat = await self.store.create_chat(None)
        await self.insert_run(chat["id"], "active-delete", "cancelling")
        with self.assertRaises(ChatBusy):
            await self.store.delete_chat(chat["id"])
        self.assertIsNotNone(await self.store.get_chat(chat["id"]))
        self.assertEqual(await self.rows("SELECT request_id FROM runs"), [("active-delete",)])

    async def test_delete_detaches_saved_reports_and_deletes_unsaved(self) -> None:
        chat = await self.store.create_chat("Delete")
        await self.insert_run(chat["id"], "delete-run")
        await self.store.append_message(chat["id"], "delete-run", "user", "q", None, None, None)
        await self.report(chat["id"], "saved", True)
        await self.report(chat["id"], "unsaved", False)
        self.assertEqual((await self.existing_chat(chat["id"]))["report_count"], 2)
        self.assertEqual(await self.store.delete_chat(chat["id"]), [chat["id"]])
        self.assertIsNone(await self.store.get_chat(chat["id"]))
        self.assertEqual(await self.rows("SELECT id,chat_id FROM reports"), [("saved", None)])
        self.assertEqual(await self.rows("SELECT id FROM messages"), [])
        self.assertEqual(await self.rows("SELECT request_id FROM runs"), [])

    async def test_unknown_chat_message_raises_foreign_key_integrity_error(self) -> None:
        chat = await self.store.create_chat("Valid")
        await self.insert_run(chat["id"], "fk-run")
        with self.assertRaises(sqlite3.IntegrityError):
            await self.store.append_message("missing", "fk-run", "user", "invalid", None, None, None)
        self.assertEqual(await self.store.list_messages("missing"), [])
        valid = await self.store.append_message(chat["id"], "fk-run", "user", "valid", None, None, None)
        self.assertEqual(len(await self.store.list_messages(chat["id"])), 1)
        self.assertEqual(valid["content"], "valid")

    async def test_invalid_limit_and_cursor_raise_value_error(self) -> None:
        for limit in (0, 101, -1, True):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                await self.store.list_chats(None, limit, None)
        for cursor in ("garbage", "!!!", "bm90LWF8Y3Vyc29y", "\" OR 1=1 --"):
            with self.subTest(cursor=cursor), self.assertRaisesRegex(ValueError, "cursor"):
                await self.store.list_chats(None, 50, cursor)

    async def test_search_treats_wildcards_and_quotes_as_literal_text(self) -> None:
        chat = await self.store.create_chat("100%_ ' OR 1=1 --")
        other = await self.store.create_chat("Ordinary")
        self.assertEqual([row["id"] for row in (await self.store.list_chats("%_ ' OR 1=1 --", 50, None))[0]], [chat["id"]])
        self.assertEqual((await self.store.list_chats("%not-there", 50, None))[0], [])
        self.assertEqual([row["id"] for row in (await self.store.list_chats("ordinary", 50, None))[0]], [other["id"]])

    async def test_whitespace_only_title_is_invalid(self) -> None:
        with self.assertRaises(ValueError):
            await self.store.create_chat(" \t \n ")
        chat = await self.store.create_chat("Valid")
        with self.assertRaises(ValueError):
            await self.store.rename_chat(chat["id"], " \t\n ")
        self.assertEqual((await self.existing_chat(chat["id"]))["title"], "Valid")

    async def test_concurrent_writes_preserve_both_messages_and_search_terms(self) -> None:
        chat = await self.store.create_chat("Concurrent")
        await self.insert_run(chat["id"], "parallel-1")
        await self.insert_run(chat["id"], "parallel-2")
        messages = await asyncio.wait_for(
            asyncio.gather(
                self.store.append_message(chat["id"], "parallel-1", "assistant", "alpha", None, "succeeded", None),
                self.store.append_message(chat["id"], "parallel-2", "assistant", "beta", None, "succeeded", None),
            ),
            timeout=5,
        )
        self.assertEqual({message["content"] for message in messages}, {"alpha", "beta"})
        self.assertEqual(len(await self.store.list_messages(chat["id"])), 2)
        for term in ("alpha", "beta"):
            self.assertEqual([row["id"] for row in (await self.store.list_chats(term, 50, None))[0]], [chat["id"]])


if __name__ == "__main__":
    unittest.main()
