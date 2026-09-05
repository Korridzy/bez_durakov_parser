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


if __name__ == "__main__":
    unittest.main()
