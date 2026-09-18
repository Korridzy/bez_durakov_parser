"""Shared fixtures for the public TestTools family."""
import importlib
import json
import unittest
from typing import Any

_support = importlib.import_module("test_agent_support")
TOOL_NAMES = _support.TOOL_NAMES
TOOL_PARAMS = _support.TOOL_PARAMS
StubService = _support.StubService


class ToolsCaseBase(unittest.IsolatedAsyncioTestCase):
    """Build real LangGraph ToolNode executions around a stubbed service boundary."""

    def __init__(self, methodName: str = "runTest"):
        super().__init__(methodName)
        self.service: StubService = StubService()
        self.registry: Any = None
        self.tools: dict[str, Any] = {}

    @classmethod
    def setUpClass(cls):
        cls.pd = importlib.import_module("pandas")
        cls.config = importlib.import_module("bd_shared.config")
        cls.messages = importlib.import_module("langchain_core.messages")
        cls.graph = importlib.import_module("langgraph.graph")
        cls.prebuilt = importlib.import_module("langgraph.prebuilt")
        cls.registry_module = importlib.import_module("agent.registry")
        cls.state_module = importlib.import_module("agent.state")
        cls.tools_module = importlib.import_module("agent.tools")

    def setUp(self):
        self.service = StubService()
        self.registry = self.registry_module.ToolRegistry(self.service)
        built = self.tools_module.build_tools(self.registry, self.config)
        self.tools = {tool.name: tool for tool in built}

    def set_rows(self, count: int) -> None:
        self.service.results["get_team_game_scores"] = self.pd.DataFrame(
            [{"game_id": index, "team_name": f"team-{index}"} for index in range(count)]
        )

    async def invoke_tool(
        self,
        name: str,
        args: dict[str, Any],
        *,
        state: dict[str, Any] | None = None,
        call_id: str = "call-1",
    ) -> dict[str, Any]:
        current = state or {
            "messages": [],
            "report_payload": None,
            "rows_consumed": 0,
            "knowledge_bytes_consumed": 0,
        }
        tool_call = {
            "name": name,
            "args": args,
            "id": call_id,
            "type": "tool_call",
        }
        message = self.messages.AIMessage(content="", tool_calls=[tool_call])
        builder = self.graph.StateGraph(self.state_module.GraphState)
        builder.add_node("tools", self.prebuilt.ToolNode(list(self.tools.values())))
        builder.set_entry_point("tools")
        builder.set_finish_point("tools")
        compiled = builder.compile()
        return await compiled.ainvoke(
            {
                "messages": [*current["messages"], message],
                "report_payload": current["report_payload"],
                "rows_consumed": current["rows_consumed"],
                "knowledge_bytes_consumed": current.get(
                    "knowledge_bytes_consumed",
                    0,
                ),
            }
        )

    def latest_tool_message(self, state: dict[str, Any]):
        message = state["messages"][-1]
        self.assertIsInstance(message, self.messages.ToolMessage)
        return message

    def latest_json(self, state: dict[str, Any]) -> dict[str, Any]:
        content = self.latest_tool_message(state).content
        self.assertIsInstance(content, str)
        return json.loads(content)


if __name__ == "__main__":
    unittest.main()
