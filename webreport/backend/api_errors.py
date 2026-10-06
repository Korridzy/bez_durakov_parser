"""Error envelope for the chat and report routes (issue #112)."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class ApiError(Exception):
    """Raised only by the new chat and report routes; legacy routes keep HTTPException."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        body_extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.body_extra = body_extra or {}

    def body(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message}, **self.body_extra}


def register_api_error_handler(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _handle_api_error(_request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.body())
