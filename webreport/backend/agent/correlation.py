"""Per-call request and session correlation for model invocations."""

import time
from collections.abc import Mapping, Sequence
from typing import Any, Protocol, cast, final

import structlog

from .graph import AgentMessageView, BoundModel, MessageView, ModelClient, NamedTool

CORRELATION_KEYS = ("request_id", "session_id")

logger = structlog.get_logger(__name__)


class _KwargsBoundModel(Protocol):
    async def ainvoke(
        self,
        messages: Sequence[MessageView],
        **kwargs: Any,
    ) -> AgentMessageView: ...


def correlation_kwargs(context: Mapping[str, object]) -> dict[str, object]:
    """Build LiteLLM proxy metadata and headers from bound context values."""
    metadata = {key: context[key] for key in CORRELATION_KEYS if key in context}
    kwargs: dict[str, object] = {}
    if metadata:
        kwargs["extra_body"] = {"metadata": metadata}
    if "request_id" in context:
        kwargs["extra_headers"] = {"X-Request-ID": str(context["request_id"])}
    return kwargs


@final
class _CorrelatedBoundModel:
    def __init__(self, bound: object, *, model: str) -> None:
        self.bound = cast(_KwargsBoundModel, bound)
        self.model = model

    async def ainvoke(self, messages: Sequence[MessageView]) -> AgentMessageView:
        kwargs = correlation_kwargs(structlog.contextvars.get_contextvars())
        started = time.perf_counter()
        try:
            response = await self.bound.ainvoke(messages, **kwargs)
        except BaseException:
            logger.error(
                "llm_call_failed",
                model=self.model,
                duration_ms=round((time.perf_counter() - started) * 1000, 3),
                exc_info=True,
            )
            raise
        logger.info(
            "llm_call",
            model=self.model,
            duration_ms=round((time.perf_counter() - started) * 1000, 3),
        )
        return response


@final
class CorrelatedModelClient:
    def __init__(self, client: ModelClient, *, model: str) -> None:
        self.client = client
        self.model = model

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
        )
