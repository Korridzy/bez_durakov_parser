"""Regression tests for the knowledge preflight CLI exit statuses."""

import io
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from agent import knowledge_cli

BACKEND_DIR = Path(__file__).parent
SCRATCH_BASE_CONFIG = Path("/bd_shared/test_config.toml")

# test_config.toml names the same database in both its url and its docker_url, so the
# derived dataset name is this regardless of BD_DOCKER. A scratch manifest declares it so
# the only defect under test is the scope, never a dataset mismatch.
SCRATCH_DATASET = "bez_durakov_test"


def _scratch_knowledge_folder(directory: Path, scope: str | None) -> Path:
    """A knowledge folder whose manifest carries the given scope, or omits the key."""
    folder = directory / "knowledge"
    folder.mkdir()
    manifest = f'dataset = "{SCRATCH_DATASET}"\npersona = "Some persona text."\n'
    if scope is not None:
        manifest += f'scope = "{scope}"\n'
    _ = (folder / "manifest.toml").write_text(manifest, encoding="utf-8")
    _ = (folder / "rules.md").write_text(
        "# Rules\n\nSome summary paragraph text.\n", encoding="utf-8"
    )
    return folder


def _scratch_config(directory: Path, knowledge_dir: Path, webreport_extra: str = "") -> Path:
    """A complete scratch config aiming the preflight at a scratch knowledge folder."""
    config_path = directory / "config.toml"
    body = SCRATCH_BASE_CONFIG.read_text(encoding="utf-8").replace(
        "[dataset]\n", f'[dataset]\nknowledge_dir = "{knowledge_dir}"\n', 1
    )
    if webreport_extra:
        body = body.replace("[webreport]\n", f"[webreport]\n{webreport_extra}\n", 1)
    _ = config_path.write_text(body, encoding="utf-8")
    return config_path


def _preflight(config_file: str | Path) -> subprocess.CompletedProcess[str]:
    """Run the operator's own preflight command in its own interpreter.

    A child process is the only way to observe a scratch config: bd_shared.config reads
    its file at import time, and knowledge_cli reads the constants at call time.
    """
    return subprocess.run(
        [sys.executable, "-m", "agent.knowledge_cli"],
        cwd=str(BACKEND_DIR),
        env={**os.environ, "BD_CONFIG_FILE": str(config_file)},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=60,
    )


class KnowledgeCliTests(unittest.TestCase):
    @staticmethod
    def _run(knowledge_dir: Path | None) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch.object(knowledge_cli, "KNOWLEDGE_DIR", knowledge_dir),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            exit_code = knowledge_cli.main()
        return exit_code, stdout.getvalue(), stderr.getvalue()

    def test_unset_knowledge_dir_exits_zero(self):
        exit_code, stdout, stderr = self._run(None)

        self.assertEqual(exit_code, 0)
        self.assertIn("Knowledge folder is not configured", stdout)
        self.assertEqual(stderr, "")

    def test_missing_knowledge_dir_exits_zero(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing_path = Path(temp_dir) / "does-not-exist"
            exit_code, stdout, stderr = self._run(missing_path)

        self.assertEqual(exit_code, 0)
        self.assertIn(f"Knowledge folder not found at {missing_path}", stdout)
        self.assertEqual(stderr, "")

    def test_invalid_knowledge_dir_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            invalid_path = Path(temp_dir)
            _ = (invalid_path / "manifest.toml").write_text("[invalid", encoding="utf-8")
            exit_code, stdout, stderr = self._run(invalid_path)

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("Knowledge folder is invalid", stderr)
        self.assertIn("manifest.toml", stderr)

    def test_invalid_configured_byte_budget_exits_nonzero(self):
        shipped_path = Path("/bd_shared/knowledge/bez_durakov")
        with (
            patch("bd_shared.config.KNOWLEDGE_MAX_BYTES_PER_TURN", 0),
            patch.object(knowledge_cli, "KNOWLEDGE_MAX_BYTES_PER_TURN", 0),
        ):
            exit_code, stdout, stderr = self._run(shipped_path)

        self.assertNotEqual(exit_code, 0)
        self.assertEqual(stdout, "")
        self.assertIn("knowledge_max_bytes_per_turn", stderr)

    def test_shipped_knowledge_dir_exits_zero(self):
        shipped_path = Path("/bd_shared/knowledge/bez_durakov")
        exit_code, stdout, stderr = self._run(shipped_path)

        self.assertEqual(exit_code, 0)
        self.assertIn("Knowledge folder is valid", stdout)
        self.assertEqual(stderr, "")

    def test_manifest_without_scope_exits_one_naming_the_manifest_and_the_key(self):
        """Given a manifest with no scope, When the preflight runs, Then it exits 1 naming the manifest and scope."""
        with tempfile.TemporaryDirectory(dir="/tmp") as temp_dir:
            directory = Path(temp_dir)
            folder = _scratch_knowledge_folder(directory, scope=None)
            result = _preflight(_scratch_config(directory, folder))
            manifest_path = folder / "manifest.toml"

            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertEqual(result.stdout, "")
            self.assertIn(str(manifest_path), result.stderr)
            self.assertIn("scope", result.stderr)

    def test_manifest_with_an_empty_scope_exits_one_naming_the_manifest_and_the_key(self):
        """Given an empty scope, When the preflight runs, Then it exits 1 naming the manifest and scope."""
        with tempfile.TemporaryDirectory(dir="/tmp") as temp_dir:
            directory = Path(temp_dir)
            folder = _scratch_knowledge_folder(directory, scope="")
            result = _preflight(_scratch_config(directory, folder))
            manifest_path = folder / "manifest.toml"

            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertEqual(result.stdout, "")
            self.assertIn(str(manifest_path), result.stderr)
            self.assertIn("scope", result.stderr)

    def test_over_long_scope_exits_one_naming_the_manifest_and_the_limit(self):
        """Given a scope past the configured limit, When the preflight runs, Then it exits 1 naming the manifest and the limit."""
        limit = 40
        with tempfile.TemporaryDirectory(dir="/tmp") as temp_dir:
            directory = Path(temp_dir)
            folder = _scratch_knowledge_folder(directory, scope="S" * (limit + 1))
            config_path = _scratch_config(
                directory, folder, f"knowledge_max_scope_chars = {limit}"
            )
            result = _preflight(config_path)
            manifest_path = folder / "manifest.toml"

            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertEqual(result.stdout, "")
            self.assertIn(str(manifest_path), result.stderr)
            self.assertIn("max_scope_chars", result.stderr)
            self.assertIn(f"scope is {limit + 1} characters, limit is {limit}", result.stderr)

    def test_invalid_configured_scope_limit_exits_one_naming_the_key(self):
        """Given a zero scope limit, When the preflight runs, Then it exits 1 naming knowledge_max_scope_chars."""
        with tempfile.TemporaryDirectory(dir="/tmp") as temp_dir:
            directory = Path(temp_dir)
            folder = _scratch_knowledge_folder(directory, scope="Some scope text.")
            config_path = _scratch_config(directory, folder, "knowledge_max_scope_chars = 0")
            result = _preflight(config_path)

            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertEqual(result.stdout, "")
            self.assertIn("knowledge_max_scope_chars", result.stderr)

    def test_both_shipped_knowledge_folders_pass_the_preflight_under_default_limits(self):
        """Given the two folders shipped in this repository, When each preflight runs, Then both exit 0."""
        for config_file in ("config.toml", "test_config_sqlite.toml"):
            with self.subTest(config_file=config_file):
                result = _preflight(config_file)

                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn("Knowledge folder is valid", result.stdout)
                self.assertEqual(result.stderr, "")


if __name__ == "__main__":
    _ = unittest.main()
