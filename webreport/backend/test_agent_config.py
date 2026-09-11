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
                .replace("[dataset]\n", '[dataset]\nknowledge_dir = ""\n', 1)
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
                .replace("[dataset]\n", '[dataset]\nknowledge_dir = "some/relative/dir"\n', 1)
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
                .replace("[dataset]\n", '[dataset]\nknowledge_dir = "/some/absolute/dir"\n', 1)
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
                        .replace("[dataset]\n", f'[dataset]\nknowledge_dir = "{raw_value}"\n', 1)
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
                .replace("[dataset]\n", '[dataset]\nknowledge_dir = "definitely/does/not/exist/anywhere"\n', 1)
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


class DatabaseNameDerivationTests(unittest.TestCase):
    """Cases for _derive_database_name, called directly so no URL ever reaches a driver."""

    def setUp(self):
        self.config_module = importlib.import_module("bd_shared.config")

    def test_server_url_yields_the_url_database(self):
        """Given a server URL, When the name is derived, Then the URL database is used."""
        cases = {
            "mysql+pymysql://durak:devpass@localhost:3306/bez_durakov": "bez_durakov",
            "postgresql+psycopg://u:p@pg:5432/warehouse": "warehouse",
        }
        for url, expected in cases.items():
            with self.subTest(url=url):
                self.assertEqual(self.config_module._derive_database_name(url), expected)

    def test_file_url_yields_the_file_stem(self):
        """Given a file-based URL, When the name is derived, Then the file stem is used."""
        cases = {
            "sqlite:////data/library.db": "library",
            "sqlite:///library.db": "library",
        }
        for url, expected in cases.items():
            with self.subTest(url=url):
                self.assertEqual(self.config_module._derive_database_name(url), expected)

    def test_url_without_a_database_part_is_rejected_naming_the_scheme(self):
        """Given a URL with no database part, When the name is derived, Then ValueError names the scheme."""
        with self.assertRaises(ValueError) as caught:
            self.config_module._derive_database_name("sqlite://")
        self.assertIn("sqlite", str(caught.exception))

    def test_in_memory_sqlite_is_rejected(self):
        """Given an in-memory SQLite URL, When the name is derived, Then it is rejected."""
        with self.assertRaises(ValueError) as caught:
            self.config_module._derive_database_name("sqlite:///:memory:")
        self.assertIn("in-memory SQLite is not supported", str(caught.exception))

    def test_derivation_opens_no_socket(self):
        """Given socket creation is patched to fail, When every URL is derived, Then no socket is opened."""
        with patch("socket.socket", side_effect=RuntimeError("attempted to open a socket during derivation")):
            self.assertEqual(
                self.config_module._derive_database_name("mysql+pymysql://u:p@h:3306/db"),
                "db",
            )
            self.assertEqual(
                self.config_module._derive_database_name("sqlite:////data/library.db"),
                "library",
            )


class DatasetConfigTests(unittest.TestCase):
    """Cases for the [dataset] section and its soft configuration error."""

    def _reload_with(self, transform):
        """Reload bd_shared.config from a temporary copy of test_config.toml."""
        config_module = importlib.import_module("bd_shared.config")
        with tempfile.TemporaryDirectory(dir="/tmp") as directory:
            config_path = Path(directory) / "config.toml"
            config_path.write_text(transform(Path("/bd_shared/test_config.toml").read_text()))
            with patch.dict(os.environ, {"BD_CONFIG_FILE": str(config_path)}):
                return importlib.reload(config_module)

    def tearDown(self):
        config_module = importlib.import_module("bd_shared.config")
        with patch.dict(os.environ, {"BD_CONFIG_FILE": "config.toml"}):
            importlib.reload(config_module)

    def test_tools_module_is_read_from_the_dataset_section(self):
        """Given a [dataset] tools_module, When config loads, Then DATASET_TOOLS_MODULE carries it."""
        config_module = self._reload_with(
            lambda text: text.replace(
                'tools_module = "bd_shared.tools.bez_durakov"',
                'tools_module = "some.operator.module"',
                1,
            )
        )
        self.assertEqual(config_module.DATASET_TOOLS_MODULE, "some.operator.module")
        self.assertIsNone(config_module.DATASET_CONFIG_ERROR)

    def test_knowledge_dir_is_read_from_the_dataset_section(self):
        """Given a [dataset] knowledge_dir, When config loads, Then KNOWLEDGE_DIR resolves from it."""
        config_module = self._reload_with(
            lambda text: text.replace(
                "[dataset]\n", '[dataset]\nknowledge_dir = "/operator/knowledge"\n', 1
            )
        )
        self.assertEqual(config_module.KNOWLEDGE_DIR, Path("/operator/knowledge"))

    def test_missing_tools_module_reports_an_error_naming_the_key(self):
        """Given no tools_module, When config loads, Then DATASET_CONFIG_ERROR names the key."""
        config_module = self._reload_with(
            lambda text: text.replace(
                '\ntools_module = "bd_shared.tools.bez_durakov"', "", 1
            )
        )
        self.assertIsNotNone(config_module.DATASET_CONFIG_ERROR)
        self.assertIn("dataset.tools_module", config_module.DATASET_CONFIG_ERROR)

    def test_empty_tools_module_reports_the_same_error(self):
        """Given an empty tools_module, When config loads, Then DATASET_CONFIG_ERROR is set."""
        config_module = self._reload_with(
            lambda text: text.replace(
                'tools_module = "bd_shared.tools.bez_durakov"', 'tools_module = ""', 1
            )
        )
        self.assertIsNotNone(config_module.DATASET_CONFIG_ERROR)
        self.assertIn("dataset.tools_module", config_module.DATASET_CONFIG_ERROR)

    def test_leftover_webreport_knowledge_dir_reports_both_locations(self):
        """Given knowledge_dir still under [webreport], When config loads, Then the error names both locations."""
        config_module = self._reload_with(
            lambda text: text.replace(
                "[webreport]\n", '[webreport]\nknowledge_dir = "knowledge/bez_durakov"\n', 1
            )
        )
        self.assertIsNotNone(config_module.DATASET_CONFIG_ERROR)
        self.assertIn("webreport.knowledge_dir", config_module.DATASET_CONFIG_ERROR)
        self.assertIn("dataset.knowledge_dir", config_module.DATASET_CONFIG_ERROR)

    def test_importing_the_module_never_raises_for_a_dataset_error(self):
        """Given a broken [dataset] section, When the module imports, Then it still imports."""
        config_module = self._reload_with(lambda text: text.replace("[dataset]\n", "", 1))
        self.assertEqual(config_module.DATASET_TOOLS_MODULE, "")
        self.assertIsNotNone(config_module.DATASET_CONFIG_ERROR)

    def test_the_shipped_config_has_no_dataset_error(self):
        """Given the shipped config.toml, When config loads, Then DATASET_CONFIG_ERROR is None."""
        config_module = importlib.import_module("bd_shared.config")
        with patch.dict(os.environ, {"BD_CONFIG_FILE": "config.toml"}):
            reloaded = importlib.reload(config_module)
        self.assertIsNone(reloaded.DATASET_CONFIG_ERROR)
        self.assertEqual(reloaded.DATASET_TOOLS_MODULE, "bd_shared.tools.bez_durakov")


if __name__ == "__main__":
    unittest.main()
