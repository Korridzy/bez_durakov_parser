import importlib
import os
import subprocess
import sys
import unittest
from asyncio import CancelledError, sleep
from pathlib import Path
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
        cls.knowledge = importlib.import_module("agent.knowledge")
        cls.pd = importlib.import_module("pandas")
        cls.report_module = importlib.import_module("agents.report_runtime")
        cls.runtime_module = importlib.import_module("agents.report_runtime")
        cls.support = importlib.import_module("test_agent_support")

    def make_system(self, saver, *, model=None, timeout: float = 60):
        """Build a system over a stub service. A None model builds the real LiteLLM client."""
        service = self.support.StubService()
        system = self.report_module.ReportAgentSystem(
            service=service,
            model_client=model,
            checkpointer=saver,
            timeout_seconds=timeout,
        )
        return system, service

    def answering_model(self, answer="Готово."):
        """A model that answers immediately, for cases that only need a completed turn."""
        return ScriptedModel([self.messages.AIMessage(content=answer)])

    def load_fixture_knowledge(self):
        return self.knowledge.load_knowledge(
            Path("/bd_shared/knowledge/bez_durakov"),
            "bez_durakov",
            self.knowledge.KnowledgeLimits(
                max_title_chars=80,
                max_summary_chars=200,
                max_persona_chars=2000,
                max_topics=50,
                max_doc_bytes=65536,
                max_bytes_per_turn=131072,
            ),
        )

    async def test_knowledge_is_threaded_into_tools_graph_and_prompt(self):
        knowledge = self.load_fixture_knowledge()
        model = ScriptedModel([self.messages.AIMessage(content="Правила загружены.")])
        service = self.support.StubService()

        with patch.object(
            self.runtime_module,
            "compose_system_prompt",
            wraps=self.knowledge.compose_system_prompt,
        ) as prompt_composer:
            system = self.report_module.ReportAgentSystem(
                service=service,
                model_client=model,
                checkpointer=self.memory.InMemorySaver(),
                knowledge=knowledge,
            )
            response = await system.process_user_request("Объясни правила", "knowledge-agent")

        self.assertEqual(
            model.bound_tool_names,
            [
                "read_knowledge",
                *self.support.TOOL_NAMES,
                "read_rows",
                "mark_report",
            ],
        )
        self.assertEqual(
            model.requests[0][0].content,
            self.knowledge.compose_system_prompt(knowledge),
        )
        prompt_composer.assert_called_once_with(knowledge)
        self.assertEqual(response["message"], "Правила загружены.")
        self.assertNotIn("mode", response)

    def test_explicit_none_knowledge_keeps_the_ten_tool_catalogue(self):
        model = ScriptedModel([])

        self.report_module.ReportAgentSystem(
            service=self.support.StubService(),
            model_client=model,
            checkpointer=self.memory.InMemorySaver(),
            knowledge=None,
        )

        self.assertEqual(
            model.bound_tool_names,
            [*self.support.TOOL_NAMES, "read_rows", "mark_report"],
        )

    def test_import_orders_are_safe_in_independent_processes(self):
        import_orders = (
            "import agents.report_runtime",
            "from agents.report_runtime import ReportAgentSystem",
            "import agents.report_contracts; import agents.report_runtime",
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

    async def test_default_agent_client_targets_litellm_without_real_key(self):
        client = FailingModel()
        chat_litellm = Mock(return_value=client)
        proxy_module = type("ProxyModule", (), {"ChatLiteLLM": chat_litellm})()
        real_import = importlib.import_module
        with (
            patch.object(
                self.runtime_module.importlib,
                "import_module",
                side_effect=lambda name: proxy_module
                if name == "langchain_litellm"
                else real_import(name),
            ),
            patch.object(self.runtime_module, "build_graph") as graph_builder,
        ):
            self.make_system(self.memory.InMemorySaver())
        chat_litellm.assert_called_once_with(
            model="litellm_proxy/gpt-4o",
            api_base="http://litellm:4000",
            api_key="sk-noop",
            request_timeout=60,
            model_kwargs={"num_retries": 0},
        )
        self.assertIsInstance(
            graph_builder.call_args.args[0], self.runtime_module.OutboundReasoningFilter
        )
        self.assertIs(graph_builder.call_args.args[0].client, client)

    async def test_a_turn_is_checkpointed_as_a_human_assistant_pair(self):
        async with self.checkpoint.AsyncSqliteSaver.from_conn_string(":memory:") as saver:
            system, service = self.make_system(saver, model=self.answering_model())
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
            system, service = self.make_system(saver, model=model)
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
            system, service = self.make_system(saver, model=model)
            service.results.update({"get_all_teams": [], "get_top_teams": []})
            response = await system.process_user_request("Сравни команды", "trace-thread")
        self.assertEqual(
            response["query_info"],
            [{"tool": "get_all_teams", "args": {}}, {"tool": "get_top_teams", "args": {"limit": 2}}],
        )
        self.assertEqual(response["message"], "Сравнение готово.")
        self.assertIsNone(response["data"])

    async def test_timeout_cancels_the_agent_run_and_returns_a_controlled_failure(self):
        model = SlowModel()
        system, service = self.make_system(
            self.memory.InMemorySaver(), model=model, timeout=0.05
        )
        response = await system.process_user_request("покажи все игры", "timeout-thread")
        self.assertFalse(response["success"])
        self.assertTrue(model.cancelled)
        self.assertEqual(response["query_info"], [])
        self.assertEqual(service.calls, [])
        self.assertRegex(response["message"], "[А-Яа-я]")

    async def test_model_error_is_controlled_without_regex_data(self):
        system, service = self.make_system(
            self.memory.InMemorySaver(), model=FailingModel()
        )
        service.results["get_all_games_summary"] = [{"unused": True}]
        response = await system.process_user_request("покажи все игры", "error-thread")
        self.assertFalse(response["success"])
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
        system, service = self.make_system(self.memory.InMemorySaver(), model=model)
        service.results["get_all_teams"] = []
        response = await system.process_user_request("Не останавливайся", "recursion-thread")
        self.assertFalse(response["success"])
        self.assertEqual(response["query_info"], [])
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
            system, service = self.make_system(saver, model=model)
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
