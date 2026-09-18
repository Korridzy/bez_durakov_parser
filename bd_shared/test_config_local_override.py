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


def load_config(overlay_path: str | None) -> subprocess.CompletedProcess[str]:
    """Import the config module in a fresh interpreter and dump the values it derived."""
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(PROJECT_ROOT)
    environment.pop("BD_CONFIG_FILE", None)
    environment.pop("BD_DOCKER", None)
    environment.pop("BD_CONFIG_LOCAL_FILE", None)
    if overlay_path is not None:
        environment["BD_CONFIG_LOCAL_FILE"] = overlay_path
    return subprocess.run(
        [sys.executable, "-c", PROBE],
        cwd=str(PROJECT_ROOT),
        env=environment,
        capture_output=True,
        text=True,
    )


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
