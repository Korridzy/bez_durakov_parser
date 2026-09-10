"""Regression tests for the knowledge preflight CLI exit statuses."""

import io
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from agent import knowledge_cli


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

    def test_shipped_knowledge_dir_exits_zero(self):
        shipped_path = Path("/bd_shared/knowledge/bez_durakov")
        exit_code, stdout, stderr = self._run(shipped_path)

        self.assertEqual(exit_code, 0)
        self.assertIn("Knowledge folder is valid", stdout)
        self.assertEqual(stderr, "")


if __name__ == "__main__":
    _ = unittest.main()
