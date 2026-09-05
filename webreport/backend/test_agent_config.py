"""Configuration cases for the operator knowledge folder settings."""

import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, "/")


class KnowledgeConfigTests(unittest.TestCase):
    def _reload_config(self, env=None, unset=()):
        """Reload bd_shared.config under a temporary environment."""
        config_module = importlib.import_module("bd_shared.config")

        with patch.dict(os.environ, {"BD_CONFIG_FILE": "config.toml", **(env or {})}):
            for name in unset:
                os.environ.pop(name, None)
            return importlib.reload(config_module)

    def tearDown(self):
        self._reload_config()

    def test_knowledge_max_defaults_when_keys_are_absent(self):
        """Given no knowledge keys, When config loads, Then all limits use their defaults."""
        config_module = self._reload_config({"BD_CONFIG_FILE": "test_config.toml"})

        expected_defaults = {
            "KNOWLEDGE_MAX_TITLE_CHARS": 80,
            "KNOWLEDGE_MAX_SUMMARY_CHARS": 200,
            "KNOWLEDGE_MAX_PERSONA_CHARS": 2000,
            "KNOWLEDGE_MAX_TOPICS": 50,
            "KNOWLEDGE_MAX_DOC_BYTES": 65536,
        }
        for name, expected in expected_defaults.items():
            with self.subTest(constant=name):
                self.assertEqual(getattr(config_module, name), expected)

    def test_knowledge_dir_is_none_when_key_is_unset(self):
        """Given no knowledge_dir key, When config loads, Then KNOWLEDGE_DIR is None."""
        config_module = self._reload_config({"BD_CONFIG_FILE": "test_config.toml"})

        self.assertIsNone(config_module.KNOWLEDGE_DIR)

    def test_knowledge_dir_empty_value_is_none(self):
        """Given an empty knowledge_dir, When config loads, Then KNOWLEDGE_DIR is None."""
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            config_path = Path(directory) / "config.toml"
            config_path.write_text(
                Path("/bd_shared/test_config.toml")
                .read_text()
                .replace("[webreport]\n", '[webreport]\nknowledge_dir = ""\n', 1)
            )
            config_module = self._reload_config({"BD_CONFIG_FILE": str(config_path)})

        self.assertIsNone(config_module.KNOWLEDGE_DIR)

    def test_knowledge_settings_read_webreport_section_override(self):
        """Given a webreport override, When config loads, Then the section value wins."""
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            config_path = Path(directory) / "config.toml"
            config_path.write_text(
                Path("/bd_shared/test_config.toml")
                .read_text()
                .replace(
                    "[webreport]\n",
                    "[webreport]\nknowledge_max_topics = 7\n",
                    1,
                )
            )
            config_module = self._reload_config({"BD_CONFIG_FILE": str(config_path)})

        self.assertEqual(config_module.KNOWLEDGE_MAX_TOPICS, 7)

    def test_knowledge_dir_relative_value_resolves_against_bd_shared_directory(self):
        """Given a relative knowledge_dir, When config loads, Then it resolves against the bd_shared package directory."""
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            config_path = Path(directory) / "config.toml"
            config_path.write_text(
                Path("/bd_shared/test_config.toml")
                .read_text()
                .replace("[webreport]\n", '[webreport]\nknowledge_dir = "some/relative/dir"\n', 1)
            )
            config_module = self._reload_config({"BD_CONFIG_FILE": str(config_path)})

        expected = Path(config_module.config_directory) / "some/relative/dir"
        self.assertEqual(config_module.KNOWLEDGE_DIR, expected)

    def test_knowledge_dir_absolute_value_is_returned_unchanged(self):
        """Given an absolute knowledge_dir, When config loads, Then it is used unchanged."""
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            config_path = Path(directory) / "config.toml"
            config_path.write_text(
                Path("/bd_shared/test_config.toml")
                .read_text()
                .replace("[webreport]\n", '[webreport]\nknowledge_dir = "/some/absolute/dir"\n', 1)
            )
            config_module = self._reload_config({"BD_CONFIG_FILE": str(config_path)})

        self.assertEqual(config_module.KNOWLEDGE_DIR, Path("/some/absolute/dir"))

    def test_knowledge_dir_resolved_value_is_always_an_absolute_path(self):
        """Given either a relative or absolute knowledge_dir, When config loads, Then KNOWLEDGE_DIR is always an absolute pathlib.Path."""
        for raw_value in ("relative/dir", "/absolute/dir"):
            with self.subTest(raw_value=raw_value):
                with tempfile.TemporaryDirectory(dir="/tmp") as directory:
                    config_path = Path(directory) / "config.toml"
                    config_path.write_text(
                        Path("/bd_shared/test_config.toml")
                        .read_text()
                        .replace("[webreport]\n", f'[webreport]\nknowledge_dir = "{raw_value}"\n', 1)
                    )
                    config_module = self._reload_config({"BD_CONFIG_FILE": str(config_path)})

                self.assertIsInstance(config_module.KNOWLEDGE_DIR, Path)
                self.assertTrue(config_module.KNOWLEDGE_DIR.is_absolute())

    def test_knowledge_dir_resolves_without_requiring_existence(self):
        """Given a knowledge_dir that does not exist on disk, When config loads, Then it still resolves to a Path rather than raising or returning None."""
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            config_path = Path(directory) / "config.toml"
            config_path.write_text(
                Path("/bd_shared/test_config.toml")
                .read_text()
                .replace("[webreport]\n", '[webreport]\nknowledge_dir = "definitely/does/not/exist/anywhere"\n', 1)
            )
            config_module = self._reload_config({"BD_CONFIG_FILE": str(config_path)})

        self.assertIsInstance(config_module.KNOWLEDGE_DIR, Path)
        self.assertFalse(config_module.KNOWLEDGE_DIR.exists())

    def test_database_name_matches_local_url_without_bd_docker(self):
        """Given BD_DOCKER is unset, When config loads, Then DATABASE_NAME derives from database.url."""
        config_module = self._reload_config(unset=("BD_DOCKER",))
        self.assertEqual(config_module.DATABASE_NAME, "bez_durakov")

    def test_database_name_matches_docker_url_with_bd_docker(self):
        """Given BD_DOCKER=1, When config loads, Then DATABASE_NAME still derives correctly from database.docker_url."""
        config_module = self._reload_config({"BD_DOCKER": "1"})
        self.assertEqual(config_module.DATABASE_NAME, "bez_durakov")

    def test_database_name_under_test_config_is_the_test_database(self):
        """Given BD_CONFIG_FILE=test_config.toml, When config loads, Then DATABASE_NAME is bez_durakov_test."""
        config_module = self._reload_config({"BD_CONFIG_FILE": "test_config.toml"})
        self.assertEqual(config_module.DATABASE_NAME, "bez_durakov_test")

    def test_database_name_derivation_opens_no_socket(self):
        """Given socket creation is patched to fail, When config reloads, Then DATABASE_NAME is still derived without opening a connection."""
        with patch("socket.socket", side_effect=RuntimeError("attempted to open a socket during DATABASE_NAME derivation")):
            config_module = self._reload_config({"BD_CONFIG_FILE": "test_config.toml"})
        self.assertEqual(config_module.DATABASE_NAME, "bez_durakov_test")


if __name__ == "__main__":
    unittest.main()
