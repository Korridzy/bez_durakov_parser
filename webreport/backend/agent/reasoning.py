"""Reasoning round-trip support for the report agent.

Providers reached through the LiteLLM proxy normalize a model's thinking into
`additional_kwargs["reasoning_content"]`, and the strict ones require it back
during the tool loop of the turn that produced it. `OutboundReasoningFilter`
echoes exactly that span: everything before the last human message goes out as a
copy without the thought, so token cost stays bounded and prior turns are never
re-sent. Checkpoints keep the full history untouched - the filter copies, never
mutates.

Public langchain APIs only (pydantic `model_copy`), and deliberately free of any
litellm import, so the wrapper stays independent of the client package.
"""
from collections.abc import Mapping, Sequence
from typing import Protocol, TypeGuard, final

from .graph import AgentMessageView, BoundModel, MessageView, ModelClient, NamedTool

REASONING_KEY = "reasoning_content"
SEGMENT_SEPARATOR = "\n\n"


class ReasoningMessage(MessageView, Protocol):
    """The message shape the filter copies - public pydantic API only."""

    additional_kwargs: dict[str, object]

    def model_copy(self, *, update: Mapping[str, object]) -> "ReasoningMessage": ...


def extract_text(content: object) -> str:
    """Read message content as text, tolerating provider block lists."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return SEGMENT_SEPARATOR.join(
            str(block["text"])
            for block in content
            if isinstance(block, Mapping)
            and block.get("type") == "text"
            and "text" in block
        )
    return str(content)


def _reasoning_of(message: object) -> str | None:
    extra = getattr(message, "additional_kwargs", None)
    if not isinstance(extra, Mapping):
        return None
    value = extra.get(REASONING_KEY)
    return value if isinstance(value, str) and value else None


def extract_reasoning(messages: Sequence[object]) -> str | None:
    """Join the reasoning segments carried by `messages`, in order."""
    segments = [
        segment
        for segment in (_reasoning_of(message) for message in messages)
        if segment is not None
    ]
    joined = SEGMENT_SEPARATOR.join(segments)
    return joined if joined.strip() else None


def _last_human_index(messages: Sequence[object]) -> int:
    for index in range(len(messages) - 1, -1, -1):
        if getattr(messages[index], "type", None) == "human":
            return index
    return -1


def current_turn_reasoning(messages: Sequence[object]) -> str | None:
    """Reasoning produced after the last human message, or None.

    Lenient by design: it runs on failure paths over whatever a checkpoint
    happened to contain, so a turn without any model response is None rather
    than an error - unlike `report_support.current_turn_messages`.
    """
    last_human = _last_human_index(messages)
    if last_human < 0:
        return None
    return extract_reasoning(messages[last_human + 1 :])


def _carries_reasoning(message: object) -> TypeGuard[ReasoningMessage]:
    """A message with a thought is a pydantic message the filter can copy."""
    return _reasoning_of(message) is not None


def _without_reasoning(message: ReasoningMessage) -> ReasoningMessage:
    kept = {
        key: value
        for key, value in message.additional_kwargs.items()
        if key != REASONING_KEY
    }
    return message.model_copy(update={"additional_kwargs": kept})


def _filtered(messages: Sequence[MessageView]) -> list[MessageView]:
    boundary = _last_human_index(messages)
    return [
        _without_reasoning(message)
        if index < boundary and _carries_reasoning(message)
        else message
        for index, message in enumerate(messages)
    ]


@final
class _FilteredBoundModel:
    """Bound model that drops prior-turn reasoning on the way out."""

    def __init__(self, bound: BoundModel) -> None:
        self.bound = bound

    async def ainvoke(self, messages: Sequence[MessageView]) -> AgentMessageView:
        return await self.bound.ainvoke(_filtered(messages))


@final
class OutboundReasoningFilter:
    """ModelClient wrapper echoing reasoning for the current turn only."""

    def __init__(self, client: ModelClient) -> None:
        self.client = client

    def bind_tools(
        self,
        tools: Sequence[NamedTool],
        *,
        parallel_tool_calls: bool,
    ) -> BoundModel:
        return _FilteredBoundModel(
            self.client.bind_tools(tools, parallel_tool_calls=parallel_tool_calls)
        )
