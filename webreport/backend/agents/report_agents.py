"""
AutoGen-based agent system for generating reports.
Uses AutoGen framework to orchestrate agent conversations.
"""

import os
import sys
import importlib
import logging
import re
from datetime import datetime, date
import json
from textwrap import dedent
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)
_MIN_TOP_TEAMS_LIMIT = 1
_MAX_TOP_TEAMS_LIMIT = 1024

# No need to add path, services is in same app
from services.game_data_service import GameDataService

try:
    _agents_module = importlib.import_module("autogen_agentchat.agents")
    AssistantAgent = getattr(_agents_module, "AssistantAgent")
    UserProxyAgent = getattr(_agents_module, "UserProxyAgent")
    agentchat_available = True
except ImportError:
    AssistantAgent = None
    UserProxyAgent = None
    agentchat_available = False

try:
    _openai_module = importlib.import_module("autogen_ext.models.openai")
    OpenAIChatCompletionClient = getattr(_openai_module, "OpenAIChatCompletionClient")
    openai_client_available = True
except ImportError:
    OpenAIChatCompletionClient = None
    openai_client_available = False


class ReportAgentSystem:
    """Agent system for generating data reports using AutoGen."""

    def __init__(self, api_key: Optional[str] = None, service: Optional[GameDataService] = None):
        self.service = service or GameDataService()
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.conversation_history = []
        self.model_client = None
        self.coder_agent = None
        self.analyst_agent = None
        self.user_proxy = None

        if agentchat_available and self.api_key:
            try:
                self._setup_agents()
            except Exception:
                self.agents_available = False
                logger.warning("Agent setup failed; using fallback mode", exc_info=True)
        else:
            self.agents_available = False
            logger.info("Agents unavailable; using fallback mode")

    def _setup_agents(self):
        """Setup AutoGen agents."""

        assistant_agent_cls = AssistantAgent
        user_proxy_agent_cls = UserProxyAgent
        model_client_cls = OpenAIChatCompletionClient

        if not openai_client_available or model_client_cls is None:
            raise RuntimeError(
                "AutoGen AgentChat is installed, but OpenAI model client is unavailable"
            )
        if assistant_agent_cls is None or user_proxy_agent_cls is None:
            raise RuntimeError("AutoGen AgentChat agents are unavailable")

        self.model_client = model_client_cls(
            model="gpt-4o",
            api_key=self.api_key,
            temperature=0.7,
        )

        # Coder agent - responsible for generating data queries
        self.coder_agent = assistant_agent_cls(
            name="DataCoder",
            model_client=self.model_client,
            system_message=dedent(
                """\
                You are a data analyst coder. Your job is to:
                1. Understand user requirements for data reports
                2. Use ONLY the available service methods to retrieve data
                3. Return structured data queries

                Available methods:
                - get_all_games_summary(): Get all games summary
                - get_game_by_id(game_id): Get specific game data
                - get_games_by_date_range(start_date, end_date): Get games in date range
                - get_team_game_scores(game_id=None): Get team scores
                - get_all_teams(): Get all teams
                - get_team_statistics(team_name): Get statistics for a team
                - get_team_wins(team_name, year=None): Get games won by a team (optionally filtered by year)
                - get_top_teams(limit=10): Get top teams by total points

                When user asks for a report, respond with a JSON object containing:
                {
                    "method": "method_name",
                    "params": {...},
                    "description": "what this query does"
                }

                Be concise and only use existing methods. Do not write new code."""
            ),
        )

        # Analyst agent - responsible for interpreting results
        self.analyst_agent = assistant_agent_cls(
            name="DataAnalyst",
            model_client=self.model_client,
            system_message=dedent(
                """\
                You are a data analyst. Your job is to:
                1. Review the data retrieved by the coder
                2. Provide insights and interpretations
                3. Format results in a user-friendly way

                Present your analysis in a clear, structured format.
                Use tables, lists, and summaries as appropriate."""
            ),
        )

        # User proxy - manages the conversation
        self.user_proxy = user_proxy_agent_cls(
            name="User",
            description="System user proxy for non-interactive chat flow",
        )

        self.agents_available = True

    def process_user_request(self, user_message: str) -> Dict[str, Any]:
        """
        Process user request and generate report.

        Args:
            user_message: User's request for a report

        Returns:
            Dictionary with report data and metadata
        """
        if not self.agents_available:
            return self._fallback_process(user_message)

        try:
            # Store user message in history
            self.conversation_history.append(
                {
                    "role": "user",
                    "content": user_message,
                    "timestamp": datetime.now().isoformat(),
                }
            )

            # Parse the request to determine what data is needed
            query_info = self._interpret_request(user_message)

            # Execute the query
            data = self._execute_query(query_info)

            # Format the response
            response = {
                "success": True,
                "query": query_info,
                "data": data,
                "timestamp": datetime.now().isoformat(),
                "message": f"Report generated based on: {user_message}",
            }

            # Store response in history
            self.conversation_history.append(
                {
                    "role": "assistant",
                    "content": response,
                    "timestamp": datetime.now().isoformat(),
                }
            )

            return response

        except Exception as e:
            error_response = {
                "success": False,
                "error": str(e),
                "timestamp": datetime.now().isoformat(),
            }
            self.conversation_history.append(
                {
                    "role": "assistant",
                    "content": error_response,
                    "timestamp": datetime.now().isoformat(),
                }
            )
            return error_response

    def _extract_team_name_from_prompt(self, user_message: str) -> str:
        """
        Extract full team name from a prompt containing 'команда' or 'team' keyword.
        Preserves multi-word team names (e.g., 'Однажды было дважды').

        Returns the text following the keyword, trimmed of leading/trailing whitespace.
        Preserves original casing from the input message.
        """
        import re

        message_lower = user_message.lower()

        # Try Russian 'команда' (nominative/genitive/other forms: команда, команды, etc.)
        # Match text after keyword until end of string or until date pattern
        match = re.search(
            r"команд[ауы]?\s+(.+?)(?:\s+(?:за|в)\s+\d{4}\s+|$)",
            message_lower,
        )
        if match:
            # Extract the same text from the original message to preserve case
            start_idx = match.start(1)
            end_idx = match.end(1)
            team_part = user_message[start_idx:end_idx].strip()
            if team_part:
                return team_part

        # Fallback: try English 'team'
        match = re.search(r"team\s+(.+?)(?:\s+for\s+|$)", message_lower)
        if match:
            # Extract the same text from the original message to preserve case
            start_idx = match.start(1)
            end_idx = match.end(1)
            team_part = user_message[start_idx:end_idx].strip()
            if team_part:
                return team_part

        # Last resort: take last word (original fallback, preserves case)
        words = user_message.split()
        return words[-1] if words else ""

    def _extract_year_from_prompt(self, user_message: str) -> Optional[int]:
        """
        Extract year from win-query style prompts.
        Targets patterns like 'за 2025 год', 'в 2025 году', or standalone year near 'год'.

        Returns year as integer, or None if not found.
        """
        import re

        message_lower = user_message.lower()

        # Pattern: 'за YYYY год' or 'в YYYY году'
        match = re.search(r"(?:за|в)\s+(\d{4})\s+(?:год|году)", message_lower)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                pass

        # Pattern: standalone 'YYYY год' without preposition
        match = re.search(r"(\d{4})\s+год", message_lower)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                pass

        return None

    def _interpret_request(self, user_message: str) -> Dict[str, Any]:
        """
        Interpret user request and determine what data to fetch.
        This is a simplified version - in production, you'd use LLM.
        """
        message_lower = user_message.lower()

        # Pattern matching for common requests
        if "все игры" in message_lower or "all games" in message_lower:
            return {
                "method": "get_all_games_summary",
                "params": {},
                "description": "Get summary of all games",
            }

        elif top_teams_match := re.search(r"топ\s*(\d+)?\s+команд", message_lower):
            requested_limit = int(top_teams_match.group(1) or 10)
            return {
                "method": "get_top_teams",
                "params": {
                    "limit": min(
                        _MAX_TOP_TEAMS_LIMIT,
                        max(_MIN_TOP_TEAMS_LIMIT, requested_limit),
                    )
                },
                "description": "Get top teams by total points",
            }

        elif "top teams" in message_lower:
            return {
                "method": "get_top_teams",
                "params": {"limit": 10},
                "description": "Get top teams by total points",
            }

        elif any(
            kw in message_lower
            for kw in (
                "побеждала",
                "победила",
                "побеждал",
                "победил",
                "побед ",
                "побед.",
                "побед,",
                "побед?",
                "wins",
                "won",
            )
        ):
            # Win-oriented prompt — route to get_team_wins
            team_name = self._extract_team_name_from_prompt(user_message)
            year = self._extract_year_from_prompt(user_message)
            params: Dict[str, Any] = {"team_name": team_name}
            if year is not None:
                params["year"] = year
            return {
                "method": "get_team_wins",
                "params": params,
                "description": f"Get wins for team {team_name}"
                + (f" in {year}" if year else ""),
            }

        elif "команд" in message_lower or "team" in message_lower:
            # Generic team statistics (multi-word name preserved)
            team_name = self._extract_team_name_from_prompt(user_message)
            year = self._extract_year_from_prompt(user_message)

            return {
                "method": "get_team_statistics",
                "params": {"team_name": team_name},
                "description": f"Get statistics for team {team_name}",
                "year": year,  # Stored for potential future use
            }

        elif "очки" in message_lower or "scores" in message_lower:
            return {
                "method": "get_team_game_scores",
                "params": {},
                "description": "Get all team game scores",
            }

        else:
            # Default: show all games
            return {
                "method": "get_all_games_summary",
                "params": {},
                "description": "Get summary of all games",
            }

    def _execute_query(self, query_info: Dict[str, Any]) -> Any:
        """Execute the determined query."""
        method_name = query_info.get("method")
        if not isinstance(method_name, str):
            raise ValueError(f"Invalid method name: {method_name}")
        params = query_info.get("params", {})

        # Map method names to service methods
        method_map = {
            "get_all_games_summary": self.service.get_all_games_summary,
            "get_game_by_id": self.service.get_game_by_id,
            "get_games_by_date_range": self.service.get_games_by_date_range,
            "get_team_game_scores": self.service.get_team_game_scores,
            "get_all_teams": self.service.get_all_teams,
            "get_team_statistics": self.service.get_team_statistics,
            "get_team_wins": self.service.get_team_wins,
            "get_top_teams": self.service.get_top_teams,
        }

        method = method_map.get(method_name)
        if not method:
            raise ValueError(f"Unknown method: {method_name}")

        # Execute method with params
        result = method(**params)

        # Convert DataFrame to dict if needed
        if isinstance(result, (dict, list)) or result is None:
            return result

        to_dict_method = getattr(result, "to_dict", None)
        if callable(to_dict_method):
            return to_dict_method(orient="records")

        return result

    def _fallback_process(self, user_message: str) -> Dict[str, Any]:
        """Fallback processing when AutoGen is not available."""
        query_info = self._interpret_request(user_message)

        try:
            data = self._execute_query(query_info)
            return {
                "success": True,
                "query": query_info,
                "data": data,
                "timestamp": datetime.now().isoformat(),
                "message": f"Report generated (fallback mode): {user_message}",
                "mode": "fallback",
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "timestamp": datetime.now().isoformat(),
                "mode": "fallback",
            }

    def get_conversation_history(self) -> List[Dict[str, Any]]:
        """Get conversation history."""
        return self.conversation_history

    def clear_history(self):
        """Clear conversation history."""
        self.conversation_history = []
