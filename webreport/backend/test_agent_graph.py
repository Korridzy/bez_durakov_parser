import importlib
import unittest
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import ClassVar, final, Protocol, TypeAlias, TypedDict

_support = importlib.import_module("test_agent_tools_support")
StubService = _support.StubService

JsonValue: TypeAlias = (
    str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
)
DEFAULT_TEST_PROMPT = "Test system prompt for GraphTests."


class ToolCall(TypedDict):
    name: str
    args: dict[str, JsonValue]
    id: str
    type: str


class MessageView(Protocol):
    content: str


class AgentMessageView(MessageView, Protocol):
    tool_calls: list[ToolCall]


class NamedTool(Protocol):
    name: str


class RunnableGraph(Protocol):
    async def ainvoke(
        self,
        input_state: dict[str, JsonValue],
        config: dict[str, JsonValue],
    ) -> dict[str, JsonValue]: ...


class ServiceView(Protocol):
    calls: list[tuple[str, dict[str, str | int | None]]]
    results: dict[str, list[dict[str, str | int]]]


@final
class ScriptedModel:
    """Mutable deterministic model double that records binding and invocation data."""

    def __init__(
        self,
        responses: Sequence[AgentMessageView],
        *,
        repeat_factory: Callable[[int], AgentMessageView] | None = None,
    ) -> None:
        self._responses: list[AgentMessageView] = list(responses)
        self._repeat_factory: Callable[[int], AgentMessageView] | None = repeat_factory
        self.invocation_count: int = 0
        self.requests: list[Sequence[MessageView]] = []
        self.bound_tool_names: list[str] = []
        self.parallel_tool_calls: bool | None = None

    def bind_tools(
        self,
        tools: Sequence[NamedTool],
        *,
        parallel_tool_calls: bool,
    ) -> "ScriptedModel":
        self.bound_tool_names = [tool.name for tool in tools]
        self.parallel_tool_calls = parallel_tool_calls
        return self

    async def ainvoke(self, messages: Sequence[MessageView]) -> AgentMessageView:
        self.invocation_count += 1
        self.requests.append(messages)
        if self._responses:
            return self._responses.pop(0)
        if self._repeat_factory is not None:
            return self._repeat_factory(self.invocation_count)
        raise AssertionError("ScriptedModel exhausted its responses")


def tool_call(name: str, args: dict[str, JsonValue], call_id: str) -> ToolCall:
    return {"name": name, "args": args, "id": call_id, "type": "tool_call"}


class GraphTests(unittest.IsolatedAsyncioTestCase):
    config: ClassVar
    graph_module: ClassVar
    memory: ClassVar
    messages: ClassVar
    pd: ClassVar
    registry_module: ClassVar
    tools_module: ClassVar

    @classmethod
    def setUpClass(cls) -> None:
        cls.config = importlib.import_module("bd_shared.config")
        cls.graph_module = importlib.import_module("agent.graph")
        cls.memory = importlib.import_module("langgraph.checkpoint.memory")
        cls.messages = importlib.import_module("langchain_core.messages")
        cls.knowledge = importlib.import_module("agent.knowledge")
        cls.pd = importlib.import_module("pandas")
        cls.registry_module = importlib.import_module("agent.registry")
        cls.tools_module = importlib.import_module("agent.tools")

    def build_harness(
        self,
        responses: Sequence[AgentMessageView],
        *,
        repeat_factory: Callable[[int], AgentMessageView] | None = None,
    ) -> tuple[ScriptedModel, ServiceView, list[NamedTool], RunnableGraph]:
        service: ServiceView = StubService()
        registry = self.registry_module.ToolRegistry(service)
        tools: list[NamedTool] = self.tools_module.build_tools(registry, self.config)
        model = ScriptedModel(responses, repeat_factory=repeat_factory)
        graph = self.graph_module.build_graph(
            model,
            tools,
            self.memory.InMemorySaver(),
            DEFAULT_TEST_PROMPT,
        )
        return model, service, tools, graph

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

    async def test_knowledge_round_trip_is_free_and_invalid_report_stays_in_band(
        self,
    ) -> None:
        knowledge = self.load_fixture_knowledge()
        rules_text = next(topic.text for topic in knowledge.topics if topic.id == "rules")
        invalid_handle: dict[str, JsonValue] = {"tool": rules_text, "args": {}}
        model = ScriptedModel(
            [
                self.messages.AIMessage(
                    content="",
                    tool_calls=[
                        tool_call(
                            "read_knowledge",
                            {"topic_id": "rules"},
                            "knowledge-1",
                        )
                    ],
                ),
                self.messages.AIMessage(
                    content="",
                    tool_calls=[
                        tool_call(
                            "mark_report",
                            {"handle": invalid_handle},
                            "invalid-report-1",
                        )
                    ],
                ),
                self.messages.AIMessage(content="Правила прочитаны."),
            ]
        )
        service: ServiceView = StubService()
        registry = self.registry_module.ToolRegistry(service)
        tools: list[NamedTool] = self.tools_module.build_tools(
            registry,
            self.config,
            knowledge=knowledge,
        )
        graph = self.graph_module.build_graph(
            model,
            tools,
            self.memory.InMemorySaver(),
            self.knowledge.compose_system_prompt(knowledge),
        )
        rows_consumed_before_knowledge_call = 0

        result = await self.graph_module.arun(graph, "Объясни правила", "knowledge-thread")

        knowledge_messages = [
            message
            for message in model.requests[1]
            if isinstance(message, self.messages.ToolMessage)
        ]
        invalid_report_messages = [
            message
            for message in model.requests[2]
            if isinstance(message, self.messages.ToolMessage)
        ]
        self.assertEqual(len(knowledge_messages), 1)
        self.assertEqual(knowledge_messages[0].content, rules_text)
        self.assertEqual(len(invalid_report_messages), 2)
        self.assertTrue(invalid_report_messages[-1].content.startswith("Tool error:"))
        self.assertEqual(result["rows_consumed"], rows_consumed_before_knowledge_call)
        self.assertIsNone(result["report_payload"])
        self.assertEqual(result["messages"][-1].content, "Правила прочитаны.")
        self.assertEqual(service.calls, [])

    async def test_build_graph_injects_caller_supplied_system_prompt(self) -> None:
        service: ServiceView = StubService()
        registry = self.registry_module.ToolRegistry(service)
        tools: list[NamedTool] = self.tools_module.build_tools(registry, self.config)
        model = ScriptedModel([self.messages.AIMessage(content="Готово.")])
        graph = self.graph_module.build_graph(
            model,
            tools,
            self.memory.InMemorySaver(),
            "SENTINEL-PROMPT-42",
        )

        await self.graph_module.arun(graph, "Ответь", "prompt-thread")

        self.assertEqual(model.requests[0][0].content, "SENTINEL-PROMPT-42")

    async def test_build_graph_reinjects_caller_supplied_system_prompt_after_tool_round_trip(
        self,
    ) -> None:
        service: ServiceView = StubService()
        registry = self.registry_module.ToolRegistry(service)
        tools: list[NamedTool] = self.tools_module.build_tools(registry, self.config)
        model = ScriptedModel(
            [
                self.messages.AIMessage(
                    content="",
                    tool_calls=[tool_call("get_all_teams", {}, "prompt-tool-1")],
                ),
                self.messages.AIMessage(content="Готово."),
            ]
        )
        graph = self.graph_module.build_graph(
            model,
            tools,
            self.memory.InMemorySaver(),
            "SENTINEL-PROMPT-42",
        )
        service.results["get_all_teams"] = []

        await self.graph_module.arun(graph, "Покажи команды", "prompt-tool-thread")

        self.assertEqual(model.requests[1][0].content, "SENTINEL-PROMPT-42")

    async def test_data_call_mark_report_and_russian_answer_complete(self) -> None:
        handle: dict[str, JsonValue] = {"tool": "get_all_teams", "args": {}}
        responses = [
            self.messages.AIMessage(
                content="",
                tool_calls=[tool_call("get_all_teams", {}, "data-1")],
            ),
            self.messages.AIMessage(
                content="",
                tool_calls=[tool_call("mark_report", {"handle": handle}, "mark-1")],
            ),
            self.messages.AIMessage(content="Отчёт готов."),
        ]
        model, service, tools, graph = self.build_harness(responses)
        service.results["get_all_teams"] = [{"team_id": 1, "team_name": "Команда"}]

        result = await self.graph_module.arun(graph, "Покажи команды", "happy-thread")

        self.assertEqual(result["report_payload"], handle)
        self.assertEqual(result["messages"][-1].content, "Отчёт готов.")
        self.assertEqual(model.parallel_tool_calls, False)
        self.assertEqual(model.bound_tool_names, [tool.name for tool in tools])
        self.assertEqual(model.requests[0][0].content, DEFAULT_TEST_PROMPT)

    async def test_same_message_tool_calls_execute_in_script_order(self) -> None:
        responses = [
            self.messages.AIMessage(
                content="",
                tool_calls=[
                    tool_call("get_all_teams", {}, "ordered-1"),
                    tool_call("get_top_teams", {"limit": 2}, "ordered-2"),
                ],
            ),
            self.messages.AIMessage(content="Готово."),
        ]
        _, service, _, graph = self.build_harness(responses)
        service.results["get_all_teams"] = []
        service.results["get_top_teams"] = []

        result = await self.graph_module.arun(graph, "Сравни команды", "order-thread")
        tool_messages = [
            message
            for message in result["messages"]
            if isinstance(message, self.messages.ToolMessage)
        ]

        self.assertEqual(
            [name for name, _ in service.calls],
            ["get_all_teams", "get_top_teams"],
        )
        self.assertEqual(
            [message.tool_call_id for message in tool_messages],
            ["ordered-1", "ordered-2"],
        )

    async def test_budget_error_tool_message_can_be_followed_by_final_answer(self) -> None:
        handle: dict[str, JsonValue] = {
            "tool": "get_team_game_scores",
            "args": {"game_id": None},
        }
        calls = [
            tool_call(
                "read_rows",
                {"handle": handle, "offset": index * 256, "limit": 256},
                f"read-{index + 1}",
            )
            for index in range(5)
        ]
        responses = [
            self.messages.AIMessage(content="", tool_calls=calls),
            self.messages.AIMessage(content="Отвечаю по доступным данным."),
        ]
        _, service, _, graph = self.build_harness(responses)
        service.results["get_team_game_scores"] = self.pd.DataFrame(
            [{"game_id": index, "team_name": f"team-{index}"} for index in range(1200)]
        )

        result = await self.graph_module.arun(graph, "Прочитай всё", "budget-thread")
        tool_messages = [
            message
            for message in result["messages"]
            if isinstance(message, self.messages.ToolMessage)
        ]

        self.assertEqual(result["rows_consumed"], 1024)
        self.assertEqual(
            [message.tool_call_id for message in tool_messages],
            ["read-1", "read-2", "read-3", "read-4", "read-5"],
        )
        self.assertIn("Tool error", tool_messages[-1].content)
        self.assertEqual(result["messages"][-1].content, "Отвечаю по доступным данным.")
        self.assertEqual(len(service.calls), 4)

    async def test_endless_tool_calls_return_controlled_recursion_marker(self) -> None:
        def repeat(invocation: int) -> AgentMessageView:
            return self.messages.AIMessage(
                content="",
                tool_calls=[
                    tool_call("get_all_teams", {}, f"endless-{invocation}")
                ],
            )

        model, service, _, graph = self.build_harness([], repeat_factory=repeat)
        service.results["get_all_teams"] = []

        result = await self.graph_module.arun(graph, "Не останавливайся", "endless-thread")

        self.assertEqual(result, {"error": "recursion_limit"})
        self.assertEqual(model.invocation_count, self.config.AGENT_RECURSION_LIMIT + 1)
        self.assertEqual(len(service.calls), self.config.AGENT_RECURSION_LIMIT)


if __name__ == "__main__":
    _ = unittest.main()
