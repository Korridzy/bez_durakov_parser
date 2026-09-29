"""HTTP contract for retained reports and model-free handle replay."""

import asyncio
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import AsyncMock, Mock, patch
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient

import main
from agent.registry import ToolRegistry
from chat_store import ChatStore


class SampleService:
    def __init__(self):
        self.calls: list[int] = []
        self.error: Exception | None = None

    def sample(self, value: int):
        """Return the current dataset value."""
        self.calls.append(value)
        if self.error is not None:
            raise self.error
        return [{"value": value}, {"value": value + 1}]


class UnusedAgent:
    def __init__(self):
        self.calls = 0

    async def process_user_request(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError("Update must not invoke the model")


class ReportFixture:
    def __init__(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = ChatStore(Path(self.temp.name) / "chats.db")
        self.old_globals = {
            name: getattr(main, name, None)
            for name in ("chat_store", "registry", "tool_service", "tool_registry", "agent_system")
        }
        self.service = SampleService()
        self.agent = UnusedAgent()

    async def setup(self):
        await self.store.setup()
        main.chat_store = self.store
        # A real registry exposes the same store used by the run submission path.
        from runs import RunRegistry
        main.registry = RunRegistry(self.store, runtime=lambda: main)
        main.tool_service = self.service
        main.tool_registry = ToolRegistry(self.service)
        main.agent_system = self.agent
        self.chat = (await self.store.create_chat("First"))["id"]
        self.other_chat = (await self.store.create_chat("Other"))["id"]
        self.report = await self.add_report(self.chat)

    async def close(self):
        for name, original in self.old_globals.items():
            setattr(main, name, original)
        await self.store.close()
        self.temp.cleanup()

    async def add_report(self, chat_id, *, created_at="2026-01-01T00:00:00Z", saved_at=None):
        report_id = uuid4().hex
        assert self.store.connection is not None
        await self.store.connection.execute(
            """INSERT INTO reports (id, chat_id, title, question, tool, args_json,
                                     data_json, row_count, generated_at, created_at, saved_at)
               VALUES (?, ?, 'Sample report', 'Original question', 'sample', ?, ?, 1, ?, ?, ?)""",
            (
                report_id, chat_id, json.dumps({"value": 7}),
                json.dumps([{"old": "yes"}]), "2025-01-01T00:00:00Z", created_at, saved_at,
            ),
        )
        await self.store.connection.commit()
        return report_id


class ReportRouteTests(unittest.TestCase):
    def setUp(self):
        self.fixture = ReportFixture()
        asyncio.run(self.fixture.setup())
        self.client = TestClient(main.app)
        self.addCleanup(self.client.close)
        self.addCleanup(lambda: asyncio.run(self.fixture.close()))

    def test_chat_reports_are_scoped_and_unknown_chat_is_404(self):
        other_report = asyncio.run(self.fixture.add_report(self.fixture.other_chat))
        response = self.client.get(f"/api/chats/{self.fixture.chat}/reports")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["id"] for item in response.json()], [self.fixture.report])
        self.assertNotIn(other_report, [item["id"] for item in response.json()])
        for missing in ("missing", "not-hex"):
            error = self.client.get(f"/api/chats/{missing}/reports")
            self.assertEqual(error.status_code, 404)
            self.assertEqual(error.json()["error"]["code"], "not_found")

    def test_get_report_and_non_hex_unknown_ids(self):
        report = self.client.get(f"/api/reports/{self.fixture.report}")
        self.assertEqual(report.status_code, 200)
        self.assertEqual(report.json()["data"], [{"old": "yes"}])
        self.assertEqual(report.json()["args"], {"value": 7})
        for missing in ("missing", "not-hex"):
            error = self.client.get(f"/api/reports/{missing}")
            self.assertEqual(error.status_code, 404)
            self.assertEqual(error.json()["error"]["code"], "not_found")

    def test_save_and_unsave_are_idempotent(self):
        path = f"/api/reports/{self.fixture.report}/saved"
        first = self.client.put(path, json={})
        self.assertEqual(first.status_code, 200)
        self.assertIsNotNone(first.json()["saved_at"])
        self.assertEqual(self.client.put(path, json={}).json(), first.json())
        self.assertEqual(self.client.get(f"/api/reports/{self.fixture.report}").json()["saved_at"], first.json()["saved_at"])
        self.assertEqual(self.client.delete(path).status_code, 204)
        self.assertEqual(self.client.delete(path).status_code, 204)
        self.assertIsNone(self.client.get(f"/api/reports/{self.fixture.report}").json()["saved_at"])
        for method in (self.client.put, self.client.delete):
            missing = method("/api/reports/not-hex/saved")
            self.assertEqual(missing.status_code, 404)
            self.assertEqual(missing.json()["error"]["code"], "not_found")

    def test_saved_reports_are_ordered_by_saved_at(self):
        newer = asyncio.run(self.fixture.add_report(self.fixture.other_chat, saved_at="2026-02-01T00:00:00Z"))
        older = asyncio.run(self.fixture.add_report(self.fixture.chat, saved_at="2026-01-01T00:00:00Z"))
        response = self.client.get("/api/saved-reports")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([card["id"] for card in response.json()], [newer, older])
        self.assertTrue(all("data" not in card for card in response.json()))

    def test_success_replays_handle_and_preserves_bookmark(self):
        path = f"/api/reports/{self.fixture.report}"
        self.client.put(f"{path}/saved", json={})
        before = self.client.get(path).json()
        response = self.client.post(f"{path}/update", json={})
        self.assertEqual(response.status_code, 200)
        after = response.json()
        self.assertEqual(after["version"], before["version"] + 1)
        self.assertNotEqual(after["generated_at"], before["generated_at"])
        self.assertTrue(after["generated_at"].endswith("Z"))
        self.assertEqual(after["row_count"], 2)
        self.assertEqual(after["data"], [{"value": 7}, {"value": 8}])
        self.assertEqual(after["saved_at"], before["saved_at"])
        self.assertEqual(self.client.get(path).json(), after)
        self.assertEqual(self.fixture.service.calls, [7])
        self.assertEqual(self.fixture.agent.calls, 0)

    def test_tool_error_keeps_report_and_502_body_byte_equal_to_get(self):
        path = f"/api/reports/{self.fixture.report}"
        before = self.client.get(path).content
        self.fixture.service.error = ValueError("source offline")
        with self.assertLogs("report_routes", level="WARNING") as captured:
            failure = self.client.post(f"{path}/update", json={})
        self.assertEqual(failure.status_code, 502)
        self.assertEqual(failure.json()["error"]["code"], "update_failed")
        self.assertIn("ToolError", failure.json()["error"]["message"])
        self.assertEqual(json.dumps(failure.json()["report"], ensure_ascii=False, separators=(",", ":")).encode(), before)
        self.assertEqual(self.client.get(path).content, before)
        self.assertTrue(any(self.fixture.report in entry for entry in captured.output))
        self.assertTrue(all("source offline" not in entry for entry in captured.output))
        self.assertEqual(self.fixture.agent.calls, 0)

    def test_unknown_update_is_404_even_without_tool_service(self):
        main.tool_service = None
        response = self.client.post("/api/reports/not-hex/update", json={})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()["error"]["code"], "not_found")

    def test_unavailable_tool_service_does_not_update(self):
        main.tool_service = None
        path = f"/api/reports/{self.fixture.report}"
        before = self.client.get(path).json()
        response = self.client.post(f"{path}/update", json={})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"]["code"], "tool_service_unavailable")
        self.assertEqual(self.client.get(path).json(), before)
        self.assertEqual(self.fixture.service.calls, [])

    def test_run_in_chat_blocks_update(self):
        path = f"/api/reports/{self.fixture.report}"
        before = self.client.get(path).json()
        asyncio.run(self.fixture.store.create_run(self.fixture.chat, uuid4().hex, "active", "boot"))
        response = self.client.post(f"{path}/update", json={})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error"]["code"], "report_busy")
        self.assertEqual(self.client.get(path).json(), before)
        self.assertEqual(self.fixture.service.calls, [])

    def test_saved_orphan_updates_without_an_originating_chat(self):
        path = f"/api/reports/{self.fixture.report}"
        asyncio.run(self.fixture.store.set_saved(self.fixture.report, True))
        asyncio.run(self.fixture.store.delete_chat(self.fixture.chat))
        before = self.client.get(path).json()
        self.assertIsNone(before["chat_id"])
        response = self.client.post(f"{path}/update", json={})
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json()["chat_id"])
        self.assertEqual(response.json()["version"], 2)

    def test_model_unavailable_does_not_disable_update(self):
        main.agent_system = None
        response = self.client.post(f"/api/reports/{self.fixture.report}/update", json={})
        self.assertEqual(response.status_code, 200)
        # Chat messages are owned by the parallel chat-routes lane; assert the 503
        # only once that route has been registered in the shared worktree.
        if "/api/chats/{chat_id}/messages" in main.app.openapi()["paths"]:
            with patch.object(main, "_recover_agent_system", return_value=None):
                failed = self.client.post(
                    f"/api/chats/{self.fixture.chat}/messages",
                    json={"request_id": uuid4().hex, "message": "Question"},
                )
            self.assertEqual(failed.status_code, 503)
            self.assertEqual(failed.json()["error"]["code"], "llm_proxy_unavailable")


class ConcurrentReportRouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fixture = ReportFixture()
        await self.fixture.setup()

    async def asyncTearDown(self):
        await self.fixture.close()

    async def test_startup_builds_tool_registry_even_when_model_probe_fails(self):
        engine = Mock()
        with (
            patch.object(main, "KNOWLEDGE_DIR", None),
            patch.object(main, "ARCHIVE_ENABLED", False),
            patch.object(main, "CHECKPOINT_DB_PATH", str(Path(self.fixture.temp.name) / "checkpoints.db")),
            patch.object(main, "CHATS_DB_PATH", str(Path(self.fixture.temp.name) / "startup-chats.db")),
            patch.object(main, "initialize_tool_service_with_retry", AsyncMock(
                return_value=(engine, self.fixture.service, ())
            )),
            patch.object(main, "probe_llm_proxy", AsyncMock(return_value=False)),
            patch.object(main, "rebuild_session_index", AsyncMock()),
        ):
            try:
                await main.startup_event()
                self.assertIsNone(main.agent_system)
                self.assertIsInstance(main.tool_registry, ToolRegistry)
                self.assertIs(main.tool_registry.service, self.fixture.service)
            finally:
                await main.shutdown_event()

    async def test_concurrent_update_rejects_second_without_waiting(self):
        started, release = asyncio.Event(), asyncio.Event()

        class BlockingRegistry:
            async def execute_response(self, tool, args):
                started.set()
                await release.wait()
                return [{"new": 10}]

        main.tool_registry = BlockingRegistry()
        path = f"/api/reports/{self.fixture.report}/update"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
            first = asyncio.create_task(client.post(path, json={}))
            try:
                await asyncio.wait_for(started.wait(), 5)

                async def second_and_release():
                    try:
                        return await client.post(path, json={})
                    finally:
                        release.set()

                responses = await asyncio.wait_for(asyncio.gather(first, second_and_release()), 5)
                self.assertEqual(sorted(response.status_code for response in responses), [200, 409])
                self.assertEqual(responses[1].json()["error"]["code"], "report_busy")
                self.assertEqual((await self.fixture.store.get_report(self.fixture.report))["version"], 2)
            finally:
                release.set()
                if not first.done():
                    await asyncio.wait_for(first, 5)

    async def test_timeout_with_late_to_thread_result_does_not_publish(self):
        started, release, finished = threading.Event(), threading.Event(), threading.Event()

        class BlockingService:
            def sample(self, value: int):
                """Wait for the test to allow the query to finish."""
                started.set()
                try:
                    if not release.wait(5):
                        raise RuntimeError("test worker was not released")
                    return [{"late": value}]
                finally:
                    finished.set()

        main.tool_registry = ToolRegistry(BlockingService())
        path = f"/api/reports/{self.fixture.report}"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
            before = (await client.get(path)).json()
            with patch("report_routes.AGENT_TIMEOUT_SECONDS", 0.05):
                request = asyncio.create_task(client.post(f"{path}/update", json={}))
                try:
                    self.assertTrue(await asyncio.wait_for(asyncio.to_thread(started.wait, 5), 6))
                    response = await asyncio.wait_for(request, 5)
                    self.assertEqual(response.status_code, 502)
                    self.assertEqual(response.json()["error"]["code"], "update_failed")
                    self.assertIn("TimeoutError", response.json()["error"]["message"])
                    self.assertEqual(response.json()["report"], before)
                    self.assertEqual((await client.get(path)).json(), before)
                    # Mimic a newer write winning while the old to_thread still runs.
                    newer = await self.fixture.store.replace_report_data(
                        self.fixture.report, [{"fresh": 1}], "2026-02-01T00:00:00Z", expected_version=1,
                    )
                    self.assertIsNotNone(newer)
                finally:
                    release.set()
                    self.assertTrue(await asyncio.wait_for(asyncio.to_thread(finished.wait, 5), 6))
                    if not request.done():
                        await asyncio.wait_for(request, 5)
            self.assertEqual((await client.get(path)).json(), newer)

    async def test_optimistic_conflict_after_external_write_is_409(self):
        started, release = asyncio.Event(), asyncio.Event()

        class BlockingRegistry:
            async def execute_response(self, tool, args):
                started.set()
                await release.wait()
                return [{"stale": True}]

        main.tool_registry = BlockingRegistry()
        path = f"/api/reports/{self.fixture.report}/update"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
            request = asyncio.create_task(client.post(path, json={}))
            try:
                await asyncio.wait_for(started.wait(), 5)
                fresh = await self.fixture.store.replace_report_data(
                    self.fixture.report, [{"newer": True}], "2026-02-01T00:00:00Z", expected_version=1,
                )
                release.set()
                response = await asyncio.wait_for(request, 5)
                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.json()["error"]["code"], "report_busy")
                self.assertEqual(await self.fixture.store.get_report(self.fixture.report), fresh)
            finally:
                release.set()
                if not request.done():
                    await asyncio.wait_for(request, 5)

    async def test_deleted_during_replay_is_404(self):
        started, release = asyncio.Event(), asyncio.Event()

        class BlockingRegistry:
            async def execute_response(self, tool, args):
                started.set()
                await release.wait()
                return [{"new": True}]

        main.tool_registry = BlockingRegistry()
        path = f"/api/reports/{self.fixture.report}/update"
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app), base_url="http://test") as client:
            request = asyncio.create_task(client.post(path, json={}))
            try:
                await asyncio.wait_for(started.wait(), 5)
                await self.fixture.store.delete_chat(self.fixture.chat)
                release.set()
                response = await asyncio.wait_for(request, 5)
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.json()["error"]["code"], "not_found")
                self.assertIsNone(await self.fixture.store.get_report(self.fixture.report))
            finally:
                release.set()
                if not request.done():
                    await asyncio.wait_for(request, 5)


if __name__ == "__main__":
    unittest.main()
