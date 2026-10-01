"""Contract tests for the durable chat and message store."""

import asyncio
import json
from pathlib import Path
import sqlite3
import tempfile
from typing import Any
import unittest
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from dataclasses import dataclass
from itertools import product
from pydantic import BaseModel
from uuid import UUID
from fastapi.encoders import jsonable_encoder
from starlette.responses import JSONResponse

from chat_store import (
    Chat, ChatBusy, ChatStore, Report, ReportNotFound, RequestConflict,
    RequestExists, Run, RunConflict,
)


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

    async def existing_run(self, request_id: str) -> Run:
        run = await self.store.get_run(request_id)
        assert run is not None
        return run

    async def existing_report(self, report_id: str) -> Report:
        report = await self.store.get_report(report_id)
        assert report is not None
        return report

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
        first_page, cursor = await self.store.list_chats(None, 50, None)
        self.assertEqual(len(first_page), 50)
        assert cursor is not None
        # Both mutations land before the cursor. Offset pagination would duplicate a
        # page-one row and omit a row from the original 120.
        inserted = await self.store.create_chat("New arrival")
        await self.store.connection.execute(
            "UPDATE chats SET updated_at='9999-01-01T00:00:00Z' WHERE id=?",
            (first_page[-1]["id"],),
        )
        await self.store.connection.commit()
        seen = [chat["id"] for chat in first_page]
        for size in (50, 20):
            page, cursor = await self.store.list_chats(None, 50, cursor)
            self.assertEqual(len(page), size)
            seen.extend(chat["id"] for chat in page)
        self.assertIsNone(cursor)
        self.assertNotIn(inserted["id"], seen)
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

    async def new_run(self, message: str = "What happened?") -> tuple[str, str]:
        chat = await self.store.create_chat()
        request_id = f"request-{chat['id']}"
        await self.store.create_run(chat["id"], request_id, message, "boot-1")
        return chat["id"], request_id

    @staticmethod
    def marked_report(report_id: str = "report-1", data: object = None) -> dict[str, Any]:
        return {
            "id": report_id, "title": "Answer", "question": "What happened?",
            "tool": "read_rows", "args": {"limit": 2, "category": "данные"},
            "data": [{"value": 12}, {"value": 13}] if data is None else data,
            "generated_at": "2026-01-02T00:00:00Z",
        }

    @staticmethod
    def answered(content: str = "Answer") -> tuple[dict[str, Any], dict[str, Any]]:
        return (
            {"content": content, "reasoning": "because"},
            {"session_id": "chat", "message": content, "success": True,
             "data": [{"value": 12}], "report": None},
        )

    async def test_create_run_conflicts_and_request_reuse(self) -> None:
        chat_id, request_id = await self.new_run()
        other = await self.store.create_chat()
        run = await self.store.get_run(request_id)
        assert run is not None
        self.assertEqual(run["chat_id"], chat_id)
        self.assertEqual(run["state"], "running")
        self.assertIsNone(run["response"])
        self.assertIsNone(run["finished_at"])
        with self.assertRaises(RequestExists) as existing:
            await self.store.create_run(chat_id, request_id, "What happened?", "boot-2")
        self.assertEqual(existing.exception.run, run)
        with self.assertRaises(RequestConflict):
            await self.store.create_run(chat_id, request_id, "Different", "boot-1")
        with self.assertRaises(RequestConflict):
            await self.store.create_run(other["id"], request_id, "What happened?", "boot-1")
        with self.assertRaises(RunConflict):
            await self.store.create_run(chat_id, "another", "Second", "boot-1")
        self.assertEqual(await self.rows("SELECT request_id FROM runs"), [(request_id,)])
        self.assertIsNone(await self.store.get_run("missing"))

    async def test_concurrent_create_run_one_active_index_decides(self) -> None:
        chat = await self.store.create_chat()
        results = await asyncio.wait_for(asyncio.gather(
            self.store.create_run(chat["id"], "one", "First", "boot"),
            self.store.create_run(chat["id"], "two", "Second", "boot"),
            return_exceptions=True,
        ), 5)
        self.assertEqual(sum(isinstance(result, dict) for result in results), 1)
        self.assertEqual(sum(isinstance(result, RunConflict) for result in results), 1)
        self.assertEqual(len(await self.rows("SELECT request_id FROM runs")), 1)
        self.assertEqual(
            await self.rows("SELECT name FROM sqlite_master WHERE type='index' AND name='runs_one_active'"),
            [("runs_one_active",)],
        )

    async def test_run_state_finish_and_invalid_states_check_constraints(self) -> None:
        chat_id, request_id = await self.new_run()
        active_run = await self.store.active_run(chat_id)
        assert active_run is not None
        self.assertEqual(active_run["request_id"], request_id)
        await self.store.set_run_state(request_id, "cancelling")
        self.assertEqual((await self.existing_run(request_id))["state"], "cancelling")
        response = {"success": False, "data": [12], "message": "Failed"}
        await self.store.finish_run(request_id, "failed", response, ("timeout", "Timed out"))
        run = await self.store.get_run(request_id)
        assert run is not None
        self.assertEqual(run["response"], response)
        self.assertEqual(run["error"], {"code": "timeout", "message": "Timed out"})
        self.assertIsNotNone(run["finished_at"])
        self.assertIsNone(await self.store.active_run(chat_id))
        self.assertEqual(await self.store.last_run(chat_id), run)
        await self.store.set_run_state(request_id, "cancelling")
        await self.store.finish_run(request_id, "cancelled", None, None)
        self.assertEqual(await self.store.get_run(request_id), run)
        active = await self.store.create_run(chat_id, "next", "Next", "boot")
        with self.assertRaises(sqlite3.IntegrityError):
            await self.store.set_run_state(active["request_id"], "not-a-state")
        with self.assertRaises(sqlite3.IntegrityError):
            await self.store.finish_run(active["request_id"], "not-a-state", None, None)
        self.assertEqual((await self.existing_run("next"))["state"], "running")
        self.assertIsNone(await self.store.last_run("missing"))

    async def test_sweep_interrupted_only_foreign_boot_rows_and_idempotent_setup(self) -> None:
        a = await self.store.create_chat()
        b = await self.store.create_chat()
        c = await self.store.create_chat()
        d = await self.store.create_chat()
        await self.store.create_run(a["id"], "foreign-running", "Q", "old")
        await self.store.create_run(b["id"], "foreign-cancelling", "Q", "old")
        await self.store.set_run_state("foreign-cancelling", "cancelling")
        await self.store.create_run(c["id"], "current-running", "Q", "current")
        await self.store.create_run(d["id"], "foreign-finished", "Q", "old")
        await self.store.finish_run("foreign-finished", "succeeded", {"success": True}, None)
        await self.store.close()
        self.store = ChatStore(self.path)
        await self.store.setup()
        self.assertEqual(
            {run["request_id"] for run in await self.store.sweep_interrupted("current")},
            {"foreign-running", "foreign-cancelling"},
        )
        self.assertEqual(await self.store.sweep_interrupted("current"), [])
        self.assertEqual((await self.existing_run("foreign-running"))["state"], "interrupted")
        self.assertIsNotNone((await self.existing_run("foreign-cancelling"))["finished_at"])
        self.assertEqual((await self.existing_run("current-running"))["state"], "running")
        self.assertEqual((await self.existing_run("foreign-finished"))["state"], "succeeded")

    async def test_publish_result_atomically_links_message_report_and_response(self) -> None:
        chat_id, request_id = await self.new_run()
        await self.store.append_message(chat_id, request_id, "user", "What happened?", None, None, None)
        assistant, response = self.answered("Answer with needle")
        self.assertTrue(await self.store.publish_result(
            request_id, assistant=assistant, report=self.marked_report(), response=response,
            state="succeeded",
        ))
        run = await self.existing_run(request_id)
        self.assertEqual(run["state"], "succeeded")
        stored_response = run["response"]
        assert stored_response is not None
        self.assertEqual(stored_response["data"], response["data"])
        self.assertEqual(stored_response["report"]["id"], "report-1")
        self.assertIsNotNone(run["finished_at"])
        messages = await self.store.list_messages(chat_id)
        self.assertEqual([row["role"] for row in messages], ["user", "assistant"])
        self.assertEqual(messages[1]["report_id"], "report-1")
        self.assertEqual(messages[1]["reasoning"], "because")
        self.assertEqual(messages[1]["state"], "succeeded")
        report = await self.existing_report("report-1")
        self.assertEqual(report["args"], {"limit": 2, "category": "данные"})
        self.assertEqual(report["data"], [{"value": 12}, {"value": 13}])
        self.assertEqual(report["row_count"], 2)
        self.assertEqual(report["version"], 1)
        self.assertEqual((await self.store.list_reports(chat_id))[0]["id"], report["id"])
        self.assertEqual((await self.existing_chat(chat_id))["report_count"], 1)
        self.assertEqual([chat["id"] for chat in (await self.store.list_chats("NEEDLE"))[0]], [chat_id])
        self.assertEqual((await self.existing_chat(chat_id))["last_message_at"], messages[1]["created_at"])

    async def test_publish_failed_text_only_result_has_no_report(self) -> None:
        chat_id, request_id = await self.new_run()
        assistant, response = self.answered("Unavailable")
        self.assertTrue(await self.store.publish_result(
            request_id, assistant=assistant, report=None, response=response, state="failed",
        ))
        run = await self.existing_run(request_id)
        self.assertEqual(run["state"], "failed")
        stored_response = run["response"]
        assert stored_response is not None
        self.assertIsNone(stored_response["report"])
        self.assertEqual((await self.store.list_messages(chat_id))[0]["state"], "failed")
        self.assertEqual(await self.store.list_reports(chat_id), [])

    async def test_cancelled_run_rejects_late_publication_without_phantom_report(self) -> None:
        chat_id, request_id = await self.new_run()
        await self.store.finish_run(request_id, "cancelled", None, None)
        before = await self.store.get_run(request_id)
        assistant, response = self.answered()
        self.assertFalse(await self.store.publish_result(
            request_id, assistant=assistant, report=self.marked_report(),
            response=response, state="succeeded",
        ))
        self.assertEqual(await self.store.get_run(request_id), before)
        self.assertEqual(await self.rows("SELECT id FROM messages"), [])
        self.assertEqual(await self.rows("SELECT id FROM reports"), [])
        self.assertEqual(await self.store.list_reports(chat_id), [])
        self.assertFalse(await self.store.publish_result(
            "missing", assistant=assistant, report=None, response=response, state="failed",
        ))

    async def test_publish_report_insert_failure_rolls_back_message_and_run(self) -> None:
        chat_id, request_id = await self.new_run()
        await self.report(chat_id, "duplicate", False)
        before = await self.store.get_run(request_id)
        before_chat = await self.existing_chat(chat_id)
        assistant, response = self.answered("Uncommitted")
        with self.assertRaises(sqlite3.IntegrityError):
            await self.store.publish_result(
                request_id, assistant=assistant, report=self.marked_report("duplicate"),
                response=response, state="succeeded",
            )
        self.assertEqual(await self.store.get_run(request_id), before)
        self.assertEqual(await self.existing_chat(chat_id), before_chat)
        self.assertEqual(await self.rows("SELECT id FROM messages"), [])
        self.assertEqual(await self.rows("SELECT id FROM reports"), [("duplicate",)])
        self.assertTrue(await self.store.publish_result(
            request_id, assistant=assistant, report=self.marked_report("valid"),
            response=response, state="succeeded",
        ))

    async def test_non_json_report_data_fails_before_sql_transaction(self) -> None:
        _, request_id = await self.new_run()
        assert self.store.connection is not None
        statements: list[str] = []
        await self.store.connection.set_trace_callback(statements.append)
        assistant, response = self.answered()
        with self.assertRaises(TypeError):
            await self.store.publish_result(
                request_id, assistant=assistant,
                report=self.marked_report(data={"not_json": {1, 2}}),
                response=response, state="succeeded",
            )
        self.assertEqual(statements, [])
        self.assertEqual((await self.existing_run(request_id))["state"], "running")
        await self.store.connection.set_trace_callback(None)

    async def test_colliding_invalid_value_fails_before_sql_transaction(self) -> None:
        _, request_id = await self.new_run()
        assistant, response = self.answered()
        rows = [{date(2026, 10, 1): object(), "2026-10-01": 1}]
        assert self.store.connection is not None
        statements: list[str] = []
        await self.store.connection.set_trace_callback(statements.append)
        try:
            with self.assertRaises(TypeError):
                await self.store.publish_result(
                    request_id, assistant=assistant, report=self.marked_report(data=rows),
                    response=response, state="succeeded",
                )
            self.assertEqual(statements, [])
        finally:
            await self.store.connection.set_trace_callback(None)
        self.assertEqual((await self.existing_run(request_id))["state"], "running")

    async def test_invalid_dictionary_keys_fail_before_sql_transaction(self) -> None:
        _, request_id = await self.new_run()
        assistant, response = self.answered()
        assert self.store.connection is not None
        statements: list[str] = []
        await self.store.connection.set_trace_callback(statements.append)
        try:
            for key in (object(), (1, 2)):
                bad = {key: 1}
                operations = {
                    "finish": lambda: self.store.finish_run(
                        request_id, "succeeded", {"data": bad}, None),
                    "publish_data": lambda: self.store.publish_result(
                        request_id, assistant=assistant, report=self.marked_report(data=bad),
                        response=response, state="succeeded"),
                    "publish_args": lambda: self.store.publish_result(
                        request_id, assistant=assistant,
                        report={**self.marked_report(), "args": bad},
                        response=response, state="succeeded"),
                    "publish_response": lambda: self.store.publish_result(
                        request_id, assistant=assistant, report=None,
                        response={"data": bad}, state="succeeded"),
                    "update": lambda: self.store.replace_report_data("missing", bad, "now", 1),
                }
                for name, operation in operations.items():
                    with self.subTest(key=type(key).__name__, operation=name):
                        with self.assertRaises(TypeError):
                            await operation()
                        self.assertEqual(statements, [])
        finally:
            await self.store.connection.set_trace_callback(None)

    async def test_reports_saved_order_and_idempotent_bookmark(self) -> None:
        chat_id, request_id = await self.new_run()
        assistant, response = self.answered()
        self.assertTrue(await self.store.publish_result(
            request_id, assistant=assistant, report=self.marked_report("first"),
            response=response, state="succeeded",
        ))
        await self.store.create_run(chat_id, "second-run", "Q2", "boot")
        self.assertTrue(await self.store.publish_result(
            "second-run", assistant=assistant, report=self.marked_report("second"),
            response=response, state="succeeded",
        ))
        assert self.store.connection is not None
        await self.store.connection.execute(
            "UPDATE reports SET created_at=? WHERE id=?", ("2026-01-01T00:00:00Z", "first")
        )
        await self.store.connection.commit()
        self.assertEqual([r["id"] for r in await self.store.list_reports(chat_id)], ["second", "first"])
        self.assertEqual(await self.store.list_saved_reports(), [])
        first = await self.store.set_saved("first", True)
        self.assertNotIn("data", first)
        saved_at = first["saved_at"]
        self.assertIsNotNone(saved_at)
        self.assertEqual((await self.store.set_saved("first", True))["saved_at"], saved_at)
        await self.store.set_saved("second", True)
        await self.store.connection.execute(
            "UPDATE reports SET saved_at=? WHERE id=?", ("2026-01-01T00:00:00Z", "first")
        )
        await self.store.connection.commit()
        self.assertEqual([r["id"] for r in await self.store.list_saved_reports()], ["second", "first"])
        self.assertEqual((await self.store.set_saved("first", False))["saved_at"], None)
        self.assertIsNone((await self.store.set_saved("first", False))["saved_at"])
        self.assertEqual([r["id"] for r in await self.store.list_saved_reports()], ["second"])
        with self.assertRaises(ReportNotFound):
            await self.store.set_saved("missing", True)
        self.assertIsNone(await self.store.get_report("missing"))

    async def test_replace_report_data_version_row_count_and_stale_version(self) -> None:
        chat_id, request_id = await self.new_run()
        assistant, response = self.answered()
        await self.store.publish_result(
            request_id, assistant=assistant, report=self.marked_report(),
            response=response, state="succeeded",
        )
        old = await self.existing_report("report-1")
        updated = await self.store.replace_report_data(
            "report-1", [{"value": 400}], "2026-02-01T00:00:00Z", expected_version=1,
        )
        assert updated is not None
        self.assertEqual(updated["version"], 2)
        self.assertEqual(updated["row_count"], 1)
        self.assertEqual(updated["data"], [{"value": 400}])
        self.assertEqual(updated["generated_at"], "2026-02-01T00:00:00Z")
        self.assertEqual(updated["created_at"], old["created_at"])
        self.assertEqual(updated["saved_at"], old["saved_at"])
        self.assertIsNone(await self.store.replace_report_data(
            "report-1", [999], "2026-03-01T00:00:00Z", expected_version=1,
        ))
        self.assertIsNone(await self.store.replace_report_data(
            "missing", [999], "2026-03-01T00:00:00Z", expected_version=1,
        ))
        self.assertEqual(await self.store.get_report("report-1"), updated)
        self.assertEqual((await self.existing_chat(chat_id))["report_count"], 1)
        changed = await self.store.replace_report_data(
            "report-1", {"summary": "new"}, "2026-04-01T00:00:00Z", expected_version=2,
        )
        assert changed is not None
        self.assertIsNone(changed["row_count"])
        self.assertEqual(changed["data"], {"summary": "new"})

    async def test_saved_report_survives_chat_deletion_as_orphan(self) -> None:
        chat_id, request_id = await self.new_run()
        assistant, response = self.answered()
        await self.store.publish_result(
            request_id, assistant=assistant, report=self.marked_report(),
            response=response, state="succeeded",
        )
        await self.store.set_saved("report-1", True)
        await self.store.create_run(chat_id, "another", "Another", "boot")
        await self.store.publish_result(
            "another", assistant=assistant, report=self.marked_report("unsaved"),
            response=response, state="succeeded",
        )
        await self.store.delete_chat(chat_id)
        self.assertIsNone((await self.existing_report("report-1"))["chat_id"])
        self.assertEqual([card["id"] for card in await self.store.list_saved_reports()], ["report-1"])
        self.assertIsNone(await self.store.get_report("unsaved"))


class JsonStorageTests(unittest.TestCase):
    def test_collision_repro_rejects_unencodable_value(self):
        from chat_store import _dump_json
        rows = [{date(2026, 10, 1): object(), "2026-10-01": 1}]
        with self.assertRaises(ValueError):
            jsonable_encoder(rows)
        with self.assertRaises(TypeError):
            _dump_json(rows)

    def test_systematic_key_value_collision_parity(self):
        from chat_store import _dump_json

        class Key(Enum):
            LABEL = "text"
            INT = 7
            FLOAT = 1.25
            BOOL = True
            NULL = None

        @dataclass
        class Record:
            day: date

        class Model(BaseModel):
            count: int

        class Custom:
            def __init__(self):
                self.amount = Decimal("1.25")

        key_pairs = [
            ("str", "text", Key.LABEL), ("int", 7, Key.INT),
            ("float", 1.25, Key.FLOAT), ("bool", True, Key.BOOL),
            ("None", None, Key.NULL),
            ("date", date(2026, 10, 1), "2026-10-01"),
            ("datetime", datetime(2026, 10, 1, 12), "2026-10-01T12:00:00"),
            ("Decimal", Decimal("1.25"), Key.FLOAT),
            ("UUID", UUID(int=1), str(UUID(int=1))), ("Enum", Key.LABEL, "text"),
        ]
        encodable = {"record": Record(date(2026, 10, 1)), "model": Model(count=1),
                     "custom": Custom(), "enum": Key.INT, "bytes": b"rows",
                     "clock": time(12), "number": Decimal("1234.5678")}
        for (kind, key, twin), invalid, collision, nested in product(
            key_pairs, (False, True), (False, True), (False, True)
        ):
            value = object() if invalid else encodable
            data = {key: value, twin if collision else "other": 1}
            rows = [{"nested": [data]}] if nested else data
            with self.subTest(key=kind, invalid=invalid, collision=collision, nested=nested):
                try:
                    encoded = jsonable_encoder(rows)
                except (ValueError, TypeError):
                    with self.assertRaises(TypeError):
                        _dump_json(rows)
                else:
                    expected = json.dumps(encoded, ensure_ascii=False, allow_nan=False)
                    self.assertEqual(
                        json.loads(_dump_json(rows), object_pairs_hook=list),
                        json.loads(expected, object_pairs_hook=list),
                    )

    def test_dictionary_keys_match_installed_fastapi_oracle(self):
        from chat_store import _dump_json

        class Key(Enum):
            LABEL = "enum"
            NUMBER = 7

        keys = ["text", 7, 1.25, True, False, None, date(2026, 10, 1),
                datetime(2026, 10, 1, 12), time(12), Decimal("1.25"),
                Decimal("100000"), UUID(int=1), Key.LABEL, Key.NUMBER, b"rows"]
        cases: list[tuple[str, object]] = [
            (type(key).__name__ + ":" + repr(key), {key: Decimal("1.25")})
            for key in keys]
        cases.extend([
            ("nested", {"rows": [{date(2026, 10, 1): {
                UUID(int=1): [{Decimal("1.25"): datetime(2026, 10, 1, 12)}]}}]}),
            ("collision", {date(2026, 10, 1): 1, "2026-10-01": 2}),
            ("sqlalchemy_private", {"_sa_state": "private", "public": 1}),
        ])
        for label, rows in cases:
            with self.subTest(case=label):
                expected = json.loads(JSONResponse(jsonable_encoder(rows)).body)
                self.assertEqual(json.loads(_dump_json(rows)), expected)

    def test_rejected_dictionary_keys_remain_type_errors(self):
        from chat_store import _dump_json

        class Key(Enum):
            DECIMAL = Decimal("1.25")

        for key in (object(), (1, 2), Key.DECIMAL):
            with self.subTest(key=type(key).__name__):
                with self.assertRaises((ValueError, TypeError)):
                    JSONResponse(jsonable_encoder({key: 1}))
                with self.assertRaises(TypeError):
                    _dump_json({key: 1})

    def test_mysql_scalars_match_fastapi_and_keep_decimal_digits_numeric(self):
        from chat_store import _dump_json
        rows = [{"day": date(2026, 10, 1), "moment": datetime(2026, 10, 1, 12, 30),
                 "clock": time(12, 30), "amount": Decimal("1234.5678"),
                 "count": Decimal("100000"), "id": UUID(int=1), "label": b"rows",
                 "text": "данные", "nested": [None, True, {"n": 1}]}]
        encoded = _dump_json(rows)
        self.assertEqual(json.loads(encoded), jsonable_encoder(rows))
        self.assertIn("данные", encoded)
        data = json.loads(encoded)[0]
        self.assertEqual(str(data["amount"]), "1234.5678")
        self.assertEqual(str(data["count"]), "100000")
        self.assertIsInstance(data["amount"], float)
        self.assertIsInstance(data["count"], int)

    def test_arbitrary_objects_and_sets_remain_type_errors(self):
        from chat_store import _dump_json
        for value in (object(), {1, 2}):
            with self.subTest(value=type(value).__name__), self.assertRaises(TypeError):
                _dump_json({"bad": value})

    def test_nonfinite_numbers_reject_like_http_json(self):
        from chat_store import _dump_json
        for value in (float("nan"), float("inf"), -float("inf")):
            with self.subTest(value=value):
                encoded = jsonable_encoder({"bad": value})
                # FastAPI leaves floats alone; json.dumps defaults emit invalid
                # JSON tokens. Starlette's actual HTTP renderer rejects them.
                self.assertIn(json.dumps(encoded), ('{"bad": NaN}', '{"bad": Infinity}',
                                                    '{"bad": -Infinity}'))
                with self.assertRaises(ValueError):
                    JSONResponse(encoded)
                with self.assertRaises(ValueError):
                    _dump_json(encoded)


if __name__ == "__main__":
    unittest.main()
