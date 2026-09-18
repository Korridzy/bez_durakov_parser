"""Contracts for the scope gate: its decision schema and its strict output parser.

The parser is the trust boundary in front of the gate, so the invalid table below
is the point of this module: a repaired or coerced verdict would silently
misclassify a user's turn. Every rejected payload must raise, never parse.
"""

import ast
import importlib
import inspect
import json
import unittest
from typing import Final, get_args

from pydantic import ValidationError

VALID_PAYLOADS: Final[tuple[tuple[str, dict[str, object]], ...]] = (
    ("in_scope", {"verdict": "in_scope", "reply": None, "note": None}),
    ("unrelated", {"verdict": "unrelated", "reply": "Not my subject.", "note": None}),
    ("unclear", {"verdict": "unclear", "reply": "Which period?", "note": None}),
    ("mixed", {"verdict": "mixed", "reply": None, "note": "One part was skipped."}),
)

INVALID_PAYLOADS: Final[tuple[tuple[str, object], ...]] = (
    # Verdict vocabulary: the literal is exact, so case and synonyms are refusals.
    ("verdict_wrong_case", {"verdict": "Unrelated", "reply": "x", "note": None}),
    ("verdict_unknown", {"verdict": "off_topic", "reply": "x", "note": None}),
    ("verdict_wrong_type", {"verdict": 5, "reply": None, "note": None}),
    # Blank strings are missing fields wearing a costume.
    ("blank_reply", {"verdict": "unrelated", "reply": " ", "note": None}),
    ("blank_note", {"verdict": "mixed", "reply": None, "note": ""}),
    # Field combinations the verdict does not allow.
    ("mixed_with_reply_and_note", {"verdict": "mixed", "reply": "a", "note": "b"}),
    ("mixed_without_note", {"verdict": "mixed", "reply": None, "note": None}),
    ("in_scope_with_reply", {"verdict": "in_scope", "reply": "a", "note": None}),
    ("in_scope_with_note", {"verdict": "in_scope", "reply": None, "note": "b"}),
    ("unrelated_without_reply", {"verdict": "unrelated", "reply": None, "note": None}),
    ("unclear_with_note", {"verdict": "unclear", "reply": "a?", "note": "b"}),
    # Shape: missing keys, extra keys, wrong types, wrong root.
    ("missing_note_key", {"verdict": "in_scope", "reply": None}),
    ("missing_verdict_key", {"reply": None, "note": None}),
    ("extra_key", {"verdict": "in_scope", "reply": None, "note": None, "why": "x"}),
    ("reply_wrong_type", {"verdict": "unrelated", "reply": 5, "note": None}),
    ("note_wrong_type", {"verdict": "mixed", "reply": None, "note": ["b"]}),
    ("empty_object", {}),
    ("non_object_root", ["verdict", "in_scope"]),
)

UNPARSABLE_TEXTS: Final[tuple[tuple[str, str], ...]] = (
    ("truncated_json", '{"verdict": "unrelated", "reply": "x"'),
    ("empty_text", ""),
    ("whitespace_text", "   \n  "),
    ("prose", "I think the question is unrelated."),
    ("json_array_root", '["unrelated"]'),
    ("json_scalar_root", '"unrelated"'),
    ("trailing_garbage", '{"verdict": "in_scope", "reply": null, "note": null} extra'),
)


class StubResponse:
    """Minimal `AgentMessageView` double: content plus tool calls, nothing else."""

    def __init__(self, content="", tool_calls=None):
        self.content = content
        self.tool_calls = list(tool_calls or [])


def schema_tool_call(arguments, *, name="record_scope_decision", call_id="call-1"):
    """One `ToolCall` in the shape graph.py:29-34 declares."""
    return {"name": name, "args": arguments, "id": call_id, "type": "tool_call"}


class ScopeGateDecisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scope_gate = importlib.import_module("agent.scope_gate")

    def test_verdict_literal_holds_exactly_the_four_verdicts(self):
        """Given ScopeVerdict, When its arguments are read, Then they are the four spec verdicts."""
        self.assertEqual(
            get_args(self.scope_gate.ScopeVerdict),
            ("in_scope", "unrelated", "unclear", "mixed"),
        )

    def test_model_config_is_strict_frozen_and_closed(self):
        """Given GateDecision, When its config is read, Then extras are forbidden and it is strict and frozen."""
        config = self.scope_gate.GateDecision.model_config

        self.assertEqual(config["extra"], "forbid")
        self.assertTrue(config["strict"])
        self.assertTrue(config["frozen"])

    def test_gate_output_error_is_a_value_error(self):
        """Given GateOutputError, When its MRO is inspected, Then it derives from ValueError."""
        self.assertTrue(issubclass(self.scope_gate.GateOutputError, ValueError))

    def test_valid_payloads_validate_to_the_declared_fields(self):
        """Given each of the four valid payloads, When validated, Then every field round-trips."""
        for label, payload in VALID_PAYLOADS:
            with self.subTest(payload=label):
                decision = self.scope_gate.GateDecision.model_validate(payload)

                self.assertEqual(decision.verdict, payload["verdict"])
                self.assertEqual(decision.reply, payload["reply"])
                self.assertEqual(decision.note, payload["note"])

    def test_valid_decisions_are_frozen(self):
        """Given a validated decision, When a field is assigned, Then pydantic refuses the mutation."""
        for label, payload in VALID_PAYLOADS:
            with self.subTest(payload=label):
                decision = self.scope_gate.GateDecision.model_validate(payload)

                with self.assertRaises(ValidationError):
                    decision.verdict = "in_scope"

    def test_invalid_payloads_are_rejected_by_the_model(self):
        """Given each invalid payload, When validated directly, Then a ValidationError is raised."""
        for label, payload in INVALID_PAYLOADS:
            with self.subTest(payload=label):
                with self.assertRaises(ValidationError):
                    self.scope_gate.GateDecision.model_validate(payload)

    def test_a_single_tool_call_parses_every_valid_payload_to_a_frozen_model(self):
        """Given one schema tool call per valid payload, When parsed, Then a frozen decision comes back."""
        for label, payload in VALID_PAYLOADS:
            with self.subTest(payload=label):
                response = StubResponse(tool_calls=[schema_tool_call(payload)])

                decision = self.scope_gate.parse_gate_decision(response)

                self.assertIsInstance(decision, self.scope_gate.GateDecision)
                self.assertEqual(decision.verdict, payload["verdict"])
                with self.assertRaises(ValidationError):
                    decision.reply = "mutated"

    def test_json_text_parses_when_there_is_no_tool_call(self):
        """Given a text-only response carrying JSON, When parsed, Then the decision is read from the text."""
        response = StubResponse(
            content='{"verdict": "mixed", "reply": null, "note": "left out one part"}'
        )

        decision = self.scope_gate.parse_gate_decision(response)

        self.assertEqual(decision.verdict, "mixed")
        self.assertEqual(decision.note, "left out one part")
        self.assertIsNone(decision.reply)

    def test_json_text_in_provider_content_blocks_parses(self):
        """Given block-list content, When parsed, Then extract_text finds the JSON body."""
        response = StubResponse(
            content=[
                {"type": "text", "text": '{"verdict": "in_scope", "reply": null, "note": null}'}
            ]
        )

        decision = self.scope_gate.parse_gate_decision(response)

        self.assertEqual(decision.verdict, "in_scope")

    def test_invalid_payloads_in_a_tool_call_raise_gate_output_error(self):
        """Given each invalid payload as tool call arguments, When parsed, Then GateOutputError is raised."""
        for label, payload in INVALID_PAYLOADS:
            with self.subTest(payload=label):
                response = StubResponse(tool_calls=[schema_tool_call(payload)])

                with self.assertRaises(self.scope_gate.GateOutputError):
                    self.scope_gate.parse_gate_decision(response)

    def test_invalid_payloads_as_json_text_raise_gate_output_error(self):
        """Given each invalid payload serialized as JSON text, When parsed, Then GateOutputError is raised."""
        for label, payload in INVALID_PAYLOADS:
            with self.subTest(payload=label):
                response = StubResponse(content=json.dumps(payload))

                with self.assertRaises(self.scope_gate.GateOutputError):
                    self.scope_gate.parse_gate_decision(response)

    def test_unparsable_text_without_a_tool_call_raises_gate_output_error(self):
        """Given truncated, empty or non-JSON text and no tool call, When parsed, Then GateOutputError is raised."""
        for label, text in UNPARSABLE_TEXTS:
            with self.subTest(text=label):
                with self.assertRaises(self.scope_gate.GateOutputError):
                    self.scope_gate.parse_gate_decision(StubResponse(content=text))

    def test_two_tool_calls_raise_gate_output_error(self):
        """Given two tool calls, When parsed, Then GateOutputError is raised and neither call is used."""
        first, second = VALID_PAYLOADS[0][1], VALID_PAYLOADS[1][1]
        response = StubResponse(
            tool_calls=[
                schema_tool_call(first, call_id="call-1"),
                schema_tool_call(second, call_id="call-2"),
            ]
        )

        with self.assertRaises(self.scope_gate.GateOutputError) as raised:
            self.scope_gate.parse_gate_decision(response)

        self.assertIn("2", str(raised.exception))

    def test_a_tool_call_without_an_argument_object_raises_gate_output_error(self):
        """Given a tool call whose args are not an object, When parsed, Then GateOutputError is raised."""
        for label, arguments in (("list", ["in_scope"]), ("string", "in_scope"), ("none", None)):
            with self.subTest(arguments=label):
                response = StubResponse(tool_calls=[schema_tool_call(arguments)])

                with self.assertRaises(self.scope_gate.GateOutputError):
                    self.scope_gate.parse_gate_decision(response)

    def test_gate_output_error_chains_the_validation_error(self):
        """Given a rejected payload, When GateOutputError is raised, Then the ValidationError is its cause."""
        response = StubResponse(
            tool_calls=[schema_tool_call({"verdict": "Unrelated", "reply": "x", "note": None})]
        )

        with self.assertRaises(self.scope_gate.GateOutputError) as raised:
            self.scope_gate.parse_gate_decision(response)

        self.assertIsInstance(raised.exception.__cause__, ValidationError)

    def test_module_imports_neither_config_nor_an_output_parser(self):
        """Given the module source, When its imports are scanned, Then it names no config and no LangChain module.

        Prose may name `bd_shared.config` to say the dependency is deliberately
        absent, so the scan reads import statements rather than any occurrence.
        A langchain or langgraph import here would mean an output parser or a
        message class crept in; the sibling agent modules own those.
        """
        source = inspect.getsource(self.scope_gate)
        imported = set()
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add(node.module or "")

        self.assertNotIn("import_module", source)
        for module_name in imported:
            with self.subTest(module=module_name):
                self.assertFalse(module_name.startswith("bd_shared"))
                self.assertFalse(module_name.startswith("langchain"))
                self.assertFalse(module_name.startswith("langgraph"))


if __name__ == "__main__":
    unittest.main()
