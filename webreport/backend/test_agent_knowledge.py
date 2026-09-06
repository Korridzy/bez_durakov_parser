"""Contracts for the knowledge model types in agent/knowledge.py."""

import importlib
import inspect
import tempfile
import unittest
from pathlib import Path

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

    def _knowledge_limits(self):
        return self.knowledge_module.KnowledgeLimits(
            max_title_chars=80,
            max_summary_chars=200,
            max_persona_chars=2000,
            max_topics=50,
            max_doc_bytes=65536,
            max_bytes_per_turn=131072,
        )

    def _assert_manifest_path(self, error, manifest_path):
        path_sources = (str(error.path), str(error))

        self.assertTrue(any(str(manifest_path) in source for source in path_sources))

    def test_load_knowledge_rejects_missing_manifest(self):
        """Given an empty knowledge folder, When it is loaded, Then KnowledgeError names the missing manifest."""
        knowledge_error = self.knowledge_module.KnowledgeError
        limits = self._knowledge_limits()

        with tempfile.TemporaryDirectory() as temp_dir:
            manifest_path = Path(temp_dir) / "manifest.toml"

            with self.assertRaises(knowledge_error) as raised:
                self.knowledge_module.load_knowledge(Path(temp_dir), "some_db", limits)

            self._assert_manifest_path(raised.exception, manifest_path)

    def test_load_knowledge_treats_differently_cased_manifest_as_missing(self):
        """Given only Manifest.TOML, When the folder is loaded, Then KnowledgeError reports lowercase manifest.toml missing."""
        knowledge_error = self.knowledge_module.KnowledgeError
        limits = self._knowledge_limits()

        with tempfile.TemporaryDirectory() as temp_dir:
            folder_path = Path(temp_dir)
            wrong_case_path = folder_path / "Manifest.TOML"
            manifest_path = folder_path / "manifest.toml"
            wrong_case_path.write_text('dataset = "some_db"\npersona = "Some text."\n', encoding="utf-8")
            self.assertFalse(manifest_path.exists())

            with self.assertRaises(knowledge_error) as raised:
                self.knowledge_module.load_knowledge(folder_path, "some_db", limits)

            self._assert_manifest_path(raised.exception, manifest_path)

    def test_load_knowledge_rejects_manifest_symlink_outside_folder(self):
        """Given manifest.toml escapes through a symlink, When loaded, Then KnowledgeError names the manifest."""
        knowledge_error = self.knowledge_module.KnowledgeError
        limits = self._knowledge_limits()

        with (
            tempfile.TemporaryDirectory() as temp_dir,
            tempfile.TemporaryDirectory() as outside_dir,
        ):
            manifest_path = Path(temp_dir) / "manifest.toml"
            outside_manifest_path = Path(outside_dir) / "manifest.toml"
            outside_manifest_path.write_text(
                'dataset = "some_db"\npersona = "Some text."\n',
                encoding="utf-8",
            )
            manifest_path.symlink_to(outside_manifest_path)

            with self.assertRaises(knowledge_error) as raised:
                self.knowledge_module.load_knowledge(Path(temp_dir), "some_db", limits)

            self._assert_manifest_path(raised.exception, manifest_path)

    def test_load_knowledge_wraps_unparseable_toml(self):
        """Given malformed manifest TOML, When the folder is loaded, Then KnowledgeError identifies the parse failure."""
        knowledge_error = self.knowledge_module.KnowledgeError
        limits = self._knowledge_limits()

        with tempfile.TemporaryDirectory() as temp_dir:
            manifest_path = Path(temp_dir) / "manifest.toml"
            manifest_path.write_text("[[[\n", encoding="utf-8")

            with self.assertRaises(knowledge_error) as raised:
                self.knowledge_module.load_knowledge(Path(temp_dir), "some_db", limits)

            self._assert_manifest_path(raised.exception, manifest_path)
            self.assertRegex(str(raised.exception), r"(?i)(TOML|line \d+|column \d+)")

    def test_load_knowledge_wraps_unknown_manifest_key_validation(self):
        """Given a manifest with language, When the folder is loaded, Then KnowledgeError names the manifest and key."""
        knowledge_error = self.knowledge_module.KnowledgeError
        limits = self._knowledge_limits()

        with tempfile.TemporaryDirectory() as temp_dir:
            manifest_path = Path(temp_dir) / "manifest.toml"
            manifest_path.write_text(
                'dataset = "some_db"\npersona = "Some text."\nlanguage = "ru"\n',
                encoding="utf-8",
            )

            with self.assertRaises(knowledge_error) as raised:
                self.knowledge_module.load_knowledge(Path(temp_dir), "some_db", limits)

            self._assert_manifest_path(raised.exception, manifest_path)
            self.assertIn("language", str(raised.exception))

    def test_load_knowledge_wraps_dataset_pattern_validation(self):
        """Given an invalid manifest dataset, When the folder is loaded, Then KnowledgeError names the manifest and dataset."""
        knowledge_error = self.knowledge_module.KnowledgeError
        limits = self._knowledge_limits()

        with tempfile.TemporaryDirectory() as temp_dir:
            manifest_path = Path(temp_dir) / "manifest.toml"
            manifest_path.write_text(
                'dataset = "Bad_Dataset"\npersona = "Some text."\n',
                encoding="utf-8",
            )

            with self.assertRaises(knowledge_error) as raised:
                self.knowledge_module.load_knowledge(Path(temp_dir), "some_db", limits)

            self._assert_manifest_path(raised.exception, manifest_path)
            self.assertIn("dataset", str(raised.exception))

    def test_load_knowledge_rejects_dataset_mismatch_with_both_names(self):
        """Given a valid manifest for another dataset, When loaded, Then KnowledgeError names expected and actual datasets."""
        knowledge_error = self.knowledge_module.KnowledgeError
        limits = self._knowledge_limits()

        with tempfile.TemporaryDirectory() as temp_dir:
            manifest_path = Path(temp_dir) / "manifest.toml"
            manifest_path.write_text(
                'dataset = "wrong_dataset"\npersona = "Some text."\n',
                encoding="utf-8",
            )

            with self.assertRaises(knowledge_error) as raised:
                self.knowledge_module.load_knowledge(Path(temp_dir), "actual_dataset", limits)

            self.assertIn("wrong_dataset", str(raised.exception))
            self.assertIn("actual_dataset", str(raised.exception))

    def test_load_knowledge_signature_excludes_database_handles(self):
        """Given load_knowledge, When its signature is inspected, Then it accepts no database handle parameter."""
        signature = inspect.signature(self.knowledge_module.load_knowledge)
        database_handle_names = ("engine", "connection", "conn", "url", "session")

        for parameter_name in signature.parameters:
            self.assertFalse(
                any(name in parameter_name.lower() for name in database_handle_names),
                msg=f"unexpected database handle parameter: {parameter_name}",
            )

    def test_load_knowledge_accepts_database_name_string_and_limits(self):
        """Given a valid folder, database-name string and limits, When loaded, Then a Knowledge value is returned."""
        limits = self._knowledge_limits()

        with tempfile.TemporaryDirectory() as temp_dir:
            manifest_path = Path(temp_dir) / "manifest.toml"
            manifest_path.write_text(
                'dataset = "actual_dataset"\npersona = "Some text."\n',
                encoding="utf-8",
            )
            (Path(temp_dir) / "rules.md").write_text("# Rules\n\nSome text.\n", encoding="utf-8")

            knowledge = self.knowledge_module.load_knowledge(
                Path(temp_dir),
                "actual_dataset",
                limits,
            )

            self.assertIsInstance(knowledge, self.knowledge_module.Knowledge)

    def test_load_knowledge_ignores_manifest_non_md_and_dot_prefixed_entries(self):
        limits = self._knowledge_limits()

        with tempfile.TemporaryDirectory() as temp_dir:
            folder_path = Path(temp_dir)
            (folder_path / "manifest.toml").write_text(
                'dataset = "some_db"\npersona = "Some text."\n',
                encoding="utf-8",
            )
            (folder_path / "notes.txt").write_text("Arbitrary notes.\n", encoding="utf-8")
            (folder_path / ".hidden.md").write_text(
                "# Hidden\n\nSome hidden paragraph text.\n",
                encoding="utf-8",
            )
            (folder_path / "rules.md").write_text(
                "# Rules\n\nSome summary paragraph text.\n",
                encoding="utf-8",
            )

            knowledge = self.knowledge_module.load_knowledge(folder_path, "some_db", limits)

            self.assertEqual(len(knowledge.topics), 1)
            self.assertEqual(knowledge.topics[0].id, "rules")

    def test_load_knowledge_rejects_subdirectory_in_folder_root(self):
        knowledge_error = self.knowledge_module.KnowledgeError
        limits = self._knowledge_limits()

        with tempfile.TemporaryDirectory() as temp_dir:
            folder_path = Path(temp_dir)
            (folder_path / "manifest.toml").write_text(
                'dataset = "some_db"\npersona = "Some text."\n',
                encoding="utf-8",
            )
            (folder_path / "rules.md").write_text(
                "# Rules\n\nSome summary paragraph text.\n",
                encoding="utf-8",
            )
            (folder_path / "subdir").mkdir()

            with self.assertRaises(knowledge_error):
                self.knowledge_module.load_knowledge(folder_path, "some_db", limits)

    def test_load_knowledge_rejects_zero_topic_documents(self):
        knowledge_error = self.knowledge_module.KnowledgeError
        limits = self._knowledge_limits()

        with tempfile.TemporaryDirectory() as temp_dir:
            folder_path = Path(temp_dir)
            (folder_path / "manifest.toml").write_text(
                'dataset = "some_db"\npersona = "Some text."\n',
                encoding="utf-8",
            )

            with self.assertRaises(knowledge_error):
                self.knowledge_module.load_knowledge(folder_path, "some_db", limits)

    def test_load_knowledge_rejects_topic_count_over_max_topics(self):
        knowledge_error = self.knowledge_module.KnowledgeError
        limits = self.knowledge_module.KnowledgeLimits(
            max_title_chars=80,
            max_summary_chars=200,
            max_persona_chars=2000,
            max_topics=2,
            max_doc_bytes=65536,
            max_bytes_per_turn=131072,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            folder_path = Path(temp_dir)
            (folder_path / "manifest.toml").write_text(
                'dataset = "some_db"\npersona = "Some text."\n',
                encoding="utf-8",
            )
            for filename, title in (
                ("topic-a.md", "Topic A"),
                ("topic-b.md", "Topic B"),
                ("topic-c.md", "Topic C"),
            ):
                (folder_path / filename).write_text(
                    f"# {title}\n\nSome summary paragraph text.\n",
                    encoding="utf-8",
                )

            with self.assertRaises(knowledge_error):
                self.knowledge_module.load_knowledge(folder_path, "some_db", limits)

    def test_load_knowledge_rejects_topic_stem_outside_pattern_and_names_file(self):
        knowledge_error = self.knowledge_module.KnowledgeError
        limits = self._knowledge_limits()

        with tempfile.TemporaryDirectory() as temp_dir:
            folder_path = Path(temp_dir)
            (folder_path / "manifest.toml").write_text(
                'dataset = "some_db"\npersona = "Some text."\n',
                encoding="utf-8",
            )
            (folder_path / "Rules.md").write_text(
                "# Rules\n\nSome summary paragraph text.\n",
                encoding="utf-8",
            )

            with self.assertRaises(knowledge_error) as raised:
                self.knowledge_module.load_knowledge(folder_path, "some_db", limits)

            self.assertIn("Rules.md", str(raised.exception))

    def test_load_knowledge_yields_three_topics_in_expected_order_with_expected_ids(self):
        limits = self._knowledge_limits()

        with tempfile.TemporaryDirectory() as temp_dir:
            folder_path = Path(temp_dir)
            (folder_path / "manifest.toml").write_text(
                'dataset = "some_db"\npersona = "Some text."\n',
                encoding="utf-8",
            )
            for filename, title in (
                ("glossary.md", "Glossary"),
                ("rules.md", "Rules"),
                ("scoring.md", "Scoring"),
            ):
                (folder_path / filename).write_text(
                    f"# {title}\n\nSome summary paragraph text.\n",
                    encoding="utf-8",
                )

            knowledge = self.knowledge_module.load_knowledge(folder_path, "some_db", limits)

            self.assertEqual(len(knowledge.topics), 3)
            self.assertEqual(
                tuple(topic.id for topic in knowledge.topics),
                ("glossary", "rules", "scoring"),
            )


if __name__ == "__main__":
    unittest.main()
