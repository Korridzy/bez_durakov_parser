from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

import chat_pane


class _Container:
    def __enter__(self) -> _Container:
        return self

    def __exit__(self, exception_type: object, exception: object, traceback: object) -> bool:
        return False


class _Streamlit:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.session_state = SimpleNamespace(
            chat_history=[],
            pending_request=None,
            is_generating=False,
            active_report_id=None,
            fullscreen=None,
            report_ready_badge=False,
            user_has_dragged=False,
            split_pct=70.0,
        )

    def container(self, **_kwargs: object) -> _Container:
        return _Container()

    def chat_message(self, _role: str) -> _Container:
        return _Container()

    def expander(self, label: str, *, expanded: bool = True) -> _Container:
        self.calls.append(("expander", label, expanded))
        return _Container()

    def markdown(self, body: object) -> None:
        self.calls.append(("markdown", body))

    def caption(self, _body: str) -> None:
        return None

    def button(self, _label: str, **_kwargs: object) -> bool:
        return False

    def error(self, _body: str) -> None:
        return None

    def rerun(self) -> None:
        return None


class ReasoningViewTest(unittest.TestCase):
    def test_returns_plain_label_for_complete_reasoning(self) -> None:
        view = chat_pane.reasoning_view({"reasoning": "Шаг 1\n\nШаг 2"})

        self.assertEqual(("Рассуждения", "Шаг 1\n\nШаг 2"), view)

    def test_returns_partial_label_when_message_marked_partial(self) -> None:
        view = chat_pane.reasoning_view({"reasoning": "Шаг 1", "reasoning_partial": True})

        self.assertEqual(("Рассуждения (неполные)", "Шаг 1"), view)

    def test_returns_plain_label_when_partial_flag_is_false(self) -> None:
        view = chat_pane.reasoning_view({"reasoning": "Шаг 1", "reasoning_partial": False})

        self.assertEqual(("Рассуждения", "Шаг 1"), view)

    def test_returns_none_when_reasoning_absent(self) -> None:
        self.assertIsNone(chat_pane.reasoning_view({"content": "Отчёт готов"}))

    def test_returns_none_when_reasoning_is_none(self) -> None:
        self.assertIsNone(chat_pane.reasoning_view({"reasoning": None}))

    def test_returns_none_when_reasoning_is_whitespace_only(self) -> None:
        self.assertIsNone(chat_pane.reasoning_view({"reasoning": "  \n\t "}))

    def test_returns_none_when_reasoning_is_empty_string(self) -> None:
        self.assertIsNone(chat_pane.reasoning_view({"reasoning": ""}))

    def test_returns_none_when_reasoning_is_not_a_string(self) -> None:
        self.assertIsNone(chat_pane.reasoning_view({"reasoning": ["Шаг 1"]}))


class ProcessPendingRequestReasoningTest(unittest.TestCase):
    def _run(self, response: dict[str, object]) -> dict[str, object]:
        streamlit = _Streamlit()
        streamlit.session_state.pending_request = {"id": "request-1", "content": "покажи все игры"}

        with patch.object(chat_pane, "st", streamlit):
            chat_pane.process_pending_request(lambda _content: response)

        return streamlit.session_state.chat_history[-1]

    def test_stores_reasoning_as_complete_on_successful_response(self) -> None:
        message = self._run(
            {"success": True, "message": "Отчёт готов", "data": [], "reasoning": "Шаг 1\n\nШаг 2"}
        )

        self.assertEqual("Шаг 1\n\nШаг 2", message["reasoning"])
        self.assertFalse(message["reasoning_partial"])

    def test_marks_reasoning_partial_on_failed_response(self) -> None:
        message = self._run({"success": False, "error": "Таймаут", "reasoning": "Шаг 1"})

        self.assertEqual("Шаг 1", message["reasoning"])
        self.assertTrue(message["reasoning_partial"])

    def test_omits_reasoning_when_response_carries_none(self) -> None:
        message = self._run({"success": True, "message": "Отчёт готов", "data": [], "reasoning": None})

        self.assertNotIn("reasoning", message)

    def test_omits_reasoning_when_response_has_no_reasoning_key(self) -> None:
        message = self._run({"success": True, "message": "Отчёт готов", "data": []})

        self.assertNotIn("reasoning", message)


class RenderMessageReasoningTest(unittest.TestCase):
    def _render(self, message: dict[str, object]) -> list[tuple[object, ...]]:
        streamlit = _Streamlit()

        with patch.object(chat_pane, "st", streamlit):
            chat_pane._render_message(message, None)

        return streamlit.calls

    def test_renders_collapsed_expander_above_the_answer(self) -> None:
        calls = self._render(
            {
                "id": "message-1",
                "role": "assistant",
                "content": "Отчёт готов",
                "reasoning": "Шаг 1",
            }
        )

        self.assertEqual(
            [("expander", "Рассуждения", False), ("markdown", "Шаг 1"), ("markdown", "Отчёт готов")],
            calls,
        )

    def test_renders_partial_label_for_partial_reasoning(self) -> None:
        calls = self._render(
            {
                "id": "message-1",
                "role": "assistant",
                "content": "Не удалось создать отчёт",
                "reasoning": "Шаг 1",
                "reasoning_partial": True,
            }
        )

        self.assertEqual(("expander", "Рассуждения (неполные)", False), calls[0])

    def test_renders_no_expander_when_reasoning_is_whitespace_only(self) -> None:
        calls = self._render(
            {"id": "message-1", "role": "assistant", "content": "Отчёт готов", "reasoning": "   "}
        )

        self.assertEqual([("markdown", "Отчёт готов")], calls)

    def test_renders_no_expander_when_reasoning_is_absent(self) -> None:
        calls = self._render({"id": "message-1", "role": "assistant", "content": "Отчёт готов"})

        self.assertEqual([("markdown", "Отчёт готов")], calls)


if __name__ == "__main__":
    _ = unittest.main()
