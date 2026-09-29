"""HTTP and startup contract for durable chat routes and the legacy wrapper."""
import asyncio
import importlib
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient

sys.path.insert(0, "/")


class FakeAgent:
    def __init__(self):
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()
        self.calls = []
        self.result = {
            "success": True, "data": [{"game": 1}], "message": "# Игры",
            "query_info": [{"tool": "list_games", "args": {"limit": 1}}],
            "timestamp": "2026-09-29T00:00:00Z", "reasoning": "шаг",
            "verdict": "in_scope", "report_handle": {"tool": "list_games", "args": {"limit": 1}},
        }

    async def head_messages(self, _chat_id):
        return []

    async def process_user_request(self, message, session_id, history=()):
        self.calls.append((message, session_id, history))
        self.started.set()
        await self.release.wait()
        return dict(self.result)


class FakeArchive:
    def __init__(self):
        self.rows = []
        self.completed = []

    async def begin(self, **kwargs):
        self.rows.append(kwargs)
        return len(self.rows)

    async def complete(self, row_id, result):
        self.completed.append((row_id, result))


class ChatRoutes(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.main = importlib.import_module("main")
        self.tmp = tempfile.TemporaryDirectory()
        self.saved = {name: getattr(self.main, name) for name in (
            "chat_store", "registry", "agent_system", "tool_service", "checkpoint_saver",
            "archive", "sessions", "pinned", "admission_lock",
        )}
        self.agent = FakeAgent()
        self.archive = FakeArchive()
        self.main.agent_system = self.agent
        self.main.tool_service = object()
        self.main.archive = self.archive
        self.main.checkpoint_saver = AsyncMock()
        self.main.sessions = importlib.import_module("session_store").SessionIndex(max_size=4)
        self.main.pinned = {}
        self.main.admission_lock = asyncio.Lock()
        await importlib.import_module("test_support").install_test_runtime(self.main, self.tmp.name)
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.main.app), base_url="http://test")

    async def asyncTearDown(self):
        await self.main.registry.shutdown()
        await self.client.aclose()
        await self.main.chat_store.close()
        for name, value in self.saved.items():
            setattr(self.main, name, value)
        self.tmp.cleanup()

    async def create(self):
        response = await self.client.post("/api/chats", json={})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["id"]

    async def finish(self, request_id):
        self.agent.release.set()
        return await asyncio.wait_for(self.main.registry.wait(request_id), 5)

    async def test_crud_search_pagination_and_validation(self):
        blank = await self.client.post("/api/chats", json={"title": "  \n  "})
        self.assertEqual(blank.status_code, 422)
        self.assertEqual((await self.client.post("/api/chats", json={"title": "x" * 200})).status_code, 422)
        created = await self.client.post("/api/chats", json={"title": "  Однажды  дважды "})
        self.assertEqual(created.status_code, 201)
        chat = created.json()
        self.assertEqual(chat["title"], "Однажды дважды")
        self.assertFalse(chat["auto_title"])
        self.assertEqual((await self.client.get("/api/chats", params={"q": "ОДНАЖДЫ"})).json()["items"][0]["id"], chat["id"])
        self.assertEqual((await self.client.get("/api/chats", params={"limit": 0})).status_code, 422)
        self.assertEqual((await self.client.get("/api/chats", params={"limit": 101})).status_code, 422)
        self.assertEqual((await self.client.get("/api/chats", params={"cursor": "broken"})).status_code, 422)
        self.assertEqual((await self.client.patch(f"/api/chats/{chat['id']}", json={"title": "y" * 200})).status_code, 422)
        renamed = await self.client.patch(f"/api/chats/{chat['id']}", json={"title": " Новый   заголовок "})
        self.assertEqual(renamed.json()["title"], "Новый заголовок")
        self.assertFalse(renamed.json()["auto_title"])
        self.assertEqual((await self.client.get("/api/chats", params={"q": "ОДНАЖДЫ"})).json()["items"], [])
        for _ in range(3):
            await self.create()
        first = (await self.client.get("/api/chats", params={"limit": 2})).json()
        second = (await self.client.get("/api/chats", params={"limit": 2, "cursor": first["next_cursor"]})).json()
        self.assertEqual(len({row["id"] for row in first["items"] + second["items"]}), 4)
        self.assertIsNone(second["next_cursor"])
        self.assertEqual((await self.client.delete(f"/api/chats/{chat['id']}")).status_code, 204)
        self.assertEqual((await self.client.get(f"/api/chats/{chat['id']}")).json()["error"]["code"], "not_found")
        self.assertEqual((await self.client.delete(f"/api/chats/{chat['id']}")).status_code, 404)
        self.assertEqual((await self.client.patch("/api/chats/unknown", json={"title": "x"})).status_code, 404)

    async def test_run_status_report_conflicts_and_recovery(self):
        chat_id = await self.create()
        request_id = uuid4().hex
        self.agent.release.clear()
        url = f"/api/chats/{chat_id}/messages"
        payload = {"request_id": request_id, "message": "покажи игры"}
        run = await self.client.post(url, json=payload)
        self.assertEqual((run.status_code, run.json()["state"]), (202, "running"))
        await asyncio.wait_for(self.agent.started.wait(), 5)
        self.assertEqual((await self.client.post(url, json=payload)).status_code, 200)
        for different in ({"request_id": request_id, "message": "другой"},
                          {"request_id": uuid4().hex, "message": "другой"}):
            conflict = await self.client.post(url, json=different)
            self.assertEqual(conflict.status_code, 409)
            self.assertEqual(conflict.json()["error"]["code"],
                             "request_conflict" if different["request_id"] == request_id else "chat_busy")
        other = await self.create()
        self.assertEqual((await self.client.post(f"/api/chats/{other}/messages", json=payload)).json()["error"]["code"], "request_conflict")
        self.assertEqual((await self.client.delete(f"/api/chats/{chat_id}")).json()["error"]["code"], "chat_busy")
        self.assertEqual((await self.client.post(f"/api/clear/{chat_id}")).status_code, 409)
        self.assertEqual((await self.client.get(f"/api/chats/{chat_id}/status")).json()["active_run"]["request_id"], request_id)
        finished = await self.finish(request_id)
        self.assertEqual(finished["state"], "succeeded")
        self.assertIsNone((await self.client.get(f"/api/runs/{request_id}")).json()["response"]["data"])
        detail = (await self.client.get(f"/api/chats/{chat_id}")).json()
        self.assertEqual(detail["reports"][0]["id"], detail["messages"][-1]["report_id"])
        self.assertEqual(detail["last_run"]["response"]["report"], detail["reports"][0])
        self.assertEqual(detail["chat"]["title"], "покажи игры")
        self.assertEqual((await self.client.get(f"/api/chats/{chat_id}/status")).json()["last_run"]["state"], "succeeded")
        self.assertEqual((await self.client.post(url, json=payload)).status_code, 200)
        cleared = await self.client.post(f"/api/clear/{chat_id}")
        self.assertEqual(cleared.status_code, 200)
        detail = (await self.client.get(f"/api/chats/{chat_id}")).json()
        self.assertEqual(detail["messages"], [])
        self.assertEqual(len(detail["reports"]), 1)
        self.assertIsNone(detail["chat"]["last_message_at"])
        self.assertEqual((await self.client.get(f"/api/runs/{request_id}")).status_code, 404)

    async def test_identical_retry_survives_model_and_tool_outages(self):
        chat_id = await self.create()
        other = await self.create()
        request_id = uuid4().hex
        payload = {"request_id": request_id, "message": "покажи игры"}
        self.agent.release.clear()
        url = f"/api/chats/{chat_id}/messages"
        first = await self.client.post(url, json=payload)
        self.assertEqual(first.status_code, 202)
        await asyncio.wait_for(self.agent.started.wait(), 5)
        self.main.agent_system = None
        self.main.tool_service = None
        with patch.object(self.main, "_recover_agent_system", new=AsyncMock(return_value=None)) as recover:
            retry = await self.client.post(url, json=payload)
            changed = await self.client.post(url, json={**payload, "message": "другой"})
            foreign = await self.client.post(f"/api/chats/{other}/messages", json=payload)
            self.assertEqual((retry.status_code, retry.json()["request_id"]), (200, request_id))
            self.assertEqual(changed.json()["error"]["code"], "request_conflict")
            self.assertEqual(foreign.json()["error"]["code"], "request_conflict")
            recover.assert_not_awaited()
        self.assertEqual(len(await self.main.chat_store.list_messages(chat_id)), 1)
        self.assertEqual(self.archive.rows[0]["session_id"], chat_id)
        self.main.agent_system = self.agent
        self.main.tool_service = object()
        await self.finish(request_id)
        self.main.agent_system = None
        with patch.object(self.main, "_recover_agent_system", new=AsyncMock(return_value=None)) as recover:
            terminal = await self.client.post(url, json=payload)
            self.assertEqual((terminal.status_code, terminal.json()["state"]), (200, "succeeded"))
            fresh = await self.client.post(url, json={"request_id": uuid4().hex, "message": "fresh"})
            self.assertEqual((fresh.status_code, fresh.json()["error"]["code"]), (503, "llm_proxy_unavailable"))
            recover.assert_awaited_once_with()

    async def test_retry_cleared_after_lookup_creates_new_run_with_202(self):
        chat_id = await self.create()
        request_id = uuid4().hex
        url = f"/api/chats/{chat_id}/messages"
        payload = {"request_id": request_id, "message": "same text"}
        first = await self.client.post(url, json=payload)
        self.assertEqual(first.status_code, 202)
        self.assertEqual((await asyncio.wait_for(self.main.registry.wait(request_id), 5))["state"], "succeeded")
        entered, resume = asyncio.Event(), asyncio.Event()
        original = self.main.registry.submit

        async def paused(*args, **kwargs):
            entered.set()
            await resume.wait()
            return await original(*args, **kwargs)

        self.main.registry.submit = paused
        try:
            repeat = asyncio.create_task(self.client.post(url, json=payload))
            await asyncio.wait_for(entered.wait(), 5)
            cleared = await self.client.post(f"/api/clear/{chat_id}")
            self.assertEqual(cleared.status_code, 200)
            self.assertIsNone(await self.main.chat_store.get_run(request_id))
            resume.set()
            fresh = await asyncio.wait_for(repeat, 5)
            self.assertEqual((fresh.status_code, fresh.json()["state"]), (202, "running"))
            self.assertEqual((await asyncio.wait_for(self.main.registry.wait(request_id), 5))["state"], "succeeded")
            self.assertEqual([m["role"] for m in await self.main.chat_store.list_messages(chat_id)],
                             ["user", "assistant"])
        finally:
            resume.set()
            self.main.registry.submit = original

    async def test_retry_after_cancel_is_existing_and_after_delete_is_not_found(self):
        chat_id = await self.create()
        request_id = uuid4().hex
        url = f"/api/chats/{chat_id}/messages"
        payload = {"request_id": request_id, "message": "cancel this"}
        self.agent.release.clear()
        first = await self.client.post(url, json=payload)
        self.assertEqual(first.status_code, 202)
        await asyncio.wait_for(self.agent.started.wait(), 5)
        changed, resume = asyncio.Event(), asyncio.Event()
        original = self.main.chat_store.set_run_state

        async def paused(*args):
            await original(*args)
            changed.set()
            await resume.wait()

        self.main.chat_store.set_run_state = paused
        try:
            cancelling_task = asyncio.create_task(self.client.post(
                f"/api/chats/{chat_id}/cancel", json={"request_id": request_id}))
            await asyncio.wait_for(changed.wait(), 5)
            retry = await self.client.post(url, json=payload)
            self.assertEqual((retry.status_code, retry.json()["state"]), (200, "cancelling"))
        finally:
            resume.set()
            self.main.chat_store.set_run_state = original
        cancelling = await asyncio.wait_for(cancelling_task, 5)
        self.assertEqual(cancelling.status_code, 202)
        self.assertEqual((await asyncio.wait_for(self.main.registry.wait(request_id), 5))["state"], "cancelled")
        terminal = await self.client.post(url, json=payload)
        self.assertEqual((terminal.status_code, terminal.json()["state"]), (200, "cancelled"))
        self.assertEqual(len(await self.main.chat_store.list_messages(chat_id)), 2)
        self.assertEqual(len(self.archive.rows), 1)
        self.assertEqual((await self.client.delete(f"/api/chats/{chat_id}")).status_code, 204)
        missing = await self.client.post(url, json=payload)
        self.assertEqual((missing.status_code, missing.json()["error"]["code"]), (404, "not_found"))

    async def test_delete_during_admitted_submit_is_busy(self):
        chat_id = await self.create()
        request_id = uuid4().hex
        entered, release = asyncio.Event(), asyncio.Event()
        original = self.main.chat_store.create_run

        async def paused(*args, **kwargs):
            entered.set()
            await release.wait()
            return await original(*args, **kwargs)

        self.main.chat_store.create_run = paused
        try:
            submitting = asyncio.create_task(self.client.post(
                f"/api/chats/{chat_id}/messages", json={"request_id": request_id, "message": "valid"}))
            await asyncio.wait_for(entered.wait(), 5)
            deletion = await self.client.delete(f"/api/chats/{chat_id}")
            self.assertEqual((deletion.status_code, deletion.json()["error"]["code"]), (409, "chat_busy"))
            release.set()
            submitted = await asyncio.wait_for(submitting, 5)
            self.assertEqual(submitted.status_code, 202)
            await self.finish(request_id)
            self.assertEqual(self.main.pinned, {})
        finally:
            release.set()
            self.main.chat_store.create_run = original

    async def test_chat_disappearing_during_submit_returns_not_found(self):
        chat_id = await self.create()
        request_id = uuid4().hex
        entered, release = asyncio.Event(), asyncio.Event()
        original = self.main.chat_store.create_run

        async def paused(*args, **kwargs):
            entered.set()
            await release.wait()
            return await original(*args, **kwargs)

        self.main.chat_store.create_run = paused
        try:
            submitting = asyncio.create_task(self.client.post(
                f"/api/chats/{chat_id}/messages", json={"request_id": request_id, "message": "valid"}))
            await asyncio.wait_for(entered.wait(), 5)
            # Simulate another store writer removing the chat after admission,
            # bypassing the HTTP route's pending-pin guard.
            await self.main.chat_store.delete_chat(chat_id)
            release.set()
            missing = await asyncio.wait_for(submitting, 5)
            self.assertEqual((missing.status_code, missing.json()["error"]["code"]), (404, "not_found"))
            self.assertIsNone(await self.main.chat_store.get_run(request_id))
            self.assertEqual(self.main.pinned, {})
        finally:
            release.set()
            self.main.chat_store.create_run = original

    async def test_large_nonblank_message_is_accepted(self):
        chat_id = await self.create()
        request_id = uuid4().hex
        message = "x" * 200000
        response = await self.client.post(f"/api/chats/{chat_id}/messages", json={
            "request_id": request_id, "message": message})
        self.assertEqual(response.status_code, 202, response.text[:200])
        self.assertEqual((await self.finish(request_id))["state"], "succeeded")
        self.assertEqual((await self.main.chat_store.list_messages(chat_id))[0]["content"], message)

    async def test_concurrent_identical_send_returns_202_then_200(self):
        chat_id = await self.create()
        request_id = uuid4().hex
        self.agent.release.clear()
        entered, release = asyncio.Event(), asyncio.Event()
        original = self.main.chat_store.create_run

        async def paused(*args, **kwargs):
            if args[1] == request_id:
                entered.set()
                await release.wait()
            return await original(*args, **kwargs)

        self.main.chat_store.create_run = paused
        payload = {"request_id": request_id, "message": "покажи игры"}
        locks = importlib.import_module("chat_routes")._submission_locks
        waiting = asyncio.Event()

        class ObservedLock:
            def __init__(self):
                self.lock = asyncio.Lock()

            async def __aenter__(self):
                if self.lock.locked():
                    waiting.set()
                await self.lock.acquire()

            async def __aexit__(self, *_):
                self.lock.release()

        observed = ObservedLock()
        locks[request_id] = observed
        try:
            first = asyncio.create_task(self.client.post(f"/api/chats/{chat_id}/messages", json=payload))
            await asyncio.wait_for(entered.wait(), 5)
            second = asyncio.create_task(self.client.post(f"/api/chats/{chat_id}/messages", json=payload))
            await asyncio.wait_for(waiting.wait(), 5)
            release.set()
            responses = await asyncio.wait_for(asyncio.gather(first, second), 5)
            self.assertEqual(sorted(response.status_code for response in responses), [200, 202])
            self.assertEqual({response.json()["request_id"] for response in responses}, {request_id})
        finally:
            release.set()
            self.main.chat_store.create_run = original
            locks.pop(request_id, None)
        await self.finish(request_id)
        self.assertEqual(len(self.archive.rows), 1)

    async def test_cancel_then_send_and_shutdown(self):
        chat_id = await self.create()
        self.agent.release.clear()
        first = uuid4().hex
        await self.client.post(f"/api/chats/{chat_id}/messages", json={"request_id": first, "message": "one"})
        await asyncio.wait_for(self.agent.started.wait(), 5)
        cancelled = await self.client.post(f"/api/chats/{chat_id}/cancel", json={"request_id": first})
        self.assertEqual((cancelled.status_code, cancelled.json()["state"]), (202, "cancelling"))
        done = await asyncio.wait_for(self.main.registry.wait(first), 5)
        self.assertEqual(done["state"], "cancelled")
        self.assertEqual((await self.client.post(f"/api/chats/{chat_id}/cancel", json={"request_id": first})).status_code, 200)
        self.assertEqual((await self.client.post(f"/api/chats/{chat_id}/cancel", json={"request_id": uuid4().hex})).status_code, 404)
        self.agent.started.clear()
        second = uuid4().hex
        await self.client.post(f"/api/chats/{chat_id}/messages", json={"request_id": second, "message": "two"})
        await asyncio.wait_for(self.agent.started.wait(), 5)
        await asyncio.wait_for(self.main.registry.shutdown(), 5)
        self.assertEqual((await self.main.chat_store.get_run(second))["state"], "interrupted")
        self.assertEqual(self.main.pinned, {})

    async def test_overload_does_not_insert_a_run_or_message(self):
        chat_id = await self.create()
        self.main.sessions = importlib.import_module("session_store").SessionIndex(max_size=1)
        await self.main.sessions.touch("occupied")
        self.main.pinned["occupied"] = 1
        result = await self.client.post(f"/api/chats/{chat_id}/messages", json={
            "request_id": uuid4().hex, "message": "покажи игры"})
        self.assertEqual((result.status_code, result.json()["error"]["code"]), (503, "overloaded"))
        self.assertEqual((await self.client.get(f"/api/chats/{chat_id}")).json()["messages"], [])
        self.assertEqual(self.archive.rows, [])
        self.main.pinned.clear()

    async def test_no_rows_for_rejections_and_404_envelopes(self):
        unknown = f"/api/chats/{uuid4().hex}"
        self.assertEqual((await self.client.post(unknown + "/messages", json={"request_id": uuid4().hex, "message": "x"})).json()["error"]["code"], "not_found")
        self.assertEqual((await self.client.get("/api/runs/unknown")).status_code, 404)
        chat = await self.create()
        url = f"/api/chats/{chat}/messages"
        for payload in ({"request_id": "abc", "message": "x"},
                        {"request_id": uuid4().hex.upper(), "message": "x"},
                        {"request_id": uuid4().hex, "message": "  \n "}):
            result = await self.client.post(url, json=payload)
            self.assertEqual((result.status_code, result.json()["error"]["code"]), (422, "invalid_request"))
        self.main.tool_service = None
        unavailable = await self.client.post(url, json={"request_id": uuid4().hex, "message": "hello"})
        self.assertEqual((unavailable.status_code, unavailable.json()["error"]["code"]), (503, "tool_service_unavailable"))
        self.main.tool_service = object()
        self.main.agent_system = None
        with patch.object(self.main, "_recover_agent_system", new=AsyncMock(return_value=None)) as recover:
            unavailable = await self.client.post(url, json={"request_id": uuid4().hex, "message": "hello"})
        recover.assert_awaited_once_with()
        self.assertEqual((unavailable.status_code, unavailable.json()["error"]["code"]), (503, "llm_proxy_unavailable"))
        self.assertEqual((await self.client.get(f"/api/chats/{chat}")).json()["messages"], [])
        self.assertEqual(self.archive.rows, [])

    async def test_legacy_overload_creates_no_chat_or_archive_row(self):
        self.main.sessions = importlib.import_module("session_store").SessionIndex(max_size=1)
        await self.main.sessions.touch("occupied")
        self.main.pinned["occupied"] = 1
        denied = await self.client.post("/api/chat", json={
            "session_id": "overloaded-legacy", "message": "покажи игры"})
        self.assertEqual((denied.status_code, denied.json()["detail"]),
                         (503, "Сервер перегружен, повторите позже"))
        self.assertIsNone(await self.main.chat_store.get_chat("overloaded-legacy"))
        self.assertEqual(self.archive.rows, [])
        self.main.pinned.clear()

    async def test_legacy_envelopes_and_cancellation(self):
        normal = await self.client.post("/api/chat", json={"message": "games", "session_id": "legacy-id"})
        self.assertEqual(normal.status_code, 200)
        body = normal.json()
        self.assertEqual(body["session_id"], "legacy-id")
        self.assertEqual(body["data"], [{"game": 1}])
        self.assertEqual(body["report"]["question"], "games")
        self.assertEqual(body["scope_verdict"], "in_scope")
        self.main.agent_system = None
        self.main.checkpoint_saver = None
        with patch.object(self.main, "_recover_agent_system", new=AsyncMock(return_value=None)):
            unavailable = await self.client.post("/api/chat", json={"message": "no model"})
        self.assertEqual(unavailable.status_code, 503)
        self.assertEqual(unavailable.json()["error"], "llm_proxy_unavailable")
        self.assertIsNone(await self.main.chat_store.get_chat(unavailable.json()["session_id"]))
        self.main.checkpoint_saver = AsyncMock()
        self.main.agent_system = self.agent
        self.agent.started.clear()
        self.agent.release.clear()
        running = asyncio.create_task(self.client.post("/api/chat", json={"message": "held", "session_id": "legacy-id"}))
        await asyncio.wait_for(self.agent.started.wait(), 5)
        busy = await self.client.post("/api/chat", json={"message": "another", "session_id": "legacy-id"})
        self.assertEqual((busy.status_code, busy.json()["detail"]), (409, "Чат занят, дождитесь ответа"))
        running.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await running
        self.assertEqual(self.main.pinned, {})
        self.assertEqual((await self.main.chat_store.last_run("legacy-id"))["state"], "cancelled")


STARTUP_PROBE = """\
import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch
from uuid import uuid4
import main
from chat_store import ChatStore

async def probe():
    old = ChatStore(main.CHATS_DB_PATH)
    await old.setup()
    chat = await old.create_chat()
    request_id = uuid4().hex
    await old.create_run(chat['id'], request_id, 'old question', 'foreign-boot', with_user_message=True)
    await old.close()
    order = []
    original_setup = ChatStore.setup
    original_sweep = main.RunRegistry.sweep_on_startup
    original_index = main.rebuild_session_index
    async def setup(store):
        assert main.checkpoint_saver is not None
        assert main.archive.connection is not None
        order.append('store')
        await original_setup(store)
    async def sweep(registry):
        assert registry.store.connection is not None
        order.append('sweep')
        await original_sweep(registry)
    async def index():
        order.append('index')
        await original_index()
    with patch.object(main, 'initialize_tool_service_with_retry', new=AsyncMock(return_value=(None, object(), ()))), \\
         patch.object(main, 'probe_llm_proxy', new=AsyncMock(return_value=True)), \\
         patch.object(main, '_build_agent_system', return_value=object()), \\
         patch.object(ChatStore, 'setup', new=setup), \\
         patch.object(main.RunRegistry, 'sweep_on_startup', new=sweep), \\
         patch.object(main, 'rebuild_session_index', new=index):
        await main.startup_event()
    assert order == ['store', 'sweep', 'index'], order
    run = await main.chat_store.get_run(request_id)
    assert run['state'] == 'interrupted', run
    messages = await main.chat_store.list_messages(chat['id'])
    assert messages[-1]['content'] == 'Ответ прерван перезапуском сервера', messages
    await main.shutdown_event()
    assert main.chat_store is None or main.chat_store.connection is None
    print('startup swept foreign run, ordered store before index and closed it')
    original_connect = main.aiosqlite.connect
    checkpoint = []
    async def connect(*args, **kwargs):
        connection = await original_connect(*args, **kwargs)
        checkpoint.append(connection)
        return connection
    async def broken_setup(store):
        assert main.checkpoint_saver is not None
        raise OSError('chat store unavailable')
    with patch.object(main, 'initialize_tool_service_with_retry', new=AsyncMock(return_value=(None, object(), ()))), \\
         patch.object(main, 'aiosqlite', main.aiosqlite), \\
         patch.object(main.aiosqlite, 'connect', new=connect), \\
         patch.object(ChatStore, 'setup', new=broken_setup):
        try:
            await main.startup_event()
        except OSError as error:
            assert str(error) == 'chat store unavailable', error
        else:
            raise AssertionError('store failure did not abort startup')
    assert main.checkpoint_connection is None and main.checkpoint_saver is None
    assert checkpoint and checkpoint[0]._running is False, checkpoint
    print('chat store setup failure closed checkpoint')

asyncio.run(probe())
"""


class ChatValidationClient(unittest.TestCase):
    def test_framework_validation_stays_in_fastapi_detail_shape(self):
        main = importlib.import_module("main")
        client = TestClient(main.app)
        try:
            response = client.post("/api/chats", json={"title": 42})
            self.assertEqual(response.status_code, 422)
            self.assertIsInstance(response.json()["detail"], list)
        finally:
            client.close()


class StartupChatTests(unittest.TestCase):
    def test_real_startup_sweeps_and_closes_checkpoint_on_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            probe = Path(directory) / "chat_startup_probe.py"
            probe.write_text(STARTUP_PROBE, encoding="utf-8")
            config = Path(directory) / "config.toml"
            config.write_text(Path("/bd_shared/test_config.toml").read_text(encoding="utf-8").replace(
                "[webreport]\n", "[webreport]\narchive_enabled = true\n", 1), encoding="utf-8")
            environment = {**os.environ, "BD_CONFIG_FILE": str(config),
                           "BD_ARCHIVE_DB_PATH": str(Path(directory) / "archive.db"),
                           "BD_CHECKPOINT_DB_PATH": str(Path(directory) / "checkpoint.db"),
                           "BD_CHATS_DB_PATH": str(Path(directory) / "chats.db"),
                           "PYTHONPATH": os.pathsep.join(("/", str(Path(__file__).parent)))}
            environment.pop("BD_CONFIG_LOCAL_FILE", None)
            result = subprocess.run([sys.executable, str(probe)], env=environment,
                                    capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("chat store setup failure closed checkpoint", result.stdout)


if __name__ == "__main__":
    unittest.main()
