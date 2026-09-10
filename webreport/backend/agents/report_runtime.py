from __future__ import annotations

import importlib
import logging
from asyncio import wait_for
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import (
    Final,
    Protocol,
    TypeAlias,
    TypeGuard,
    TypedDict,
    assert_never,
    final,
    runtime_checkable,
)

from agent.graph import (
    CompiledGraph,
    ConversationState,
    ModelClient,
    RECURSION_LIMIT_MARKER,
    StateUpdate,
    ThreadConfig,
    arun,
    build_graph,
)
from agent.knowledge import Knowledge, compose_system_prompt
from agent.reasoning import OutboundReasoningFilter, current_turn_reasoning, extract_text
from agent.registry import ToolRegistry
from agent.tools import ToolArgs, build_tools
from .report_contracts import (
    ChatModelModule,
    ConfigModule,
    GameDataServiceView,
    HistoryGraph,
    Interpreter,
    InterpreterModule,
    LangGraphModule,
    MemoryModule,
    MessageModule,
    Mode,
    QueryPlan,
    ReportResponse,
    ResponseRegistry,
    RuntimeDependencyError,
    StateModule,
)
from .report_support import current_turn_messages, failure, success, trace
from services.game_data_service import GameDataService


def _load_runtime_modules() -> tuple[
    ConfigModule, MessageModule, MemoryModule, LangGraphModule, StateModule
]:
    modules: tuple[object, ...] = (
        importlib.import_module("bd_shared.config"),
        importlib.import_module("langchain_core.messages"),
        importlib.import_module("langgraph.checkpoint.memory"),
        importlib.import_module("langgraph.graph"),
        importlib.import_module("agent.state"),
    )
    config, messages, memory, langgraph, state = modules
    if not isinstance(config, ConfigModule):
        raise RuntimeDependencyError("Invalid agent configuration module")
    if not isinstance(messages, MessageModule):
        raise RuntimeDependencyError("Invalid message module")
    if not isinstance(memory, MemoryModule):
        raise RuntimeDependencyError("Invalid checkpoint module")
    if not isinstance(langgraph, LangGraphModule):
        raise RuntimeDependencyError("Invalid graph module")
    if not isinstance(state, StateModule):
        raise RuntimeDependencyError("Invalid graph state module")
    return config, messages, memory, langgraph, state


CONFIG, MESSAGES, MEMORY, LANGGRAPH, STATE = _load_runtime_modules()


class CheckpointConfig(TypedDict):
    configurable: ThreadConfig


class CheckpointSaver(Protocol):
    async def aget_tuple(self, config: CheckpointConfig) -> object: ...


@runtime_checkable
class CheckpointTuple(Protocol):
    checkpoint: Mapping[str, object]


def _is_checkpoint_saver(value: object) -> TypeGuard[CheckpointSaver]:
    return callable(getattr(value, "aget_tuple", None))


def _is_checkpoint_tuple(value: object) -> TypeGuard[CheckpointTuple]:
    return isinstance(value, CheckpointTuple)


def _is_checkpoint_channels(value: object) -> TypeGuard[Mapping[str, object]]:
    return isinstance(value, Mapping)


def _checkpoint_messages(value: object) -> Sequence[object] | None:
    if not _is_checkpoint_tuple(value):
        return None
    channel_values = value.checkpoint.get("channel_values")
    if not _is_checkpoint_channels(channel_values):
        return None
    messages = channel_values.get("messages")
    if isinstance(messages, Sequence) and not isinstance(messages, (str, bytes)):
        return messages
    return None
DEFAULT_TIMEOUT_SECONDS: Final = CONFIG.AGENT_TIMEOUT_SECONDS
logger = logging.getLogger(__name__)


def parse_legacy_query(raw: object) -> QueryPlan:
    if not _is_string_mapping(raw):
        raise RuntimeDependencyError("Legacy interpreter returned a non-mapping")
    method = raw.get("method")
    params = raw.get("params")
    description = raw.get("description")
    if not isinstance(method, str) or not isinstance(description, str):
        raise RuntimeDependencyError("Legacy interpreter returned invalid metadata")
    plan: QueryPlan = {
        "method": method,
        "params": _parse_tool_args(params),
        "description": description,
    }
    if "year" in raw:
        year = raw["year"]
        if isinstance(year, (int, type(None))):
            plan["year"] = year
    return plan


def _is_string_mapping(raw: object) -> TypeGuard[dict[str, object]]:
    return isinstance(raw, dict) and all(isinstance(key, str) for key in raw)


def _parse_tool_args(raw: object) -> ToolArgs:
    if not _is_string_mapping(raw):
        raise RuntimeDependencyError("Tool arguments are not a mapping")
    parsed: ToolArgs = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, (str, int, bool, type(None))):
            raise RuntimeDependencyError("Tool arguments contain an unsupported value")
        parsed[key] = value
    return parsed


def _parse_handle(payload: object) -> tuple[str, ToolArgs]:
    if not _is_string_mapping(payload):
        raise RuntimeDependencyError("Marked report handle is not a mapping")
    name = payload.get("tool")
    if not isinstance(name, str):
        raise RuntimeDependencyError("Marked report tool is invalid")
    return name, _parse_tool_args(payload.get("args"))


def _new_interpreter() -> Interpreter:
    module: object = importlib.import_module("agents.report_agents")
    if not isinstance(module, InterpreterModule):
        raise RuntimeDependencyError("Invalid fallback interpreter module")
    return module.FallbackInterpreter()


def _new_model_client() -> ModelClient:
    module: object = importlib.import_module("langchain_litellm")
    if not isinstance(module, ChatModelModule):
        raise RuntimeDependencyError("Invalid chat model module")
    # Anthropic-style thinking models are unsupported because thinking_blocks do not round-trip.
    return OutboundReasoningFilter(
        module.ChatLiteLLM(
            model="litellm_proxy/" + CONFIG.AGENT_MODEL,
            api_base=CONFIG.LITELLM_BASE_URL,
            api_key="sk-noop",
            request_timeout=CONFIG.LLM_REQUEST_TIMEOUT_SECONDS,
            model_kwargs={"num_retries": CONFIG.LLM_MAX_RETRIES},
        )
    )


def _build_history_graph(checkpointer: object) -> HistoryGraph:
    async def append_turn(state: ConversationState) -> StateUpdate:
        return {"messages": state["messages"]}

    builder = LANGGRAPH.StateGraph(STATE.GraphState)
    builder.add_node("append_turn", append_turn)
    builder.set_entry_point("append_turn")
    builder.set_finish_point("append_turn")
    return builder.compile(checkpointer=checkpointer)


@dataclass(frozen=True, slots=True)
class FallbackExecution:
    history_graph: HistoryGraph


@dataclass(frozen=True, slots=True)
class AgentExecution:
    graph: CompiledGraph
    timeout_seconds: float


Execution: TypeAlias = FallbackExecution | AgentExecution


@final
class ReportAgentSystem:
    def __init__(
        self,
        service: GameDataServiceView | None = None,
        model_client: ModelClient | None = None,
        checkpointer: object | None = None,
        mode: Mode = "fallback",
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        knowledge: Knowledge | None = None,
    ) -> None:
        selected_service = service if service is not None else GameDataService()
        registry = ToolRegistry(selected_service)
        self.service: GameDataServiceView = selected_service
        self._registry: ResponseRegistry = registry
        self._interpreter = _new_interpreter()
        saver = checkpointer if checkpointer is not None else MEMORY.InMemorySaver()
        self._saver: object = saver
        match mode:
            case "fallback":
                self._execution: Execution = FallbackExecution(_build_history_graph(saver))
            case "agent":
                client = model_client if model_client is not None else _new_model_client()
                tools = build_tools(registry, CONFIG, knowledge=knowledge)
                self._execution = AgentExecution(
                    build_graph(client, tools, saver, compose_system_prompt(knowledge)),
                    timeout_seconds,
                )
            case unreachable:
                assert_never(unreachable)

    @property
    def mode(self) -> Mode:
        match self._execution:
            case FallbackExecution():
                return "fallback"
            case AgentExecution():
                return "agent"
            case unreachable:
                assert_never(unreachable)

    async def process_user_request(
        self, user_message: str, session_id: str
    ) -> ReportResponse:
        try:
            match self._execution:
                case FallbackExecution(history_graph=history_graph):
                    return await self._process_fallback(user_message, session_id, history_graph)
                case AgentExecution(graph=graph, timeout_seconds=timeout_seconds):
                    return await self._process_agent(user_message, session_id, graph, timeout_seconds)
                case unreachable:
                    assert_never(unreachable)
        except Exception as error:
            mode = self.mode
            logger.exception("Report request failed", extra={"mode": mode})
            match mode:
                case "agent":
                    message = "Не удалось сформировать отчёт с помощью агента."
                    reasoning = await self._partial_reasoning(session_id)
                case "fallback":
                    message = "Не удалось сформировать отчёт."
                    reasoning = None
                case unreachable:
                    assert_never(unreachable)
            return failure(message, str(error), mode, reasoning=reasoning)

    async def _partial_reasoning(self, session_id: str) -> str | None:
        if not _is_checkpoint_saver(self._saver):
            return None
        try:
            checkpoint_tuple = await self._saver.aget_tuple(
                {"configurable": {"thread_id": session_id}}
            )
        except Exception:
            return None
        messages = _checkpoint_messages(checkpoint_tuple)
        return current_turn_reasoning(messages) if messages is not None else None

    async def _process_fallback(
        self, user_message: str, session_id: str, history_graph: HistoryGraph
    ) -> ReportResponse:
        query = self._interpreter.interpret(user_message)
        data = await self._registry.execute_response(query["method"], query["params"])
        message = f"Report generated (fallback mode): {user_message}"
        await history_graph.ainvoke(
            {
                "messages": [
                    MESSAGES.HumanMessage(content=user_message),
                    MESSAGES.AIMessage(content=message),
                ],
                "rows_consumed": 0,
                "knowledge_bytes_consumed": 0,
                "report_payload": None,
            },
            {"configurable": {"thread_id": session_id}, "recursion_limit": 2},
        )
        return success(
            message,
            "fallback",
            [{"tool": query["method"], "args": query["params"]}],
            data,
            reasoning=None,
        )

    async def _process_agent(
        self,
        user_message: str,
        session_id: str,
        graph: CompiledGraph,
        timeout_seconds: float,
    ) -> ReportResponse:
        try:
            result = await wait_for(arun(graph, user_message, session_id), timeout_seconds)
        except TimeoutError:
            return failure(
                "Время ожидания ответа агента истекло.",
                "timeout",
                "agent",
                reasoning=await self._partial_reasoning(session_id),
            )
        if "error" in result:
            return failure(
                "Агент превысил допустимое число шагов.",
                RECURSION_LIMIT_MARKER,
                "agent",
                reasoning=await self._partial_reasoning(session_id),
            )
        turn_messages = current_turn_messages(result["messages"])
        query_trace = trace(turn_messages)
        payload = result["report_payload"]
        data = None
        if payload is not None:
            name, args = _parse_handle(payload)
            data = await self._registry.execute_response(name, args)
        return success(
            extract_text(turn_messages[-1].content),
            "agent",
            query_trace,
            data,
            reasoning=current_turn_reasoning(result["messages"]),
        )
