import importlib
import os
import subprocess
import sys
import unittest
from asyncio import CancelledError, sleep
from unittest.mock import Mock, patch

_graph_cases = importlib.import_module("test_agent_graph")
ScriptedModel = _graph_cases.ScriptedModel
tool_call = _graph_cases.tool_call


class ScriptedModelError(RuntimeError):
    pass


class FailingModel:
    def bind_tools(self, tools, *, parallel_tool_calls):
        return self

    async def ainvoke(self, messages):
        raise ScriptedModelError("scripted model failure")


class SlowModel:
    def __init__(self):
        self.cancelled = False

    def bind_tools(self, tools, *, parallel_tool_calls):
        return self

    async def ainvoke(self, messages):
        try:
            await sleep(1)
        except CancelledError:
            self.cancelled = True
            raise


class ReportAgentSystemTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.checkpoint = importlib.import_module("langgraph.checkpoint.sqlite.aio")
        cls.memory = importlib.import_module("langgraph.checkpoint.memory")
        cls.messages = importlib.import_module("langchain_core.messages")
        cls.pd = importlib.import_module("pandas")
        cls.report_module = importlib.import_module("agents.report_agents")
        cls.runtime_module = importlib.import_module("agents.report_runtime")
        cls.support = importlib.import_module("test_agent_support")

    def make_system(self, saver, *, mode="fallback", model=None, timeout: float = 60):
        service = self.support.StubService()
        system = self.report_module.ReportAgentSystem(
            service=service,
            model_client=model,
            checkpointer=saver,
            mode=mode,
            timeout_seconds=timeout,
        )
        return system, service

    async def test_fallback_preserves_frozen_routes_and_response_shapes(self):
        cases = (
            ("покажи все игры", "get_all_games_summary", {}, [{"game_id": 1}]),
            ("топ 10 команд", "get_top_teams", {"limit": 10}, [{"team": "А"}]),
            (
                "Сделай отчёт о том, в каких играх за 2025 год побеждала команда Однажды было дважды",
                "get_team_wins",
                {"team_name": "Однажды было дважды", "year": 2025},
                {"wins": [7]},
            ),
            (
                "статистика команды Однажды было дважды",
                "get_team_statistics",
                {"team_name": "Однажды было дважды"},
                {"games": 4},
            ),
            ("очки всех команд", "get_team_game_scores", {}, [{"score": 42}]),
        )
        async with self.checkpoint.AsyncSqliteSaver.from_conn_string(":memory:") as saver:
            system, service = self.make_system(saver)
            service.results.update(
                {
                    "get_all_games_summary": self.pd.DataFrame([{"game_id": 1}]),
                    "get_top_teams": self.pd.DataFrame([{"team": "А"}]),
                    "get_team_wins": {"wins": [7]},
                    "get_team_statistics": {"games": 4},
                    "get_team_game_scores": self.pd.DataFrame([{"score": 42}]),
                }
            )
            for index, (prompt, name, args, data) in enumerate(cases):
                with self.subTest(prompt=prompt):
                    response = await system.process_user_request(prompt, f"fallback-{index}")
                    self.assertEqual(response["query_info"][0], {"tool": name, "args": args})
                    self.assertEqual(response["data"], data)
                    self.assertEqual(response["mode"], "fallback")

    async def test_fallback_never_builds_the_agent_graph(self):
        with patch.object(self.runtime_module, "build_graph") as graph_builder:
            system, _ = self.make_system(self.memory.InMemorySaver())
        await system.process_user_request("покажи все игры", "fixed-fallback")
        graph_builder.assert_not_called()

    async def test_report_agent_system_is_exported_from_typed_runtime(self):
        runtime_module = importlib.import_module("agents.report_runtime")

        self.assertIs(self.report_module.ReportAgentSystem, runtime_module.ReportAgentSystem)

    def test_import_orders_are_safe_in_independent_processes(self):
        import_orders = (
            "import agents.report_agents; import agents.report_runtime",
            "import agents.report_runtime; from agents.report_agents import ReportAgentSystem",
        )
        child_environment = os.environ.copy()
        child_environment["PYTHONPATH"] = "/"

        for statement in import_orders:
            with self.subTest(statement=statement):
                completed = subprocess.run(
                    [sys.executable, "-c", statement],
                    capture_output=True,
                    text=True,
                    check=False,
                    env=child_environment,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)

    async def test_score_route_discrepancy_remains_explicit(self):
        interpreter = self.report_module.FallbackInterpreter()

        raw = interpreter._interpret_request("очки всех команд")
        public = interpreter.interpret("очки всех команд")

        self.assertEqual(raw["method"], "get_team_statistics")
        self.assertEqual(raw["params"], {"team_name": "команд"})
        self.assertEqual(public["method"], "get_team_game_scores")
        self.assertEqual(public["params"], {})

    async def test_default_agent_client_targets_litellm_without_real_key(self):
        client = FailingModel()
        chat_openai = Mock(return_value=client)
        proxy_module = type("ProxyModule", (), {"ChatOpenAI": chat_openai})()
        real_import = importlib.import_module
        with (
            patch.object(
                self.runtime_module.importlib,
                "import_module",
                side_effect=lambda name: proxy_module
                if name == "langchain_openai"
                else real_import(name),
            ),
            patch.object(self.runtime_module, "build_graph") as graph_builder,
        ):
            self.make_system(self.memory.InMemorySaver(), mode="agent")
        chat_openai.assert_called_once_with(
            base_url="http://litellm:4000",
            model="gpt-4o",
            api_key="sk-noop",
            max_retries=0,
            timeout=60,
        )
        self.assertIs(graph_builder.call_args.args[0], client)

    async def test_fallback_turn_is_checkpointed_as_human_assistant_pair(self):
        async with self.checkpoint.AsyncSqliteSaver.from_conn_string(":memory:") as saver:
            system, service = self.make_system(saver)
            service.results["get_all_games_summary"] = []
            await system.process_user_request("покажи все игры", "history-thread")
            checkpoint = await saver.aget({"configurable": {"thread_id": "history-thread"}})
        stored = checkpoint["channel_values"]["messages"]
        self.assertEqual([message.type for message in stored], ["human", "ai"])

    async def test_marked_report_is_freshly_materialized(self):
        handle = {"tool": "get_all_teams", "args": {}}
        model = ScriptedModel(
            [
                self.messages.AIMessage(content="", tool_calls=[tool_call("get_all_teams", {}, "data")]),
                self.messages.AIMessage(content="", tool_calls=[tool_call("mark_report", {"handle": handle}, "mark")]),
                self.messages.AIMessage(content="Отчёт готов."),
            ]
        )
        async with self.checkpoint.AsyncSqliteSaver.from_conn_string(":memory:") as saver:
            system, service = self.make_system(saver, mode="agent", model=model)
            service.results["get_all_teams"] = self.pd.DataFrame([{"team_name": "А"}])
            response = await system.process_user_request("Покажи команды", "marked-thread")
        self.assertTrue(response["success"])
        self.assertEqual(response["data"], [{"team_name": "А"}])
        self.assertEqual([name for name, _ in service.calls], ["get_all_teams"] * 3)

    async def test_multi_call_trace_is_ordered_and_unmarked_text_has_no_data(self):
        model = ScriptedModel(
            [
                self.messages.AIMessage(
                    content="",
                    tool_calls=[
                        tool_call("get_all_teams", {}, "first"),
                        tool_call("get_top_teams", {"limit": 2}, "second"),
                    ],
                ),
                self.messages.AIMessage(content="Сравнение готово."),
            ]
        )
        async with self.checkpoint.AsyncSqliteSaver.from_conn_string(":memory:") as saver:
            system, service = self.make_system(saver, mode="agent", model=model)
            service.results.update({"get_all_teams": [], "get_top_teams": []})
            response = await system.process_user_request("Сравни команды", "trace-thread")
        self.assertEqual(
            response["query_info"],
            [{"tool": "get_all_teams", "args": {}}, {"tool": "get_top_teams", "args": {"limit": 2}}],
        )
        self.assertEqual(response["message"], "Сравнение готово.")
        self.assertIsNone(response["data"])

    async def test_timeout_cancels_agent_run_without_fallback(self):
        model = SlowModel()
        system, service = self.make_system(
            self.memory.InMemorySaver(), mode="agent", model=model, timeout=0.05
        )
        response = await system.process_user_request("покажи все игры", "timeout-thread")
        self.assertFalse(response["success"])
        self.assertTrue(model.cancelled)
        self.assertEqual(response["mode"], "agent")
        self.assertEqual(response["query_info"], [])
        self.assertEqual(service.calls, [])
        self.assertRegex(response["message"], "[А-Яа-я]")

    async def test_model_error_is_controlled_without_regex_data(self):
        system, service = self.make_system(
            self.memory.InMemorySaver(), mode="agent", model=FailingModel()
        )
        service.results["get_all_games_summary"] = [{"fallback": True}]
        response = await system.process_user_request("покажи все игры", "error-thread")
        self.assertFalse(response["success"])
        self.assertEqual(response["mode"], "agent")
        self.assertEqual(response["query_info"], [])
        self.assertIsNone(response["data"])
        self.assertEqual(service.calls, [])
        self.assertRegex(response["message"], "[А-Яа-я]")

    async def test_recursion_marker_becomes_controlled_agent_failure(self):
        def repeat(invocation):
            return self.messages.AIMessage(
                content="", tool_calls=[tool_call("get_all_teams", {}, f"loop-{invocation}")]
            )

        model = ScriptedModel([], repeat_factory=repeat)
        system, service = self.make_system(self.memory.InMemorySaver(), mode="agent", model=model)
        service.results["get_all_teams"] = []
        response = await system.process_user_request("Не останавливайся", "recursion-thread")
        self.assertFalse(response["success"])
        self.assertEqual(response["query_info"], [])
        self.assertEqual(response["mode"], "agent")
        self.assertRegex(response["message"], "[А-Яа-я]")

    async def test_each_agent_turn_resets_transient_graph_state(self):
        handle = {"tool": "get_team_game_scores", "args": {"game_id": None}}
        model = ScriptedModel(
            [
                self.messages.AIMessage(content="", tool_calls=[tool_call("read_rows", {"handle": handle, "limit": 1}, "read-1")]),
                self.messages.AIMessage(content="", tool_calls=[tool_call("mark_report", {"handle": handle}, "mark-1")]),
                self.messages.AIMessage(content="Первый ответ."),
                self.messages.AIMessage(content="", tool_calls=[tool_call("read_rows", {"handle": handle, "limit": 1}, "read-2")]),
                self.messages.AIMessage(content="Второй ответ."),
            ]
        )
        async with self.checkpoint.AsyncSqliteSaver.from_conn_string(":memory:") as saver:
            system, service = self.make_system(saver, mode="agent", model=model)
            service.results["get_team_game_scores"] = self.pd.DataFrame([{"score": 7}])
            await system.process_user_request("Первый", "two-turn-thread")
            second = await system.process_user_request("Второй", "two-turn-thread")
            checkpoint = await saver.aget({"configurable": {"thread_id": "two-turn-thread"}})
        self.assertEqual(checkpoint["channel_values"]["rows_consumed"], 1)
        self.assertIsNone(checkpoint["channel_values"]["report_payload"])
        self.assertEqual(second["query_info"][0]["args"]["limit"], 1)
        self.assertIsNone(second["data"])


if __name__ == "__main__":
    unittest.main()
