"""
FastAPI backend for the web reporting system.
Provides REST API for chat and report generation.
"""
from typing import Dict, Any, Literal, Optional, Protocol, TypedDict, TypeGuard, assert_never
from collections.abc import Sequence
from datetime import datetime
import asyncio
import importlib
import logging
import uuid
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from bd_shared.config import (
    AGENT_MODEL,
    CHECKPOINT_DB_PATH,
    CHECKPOINT_TTL_SECONDS,
    DATABASE_NAME,
    KNOWLEDGE_DIR,
    KNOWLEDGE_MAX_BYTES_PER_TURN,
    KNOWLEDGE_MAX_DOC_BYTES,
    KNOWLEDGE_MAX_PERSONA_CHARS,
    KNOWLEDGE_MAX_SUMMARY_CHARS,
    KNOWLEDGE_MAX_TITLE_CHARS,
    KNOWLEDGE_MAX_TOPICS,
    LITELLM_BASE_URL,
    PROBE_REQUEST_TIMEOUT_SECONDS,
    PROBE_RETRY_ATTEMPTS,
    PROBE_RETRY_DELAY_SECONDS,
    WEBREPORT_ALLOWED_ORIGINS,
    WEBREPORT_DEBUG,
)


from agent.knowledge import (
    Knowledge,
    KnowledgeError,
    KnowledgeLimits,
    load_knowledge,
    validate_limits,
)
from agent.reasoning import extract_reasoning, extract_text
from agents.report_agents import ReportAgentSystem
from services.game_data_service import GameDataService
from session_store import MAX_SESSIONS, SessionIndex

aiosqlite = importlib.import_module("aiosqlite")
AsyncSqliteSaver = importlib.import_module(
    "langgraph.checkpoint.sqlite.aio"
).AsyncSqliteSaver
requests = importlib.import_module("requests")
langchain_messages = importlib.import_module("langchain_core.messages")
logger = logging.getLogger(__name__)


# Pydantic models for request/response
class ChatMessage(BaseModel):
    """Chat message model."""
    message: str = Field(..., description="User's message/requirement for report")
    session_id: Optional[str] = Field(None, description="Session ID for conversation tracking")


class ChatResponse(BaseModel):
    """Chat response model."""
    success: bool
    session_id: str
    mode: str
    data: Optional[Any] = None
    query_info: list[Dict[str, Any]]
    message: str
    timestamp: str
    error: Optional[str] = None
    reasoning: Optional[str] = None


class ReportData(BaseModel):
    """Report data model."""
    report_id: str
    data: Any
    generated_at: str
    query: Dict[str, Any]


class HealthServices(TypedDict):
    database: bool
    agents: bool
    llm_proxy: bool


class HealthResponse(TypedDict):
    status: str
    timestamp: str
    services: HealthServices


# Initialize FastAPI app
app = FastAPI(
    title="Game Data Report API",
    description="REST API for generating game data reports using AI agents",
    version="1.0.0"
)

# CORS middleware for frontend communication
app.add_middleware(
    CORSMiddleware,
    allow_origins=WEBREPORT_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global instances
agent_system: Optional[ReportAgentSystem] = None
checkpoint_connection = None
checkpoint_saver = None
data_service: Optional[GameDataService] = None
knowledge: Knowledge | None = None
llm_proxy_healthy: bool = False
sessions: SessionIndex = SessionIndex(
    max_size=MAX_SESSIONS,
    ttl=CHECKPOINT_TTL_SECONDS,
)
pinned: dict[str, int] = {}
admission_lock = asyncio.Lock()

STARTUP_RETRY_ATTEMPTS = 5
STARTUP_RETRY_DELAY_SECONDS = 2
PERMANENT_PROBE_STATUSES = frozenset({400, 401, 403, 404})
probe_sleep = asyncio.sleep


def _internal_error(e: Exception) -> HTTPException:
    logger.exception("Unexpected error in API handler")
    detail = str(e) if WEBREPORT_DEBUG else "Internal server error"
    return HTTPException(status_code=500, detail=detail)


async def initialize_data_service_with_retry() -> GameDataService:
    last_error: Exception | None = None

    for attempt in range(1, STARTUP_RETRY_ATTEMPTS + 1):
        try:
            return GameDataService()
        except Exception as exc:
            last_error = exc
            logger.warning(
                "Database initialization attempt %d/%d failed: %s",
                attempt,
                STARTUP_RETRY_ATTEMPTS,
                exc,
            )
            if attempt < STARTUP_RETRY_ATTEMPTS:
                await asyncio.sleep(STARTUP_RETRY_DELAY_SECONDS)

    if last_error is None:
        raise RuntimeError("Database initialization failed without an exception")

    raise last_error


ProbeVerdict = Literal["healthy", "permanent", "transient"]


def _probe_exception_status(body: Any) -> Optional[int]:
    if not isinstance(body, dict):
        return None

    unhealthy_endpoints = body.get("unhealthy_endpoints")
    if not isinstance(unhealthy_endpoints, list):
        return None

    first_status = None
    for endpoint in unhealthy_endpoints:
        if not isinstance(endpoint, dict):
            continue
        exception_status = endpoint.get("exception_status")
        if type(exception_status) is not int:
            continue
        if exception_status in PERMANENT_PROBE_STATUSES:
            return exception_status
        if first_status is None:
            first_status = exception_status

    return first_status


def _classify_probe_response(status_code: Optional[int], body: Any) -> ProbeVerdict:
    if status_code in PERMANENT_PROBE_STATUSES:
        return "permanent"

    if status_code == 200 and isinstance(body, dict):
        healthy_endpoints = body.get("healthy_endpoints")
        if isinstance(healthy_endpoints, list) and healthy_endpoints:
            return "healthy"

    if _probe_exception_status(body) in PERMANENT_PROBE_STATUSES:
        return "permanent"

    return "transient"


async def probe_llm_proxy(sleep=asyncio.sleep) -> bool:
    status_code = None
    body = None
    verdict: ProbeVerdict = "transient"
    proxy_is_healthy = False

    for attempt in range(1, PROBE_RETRY_ATTEMPTS + 1):
        status_code = None
        body = None
        try:
            response = await asyncio.to_thread(
                requests.get,
                f"{LITELLM_BASE_URL}/health",
                params={"model": AGENT_MODEL},
                timeout=PROBE_REQUEST_TIMEOUT_SECONDS,
            )
            status_code = response.status_code
            if status_code not in PERMANENT_PROBE_STATUSES:
                try:
                    body = response.json()
                except (requests.RequestException, ValueError):
                    body = None
            verdict = _classify_probe_response(status_code, body)
        except requests.RequestException:
            verdict = "transient"

        match verdict:
            case "healthy":
                proxy_is_healthy = True
                break
            case "permanent":
                break
            case "transient":
                if attempt < PROBE_RETRY_ATTEMPTS:
                    await sleep(PROBE_RETRY_DELAY_SECONDS)
                    continue
                break
            case unreachable:
                assert_never(unreachable)

    logger.warning(
        "LiteLLM probe classified verdict=%s status=%s exception_status=%s",
        verdict,
        status_code,
        _probe_exception_status(body),
    )
    return proxy_is_healthy


async def rebuild_session_index() -> None:
    saver = checkpoint_saver
    assert saver is not None

    # LangGraph checkpoint IDs are time-ordered UUIDs, so MAX + DESC is recency order.
    async with saver.conn.execute(
        """
        SELECT thread_id, MAX(checkpoint_id) AS latest
        FROM checkpoints
        GROUP BY thread_id
        ORDER BY latest DESC
        """
    ) as cursor:
        rows = await cursor.fetchall()

    newest_first_ids = [row[0] for row in rows]
    retained_ids = newest_first_ids[:sessions.max_size]
    excess_ids = newest_first_ids[sessions.max_size:]

    for thread_id in excess_ids:
        await saver.adelete_thread(thread_id)

    await sessions.seed(retained_ids)


@app.on_event("startup")
async def startup_event():
    """Initialize services on startup."""
    global agent_system, checkpoint_connection, checkpoint_saver
    global data_service, knowledge, llm_proxy_healthy

    try:
        knowledge_limits = KnowledgeLimits(
            max_title_chars=KNOWLEDGE_MAX_TITLE_CHARS,
            max_summary_chars=KNOWLEDGE_MAX_SUMMARY_CHARS,
            max_persona_chars=KNOWLEDGE_MAX_PERSONA_CHARS,
            max_topics=KNOWLEDGE_MAX_TOPICS,
            max_doc_bytes=KNOWLEDGE_MAX_DOC_BYTES,
            max_bytes_per_turn=KNOWLEDGE_MAX_BYTES_PER_TURN,
        )
        validate_limits(knowledge_limits)
        if KNOWLEDGE_DIR is None:
            logger.warning(
                "Knowledge folder is not configured (webreport.knowledge_dir is unset); the agent runs without dataset knowledge."
            )
            knowledge = None
        elif not KNOWLEDGE_DIR.exists():
            logger.warning(
                "Knowledge folder not found at %s; the agent runs without dataset knowledge.",
                KNOWLEDGE_DIR.resolve(),
            )
            knowledge = None
        else:
            knowledge = load_knowledge(
                KNOWLEDGE_DIR,
                DATABASE_NAME,
                knowledge_limits,
            )
            logger.info(
                "Knowledge loaded: dataset=%s, topics=%d",
                getattr(knowledge.manifest, "dataset"),
                len(knowledge.topics),
            )
    except KnowledgeError as error:
        logger.error("Knowledge folder is invalid: %s", error)
        raise

    data_service = await initialize_data_service_with_retry()

    connection = await aiosqlite.connect(CHECKPOINT_DB_PATH)
    saver = AsyncSqliteSaver(connection)
    startup_complete = False
    try:
        # Local checkpoint setup is intentionally not retried; an unwritable store aborts startup.
        await saver.setup()
        checkpoint_connection = connection
        checkpoint_saver = saver

        llm_proxy_healthy = await probe_llm_proxy(sleep=probe_sleep)
        mode = "agent" if llm_proxy_healthy else "fallback"
        logger.warning("LLM mode elected: %s", mode)

        await rebuild_session_index()

        agent_system = ReportAgentSystem(
            service=data_service,
            checkpointer=saver,
            mode=mode,
            knowledge=knowledge,
        )
        startup_complete = True
    finally:
        if not startup_complete:
            await connection.close()
            checkpoint_connection = None
            checkpoint_saver = None

    logger.info("Services initialized successfully")


@app.on_event("shutdown")
async def shutdown_event() -> None:
    global checkpoint_connection, checkpoint_saver

    if checkpoint_connection is not None:
        await checkpoint_connection.close()
    checkpoint_connection = None
    checkpoint_saver = None


@app.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": "Game Data Report API",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "health": "/health",
            "chat": "/api/chat",
            "history": "/api/history/{session_id}",
            "clear": "/api/clear/{session_id}",
            "games": "/api/games",
            "teams": "/api/teams"
        }
    }


@app.get("/health", response_model=None)
async def health_check() -> HealthResponse:
    """Health check endpoint."""
    if data_service is None:
        raise HTTPException(status_code=503, detail="Data service not available")

    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "services": {
            "database": data_service is not None,
            "agents": agent_system is not None,
            "llm_proxy": llm_proxy_healthy,
        }
    }


@app.post("/api/chat", response_model=ChatResponse)
async def chat(message: ChatMessage):
    """
    Process user message and generate report.

    Args:
        message: User's chat message with requirements

    Returns:
        Chat response with report data
    """
    system = agent_system
    saver = checkpoint_saver
    if system is None or saver is None:
        raise HTTPException(status_code=503, detail="Agent system not available")

    session_id = message.session_id or uuid.uuid4().hex
    pinned_added = False
    try:
        async with admission_lock:
            for expired_id in await sessions.expired_ids():
                if pinned.get(expired_id, 0) > 0:
                    continue
                await saver.adelete_thread(expired_id)
                await sessions.drop(expired_id)

            pinned[session_id] = pinned.get(session_id, 0) + 1
            pinned_added = True

            if not await sessions.is_live(session_id) and len(sessions) >= sessions.max_size:
                victim = await sessions.lru_victim(pinned)
                if victim is None:
                    raise HTTPException(
                        status_code=503,
                        detail="Сервер перегружен, повторите позже",
                    )
                await saver.adelete_thread(victim)
                await sessions.drop(victim)

            await sessions.touch(session_id)

        result = await system.process_user_request(
            message.message,
            session_id=session_id,
        )
        return ChatResponse(
            success=result["success"],
            session_id=session_id,
            mode=result["mode"],
            data=result.get("data"),
            query_info=result["query_info"],
            message=result["message"],
            timestamp=result["timestamp"],
            error=result.get("error"),
            reasoning=result.get("reasoning"),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise _internal_error(e)
    finally:
        if pinned_added:
            remaining_pins = pinned[session_id] - 1
            if remaining_pins > 0:
                pinned[session_id] = remaining_pins
            else:
                del pinned[session_id]


class QuestionMessage(Protocol):
    """What the whitelist reads off a stored user message."""

    content: object


class AnswerMessage(Protocol):
    """A stored model message: its content plus the tool calls it may carry."""

    content: object
    tool_calls: Sequence[object]


def _is_question(message: object) -> TypeGuard[QuestionMessage]:
    """The message classes arrive through importlib, so narrow them explicitly."""
    return isinstance(message, langchain_messages.HumanMessage)


def _is_answer(message: object) -> TypeGuard[AnswerMessage]:
    return isinstance(message, langchain_messages.AIMessage)


def _history_entries(stored_messages: Sequence[object]) -> list[dict[str, str | None]]:
    """Whitelist the chat turns a client may replay from a checkpoint.

    Tool calls and their results stay internal; only the user's questions and
    the final answers are served. Reasoning accumulates across the AI messages
    of a turn and rides on that turn's final answer.
    """
    entries: list[dict[str, str | None]] = []
    turn: list[object] = []
    for stored_message in stored_messages:
        if _is_question(stored_message):
            turn = []
            entries.append(
                {"role": "user", "content": extract_text(stored_message.content)}
            )
        elif _is_answer(stored_message):
            turn.append(stored_message)
            if stored_message.content and not stored_message.tool_calls:
                entries.append(
                    {
                        "role": "assistant",
                        "content": extract_text(stored_message.content),
                        "reasoning": extract_reasoning(turn),
                    }
                )

    return entries


@app.get("/api/history/{session_id}")
async def get_history(session_id: str):
    """
    Get conversation history for a session.

    Args:
        session_id: Session identifier

    Returns:
        Conversation history
    """
    saver = checkpoint_saver
    if saver is None:
        raise HTTPException(status_code=503, detail="Checkpoint store not available")

    async with admission_lock:
        if not await sessions.is_live(session_id):
            await saver.adelete_thread(session_id)
            await sessions.drop(session_id)
            return {"history": []}

        await sessions.touch(session_id)
        checkpoint_tuple = await saver.aget_tuple(
            {"configurable": {"thread_id": session_id}}
        )

    history = []
    if checkpoint_tuple is not None:
        history = _history_entries(
            checkpoint_tuple.checkpoint.get("channel_values", {}).get("messages", [])
        )

    return {"session_id": session_id, "history": history}


@app.post("/api/clear/{session_id}")
async def clear_history(session_id: str):
    """
    Clear conversation history for a session.

    Args:
        session_id: Session identifier
    """
    saver = checkpoint_saver
    if saver is None:
        raise HTTPException(status_code=503, detail="Checkpoint store not available")

    async with admission_lock:
        await saver.adelete_thread(session_id)
        await sessions.drop(session_id)

    return {
        "success": True,
        "message": f"History cleared for session {session_id}"
    }


@app.get("/api/games")
async def get_games(limit: Optional[int] = None):
    """
    Get all games summary.

    Args:
        limit: Optional limit on number of results

    Returns:
        Games summary
    """
    if not data_service:
        raise HTTPException(status_code=503, detail="Data service not available")

    try:
        df = data_service.get_all_games_summary()
        if limit:
            df = df.head(limit)
        return {
            "success": True,
            "data": df.to_dict(orient='records'),
            "count": len(df)
        }
    except Exception as e:
        raise _internal_error(e)


@app.get("/api/games/{game_id}")
async def get_game(game_id: int):
    """
    Get specific game data.

    Args:
        game_id: Game ID

    Returns:
        Game data
    """
    if not data_service:
        raise HTTPException(status_code=503, detail="Data service not available")

    try:
        data = data_service.get_game_by_id(game_id)
        if not data:
            raise HTTPException(status_code=404, detail=f"Game {game_id} not found")

        return {
            "success": True,
            "data": data
        }
    except HTTPException:
        raise
    except Exception as e:
        raise _internal_error(e)


@app.get("/api/teams")
async def get_teams():
    """
    Get all teams.

    Returns:
        All teams
    """
    if not data_service:
        raise HTTPException(status_code=503, detail="Data service not available")

    try:
        df = data_service.get_all_teams()
        return {
            "success": True,
            "data": df.to_dict(orient='records'),
            "count": len(df)
        }
    except Exception as e:
        raise _internal_error(e)


@app.get("/api/teams/{team_name}/stats")
async def get_team_stats(team_name: str):
    """
    Get statistics for a specific team.

    Args:
        team_name: Team name

    Returns:
        Team statistics
    """
    if not data_service:
        raise HTTPException(status_code=503, detail="Data service not available")

    try:
        stats = data_service.get_team_statistics(team_name)
        return {
            "success": True,
            "data": stats
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise _internal_error(e)


@app.get("/api/scores")
async def get_scores(game_id: Optional[int] = None):
    """
    Get team game scores.

    Args:
        game_id: Optional game ID filter

    Returns:
        Team scores
    """
    if not data_service:
        raise HTTPException(status_code=503, detail="Data service not available")

    try:
        df = data_service.get_team_game_scores(game_id)
        return {
            "success": True,
            "data": df.to_dict(orient='records'),
            "count": len(df)
        }
    except Exception as e:
        raise _internal_error(e)
