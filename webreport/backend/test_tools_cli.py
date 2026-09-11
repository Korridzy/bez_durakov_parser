"""Regression tests for the tool-module preflight CLI exit statuses.

Shaped like test_knowledge_cli.py: main() is called in process and its two streams are
captured, so the single-line contract is asserted rather than described.
"""

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from agent import tools_cli

VALID_MODULE = '''
"""A stand-in operator module."""


class Service:
    """A stand-in service."""

    def __init__(self, engine):
        self.engine = engine

    def list_rows(self) -> dict:
        """Return every row."""
        return {}

    def row_by_name(self, name: str) -> dict:
        """Return one row by name."""
        return {"name": name}


def build_service(engine):
    """Build the service around the injected engine."""
    return Service(engine)
'''

UNDOCUMENTED_MODULE = '''
"""A module whose service has an undocumented method."""


class Service:
    """A stand-in service."""

    def __init__(self, engine):
        self.engine = engine

    def silent(self) -> dict:
        return {}


def build_service(engine):
    """Build the service."""
    return Service(engine)
'''

NO_FACTORY_MODULE = '''
"""A module that forgot its factory."""


def make_service(engine):
    """Not the fixed factory name."""
    return object()
'''


class ToolsCliTests(unittest.TestCase):
    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = Path(self._directory.name)
        sys.path.insert(0, str(self.root))
        self.addCleanup(sys.path.remove, str(self.root))
        self._written: list[str] = []
        self.addCleanup(self._forget_written)

    def _forget_written(self):
        for name in self._written:
            sys.modules.pop(name, None)

    def _write(self, name: str, body: str) -> str:
        (self.root / f"{name}.py").write_text(body)
        self._written.append(name)
        return name

    @staticmethod
    def _run(
        module: str,
        url: str = "sqlite:////tmp/bd-preflight-absent.db",
        config_error: str | None = None,
    ) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            patch.object(tools_cli, "DATASET_TOOLS_MODULE", module),
            patch.object(tools_cli, "DATABASE_URL", url),
            patch.object(tools_cli, "DATASET_CONFIG_ERROR", config_error),
            redirect_stdout(stdout),
            redirect_stderr(stderr),
        ):
            exit_code = tools_cli.main()
        return exit_code, stdout.getvalue(), stderr.getvalue()

    def test_a_valid_module_exits_zero_with_one_summary_line(self):
        """Given a valid module, When the preflight runs, Then one stdout line reports its tools."""
        name = self._write("preflight_valid", VALID_MODULE)

        exit_code, stdout, stderr = self._run(name)

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertEqual(stdout.splitlines(), [
            f"Tool module is valid: {name} (2 tools: list_rows, row_by_name)"
        ])

    def test_the_default_module_is_valid_with_the_database_down(self):
        """Given the shipped module and an unreachable URL, When the preflight runs, Then it passes."""
        exit_code, stdout, stderr = self._run(
            "bd_shared.tools.bez_durakov",
            url="mysql+pymysql://nobody:nobody@127.0.0.1:1/absent",
        )

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr, "")
        self.assertIn("8 tools:", stdout)

    def test_an_unimportable_module_exits_one_with_one_error_line(self):
        """Given a module that does not import, When the preflight runs, Then one stderr line names it."""
        exit_code, stdout, stderr = self._run("definitely.not.a.module")

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout, "")
        self.assertEqual(len(stderr.splitlines()), 1)
        self.assertIn("definitely.not.a.module", stderr)
        self.assertIn("could not be imported", stderr)

    def test_a_missing_factory_exits_one_naming_the_module(self):
        """Given no build_service, When the preflight runs, Then the module and factory are named."""
        name = self._write("preflight_no_factory", NO_FACTORY_MODULE)

        exit_code, _, stderr = self._run(name)

        self.assertEqual(exit_code, 1)
        self.assertIn(f"Tool module is invalid: {name} has no build_service factory", stderr)

    def test_a_method_without_a_docstring_exits_one_naming_the_method(self):
        """Given an undocumented method, When the preflight runs, Then the method is named."""
        name = self._write("preflight_undocumented", UNDOCUMENTED_MODULE)

        exit_code, _, stderr = self._run(name)

        self.assertEqual(exit_code, 1)
        self.assertEqual(
            stderr.strip(), f"Tool module is invalid: {name}.silent has no docstring"
        )

    def test_a_dataset_config_error_is_reported_before_any_import(self):
        """Given a [dataset] misconfiguration, When the preflight runs, Then it reports that first."""
        exit_code, stdout, stderr = self._run(
            "definitely.not.a.module", config_error="dataset.tools_module is not configured"
        )

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout, "")
        self.assertEqual(stderr.strip(), "dataset.tools_module is not configured")

    def test_a_malformed_url_exits_one_with_one_error_line(self):
        """Given an unusable URL, When the preflight runs, Then one stderr line explains it."""
        name = self._write("preflight_bad_url", VALID_MODULE)

        exit_code, stdout, stderr = self._run(name, url="sqlite://")

        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout, "")
        self.assertEqual(len(stderr.splitlines()), 1)
        self.assertIn("Database URL is invalid", stderr)


if __name__ == "__main__":
    unittest.main()
