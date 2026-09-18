"""End-to-end proof that the backend serves whatever database the operator configures.

One file, executed twice by `make -C webreport test`: once against a SQLite file and once
against the throwaway PostgreSQL in docker-compose.test.yml. Each run seeds the fixture
through a separate writable engine, starts the real backend over the real generated tools
with a scripted model, asserts the answer through /api/chat, asserts the dataset check, and
asserts that a write is refused twice so the second attempt lands on a reset pooled
connection.

This module must not import test_system: importing it drives a full startup at import time,
under the acceptance config, before any patch exists.
"""

import asyncio
import importlib
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import fastapi
from sqlalchemy import create_engine, text

# Parent of the mounted bd_shared directory, same convention as main.py.
sys.path.insert(0, "/")

import acceptance_fixture  # noqa: E402

_config = importlib.import_module("bd_shared.config")
_net_guard = importlib.import_module("test_net_guard")
_graph_cases = importlib.import_module("test_agent_graph")
_messages = importlib.import_module("langchain_core.messages")

ScriptedModel = _graph_cases.ScriptedModel
tool_call = _graph_cases.tool_call

STATION_HANDLE = {"tool": "station_total", "args": {"station": "north"}}
ANSWER = "Сумма по станции north равна 60."
REFUSAL_PREFIX = "Tool error: Tool 'insert_reading' failed:"

# Every data call the script makes, validated against the schema the running system built
# before the run, because ScriptedModel never validates a tool call itself.
SCRIPTED_DATA_CALLS = (
    ("station_total", {"station": "north"}),
    ("insert_reading", {"station": "north", "value": 99}),
)


class _ProbeResponse:
    """A healthy LiteLLM probe response. Defined locally so test_system stays unimported."""

    status_code = 200

    @staticmethod
    def json():
        return {"healthy_endpoints": [{"model": "fixture"}], "unhealthy_endpoints": []}


def setUpModule():
    """Offline lane: only loopback and the configured database host are reachable."""
    _net_guard.install()


def _script():
    """One answering turn, then two turns that each attempt a refused write."""
    insert_args = {"station": "north", "value": 99}
    return [
        _messages.AIMessage(
            content="", tool_calls=[tool_call("station_total", {"station": "north"}, "d1")]
        ),
        _messages.AIMessage(
            content="", tool_calls=[tool_call("mark_report", {"handle": STATION_HANDLE}, "m1")]
        ),
        _messages.AIMessage(content=ANSWER),
        _messages.AIMessage(
            content="", tool_calls=[tool_call("insert_reading", insert_args, "w1")]
        ),
        _messages.AIMessage(content="Запись отклонена."),
        _messages.AIMessage(
            content="", tool_calls=[tool_call("insert_reading", insert_args, "w2")]
        ),
        _messages.AIMessage(content="Запись отклонена снова."),
    ]


class AcceptanceSwapTests(unittest.TestCase):
    """The whole dialect promise, asserted on whichever database the config names."""

    @classmethod
    def setUpClass(cls):
        cls.main = importlib.import_module("main")
        cls.runtime = importlib.import_module("agents.report_runtime")

        database_url = str(_config.DATABASE_URL)
        if database_url.startswith("sqlite"):
            # The read-only file URI refuses to open a file whose directory is missing.
            Path("/tmp/bd-acceptance").mkdir(parents=True, exist_ok=True)

        # Principle 2's one written-down exception: seeding needs a writable engine, and
        # using a separate one is what proves the refusal comes from the enforcement
        # mechanism rather than from account permissions.
        cls.seeding_engine = create_engine(database_url)
        acceptance_fixture.create_schema(cls.seeding_engine)
        acceptance_fixture.seed(cls.seeding_engine)

    @classmethod
    def tearDownClass(cls):
        cls.seeding_engine.dispose()

    def _row_count(self):
        with self.seeding_engine.connect() as connection:
            return connection.execute(text("SELECT COUNT(*) FROM station_readings")).scalar()

    def _tool_error_messages(self, model):
        return [
            message.content
            for request in model.requests
            for message in request
            if isinstance(message, _messages.ToolMessage)
            and str(message.content).startswith("Tool error:")
        ]

    def test_the_configured_database_is_served_end_to_end(self):
        """Given a configured database, When the backend serves a turn, Then it answers from it."""
        main = self.main
        model = ScriptedModel(_script())
        built_tools = []
        real_build_tools = self.runtime.build_tools
        real_system = main.ReportAgentSystem

        def capture_tools(*args, **kwargs):
            tools = real_build_tools(*args, **kwargs)
            built_tools.extend(tools)
            return tools

        def scripted_system(**kwargs):
            return real_system(model_client=model, **kwargs)

        async def run():
            with (
                patch.object(main.requests, "get", return_value=_ProbeResponse),
                patch.object(self.runtime, "build_tools", side_effect=capture_tools),
                patch.object(main, "ReportAgentSystem", side_effect=scripted_system),
            ):
                await main.startup_event()
                try:
                    tools_by_name = {tool.name: tool for tool in built_tools}
                    for name, args in SCRIPTED_DATA_CALLS:
                        with self.subTest(scripted_call=name):
                            tools_by_name[name].args_schema.model_validate(args)

                    answered = await main.chat(
                        main.ChatMessage(message="Сумма по станции north", session_id="a1"),
                        fastapi.Response(),
                    )
                    first_write = await main.chat(
                        main.ChatMessage(message="Добавь запись", session_id="a2"),
                        fastapi.Response(),
                    )
                    second_write = await main.chat(
                        main.ChatMessage(message="Добавь запись ещё раз", session_id="a3"),
                        fastapi.Response(),
                    )
                finally:
                    await main.shutdown_event()
            return answered, first_write, second_write

        answered, first_write, second_write = asyncio.run(run())

        self.assertTrue(answered.success, answered.error)
        self.assertEqual(answered.message, ANSWER)
        self.assertEqual(answered.data, {"station": "north", "total": 60})
        self.assertEqual(
            answered.query_info,
            [
                {"tool": "station_total", "args": {"station": "north"}},
                {"tool": "mark_report", "args": {"handle": STATION_HANDLE}},
            ],
        )

        # The dataset check: the knowledge folder and the derived database name agree.
        self.assertIsNotNone(main.knowledge)
        self.assertEqual(main.knowledge.manifest.dataset, "fixture")
        self.assertEqual(_config.DATABASE_NAME, "fixture")

        # The refused write, twice, so the second attempt lands on a pooled connection that
        # has been returned and reset. This is the assertion that catches a mechanism which
        # reverts on check-in.
        refusals = self._tool_error_messages(model)
        self.assertEqual(len(refusals), 2, refusals)
        for index, refusal in enumerate(refusals):
            with self.subTest(attempt=index):
                self.assertTrue(refusal.startswith(REFUSAL_PREFIX), refusal)
        self.assertTrue(first_write.success)
        self.assertTrue(second_write.success)
        self.assertEqual(self._row_count(), 5)


if __name__ == "__main__":
    unittest.main()
