"""Tests for structured-log redaction without importing logging infrastructure."""

import copy
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bd_shared.log_redaction import MASK, MAX_DEPTH, OMITTED, redact_sensitive  # noqa: E402


class NoRepr:
    """Sentinel that fails the test if redaction tries to render arbitrary objects."""

    def __repr__(self):
        raise AssertionError("redaction must not call repr on arbitrary objects")


class TestLogRedaction(unittest.TestCase):
    def redact(self, event_dict):
        return redact_sensitive(None, "info", event_dict)

    def test_masks_sensitive_keys_in_any_casing_or_separator_style(self):
        result = self.redact(
            {
                "Authorization": "Bearer abc",
                "X-API-Key": "one",
                "api_key": "two",
                "set-cookie": "session=three",
            }
        )

        self.assertEqual(
            result,
            {
                "Authorization": MASK,
                "X-API-Key": MASK,
                "api_key": MASK,
                "set-cookie": MASK,
            },
        )

    def test_masks_every_configured_secret_name(self):
        sensitive_names = (
            "authorization",
            "proxy_authorization",
            "cookie",
            "set-cookie",
            "api_key",
            "x-api-key",
            "token",
            "access_token",
            "refresh-token",
            "secret",
            "client_secret",
            "password",
            "passwd",
            "openai_api_key",
            "openrouter-api-key",
            "opencode api key",
            "langfuse_secret_key",
            "LANGFUSE-PUBLIC-KEY",
            "langfusePublicKey",
            "database_url",
            "db-url",
        )
        result = self.redact({name: f"secret-{index}" for index, name in enumerate(sensitive_names)})

        self.assertEqual(result, {name: MASK for name in sensitive_names})

    def test_drops_payload_keys_at_depth_three_inside_lists(self):
        result = self.redact(
            {
                "outer": [
                    {
                        "middle": [
                            {
                                "prompt": "secret text",
                                "reasoning_content": "private chain",
                                "safe": "kept",
                            }
                        ]
                    }
                ]
            }
        )

        innermost = result["outer"][0]["middle"][0]
        self.assertEqual(
            innermost,
            {"prompt": OMITTED, "reasoning_content": OMITTED, "safe": "kept"},
        )

    def test_drops_every_configured_payload_name(self):
        payload_names = (
            "message",
            "messages",
            "prompt",
            "prompts",
            "response",
            "content",
            "reasoning",
            "reasoning_content",
            "rows",
            "result",
            "results",
            "query_result",
            "data",
        )
        result = self.redact({"nested": {name: object() for name in payload_names}})

        self.assertEqual(result, {"nested": {name: OMITTED for name in payload_names}})

    def test_scrubs_credentials_from_a_whole_url(self):
        result = self.redact(
            {"url": "mysql+pymysql://durak:devpass@mysql:3306/bez_durakov"}
        )

        self.assertEqual(
            result,
            {"url": "mysql+pymysql://[REDACTED]@mysql:3306/bez_durakov"},
        )

    def test_scrubs_credentials_from_an_embedded_url(self):
        result = self.redact({"error": "connect failed: postgresql://u:p@h/db"})

        self.assertEqual(
            result, {"error": "connect failed: postgresql://[REDACTED]@h/db"}
        )

    def test_scrubs_sensitive_query_params_and_keeps_other_params(self):
        result = self.redact({"url": "https://x/?api_key=abc&page=2"})

        self.assertEqual(result, {"url": "https://x/?api_key=[REDACTED]&page=2"})

    def test_scrubs_every_duplicate_sensitive_query_param(self):
        result = self.redact(
            {"url": "https://x/path?token=first&token=second&sig=third"}
        )

        self.assertEqual(
            result,
            {
                "url": (
                    "https://x/path?token=[REDACTED]&token=[REDACTED]"
                    "&sig=[REDACTED]"
                )
            },
        )

    def test_masks_a_cycle_on_the_active_path(self):
        cyclic = []
        cyclic.append(cyclic)

        result = self.redact({"nested": cyclic})

        self.assertEqual(result, {"nested": [MASK]})

    def test_masks_a_subtree_beyond_the_depth_limit(self):
        deep = {"leaf": "bottom"}
        for _ in range(MAX_DEPTH + 1):
            deep = {"child": deep}

        result = self.redact({"nested": deep})

        cursor = result["nested"]
        for _ in range(MAX_DEPTH - 1):
            cursor = cursor["child"]
        self.assertEqual(cursor, MASK)

    def test_returns_tuples_as_lists(self):
        result = self.redact({"items": ("safe", {"password": "hidden"})})

        self.assertEqual(result, {"items": ["safe", {"password": MASK}]})
        self.assertIsInstance(result["items"], list)

    def test_does_not_mutate_the_input(self):
        event_dict = {
            "headers": {"Authorization": "Bearer abc"},
            "items": ("https://x/?token=secret", ["unchanged"]),
            "prompt": {"nested": "must not be traversed"},
        }
        original = copy.deepcopy(event_dict)

        result = self.redact(event_dict)

        self.assertEqual(event_dict, original)
        self.assertIsNot(result, event_dict)
        self.assertIsNot(result["headers"], event_dict["headers"])

    def test_event_key_survives_and_its_string_value_is_scrubbed(self):
        result = self.redact(
            {"event": "connect postgresql://u:p@h/db?token=abc", "message": "private"}
        )

        self.assertEqual(
            result,
            {
                "event": "connect postgresql://[REDACTED]@h/db?token=[REDACTED]",
                "message": OMITTED,
            },
        )

    def test_non_string_scalars_pass_through_by_identity(self):
        integer = int("123456789012345678901234567890")
        timestamp = datetime(2025, 1, 2, 3, 4, tzinfo=timezone.utc)
        path = Path("/tmp/report.json")
        opaque = NoRepr()

        result = self.redact(
            {"integer": integer, "timestamp": timestamp, "path": path, "opaque": opaque}
        )

        self.assertIs(result["integer"], integer)
        self.assertIs(result["timestamp"], timestamp)
        self.assertIs(result["path"], path)
        self.assertIs(result["opaque"], opaque)

    def test_exception_frames_are_recursed_and_scrubbed(self):
        result = self.redact(
            {
                "exception": [
                    {
                        "exc_type": "RuntimeError",
                        "exc_value": "connect failed: postgresql://u:p@h/db",
                        "locals": {"password": "private", "status": "failed"},
                    }
                ]
            }
        )

        self.assertEqual(
            result,
            {
                "exception": [
                    {
                        "exc_type": "RuntimeError",
                        "exc_value": "connect failed: postgresql://[REDACTED]@h/db",
                        "locals": {"password": MASK, "status": "failed"},
                    }
                ]
            },
        )

    def test_non_string_keys_and_non_utf8ish_text_are_handled(self):
        text = "bad-surrogate-\udcff https://x/?signature=value"

        result = self.redact({17: {"api_key": "hidden", "text": text}})

        self.assertEqual(
            result,
            {17: {"api_key": MASK, "text": "bad-surrogate-\udcff https://x/?signature=[REDACTED]"}},
        )

    def test_shared_values_are_not_mistaken_for_cycles(self):
        shared = {"url": "https://x/?key=value"}

        result = self.redact({"left": shared, "right": shared})

        expected = {"url": "https://x/?key=[REDACTED]"}
        self.assertEqual(result, {"left": expected, "right": expected})
        self.assertIsNot(result["left"], result["right"])

    def test_rejects_non_dict_event_values(self):
        with self.assertRaisesRegex(TypeError, "event_dict must be a dict"):
            self.redact(None)
        with self.assertRaisesRegex(TypeError, "event_dict must be a dict"):
            self.redact([{"event": "not a dict"}])


if __name__ == "__main__":
    unittest.main(verbosity=2)
