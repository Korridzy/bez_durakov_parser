"""The scope gate's decision schema and the strict parser for its output.

The gate model answers through a single schema tool call, which is the transport
that survives every provider reached through the LiteLLM proxy; a bare JSON body
is accepted as the fallback for providers that answer in text.

Parsing is deliberately hand-rolled. LangChain's output parsers repair partial
JSON, and a repaired verdict is a silent misclassification of a user's turn, so
nothing here completes, coerces or invents a field: anything that is not exactly
one well-formed decision raises `GateOutputError`, which the caller turns into a
fail-open turn rather than a guessed reply.

Deliberately free of any `bd_shared.config` dependency: the schema and the parser
are pure and independently testable, and the node that owns the model client
passes configuration in.
"""

from collections.abc import Mapping
from typing import Literal, TypeAlias

from pydantic import (
    BaseModel,
    ConfigDict,
    ValidationError,
    field_validator,
    model_validator,
)

from .graph import AgentMessageView
from .reasoning import extract_text

ScopeVerdict: TypeAlias = Literal["in_scope", "unrelated", "unclear", "mixed"]


class GateOutputError(ValueError):
    """Raised when a gate response is not exactly one valid decision."""


class GateDecision(BaseModel):
    """One classification of one incoming user message.

    Frozen and strict: the node stores the verdict in graph state and the reply
    straight into the conversation, so a decision must never be mutated after it
    was judged, and a wrongly typed field is an unparsable response, not a value
    to cast.
    """

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    verdict: ScopeVerdict
    reply: str | None
    note: str | None

    @field_validator("reply", "note")
    @classmethod
    def reject_blank_text(cls, value: str | None) -> str | None:
        """A whitespace-only string is a missing field wearing a costume."""
        if value is not None and not value.strip():
            raise ValueError("must be null or non-blank text, not whitespace")
        return value

    @model_validator(mode="after")
    def require_the_fields_of_the_verdict(self) -> "GateDecision":
        """Each verdict owns exactly one field combination; the rest are refusals."""
        if self.verdict in ("unrelated", "unclear"):
            if self.reply is None or self.note is not None:
                raise ValueError(
                    f"verdict {self.verdict} requires a reply and a null note"
                )
        elif self.verdict == "mixed":
            if self.note is None or self.reply is not None:
                raise ValueError("verdict mixed requires a note and a null reply")
        elif self.reply is not None or self.note is not None:
            raise ValueError("verdict in_scope requires a null reply and a null note")
        return self


def parse_gate_decision(response: AgentMessageView) -> GateDecision:
    """Read one `GateDecision` out of a gate model response.

    Exactly one tool call is the expected shape and its arguments are validated
    as they arrived. With no tool call the response text is validated as JSON.
    Every other shape - two tool calls, no tool call and no parsable text, or a
    payload the model rejects - raises `GateOutputError`.
    """
    tool_calls = response.tool_calls
    if len(tool_calls) > 1:
        raise GateOutputError(
            f"expected exactly one tool call, the response carries {len(tool_calls)}"
        )

    if tool_calls:
        call = tool_calls[0]
        arguments = call.get("args") if isinstance(call, Mapping) else None
        if not isinstance(arguments, Mapping):
            raise GateOutputError("the tool call carries no argument object")
        try:
            return GateDecision.model_validate(dict(arguments))
        except ValidationError as error:
            raise GateOutputError(
                f"the tool call arguments are not a decision: {error}"
            ) from error

    text = extract_text(response.content).strip()
    if not text:
        raise GateOutputError("the response carries neither a tool call nor text")
    try:
        return GateDecision.model_validate_json(text)
    except ValidationError as error:
        raise GateOutputError(
            f"the response text is not a decision: {error}"
        ) from error
