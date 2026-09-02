import importlib
import sys
import unittest
from collections.abc import Mapping, Sequence
from typing import TypeGuard
from unittest.mock import patch

sys.path.insert(0, "/")

litellm = importlib.import_module("litellm")
messages = importlib.import_module("langchain_core.messages")
net_guard = importlib.import_module("test_net_guard")
runtime = importlib.import_module("agents.report_runtime")

REASONING = "reasoning content"
TOOL_CALL_ID = "call-get-games"


def setUpModule() -> None:
    net_guard.install()


def _scripted_response(*, reasoning: str | None, tool_call: bool) -> object:
    message: dict[str, object] = {"role": "assistant", "content": "Model reply."}
    if reasoning is not None:
        message["reasoning_content"] = reasoning
    if tool_call:
        message["tool_calls"] = [
            {
                "id": TOOL_CALL_ID,
                "type": "function",
                "function": {"name": "get_all_games_summary", "arguments": "{}"},
            }
        ]
    return litellm.ModelResponse(
        choices=[
            {
                "index": 0,
                "finish_reason": "tool_calls" if tool_call else "stop",
                "message": message,
            }
        ],
        model="scripted-model",
    )


def _is_object_sequence(value: object) -> TypeGuard[Sequence[object]]:
    return isinstance(value, list)


def _contains_reasoning_key(value: object) -> bool:
    if isinstance(value, Mapping):
        return "reasoning_content" in value or any(
            _contains_reasoning_key(nested) for nested in value.values()
        )
    if isinstance(value, list):
        return any(_contains_reasoning_key(item) for item in value)
    return False


def _contains_thinking_block(messages_to_check: Sequence[object]) -> bool:
    for message in messages_to_check:
        if not isinstance(message, Mapping):
            continue
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if isinstance(block, Mapping) and block.get("type") in {"thinking", "reasoning"}:
                return True
    return False


class TestEchoTripwire(unittest.IsolatedAsyncioTestCase):
    async def test_echoes_reasoning_within_tool_turn_without_thinking_blocks(self) -> None:
        recorded_requests: list[Sequence[object]] = []
        responses = [
            _scripted_response(reasoning=REASONING, tool_call=True),
            _scripted_response(reasoning=None, tool_call=False),
        ]

        async def fake_acompletion(**kwargs: object) -> object:
            raw_messages = kwargs["messages"]
            if not _is_object_sequence(raw_messages):
                raise AssertionError("LiteLLM completion messages must be a list")
            recorded_requests.append(raw_messages)
            return responses.pop(0)

        client = runtime._new_model_client()
        bound = client.bind_tools([], parallel_tool_calls=False)

        with patch.object(litellm, "acompletion", fake_acompletion):
            first_response = await bound.ainvoke([messages.HumanMessage(content="Request.")])
            self.assertEqual(first_response.additional_kwargs["reasoning_content"], REASONING)
            self.assertEqual(first_response.tool_calls[0]["id"], TOOL_CALL_ID)
            await bound.ainvoke(
                [
                    messages.HumanMessage(content="Request."),
                    first_response,
                    messages.ToolMessage(content="[]", tool_call_id=TOOL_CALL_ID),
                ]
            )

        self.assertEqual(len(recorded_requests), 2)
        assistant_messages = [
            message
            for message in recorded_requests[1]
            if isinstance(message, Mapping) and message.get("role") == "assistant"
        ]
        self.assertEqual(assistant_messages[0]["reasoning_content"], REASONING)
        self.assertFalse(_contains_thinking_block(recorded_requests[1]))


class TestNoReasoningNoOp(unittest.IsolatedAsyncioTestCase):
    async def test_keeps_plain_string_and_omits_reasoning_keys_when_model_has_none(self) -> None:
        recorded_requests: list[Sequence[object]] = []

        async def fake_acompletion(**kwargs: object) -> object:
            raw_messages = kwargs["messages"]
            if not _is_object_sequence(raw_messages):
                raise AssertionError("LiteLLM completion messages must be a list")
            recorded_requests.append(raw_messages)
            return _scripted_response(reasoning=None, tool_call=False)

        client = runtime._new_model_client()
        bound = client.bind_tools([], parallel_tool_calls=False)

        with patch.object(litellm, "acompletion", fake_acompletion):
            response = await bound.ainvoke([messages.HumanMessage(content="Request.")])

        self.assertIsInstance(response.content, str)
        self.assertNotIn("reasoning_content", response.additional_kwargs)
        self.assertFalse(any(_contains_reasoning_key(request) for request in recorded_requests))


if __name__ == "__main__":
    unittest.main()
