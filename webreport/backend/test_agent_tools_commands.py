"""Bounded read_rows and mark_report Command cases."""
import importlib
import unittest

ToolsCaseBase = importlib.import_module("test_agent_tools_support").ToolsCaseBase


class ToolCommandTests(ToolsCaseBase):

    @staticmethod
    def scores_handle():
        return {"tool": "get_team_game_scores", "args": {"game_id": None}}

    async def test_read_rows_honors_offset_limit_and_tool_call_id(self):
        """Given rows, When a page is read, Then the slice and Command metadata match."""
        self.set_rows(30)

        state = await self.invoke_tool(
            "read_rows",
            {"handle": self.scores_handle(), "offset": 10, "limit": 5},
            call_id="read-5",
        )
        payload = self.latest_json(state)

        self.assertEqual([row["game_id"] for row in payload["records"]], [10, 11, 12, 13, 14])
        self.assertEqual(payload["returned"], 5)
        self.assertFalse(payload["budget_limited"])
        self.assertEqual(state["rows_consumed"], 5)
        self.assertEqual(self.latest_tool_message(state).tool_call_id, "read-5")

    async def test_read_rows_caps_one_fetch_at_256(self):
        """Given an oversized limit, When rows are read, Then the configured per-fetch cap wins."""
        self.set_rows(400)

        state = await self.invoke_tool(
            "read_rows",
            {"handle": self.scores_handle(), "offset": 0, "limit": 999},
        )
        payload = self.latest_json(state)

        self.assertEqual(payload["returned"], 256)
        self.assertEqual(len(payload["records"]), 256)
        self.assertEqual(state["rows_consumed"], 256)

    async def test_read_rows_returns_only_remaining_run_budget(self):
        """Given 24 rows remain, When 256 are requested, Then exactly 24 return and explain why."""
        self.set_rows(400)
        prior = {"messages": [], "report_payload": None, "rows_consumed": 1000}

        state = await self.invoke_tool(
            "read_rows",
            {"handle": self.scores_handle(), "offset": 0, "limit": 256},
            state=prior,
        )
        payload = self.latest_json(state)

        self.assertEqual(payload["returned"], 24)
        self.assertEqual(len(payload["records"]), 24)
        self.assertTrue(payload["budget_limited"])
        self.assertEqual(state["rows_consumed"], 1024)

    async def test_read_rows_exhausted_budget_returns_error_without_mutation(self):
        """Given the run budget is exhausted, When rows are requested, Then execution continues."""
        self.set_rows(10)
        prior = {"messages": [], "report_payload": None, "rows_consumed": 1024}

        state = await self.invoke_tool(
            "read_rows",
            {"handle": self.scores_handle(), "offset": 0, "limit": 1},
            state=prior,
        )
        content = self.latest_tool_message(state).content

        self.assertIsInstance(content, str)
        self.assertIn("tool error", content.lower())
        self.assertIn("1024", content)
        self.assertEqual(state["rows_consumed"], 1024)

    async def test_read_rows_rejects_stale_budget_state(self):
        """Given stale state exceeds the cap, When rows are requested, Then it fails closed."""
        self.set_rows(10)
        prior = {"messages": [], "report_payload": None, "rows_consumed": 1025}

        state = await self.invoke_tool(
            "read_rows",
            {"handle": self.scores_handle(), "offset": 0, "limit": 1},
            state=prior,
        )
        content = self.latest_tool_message(state).content

        self.assertIsInstance(content, str)
        self.assertIn("tool error", content.lower())
        self.assertIn("outside", content.lower())
        self.assertEqual(state["rows_consumed"], 1025)

    async def test_read_rows_rejects_invalid_ranges_as_tool_errors(self):
        """Given invalid page bounds, When read_rows runs, Then neither error escapes."""
        self.set_rows(10)
        cases = ((-1, 1), (0, 0))

        for offset, limit in cases:
            with self.subTest(offset=offset, limit=limit):
                state = await self.invoke_tool(
                    "read_rows",
                    {"handle": self.scores_handle(), "offset": offset, "limit": limit},
                )
                content = self.latest_tool_message(state).content
                self.assertIsInstance(content, str)
                self.assertIn("tool error", content.lower())
                self.assertEqual(state["rows_consumed"], 0)

    async def test_read_rows_maps_forged_handle_and_domain_error_to_text(self):
        """Given bad handles, When read_rows runs, Then both failures stay inside the tool lane."""
        cases = (
            ({"tool": "bogus", "args": {}}, None),
            ({"tool": "get_team_statistics", "args": {"team_name": "Ghost"}}, ValueError(
                "Team Ghost not found"
            )),
        )

        for handle, error in cases:
            with self.subTest(tool=handle["tool"]):
                if error is not None:
                    self.service.raises["get_team_statistics"] = error
                state = await self.invoke_tool(
                    "read_rows",
                    {"handle": handle, "offset": 0, "limit": 1},
                )
                content = self.latest_tool_message(state).content
                self.assertIsInstance(content, str)
                self.assertIn("tool error", content.lower())

    async def test_sequential_reads_observe_same_turn_budget_updates(self):
        """Given 124 rows remain, When two reads run serially, Then the second sees the first."""
        self.set_rows(300)
        prior = {"messages": [], "report_payload": None, "rows_consumed": 900}

        first = await self.invoke_tool(
            "read_rows",
            {"handle": self.scores_handle(), "offset": 0, "limit": 100},
            state=prior,
            call_id="read-first",
        )
        second = await self.invoke_tool(
            "read_rows",
            {"handle": self.scores_handle(), "offset": 100, "limit": 100},
            state=first,
            call_id="read-second",
        )
        payload = self.latest_json(second)

        self.assertEqual(first["rows_consumed"], 1000)
        self.assertEqual(payload["returned"], 24)
        self.assertTrue(payload["budget_limited"])
        self.assertEqual(second["rows_consumed"], 1024)
        self.assertEqual(self.latest_tool_message(second).tool_call_id, "read-second")

    async def test_mark_report_validates_and_records_handle_with_matching_message(self):
        """Given a valid handle, When marked, Then one Command records it and answers its call."""
        self.set_rows(1)
        handle = self.scores_handle()

        state = await self.invoke_tool(
            "mark_report",
            {"handle": handle},
            call_id="mark-1",
        )

        self.assertEqual(state["report_payload"], handle)
        self.assertEqual(state["rows_consumed"], 0)
        self.assertEqual(self.latest_tool_message(state).tool_call_id, "mark-1")

    async def test_mark_report_rejects_forged_handle_without_state_change(self):
        """Given a forged handle, When marked, Then a tool error leaves report state empty."""
        state = await self.invoke_tool(
            "mark_report",
            {"handle": {"tool": "bogus", "args": {}}},
        )
        content = self.latest_tool_message(state).content

        self.assertIsInstance(content, str)
        self.assertIn("tool error", content.lower())
        self.assertIsNone(state["report_payload"])

    async def test_state_tools_reject_malformed_handle_without_exception(self):
        """Given a handle misses args, When state tools run, Then both return in-band errors."""
        for name in ("read_rows", "mark_report"):
            with self.subTest(tool=name):
                if name == "read_rows":
                    state = await self.invoke_tool(
                        name,
                        {
                            "handle": {"tool": "get_all_teams"},
                            "offset": 0,
                            "limit": 1,
                        },
                    )
                else:
                    state = await self.invoke_tool(
                        name,
                        {"handle": {"tool": "get_all_teams"}},
                    )
                content = self.latest_tool_message(state).content
                self.assertIsInstance(content, str)
                self.assertIn("error", content.lower())
                self.assertEqual(state["rows_consumed"], 0)
                self.assertIsNone(state["report_payload"])


if __name__ == "__main__":
    unittest.main()
