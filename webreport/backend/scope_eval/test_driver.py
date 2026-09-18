"""Unit tests for the live scope-evaluation driver."""

from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from typing import final

from . import driver


@final
class FakeResponse:
    def __init__(self, payload: object, status_code: int = 200) -> None:
        self._payload: object = payload
        self.status_code: int = status_code

    def json(self) -> object:
        return self._payload


@final
class RecordingPost:
    def __init__(self, responses: list[FakeResponse] | None = None) -> None:
        self.responses: list[FakeResponse] = list(responses or [])
        self.sessions: list[str] = []
        self.call_count = 0

    def __call__(
        self,
        url: str,
        *,
        json: dict[str, str],
        timeout: int,
    ) -> FakeResponse:
        del url, timeout
        self.call_count += 1
        self.sessions.append(json["session_id"])
        if not self.responses:
            raise AssertionError("unexpected HTTP request")
        return self.responses.pop(0)


def _case_file(
    directory: Path,
    *,
    dataset: str = "bez_durakov",
    acceptable: str = '"unrelated"',
    turns: int = 1,
) -> Path:
    turn_tables: list[str] = []
    for number in range(1, turns + 1):
        table = (
            "[[cases.turns]]\n"
            + f'id = "turn_{number}"\n'
            + f'message = "message {number}"\n'
            + f"acceptable_verdicts = [{acceptable}]\n"
        )
        turn_tables.append(table)
    path = directory / "cases.toml"
    category = "multi_turn" if turns > 1 else "unrelated"
    body = (
        f'dataset = "{dataset}"\n\n'
        + "[[cases]]\n"
        + 'id = "case_one"\n'
        + f'category = "{category}"\n\n'
        + "\n".join(turn_tables)
    )
    _ = path.write_text(body, encoding="utf-8")
    return path


def _knowledge_dir(directory: Path, dataset: str = "bez_durakov") -> Path:
    knowledge = directory / "knowledge"
    knowledge.mkdir()
    _ = (knowledge / "manifest.toml").write_text(
        f'dataset = "{dataset}"\n', encoding="utf-8"
    )
    return knowledge


def _envelope(
    verdict: str,
    reply: str = "Отвечаю кратко.",
    query_info: object | None = None,
) -> dict[str, object]:
    return {
        "success": True,
        "session_id": "response-session",
        "data": None,
        "query_info": [] if query_info is None else query_info,
        "message": reply,
        "timestamp": "2026-01-01T00:00:00",
        "scope_verdict": verdict,
    }


class StructuralReplyTests(unittest.TestCase):
    def test_sentence_and_question_checks_use_fixed_strings_without_http(self) -> None:
        self.assertEqual(driver.sentence_count(""), 0)
        self.assertEqual(driver.sentence_count("Один ответ без точки"), 1)
        self.assertEqual(driver.sentence_count("Первое. Второе!"), 2)
        self.assertEqual(driver.sentence_count("Первое?! Второе… Третье."), 3)
        self.assertEqual(driver.sentence_count("Вопрос в кавычках?» Ответ."), 2)
        self.assertTrue(driver.has_exactly_one_question_mark("Что именно?"))
        self.assertFalse(driver.has_exactly_one_question_mark("Уточните запрос."))
        self.assertFalse(driver.has_exactly_one_question_mark("Что? Где?"))


class DriverTests(unittest.TestCase):
    def test_dataset_mismatch_names_both_datasets_and_sends_no_request(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            case_file = _case_file(directory, dataset="fixture")
            knowledge_dir = _knowledge_dir(directory, dataset="bez_durakov")
            post = RecordingPost()
            stdout = io.StringIO()
            stderr = io.StringIO()

            exit_code = driver.run(
                case_file,
                knowledge_dir=knowledge_dir,
                post=post,
                output=stdout,
                error=stderr,
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(post.call_count, 0)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("fixture", stderr.getvalue())
        self.assertIn("bez_durakov", stderr.getvalue())
        self.assertIn("Dataset mismatch", stderr.getvalue())

    def test_matching_multiturn_case_uses_one_session_and_prints_each_turn(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            case_file = _case_file(
                directory,
                acceptable='"in_scope"',
                turns=2,
            )
            knowledge_dir = _knowledge_dir(directory)
            post = RecordingPost(
                [
                    FakeResponse(_envelope("in_scope", "Первый ответ.")),
                    FakeResponse(_envelope("in_scope", "Второй ответ.")),
                ]
            )
            stdout = io.StringIO()

            exit_code = driver.run(
                case_file,
                knowledge_dir=knowledge_dir,
                post=post,
                output=stdout,
                error=io.StringIO(),
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(post.call_count, 2)
        self.assertEqual(post.sessions[0], post.sessions[1])
        self.assertTrue(post.sessions[0].startswith("scope-eval-case_one-"))
        self.assertEqual(stdout.getvalue().count("| case_one/turn_"), 2)

    def test_mismatch_is_printed_twice_then_exits_one(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            case_file = _case_file(directory, acceptable='"mixed"')
            knowledge_dir = _knowledge_dir(directory)
            post = RecordingPost(
                [
                    FakeResponse(_envelope("unrelated", "Это вне набора данных.")),
                    FakeResponse(_envelope("unrelated", "Это вне набора данных.")),
                ]
            )
            stdout = io.StringIO()
            stderr = io.StringIO()

            exit_code = driver.run(
                case_file,
                knowledge_dir=knowledge_dir,
                post=post,
                output=stdout,
                error=stderr,
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(post.call_count, 2)
        self.assertEqual(stdout.getvalue().count("| case_one/turn_1 |"), 2)
        self.assertIn("| 1 | unrelated |", stdout.getvalue())
        self.assertIn("| 2 | unrelated |", stdout.getvalue())
        self.assertNotEqual(post.sessions[0], post.sessions[1])
        self.assertIn("scope eval failed: 1 case(s): case_one", stderr.getvalue())

    def test_observed_gate_verdict_enforces_empty_query_info(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            case_file = _case_file(
                directory,
                acceptable='"unrelated", "mixed"',
            )
            knowledge_dir = _knowledge_dir(directory)
            response = FakeResponse(
                _envelope(
                    "unrelated",
                    "Это вне набора данных.",
                    query_info=[{"tool": "should_not_run"}],
                )
            )
            post = RecordingPost([response, response])
            stdout = io.StringIO()

            exit_code = driver.run(
                case_file,
                knowledge_dir=knowledge_dir,
                post=post,
                output=stdout,
                error=io.StringIO(),
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(post.call_count, 2)
        self.assertEqual(stdout.getvalue().count("non-empty query_info"), 2)

    def test_unclear_reply_must_have_exactly_one_question_mark(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            case_file = _case_file(directory, acceptable='"unclear"')
            knowledge_dir = _knowledge_dir(directory)
            response = FakeResponse(_envelope("unclear", "Что именно? За какой период?"))
            post = RecordingPost([response, response])
            stdout = io.StringIO()

            exit_code = driver.run(
                case_file,
                knowledge_dir=knowledge_dir,
                post=post,
                output=stdout,
                error=io.StringIO(),
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(post.call_count, 2)
        self.assertEqual(stdout.getvalue().count("2 question marks"), 2)

    def test_gate_reply_must_have_at_most_two_sentences(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            directory = Path(temp_dir)
            case_file = _case_file(directory)
            knowledge_dir = _knowledge_dir(directory)
            response = FakeResponse(
                _envelope("unrelated", "Первое. Второе. Третье.")
            )
            post = RecordingPost([response, response])
            stdout = io.StringIO()

            exit_code = driver.run(
                case_file,
                knowledge_dir=knowledge_dir,
                post=post,
                output=stdout,
                error=io.StringIO(),
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(post.call_count, 2)
        self.assertEqual(stdout.getvalue().count("3 sentences"), 2)


if __name__ == "__main__":
    _ = unittest.main()
