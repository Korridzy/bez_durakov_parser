import re
from dataclasses import dataclass
from typing import Any, Dict, Final, Optional, final

from .report_contracts import QueryPlan
from .report_runtime import ReportAgentSystem as ReportAgentSystem, parse_legacy_query

_MIN_TOP_TEAMS_LIMIT: Final = 1
_MAX_TOP_TEAMS_LIMIT: Final = 1024


@final
@dataclass(frozen=True, slots=True)
class FallbackInterpreter:
    def interpret(self, user_message: str) -> QueryPlan:
        if "очки" in user_message.lower() or "scores" in user_message.lower():
            return {
                "method": "get_team_game_scores",
                "params": {},
                "description": "Get all team game scores",
            }
        legacy_query: object = self._interpret_request(user_message)
        return parse_legacy_query(legacy_query)

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
            requested_limit_text = (top_teams_match.group(1) or "10").lstrip("0") or "0"
            requested_limit = (
                _MAX_TOP_TEAMS_LIMIT
                if len(requested_limit_text) > len(str(_MAX_TOP_TEAMS_LIMIT))
                else int(requested_limit_text)
            )
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
