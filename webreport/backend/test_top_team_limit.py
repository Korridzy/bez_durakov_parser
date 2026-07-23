from __future__ import annotations

import unittest
from unittest.mock import patch

from agents.report_agents import ReportAgentSystem
from services.game_data_service import GameDataService


class TopTeamLimitTest(unittest.TestCase):
    def test_fallback_clamps_requested_top_team_limit(self) -> None:
        service = object.__new__(GameDataService)
        limits: list[int] = []

        def record_limit(limit: int = 10) -> list[object]:
            limits.append(limit)
            return []

        system = ReportAgentSystem(service=service)
        system.agents_available = False

        with patch.object(GameDataService, "get_top_teams", side_effect=record_limit):
            oversized_response = system.process_user_request("топ 1000000 команд")
            zero_response = system.process_user_request("топ 0 команд")

        self.assertTrue(oversized_response["success"])
        self.assertTrue(zero_response["success"])
        self.assertEqual([1024, 1], limits)

    def test_fallback_skips_int_for_oversized_top_team_limit(self) -> None:
        service = object.__new__(GameDataService)
        limits: list[int] = []

        def record_limit(limit: int = 10) -> list[object]:
            limits.append(limit)
            return []

        system = ReportAgentSystem(service=service)
        system.agents_available = False
        oversized_limit = "9" * 10_000

        with (
            patch.object(GameDataService, "get_top_teams", side_effect=record_limit),
            patch(
                "agents.report_agents.int",
                side_effect=AssertionError("oversized limits must not be parsed"),
                create=True,
            ),
        ):
            response = system.process_user_request(f"топ {oversized_limit} команд")

        self.assertTrue(response["success"])
        self.assertEqual([1024], limits)


if __name__ == "__main__":
    _ = unittest.main()
