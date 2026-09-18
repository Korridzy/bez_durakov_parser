import importlib
import json
from collections.abc import Mapping
from typing import Annotated, Protocol, TYPE_CHECKING, TypeAlias, TypedDict

from .knowledge import Knowledge
from .registry import ToolError, ToolRegistry
from .toolmodule import ParamSpec, ToolSpec
_messages = importlib.import_module("langchain_core.messages")
_tool_api = importlib.import_module("langchain_core.tools")
_prebuilt = importlib.import_module("langgraph.prebuilt")
_types = importlib.import_module("langgraph.types")
_pydantic = importlib.import_module("pydantic")

ToolMessage = _messages.ToolMessage
InjectedToolCallId = _tool_api.InjectedToolCallId
tool = _tool_api.tool
StructuredTool = _tool_api.StructuredTool
InjectedState = _prebuilt.InjectedState
Command = _types.Command
create_model = _pydantic.create_model

if TYPE_CHECKING:
    class ToolState(TypedDict):
        rows_consumed: int
        knowledge_bytes_consumed: int
else:
    ToolState = importlib.import_module("agent.state").GraphState

JsonValue: TypeAlias = (
    str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
)
ToolArgument: TypeAlias = str | int | float | bool | None
ToolArgs: TypeAlias = dict[str, ToolArgument]


class QueryHandle(TypedDict):
    tool: str
    args: ToolArgs


class ToolEnvelope(TypedDict):
    handle: QueryHandle
    rows: int
    cols: list[str]
    summary: str


class AgentToolConfig(Protocol):
    AGENT_MAX_ROWS_PER_FETCH: int
    AGENT_MAX_ROWS_PER_RUN: int
    KNOWLEDGE_MAX_BYTES_PER_TURN: int


class BuiltTool(Protocol):
    name: str


class ToolMessageResult(Protocol):
    content: str
    tool_call_id: str


class CommandResult(Protocol):
    update: Mapping[str, JsonValue | list[ToolMessageResult]] | None


def _field(param: ParamSpec) -> tuple[object, object]:
    """One pydantic field: the wire annotation and either its default or a required marker."""
    annotation = param.wire_type | None if param.optional else param.wire_type
    return annotation, (param.default if param.has_default else ...)


def _parse_handle(handle: dict[str, str | ToolArgs]) -> QueryHandle:
    if set(handle) != {"tool", "args"}:
        raise ToolError("A handle must contain exactly 'tool' and 'args'")
    name = handle["tool"]
    args = handle["args"]
    if not isinstance(name, str) or not isinstance(args, dict):
        raise ToolError("A handle requires a string tool and an object args value")
    return {"tool": name, "args": dict(args)}


def build_tools(
    registry: ToolRegistry,
    cfg: AgentToolConfig,
    knowledge: Knowledge | None = None,
) -> list[BuiltTool]:
    async def metadata(name: str, args: ToolArgs) -> ToolEnvelope | str:
        try:
            records, cols = await registry.execute_normalized(name, args)
        except ToolError as error:
            return f"Tool error: {error}"
        rows = len(records)
        columns = ", ".join(cols) if cols else "none"
        return {
            "handle": {"tool": name, "args": args},
            "rows": rows,
            "cols": cols,
            "summary": f"{rows} rows; columns: {columns}",
        }

    def build_data_tool(spec: ToolSpec) -> BuiltTool:
        """Turn one discovered spec into a StructuredTool over the metadata envelope.

        The args schema is generated from the type hints the operator's method carries, with
        a date rendered as a JSON string so the handle args stay JSON primitives; the
        registry coerces the string back to a date just before the call.
        """
        args_schema = create_model(
            f"{spec.name}_args",
            **{param.name: _field(param) for param in spec.params},
        )

        async def call(**kwargs: ToolArgument) -> ToolEnvelope | str:
            return await metadata(spec.name, kwargs)

        return StructuredTool.from_function(
            coroutine=call,
            name=spec.name,
            description=spec.description,
            args_schema=args_schema,
        )

    data_tools = [build_data_tool(spec) for spec in registry.specs.values()]

    @tool
    async def read_rows(
        handle: dict[str, str | ToolArgs],
        offset: int = 0,
        limit: int = 256,
        *,
        state: Annotated[ToolState, InjectedState],
        tool_call_id: Annotated[str, InjectedToolCallId],
    ) -> CommandResult | str:
        """Read one bounded row page from a previously returned data handle."""
        if offset < 0:
            return "Tool error: offset must be at least 0"
        if limit < 1:
            return "Tool error: limit must be at least 1"

        consumed = state["rows_consumed"]
        if consumed < 0 or consumed > cfg.AGENT_MAX_ROWS_PER_RUN:
            return "Tool error: rows_consumed state is outside the configured run budget"
        remaining = cfg.AGENT_MAX_ROWS_PER_RUN - consumed
        if remaining == 0:
            return f"Tool error: row budget of {cfg.AGENT_MAX_ROWS_PER_RUN} is exhausted"

        try:
            parsed = _parse_handle(handle)
            records, _ = await registry.execute_normalized(parsed["tool"], parsed["args"])
        except ToolError as error:
            return f"Tool error: {error}"

        fetch_limit = min(limit, cfg.AGENT_MAX_ROWS_PER_FETCH)
        allowed = min(fetch_limit, remaining)
        page = records[offset : offset + allowed]
        new_total = consumed + len(page)
        payload = {
            "records": page,
            "offset": offset,
            "returned": len(page),
            "rows_consumed": new_total,
            "budget_limited": allowed < fetch_limit,
        }
        return Command(
            update={
                "rows_consumed": new_total,
                "messages": [
                    ToolMessage(
                        content=json.dumps(payload, ensure_ascii=False),
                        tool_call_id=tool_call_id,
                    )
                ],
            }
        )

    @tool
    async def mark_report(
        handle: dict[str, str | ToolArgs],
        *,
        tool_call_id: Annotated[str, InjectedToolCallId],
    ) -> CommandResult | str:
        """Validate and mark a data handle as the report rendered for this turn."""
        try:
            parsed = _parse_handle(handle)
            await registry.execute_normalized(parsed["tool"], parsed["args"])
        except ToolError as error:
            return f"Tool error: {error}"

        content = json.dumps({"report_marked": parsed}, ensure_ascii=False)
        return Command(
            update={
                "report_payload": parsed,
                "messages": [ToolMessage(content=content, tool_call_id=tool_call_id)],
            }
        )

    existing_tools = [*data_tools, read_rows, mark_report]
    if knowledge is None:
        return existing_tools

    @tool
    async def read_knowledge(
        topic: str,
        *,
        state: Annotated[ToolState, InjectedState],
        tool_call_id: Annotated[str, InjectedToolCallId],
    ) -> CommandResult | str:
        """Return the full Markdown of one knowledge topic. Pass the topic id exactly as listed under Knowledge topics in the system prompt."""
        consumed = state["knowledge_bytes_consumed"]
        if consumed < 0 or consumed > cfg.KNOWLEDGE_MAX_BYTES_PER_TURN:
            return "Tool error: knowledge_bytes_consumed state is outside the configured turn budget"
        remaining = cfg.KNOWLEDGE_MAX_BYTES_PER_TURN - consumed
        if remaining == 0:
            return (
                "Tool error: knowledge byte budget of "
                f"{cfg.KNOWLEDGE_MAX_BYTES_PER_TURN} is exhausted"
            )

        for knowledge_topic in knowledge.topics:
            if knowledge_topic.id == topic:
                document_bytes = len(knowledge_topic.text.encode("utf-8"))
                if document_bytes > remaining:
                    return (
                        "Tool error: knowledge byte budget of "
                        f"{cfg.KNOWLEDGE_MAX_BYTES_PER_TURN} is exhausted"
                    )
                new_total = consumed + document_bytes
                return Command(
                    update={
                        "knowledge_bytes_consumed": new_total,
                        "messages": [
                            ToolMessage(
                                content=knowledge_topic.text,
                                tool_call_id=tool_call_id,
                            )
                        ],
                    }
                )

        available_topics = ", ".join(topic.id for topic in knowledge.topics)
        return (
            f"Tool error: unknown knowledge topic '{topic}'. "
            f"Available topics: {available_topics}"
        )

    return [read_knowledge, *existing_tools]
