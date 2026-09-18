"""Metadata-only data-tool and GraphState contract cases."""
import importlib
import json
import typing
import unittest
from pathlib import Path

_support = importlib.import_module("test_agent_tools_support")
TOOL_NAMES = _support.TOOL_NAMES
TOOL_PARAMS = _support.TOOL_PARAMS
ToolsCaseBase = _support.ToolsCaseBase


class ToolMetadataTests(ToolsCaseBase):

    def test_graph_state_has_only_the_serializable_contract_fields(self):
        """Given GraphState, When hints are resolved, Then only serializable state fields exist."""
        hints = typing.get_type_hints(self.state_module.GraphState, include_extras=True)
        message_args = typing.get_args(hints["messages"])

        self.assertEqual(
            set(hints),
            {
                "messages",
                "report_payload",
                "rows_consumed",
                "knowledge_bytes_consumed",
            },
        )
        self.assertIs(typing.get_origin(hints["messages"]), typing.Annotated)
        self.assertIs(message_args[0], list)
        self.assertIs(message_args[1], self.graph.add_messages)
        self.assertEqual(hints["report_payload"], dict | None)
        self.assertIs(hints["rows_consumed"], int)
        self.assertIs(hints["knowledge_bytes_consumed"], int)
        json.dumps(
            {
                "messages": [],
                "report_payload": None,
                "rows_consumed": 0,
                "knowledge_bytes_consumed": 0,
            }
        )

    def test_build_tools_without_knowledge_keeps_current_catalogue(self):
        """Given no knowledge, When tools are built, Then the current ten-tool catalogue is unchanged."""
        built = self.tools_module.build_tools(self.registry, self.config)
        names = [tool.name for tool in built]
        expected = [*TOOL_NAMES, "read_rows", "mark_report"]

        self.assertEqual(names, expected)
        self.assertNotIn("read_knowledge", names)

    def test_build_tools_with_knowledge_puts_read_knowledge_first(self):
        """Given loaded knowledge, When tools are built, Then read_knowledge leads the unchanged catalogue."""
        knowledge_module = importlib.import_module("agent.knowledge")
        topic = knowledge_module.KnowledgeTopic(
            id="rules",
            title="Rules",
            summary="A summary.",
            text="# Rules\\n\\nA summary.\\n",
        )
        knowledge = knowledge_module.Knowledge(manifest=object(), topics=(topic,))

        built = self.tools_module.build_tools(self.registry, self.config, knowledge=knowledge)
        names = [tool.name for tool in built]
        expected_existing = [*TOOL_NAMES, "read_rows", "mark_report"]

        self.assertEqual(len(built), 11)
        self.assertEqual(names[0], "read_knowledge")
        self.assertEqual(names[1:], expected_existing)
        schema = built[0].tool_call_schema.model_json_schema()
        self.assertEqual(set(schema["properties"]), {"topic"})
        self.assertEqual(schema["properties"]["topic"]["type"], "string")
        self.assertEqual(schema["required"], ["topic"])

    def _build_knowledge_tools(self):
        knowledge_module = importlib.import_module("agent.knowledge")
        fixture_path = Path("/bd_shared/knowledge/bez_durakov")
        limits = knowledge_module.KnowledgeLimits(
            max_title_chars=80,
            max_summary_chars=200,
            max_persona_chars=2000,
            max_topics=50,
            max_doc_bytes=65536,
            max_bytes_per_turn=131072,
        )
        knowledge = knowledge_module.load_knowledge(fixture_path, "bez_durakov", limits)
        built = self.tools_module.build_tools(self.registry, self.config, knowledge=knowledge)
        self.tools = {tool.name: tool for tool in built}
        return fixture_path

    async def test_read_knowledge_returns_full_fixture_text_verbatim(self):
        """Given a known topic, When it is read, Then the complete file is returned unchanged."""
        fixture_path = self._build_knowledge_tools()

        state = await self.invoke_tool("read_knowledge", {"topic": "rules"})
        message = self.latest_tool_message(state)
        read_knowledge_content = message.content

        self.assertIsInstance(read_knowledge_content, str)
        self.assertEqual(read_knowledge_content, (fixture_path / "rules.md").read_text(encoding="utf-8"))
        self.assertEqual(state["rows_consumed"], 0)

    async def test_read_knowledge_unknown_id_returns_exact_tool_error(self):
        """Given an unknown topic, When it is read, Then an exact in-band error is returned."""
        self._build_knowledge_tools()
        topic = "missing"

        state = await self.invoke_tool("read_knowledge", {"topic": topic})
        message = self.latest_tool_message(state)

        self.assertEqual(
            message.content,
            "Tool error: unknown knowledge topic 'missing'. Available topics: glossary, rules, scoring",
        )
        self.assertEqual(state["rows_consumed"], 0)

    async def test_read_knowledge_empty_ids_keep_raw_value_in_exact_error(self):
        """Given empty topic ids, When they are read, Then each raw value is interpolated."""
        self._build_knowledge_tools()

        for topic in ("", "   "):
            with self.subTest(topic=topic):
                state = await self.invoke_tool("read_knowledge", {"topic": topic})
                message = self.latest_tool_message(state)
                expected = (
                    f"Tool error: unknown knowledge topic '{topic}'. "
                    "Available topics: glossary, rules, scoring"
                )

                self.assertEqual(message.content, expected)
                self.assertEqual(state["rows_consumed"], 0)

    async def test_read_knowledge_ids_are_case_sensitive(self):
        """Given a correctly spelled id with different case, When read, Then it is unknown."""
        self._build_knowledge_tools()
        topic = "Rules"

        state = await self.invoke_tool("read_knowledge", {"topic": topic})
        message = self.latest_tool_message(state)

        self.assertEqual(
            message.content,
            "Tool error: unknown knowledge topic 'Rules'. Available topics: glossary, rules, scoring",
        )
        self.assertEqual(state["rows_consumed"], 0)

    def test_data_tool_schemas_match_registry_parameters(self):
        """Given data tools, When schemas are inspected, Then all eight inputs remain typed."""
        for name, expected in TOOL_PARAMS.items():
            with self.subTest(tool=name):
                schema = self.tools[name].args_schema.model_json_schema()
                self.assertEqual(tuple(schema["properties"]), expected)

        date_properties = self.tools["get_games_by_date_range"].args_schema.model_json_schema()[
            "properties"
        ]
        self.assertEqual(date_properties["start_date"]["type"], "string")
        self.assertIn("string", json.dumps(date_properties["end_date"]))
        read_properties = self.tools["read_rows"].tool_call_schema.model_json_schema()["properties"]
        mark_properties = self.tools["mark_report"].tool_call_schema.model_json_schema()["properties"]
        self.assertEqual(set(read_properties), {"handle", "offset", "limit"})
        self.assertEqual(set(mark_properties), {"handle"})

    def test_generated_descriptions_are_the_docstring_summary_plus_the_envelope_note(self):
        """Given discovered tools, When descriptions are read, Then each is a summary plus the envelope note.

        This is the only guard on the prompt's quality: without it the descriptions could
        silently degrade into whatever the service docstrings happen to say about DataFrames.
        """
        toolmodule = importlib.import_module("agent.toolmodule")
        expected_summaries = {
            "get_all_games_summary": "Get summary of all games.",
            "get_all_teams": "Get all teams.",
            "get_game_by_id": "Get full game data by ID.",
            "get_games_by_date_range": "Get game IDs within an inclusive date range.",
            "get_team_game_scores": "Get team game scores, optionally for one game.",
            "get_team_statistics": "Get statistics for a specific team.",
            "get_team_wins": "Get games won by a specific team.",
            "get_top_teams": "Get top teams by total points.",
        }

        self.assertEqual(set(expected_summaries), set(TOOL_NAMES))
        for name, summary in expected_summaries.items():
            with self.subTest(tool=name):
                self.assertEqual(
                    self.tools[name].description,
                    f"{summary}\n{toolmodule.ENVELOPE_NOTE}",
                )

    def test_generated_schemas_preserve_defaults_and_requiredness(self):
        """Given a defaulted parameter, When the schema is generated, Then the default survives."""
        top_teams = self.tools["get_top_teams"].args_schema.model_json_schema()
        statistics = self.tools["get_team_statistics"].args_schema.model_json_schema()
        wins = self.tools["get_team_wins"].args_schema.model_json_schema()

        self.assertEqual(top_teams["properties"]["limit"]["default"], 10)
        self.assertNotIn("required", top_teams)
        self.assertEqual(statistics["required"], ["team_name"])
        self.assertEqual(wins["required"], ["team_name"])
        self.assertIsNone(wins["properties"]["year"]["default"])

    async def test_handle_arguments_stay_json_primitives(self):
        """Given a date argument, When the envelope comes back, Then every handle value is a primitive."""
        self.service.results["get_games_by_date_range"] = [3, 4]

        state = await self.invoke_tool(
            "get_games_by_date_range",
            {"start_date": "2025-01-01", "end_date": "2025-12-31"},
        )
        handle = self.latest_json(state)["handle"]

        for key, value in handle["args"].items():
            with self.subTest(argument=key):
                self.assertIsInstance(value, (str, int, float, bool, type(None)))
        self.assertEqual(handle["args"]["start_date"], "2025-01-01")

    async def test_all_data_tools_return_metadata_without_records(self):
        """Given all service result shapes, When data tools run, Then only metadata is exposed."""
        rows = self.pd.DataFrame([{"game_id": 1}, {"game_id": 2}])
        self.service.results.update(
            {
                "get_all_games_summary": rows,
                "get_game_by_id": {"game_id": 7},
                "get_games_by_date_range": [3, 4],
                "get_team_game_scores": rows,
                "get_all_teams": self.pd.DataFrame(
                    [{"team_id": 1, "team_name": "A"}, {"team_id": 2, "team_name": "B"}]
                ),
                "get_team_statistics": {"team_name": "A", "games_played": 2},
                "get_team_wins": {"team_name": "A", "wins": []},
                "get_top_teams": self.pd.DataFrame([{"team_name": "A"}]),
            }
        )
        args_by_name = {
            "get_all_games_summary": {},
            "get_game_by_id": {"game_id": 7},
            "get_games_by_date_range": {
                "start_date": "2025-01-01",
                "end_date": "2025-12-31",
            },
            "get_team_game_scores": {"game_id": None},
            "get_all_teams": {},
            "get_team_statistics": {"team_name": "A"},
            "get_team_wins": {"team_name": "A", "year": 2025},
            "get_top_teams": {"limit": 1},
        }
        expected_rows = {
            "get_all_games_summary": 2,
            "get_game_by_id": 1,
            "get_games_by_date_range": 2,
            "get_team_game_scores": 2,
            "get_all_teams": 2,
            "get_team_statistics": 1,
            "get_team_wins": 1,
            "get_top_teams": 1,
        }

        for name in TOOL_NAMES:
            with self.subTest(tool=name):
                state = await self.invoke_tool(name, args_by_name[name])
                payload = self.latest_json(state)

                self.assertEqual(set(payload), {"handle", "rows", "cols", "summary"})
                self.assertEqual(payload["handle"], {"tool": name, "args": args_by_name[name]})
                self.assertEqual(payload["rows"], expected_rows[name])
                self.assertIsInstance(payload["cols"], list)
                self.assertIsInstance(payload["summary"], str)
                self.assertNotIn("records", payload)
                self.assertNotIn("data", payload)

    async def test_data_tool_maps_service_domain_error_to_tool_error_text(self):
        """Given a service ValueError, When a data tool runs, Then no exception escapes."""
        self.service.raises["get_team_statistics"] = ValueError("Team Ghost not found")

        state = await self.invoke_tool(
            "get_team_statistics",
            {"team_name": "Ghost"},
        )
        content = self.latest_tool_message(state).content

        self.assertIsInstance(content, str)
        self.assertIn("tool error", content.lower())
        self.assertIn("Team Ghost not found", content)

    async def test_malformed_data_tool_arguments_become_tool_message_error(self):
        """Given a required argument is absent, When ToolNode runs, Then validation stays in-band."""
        state = await self.invoke_tool("get_team_statistics", {})
        message = self.latest_tool_message(state)

        self.assertIsInstance(message.content, str)
        self.assertIn("error", message.content.lower())
        self.assertEqual(message.status, "error")


if __name__ == "__main__":
    unittest.main()
