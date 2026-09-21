"""Cover the out-of-tree local override that the DATASET switch depends on.

The webreport stack serves whichever database `bd_shared/config.toml` names, and a second
dataset keeps its own overlay outside the repository. `BD_CONFIG_LOCAL_FILE` is the seam
that lets an operator point the loader at that overlay without editing a tracked file, so
these cases pin the three behaviours the switch relies on: an out-of-tree overlay wins over
the in-tree one, an unset variable keeps the in-tree overlay, and a missing overlay file is
a loud failure instead of a silent fallback to the wrong dataset.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

PROBE = (
    "import json;"
    "from bd_shared.config import DATABASE_URL, DATASET_TOOLS_MODULE, KNOWLEDGE_DIR, AGENT_MODEL;"
    "print(json.dumps({"
    "'database_url': DATABASE_URL,"
    "'tools_module': DATASET_TOOLS_MODULE,"
    "'knowledge_dir': None if KNOWLEDGE_DIR is None else str(KNOWLEDGE_DIR),"
    "'agent_model': AGENT_MODEL}))"
)

ARCHIVE_PROBE = (
    "import json;"
    "from bd_shared.config import ("
    "ARCHIVE_ENABLED, ARCHIVE_DB_PATH, ARCHIVE_RETENTION_DAYS, ARCHIVE_STORE_REASONING, "
    "ARCHIVE_REASONING_RETENTION_DAYS, ARCHIVE_SWEEP_INTERVAL_SECONDS, "
    "LANGFUSE_HOST, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_ENABLED);"
    "print(json.dumps({"
    "'archive_enabled': ARCHIVE_ENABLED,"
    "'archive_db_path': ARCHIVE_DB_PATH,"
    "'archive_retention_days': ARCHIVE_RETENTION_DAYS,"
    "'archive_store_reasoning': ARCHIVE_STORE_REASONING,"
    "'archive_reasoning_retention_days': ARCHIVE_REASONING_RETENTION_DAYS,"
    "'archive_sweep_interval_seconds': ARCHIVE_SWEEP_INTERVAL_SECONDS,"
    "'langfuse_host': LANGFUSE_HOST,"
    "'langfuse_public_key': LANGFUSE_PUBLIC_KEY,"
    "'langfuse_secret_key': LANGFUSE_SECRET_KEY,"
    "'langfuse_enabled': LANGFUSE_ENABLED}))"
)


def run_probe(
    probe: str,
    *,
    overlay_path: str | None = None,
    config_path: str | None = None,
    environment_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Import the config module in a fresh interpreter and dump the values it derived."""
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(PROJECT_ROOT)
    environment.pop("BD_CONFIG_FILE", None)
    environment.pop("BD_DOCKER", None)
    environment.pop("BD_CONFIG_LOCAL_FILE", None)
    environment.pop("BD_ARCHIVE_DB_PATH", None)
    if config_path is not None:
        environment["BD_CONFIG_FILE"] = config_path
    if overlay_path is not None:
        environment["BD_CONFIG_LOCAL_FILE"] = overlay_path
    if environment_overrides:
        environment.update(environment_overrides)
    return subprocess.run(
        [sys.executable, "-c", probe],
        cwd=str(PROJECT_ROOT),
        env=environment,
        capture_output=True,
        text=True,
    )


def load_config(overlay_path: str | None) -> subprocess.CompletedProcess[str]:
    return run_probe(PROBE, overlay_path=overlay_path)


def write_scratch_config(directory: str, archive_db_path: str | None = None) -> Path:
    archive_setting = "" if archive_db_path is None else f'archive_db_path = "{archive_db_path}"\n'
    config_path = Path(directory) / "config.toml"
    config_path.write_text(
        "[database]\n"
        'url = "sqlite:///probe.db"\n'
        "\n"
        "[application]\n"
        'default_game_date = "02.03.2022"\n'
        "\n"
        "[webreport]\n"
        + archive_setting,
        encoding="utf-8",
    )
    return config_path


class TestConfigLocalOverride(unittest.TestCase):
    def test_out_of_tree_overlay_replaces_the_in_tree_one(self):
        """Given an overlay outside the repository, When config loads, Then its values win."""
        with tempfile.TemporaryDirectory() as directory:
            overlay = Path(directory) / "config.local.toml"
            _ = overlay.write_text(
                '[database]\n'
                'url = "mysql+pymysql://probe:probe@127.0.0.1:3307/probe_db"\n'
                '\n'
                '[dataset]\n'
                'tools_module = "probe.tools"\n'
                'knowledge_dir = "/probe/knowledge"\n',
                encoding="utf-8",
            )
            result = load_config(str(overlay))

        self.assertEqual(result.returncode, 0, result.stderr)
        values = json.loads(result.stdout)
        self.assertEqual(
            values["database_url"], "mysql+pymysql://probe:probe@127.0.0.1:3307/probe_db"
        )
        self.assertEqual(values["tools_module"], "probe.tools")
        self.assertEqual(values["knowledge_dir"], "/probe/knowledge")
        print("✅ BD_CONFIG_LOCAL_FILE: an out-of-tree overlay supplies database and dataset")

    def test_unset_variable_keeps_the_in_tree_overlay(self):
        """Given no override, When config loads, Then the tracked defaults still apply."""
        result = load_config(None)

        self.assertEqual(result.returncode, 0, result.stderr)
        values = json.loads(result.stdout)
        self.assertEqual(values["tools_module"], "bd_shared.tools.bez_durakov")
        self.assertTrue(
            values["database_url"].endswith("/bez_durakov"),
            f"default database URL should still name bez_durakov, got {values['database_url']}",
        )
        print("✅ BD_CONFIG_LOCAL_FILE unset: the bez_durakov defaults are untouched")

    def test_archive_defaults_from_scratch_config(self):
        """Given no archive keys, When config loads, Then tracked defaults apply."""
        with tempfile.TemporaryDirectory() as directory:
            config_path = write_scratch_config(directory)
            result = run_probe(ARCHIVE_PROBE, config_path=str(config_path))

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            json.loads(result.stdout),
            {
                "archive_enabled": True,
                "archive_db_path": "/data/conversations.db",
                "archive_retention_days": 0,
                "archive_store_reasoning": True,
                "archive_reasoning_retention_days": 30,
                "archive_sweep_interval_seconds": 600,
                "langfuse_host": "",
                "langfuse_public_key": "",
                "langfuse_secret_key": "",
                "langfuse_enabled": False,
            },
        )
        print("✅ archive config: scratch configs receive every tracked default")

    def test_langfuse_credentials_enable_langfuse(self):
        """Given all Langfuse credentials, When config loads, Then Langfuse is enabled."""
        with tempfile.TemporaryDirectory() as directory:
            config_path = write_scratch_config(directory)
            overlay = Path(directory) / "config.local.toml"
            overlay.write_text(
                "[webreport]\n"
                'langfuse_host = "https://langfuse.example"\n'
                'langfuse_public_key = "pk-probe"\n'
                'langfuse_secret_key = "sk-probe"\n',
                encoding="utf-8",
            )
            result = run_probe(
                ARCHIVE_PROBE,
                config_path=str(config_path),
                overlay_path=str(overlay),
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        values = json.loads(result.stdout)
        self.assertTrue(values["langfuse_enabled"])
        self.assertEqual(values["langfuse_host"], "https://langfuse.example")
        print("✅ Langfuse config: three credentials enable tracing")

    def test_any_empty_langfuse_credential_disables_langfuse(self):
        """Given any empty credential, When config loads, Then Langfuse stays disabled."""
        credentials = {
            "langfuse_host": "https://langfuse.example",
            "langfuse_public_key": "pk-probe",
            "langfuse_secret_key": "sk-probe",
        }
        with tempfile.TemporaryDirectory() as directory:
            config_path = write_scratch_config(directory)
            overlay = Path(directory) / "config.local.toml"
            for missing in credentials:
                values = {**credentials, missing: ""}
                overlay.write_text(
                    "[webreport]\n"
                    + "\n".join(f'{key} = "{value}"' for key, value in values.items())
                    + "\n",
                    encoding="utf-8",
                )
                result = run_probe(
                    ARCHIVE_PROBE,
                    config_path=str(config_path),
                    overlay_path=str(overlay),
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertFalse(json.loads(result.stdout)["langfuse_enabled"], missing)
        print("✅ Langfuse config: each empty credential disables tracing")

    def test_archive_db_path_environment_override_wins(self):
        """Given an archive path environment variable, When config loads, Then it wins."""
        with tempfile.TemporaryDirectory() as directory:
            config_path = write_scratch_config(directory, "/config/conversations.db")
            result = run_probe(
                ARCHIVE_PROBE,
                config_path=str(config_path),
                environment_overrides={"BD_ARCHIVE_DB_PATH": "/env/conversations.db"},
            )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["archive_db_path"], "/env/conversations.db")
        print("✅ archive config: BD_ARCHIVE_DB_PATH overrides the file setting")

    def test_missing_overlay_file_is_an_error(self):
        """Given a path that does not exist, When config loads, Then it fails loudly."""
        result = load_config(str(PROJECT_ROOT / "bd_shared" / "no_such_overlay.toml"))

        self.assertNotEqual(
            result.returncode, 0, "a missing overlay must not be silently ignored"
        )
        self.assertIn("no_such_overlay.toml", result.stderr)
        print("✅ BD_CONFIG_LOCAL_FILE: a missing overlay file fails the import")


if __name__ == "__main__":
    unittest.main(verbosity=2)
