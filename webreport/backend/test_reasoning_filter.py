"""Tests for agent/reasoning.py: outbound reasoning filter and extraction helpers.

Import-light at module level, same convention as test_agent.py: the module under
test and langchain_core are resolved inside setUpClass, so this file stays
runnable before its implementation lands.
"""
import importlib
import sys
import unittest
from collections.abc import Sequence
from typing import ClassVar, Protocol, final

# Parent of the mounted bd_shared directory, same convention as main.py:16
sys.path.insert(0, '/')

net_guard = importlib.import_module("test_net_guard")


def setUpModule():
    """Offline suite: only loopback and the Compose database host are reachable."""
    net_guard.install()


class _ReasoningImports:
    """Resolves the module under test once per class."""

    reasoning: ClassVar
    messages: ClassVar

    @classmethod
    def setUpClass(cls):
        cls.reasoning = importlib.import_module("agent.reasoning")
        cls.messages = importlib.import_module("langchain_core.messages")


@final
class StubTool:
    def __init__(self, name: str) -> None:
        self.name = name


class MessageView(Protocol):
    """What the assertions read off a recorded outbound message."""

    content: object
    additional_kwargs: dict[str, object]


@final
class RecordingBoundModel:
    """Records every outbound message sequence the filter forwards."""

    def __init__(self, response: object) -> None:
        self.requests: list[Sequence[MessageView]] = []
        self._response = response

    async def ainvoke(self, messages: Sequence[MessageView]) -> object:
        self.requests.append(messages)
        return self._response


@final
class RecordingClient:
    def __init__(self, bound: RecordingBoundModel) -> None:
        self.bound = bound
        self.bound_tool_names: list[str] = []
        self.parallel_tool_calls: bool | None = None

    def bind_tools(
        self,
        tools: Sequence[StubTool],
        *,
        parallel_tool_calls: bool,
    ) -> RecordingBoundModel:
        self.bound_tool_names = [tool.name for tool in tools]
        self.parallel_tool_calls = parallel_tool_calls
        return self.bound


class TestExtractText(_ReasoningImports, unittest.TestCase):
    """extract_text: string content passes through, block lists are joined."""

    def test_plain_string_passes_through(self):
        """Given a str, When extracted, Then the same text is returned."""
        self.assertEqual(self.reasoning.extract_text("готовый ответ"), "готовый ответ")

    def test_empty_string_stays_empty(self):
        """Given an empty str, When extracted, Then the result is empty."""
        self.assertEqual(self.reasoning.extract_text(""), "")

    def test_text_blocks_joined_with_blank_line(self):
        """Given text blocks, When extracted, Then they join with a blank line."""
        content = [{"type": "text", "text": "A"}, {"type": "text", "text": "B"}]

        self.assertEqual(self.reasoning.extract_text(content), "A\n\nB")

    def test_non_text_blocks_are_skipped(self):
        """Given mixed blocks, When extracted, Then only text blocks contribute."""
        content = [
            {"type": "thinking", "thinking": "скрытое"},
            {"type": "text", "text": "видимое"},
            {"type": "tool_use", "id": "call_1"},
            "не блок",
        ]

        self.assertEqual(self.reasoning.extract_text(content), "видимое")

    def test_block_text_is_coerced_to_str(self):
        """Given a non-str text field, When extracted, Then it is stringified."""
        self.assertEqual(self.reasoning.extract_text([{"type": "text", "text": 7}]), "7")

    def test_empty_list_yields_empty_string(self):
        """Given no blocks, When extracted, Then the result is empty."""
        self.assertEqual(self.reasoning.extract_text([]), "")

    def test_other_values_are_stringified(self):
        """Given neither str nor list, When extracted, Then str() is applied."""
        self.assertEqual(self.reasoning.extract_text(7), "7")
        self.assertEqual(self.reasoning.extract_text(None), "None")


class TestExtractReasoning(_ReasoningImports, unittest.TestCase):
    """extract_reasoning and current_turn_reasoning over message sequences."""

    def _ai(self, content: str, reasoning: str | None = None):
        extra = {} if reasoning is None else {"reasoning_content": reasoning}
        return self.messages.AIMessage(content=content, additional_kwargs=extra)

    def test_segments_join_in_order(self):
        """Given several reasoning messages, When extracted, Then order is preserved."""
        collected = self.reasoning.extract_reasoning(
            [self._ai("", "Шаг 1"), self._ai("ответ", "Шаг 2")]
        )

        self.assertEqual(collected, "Шаг 1\n\nШаг 2")

    def test_messages_without_reasoning_are_ignored(self):
        """Given a mixed sequence, When extracted, Then only reasoning contributes."""
        collected = self.reasoning.extract_reasoning(
            [
                self.messages.HumanMessage(content="вопрос"),
                self._ai("промежуточный"),
                self._ai("ответ", "Шаг 1"),
            ]
        )

        self.assertEqual(collected, "Шаг 1")

    def test_no_reasoning_yields_none(self):
        """Given no reasoning anywhere, When extracted, Then the result is None."""
        self.assertIsNone(self.reasoning.extract_reasoning([self._ai("ответ")]))

    def test_empty_sequence_yields_none(self):
        """Given no messages, When extracted, Then the result is None."""
        self.assertIsNone(self.reasoning.extract_reasoning([]))

    def test_whitespace_only_reasoning_yields_none(self):
        """Given blank reasoning, When extracted, Then the result is None."""
        self.assertIsNone(self.reasoning.extract_reasoning([self._ai("ответ", "   \n")]))

    def test_non_string_reasoning_is_ignored(self):
        """Given a non-str reasoning value, When extracted, Then it is skipped."""
        message = self.messages.AIMessage(
            content="ответ", additional_kwargs={"reasoning_content": {"blocks": []}}
        )

        self.assertIsNone(self.reasoning.extract_reasoning([message]))

    def test_objects_without_additional_kwargs_are_tolerated(self):
        """Given a foreign object, When extracted, Then it contributes nothing."""
        self.assertIsNone(self.reasoning.extract_reasoning([object()]))

    def test_current_turn_starts_after_the_last_human(self):
        """Given two turns, When the current turn is read, Then prior turns are excluded."""
        history = [
            self.messages.HumanMessage(content="первый"),
            self._ai("ответ 1", "Прошлый шаг"),
            self.messages.HumanMessage(content="второй"),
            self._ai("", "Текущий шаг 1"),
            self._ai("ответ 2", "Текущий шаг 2"),
        ]

        collected = self.reasoning.current_turn_reasoning(history)

        self.assertEqual(collected, "Текущий шаг 1\n\nТекущий шаг 2")

    def test_current_turn_without_human_yields_none(self):
        """Given no human message, When the current turn is read, Then it is None."""
        self.assertIsNone(self.reasoning.current_turn_reasoning([self._ai("x", "Шаг")]))

    def test_current_turn_with_nothing_after_human_yields_none(self):
        """Given a trailing human message, When the current turn is read, Then None."""
        history = [self._ai("ответ", "Шаг"), self.messages.HumanMessage(content="ещё")]

        self.assertIsNone(self.reasoning.current_turn_reasoning(history))

    def test_current_turn_never_raises_on_empty_input(self):
        """Given no messages, When the current turn is read, Then None, not an error."""
        self.assertIsNone(self.reasoning.current_turn_reasoning([]))


class TestOutboundReasoningFilter(_ReasoningImports, unittest.IsolatedAsyncioTestCase):
    """The wrapper echoes current-turn reasoning only, without mutating state."""

    def _ai(self, content: str, reasoning: str | None = None, **extra):
        kwargs = dict(extra)
        if reasoning is not None:
            kwargs["reasoning_content"] = reasoning
        return self.messages.AIMessage(content=content, additional_kwargs=kwargs)

    def _wrap(self, response: object | None = None):
        bound = RecordingBoundModel(response or self.messages.AIMessage(content="ok"))
        client = RecordingClient(bound)
        return client, bound, self.reasoning.OutboundReasoningFilter(client)

    async def test_bind_tools_delegates_to_the_wrapped_client(self):
        """Given tools, When bound, Then the wrapped client receives them verbatim."""
        client, _, wrapper = self._wrap()

        bound = wrapper.bind_tools([StubTool("list_games")], parallel_tool_calls=False)

        self.assertEqual(client.bound_tool_names, ["list_games"])
        self.assertIs(client.parallel_tool_calls, False)
        self.assertTrue(hasattr(bound, "ainvoke"))

    async def test_bound_model_returns_the_wrapped_response(self):
        """Given a scripted response, When invoked, Then it is returned unchanged."""
        response = self.messages.AIMessage(content="итог")
        _, _, wrapper = self._wrap(response)
        bound = wrapper.bind_tools([], parallel_tool_calls=False)

        self.assertIs(await bound.ainvoke([self.messages.HumanMessage(content="?")]), response)

    async def test_prior_turn_reasoning_is_stripped_current_turn_kept(self):
        """Given two turns, When invoked, Then only current-turn reasoning goes out."""
        prior = self._ai("ответ 1", "Прошлый шаг")
        current = self._ai("", "Текущий шаг")
        history = [
            self.messages.SystemMessage(content="системная подсказка"),
            self.messages.HumanMessage(content="первый"),
            prior,
            self.messages.HumanMessage(content="второй"),
            current,
        ]
        _, bound_double, wrapper = self._wrap()
        bound = wrapper.bind_tools([], parallel_tool_calls=False)

        await bound.ainvoke(history)

        sent = list(bound_double.requests[0])
        self.assertEqual(len(sent), len(history))
        self.assertNotIn("reasoning_content", sent[2].additional_kwargs)
        self.assertEqual(sent[4].additional_kwargs["reasoning_content"], "Текущий шаг")
        self.assertIs(sent[4], current)

    async def test_stripped_copy_preserves_content_and_other_kwargs(self):
        """Given extra kwargs, When stripped, Then only reasoning_content is dropped."""
        prior = self._ai("ответ 1", "Прошлый шаг", refusal=None)
        history = [prior, self.messages.HumanMessage(content="второй")]
        _, bound_double, wrapper = self._wrap()
        bound = wrapper.bind_tools([], parallel_tool_calls=False)

        await bound.ainvoke(history)

        stripped = bound_double.requests[0][0]
        self.assertIsNot(stripped, prior)
        self.assertEqual(stripped.content, "ответ 1")
        self.assertEqual(stripped.additional_kwargs, {"refusal": None})

    async def test_messages_without_reasoning_pass_by_identity(self):
        """Given no reasoning, When invoked, Then the same objects are forwarded."""
        history = [
            self.messages.SystemMessage(content="системная подсказка"),
            self.messages.HumanMessage(content="первый"),
            self._ai("ответ 1"),
            self.messages.HumanMessage(content="второй"),
        ]
        _, bound_double, wrapper = self._wrap()
        bound = wrapper.bind_tools([], parallel_tool_calls=False)

        await bound.ainvoke(history)

        for index, original in enumerate(history):
            with self.subTest(index=index):
                self.assertIs(bound_double.requests[0][index], original)

    async def test_absent_human_message_leaves_everything_untouched(self):
        """Given no human message, When invoked, Then nothing is stripped."""
        prior = self._ai("ответ", "Шаг")
        history = [self.messages.SystemMessage(content="подсказка"), prior]
        _, bound_double, wrapper = self._wrap()
        bound = wrapper.bind_tools([], parallel_tool_calls=False)

        await bound.ainvoke(history)

        self.assertIs(bound_double.requests[0][1], prior)

    async def test_inputs_are_never_mutated(self):
        """Given a prior-turn thought, When stripped, Then the input keeps it."""
        prior = self._ai("ответ 1", "Прошлый шаг")
        snapshot = dict(prior.additional_kwargs)
        history = [prior, self.messages.HumanMessage(content="второй")]
        originals = list(history)
        _, _, wrapper = self._wrap()
        bound = wrapper.bind_tools([], parallel_tool_calls=False)

        await bound.ainvoke(history)

        self.assertEqual(prior.additional_kwargs, snapshot)
        self.assertEqual(prior.additional_kwargs["reasoning_content"], "Прошлый шаг")
        self.assertEqual(history, originals)
        self.assertIs(history[0], prior)


if __name__ == "__main__":
    unittest.main()
