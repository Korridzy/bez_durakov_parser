"""ASGI middleware for request IDs and structured HTTP request logs."""

import re
import sys
import time
import uuid
from collections.abc import Iterable

import structlog
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"
REQUEST_ID_PATTERN = re.compile(rb"[A-Za-z0-9._-]{1,128}")


def new_request_id() -> str:
    return uuid.uuid4().hex


def incoming_request_id(headers: Iterable[tuple[bytes, bytes]]) -> str | None:
    values = [
        value for name, value in headers if name.lower() == b"x-request-id"
    ]
    if len(values) != 1 or REQUEST_ID_PATTERN.fullmatch(values[0]) is None:
        return None
    return values[0].decode("ascii")


class RequestCorrelationMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self, scope: Scope, receive: Receive, send: Send
    ) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = incoming_request_id(scope.get("headers", []))
        if request_id is None:
            request_id = new_request_id()

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        started = time.perf_counter()
        status: int | None = None
        error_info = None

        async def send_wrapper(message: Message) -> None:
            nonlocal status
            if message["type"] != "http.response.start":
                await send(message)
                return

            response_start = dict(message)
            headers = [
                (name, value)
                for name, value in message.get("headers", [])
                if name.lower() != b"x-request-id"
            ]
            headers.append((b"x-request-id", request_id.encode("ascii")))
            response_start["headers"] = headers
            status = message["status"]
            await send(response_start)

        try:
            await self.app(scope, receive, send_wrapper)
        except BaseException:
            status = 500
            error_info = sys.exc_info()
            raise
        finally:
            try:
                fields = {
                    "method": scope["method"],
                    "route": getattr(scope.get("route"), "path", None)
                    or scope["path"],
                    "status": status,
                    "duration_ms": round(
                        (time.perf_counter() - started) * 1000, 3
                    ),
                }
                logger = structlog.get_logger("webreport.backend.request")
                if error_info is None:
                    logger.info("http_request", **fields)
                else:
                    logger.error("http_request", exc_info=error_info, **fields)
            finally:
                structlog.contextvars.clear_contextvars()
