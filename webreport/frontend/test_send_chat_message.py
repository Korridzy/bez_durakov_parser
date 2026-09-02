from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

import requests

import main


class _InvalidJsonResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        raise requests.exceptions.JSONDecodeError("invalid", "", 0)


class _ListJsonResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> object:
        return ["unexpected"]


class _UnavailableResponse:
    def raise_for_status(self) -> None:
        raise requests.HTTPError(response=_ErrorPayload())


class _ErrorPayload:
    def json(self) -> dict[str, str]:
        return {"detail": "Agent system not available"}


class SendChatMessageTest(unittest.TestCase):
    def test_returns_user_friendly_error_when_backend_returns_invalid_json(self) -> None:
        with (
            patch.object(main, "st", SimpleNamespace(session_state=SimpleNamespace(session_id="test"))),
            patch("main.requests.post", return_value=_InvalidJsonResponse()),
        ):
            result = main.send_chat_message("покажи все игры")

        self.assertEqual(
            {
                "success": False,
                "error": "Сервер вернул некорректный ответ.",
                "message": "Сервер вернул некорректный ответ.",
            },
            result,
        )

    def test_returns_user_friendly_error_when_backend_returns_json_list(self) -> None:
        with (
            patch.object(main, "st", SimpleNamespace(session_state=SimpleNamespace(session_id="test"))),
            patch("main.requests.post", return_value=_ListJsonResponse()),
        ):
            result = main.send_chat_message("покажи все игры")

        self.assertEqual(
            {
                "success": False,
                "error": "Сервер вернул некорректный ответ.",
                "message": "Сервер вернул некорректный ответ.",
            },
            result,
        )

    def test_preserves_backend_detail_when_chat_request_returns_http_error(self) -> None:
        with (
            patch.object(main, "st", SimpleNamespace(session_state=SimpleNamespace(session_id="test"))),
            patch("main.requests.post", return_value=_UnavailableResponse()) as post,
        ):
            result = main.send_chat_message("покажи все игры")

        post.assert_called_once_with(
            f"{main.API_BASE_URL}/api/chat",
            json={"message": "покажи все игры", "session_id": "test"},
            timeout=150,
        )
        self.assertEqual(
            {
                "success": False,
                "error": "Agent system not available",
                "message": "Agent system not available",
            },
            result,
        )


if __name__ == "__main__":
    _ = unittest.main()
