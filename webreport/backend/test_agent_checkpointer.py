import importlib
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, "/")


class TestCheckpointerCases(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.checkpoint = importlib.import_module("langgraph.checkpoint.sqlite.aio")
        cls.config = importlib.import_module("bd_shared.config")
        cls.graph_module = importlib.import_module("agent.graph")
        cls.registry_module = importlib.import_module("agent.registry")
        cls.tools_module = importlib.import_module("agent.tools")
        cls.messages = importlib.import_module("langchain_core.messages")
        cls.graph_cases = importlib.import_module("test_agent_graph")
        cls.support = importlib.import_module("test_agent_support")

    def _build_graph(self, saver, model):
        service = self.support.StubService()
        registry = self.registry_module.ToolRegistry(service)
        tools = self.tools_module.build_tools(registry, self.config)
        graph = self.graph_module.build_graph(
            model, tools, saver, "Test system prompt for checkpointer tests."
        )
        return service, graph

    async def test_checkpoint_round_trip_preserves_history(self):
        async with self.checkpoint.AsyncSqliteSaver.from_conn_string(":memory:") as saver:
            model = self.graph_cases.ScriptedModel(
                [
                    self.messages.AIMessage(
                        content="",
                        tool_calls=[
                            self.graph_cases.tool_call("get_all_teams", {}, "turn-1-tool")
                        ],
                    ),
                    self.messages.AIMessage(content="Первый ответ."),
                    self.messages.AIMessage(
                        content="",
                        tool_calls=[
                            self.graph_cases.tool_call("get_all_teams", {}, "turn-2-tool")
                        ],
                    ),
                    self.messages.AIMessage(content="Второй ответ."),
                ]
            )
            service, graph = self._build_graph(saver, model)
            service.results["get_all_teams"] = []

            first = await self.graph_module.arun(graph, "Покажи команды", "t1")
            first_tuple = await saver.aget_tuple({"configurable": {"thread_id": "t1"}})
            self.assertIsNotNone(first_tuple)
            assert first_tuple is not None
            first_messages = first_tuple.checkpoint["channel_values"]["messages"]

            second = await self.graph_module.arun(graph, "Ещё раз", "t1")
            second_tuple = await saver.aget_tuple({"configurable": {"thread_id": "t1"}})
            self.assertIsNotNone(second_tuple)
            assert second_tuple is not None
            second_messages = second_tuple.checkpoint["channel_values"]["messages"]

            self.assertEqual(first["messages"][-1].content, "Первый ответ.")
            self.assertEqual(second["messages"][-1].content, "Второй ответ.")
            self.assertEqual(
                [message.content for message in second_messages if message.type == "human"],
                ["Покажи команды", "Ещё раз"],
            )
            self.assertEqual(second_messages[-1].content, "Второй ответ.")
            self.assertGreater(len(second_messages), len(first_messages))

    async def test_delete_thread_on_missing_thread_needs_setup(self):
        async with self.checkpoint.AsyncSqliteSaver.from_conn_string(":memory:") as saver:
            await saver.setup()
            await saver.adelete_thread("never-existed")


class TestPromptCases(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.knowledge_module = importlib.import_module("agent.knowledge")

    def _knowledge_limits(self):
        return self.knowledge_module.KnowledgeLimits(
            max_title_chars=80,
            max_summary_chars=200,
            max_persona_chars=2000,
            max_topics=50,
            max_doc_bytes=65536,
            max_bytes_per_turn=131072,
        )

    def test_system_prompt_without_knowledge_is_byte_exact(self):
        expected_prompt = (
            "You are a data analyst for the connected database. Answer in the language of the user's question.\n\n"
            "- Get data ONLY through the tools.\n"
            "- The tools return a summary, not the rows themselves. If you need rows, call read_rows.\n"
            "- Row budgets are bounded per call and per request. "
            "When a budget is exhausted, answer with what you have.\n"
            "- Once you have received data, call mark_report(handle).\n"
            "- If there is nothing, say so plainly and do not mark a report.\n"
            "- Do not invent numbers or names."
        )
        actual_prompt = self.knowledge_module.compose_system_prompt(None)

        self.assertEqual(expected_prompt.encode("utf-8"), actual_prompt.encode("utf-8"))
        for fragment in ("read_rows", "mark_report"):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, actual_prompt)
        self.assertNotIn("256", actual_prompt)
        self.assertNotIn("1024", actual_prompt)

    def test_system_prompt_with_knowledge_is_byte_exact(self):
        limits = self._knowledge_limits()

        with tempfile.TemporaryDirectory() as temp_dir:
            folder_path = Path(temp_dir)
            (folder_path / "manifest.toml").write_text(
                'dataset = "some_db"\npersona = "Some text."\n',
                encoding="utf-8",
            )
            (folder_path / "rules.md").write_text(
                "# Rules\n\nSome summary paragraph text.\n",
                encoding="utf-8",
            )
            knowledge = self.knowledge_module.load_knowledge(
                folder_path,
                "some_db",
                limits,
            )
            expected_prompt = (
                "Some text.\n\n"
                "- Get data ONLY through the tools.\n"
                "- The tools return a summary, not the rows themselves. If you need rows, call read_rows.\n"
                "- Row budgets are bounded per call and per request. "
                "When a budget is exhausted, answer with what you have.\n"
                "- Once you have received data, call mark_report(handle).\n"
                "- If there is nothing, say so plainly and do not mark a report.\n"
                "- Do not invent numbers or names.\n"
                "- Before answering a question covered by a listed topic, "
                "call read_knowledge with that topic id.\n\n"
                "## Knowledge topics\n\n"
                "rules: Rules. Some summary paragraph text."
            )

            actual_prompt = self.knowledge_module.compose_system_prompt(knowledge)

            self.assertEqual(expected_prompt.encode("utf-8"), actual_prompt.encode("utf-8"))


if __name__ == "__main__":
    unittest.main()
