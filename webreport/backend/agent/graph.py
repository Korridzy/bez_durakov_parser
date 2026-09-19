import importlib
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import (
    cast,
    Final,
    Literal,
    NotRequired,
    Protocol,
    TypeAlias,
    TypedDict,
    TypeVar,
)

from .state import GraphState

_config = importlib.import_module("bd_shared.config")
_errors = importlib.import_module("langgraph.errors")
_graph = importlib.import_module("langgraph.graph")
_messages = importlib.import_module("langchain_core.messages")
_prebuilt = importlib.import_module("langgraph.prebuilt")
_runnables = importlib.import_module("langchain_core.runnables")

END = _graph.END
GraphRecursionError = _errors.GraphRecursionError
HumanMessage = _messages.HumanMessage
AIMessage = _messages.AIMessage
SystemMessage = _messages.SystemMessage
ToolMessage = _messages.ToolMessage
StateGraph = _graph.StateGraph
ToolNode = _prebuilt.ToolNode
# LangGraph injects a node's run configuration only when the parameter carries this
# exact annotation, so nodes in sibling modules take it from here.
RunnableConfig = _runnables.RunnableConfig

RECURSION_LIMIT_MARKER: Final = "recursion_limit"

JsonValue: TypeAlias = (
    str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
)


class ToolCall(TypedDict):
    name: str
    args: dict[str, JsonValue]
    id: str
    type: str


class MessageView(Protocol):
    content: str


class AgentMessageView(MessageView, Protocol):
    tool_calls: list[ToolCall]


class NamedTool(Protocol):
    name: str
    description: str


class BoundModel(Protocol):
    async def ainvoke(self, messages: Sequence[MessageView]) -> AgentMessageView: ...


class ModelClient(Protocol):
    def bind_tools(
        self,
        tools: Sequence[NamedTool],
        *,
        parallel_tool_calls: bool,
    ) -> BoundModel: ...


class ConversationState(TypedDict):
    messages: list[MessageView]
    report_payload: dict[str, JsonValue] | None
    rows_consumed: int
    knowledge_bytes_consumed: int
    scope_verdict: NotRequired[str | None]
    scope_note: NotRequired[str | None]


class AgentState(TypedDict):
    messages: list[AgentMessageView]
    report_payload: dict[str, JsonValue] | None
    rows_consumed: int
    knowledge_bytes_consumed: int
    scope_verdict: NotRequired[str | None]
    scope_note: NotRequired[str | None]


class StateUpdate(TypedDict, total=False):
    messages: list[MessageView]
    report_payload: dict[str, JsonValue] | None
    rows_consumed: int
    knowledge_bytes_consumed: int
    scope_verdict: str | None
    scope_note: str | None


class ThreadConfig(TypedDict):
    thread_id: str


class RunConfig(TypedDict):
    configurable: ThreadConfig
    recursion_limit: int


GateNode: TypeAlias = Callable[
    [ConversationState, RunConfig],
    Awaitable[Mapping[str, object]],
]
GateRouter: TypeAlias = Callable[[Mapping[str, object]], str]


class RecursionLimitResult(TypedDict):
    error: Literal["recursion_limit"]


class CompiledGraph(Protocol):
    async def ainvoke(
        self,
        input_state: ConversationState,
        config: RunConfig,
    ) -> ConversationState: ...


Checkpointer = TypeVar("Checkpointer")
GraphRunResult: TypeAlias = ConversationState | RecursionLimitResult


class _ToolResultMessage(MessageView, Protocol):
    tool_call_id: str

    def model_copy(self, *, update: Mapping[str, object]) -> MessageView: ...


def _compact_knowledge(messages: list[MessageView]) -> list[MessageView]:
    """Replace knowledge results in a message-list copy, retaining call/result identity."""
    topics: dict[str, JsonValue] = {}
    replacements: list[MessageView] = []
    for index, message in enumerate(messages):
        if isinstance(message, AIMessage):
            for call in cast(AgentMessageView, message).tool_calls:
                if call["name"] == "read_knowledge":
                    topics[call["id"]] = call["args"].get("topic")
        elif isinstance(message, ToolMessage):
            result = cast(_ToolResultMessage, message)
            if result.tool_call_id in topics:
                topic = topics[result.tool_call_id]
                placeholder = f"[knowledge topic '{topic}' read; document omitted from history]"
                if result.content != placeholder:
                    # model_copy keeps id and tool_call_id; add_messages replaces in place.
                    replacement = result.model_copy(update={"content": placeholder})
                    messages[index] = replacement
                    replacements.append(replacement)
    return replacements


def build_graph(
    model_client: ModelClient,
    tools: Sequence[NamedTool],
    checkpointer: Checkpointer,
    system_prompt: str,
    *,
    gate: tuple[GateNode, GateRouter] | None = None,
) -> CompiledGraph:
    bound_model = model_client.bind_tools(tools, parallel_tool_calls=False)
    single_tool_builder = StateGraph(GraphState)
    single_tool_builder.add_node("tool", ToolNode(tools))
    single_tool_builder.set_entry_point("tool")
    single_tool_builder.set_finish_point("tool")
    single_tool_graph = single_tool_builder.compile()

    async def call_model(state: ConversationState) -> StateUpdate:
        """Keep documents within their fetching turn, without another super-step.

        Prior-turn documents are removed from what the model sees and from the
        resumable head state; historical checkpoint rows may retain them until
        thread deletion. The head is compacted on each completed model-node
        update: a failed invocation can leave an uncompacted head, but its
        outbound copy is already compacted. Current-turn reads remain available
        until the final answer and are compacted in that same state update.
        """
        boundary = max(
            (index for index, message in enumerate(state["messages"])
             if isinstance(message, HumanMessage)),
            default=-1,
        )
        prior = state["messages"][:boundary + 1]
        current = state["messages"][boundary + 1:]
        replacements = _compact_knowledge(prior)
        scope_note = state.get("scope_note")
        turn_system_prompt = (
            system_prompt
            if scope_note is None
            else f"{system_prompt}\n\n## Scope gate note\n\n{scope_note}"
        )
        response = await bound_model.ainvoke(
            [SystemMessage(turn_system_prompt), *prior, *current]
        )
        if not response.tool_calls:
            replacements.extend(_compact_knowledge(current))
        return {"messages": [*replacements, response]}

    def route_after_model(state: AgentState) -> str:
        return "tools" if state["messages"][-1].tool_calls else END

    async def call_tools_sequentially(state: AgentState) -> StateUpdate:
        accumulated: AgentState = {
            "messages": list(state["messages"]),
            "report_payload": state["report_payload"],
            "rows_consumed": state["rows_consumed"],
            "knowledge_bytes_consumed": state["knowledge_bytes_consumed"],
        }
        emitted_messages: list[MessageView] = []
        for current_call in state["messages"][-1].tool_calls:
            call_state: AgentState = {
                "messages": [
                    *accumulated["messages"],
                    AIMessage(content="", tool_calls=[current_call]),
                ],
                "report_payload": accumulated["report_payload"],
                "rows_consumed": accumulated["rows_consumed"],
                "knowledge_bytes_consumed": accumulated["knowledge_bytes_consumed"],
            }
            prior_message_count = len(call_state["messages"])
            accumulated = await single_tool_graph.ainvoke(call_state)
            emitted_messages.extend(accumulated["messages"][prior_message_count:])
        return {
            "messages": emitted_messages,
            "report_payload": accumulated["report_payload"],
            "rows_consumed": accumulated["rows_consumed"],
            "knowledge_bytes_consumed": accumulated["knowledge_bytes_consumed"],
        }

    builder = StateGraph(GraphState)
    builder.add_node("agent", call_model)
    builder.add_node("tools", call_tools_sequentially)
    if gate is None:
        builder.set_entry_point("agent")
    else:
        call_gate, route_after_gate = gate
        builder.add_node("gate", call_gate)
        builder.set_entry_point("gate")
        builder.add_conditional_edges(
            "gate",
            route_after_gate,
            {"agent": "agent", END: END},
        )
    builder.add_conditional_edges(
        "agent",
        route_after_model,
        {"tools": "tools", END: END},
    )
    builder.add_edge("tools", "agent")
    return builder.compile(checkpointer=checkpointer)


async def arun(
    graph: CompiledGraph,
    user_message: str,
    thread_id: str,
    *,
    extra_steps: int = 0,
) -> GraphRunResult:
    try:
        return await graph.ainvoke(
            {
                "messages": [HumanMessage(content=user_message)],
                "rows_consumed": 0,
                "knowledge_bytes_consumed": 0,
                "report_payload": None,
                "scope_verdict": None,
                "scope_note": None,
            },
            {
                "configurable": {"thread_id": thread_id},
                "recursion_limit": 2 * _config.AGENT_RECURSION_LIMIT + 1 + extra_steps,
            },
        )
    except GraphRecursionError:
        return {"error": RECURSION_LIMIT_MARKER}
