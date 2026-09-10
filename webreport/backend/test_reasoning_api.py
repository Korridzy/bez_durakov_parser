"""Tests for the reasoning surfaced on /api/chat and /api/history.

Import-light at module level, same convention as test_reasoning_filter.py: the
FastAPI module under test and langchain_core are resolved inside setUpClass, so
this file stays runnable before its implementation lands.

The endpoint classes drive the real route coroutines directly with the module
globals replaced by doubles - no server, no startup probe, no network.
"""
import asyncio
import importlib
import json
import sys
import unittest
from collections.abc import Mapping
from types import SimpleNamespace
from typing import ClassVar, final

# Parent of the mounted bd_shared directory, same convention as main.py:16
sys.path.insert(0, '/')

net_guard = importlib.import_module("test_net_guard")


def setUpModule():
    """Offline suite: only loopback and the Compose database host are reachable."""
    net_guard.install()


class _MainImports:
    """Resolves the module under test once per class."""

    main: ClassVar
    messages: ClassVar

    @classmethod
    def setUpClass(cls):
        cls.main = importlib.import_module("main")
        cls.messages = importlib.import_module("langchain_core.messages")


@final
class StubAgentSystem:
    """Agent system double returning one scripted ReportResponse."""

    def __init__(self, response: Mapping[str, object]) -> None:
        self.response = dict(response)
        self.calls: list[tuple[str, str]] = []

    async def process_user_request(
        self, user_message: str, session_id: str
    ) -> dict[str, object]:
        self.calls.append((user_message, session_id))
        return dict(self.response)


@final
class StubSaver:
    """Checkpoint saver double: one canned tuple, deletions recorded."""

    def __init__(self, checkpoint_tuple: object = None) -> None:
        self.checkpoint_tuple = checkpoint_tuple
        self.deleted: list[str] = []

    async def aget_tuple(self, config: Mapping[str, object]) -> object:
        return self.checkpoint_tuple

    async def adelete_thread(self, thread_id: str) -> None:
        self.deleted.append(thread_id)


class _EndpointHarness:
    """Swaps the module globals a route reads, and restores them afterwards."""

    saved: dict[str, object] = {}
    main: ClassVar

    async def asyncSetUp(self):
        session_store = importlib.import_module("session_store")
        self.saved = {
            name: getattr(self.main, name)
            for name in (
                "admission_lock",
                "agent_system",
                "checkpoint_saver",
                "pinned",
                "sessions",
            )
        }
        self.main.admission_lock = asyncio.Lock()
        self.main.pinned = {}
        self.main.sessions = session_store.SessionIndex(max_size=4, ttl=60)

    async def asyncTearDown(self):
        for name, value in self.saved.items():
            setattr(self.main, name, value)


def _report_response(**overrides: object) -> dict[str, object]:
    """A ReportResponse-shaped dict the chat route can consume."""
    response: dict[str, object] = {
        "success": True,
        "data": None,
        "message": "готовый ответ",
        "mode": "agent",
        "query_info": [{"tool": "list_games", "args": {}}],
        "timestamp": "2026-08-07T00:00:00",
    }
    response.update(overrides)
    return response


KNOWLEDGE_DOCUMENT_BODY = "\n".join(
    f"KNOWLEDGE_FIXTURE_DOCUMENT_LINE_{index:03d}" for index in range(64)
)
KNOWLEDGE_DOCUMENT = f"# knowledge-fixture\n\n{KNOWLEDGE_DOCUMENT_BODY}"
KNOWLEDGE_TOOL_CALL_ID = "knowledge-call-1"


def _read_knowledge_turn(messages):
    return [
        messages.HumanMessage(content="вопрос о правилах"),
        messages.AIMessage(
            content="",
            additional_kwargs={"reasoning_content": "Шаг 1"},
            tool_calls=[
                {
                    "name": "read_knowledge",
                    "args": {"topic_id": "fixture-topic"},
                    "id": KNOWLEDGE_TOOL_CALL_ID,
                }
            ],
        ),
        messages.ToolMessage(
            content=KNOWLEDGE_DOCUMENT,
            tool_call_id=KNOWLEDGE_TOOL_CALL_ID,
        ),
        messages.AIMessage(
            content="ответ",
            additional_kwargs={"reasoning_content": "Шаг 2"},
        ),
    ]


class TestHistoryEntries(_MainImports, unittest.TestCase):
    """_history_entries: whitelist, text extraction, per-turn reasoning."""

    def _ai(self, content: object, reasoning: str | None = None, **extra):
        kwargs = {} if reasoning is None else {"reasoning_content": reasoning}
        return self.messages.AIMessage(
            content=content, additional_kwargs=kwargs, **extra
        )

    def _tool_call_ai(self, reasoning: str | None = None):
        return self._ai(
            "",
            reasoning,
            tool_calls=[{"name": "list_games", "args": {}, "id": "call-1"}],
        )

    def test_empty_history_yields_no_entries(self):
        """Given no messages, When entries are built, Then the list is empty."""
        self.assertEqual(self.main._history_entries([]), [])

    def test_plain_string_content_passes_through(self):
        """Given str content, When entries are built, Then the text is unchanged."""
        stored = [self.messages.HumanMessage(content="вопрос"), self._ai("ответ")]

        entries = self.main._history_entries(stored)

        self.assertEqual(entries[0]["content"], "вопрос")
        self.assertEqual(entries[1]["content"], "ответ")

    def test_user_content_blocks_are_extracted(self):
        """Given block-list user content, When built, Then blocks join as text."""
        stored = [
            self.messages.HumanMessage(
                content=[{"type": "text", "text": "A"}, {"type": "text", "text": "B"}]
            )
        ]

        entries = self.main._history_entries(stored)

        self.assertEqual(entries, [{"role": "user", "content": "A\n\nB"}])

    def test_assistant_content_blocks_are_extracted(self):
        """Given block-list answer content, When built, Then blocks join as text."""
        stored = [
            self.messages.HumanMessage(content="вопрос"),
            self._ai([{"type": "text", "text": "Ответ"}, {"type": "text", "text": "Итог"}]),
        ]

        entries = self.main._history_entries(stored)

        self.assertEqual(entries[1]["content"], "Ответ\n\nИтог")

    def test_reasoning_attaches_to_the_final_answer_only(self):
        """Given a tool step, When built, Then its thought lands on the answer entry."""
        stored = [
            self.messages.HumanMessage(content="вопрос"),
            self._tool_call_ai("Шаг 1"),
            self.messages.ToolMessage(content="данные", tool_call_id="call-1"),
            self._ai("ответ", "Шаг 2"),
        ]

        entries = self.main._history_entries(stored)

        self.assertEqual(
            entries,
            [
                {"role": "user", "content": "вопрос"},
                {
                    "role": "assistant",
                    "content": "ответ",
                    "reasoning": "Шаг 1\n\nШаг 2",
                },
            ],
        )

    def test_read_knowledge_turn_hides_document_and_keeps_reasoning(self):
        """Given a knowledge tool turn, When built, Then only its chat entries remain."""
        entries = self.main._history_entries(_read_knowledge_turn(self.messages))

        self.assertEqual(len(entries), 2)
        self.assertEqual(
            entries,
            [
                {"role": "user", "content": "вопрос о правилах"},
                {
                    "role": "assistant",
                    "content": "ответ",
                    "reasoning": "Шаг 1\n\nШаг 2",
                },
            ],
        )
        for entry in entries:
            self.assertNotIn(KNOWLEDGE_DOCUMENT_BODY, entry["content"])

    def test_assistant_entry_carries_a_null_reasoning_key_when_absent(self):
        """Given no thought, When built, Then the key is present and None."""
        stored = [self.messages.HumanMessage(content="вопрос"), self._ai("ответ")]

        entries = self.main._history_entries(stored)

        self.assertIn("reasoning", entries[1])
        self.assertIsNone(entries[1]["reasoning"])

    def test_whitespace_only_reasoning_becomes_none(self):
        """Given a blank thought, When built, Then the entry reasoning is None."""
        stored = [
            self.messages.HumanMessage(content="вопрос"),
            self._ai("ответ", "   \n"),
        ]

        entries = self.main._history_entries(stored)

        self.assertIsNone(entries[1]["reasoning"])

    def test_reasoning_resets_at_each_human_message(self):
        """Given two turns, When built, Then each answer carries only its own turn."""
        stored = [
            self.messages.HumanMessage(content="первый"),
            self._ai("ответ 1", "Прошлый шаг"),
            self.messages.HumanMessage(content="второй"),
            self._tool_call_ai("Текущий шаг 1"),
            self._ai("ответ 2", "Текущий шаг 2"),
        ]

        entries = self.main._history_entries(stored)

        self.assertEqual(entries[1]["reasoning"], "Прошлый шаг")
        self.assertEqual(
            entries[3]["reasoning"], "Текущий шаг 1\n\nТекущий шаг 2"
        )

    def test_user_entries_carry_no_reasoning_key(self):
        """Given a user message, When built, Then only role and content are present."""
        entries = self.main._history_entries(
            [self.messages.HumanMessage(content="вопрос")]
        )

        self.assertEqual(list(entries[0]), ["role", "content"])

    def test_tool_and_system_messages_are_ignored(self):
        """Given non-chat messages, When built, Then they produce no entries."""
        stored = [
            self.messages.SystemMessage(content="подсказка"),
            self.messages.HumanMessage(content="вопрос"),
            self._tool_call_ai(),
            self.messages.ToolMessage(content="данные", tool_call_id="call-1"),
        ]

        entries = self.main._history_entries(stored)

        self.assertEqual(entries, [{"role": "user", "content": "вопрос"}])


class TestChatResponseShape(_MainImports, unittest.TestCase):
    """ChatResponse always serializes a reasoning key."""

    def _response(self, **overrides: object):
        fields: dict[str, object] = {
            "success": True,
            "session_id": "s-1",
            "mode": "agent",
            "query_info": [],
            "message": "ответ",
            "timestamp": "2026-08-07T00:00:00",
        }
        fields.update(overrides)
        return self.main.ChatResponse(**fields)

    def test_model_dump_always_contains_reasoning(self):
        """Given no reasoning, When dumped, Then the key is present and None."""
        dumped = self._response().model_dump()

        self.assertIn("reasoning", dumped)
        self.assertIsNone(dumped["reasoning"])

    def test_model_dump_json_is_null_when_absent(self):
        """Given no reasoning, When serialized, Then JSON carries an explicit null."""
        payload = json.loads(self._response().model_dump_json())

        self.assertIn("reasoning", payload)
        self.assertIsNone(payload["reasoning"])

    def test_reasoning_round_trips_when_present(self):
        """Given a thought, When serialized, Then the exact text survives."""
        payload = json.loads(
            self._response(reasoning="Шаг 1\n\nШаг 2").model_dump_json()
        )

        self.assertEqual(payload["reasoning"], "Шаг 1\n\nШаг 2")


class TestChatEndpointReasoning(
    _MainImports, _EndpointHarness, unittest.IsolatedAsyncioTestCase
):
    """/api/chat forwards the reasoning the agent system reports."""

    async def _chat(self, response: Mapping[str, object], session_id: str = "s-1"):
        self.main.agent_system = StubAgentSystem(response)
        self.main.checkpoint_saver = StubSaver()
        return await self.main.chat(
            self.main.ChatMessage(message="покажи игры", session_id=session_id)
        )

    async def test_chat_forwards_reasoning_to_the_response(self):
        """Given a reasoning-bearing result, When chatting, Then JSON carries it."""
        result = await self._chat(_report_response(reasoning="Шаг 1\n\nШаг 2"))

        self.assertEqual(result.reasoning, "Шаг 1\n\nШаг 2")
        payload = json.loads(result.model_dump_json())
        self.assertEqual(payload["reasoning"], "Шаг 1\n\nШаг 2")

    async def test_chat_read_knowledge_matches_data_tool_response_shape(self):
        """Given a knowledge tool result, When chatting, Then its JSON shape is unchanged."""
        data_tool = await self._chat(_report_response())
        knowledge_query = [
            {"tool": "read_knowledge", "args": {"topic_id": "fixture-topic"}}
        ]
        knowledge = await self._chat(
            _report_response(
                query_info=knowledge_query,
                reasoning="Шаг 1\n\nШаг 2",
            )
        )

        data_payload = json.loads(data_tool.model_dump_json())
        knowledge_payload = json.loads(knowledge.model_dump_json())

        self.assertEqual(set(knowledge_payload), set(data_payload))
        self.assertEqual(knowledge_payload["query_info"], knowledge_query)
        self.assertEqual(knowledge_payload["reasoning"], "Шаг 1\n\nШаг 2")
        for value in knowledge_payload.values():
            self.assertNotIn(KNOWLEDGE_DOCUMENT_BODY, str(value))

    async def test_chat_without_reasoning_serializes_null(self):
        """Given a result without reasoning, When chatting, Then JSON holds null."""
        result = await self._chat(_report_response())

        payload = json.loads(result.model_dump_json())
        self.assertIn("reasoning", payload)
        self.assertIsNone(payload["reasoning"])

    async def test_failed_result_keeps_both_error_and_partial_reasoning(self):
        """Given a failure with a partial thought, When chatting, Then both survive."""
        result = await self._chat(
            _report_response(
                success=False,
                error="Превышено время ожидания",
                reasoning="Шаг 1",
            )
        )

        self.assertFalse(result.success)
        self.assertEqual(result.error, "Превышено время ожидания")
        self.assertEqual(result.reasoning, "Шаг 1")


class TestHistoryEndpointWiring(
    _MainImports, _EndpointHarness, unittest.IsolatedAsyncioTestCase
):
    """/api/history serves entries built by _history_entries."""

    def _checkpoint(self, stored_messages: list[object]) -> object:
        return SimpleNamespace(
            checkpoint={"channel_values": {"messages": stored_messages}}
        )

    async def _history(self, checkpoint_tuple: object, session_id: str = "s-1"):
        self.main.checkpoint_saver = StubSaver(checkpoint_tuple)
        await self.main.sessions.touch(session_id)
        return await self.main.get_history(session_id)

    async def test_history_entries_carry_extracted_content_and_reasoning(self):
        """Given a stored turn, When history is read, Then the wiring produces entries."""
        stored = [
            self.messages.HumanMessage(content="вопрос"),
            self.messages.AIMessage(
                content="",
                additional_kwargs={"reasoning_content": "Шаг 1"},
                tool_calls=[{"name": "list_games", "args": {}, "id": "call-1"}],
            ),
            self.messages.ToolMessage(content="данные", tool_call_id="call-1"),
            self.messages.AIMessage(
                content=[{"type": "text", "text": "Ответ"}],
                additional_kwargs={"reasoning_content": "Шаг 2"},
            ),
        ]

        payload = await self._history(self._checkpoint(stored))

        self.assertEqual(payload["session_id"], "s-1")
        self.assertEqual(
            payload["history"],
            [
                {"role": "user", "content": "вопрос"},
                {
                    "role": "assistant",
                    "content": "Ответ",
                    "reasoning": "Шаг 1\n\nШаг 2",
                },
            ],
        )

    async def test_history_endpoint_hides_read_knowledge_document(self):
        """Given a knowledge tool turn, When history is read, Then only chat data is served."""
        payload = await self._history(
            self._checkpoint(_read_knowledge_turn(self.messages))
        )

        self.assertEqual(set(payload), {"session_id", "history"})
        self.assertEqual(len(payload["history"]), 2)
        self.assertEqual(
            payload["history"],
            [
                {"role": "user", "content": "вопрос о правилах"},
                {
                    "role": "assistant",
                    "content": "ответ",
                    "reasoning": "Шаг 1\n\nШаг 2",
                },
            ],
        )
        for entry in payload["history"]:
            self.assertNotIn(KNOWLEDGE_DOCUMENT_BODY, entry["content"])

    async def test_history_matches_the_pure_helper(self):
        """Given stored messages, When history is read, Then the helper output is served."""
        stored = [
            self.messages.HumanMessage(content="вопрос"),
            self.messages.AIMessage(content="ответ"),
        ]

        payload = await self._history(self._checkpoint(stored))

        self.assertEqual(payload["history"], self.main._history_entries(stored))

    async def test_history_is_empty_without_a_checkpoint(self):
        """Given no checkpoint, When history is read, Then the history is empty."""
        payload = await self._history(None)

        self.assertEqual(payload["history"], [])


if __name__ == "__main__":
    unittest.main()
