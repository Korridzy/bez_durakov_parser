from __future__ import annotations

import io
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import requests

from bd_shared.logging_setup import _reset_for_tests, configure_logging

os.environ.setdefault("CHAT_REQUEST_TIMEOUT_SECONDS", "5")

import main  # noqa: E402


class _Response:
    def __init__(self, payload: object = None, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return self.payload


class FrontendLoggingTest(unittest.TestCase):
    log_stream: io.StringIO = io.StringIO()

    def setUp(self) -> None:
        _reset_for_tests()
        self.log_stream = io.StringIO()
        configure_logging("webreport-frontend", log_format="json", stream=self.log_stream)

    def tearDown(self) -> None:
        _reset_for_tests()

    def records(self) -> list[dict[str, object]]:
        return [json.loads(line) for line in self.log_stream.getvalue().splitlines()]

    def assert_request_id(self, request_id: object) -> None:
        if not isinstance(request_id, str):
            self.fail(f"request id is not a string: {request_id!r}")
        self.assertRegex(request_id, r"^[0-9a-f]{32}$")

    def test_send_chat_message_logs_correlated_success_without_chat_content(self) -> None:
        with (
            patch.object(main.st, "session_state", SimpleNamespace(session_id="sess-1")),
            patch("main.requests.post", return_value=_Response({"success": True})) as post,
        ):
            result = main.send_chat_message("hi")

        self.assertEqual({"success": True}, result)
        request_id = post.call_args.kwargs["headers"]["X-Request-ID"]
        self.assert_request_id(request_id)
        post.assert_called_once_with(
            f"{main.API_BASE_URL}/api/chat",
            json={"message": "hi", "session_id": "sess-1"},
            timeout=main.CHAT_REQUEST_TIMEOUT_SECONDS,
            headers={"X-Request-ID": request_id},
        )

        records = self.records()
        self.assertEqual(1, len(records))
        record = records[0]
        self.assertEqual("backend_request", record["event"])
        self.assertEqual("POST", record["method"])
        self.assertEqual("/api/chat", record["path"])
        self.assertEqual(200, record["status"])
        self.assertIsInstance(record["duration_ms"], (int, float))
        self.assertEqual(request_id, record["request_id"])
        self.assertEqual("sess-1", record["session_id"])
        self.assertNotIn("message", record)
        self.assertNotIn("content", record)
        self.assertNotIn("hi", self.log_stream.getvalue())

    def test_connection_error_returns_existing_failure_and_logs_exception(self) -> None:
        with (
            patch.object(main.st, "session_state", SimpleNamespace(session_id="sess-1")),
            patch("main.requests.post", side_effect=requests.ConnectionError("offline")) as post,
        ):
            result = main.send_chat_message("hi")

        self.assertEqual(
            {
                "success": False,
                "error": "offline",
                "message": "Не удалось связаться с сервером.",
            },
            result,
        )
        request_id = post.call_args.kwargs["headers"]["X-Request-ID"]
        self.assert_request_id(request_id)
        records = self.records()
        self.assertEqual(1, len(records))
        record = records[0]
        self.assertEqual("backend_request_failed", record["event"])
        self.assertEqual("warning", record["level"])
        self.assertEqual(request_id, record["request_id"])
        self.assertEqual("sess-1", record["session_id"])
        self.assertIn("exception", record)
        self.assertNotIn("status", record)
        self.assertNotIn("hi", self.log_stream.getvalue())

    def test_clear_conversation_logs_correlated_request(self) -> None:
        with (
            patch.object(main.st, "session_state", SimpleNamespace(session_id="sess-1")),
            patch("main.requests.post", return_value=_Response()) as post,
        ):
            main.clear_conversation()

        request_id = post.call_args.kwargs["headers"]["X-Request-ID"]
        self.assert_request_id(request_id)
        post.assert_called_once_with(
            f"{main.API_BASE_URL}/api/clear/sess-1",
            timeout=10,
            headers={"X-Request-ID": request_id},
        )
        records = self.records()
        self.assertEqual(1, len(records))
        self.assertEqual("backend_request", records[0]["event"])
        self.assertEqual("/api/clear/sess-1", records[0]["path"])
        self.assertEqual(request_id, records[0]["request_id"])

    def test_check_api_health_logs_correlated_request(self) -> None:
        with (
            patch.object(main.st, "session_state", SimpleNamespace(session_id="sess-1")),
            patch("main.requests.get", return_value=_Response()) as get,
        ):
            result = main.check_api_health()

        self.assertTrue(result)
        request_id = get.call_args.kwargs["headers"]["X-Request-ID"]
        self.assert_request_id(request_id)
        get.assert_called_once_with(
            f"{main.API_BASE_URL}/health",
            timeout=2,
            headers={"X-Request-ID": request_id},
        )
        records = self.records()
        self.assertEqual(1, len(records))
        self.assertEqual("backend_request", records[0]["event"])
        self.assertEqual("GET", records[0]["method"])
        self.assertEqual("/health", records[0]["path"])
        self.assertEqual(200, records[0]["status"])
        self.assertEqual(request_id, records[0]["request_id"])

    def test_successive_calls_use_different_request_ids(self) -> None:
        with (
            patch.object(main.st, "session_state", SimpleNamespace(session_id="sess-1")),
            patch("main.requests.post", side_effect=[_Response({"success": True}), _Response({"success": True})]) as post,
        ):
            main.send_chat_message("hi")
            main.send_chat_message("hi")

        request_ids = [call.kwargs["headers"]["X-Request-ID"] for call in post.call_args_list]
        self.assertEqual(2, len(request_ids))
        self.assert_request_id(request_ids[0])
        self.assert_request_id(request_ids[1])
        self.assertNotEqual(request_ids[0], request_ids[1])
        self.assertEqual(request_ids, [record["request_id"] for record in self.records()])
        self.assertNotIn("hi", self.log_stream.getvalue())

    def test_backend_call_merges_request_id_with_existing_headers(self) -> None:
        with (
            patch.object(main.st, "session_state", SimpleNamespace(session_id="sess-1")),
            patch("main.requests.get", return_value=_Response()) as get,
        ):
            main._backend_call(
                main.requests.get,
                "GET",
                "/health",
                headers={"Accept": "application/json"},
            )

        request_id = get.call_args.kwargs["headers"]["X-Request-ID"]
        self.assert_request_id(request_id)
        self.assertEqual(
            {"Accept": "application/json", "X-Request-ID": request_id},
            get.call_args.kwargs["headers"],
        )


if __name__ == "__main__":
    _ = unittest.main()
