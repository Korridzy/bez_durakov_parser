"""Offline contracts for project isolation, secrets, provider data and resumable jobs."""

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import httpx
from fastapi import FastAPI

from connectors.http import ConnectorError
from connectors.metrika import Metrika, period
from connectors.providers import GA4, Amplitude, Mixpanel
from connectors.service import AnalyticsService
from workspace.store import WorkspaceStore


class StoreTests(unittest.TestCase):
    def test_source_settings_survive_restart_without_exposing_credentials(self):
        from connectors.catalog import CATALOG

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "workspace.json"
            store = WorkspaceStore(path)
            for provider in CATALOG:
                config = {
                    f["key"]: "private-synthetic" if f["secret"] else "123"
                    for f in provider["fields"]
                }
                config["unexpected_token"] = "private-synthetic"
                source = store.add(
                    "sources",
                    {"project_id": "test", "provider": provider["id"], "metadata": {}},
                )
                store.save_secret("sources", source["id"], config, False)
            self.assertNotIn("private-synthetic", path.read_text())
            restored = WorkspaceStore(path)
            for source in restored.snapshot()["sources"]:
                public = restored.public(source)
                self.assertEqual(public["connection_status"], "reconnect")
                self.assertFalse(public["has_credentials"])
                self.assertNotIn("private-synthetic", repr(public))
                self.assertNotIn("unexpected_token", public["config"])
                self.assertEqual(
                    public["config"],
                    {
                        f["key"]: "123"
                        for p in CATALOG
                        if p["id"] == source["provider"]
                        for f in p["fields"]
                        if not f["secret"]
                    },
                )

    def test_legacy_source_settings_are_recovered_from_metadata_and_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            store = WorkspaceStore(Path(directory) / "workspace.json")
            source = store.add(
                "sources",
                {
                    "project_id": "test",
                    "provider": "metrika",
                    "metadata": {"counter_id": "123"},
                },
            )
            self.assertEqual(store.public(source)["config"], {"counter_id": "123"})
            store.temporary_secrets[source["id"]] = {
                "counter_id": "456",
                "token": "private-synthetic",
            }
            self.assertEqual(store.public(source)["config"], {"counter_id": "456"})
            self.assertTrue(store.public(source)["has_credentials"])

    def test_persisted_keys_are_encrypted_and_session_keys_expire(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "workspace.json"
            store = WorkspaceStore(path)
            first = store.add("sources", {"name": "Saved"})
            second = store.add("sources", {"name": "Session"})
            store.save_secret(
                "sources", first["id"], {"token": "synthetic-private-token"}, True
            )
            store.save_secret(
                "sources", second["id"], {"token": "synthetic-session-token"}, False
            )
            self.assertNotIn("synthetic", path.read_text())
            restored = WorkspaceStore(path)
            self.assertEqual(
                restored.secret(restored.get("sources", first["id"]))["token"],
                "synthetic-private-token",
            )
            self.assertIsNone(restored.secret(restored.get("sources", second["id"])))
            self.assertNotIn(
                "encrypted", restored.public(restored.get("sources", first["id"]))
            )

    def test_interrupted_request_is_not_silently_running_after_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "workspace.json"
            store = WorkspaceStore(path)
            job = store.add("jobs", {"status": "running"})
            restored = WorkspaceStore(path)
            self.assertEqual(restored.get("jobs", job["id"])["status"], "interrupted")


class ConnectorTests(unittest.TestCase):
    def test_counter_scope_and_sampling_survive_query(self):
        client = Metrika({"counter_id": "123", "token": "synthetic"})
        with patch(
            "connectors.metrika.request_json",
            return_value={
                "data": [{"dimensions": [{"name": "Поиск"}], "metrics": [12, 19]}],
                "totals": [30, 50],
                "sampled": True,
                "sample_share": 0.5,
                "total_rows": 7,
            },
        ) as request:
            result = client.query(
                "2026-08-01", "2026-08-07", dimensions="ym:s:lastTrafficSource"
            )
            self.assertEqual(request.call_args.kwargs["params"]["ids"], "123")
            self.assertEqual(result["rows"][0]["ym:s:lastTrafficSource"], "Поиск")
            self.assertEqual(result["sample_share"], 0.5)
            self.assertEqual(result["total_rows"], 7)
            self.assertNotIn("synthetic", repr(result))

    def test_metrika_overview_uses_period_uniques_not_sum_of_daily_uniques(self):
        client = Metrika({"counter_id": "123", "token": "synthetic"})
        with (
            patch.object(
                client,
                "query",
                return_value={
                    "totals": [15, 25, 50, 10],
                    "sampled": False,
                    "sample_share": 1,
                },
            ),
            patch.object(
                client,
                "_get",
                return_value={
                    "data": [{"metrics": [[10, 11], [12, 13], [20, 30]]}],
                    "time_intervals": [
                        ["2026-08-01", "2026-08-01"],
                        ["2026-08-02", "2026-08-02"],
                    ],
                },
            ),
        ):
            result = client.overview("2026-08-01", "2026-08-02")
            self.assertEqual(result["metrics"][0]["value"], 15)
            self.assertEqual(sum(r["users"] for r in result["series"]), 21)

    def test_project_cannot_query_another_projects_source(self):
        read = Mock()
        service = AnalyticsService(
            [{"id": "mine", "provider": "metrika", "name": "A"}], {}, read
        )
        with self.assertRaises(ConnectorError):
            service.analytics_report("theirs", "overview")
        read.assert_not_called()

    def test_query_and_date_bounds_are_enforced_before_network(self):
        with self.assertRaises(ConnectorError):
            period("2020-01-01", "2026-01-01")
        client = Metrika({"counter_id": "123", "token": "synthetic"})
        for args in (
            {"limit": 9999},
            {"metrics": "ym:s:users&ids=other"},
            {"date_from": "bad"},
        ):
            if "date_from" in args:
                continue
            with self.assertRaises(ConnectorError):
                client.query("2026-08-01", "2026-08-07", **args)

    def test_amplitude_averages_daily_users(self):
        client = Amplitude({"api_key": "fake", "secret_key": "fake", "region": "EU"})
        with patch.object(
            client,
            "_query",
            return_value={
                "series": [[10, 30]],
                "xValues": ["2026-08-01", "2026-08-02"],
            },
        ):
            result = client.overview("2026-08-01", "2026-08-02")
            self.assertEqual(result["metrics"][0]["value"], 20)

    def test_ga4_bounce_rate_is_a_fraction_and_dates_are_normalized(self):
        client = GA4({"property_id": "123"})
        with patch.object(
            client,
            "_query",
            side_effect=[
                {
                    "rows": [
                        {
                            "metricValues": [
                                {"value": "5"},
                                {"value": "8"},
                                {"value": "12"},
                                {"value": "0.25"},
                            ]
                        }
                    ]
                },
                {
                    "rows": [
                        {
                            "dimensionValues": [{"value": "20260801"}],
                            "metricValues": [
                                {"value": "5"},
                                {"value": "8"},
                                {"value": "12"},
                            ],
                        }
                    ]
                },
            ],
        ):
            result = client.overview("2026-08-01", "2026-08-02")
            self.assertEqual(result["metrics"][3]["value"], 25)
            self.assertEqual(result["series"][0]["date"], "2026-08-01")

    def test_metrika_page_offsets_and_goal_batches_are_bounded(self):
        client = Metrika({"counter_id": "123", "token": "synthetic"})
        with (
            patch.object(
                client,
                "_get",
                return_value={"goals": [{"id": n, "name": str(n)} for n in range(65)]},
            ),
            patch.object(
                client, "query", side_effect=[{"totals": [1] * 10}, {"totals": [1] * 5}]
            ) as query,
        ):
            report = client.report("goals", "2026-08-01", "2026-08-07", page=2)
            self.assertEqual(len(report["rows"]), 15)
            self.assertEqual(report["rows"][0]["ID"], 50)
            self.assertFalse(report["has_more"])
            self.assertEqual(query.call_count, 2)

    def test_mixpanel_uses_requested_dates_and_labels_bounded_coverage(self):
        client = Mixpanel({"project_id": "123", "region": "US"})
        with patch.object(
            client,
            "_query",
            side_effect=[
                ["a", "b"],
                {"data": {"values": {"a": {"2026-08-01": 3}, "b": {"2026-08-01": 4}}}},
            ],
        ) as query:
            report = client.overview("2026-08-01", "2026-08-07")
            self.assertEqual(report["metrics"][0]["value"], 7)
            self.assertEqual(query.call_args.kwargs["to_date"], "2026-08-07")
            self.assertIn("50", report["note"])


class ProgressTests(unittest.IsolatedAsyncioTestCase):
    async def test_retry_emits_a_visible_status_and_keeps_the_same_turn(self):
        from workspace.progress import RetryingModelClient, progress_sink

        class TemporaryError(Exception):
            status_code = 503

        call = AsyncMock(side_effect=[TemporaryError(), "answer"])
        client = Mock(bind_tools=Mock(return_value=SimpleNamespace(ainvoke=call)))
        events = []
        token = progress_sink.set(events.append)
        try:
            bound = RetryingModelClient(client, 1).bind_tools(
                [], parallel_tool_calls=False
            )
            with patch("workspace.progress.asyncio.sleep", new=AsyncMock()):
                self.assertEqual(await bound.ainvoke(["question"]), "answer")
            self.assertEqual(call.await_count, 2)
            self.assertIn("Переподключение 1 из 1", events[0]["text"])
        finally:
            progress_sink.reset(token)


class HistoryTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_checkpoint_restores_transcript_without_duplicating_existing_history(
        self,
    ):
        from langchain_core.messages import AIMessage, HumanMessage
        from langgraph.checkpoint.memory import InMemorySaver
        from agents.report_runtime import ReportAgentSystem
        from test_agent_support import StubService

        observed = []

        class AnsweringModel:
            def bind_tools(self, tools, *, parallel_tool_calls):
                return self

            async def ainvoke(self, messages):
                observed.append(list(messages))
                return AIMessage(content="The answer")

        saver = InMemorySaver()
        transcript = [
            HumanMessage(content="Earlier question"),
            AIMessage(content="Earlier answer"),
        ]
        system = ReportAgentSystem(
            StubService(),
            model_client=AnsweringModel(),
            checkpointer=saver,
            history=transcript,
        )
        self.assertTrue(
            (await system.process_user_request("Follow-up", "restored-chat"))["success"]
        )
        self.assertEqual(
            [m.content for m in observed[0] if m.type != "system"],
            ["Earlier question", "Earlier answer", "Follow-up"],
        )
        self.assertTrue(
            (await system.process_user_request("Another question", "restored-chat"))[
                "success"
            ]
        )
        self.assertEqual(sum(m.content == "Earlier question" for m in observed[1]), 1)


class WorkspaceApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.gate = asyncio.Event()
        self.agent_calls = []
        gate, calls = self.gate, self.agent_calls

        class FakeAgent:
            def __init__(self, **kwargs):
                self.options = kwargs

            async def process_user_request(self, message, session_id):
                calls.append((message, session_id, self.options["service"]))
                await gate.wait()
                return {
                    "success": True,
                    "message": "**Ответ:** 42",
                    "reasoning": "Synthetic provider reasoning",
                    "data": None,
                }

        from workspace.api import install_workspace

        self.app = FastAPI()
        self.runtime = SimpleNamespace(
            knowledge=None,
            llm_proxy_healthy=True,
            checkpoint_saver=SimpleNamespace(adelete_thread=AsyncMock()),
            tool_service=SimpleNamespace(),
            admission_lock=asyncio.Lock(),
            pinned={},
            sessions=SimpleNamespace(touch=AsyncMock()),
        )
        with (
            patch(
                "bd_shared.config.CHECKPOINT_DB_PATH",
                str(Path(self.directory.name) / "checkpoints.db"),
            ),
            patch("agents.report_runtime.ReportAgentSystem", FakeAgent),
        ):
            install_workspace(self.app, lambda: self.runtime)
        self.client_patch = patch("workspace.api.make_client", return_value=object())
        self.client_patch.start()
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=self.app), base_url="http://test"
        )
        data = (await self.client.get("/api/workspace")).json()
        self.client.headers["X-Workspace-Token"] = data["csrf_token"]
        self.project_id = data["projects"][0]["id"]

    async def asyncTearDown(self):
        await self.app.state.stop_workspace_jobs()
        await self.client.aclose()
        self.client_patch.stop()
        self.directory.cleanup()

    async def test_mutation_requires_workspace_token(self):
        response = await self.client.post(
            "/api/projects",
            json={"name": "bad"},
            headers={"X-Workspace-Token": "wrong"},
        )
        self.assertEqual(response.status_code, 403)

    async def test_duplicate_delivery_does_not_duplicate_message_or_model_call(self):
        chat = (
            await self.client.post("/api/chats", json={"project_id": self.project_id})
        ).json()
        body = {"message": "Test question", "request_id": "synthetic-request-0001"}
        url = f"/api/chats/{chat['id']}/messages"
        first = await self.client.post(url, json=body)
        second = await self.client.post(url, json=body)
        self.assertEqual(first.json(), second.json())
        await asyncio.sleep(0.05)
        self.assertEqual(len(self.agent_calls), 1)
        pending = (await self.client.get(f"/api/chats/{chat['id']}")).json()
        self.assertEqual(len(pending["messages"]), 1)
        self.assertEqual(pending["active_job"], body["request_id"])
        self.gate.set()
        await asyncio.sleep(0.05)
        done = (await self.client.get(f"/api/chats/{chat['id']}")).json()
        self.assertEqual([m["role"] for m in done["messages"]], ["user", "assistant"])
        self.assertEqual(
            done["messages"][1]["reasoning"], "Synthetic provider reasoning"
        )
        answer = done["messages"][1]
        self.assertGreater(answer["duration_seconds"], 0)
        self.assertGreaterEqual(answer["created_at"], done["messages"][0]["created_at"])
        restored = WorkspaceStore(Path(self.directory.name) / "workspace.json")
        self.assertEqual(restored.get("chats", chat["id"])["messages"][1], answer)
        self.assertEqual(
            (await self.client.get("/api/jobs/" + body["request_id"])).json()["status"],
            "completed",
        )

    async def test_conflicting_request_id_and_parallel_turn_are_rejected(self):
        chat = (
            await self.client.post("/api/chats", json={"project_id": self.project_id})
        ).json()
        url = f"/api/chats/{chat['id']}/messages"
        await self.client.post(
            url, json={"message": "First", "request_id": "synthetic-request-0001"}
        )
        for request_id in ["synthetic-request-0001", "synthetic-request-0002"]:
            response = await self.client.post(
                url, json={"message": "Different", "request_id": request_id}
            )
            self.assertEqual(response.status_code, 409)

    async def test_source_validation_and_public_response_never_return_secrets(self):
        fake = SimpleNamespace(
            metadata=lambda: {"name": "Test counter", "counter_id": "123"}
        )
        with patch("workspace.api.adapter", return_value=fake):
            response = await self.client.post(
                f"/api/projects/{self.project_id}/sources",
                json={
                    "provider": "metrika",
                    "config": {"counter_id": "123", "token": "private-synthetic-token"},
                    "remember": True,
                },
            )
        self.assertEqual(response.status_code, 200)
        data = (await self.client.get("/api/workspace")).text
        self.assertNotIn("private-synthetic-token", data)
        self.assertNotIn("encrypted", data)
        self.assertTrue(response.json()["connected"])

    async def test_edit_preserves_existing_key_and_remember_choice_then_replaces_key(
        self,
    ):
        fake = SimpleNamespace(
            metadata=lambda: {"name": "Counter", "counter_id": "123"}
        )
        with patch("workspace.api.adapter", return_value=fake) as factory:
            source = (
                await self.client.post(
                    f"/api/projects/{self.project_id}/sources",
                    json={
                        "provider": "metrika",
                        "config": {"counter_id": "123", "token": "private-synthetic"},
                    },
                )
            ).json()
            updated = await self.client.put(
                f"/api/sources/{source['id']}",
                json={
                    "provider": "metrika",
                    "name": "Renamed",
                    "config": {"counter_id": "123", "token": ""},
                    "remember": True,
                },
            )
            self.assertEqual(updated.status_code, 200)
            self.assertEqual(factory.call_args.args[1]["token"], "private-synthetic")
            self.assertEqual(updated.json()["name"], "Renamed")
            self.assertEqual(updated.json()["config"], {"counter_id": "123"})
            restored = WorkspaceStore(Path(self.directory.name) / "workspace.json")
            self.assertTrue(
                restored.public(restored.get("sources", source["id"]))["connected"]
            )
            self.assertNotIn("private-synthetic", updated.text)
            await self.client.put(
                f"/api/sources/{source['id']}",
                json={
                    "provider": "metrika",
                    "config": {"token": "replacement-synthetic"},
                    "remember": False,
                },
            )
            self.assertEqual(
                factory.call_args.args[1],
                {"counter_id": "123", "token": "replacement-synthetic"},
            )
            restored = WorkspaceStore(Path(self.directory.name) / "workspace.json")
            self.assertFalse(
                restored.public(restored.get("sources", source["id"]))["connected"]
            )

    async def test_report_failures_update_source_status_and_success_recovers(self):
        fake = SimpleNamespace(
            metadata=lambda: {"name": "Counter", "counter_id": "123"},
            overview=Mock(return_value={"metrics": []}),
        )
        with patch("workspace.api.adapter", return_value=fake):
            source = (
                await self.client.post(
                    f"/api/projects/{self.project_id}/sources",
                    json={
                        "provider": "metrika",
                        "config": {"counter_id": "123", "token": "private-synthetic"},
                    },
                )
            ).json()
            url = f"/api/sources/{source['id']}/reports/overview"
            self.assertEqual((await self.client.get(url)).status_code, 200)
            for status in [401, 403, 502, 429, 504]:
                fake.overview.side_effect = ConnectorError("Synthetic failure", status)
                self.assertEqual(
                    (await self.client.get(url + "?refresh=true")).status_code, status
                )
                public = (await self.client.get("/api/workspace")).json()["sources"][0]
                self.assertEqual(public["connected"], status not in (401, 403))
                self.assertEqual(
                    public["connection_status"],
                    "reconnect" if status in (401, 403) else "error",
                )
                self.assertTrue(public["has_credentials"])
                # An old cached report must not mask a known connection failure.
                self.assertEqual((await self.client.get(url)).status_code, status)
                fake.overview.side_effect = None
                self.assertEqual((await self.client.get(url)).status_code, 200)
                self.assertEqual(
                    (await self.client.get("/api/workspace")).json()["sources"][0][
                        "connection_status"
                    ],
                    "ready",
                )
            self.app.state.workspace_store.temporary_secrets.clear()
            self.assertEqual((await self.client.get(url)).status_code, 401)
            public = (await self.client.get("/api/workspace")).json()["sources"][0]
            self.assertFalse(public["connected"])
            self.assertEqual(public["config"]["counter_id"], "123")


if __name__ == "__main__":
    unittest.main()
