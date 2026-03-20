"""
FastAPI backend for the web reporting system.
Provides REST API for chat and report generation.
"""
from typing import Dict, Any, Optional
from datetime import datetime
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


from agents.report_agents import ReportAgentSystem
from services.game_data_service import GameDataService


# Pydantic models for request/response
class ChatMessage(BaseModel):
    """Chat message model."""
    message: str = Field(..., description="User's message/requirement for report")
    session_id: Optional[str] = Field(None, description="Session ID for conversation tracking")


class ChatResponse(BaseModel):
    """Chat response model."""
    success: bool
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
    allow_origins=["*"],  # In production, specify actual origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global instances
agent_system: Optional[ReportAgentSystem] = None
data_service: Optional[GameDataService] = None
sessions: Dict[str, ReportAgentSystem] = {}


@app.on_event("startup")
async def startup_event():
    """Initialize services on startup."""
    global agent_system, data_service
    try:
        data_service = GameDataService()
        agent_system = ReportAgentSystem()
        print("✅ Services initialized successfully")
    except Exception as e:
        print(f"❌ Error initializing services: {e}")


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
        # Get or create session
        session_id = message.session_id or "default"
        if session_id not in sessions:
            sessions[session_id] = ReportAgentSystem()

        session_agent = sessions[session_id]

        # Process the request
        result = session_agent.process_user_request(message.message)

        if result.get("success"):
            return ChatResponse(
                success=True,
                data=result.get("data"),
                query_info=result.get("query"),
                message=result.get("message", "Report generated successfully"),
                timestamp=result.get("timestamp", datetime.now().isoformat())
            )
        else:
            return ChatResponse(
                success=False,
                message="Failed to generate report",
                error=result.get("error", "Unknown error"),
                timestamp=result.get("timestamp", datetime.now().isoformat())
            )

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
        raise HTTPException(status_code=500, detail=str(e))


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
        raise HTTPException(status_code=500, detail=str(e))


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
        raise HTTPException(status_code=500, detail=str(e))


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
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
        raise HTTPException(status_code=500, detail=str(e))
