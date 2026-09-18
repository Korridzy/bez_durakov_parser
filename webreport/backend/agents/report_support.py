from collections.abc import Sequence
from datetime import datetime

from .report_contracts import (
    QueryTrace,
    ReportResponse,
    RuntimeDependencyError,
    StoredMessage,
    ToolCallingMessage,
)


def current_turn_messages(messages: Sequence[object]) -> list[StoredMessage]:
    stored: list[StoredMessage] = []
    last_human = -1
    for message in messages:
        if not isinstance(message, StoredMessage):
            raise RuntimeDependencyError("Checkpoint contains an invalid message")
        stored.append(message)
        if message.type == "human":
            last_human = len(stored) - 1
    if last_human < 0 or last_human == len(stored) - 1:
        raise RuntimeDependencyError("Current turn has no model response")
    return stored[last_human + 1 :]


def trace(messages: Sequence[StoredMessage]) -> list[QueryTrace]:
    return [
        {"tool": call["name"], "args": dict(call["args"])}
        for message in messages
        if isinstance(message, ToolCallingMessage)
        for call in message.tool_calls
    ]


def success(
    message: str,
    query_info: list[QueryTrace],
    data: object | None,
    *,
    reasoning: str | None,
) -> ReportResponse:
    return {
        "success": True,
        "query_info": query_info,
        "data": data,
        "timestamp": datetime.now().isoformat(),
        "message": message,
        "reasoning": reasoning,
    }


def failure(message: str, error: str, *, reasoning: str | None = None) -> ReportResponse:
    return {
        "success": False,
        "error": error,
        "message": message,
        "timestamp": datetime.now().isoformat(),
        "query_info": [],
        "data": None,
        "reasoning": reasoning,
    }
