from __future__ import annotations

import importlib
import logging
from asyncio import wait_for
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import (
    Final,
    Protocol,
    TypeGuard,
    TypedDict,
    final,
    runtime_checkable,
)

from agent.graph import (
    CompiledGraph,
    ModelClient,
    MessageView,
    RECURSION_LIMIT_MARKER,
    ThreadConfig,
    arun,
    build_graph,
)
from agent.knowledge import Knowledge, compose_system_prompt
from agent.reasoning import OutboundReasoningFilter, current_turn_reasoning, extract_text
from agent.registry import ToolRegistry
from agent.tools import BuiltTool, ToolArgs, build_tools
from .report_contracts import (
    ChatModelModule,
    ConfigModule,
    MemoryModule,
    ReportResponse,
    ResponseRegistry,
    RuntimeDependencyError,
)
from .report_support import current_turn_messages, failure, success, trace


def _load_runtime_modules() -> tuple[ConfigModule, MemoryModule]:
    modules: tuple[object, ...] = (
        importlib.import_module("bd_shared.config"),
        importlib.import_module("langgraph.checkpoint.memory"),
    )
    config, memory = modules
    if not isinstance(config, ConfigModule):
        raise RuntimeDependencyError("Invalid agent configuration module")
    if not isinstance(memory, MemoryModule):
        raise RuntimeDependencyError("Invalid checkpoint module")
    return config, memory


CONFIG, MEMORY = _load_runtime_modules()


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


def _is_string_mapping(raw: object) -> TypeGuard[dict[str, object]]:
    return isinstance(raw, dict) and all(isinstance(key, str) for key in raw)


def _parse_tool_args(raw: object) -> ToolArgs:
    if not _is_string_mapping(raw):
        raise RuntimeDependencyError("Tool arguments are not a mapping")
    parsed: ToolArgs = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, (str, int, float, bool, type(None))):
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


@dataclass(frozen=True, slots=True)
class AgentExecution:
    graph: CompiledGraph
    timeout_seconds: float


@final
class ReportAgentSystem:
    def __init__(
        self,
        service: object,
        model_client: ModelClient | None = None,
        checkpointer: object | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        knowledge: Knowledge | None = None,
        context: str = "",
        history: Sequence[MessageView] = (),
        extra_tools: Sequence[BuiltTool] = (),
        max_steps: int | None = None,
    ) -> None:
        # The backend owns the only engine and injects the service built over it, so this
        # runtime never constructs one of its own.
        registry = ToolRegistry(service)
        self.service: object = service
        self._registry: ResponseRegistry = registry
        saver = checkpointer if checkpointer is not None else MEMORY.InMemorySaver()
        self._saver: object = saver
        self._history = history
        self._max_steps = max_steps
        client = model_client if model_client is not None else _new_model_client()
        tools = build_tools(registry, CONFIG, knowledge=knowledge)
        if {t.name for t in tools} & {t.name for t in extra_tools}:
            raise RuntimeDependencyError("Additional tools collide with data tools")
        tools.extend(extra_tools)
        self._execution = AgentExecution(
            build_graph(client, tools, saver, compose_system_prompt(knowledge) + context),
            timeout_seconds,
        )

    async def process_user_request(
        self, user_message: str, session_id: str
    ) -> ReportResponse:
        try:
            execution = self._execution
            return await self._process_agent(
                user_message, session_id, execution.graph, execution.timeout_seconds
            )
        except Exception as error:
            logger.exception("Report request failed")
            return failure(
                "Не удалось сформировать отчёт с помощью агента.",
                str(error),
                reasoning=await self._partial_reasoning(session_id),
            )

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

    async def _process_agent(
        self,
        user_message: str,
        session_id: str,
        graph: CompiledGraph,
        timeout_seconds: float,
    ) -> ReportResponse:
        try:
            prior_messages = ()
            if self._history and _is_checkpoint_saver(self._saver):
                checkpoint = await self._saver.aget_tuple({"configurable": {"thread_id": session_id}})
                if checkpoint is None:
                    prior_messages = self._history
            if self._max_steps is not None:
                run = arun(graph, user_message, session_id, prior_messages, max_steps=self._max_steps)
            else:
                run = arun(graph, user_message, session_id, prior_messages) if prior_messages else arun(graph, user_message, session_id)
            result = await wait_for(run, timeout_seconds)
        except TimeoutError:
            return failure(
                "Время ожидания ответа агента истекло.",
                "timeout",
                reasoning=await self._partial_reasoning(session_id),
            )
        if "error" in result:
            return failure(
                "Агент превысил допустимое число шагов.",
                RECURSION_LIMIT_MARKER,
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
            query_trace,
            data,
            reasoning=current_turn_reasoning(result["messages"]),
        )
