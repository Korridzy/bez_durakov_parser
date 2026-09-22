"""Tests for the shared stdlib and structlog logging configuration."""

import datetime
import inspect
import io
import json
import logging
import os
import subprocess
import sys
import tempfile
import unittest
import uuid
from decimal import Decimal
from enum import Enum
from pathlib import Path
from unittest import mock

import structlog

PROJECT_ROOT = Path(__file__).resolve().parent.parent

sys.path.insert(0, str(PROJECT_ROOT))

from bd_shared import logging_setup  # noqa: E402


class SampleStatus(Enum):
    READY = "ready"


class OpaqueValue:
    pass


class TestLoggingSetup(unittest.TestCase):
    environment_names = (
        logging_setup.ENV_LEVEL,
        logging_setup.ENV_FORMAT,
        logging_setup.ENV_ENVIRONMENT,
        logging_setup.ENV_VERSION,
    )
    original_environment: dict[str, str | None] = {}

    def setUp(self):
        logging_setup._reset_for_tests()
        self.original_environment = {
            name: os.environ.pop(name, None) for name in self.environment_names
        }

    def tearDown(self):
        logging_setup._reset_for_tests()
        for name, value in self.original_environment.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    def configure_json(self, **kwargs):
        stream = io.StringIO()
        logging_setup.configure_logging(
            "svc", log_format="json", stream=stream, **kwargs
        )
        return stream

    @staticmethod
    def parsed_lines(stream):
        return [json.loads(line) for line in stream.getvalue().splitlines()]

    def test_importing_database_does_not_configure_root_logging(self):
        environment = {**os.environ, "BD_CONFIG_FILE": "test_config.toml"}
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import bd_shared.db; import logging; "
                "print(len(logging.root.handlers), logging.root.level)",
            ],
            cwd=PROJECT_ROOT,
            env=environment,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "0 30")

    def test_parse_data_empty_directory_exits_cleanly(self):
        environment = {**os.environ, "BD_CONFIG_FILE": "test_config.toml"}
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run(
                [sys.executable, "parse_data.py", directory, "--no-save"],
                cwd=PROJECT_ROOT,
                env=environment,
                capture_output=True,
                text=True,
            )

        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("No XLSM files found", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_alembic_offline_upgrade_uses_shared_logging(self):
        environment = {**os.environ, "BD_CONFIG_FILE": "test_config.toml"}
        result = subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", "head", "--sql"],
            cwd=PROJECT_ROOT,
            env=environment,
            capture_output=True,
            text=True,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("Traceback", result.stdout + result.stderr)
        self.assertNotIn("fileConfig", result.stdout + result.stderr)

    def test_public_constants_and_configure_signature_are_exact(self):
        self.assertEqual(logging_setup.ENV_LEVEL, "BD_LOG_LEVEL")
        self.assertEqual(logging_setup.ENV_FORMAT, "BD_LOG_FORMAT")
        self.assertEqual(logging_setup.ENV_ENVIRONMENT, "BD_ENVIRONMENT")
        self.assertEqual(logging_setup.ENV_VERSION, "BD_APP_VERSION")
        self.assertEqual(logging_setup.DEFAULT_LEVEL, "INFO")
        self.assertEqual(logging_setup.DEFAULT_FORMAT, "console")
        self.assertEqual(logging_setup.DEFAULT_ENVIRONMENT, "development")
        self.assertEqual(logging_setup.DEFAULT_VERSION, "unknown")
        self.assertEqual(logging_setup.LOG_FORMATS, ("json", "console"))
        self.assertEqual(
            logging_setup.THIRD_PARTY_LEVELS,
            {
                "LiteLLM": "WARNING",
                "LiteLLM Proxy": "WARNING",
                "LiteLLM Router": "WARNING",
                "httpx": "WARNING",
                "httpcore": "WARNING",
                "sqlalchemy.engine": "WARNING",
                "uvicorn.access": "WARNING",
                "apscheduler": "INFO",
            },
        )
        signature = inspect.signature(logging_setup.configure_logging)
        self.assertEqual(
            list(signature.parameters),
            [
                "service_name",
                "level",
                "log_format",
                "environment",
                "version",
                "logger_levels",
                "stream",
            ],
        )
        self.assertEqual(signature.parameters["service_name"].default, inspect.Parameter.empty)
        for name in list(signature.parameters)[1:]:
            self.assertEqual(signature.parameters[name].default, None)
            self.assertEqual(
                signature.parameters[name].kind, inspect.Parameter.KEYWORD_ONLY
            )

    def test_json_output_has_all_shared_fields(self):
        stream = self.configure_json(environment="test", version="abc1234")

        logging_setup.get_logger("unit.logger").info("json-event")

        [record] = self.parsed_lines(stream)
        timestamp = record["timestamp"]
        self.assertTrue(timestamp.endswith(("Z", "+00:00")))
        self.assertIsNotNone(datetime.datetime.fromisoformat(timestamp))
        self.assertEqual(record["level"], "info")
        self.assertEqual(record["event"], "json-event")
        self.assertEqual(record["logger"], "unit.logger")
        self.assertEqual(record["service"], "svc")
        self.assertEqual(record["environment"], "test")
        self.assertEqual(record["version"], "abc1234")
        self.assertEqual(record["module"], "test_logging_setup")
        self.assertIsInstance(record["lineno"], int)
        self.assertEqual(record["func_name"], "test_json_output_has_all_shared_fields")

    def test_console_output_is_human_readable(self):
        stream = io.StringIO()
        logging_setup.configure_logging("svc", log_format="console", stream=stream)

        logging_setup.get_logger("unit.logger").info("console-event")

        output = stream.getvalue()
        self.assertIn("console-event", output)
        self.assertIn("svc", output)
        with self.assertRaises(json.JSONDecodeError):
            json.loads(output)

    def test_stdlib_record_includes_extra_and_shared_fields(self):
        stream = self.configure_json(environment="test", version="v1")

        logging.getLogger("sqlalchemy.engine").warning(
            "rows=%d", 3, extra={"table": "games"}
        )

        [record] = self.parsed_lines(stream)
        self.assertEqual(record["event"], "rows=3")
        self.assertEqual(record["logger"], "sqlalchemy.engine")
        self.assertEqual(record["table"], "games")
        self.assertEqual(record["service"], "svc")
        self.assertEqual(record["environment"], "test")
        self.assertEqual(record["version"], "v1")

    def test_structlog_json_exception_is_structured_without_locals(self):
        stream = self.configure_json()
        logger = logging_setup.get_logger("unit.exception")

        secret_local = "secret-local-value-9137"
        try:
            raise ValueError("bad value")
        except ValueError:
            logger.exception("boom")

        line = stream.getvalue().strip()
        record = json.loads(line)
        self.assertEqual(record["event"], "boom")
        self.assertIsInstance(record["exception"], list)
        exception = record["exception"][0]
        self.assertEqual(exception["exc_type"], "ValueError")
        self.assertEqual(exception["exc_value"], "bad value")
        self.assertTrue(exception["frames"])
        self.assertTrue(all("locals" not in frame for frame in exception["frames"]))
        self.assertNotIn(secret_local, line)

    def test_structlog_console_exception_is_plain_without_locals(self):
        stream = io.StringIO()
        logging_setup.configure_logging("svc", log_format="console", stream=stream)
        logger = logging_setup.get_logger("unit.exception")

        secret_local = "secret-local-value-2846"
        try:
            raise ValueError("bad value")
        except ValueError:
            logger.exception("boom")

        output = stream.getvalue()
        self.assertIn("boom", output)
        self.assertIn("Traceback", output)
        self.assertIn("ValueError", output)
        self.assertNotIn(secret_local, output)

    def test_chained_json_exception_keeps_both_types(self):
        stream = self.configure_json()
        logger = logging_setup.get_logger("unit.exception")

        try:
            try:
                raise LookupError("first")
            except LookupError as error:
                raise RuntimeError("second") from error
        except RuntimeError:
            logger.exception("chained")

        [record] = self.parsed_lines(stream)
        exception_types = [item["exc_type"] for item in record["exception"]]
        self.assertIn("LookupError", exception_types)
        self.assertIn("RuntimeError", exception_types)

    def test_stdlib_json_exception_has_structured_shape(self):
        stream = self.configure_json()

        try:
            raise KeyError("missing")
        except KeyError:
            logging.getLogger("x").exception("boom")

        [record] = self.parsed_lines(stream)
        self.assertEqual(record["event"], "boom")
        self.assertEqual(record["logger"], "x")
        self.assertIsInstance(record["exception"], list)
        exception = record["exception"][0]
        self.assertEqual(exception["exc_type"], "KeyError")
        self.assertIn("missing", exception["exc_value"])
        self.assertTrue(exception["frames"])
        self.assertTrue(all("locals" not in frame for frame in exception["frames"]))

    def test_same_service_configuration_is_idempotent(self):
        stream = io.StringIO()
        ignored_stream = io.StringIO()
        logging_setup.configure_logging("svc", log_format="json", stream=stream)
        original_handler = logging.root.handlers[0]

        logging_setup.configure_logging(
            "svc", log_format="console", stream=ignored_stream
        )
        logging_setup.get_logger("unit.logger").info("once")

        records = self.parsed_lines(stream)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["event"], "once")
        self.assertEqual(ignored_stream.getvalue(), "")
        self.assertEqual(len(logging.root.handlers), 1)
        self.assertIs(logging.root.handlers[0], original_handler)

    def test_different_service_reconfiguration_fails_with_both_names(self):
        logging_setup.configure_logging("svc", stream=io.StringIO())

        with self.assertRaisesRegex(RuntimeError, r"svc.*other|other.*svc"):
            logging_setup.configure_logging("other", stream=io.StringIO())

    def test_unknown_level_and_format_raise_clear_value_errors(self):
        with self.assertRaisesRegex(ValueError, "nope"):
            logging_setup.configure_logging("svc", level="nope", stream=io.StringIO())
        with self.assertRaisesRegex(ValueError, "xml"):
            logging_setup.configure_logging(
                "svc", log_format="xml", stream=io.StringIO()
            )

    def test_environment_variables_are_honored(self):
        stream = io.StringIO()
        with mock.patch.dict(
            os.environ,
            {
                "BD_LOG_LEVEL": "DEBUG",
                "BD_LOG_FORMAT": "json",
                "BD_ENVIRONMENT": "production",
                "BD_APP_VERSION": "abc1234",
            },
        ):
            logging_setup.configure_logging("svc", stream=stream)
            logging_setup.get_logger("unit.logger").debug("from-env")

        [record] = self.parsed_lines(stream)
        self.assertEqual(record["level"], "debug")
        self.assertEqual(record["event"], "from-env")
        self.assertEqual(record["environment"], "production")
        self.assertEqual(record["version"], "abc1234")

    def test_explicit_arguments_win_over_environment_variables(self):
        stream = io.StringIO()
        with mock.patch.dict(
            os.environ,
            {
                "BD_LOG_LEVEL": "WARNING",
                "BD_LOG_FORMAT": "console",
                "BD_ENVIRONMENT": "production",
                "BD_APP_VERSION": "env-version",
            },
        ):
            logging_setup.configure_logging(
                "svc",
                level="DEBUG",
                log_format="json",
                environment="staging",
                version="explicit-version",
                stream=stream,
            )
            logging_setup.get_logger("unit.logger").debug("explicit")

        [record] = self.parsed_lines(stream)
        self.assertEqual(record["level"], "debug")
        self.assertEqual(record["event"], "explicit")
        self.assertEqual(record["environment"], "staging")
        self.assertEqual(record["version"], "explicit-version")

    def test_contextvars_merge_into_structlog_and_stdlib_then_clear(self):
        stream = self.configure_json()
        structlog_logger = logging_setup.get_logger("unit.context")
        structlog.contextvars.bind_contextvars(request_id="request-7")

        structlog_logger.info("structured")
        logging.getLogger("stdlib.context").info("foreign")
        structlog.contextvars.clear_contextvars()
        structlog_logger.info("cleared")

        structured, foreign, cleared = self.parsed_lines(stream)
        self.assertEqual(structured["request_id"], "request-7")
        self.assertEqual(foreign["request_id"], "request-7")
        self.assertEqual(structured["event"], "structured")
        self.assertEqual(foreign["event"], "foreign")
        self.assertEqual(cleared["event"], "cleared")
        for key in ("request_id", "session_id", "job_id", "job_name"):
            self.assertNotIn(key, cleared)

    def test_adopt_third_party_logger_removes_handlers_and_propagates(self):
        logger = logging.getLogger("LiteLLM")
        logger.addHandler(logging.StreamHandler(io.StringIO()))
        logger.propagate = False

        logging_setup.adopt_third_party_loggers("LiteLLM")

        self.assertEqual(logger.handlers, [])
        self.assertTrue(logger.propagate)

    def test_logger_level_override_wins_over_third_party_default(self):
        stream = self.configure_json(
            logger_levels={"sqlalchemy.engine": "DEBUG"}
        )

        logging.getLogger("sqlalchemy.engine").debug("sql-debug")

        [record] = self.parsed_lines(stream)
        self.assertEqual(logging.getLogger("sqlalchemy.engine").level, logging.DEBUG)
        self.assertEqual(record["level"], "debug")
        self.assertEqual(record["event"], "sql-debug")

    def test_json_redacts_sensitive_and_payload_fields(self):
        stream = self.configure_json()

        logging_setup.get_logger("unit.redaction").info(
            "redacted", authorization="Bearer x", prompt="p"
        )

        [record] = self.parsed_lines(stream)
        self.assertEqual(record["authorization"], "[REDACTED]")
        self.assertEqual(record["prompt"], "[OMITTED]")

    def test_console_redacts_sensitive_and_payload_fields(self):
        stream = io.StringIO()
        logging_setup.configure_logging("svc", log_format="console", stream=stream)

        logging_setup.get_logger("unit.redaction").info(
            "redacted", authorization="Bearer x", prompt="p"
        )

        output = stream.getvalue()
        self.assertIn("[REDACTED]", output)
        self.assertIn("[OMITTED]", output)
        self.assertNotIn("Bearer x", output)
        self.assertNotIn("prompt='p'", output)

    def test_json_default_serializes_supported_and_opaque_values(self):
        stream = self.configure_json()
        timestamp = datetime.datetime(
            2026, 9, 19, 12, 34, 56, tzinfo=datetime.timezone.utc
        )
        identifier = uuid.UUID("12345678-1234-5678-1234-567812345678")

        logging_setup.get_logger("unit.values").info(
            "values",
            when=timestamp,
            path=Path("/tmp/report.json"),
            identifier=identifier,
            amount=Decimal("12.50"),
            status=SampleStatus.READY,
            opaque=OpaqueValue(),
        )

        [record] = self.parsed_lines(stream)
        self.assertEqual(record["when"], timestamp.isoformat())
        self.assertEqual(record["path"], "/tmp/report.json")
        self.assertEqual(record["identifier"], str(identifier))
        self.assertEqual(record["amount"], "12.50")
        self.assertEqual(record["status"], "ready")
        self.assertEqual(record["opaque"], "<OpaqueValue>")

    def test_json_preserves_unicode_without_ascii_escapes(self):
        stream = self.configure_json()
        text = "Привет, мир"

        logging_setup.get_logger("unit.unicode").info(text)

        line = stream.getvalue().strip()
        record = json.loads(line)
        self.assertEqual(record["event"], text)
        self.assertIn(text, line)
        self.assertNotIn("\\u", line)


if __name__ == "__main__":
    unittest.main(verbosity=2)
