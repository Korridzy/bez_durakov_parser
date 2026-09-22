"""Per-call request and session correlation for model invocations."""

import secrets
import time
from collections.abc import Mapping, Sequence
from typing import Any, Protocol, cast, final

import structlog

from bd_shared.config import ENVIRONMENT

from .graph import AgentMessageView, BoundModel, MessageView, ModelClient, NamedTool

CORRELATION_KEYS = ("request_id", "trace_id", "session_id", "user_id")

logger = structlog.get_logger(__name__)


class _KwargsBoundModel(Protocol):
    async def ainvoke(
        self,
        messages: Sequence[MessageView],
        **kwargs: Any,
    ) -> AgentMessageView: ...


def correlation_kwargs(
    context: Mapping[str, object],
    *,
    role: str,
) -> dict[str, object]:
    """Build LiteLLM proxy metadata and headers from bound context values."""
    if not any(key in context for key in CORRELATION_KEYS):
        return {}

    metadata = {
        key: context[key]
        for key in ("request_id", "session_id")
        if key in context
    }
    if "request_id" in context:
        metadata["trace_metadata"] = {"request_id": context["request_id"]}
    metadata["generation_name"] = role
    metadata["tags"] = ["webreport", ENVIRONMENT]
    if "user_id" in context:
        metadata["trace_user_id"] = context["user_id"]

    headers = {}
    if "request_id" in context:
        headers["X-Request-ID"] = str(context["request_id"])
    if "trace_id" in context:
        headers["traceparent"] = (
            f"00-{context['trace_id']}-{secrets.token_hex(8)}-01"
        )

    kwargs: dict[str, object] = {"extra_body": {"metadata": metadata}}
    if headers:
        kwargs["extra_headers"] = headers
    return kwargs


@final
class _CorrelatedBoundModel:
    def __init__(self, bound: object, *, model: str, role: str) -> None:
        self.bound = cast(_KwargsBoundModel, bound)
        self.model = model
        self.role = role

    async def ainvoke(self, messages: Sequence[MessageView]) -> AgentMessageView:
        kwargs = correlation_kwargs(
            structlog.contextvars.get_contextvars(),
            role=self.role,
        )
        started = time.perf_counter()
        try:
            response = await self.bound.ainvoke(messages, **kwargs)
        except BaseException:
            logger.error(
                "llm_call_failed",
                model=self.model,
                role=self.role,
                duration_ms=round((time.perf_counter() - started) * 1000, 3),
                exc_info=True,
            )
            raise
        logger.info(
            "llm_call",
            model=self.model,
            role=self.role,
            duration_ms=round((time.perf_counter() - started) * 1000, 3),
        )
        return response


@final
class CorrelatedModelClient:
    def __init__(self, client: ModelClient, *, model: str, role: str) -> None:
        self.client = client
        self.model = model
        self.role = role

    def bind_tools(
        self,
        tools: Sequence[NamedTool],
        *,
        parallel_tool_calls: bool,
    ) -> BoundModel:
        return _CorrelatedBoundModel(
            self.client.bind_tools(
                tools,
                parallel_tool_calls=parallel_tool_calls,
            ),
            model=self.model,
            role=self.role,
        )
