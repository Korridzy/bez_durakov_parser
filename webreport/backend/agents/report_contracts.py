from collections.abc import Mapping
from typing import NotRequired, Protocol, TypedDict, runtime_checkable

from agent.graph import JsonValue, ModelClient, ToolCall
from agent.tools import AgentToolConfig


class QueryTrace(TypedDict):
    tool: str
    args: Mapping[str, JsonValue]


class ReportResponse(TypedDict):
    success: bool
    query_info: list[QueryTrace]
    data: object | None
    timestamp: str
    message: str
    reasoning: str | None
    error: NotRequired[str]


class ResponseRegistry(Protocol):
    async def execute_response(
        self, name: str, args: Mapping[str, object]
    ) -> object: ...


@runtime_checkable
class StoredMessage(Protocol):
    content: str | list[object]
    type: str


@runtime_checkable
class ToolCallingMessage(StoredMessage, Protocol):
    tool_calls: list[ToolCall]


class SaverFactory(Protocol):
    def __call__(self) -> object: ...


@runtime_checkable
class MemoryModule(Protocol):
    InMemorySaver: SaverFactory


class ChatModelFactory(Protocol):
    def __call__(
        self,
        *,
        model: str,
        api_base: str,
        api_key: str,
        request_timeout: int,
        model_kwargs: Mapping[str, object],
    ) -> ModelClient: ...


@runtime_checkable
class ChatModelModule(Protocol):
    ChatLiteLLM: ChatModelFactory


@runtime_checkable
class ConfigModule(AgentToolConfig, Protocol):
    AGENT_TIMEOUT_SECONDS: int
    LITELLM_BASE_URL: str
    AGENT_MODEL: str
    LLM_MAX_RETRIES: int
    LLM_REQUEST_TIMEOUT_SECONDS: int


class RuntimeDependencyError(RuntimeError):
    pass
