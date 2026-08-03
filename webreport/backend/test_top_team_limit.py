from __future__ import annotations

import importlib
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, "/")

from services.game_data_service import GameDataService

_checkpoint = importlib.import_module("langgraph.checkpoint.sqlite.aio")
_report_agents = importlib.import_module("agents.report_agents")


class TopTeamLimitTest(unittest.IsolatedAsyncioTestCase):
    async def test_fallback_clamps_requested_top_team_limit(self) -> None:
        service = object.__new__(GameDataService)
        limits: list[int] = []

        def record_limit(limit: int = 10) -> list[object]:
            limits.append(limit)
            return []

        async with _checkpoint.AsyncSqliteSaver.from_conn_string(":memory:") as saver:
            system = _report_agents.ReportAgentSystem(
                service=service,
                mode="fallback",
                checkpointer=saver,
            )
            self.assertEqual(system.mode, "fallback")

            with patch.object(GameDataService, "get_top_teams", side_effect=record_limit):
                oversized_response = await system.process_user_request(
                    "топ 1000000 команд", "oversized-limit"
                )
                zero_response = await system.process_user_request(
                    "топ 0 команд", "zero-limit"
                )

            self.assertTrue(oversized_response["success"])
            self.assertTrue(zero_response["success"])
        self.assertEqual([1024, 1], limits)

    async def test_fallback_skips_int_for_oversized_top_team_limit(self) -> None:
        service = object.__new__(GameDataService)
        limits: list[int] = []

        def record_limit(limit: int = 10) -> list[object]:
            limits.append(limit)
            return []

        oversized_limit = "9" * 10_000

        async with _checkpoint.AsyncSqliteSaver.from_conn_string(":memory:") as saver:
            system = _report_agents.ReportAgentSystem(
                service=service,
                mode="fallback",
                checkpointer=saver,
            )
            self.assertEqual(system.mode, "fallback")

            with (
                patch.object(GameDataService, "get_top_teams", side_effect=record_limit),
                patch(
                    "agents.report_agents.int",
                    side_effect=AssertionError("oversized limits must not be parsed"),
                    create=True,
                ),
            ):
                response = await system.process_user_request(
                    f"топ {oversized_limit} команд", "unparsed-limit"
                )

            self.assertTrue(response["success"])
        self.assertEqual([1024], limits)


if __name__ == "__main__":
    _ = unittest.main()
