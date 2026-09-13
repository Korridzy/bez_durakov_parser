"""Offline harness contracts; RUN_ANALYSIS_INTEGRATION=1 also tests the real sandbox."""

import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
import pandas as pd

from analysis.artifacts import make_artifact
from analysis.storage import ResultStore
from analysis.tools import build_analysis_tools
from connectors.metrika import Metrika
from connectors.native_queries import metrika_series, native_query
from connectors.service import AnalyticsService


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = ResultStore(self.temp.name)

    def test_immutable_and_scoped_results(self):
        first = self.store.save("chat_a", {"rows": [{"x": "one", "v": 2}]})
        second = self.store.save("chat_a", {"rows": [{"x": "one", "v": 7}]})
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(self.store.get("chat_a", first["id"])["value"]["rows"][0]["v"], 2)
        for chat, ident in [("chat_b", first["id"]), ("../chat_a", first["id"]), ("chat_a", "../workspace")]:
            with self.assertRaises(ValueError):
                self.store.get(chat, ident)
        self.store.delete_chat("chat_a")
        with self.assertRaises(ValueError):
            self.store.get("chat_a", first["id"])

    def test_chart_numbers_come_from_result_not_tool_arguments(self):
        record = self.store.save("a", {"rows": [{"hour": "00", "ru": 12, "us": None}, {"hour": "01", "ru": 9, "us": 7}]})
        chart = make_artifact(record, title="Countries", kind="line", x="hour", x_label="Час по Москве", series=[{"column": "ru", "label": "Russia"}, {"column": "us", "label": "USA"}])
        self.assertEqual(chart["data"], [{"x": "00", "s0": 12, "s1": None}, {"x": "01", "s0": 9, "s1": 7}])
        self.assertEqual(chart["x_label"], "Час по Москве")
        with self.assertRaises(ValueError):
            make_artifact(record, title="Missing", kind="line", x="hour", series=[{"column": "fake", "label": "X"}])

    def test_funnel_rejects_independent_increasing_counts(self):
        record = self.store.save("a", {"rows": [{"step": "start", "n": 5}, {"step": "end", "n": 9}]})
        with self.assertRaises(ValueError):
            make_artifact(record, title="Funnel", kind="funnel", x="step", series=[{"column": "n", "label": "Players"}])

    def test_histogram_counts_all_observations_and_ignores_null(self):
        record = self.store.save("a", {"rows": [{"v": x} for x in [1, 1, 2, 4, None]]})
        chart = make_artifact(record, title="Duration", kind="histogram", x="v", series=[{"column": "v", "label": "Seconds"}], bins=3)
        self.assertEqual(sum(r["s0"] for r in chart["data"]), 4)

    def test_chart_carries_source_limitations_through_calculations(self):
        provenance = {"operation": "run_python", "sources": [
            {"metadata": {"sampled": True, "sample_share": .5, "has_more": True}},
            {"metadata": {"sampled": True, "sample_share": .5}},
        ]}
        record = self.store.save("a", {"rows": [{"x": "one", "n": 7}]}, provenance=provenance)
        chart = make_artifact(record, title="Counts", kind="bar", x="x", series=[{"column": "n", "label": "Count"}])
        self.assertEqual(len(chart["warnings"]), 2)
        self.assertIn("50.0%", chart["warnings"][0])

    def test_sparse_heatmap_bounds_rendered_cells_including_gaps(self):
        record = self.store.save("a", {"rows": [{"x": str(i), "y": str(i), "n": i} for i in range(50)]})
        with self.assertRaisesRegex(ValueError, "1600 cells"):
            make_artifact(record, title="Matrix", kind="heatmap", x="x", y="y", series=[{"column": "n", "label": "Count"}])


class ConnectorTests(unittest.TestCase):
    def test_metrika_timezone_and_pagination(self):
        client = Metrika({"counter_id": "1", "token": "synthetic"})
        with patch.object(client, "_get", return_value={"data": [], "total_rows": 90}) as query:
            result = client.query("2026-09-01", "2026-09-02", offset=51, timezone="+03:00")
        self.assertEqual(query.call_args.kwargs["timezone"], "+03:00")
        self.assertTrue(result["has_more"])
        with self.assertRaises(ValueError):
            client.query("2026-09-01", "2026-09-02", timezone="Europe/Moscow")

    def test_hourly_two_countries_missing_bucket_and_sampling(self):
        client = Mock(counter_id="1")
        client._get.return_value = {
            "data": [{"dimensions": [{"name": "Россия"}], "metrics": [[5, 9]]},
                     {"dimensions": [{"name": "США"}], "metrics": [[2]]}],
            "time_intervals": [["2026-09-01 00:00:00"], ["2026-09-01 01:00:00"]],
            "sampled": True, "sample_share": .5, "total_rows": 2,
        }
        result = metrika_series(client, "2026-09-01", "2026-09-01", "ym:s:users", "hour", "ym:s:regionCountryName", "", "+03:00", "full")
        self.assertEqual(len(result["rows"]), 4)
        self.assertIsNone(result["rows"][-1]["ym:s:users"])
        self.assertTrue(result["sampled"])
        self.assertEqual(client._get.call_args.kwargs["timezone"], "+03:00")

    def test_native_queries_cannot_override_saved_accounts(self):
        for provider, body in [("ga4", {"property": "other", "metrics": []}),
                               ("matomo", {"method": "VisitsSummary.get", "idSite": "other"}),
                               ("mixpanel", {"endpoint": "/events", "params": {"project_id": "other"}}),
                               ("amplitude", {"endpoint": "/events/list", "params": {"api_key": "other"}}),
                               ("posthog", {"sql": "DELETE FROM events"})]:
            with self.subTest(provider=provider), self.assertRaises(ValueError):
                native_query(provider, Mock(), body)

    def test_project_source_isolation(self):
        service = AnalyticsService([], {}, Mock())
        with self.assertRaises(ValueError):
            service.source_schema("other")


class ToolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.results = ResultStore(self.temp.name)
        self.calls = 0
        owner = self
        class Service:
            def countries(self) -> pd.DataFrame:
                """Return country visit counts."""
                owner.calls += 1
                return pd.DataFrame([{"country": "RU", "n": 5}, {"country": "US", "n": 2}])
        self.active = Mock()
        self.tools = {t.name: t for t in build_analysis_tools(Service(), self.results, "test_chat", self.active, [])}

    async def test_fetch_read_publish_does_not_reexecute_source(self):
        result = await self.tools["query_data"].ainvoke({"operation": "countries", "arguments": {}})
        self.assertIn("result_id", result)
        rows = await self.tools["read_result"].ainvoke({"result_id": result["result_id"]})
        self.assertEqual(rows["rows"][0]["n"], 5)
        chart = await self.tools["publish_chart"].ainvoke({"result_id": result["result_id"], "title": "Countries", "kind": "bar", "x": "country", "series": [{"column": "n", "label": "Visits"}]})
        self.assertIn("#analysis-", chart["link"])
        self.assertEqual(self.calls, 1)

    async def test_cancelled_job_does_not_query_or_save(self):
        self.active.side_effect = ValueError("cancelled")
        reply = await self.tools["query_data"].ainvoke({"operation": "countries", "arguments": {}})
        self.assertEqual(reply["error"], "cancelled")
        self.assertEqual(self.calls, 0)


@unittest.skipUnless(os.environ.get("RUN_ANALYSIS_INTEGRATION") == "1", "Explicit isolated runner integration lane")
class RunnerTests(unittest.TestCase):
    def run_code(self, code):
        response = httpx.post(os.environ.get("ANALYSIS_RUNNER_URL", "http://analysis:8080") + "/execute",
                              json={"code": code, "inputs": {"visits": {"rows": [{"country": "RU", "n": 4}, {"country": "RU", "n": 6}, {"country": "US", "n": 3}]}}}, timeout=30)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_pandas_and_sql_real_calculations(self):
        response = self.run_code("result = sql('SELECT country, SUM(n) AS n FROM visits GROUP BY country ORDER BY country')")
        self.assertTrue(response["ok"], response)
        self.assertEqual(response["result"]["rows"], [{"country": "RU", "n": 10}, {"country": "US", "n": 3}])
        response = self.run_code("result = frames['visits'].groupby('country', as_index=False)['n'].sum()")
        self.assertTrue(response["ok"], response)
        self.assertEqual(response["result"]["rows"][0]["n"], 10)

    def test_kernel_denies_network_subprocess_and_parent_memory(self):
        for code in ["import socket; socket.socket()", "import os; os.fork()", "import subprocess; subprocess.run(['id'])", "open('/proc/1/environ').read()"]:
            with self.subTest(code=code):
                response = self.run_code(code)
                self.assertFalse(response["ok"], response)

    def test_no_secrets_or_host_data(self):
        response = self.run_code("import os; result = {'env': sorted(os.environ), 'data': os.path.exists('/data/workspace.json'), 'uid': os.getuid()}")
        self.assertTrue(response["ok"], response)
        self.assertFalse(response["result"]["data"])
        self.assertEqual(response["result"]["uid"], 65534)
        self.assertFalse(any("KEY" in v or "TOKEN" in v for v in response["result"]["env"]))

    def test_timeout_and_error_then_recovery(self):
        self.assertFalse(self.run_code("while True: pass")["ok"])
        self.assertFalse(self.run_code("result = 1/0")["ok"])
        self.assertEqual(self.run_code("result = 42")["result"], 42)


@unittest.skipUnless(os.environ.get("RUN_ANALYSIS_INTEGRATION") == "1", "Explicit isolated runner integration lane")
class GraphIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_graph_queries_runs_python_and_publishes_two_lines(self):
        from langchain_core.messages import AIMessage
        from langgraph.checkpoint.memory import InMemorySaver
        from agents.report_runtime import ReportAgentSystem

        class Source:
            def hourly(self) -> dict:
                """Synthetic hourly country visits for one day, Moscow time."""
                return {"rows": [{"hour": "00:00", "country": "RU", "n": 5}, {"hour": "00:00", "country": "US", "n": 3},
                                 {"hour": "01:00", "country": "RU", "n": 9}, {"hour": "01:00", "country": "US", "n": 4}],
                        "timezone": "+03:00", "sampled": False}
        with tempfile.TemporaryDirectory() as folder:
            results = ResultStore(folder)
            service = Source()
            steps = []
            class Model:
                def bind_tools(self, tools, *, parallel_tool_calls):
                    return self

                async def ainvoke(self, messages):
                    step = len(steps)
                    steps.append(step)
                    reply = json.loads(messages[-1].content) if step else {}
                    if step == 0:
                        name, args = "inspect_data", {}
                    elif step == 1:
                        self.assertion = reply["operations"][0]["name"]
                        name, args = "query_data", {"operation": "hourly", "arguments": {}}
                    elif step == 2:
                        name, args = "run_python", {"inputs": {"hours": reply["result_id"]},
                            "code": "result = frames['hours'].pivot(index='hour', columns='country', values='n').reset_index()"}
                    elif step == 3:
                        assert "result_id" in reply, reply
                        name, args = "publish_chart", {"result_id": reply["result_id"], "title": "Russia and USA", "kind": "line", "x": "hour",
                            "series": [{"column": "RU", "label": "Россия"}, {"column": "US", "label": "США"}], "subtitle": "Synthetic day · Moscow"}
                    else:
                        assert "link" in reply, reply
                        self.artifact = reply["artifact_id"]
                        return AIMessage(content="Сравнение стран: " + reply["link"])
                    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call-{step}", "type": "tool_call"}])
            model = Model()
            tools = build_analysis_tools(service, results, "graph_chat", lambda: None, [])
            system = ReportAgentSystem(service, model_client=model, checkpointer=InMemorySaver(), extra_tools=tools, max_steps=20)
            reply = await system.process_user_request("Compare hourly countries", "graph")
            self.assertTrue(reply["success"], reply)
            self.assertEqual(len(steps), 5)
            self.assertIn("#analysis-", reply["message"])
            chart = results.get("graph_chat", model.artifact)["value"]
            self.assertEqual(chart["data"][1], {"x": "01:00", "s0": 9, "s1": 4})


if __name__ == "__main__":
    unittest.main(verbosity=2)
