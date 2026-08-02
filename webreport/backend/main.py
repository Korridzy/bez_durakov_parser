"""
FastAPI backend for the web reporting system.
Provides REST API for chat and report generation.
"""
from typing import Dict, Any, Optional
from datetime import datetime
import asyncio
import logging
import uuid
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

import sys

sys.path.insert(0, '/')

from bd_shared.config import CHECKPOINT_TTL_SECONDS, WEBREPORT_ALLOWED_ORIGINS, WEBREPORT_DEBUG

logger = logging.getLogger(__name__)

from agents.report_agents import ReportAgentSystem
from services.game_data_service import GameDataService
from session_store import SessionIndex


# Pydantic models for request/response
class ChatMessage(BaseModel):
    """Chat message model."""
    message: str = Field(..., description="User's message/requirement for report")
    session_id: Optional[str] = Field(None, description="Session ID for conversation tracking")


class ChatResponse(BaseModel):
    """Chat response model."""
    success: bool
    session_id: str
    data: Optional[Any] = None
    query_info: Optional[Dict[str, Any]] = None
    message: str
    timestamp: str
    error: Optional[str] = None


class ReportData(BaseModel):
    """Report data model."""
    report_id: str
    data: Any
    generated_at: str
    query: Dict[str, Any]


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
data_service: Optional[GameDataService] = None
sessions: SessionIndex = SessionIndex(ttl=CHECKPOINT_TTL_SECONDS)

STARTUP_RETRY_ATTEMPTS = 5
STARTUP_RETRY_DELAY_SECONDS = 2


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


@app.on_event("startup")
async def startup_event():
    """Initialize services on startup."""
    global agent_system, data_service

    data_service = await initialize_data_service_with_retry()

    agent_system = ReportAgentSystem(service=data_service)

    logger.info("Services initialized successfully")


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


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    if data_service is None:
        raise HTTPException(status_code=503, detail="Data service not available")

    return {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "services": {
            "database": data_service is not None,
            "agents": agent_system is not None
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
    if not agent_system:
        raise HTTPException(status_code=503, detail="Agent system not available")

    try:
        # Anonymous callers each get a fresh session so they never share
        # conversation history or agent state with other clients.
        session_id = message.session_id or uuid.uuid4().hex
        if session_id not in sessions:
            sessions[session_id] = ReportAgentSystem(service=data_service)

        session_agent = sessions[session_id]

        # Process the request
        result = session_agent.process_user_request(message.message)

        if result.get("success"):
            return ChatResponse(
                success=True,
                session_id=session_id,
                data=result.get("data"),
                query_info=result.get("query"),
                message=result.get("message", "Report generated successfully"),
                timestamp=result.get("timestamp", datetime.now().isoformat())
            )
        else:
            return ChatResponse(
                success=False,
                session_id=session_id,
                message="Failed to generate report",
                error=result.get("error", "Unknown error"),
                timestamp=result.get("timestamp", datetime.now().isoformat())
            )

    except Exception as e:
        raise _internal_error(e)


@app.get("/api/history/{session_id}")
async def get_history(session_id: str):
    """
    Get conversation history for a session.

    Args:
        session_id: Session identifier

    Returns:
        Conversation history
    """
    if session_id not in sessions:
        return {"history": []}

    return {
        "session_id": session_id,
        "history": sessions[session_id].get_conversation_history()
    }


@app.post("/api/clear/{session_id}")
async def clear_history(session_id: str):
    """
    Clear conversation history for a session.

    Args:
        session_id: Session identifier
    """
    if session_id in sessions:
        sessions[session_id].clear_history()

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
