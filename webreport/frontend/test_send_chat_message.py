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


if __name__ == "__main__":
    _ = unittest.main()
