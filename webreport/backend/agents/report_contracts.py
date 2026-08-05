from collections.abc import Awaitable, Callable, Mapping
from datetime import date
from typing import Literal, NotRequired, Protocol, TypeAlias, TypedDict, runtime_checkable

from agent.graph import ConversationState, JsonValue, ModelClient, RunConfig, StateUpdate, ToolCall
from agent.tools import AgentToolConfig, ToolArgs

Mode: TypeAlias = Literal["agent", "fallback"]


class QueryPlan(TypedDict):
    method: str
    params: ToolArgs
    description: str
    year: NotRequired[int | None]


class QueryTrace(TypedDict):
    tool: str
    args: Mapping[str, JsonValue]


class ReportResponse(TypedDict):
    success: bool
    query_info: list[QueryTrace]
    data: object | None
    timestamp: str
    message: str
    mode: Mode
    error: NotRequired[str]


class GameDataServiceView(Protocol):
    def get_all_games_summary(self) -> object: ...
    def get_game_by_id(self, game_id: int) -> object: ...
    def get_games_by_date_range(
        self, start_date: date, end_date: date | None = None
    ) -> object: ...
    def get_team_game_scores(self, game_id: int | None = None) -> object: ...
    def get_all_teams(self) -> object: ...
    def get_team_statistics(self, team_name: str) -> object: ...
    def get_team_wins(self, team_name: str, year: int | None = None) -> object: ...
    def get_top_teams(self, limit: int = 10) -> object: ...


class Interpreter(Protocol):
    def interpret(self, user_message: str) -> QueryPlan: ...


class ResponseRegistry(Protocol):
    async def execute_response(
        self, name: str, args: Mapping[str, object]
    ) -> object: ...


@runtime_checkable
class StoredMessage(Protocol):
    content: str
    type: str


@runtime_checkable
class ToolCallingMessage(StoredMessage, Protocol):
    tool_calls: list[ToolCall]


class MessageFactory(Protocol):
    def __call__(self, *, content: str) -> StoredMessage: ...


@runtime_checkable
class MessageModule(Protocol):
    AIMessage: MessageFactory
    HumanMessage: MessageFactory


class HistoryGraph(Protocol):
    async def ainvoke(
        self, input_state: ConversationState, config: RunConfig
    ) -> ConversationState: ...


HistoryNode: TypeAlias = Callable[[ConversationState], Awaitable[StateUpdate]]


class StateGraphBuilder(Protocol):
    def add_node(self, name: str, node: HistoryNode) -> None: ...
    def set_entry_point(self, name: str) -> None: ...
    def set_finish_point(self, name: str) -> None: ...
    def compile(self, *, checkpointer: object) -> HistoryGraph: ...


class StateGraphFactory(Protocol):
    def __call__(self, state_schema: object) -> StateGraphBuilder: ...


@runtime_checkable
class LangGraphModule(Protocol):
    StateGraph: StateGraphFactory


@runtime_checkable
class StateModule(Protocol):
    GraphState: object


class SaverFactory(Protocol):
    def __call__(self) -> object: ...


@runtime_checkable
class MemoryModule(Protocol):
    InMemorySaver: SaverFactory


class ChatModelFactory(Protocol):
    def __call__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str,
        max_retries: int,
        timeout: float,
    ) -> ModelClient: ...


@runtime_checkable
class ChatModelModule(Protocol):
    ChatOpenAI: ChatModelFactory


@runtime_checkable
class ConfigModule(AgentToolConfig, Protocol):
    AGENT_TIMEOUT_SECONDS: int
    LITELLM_BASE_URL: str
    AGENT_MODEL: str
    LLM_MAX_RETRIES: int
    LLM_REQUEST_TIMEOUT_SECONDS: int


class InterpreterFactory(Protocol):
    def __call__(self) -> Interpreter: ...


@runtime_checkable
class InterpreterModule(Protocol):
    FallbackInterpreter: InterpreterFactory


class RuntimeDependencyError(RuntimeError):
    pass
