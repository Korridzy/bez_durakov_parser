import importlib
import sys
import unittest

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
        graph = self.graph_module.build_graph(model, tools, saver)
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
        cls.graph_module = importlib.import_module("agent.graph")

    def test_system_prompt_contract_is_exact(self):
        expected_prompt = """Ты — аналитик данных игр «Без дураков».

• Отвечай только по-русски.
• Данные получай ТОЛЬКО через инструменты.
• Инструменты возвращают сводку, не сами строки.
  Нужны строки — вызови read_rows.
• Лимит: 256 строк на вызов, 1024 на запрос.
  Исчерпан — отвечай по тому, что есть.
• Получил данные — вызови mark_report(handle).
• Пусто — скажи прямо, отчёт не отмечай.
• Не выдумывай числа и названия команд."""
        actual_prompt = self.graph_module.SYSTEM_PROMPT

        self.assertEqual(expected_prompt.encode("utf-8"), actual_prompt.encode("utf-8"))
        self.assertLess(len(actual_prompt), 600)
        for fragment in (
            "Отвечай только по-русски",
            "read_rows",
            "mark_report",
            "Исчерпан — отвечай по тому, что есть",
            "Пусто — скажи прямо",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, actual_prompt)


if __name__ == "__main__":
    unittest.main()
