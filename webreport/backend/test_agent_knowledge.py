"""Contracts for the knowledge model types in agent/knowledge.py."""

import importlib
import inspect
import os
import runpy
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Final
from unittest.mock import patch

from pydantic import ValidationError


GAME_DOMAIN_FORBIDDEN_STRINGS: Final[tuple[str, ...]] = (
    "дурак",
    "Без дураков",
    "команд",
    "вybor",
    "выбор",
    "числа",
    "преферанс",
    "пары",
    "разоблачение",
    "аукцион",
    "момент истины",
    # The eight former tool names, plus the two English words they were built from. Verified
    # that neither scanned package contains "stream" or any other benign superstring of
    # "team", so a plain substring assertion is safe.
    "get_all_games_summary",
    "get_all_teams",
    "get_game_by_id",
    "get_games_by_date_range",
    "get_team_game_scores",
    "get_team_statistics",
    "get_team_wins",
    "get_top_teams",
    "game",
    "team",
)


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

    def test_knowledge_error_carries_observed_and_permitted_values(self):
        """Given observed and permitted values, When a KnowledgeError is raised, Then both are accessible attributes."""
        knowledge_module = self.knowledge_module

        error = knowledge_module.KnowledgeError(
            "boom",
            path="/x/y.md",
            observed=201,
            permitted=200,
        )

        self.assertEqual(error.observed, 201)
        self.assertEqual(error.permitted, 200)

    def test_knowledge_error_key_and_rule_default_to_none(self):
        """Given a KnowledgeError raised with only a path, When inspected, Then key and rule default to None."""
        knowledge_module = self.knowledge_module

        error = knowledge_module.KnowledgeError("boom", path="/x/y.md")

        self.assertIsNone(error.key)
        self.assertIsNone(error.rule)
        self.assertIsNone(error.observed)
        self.assertIsNone(error.permitted)

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

    def test_load_knowledge_rejects_persona_over_max_chars_with_observed_limit(self):
        """Given an over-long manifest persona, When loaded, Then its length, limit and manifest path are reported."""
        knowledge_error = self.knowledge_module.KnowledgeError
        limits = self._knowledge_limits()
        observed = limits.max_persona_chars + 1

        with tempfile.TemporaryDirectory() as temp_dir:
            folder_path = Path(temp_dir)
            manifest_path = folder_path / "manifest.toml"
            persona = "P" * observed
            manifest_path.write_text(
                f'dataset = "some_db"\npersona = "{persona}"\n',
                encoding="utf-8",
            )

            with self.assertRaises(knowledge_error) as raised:
                self.knowledge_module.load_knowledge(folder_path, "some_db", limits)

            message = str(raised.exception)
            self._assert_manifest_path(raised.exception, manifest_path)
            self.assertIn(
                f"persona is {observed} characters, limit is {limits.max_persona_chars}",
                message,
            )
            self.assertEqual(raised.exception.observed, observed)
            self.assertEqual(raised.exception.permitted, limits.max_persona_chars)

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
        self.assertEqual(error.path, manifest_path)
        self.assertIsNotNone(error.rule)

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
            self.assertEqual(raised.exception.key, "language")
            self.assertEqual(raised.exception.rule, "extra_forbidden")

    def test_load_knowledge_wraps_directory_enumeration_errors(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            (folder / "manifest.toml").write_text('dataset="some_db"\npersona="Text."\n')
            denied = PermissionError(13, "Permission denied", str(folder))

            def failing_iterator():
                yield folder / "manifest.toml"
                raise denied

            for failure in (denied, failing_iterator):
                with self.subTest(failure=failure):
                    with patch.object(Path, "iterdir", side_effect=failure):
                        with self.assertRaises(self.knowledge_module.KnowledgeError) as raised:
                            self.knowledge_module.load_knowledge(folder, "some_db", self._knowledge_limits())
                    self.assertEqual(raised.exception.path, folder)
                    self.assertIsNone(raised.exception.key)
                    self.assertEqual(raised.exception.rule, "directory_enumeration")
                    self.assertIs(raised.exception.__cause__, denied)

    def test_load_knowledge_wraps_entry_inspection_errors(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            (folder / "manifest.toml").write_text('dataset="some_db"\npersona="Text."\n')
            entry = folder / "rules.md"
            entry.write_text("# Rules\n\nSummary.\n")
            original_is_dir = Path.is_dir
            denied = PermissionError(13, "Permission denied", str(entry))

            def inspect_entry(path):
                if path == entry:
                    raise denied
                return original_is_dir(path)

            with patch.object(Path, "is_dir", inspect_entry):
                with self.assertRaises(self.knowledge_module.KnowledgeError) as raised:
                    self.knowledge_module.load_knowledge(folder, "some_db", self._knowledge_limits())
            self.assertEqual(raised.exception.path, entry)
            self.assertEqual(raised.exception.rule, "directory_entry_access")
            self.assertIs(raised.exception.__cause__, denied)

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
            self.assertEqual(raised.exception.key, "dataset")
            self.assertEqual(raised.exception.rule, "string_pattern_mismatch")

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
            self.assertEqual(raised.exception.path, manifest_path)
            self.assertEqual(raised.exception.key, "dataset")
            self.assertEqual(raised.exception.rule, "database_match")

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
            (folder_path / ".gitkeep").touch()
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
        self._assert_root_subdirectory_rejected("subdir")

    def test_load_knowledge_rejects_hidden_subdirectory_in_folder_root(self):
        self._assert_root_subdirectory_rejected(".git")

    def _assert_root_subdirectory_rejected(self, name):
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
            subdirectory = folder_path / name
            subdirectory.mkdir()

            with self.assertRaises(knowledge_error) as raised:
                self.knowledge_module.load_knowledge(folder_path, "some_db", limits)
            self.assertEqual(raised.exception.path, subdirectory)
            self.assertEqual(raised.exception.rule, "no_subdirectories")

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

            with self.assertRaises(knowledge_error) as raised:
                self.knowledge_module.load_knowledge(folder_path, "some_db", limits)

            message = str(raised.exception)
            self.assertIn(str(folder_path), message)
            self.assertIn(
                f"topic count is 3, limit is {limits.max_topics}",
                message,
            )
            self.assertEqual(raised.exception.observed, 3)
            self.assertEqual(raised.exception.permitted, limits.max_topics)

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

    def test_shipped_knowledge_skeleton_loads_under_strict_default_limits(self):
        bd_shared_config = importlib.import_module("bd_shared.config")
        limits = self.knowledge_module.KnowledgeLimits(
            max_title_chars=bd_shared_config.KNOWLEDGE_MAX_TITLE_CHARS,
            max_summary_chars=bd_shared_config.KNOWLEDGE_MAX_SUMMARY_CHARS,
            max_persona_chars=bd_shared_config.KNOWLEDGE_MAX_PERSONA_CHARS,
            max_topics=bd_shared_config.KNOWLEDGE_MAX_TOPICS,
            max_doc_bytes=bd_shared_config.KNOWLEDGE_MAX_DOC_BYTES,
            max_bytes_per_turn=131072,
        )

        knowledge = self.knowledge_module.load_knowledge(
            Path("/bd_shared/knowledge/bez_durakov"),
            "bez_durakov",
            limits,
        )

        self.assertIsInstance(knowledge, self.knowledge_module.Knowledge)
        self.assertEqual(len(knowledge.topics), 3)
        self.assertEqual(
            tuple(topic.id for topic in knowledge.topics),
            ("glossary", "rules", "scoring"),
        )
        self.assertEqual(knowledge.manifest.dataset, "bez_durakov")
        self.assertGreater(len(knowledge.manifest.persona), 0)

    def test_load_knowledge_rejects_document_without_heading_and_names_file(self):
        """Given a document without a heading, When loaded, Then KnowledgeError names the file."""
        knowledge_error = self.knowledge_module.KnowledgeError
        limits = self._knowledge_limits()

        with tempfile.TemporaryDirectory() as temp_dir:
            folder_path = Path(temp_dir)
            (folder_path / "manifest.toml").write_text(
                'dataset = "some_db"\npersona = "Some text."\n',
                encoding="utf-8",
            )
            (folder_path / "rules.md").write_text(
                "Plain prose without a heading.\n",
                encoding="utf-8",
            )

            with self.assertRaises(knowledge_error) as raised:
                self.knowledge_module.load_knowledge(folder_path, "some_db", limits)

            self.assertIn("rules.md", str(raised.exception))

    def test_load_knowledge_rejects_title_over_max_chars_and_names_file(self):
        """Given a title over the configured limit, When loaded, Then KnowledgeError names the file."""
        knowledge_error = self.knowledge_module.KnowledgeError
        limits = self._knowledge_limits()

        with tempfile.TemporaryDirectory() as temp_dir:
            folder_path = Path(temp_dir)
            (folder_path / "manifest.toml").write_text(
                'dataset = "some_db"\npersona = "Some text."\n',
                encoding="utf-8",
            )
            (folder_path / "rules.md").write_text(
                f"# {'T' * (limits.max_title_chars + 1)}\n\nA summary.\n",
                encoding="utf-8",
            )

            with self.assertRaises(knowledge_error) as raised:
                self.knowledge_module.load_knowledge(folder_path, "some_db", limits)

            message = str(raised.exception)
            self.assertIn("rules.md", message)
            self.assertIn(
                f"title is {limits.max_title_chars + 1} characters, limit is {limits.max_title_chars}",
                message,
            )
            self.assertEqual(raised.exception.observed, limits.max_title_chars + 1)
            self.assertEqual(raised.exception.permitted, limits.max_title_chars)

    def test_load_knowledge_rejects_heading_without_paragraph_and_names_file(self):
        """Given a heading with no following paragraph, When loaded, Then KnowledgeError names the file."""
        knowledge_error = self.knowledge_module.KnowledgeError
        limits = self._knowledge_limits()

        with tempfile.TemporaryDirectory() as temp_dir:
            folder_path = Path(temp_dir)
            (folder_path / "manifest.toml").write_text(
                'dataset = "some_db"\npersona = "Some text."\n',
                encoding="utf-8",
            )
            (folder_path / "rules.md").write_text("# Rules\n\n", encoding="utf-8")

            with self.assertRaises(knowledge_error) as raised:
                self.knowledge_module.load_knowledge(folder_path, "some_db", limits)

            self.assertIn("rules.md", str(raised.exception))

    def test_load_knowledge_rejects_summary_over_max_chars_and_names_file(self):
        """Given a summary over the configured limit, When loaded, Then KnowledgeError names the file."""
        knowledge_error = self.knowledge_module.KnowledgeError
        limits = self._knowledge_limits()

        with tempfile.TemporaryDirectory() as temp_dir:
            folder_path = Path(temp_dir)
            (folder_path / "manifest.toml").write_text(
                'dataset = "some_db"\npersona = "Some text."\n',
                encoding="utf-8",
            )
            (folder_path / "rules.md").write_text(
                f"# Rules\n\n{'S' * (limits.max_summary_chars + 1)}\n",
                encoding="utf-8",
            )

            with self.assertRaises(knowledge_error) as raised:
                self.knowledge_module.load_knowledge(folder_path, "some_db", limits)

            message = str(raised.exception)
            self.assertIn("rules.md", message)
            self.assertIn(
                f"summary is {limits.max_summary_chars + 1} characters, limit is {limits.max_summary_chars}",
                message,
            )
            self.assertEqual(raised.exception.observed, limits.max_summary_chars + 1)
            self.assertEqual(raised.exception.permitted, limits.max_summary_chars)

    def test_load_knowledge_rejects_bullet_block_after_heading_and_names_file(self):
        """Given a bullet block after the heading, When loaded, Then KnowledgeError names the file."""
        knowledge_error = self.knowledge_module.KnowledgeError
        limits = self._knowledge_limits()

        with tempfile.TemporaryDirectory() as temp_dir:
            folder_path = Path(temp_dir)
            (folder_path / "manifest.toml").write_text(
                'dataset = "some_db"\npersona = "Some text."\n',
                encoding="utf-8",
            )
            (folder_path / "rules.md").write_text(
                "# Rules\n\n- First item\n",
                encoding="utf-8",
            )

            with self.assertRaises(knowledge_error) as raised:
                self.knowledge_module.load_knowledge(folder_path, "some_db", limits)

            self.assertIn("rules.md", str(raised.exception))

    def test_load_knowledge_rejects_ordered_list_block_after_heading_and_names_file(self):
        """Given an ordered-list block after the heading, When loaded, Then KnowledgeError names the file."""
        knowledge_error = self.knowledge_module.KnowledgeError
        limits = self._knowledge_limits()

        with tempfile.TemporaryDirectory() as temp_dir:
            folder_path = Path(temp_dir)
            (folder_path / "manifest.toml").write_text(
                'dataset = "some_db"\npersona = "Some text."\n',
                encoding="utf-8",
            )
            (folder_path / "rules.md").write_text(
                "# Rules\n\n1. First item\n",
                encoding="utf-8",
            )

            with self.assertRaises(knowledge_error) as raised:
                self.knowledge_module.load_knowledge(folder_path, "some_db", limits)

            self.assertIn("rules.md", str(raised.exception))

    def test_load_knowledge_rejects_fence_block_after_heading_and_names_file(self):
        """Given a fenced block after the heading, When loaded, Then KnowledgeError names the file."""
        knowledge_error = self.knowledge_module.KnowledgeError
        limits = self._knowledge_limits()

        with tempfile.TemporaryDirectory() as temp_dir:
            folder_path = Path(temp_dir)
            (folder_path / "manifest.toml").write_text(
                'dataset = "some_db"\npersona = "Some text."\n',
                encoding="utf-8",
            )
            # Tilde fences are the equivalent form in this C3 marker category.
            (folder_path / "rules.md").write_text(
                "# Rules\n\n```\ncode\n```\n",
                encoding="utf-8",
            )

            with self.assertRaises(knowledge_error) as raised:
                self.knowledge_module.load_knowledge(folder_path, "some_db", limits)

            self.assertIn("rules.md", str(raised.exception))

    def test_load_knowledge_rejects_heading_block_after_heading_and_names_file(self):
        """Given another heading block after the heading, When loaded, Then KnowledgeError names the file."""
        knowledge_error = self.knowledge_module.KnowledgeError
        limits = self._knowledge_limits()

        with tempfile.TemporaryDirectory() as temp_dir:
            folder_path = Path(temp_dir)
            (folder_path / "manifest.toml").write_text(
                'dataset = "some_db"\npersona = "Some text."\n',
                encoding="utf-8",
            )
            (folder_path / "rules.md").write_text(
                "# Rules\n\n## Details\n",
                encoding="utf-8",
            )

            with self.assertRaises(knowledge_error) as raised:
                self.knowledge_module.load_knowledge(folder_path, "some_db", limits)

            self.assertIn("rules.md", str(raised.exception))

    def test_load_knowledge_rejects_quote_block_after_heading_and_names_file(self):
        """Given a quote block after the heading, When loaded, Then KnowledgeError names the file."""
        knowledge_error = self.knowledge_module.KnowledgeError
        limits = self._knowledge_limits()

        with tempfile.TemporaryDirectory() as temp_dir:
            folder_path = Path(temp_dir)
            (folder_path / "manifest.toml").write_text(
                'dataset = "some_db"\npersona = "Some text."\n',
                encoding="utf-8",
            )
            (folder_path / "rules.md").write_text(
                "# Rules\n\n> Quoted text\n",
                encoding="utf-8",
            )

            with self.assertRaises(knowledge_error) as raised:
                self.knowledge_module.load_knowledge(folder_path, "some_db", limits)

            self.assertIn("rules.md", str(raised.exception))

    def test_load_knowledge_rejects_table_block_after_heading_and_names_file(self):
        """Given a table block after the heading, When loaded, Then KnowledgeError names the file."""
        knowledge_error = self.knowledge_module.KnowledgeError
        limits = self._knowledge_limits()

        with tempfile.TemporaryDirectory() as temp_dir:
            folder_path = Path(temp_dir)
            (folder_path / "manifest.toml").write_text(
                'dataset = "some_db"\npersona = "Some text."\n',
                encoding="utf-8",
            )
            (folder_path / "rules.md").write_text(
                "# Rules\n\n| Name | Score |\n",
                encoding="utf-8",
            )

            with self.assertRaises(knowledge_error) as raised:
                self.knowledge_module.load_knowledge(folder_path, "some_db", limits)

            self.assertIn("rules.md", str(raised.exception))

    def test_load_knowledge_rejects_html_block_after_heading_and_names_file(self):
        """Given an HTML block after the heading, When loaded, Then KnowledgeError names the file."""
        knowledge_error = self.knowledge_module.KnowledgeError
        limits = self._knowledge_limits()

        with tempfile.TemporaryDirectory() as temp_dir:
            folder_path = Path(temp_dir)
            (folder_path / "manifest.toml").write_text(
                'dataset = "some_db"\npersona = "Some text."\n',
                encoding="utf-8",
            )
            (folder_path / "rules.md").write_text(
                "# Rules\n\n<div>HTML text</div>\n",
                encoding="utf-8",
            )

            with self.assertRaises(knowledge_error) as raised:
                self.knowledge_module.load_knowledge(folder_path, "some_db", limits)

            self.assertIn("rules.md", str(raised.exception))

    def test_document_failures_carry_structured_rules_and_limit_keys(self):
        limits = self._knowledge_limits()
        cases = (
            (b"No heading", "heading_required", None),
            (b"# Heading\n", "paragraph_required", None),
            (b"# " + b"T" * 81 + b"\n\nSummary.", "max_title_chars", "knowledge_max_title_chars"),
            (b"# Heading\n\n" + b"S" * 201, "max_summary_chars", "knowledge_max_summary_chars"),
            (b"x" * 65537, "max_doc_bytes", "knowledge_max_doc_bytes"),
            (b"\xff", "utf8", None),
            (b"# Heading\n\n- list", "bullet list", None),
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            (folder / "manifest.toml").write_text('dataset="some_db"\npersona="Text."\n')
            entry = folder / "rules.md"
            for body, rule, key in cases:
                with self.subTest(rule=rule):
                    entry.write_bytes(body)
                    with self.assertRaises(self.knowledge_module.KnowledgeError) as raised:
                        self.knowledge_module.load_knowledge(folder, "some_db", limits)
                    self.assertEqual(raised.exception.path, entry)
                    self.assertEqual(raised.exception.rule, rule)
                    self.assertEqual(raised.exception.key, key)

    def test_load_knowledge_derives_complete_title_and_multiline_summary(self):
        """Given a valid document, When loaded, Then id, title and joined summary are exact and untruncated."""
        limits = self._knowledge_limits()

        with tempfile.TemporaryDirectory() as temp_dir:
            folder_path = Path(temp_dir)
            (folder_path / "manifest.toml").write_text(
                'dataset = "some_db"\npersona = "Some text."\n',
                encoding="utf-8",
            )
            (folder_path / "scoring-rules.md").write_text(
                "Operator preface.\n\n# Complete scoring rules\n\n"
                "Every word in this summary remains\n"
                "and its second line joins with one space.\n",
                encoding="utf-8",
            )

            knowledge = self.knowledge_module.load_knowledge(folder_path, "some_db", limits)

            self.assertEqual(knowledge.topics[0].id, "scoring-rules")
            self.assertEqual(knowledge.topics[0].title, "Complete scoring rules")
            self.assertEqual(
                knowledge.topics[0].summary,
                "Every word in this summary remains and its second line joins with one space.",
            )

    def test_load_knowledge_strips_only_leading_heading_hashes_and_preserves_markdown(self):
        """Given a decorated heading and summary, When loaded, Then trailing hashes and inline Markdown remain verbatim."""
        limits = self._knowledge_limits()

        with tempfile.TemporaryDirectory() as temp_dir:
            folder_path = Path(temp_dir)
            (folder_path / "manifest.toml").write_text(
                'dataset = "some_db"\npersona = "Some text."\n',
                encoding="utf-8",
            )
            (folder_path / "scoring.md").write_text(
                "Operator preface.\n\n## Scoring rules ##\n\n"
                "Keep *emphasis* and `code` verbatim.\n",
                encoding="utf-8",
            )

            knowledge = self.knowledge_module.load_knowledge(folder_path, "some_db", limits)

            self.assertEqual(knowledge.topics[0].title, "Scoring rules ##")
            self.assertEqual(
                knowledge.topics[0].summary,
                "Keep *emphasis* and `code` verbatim.",
            )

    def test_load_knowledge_rejects_document_over_max_doc_bytes_and_names_file(self):
        """Given a document exceeding max_doc_bytes, When loaded, Then KnowledgeError names the file."""
        knowledge_error = self.knowledge_module.KnowledgeError
        limits = self.knowledge_module.KnowledgeLimits(
            max_title_chars=80,
            max_summary_chars=200,
            max_persona_chars=2000,
            max_topics=50,
            max_doc_bytes=10,
            max_bytes_per_turn=131072,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            folder_path = Path(temp_dir)
            (folder_path / "manifest.toml").write_text(
                'dataset = "some_db"\npersona = "Some text."\n',
                encoding="utf-8",
            )
            oversize_path = folder_path / "rules.md"
            oversize_path.write_bytes(b"# Rules\n\nThis document body is deliberately longer than ten bytes.\n")

            with self.assertRaises(knowledge_error) as raised:
                self.knowledge_module.load_knowledge(folder_path, "some_db", limits)

            message = str(raised.exception)
            self.assertIn("rules.md", message)
            self.assertIn(
                f"document is {len(oversize_path.read_bytes())} bytes, limit is {limits.max_doc_bytes}",
                message,
            )
            self.assertEqual(raised.exception.observed, len(oversize_path.read_bytes()))
            self.assertEqual(raised.exception.permitted, limits.max_doc_bytes)

    def test_load_knowledge_rejects_document_with_invalid_utf8_and_names_file(self):
        """Given a document with invalid UTF-8 bytes, When loaded, Then KnowledgeError names the file, not a raw UnicodeDecodeError."""
        knowledge_error = self.knowledge_module.KnowledgeError
        limits = self._knowledge_limits()

        with tempfile.TemporaryDirectory() as temp_dir:
            folder_path = Path(temp_dir)
            (folder_path / "manifest.toml").write_text(
                'dataset = "some_db"\npersona = "Some text."\n',
                encoding="utf-8",
            )
            bad_utf8_path = folder_path / "rules.md"
            bad_utf8_path.write_bytes(b"# Rules\n\n\xff\xfe invalid bytes here.\n")

            with self.assertRaises(knowledge_error) as raised:
                self.knowledge_module.load_knowledge(folder_path, "some_db", limits)

            self.assertIn("rules.md", str(raised.exception))

    def test_load_knowledge_reports_size_rule_before_decode_when_both_apply(self):
        """Given a document that is both oversize and invalid UTF-8, When loaded, Then the error reports the size rule, not a decode failure - proving size is checked first (decision C6)."""
        knowledge_error = self.knowledge_module.KnowledgeError
        limits = self.knowledge_module.KnowledgeLimits(
            max_title_chars=80,
            max_summary_chars=200,
            max_persona_chars=2000,
            max_topics=50,
            max_doc_bytes=5,
            max_bytes_per_turn=131072,
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            folder_path = Path(temp_dir)
            (folder_path / "manifest.toml").write_text(
                'dataset = "some_db"\npersona = "Some text."\n',
                encoding="utf-8",
            )
            bad_path = folder_path / "rules.md"
            bad_path.write_bytes(b"\xff\xfe more than five bytes of invalid utf-8")

            with self.assertRaises(knowledge_error) as raised:
                self.knowledge_module.load_knowledge(folder_path, "some_db", limits)

            message = str(raised.exception)
            self.assertIn("rules.md", message)
            self.assertNotIn("codec", message.lower())
            self.assertNotIn("decode", message.lower())

    def test_load_knowledge_orders_topics_by_full_filename_byte_order_not_stem(self):
        """Given a-.md and a.md, When loaded, Then topics are ordered by full filename UTF-8 bytes, so 'a-' sorts before 'a' (decision C5)."""
        limits = self._knowledge_limits()

        with tempfile.TemporaryDirectory() as temp_dir:
            folder_path = Path(temp_dir)
            (folder_path / "manifest.toml").write_text(
                'dataset = "some_db"\npersona = "Some text."\n',
                encoding="utf-8",
            )
            (folder_path / "a-.md").write_text(
                "# A Dash\n\nSome summary paragraph text.\n",
                encoding="utf-8",
            )
            (folder_path / "a.md").write_text(
                "# A Plain\n\nSome summary paragraph text.\n",
                encoding="utf-8",
            )

            knowledge = self.knowledge_module.load_knowledge(folder_path, "some_db", limits)

            self.assertEqual(
                tuple(topic.id for topic in knowledge.topics),
                ("a-", "a"),
            )

    def test_compose_system_prompt_without_knowledge_is_byte_exact(self):
        """Given no knowledge, When the prompt is composed, Then it is exactly the neutral persona and six rules."""
        expected_prompt = (
            "You are a data analyst for the connected database. Answer in the language of the user's question.\n\n"
            "- Get data ONLY through the tools.\n"
            "- The tools return a summary, not the rows themselves. If you need rows, call read_rows.\n"
            "- Row budgets are bounded per call and per request. "
            "When a budget is exhausted, answer with what you have.\n"
            "- Once you have received data, call mark_report(handle).\n"
            "- If there is nothing, say so plainly and do not mark a report.\n"
            "- Do not invent numbers or names."
        )

        prompt = self.knowledge_module.compose_system_prompt(None)

        self.assertEqual(prompt, expected_prompt)
        self.assertNotIn(
            "Before answering a question covered by a listed topic, call read_knowledge with that topic id.",
            prompt,
        )
        self.assertNotIn("## Knowledge topics", prompt)

    def test_compose_system_prompt_adds_retrieval_rule_only_with_knowledge(self):
        """Given loaded knowledge and no knowledge, When prompts are composed, Then only the loaded branch has D7."""
        limits = self._knowledge_limits()
        retrieval_rule = (
            "Before answering a question covered by a listed topic, call read_knowledge with that topic id."
        )

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
            knowledge = self.knowledge_module.load_knowledge(folder_path, "some_db", limits)

            knowledge_prompt = self.knowledge_module.compose_system_prompt(knowledge)
            neutral_prompt = self.knowledge_module.compose_system_prompt(None)

            self.assertIn(retrieval_rule, knowledge_prompt)
            self.assertLess(
                knowledge_prompt.index(retrieval_rule),
                knowledge_prompt.index("## Knowledge topics"),
            )
            self.assertNotIn(retrieval_rule, neutral_prompt)

    def test_compose_system_prompt_with_knowledge_has_full_ordered_structure(self):
        """Given three loaded topics, When composed, Then persona, seven rules, heading and ordered topics are exact."""
        limits = self._knowledge_limits()
        persona = "Some text."

        with tempfile.TemporaryDirectory() as temp_dir:
            folder_path = Path(temp_dir)
            (folder_path / "manifest.toml").write_text(
                f'dataset = "some_db"\npersona = "{persona}"\n',
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
            expected_prompt = (
                "Some text.\n\n"
                "- Get data ONLY through the tools.\n"
                "- The tools return a summary, not the rows themselves. If you need rows, call read_rows.\n"
                "- Row budgets are bounded per call and per request. "
                "When a budget is exhausted, answer with what you have.\n"
                "- Once you have received data, call mark_report(handle).\n"
                "- If there is nothing, say so plainly and do not mark a report.\n"
                "- Do not invent numbers or names.\n"
                "- Before answering a question covered by a listed topic, "
                "call read_knowledge with that topic id.\n\n"
                "## Knowledge topics\n\n"
                "glossary: Glossary. Some summary paragraph text.\n"
                "rules: Rules. Some summary paragraph text.\n"
                "scoring: Scoring. Some summary paragraph text."
            )

            prompt = self.knowledge_module.compose_system_prompt(knowledge)

            self.assertEqual(prompt, expected_prompt)
            self.assertIn(persona, prompt)
            self.assertEqual(
                tuple(topic.id for topic in knowledge.topics),
                ("glossary", "rules", "scoring"),
            )

    def test_compose_system_prompt_suppresses_separator_after_terminal_punctuation(self):
        """Given punctuated and plain titles, When composed, Then only the plain title receives a separator period."""
        limits = self._knowledge_limits()

        with tempfile.TemporaryDirectory() as temp_dir:
            folder_path = Path(temp_dir)
            (folder_path / "manifest.toml").write_text(
                'dataset = "some_db"\npersona = "Some text."\n',
                encoding="utf-8",
            )
            (folder_path / "question.md").write_text(
                "## Что такое счёт?\n\nRussian score summary.\n",
                encoding="utf-8",
            )
            (folder_path / "scoring.md").write_text(
                "# Scoring\n\nEnglish scoring summary.\n",
                encoding="utf-8",
            )
            knowledge = self.knowledge_module.load_knowledge(folder_path, "some_db", limits)

            prompt = self.knowledge_module.compose_system_prompt(knowledge)

            self.assertIn("question: Что такое счёт? Russian score summary.", prompt)
            self.assertNotIn("Что такое счёт?.", prompt)
            self.assertIn("scoring: Scoring. English scoring summary.", prompt)

    def test_compose_system_prompt_without_knowledge_omits_forbidden_numeric_budgets(self):
        """Given no knowledge, When the prompt is composed, Then removed literal budget figures stay absent."""
        prompt = self.knowledge_module.compose_system_prompt(None)

        self.assertNotIn("256", prompt)
        self.assertNotIn("1024", prompt)

    def test_compose_system_prompt_is_database_agnostic_for_library_catalogue(self):
        limits = self._knowledge_limits()
        persona = "You are a data analyst for a public library catalogue."

        with tempfile.TemporaryDirectory() as temp_dir:
            folder_path = Path(temp_dir)
            (folder_path / "manifest.toml").write_text(
                f'dataset = "library"\npersona = "{persona}"\n',
                encoding="utf-8",
            )
            (folder_path / "catalogue.md").write_text(
                "# Catalogue\n\nBook records include titles, authors, subjects, and shelf locations.\n",
                encoding="utf-8",
            )
            (folder_path / "lending.md").write_text(
                "# Lending\n\nLoan records track checkout dates, due dates, and borrower activity.\n",
                encoding="utf-8",
            )
            knowledge = self.knowledge_module.load_knowledge(folder_path, "library", limits)

            prompt = self.knowledge_module.compose_system_prompt(knowledge)
            prompt_lower = prompt.lower()

            self.assertIn(persona, prompt)
            self.assertIn(
                "catalogue: Catalogue. Book records include titles, authors, subjects, and shelf locations.",
                prompt,
            )
            self.assertIn(
                "lending: Lending. Loan records track checkout dates, due dates, and borrower activity.",
                prompt,
            )
            for forbidden_string in GAME_DOMAIN_FORBIDDEN_STRINGS:
                self.assertNotIn(forbidden_string.lower(), prompt_lower)

    def test_agent_packages_and_neutral_prompt_are_free_of_dataset_strings(self):
        """Both agent packages learn their surface from the operator's module, so neither names one.

        The scan deliberately stops at these two packages. acceptance_fixture.py sits in
        webreport/backend/ rather than inside either, because it is a stand-in operator
        module and must be free to name its own domain; a later reader should not widen this
        to the whole backend directory.
        """
        backend_path = Path(__file__).parent
        scanned_packages = (backend_path / "agent", backend_path / "agents")
        forbidden_strings = tuple(
            forbidden_string.lower() for forbidden_string in GAME_DOMAIN_FORBIDDEN_STRINGS
        )

        for package_path in scanned_packages:
            for source_path in sorted(package_path.rglob("*.py")):
                source = source_path.read_text(encoding="utf-8").lower()
                for forbidden_string in forbidden_strings:
                    with self.subTest(
                        path=source_path.relative_to(backend_path),
                        forbidden_string=forbidden_string,
                    ):
                        self.assertNotIn(forbidden_string, source)

        neutral_prompt = self.knowledge_module.compose_system_prompt(None).lower()
        for forbidden_string in forbidden_strings:
            with self.subTest(path="compose_system_prompt(None)", forbidden_string=forbidden_string):
                self.assertNotIn(forbidden_string, neutral_prompt)

    def test_config_preserves_raw_limits_for_backend_validation(self):
        config_module = importlib.import_module("bd_shared.config")
        config_source = inspect.getfile(config_module)
        base_config = Path(config_source).with_name("test_config.toml").read_text()
        fields = tuple(vars(self._knowledge_limits()))
        cases = (("\"abc\"", "abc"), ("true", True), ("false", False),
                 ("1.5", 1.5), ("0", 0), ("-1", -1), ("1", 1), ("17", 17))
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            for field in fields:
                key = f"knowledge_{field}"
                for toml_value, expected in cases:
                    with self.subTest(key=key, value=expected):
                        config_path.write_text(base_config.replace(
                            "[webreport]\n", f"[webreport]\n{key} = {toml_value}\n"
                        ))
                        with patch.dict(os.environ, {"BD_CONFIG_FILE": str(config_path)}):
                            raw_config = runpy.run_path(config_source)
                        value = raw_config[key.upper()]
                        self.assertEqual(value, expected)
                        self.assertIs(type(value), type(expected))
                        limits = self.knowledge_module.KnowledgeLimits(**{
                            name: raw_config[f"KNOWLEDGE_{name.upper()}"]
                            for name in fields
                        })
                        if type(expected) is int and expected >= 1:
                            self.knowledge_module.validate_limits(limits)
                        else:
                            with self.assertRaises(self.knowledge_module.KnowledgeError) as raised:
                                self.knowledge_module.validate_limits(limits)
                            error = raised.exception
                            self.assertEqual(error.key, key)
                            self.assertEqual(error.rule, "integer_minimum")
                            self.assertEqual(error.observed, expected)
                            self.assertIs(type(error.observed), type(expected))
                            self.assertEqual(error.permitted, 1)

    def test_invalid_toml_limits_abort_real_startup_before_database(self):
        config_module = importlib.import_module("bd_shared.config")
        base_config = Path(inspect.getfile(config_module)).with_name("test_config.toml").read_text()
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            probe_path = Path(temp_dir) / "startup_probe.py"
            probe_path.write_text(
                "import asyncio\n"
                "from unittest.mock import AsyncMock, patch\n"
                "import main\n"
                "from agent.knowledge import KnowledgeError\n"
                "async def probe():\n"
                "    assert main.KNOWLEDGE_DIR is None\n"
                "    with patch.object(main, 'initialize_tool_service_with_retry', "
                "new=AsyncMock()) as db:\n"
                "        try:\n"
                "            await main.startup_event()\n"
                "        except KnowledgeError as error:\n"
                "            assert error.key == 'knowledge_max_topics'\n"
                "            db.assert_not_called()\n"
                "        else:\n"
                "            raise AssertionError('invalid limit accepted')\n"
                "asyncio.run(probe())\n"
            )
            for value in ('"abc"', 'true', '1.5', '0'):
                with self.subTest(value=value):
                    config_path.write_text(base_config.replace(
                        "[webreport]\n", f"[webreport]\nknowledge_max_topics = {value}\n"
                    ))
                    result = subprocess.run(
                        [sys.executable, str(probe_path)],
                        env={**os.environ, "BD_CONFIG_FILE": str(config_path),
                             "PYTHONPATH": os.pathsep.join((str(Path(__file__).parent),
                                                           os.environ.get("PYTHONPATH", "")))},
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True, timeout=30,
                    )
                    self.assertEqual(result.returncode, 0, result.stdout)

    def test_load_knowledge_rejects_each_below_one_limit_and_names_key(self):
        knowledge_error = self.knowledge_module.KnowledgeError
        limit_cases = (
            ("max_title_chars", "knowledge_max_title_chars"),
            ("max_summary_chars", "knowledge_max_summary_chars"),
            ("max_persona_chars", "knowledge_max_persona_chars"),
            ("max_topics", "knowledge_max_topics"),
            ("max_doc_bytes", "knowledge_max_doc_bytes"),
        )
        valid_limit_values = {
            "max_title_chars": 80,
            "max_summary_chars": 200,
            "max_persona_chars": 2000,
            "max_topics": 50,
            "max_doc_bytes": 65536,
            "max_bytes_per_turn": 131072,
        }

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

            for field_name, config_key in limit_cases:
                with self.subTest(config_key=config_key):
                    limit_values = dict(valid_limit_values)
                    limit_values[field_name] = 0
                    limits = self.knowledge_module.KnowledgeLimits(**limit_values)

                    with self.assertRaises(knowledge_error) as raised:
                        self.knowledge_module.load_knowledge(folder_path, "some_db", limits)

                    self.assertIn(config_key, str(raised.exception))

    def test_load_knowledge_rejects_each_non_integer_limit_and_names_key(self):
        knowledge_error = self.knowledge_module.KnowledgeError
        limit_cases = (
            ("max_title_chars", "knowledge_max_title_chars", 80.5),
            ("max_summary_chars", "knowledge_max_summary_chars", 200.5),
            ("max_persona_chars", "knowledge_max_persona_chars", 2000.5),
            ("max_topics", "knowledge_max_topics", 50.5),
            ("max_doc_bytes", "knowledge_max_doc_bytes", 65536.5),
        )
        valid_limit_values: dict[str, int | float] = {
            "max_title_chars": 80,
            "max_summary_chars": 200,
            "max_persona_chars": 2000,
            "max_topics": 50,
            "max_doc_bytes": 65536,
            "max_bytes_per_turn": 131072,
        }

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

            for field_name, config_key, invalid_value in limit_cases:
                with self.subTest(config_key=config_key):
                    limit_values = dict(valid_limit_values)
                    limit_values[field_name] = invalid_value
                    limits = self.knowledge_module.KnowledgeLimits(**limit_values)

                    with self.assertRaises(knowledge_error) as raised:
                        self.knowledge_module.load_knowledge(folder_path, "some_db", limits)

                    self.assertIn(config_key, str(raised.exception))

    def test_load_knowledge_rejects_boolean_topics_limit_and_names_key(self):
        knowledge_error = self.knowledge_module.KnowledgeError
        limits = self.knowledge_module.KnowledgeLimits(
            max_title_chars=80,
            max_summary_chars=200,
            max_persona_chars=2000,
            max_topics=True,
            max_doc_bytes=65536,
            max_bytes_per_turn=131072,
        )

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

            with self.assertRaises(knowledge_error) as raised:
                self.knowledge_module.load_knowledge(folder_path, "some_db", limits)

            self.assertIn("knowledge_max_topics", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
