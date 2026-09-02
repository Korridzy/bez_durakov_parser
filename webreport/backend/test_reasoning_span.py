"""Acceptance instruments for the current-turn reasoning span and checkpoint serialization.

AC-2 is normative: the span test drives two user turns through the real graph and
the real wrapped client seam, and asserts BOTH directions - prior-turn reasoning
never leaves the process again, while the reasoning produced inside the current
turn is echoed back during that turn's tool loop. A no-op filter fails direction
one; a filter that strips everything fails direction two.

AC-8 guards the storage side at both layers the checkpoint stack actually uses:
the `JsonPlusSerializer` payload format and a real async SQLite saver file.
"""
import importlib
import sys
import tempfile
import unittest
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Protocol, TypeGuard
from unittest.mock import patch

sys.path.insert(0, "/")

checkpoint_base = importlib.import_module("langgraph.checkpoint.base")
config = importlib.import_module("bd_shared.config")
graph_module = importlib.import_module("agent.graph")
jsonplus = importlib.import_module("langgraph.checkpoint.serde.jsonplus")
litellm = importlib.import_module("litellm")
memory = importlib.import_module("langgraph.checkpoint.memory")
messages = importlib.import_module("langchain_core.messages")
net_guard = importlib.import_module("test_net_guard")
reasoning_module = importlib.import_module("agent.reasoning")
registry_module = importlib.import_module("agent.registry")
runtime = importlib.import_module("agents.report_runtime")
sqlite_saver = importlib.import_module("langgraph.checkpoint.sqlite.aio")
support = importlib.import_module("test_agent_support")
tools_module = importlib.import_module("agent.tools")

REASONING_KEY = "reasoning_content"
REASONING_TURN_ONE = "Первый ход: смотрю на список команд."
REASONING_TURN_TWO = "Второй ход: сверяю данные ещё раз."
TOOL_NAME = "get_all_teams"
THREAD_ID = "span-thread"


def setUpModule() -> None:
    net_guard.install()


def _scripted_response(
    *,
    content: str,
    reasoning: str | None,
    tool_call_id: str | None,
) -> object:
    message: dict[str, object] = {"role": "assistant", "content": content}
    if reasoning is not None:
        message[REASONING_KEY] = reasoning
    if tool_call_id is not None:
        message["tool_calls"] = [
            {
                "id": tool_call_id,
                "type": "function",
                "function": {"name": TOOL_NAME, "arguments": "{}"},
            }
        ]
    return litellm.ModelResponse(
        choices=[
            {
                "index": 0,
                "finish_reason": "tool_calls" if tool_call_id else "stop",
                "message": message,
            }
        ],
        model="scripted-model",
    )


def _is_object_sequence(value: object) -> TypeGuard[Sequence[object]]:
    return isinstance(value, list)


def _reasoning_values(value: object) -> list[str]:
    """Every reasoning string anywhere in an outbound payload, nesting included."""
    if isinstance(value, Mapping):
        found: list[str] = []
        for key, nested in value.items():
            if key == REASONING_KEY and isinstance(nested, str):
                found.append(nested)
            else:
                found.extend(_reasoning_values(nested))
        return found
    if isinstance(value, list):
        return [segment for item in value for segment in _reasoning_values(item)]
    return []


class StoredAIMessage(Protocol):
    """The checkpoint-message attributes the serialization guard compares."""

    content: object
    additional_kwargs: dict[str, object]
    tool_calls: list[dict[str, object]]


def _role_count(request: Sequence[object], role: str) -> int:
    return sum(
        1
        for message in request
        if isinstance(message, Mapping) and message.get("role") == role
    )


class TestCurrentTurnSpan(unittest.IsolatedAsyncioTestCase):
    async def test_prior_turn_reasoning_is_dropped_while_current_turn_is_echoed(self) -> None:
        recorded_requests: list[Sequence[object]] = []
        responses = [
            _scripted_response(
                content="Беру команды.",
                reasoning=REASONING_TURN_ONE,
                tool_call_id="turn-1-tool",
            ),
            _scripted_response(content="Первый ответ.", reasoning=None, tool_call_id=None),
            _scripted_response(
                content="Беру команды снова.",
                reasoning=REASONING_TURN_TWO,
                tool_call_id="turn-2-tool",
            ),
            _scripted_response(content="Второй ответ.", reasoning=None, tool_call_id=None),
        ]

        async def fake_acompletion(**kwargs: object) -> object:
            raw_messages = kwargs["messages"]
            if not _is_object_sequence(raw_messages):
                raise AssertionError("LiteLLM completion messages must be a list")
            recorded_requests.append(raw_messages)
            return responses.pop(0)

        service = support.StubService()
        service.results[TOOL_NAME] = []
        registry = registry_module.ToolRegistry(service)
        tools = tools_module.build_tools(registry, config)
        client = runtime._new_model_client()
        graph = graph_module.build_graph(client, tools, memory.InMemorySaver())

        with patch.object(litellm, "acompletion", fake_acompletion):
            first_turn = await graph_module.arun(graph, "Покажи команды", THREAD_ID)
            second_turn = await graph_module.arun(graph, "Повтори проверку", THREAD_ID)

        self.assertEqual(
            reasoning_module.extract_text(first_turn["messages"][-1].content),
            "Первый ответ.",
        )
        self.assertEqual(
            reasoning_module.extract_text(second_turn["messages"][-1].content),
            "Второй ответ.",
        )
        self.assertEqual(len(recorded_requests), 4)

        turn_one_second_call = recorded_requests[1]
        turn_two_first_call = recorded_requests[2]
        turn_two_second_call = recorded_requests[3]

        # The turn-2 calls really do carry the whole prior turn, so an empty
        # reasoning list below cannot be an artifact of a truncated history.
        self.assertEqual(_role_count(turn_two_first_call, "user"), 2)
        self.assertEqual(_role_count(turn_two_first_call, "assistant"), 2)
        self.assertEqual(_role_count(turn_two_second_call, "assistant"), 3)

        # Direction one: reasoning produced before the last human message is gone.
        self.assertEqual(_reasoning_values(list(turn_two_first_call)), [])
        self.assertEqual(_reasoning_values(list(turn_two_second_call)), [REASONING_TURN_TWO])

        # Direction two: within its own turn, reasoning is echoed back verbatim.
        self.assertEqual(_reasoning_values(list(turn_one_second_call)), [REASONING_TURN_ONE])


class TestCheckpointSerialization(unittest.IsolatedAsyncioTestCase):
    def _message(
        self,
        reasoning: str = REASONING_TURN_ONE,
        answer: str = "Часть B.",
    ) -> StoredAIMessage:
        return messages.AIMessage(
            content=[
                {"type": "text", "text": "Часть A."},
                {"type": "text", "text": answer},
            ],
            additional_kwargs={REASONING_KEY: reasoning},
            tool_calls=[
                {"name": TOOL_NAME, "args": {}, "id": "serde-tool-1", "type": "tool_call"}
            ],
        )

    def test_json_plus_round_trip_keeps_blocks_reasoning_and_tool_calls(self) -> None:
        message = self._message()
        serializer = jsonplus.JsonPlusSerializer()

        restored = serializer.loads_typed(serializer.dumps_typed(message))

        self.assertEqual(restored.content, message.content)
        self.assertEqual(restored.additional_kwargs[REASONING_KEY], REASONING_TURN_ONE)
        self.assertEqual(restored.tool_calls, message.tool_calls)

    def test_json_plus_round_trip_detects_a_mutated_payload(self) -> None:
        reference = self._message()
        mutated = self._message(reasoning="Подменённая мысль.", answer="Часть Z.")
        serializer = jsonplus.JsonPlusSerializer()

        restored = serializer.loads_typed(serializer.dumps_typed(mutated))

        self.assertNotEqual(restored.content, reference.content)
        self.assertNotEqual(
            restored.additional_kwargs[REASONING_KEY],
            reference.additional_kwargs[REASONING_KEY],
        )

    async def test_sqlite_saver_round_trip_keeps_blocks_reasoning_and_tool_calls(self) -> None:
        message = self._message()
        thread_config = {"configurable": {"thread_id": "span-serde", "checkpoint_ns": ""}}

        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            database = str(Path(directory) / "span-checkpoints.db")
            async with sqlite_saver.AsyncSqliteSaver.from_conn_string(database) as saver:
                await saver.setup()
                checkpoint = checkpoint_base.empty_checkpoint()
                checkpoint["channel_values"] = {"messages": [message]}
                checkpoint["channel_versions"] = {"messages": "1"}
                await saver.aput(
                    thread_config,
                    checkpoint,
                    {"source": "input", "step": 0, "parents": {}},
                    {"messages": "1"},
                )
                loaded = await saver.aget_tuple(thread_config)

                self.assertIsNotNone(loaded)
                assert loaded is not None
                restored = loaded.checkpoint["channel_values"]["messages"][0]

                self.assertEqual(restored.content, message.content)
                self.assertEqual(restored.additional_kwargs[REASONING_KEY], REASONING_TURN_ONE)
                self.assertEqual(restored.tool_calls, message.tool_calls)


if __name__ == "__main__":
    unittest.main()
