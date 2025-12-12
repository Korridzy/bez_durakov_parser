"""
AutoGen-based agent system for generating reports.
Uses AutoGen framework to orchestrate agent conversations.
"""
import os
import sys
from typing import Dict, List, Any, Optional
import json
from datetime import datetime, date

# No need to add path, services is in same app
from services.game_data_service import GameDataService

try:
    import autogen
    from autogen import AssistantAgent, UserProxyAgent, ConversableAgent
except ImportError:
    print("Warning: autogen not installed. Install with: pip install pyautogen")
    autogen = None


class ReportAgentSystem:
    """Agent system for generating data reports using AutoGen."""

    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize the agent system.

        Args:
            api_key: OpenAI API key (optional, can use env var OPENAI_API_KEY)
        """
        self.service = GameDataService()
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.conversation_history = []

        if autogen and self.api_key:
            self._setup_agents()
        else:
            self.agents_available = False
            print("Agents not available. Using fallback mode.")

    def _setup_agents(self):
        """Setup AutoGen agents."""

        llm_config = {
            "config_list": [{
                "model": "gpt-4",
                "api_key": self.api_key
            }],
            "timeout": 120,
            "temperature": 0.7,
        }

        # Coder agent - responsible for generating data queries
        self.coder_agent = AssistantAgent(
            name="DataCoder",
            llm_config=llm_config,
            system_message="""You are a data analyst coder. Your job is to:
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

When user asks for a report, respond with a JSON object containing:
{
    "method": "method_name",
    "params": {...},
    "description": "what this query does"
}

Be concise and only use existing methods. Do not write new code."""
        )

        # Analyst agent - responsible for interpreting results
        self.analyst_agent = AssistantAgent(
            name="DataAnalyst",
            llm_config=llm_config,
            system_message="""You are a data analyst. Your job is to:
1. Review the data retrieved by the coder
2. Provide insights and interpretations
3. Format results in a user-friendly way

Present your analysis in a clear, structured format.
Use tables, lists, and summaries as appropriate."""
        )

        # User proxy - manages the conversation
        self.user_proxy = UserProxyAgent(
            name="User",
            human_input_mode="NEVER",
            max_consecutive_auto_reply=10,
            code_execution_config=False,
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
            self.conversation_history.append({
                "role": "user",
                "content": user_message,
                "timestamp": datetime.now().isoformat()
            })

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
                "message": f"Report generated based on: {user_message}"
            }

            # Store response in history
            self.conversation_history.append({
                "role": "assistant",
                "content": response,
                "timestamp": datetime.now().isoformat()
            })

            return response

        except Exception as e:
            error_response = {
                "success": False,
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            }
            self.conversation_history.append({
                "role": "assistant",
                "content": error_response,
                "timestamp": datetime.now().isoformat()
            })
            return error_response

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
                "description": "Get summary of all games"
            }

        elif "топ команд" in message_lower or "top teams" in message_lower:
            return {
                "method": "get_top_teams",
                "params": {"limit": 10},
                "description": "Get top 10 teams by total points"
            }

        elif "команда" in message_lower or "team" in message_lower:
            # Extract team name (simplified)
            words = user_message.split()
            team_name = words[-1] if words else ""
            return {
                "method": "get_team_statistics",
                "params": {"team_name": team_name},
                "description": f"Get statistics for team {team_name}"
            }

        elif "очки" in message_lower or "scores" in message_lower:
            return {
                "method": "get_team_game_scores",
                "params": {},
                "description": "Get all team game scores"
            }

        else:
            # Default: show all games
            return {
                "method": "get_all_games_summary",
                "params": {},
                "description": "Get summary of all games"
            }

    def _execute_query(self, query_info: Dict[str, Any]) -> Any:
        """Execute the determined query."""
        method_name = query_info.get("method")
        params = query_info.get("params", {})

        # Map method names to service methods
        method_map = {
            "get_all_games_summary": self.service.get_all_games_summary,
            "get_game_by_id": self.service.get_game_by_id,
            "get_games_by_date_range": self.service.get_games_by_date_range,
            "get_team_game_scores": self.service.get_team_game_scores,
            "get_all_teams": self.service.get_all_teams,
            "get_team_statistics": self.service.get_team_statistics,
            "get_top_teams": self.service._get_top_teams,
        }

        method = method_map.get(method_name)
        if not method:
            raise ValueError(f"Unknown method: {method_name}")

        # Execute method with params
        result = method(**params)

        # Convert DataFrame to dict if needed
        if hasattr(result, 'to_dict'):
            return result.to_dict(orient='records')

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
                "mode": "fallback"
            }
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "timestamp": datetime.now().isoformat(),
                "mode": "fallback"
            }

    def get_conversation_history(self) -> List[Dict[str, Any]]:
        """Get conversation history."""
        return self.conversation_history

    def clear_history(self):
        """Clear conversation history."""
        self.conversation_history = []

