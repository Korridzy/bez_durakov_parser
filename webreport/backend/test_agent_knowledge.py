"""Contracts for the knowledge model types in agent/knowledge.py."""

import importlib
import unittest

from pydantic import ValidationError


class KnowledgeTypesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.knowledge_module = importlib.import_module("agent.knowledge")

    def test_knowledge_error_is_a_plain_exception_subclass(self):
        """Given KnowledgeError, When its MRO is inspected, Then it derives from Exception directly, not ValueError or ToolError."""
        knowledge_module = self.knowledge_module
        registry = importlib.import_module("agent.registry")

        self.assertTrue(issubclass(knowledge_module.KnowledgeError, Exception))
        self.assertNotIn(ValueError, knowledge_module.KnowledgeError.__mro__)
        self.assertNotIn(registry.ToolError, knowledge_module.KnowledgeError.__mro__)

    def test_knowledge_error_carries_path_and_optional_key_and_rule(self):
        """Given a KnowledgeError raised with path, key and rule, When inspected, Then all three are accessible attributes."""
        knowledge_module = self.knowledge_module

        error = knowledge_module.KnowledgeError("boom", path="/x/y.md", key="dataset", rule="pattern")

        self.assertEqual(error.path, "/x/y.md")
        self.assertEqual(error.key, "dataset")
        self.assertEqual(error.rule, "pattern")

    def test_knowledge_error_key_and_rule_default_to_none(self):
        """Given a KnowledgeError raised with only a path, When inspected, Then key and rule default to None."""
        knowledge_module = self.knowledge_module

        error = knowledge_module.KnowledgeError("boom", path="/x/y.md")

        self.assertIsNone(error.key)
        self.assertIsNone(error.rule)

    def test_knowledge_limits_holds_six_integer_fields(self):
        """Given KnowledgeLimits, When constructed with six values, Then all six are accessible as the given integers."""
        knowledge_module = self.knowledge_module

        limits = knowledge_module.KnowledgeLimits(
            max_title_chars=80,
            max_summary_chars=200,
            max_persona_chars=2000,
            max_topics=50,
            max_doc_bytes=65536,
            max_bytes_per_turn=131072,
        )

        self.assertEqual(limits.max_title_chars, 80)
        self.assertEqual(limits.max_summary_chars, 200)
        self.assertEqual(limits.max_persona_chars, 2000)
        self.assertEqual(limits.max_topics, 50)
        self.assertEqual(limits.max_doc_bytes, 65536)
        self.assertEqual(limits.max_bytes_per_turn, 131072)

    def test_knowledge_topic_exposes_id_title_summary_text(self):
        """Given a KnowledgeTopic, When constructed, Then id, title, summary and text are all accessible."""
        knowledge_module = self.knowledge_module

        topic = knowledge_module.KnowledgeTopic(
            id="rules", title="Rules", summary="A summary.", text="# Rules\n\nA summary.\n"
        )

        self.assertEqual(topic.id, "rules")
        self.assertEqual(topic.title, "Rules")
        self.assertEqual(topic.summary, "A summary.")
        self.assertEqual(topic.text, "# Rules\n\nA summary.\n")

    def test_knowledge_exposes_manifest_and_ordered_topics(self):
        """Given a Knowledge instance, When constructed with a manifest and topics, Then both are accessible and topics preserve order."""
        knowledge_module = self.knowledge_module

        topic_a = knowledge_module.KnowledgeTopic(id="a", title="A", summary="s", text="t")
        topic_b = knowledge_module.KnowledgeTopic(id="b", title="B", summary="s", text="t")
        manifest_stub = object()
        knowledge = knowledge_module.Knowledge(manifest=manifest_stub, topics=(topic_a, topic_b))

        self.assertIs(knowledge.manifest, manifest_stub)
        self.assertEqual(tuple(t.id for t in knowledge.topics), ("a", "b"))

    def test_knowledge_manifest_accepts_only_dataset_and_persona(self):
        """Given dataset and persona, When a KnowledgeManifest is constructed, Then both fields are accepted exactly."""
        knowledge_manifest = self.knowledge_module.KnowledgeManifest

        manifest = knowledge_manifest(dataset="ok_dataset", persona="Some persona text.")

        self.assertEqual(set(knowledge_manifest.model_fields), {"dataset", "persona"})
        self.assertEqual(
            manifest.model_dump(),
            {"dataset": "ok_dataset", "persona": "Some persona text."},
        )

    def test_knowledge_manifest_rejects_unknown_key_and_names_language(self):
        """Given extra=\"forbid\", When language is supplied to a KnowledgeManifest, Then the error names language."""
        knowledge_manifest = self.knowledge_module.KnowledgeManifest

        with self.assertRaises(ValidationError) as raised:
            knowledge_manifest(
                dataset="ok_dataset",
                persona="Some persona text.",
                language="ru",
            )

        self.assertIn("language", str(raised.exception))

    def test_knowledge_manifest_rejects_dataset_outside_pinned_pattern(self):
        """Given dataset must match ^[a-z0-9_-]{1,64}$, When it contains uppercase letters, Then the error names dataset."""
        knowledge_manifest = self.knowledge_module.KnowledgeManifest

        with self.assertRaises(ValidationError) as raised:
            knowledge_manifest(dataset="Bad_Durakov", persona="Some persona text.")

        self.assertIn("dataset", str(raised.exception))

    def test_knowledge_manifest_rejects_empty_persona_and_names_persona(self):
        """Given an empty persona, When a KnowledgeManifest is constructed, Then the error names persona."""
        knowledge_manifest = self.knowledge_module.KnowledgeManifest

        with self.assertRaises(ValidationError) as raised:
            knowledge_manifest(dataset="ok_dataset", persona="")

        self.assertIn("persona", str(raised.exception))

    def test_knowledge_manifest_rejects_persona_over_context_limit_and_names_persona(self):
        """Given max_persona_chars is supplied in validation context, When persona exceeds it, Then the error names persona."""
        knowledge_manifest = self.knowledge_module.KnowledgeManifest

        with self.assertRaises(ValidationError) as raised:
            knowledge_manifest.model_validate(
                {"dataset": "ok_dataset", "persona": "x" * 10},
                context={"max_persona_chars": 5},
            )

        self.assertIn("persona", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
