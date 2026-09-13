"""
Test script for the web reporting system.
Tests all components: services, agents, API.
"""
import sys
import asyncio
import importlib
import json as json_module
import os
import tempfile
from pathlib import Path
from typing import Any

import unittest
from unittest.mock import AsyncMock, call, patch

import fastapi

_test_agent_support = importlib.import_module("test_agent_support")
_test_agent_graph = importlib.import_module("test_agent_graph")
_test_net_guard = importlib.import_module("test_net_guard")
StubService = _test_agent_support.StubService
ScriptedStub = _test_agent_graph.ScriptedModel
_tool_call = _test_agent_graph.tool_call

# Import the app and set up in-process ASGI testing
testclient = None
try:
    from main import app
    from io import BytesIO
    
    class ASGITestClient:
        """In-process ASGI test client that directly calls the FastAPI app."""
        
        def __init__(self, app_instance):
            self.app = app_instance
            self.loop = asyncio.new_event_loop()
            self._closed = False
            try:
                self._previous_loop = asyncio.get_event_loop()
            except RuntimeError:
                self._previous_loop = None
            asyncio.set_event_loop(self.loop)
            # Trigger startup events
            self._run_startup()
        
        def _run_startup(self):
            """Run all startup event handlers."""
            async def startup():
                for handler in self.app.router.on_startup:
                    if asyncio.iscoroutinefunction(handler):
                        await handler()
                    else:
                        handler()
            
            self.loop.run_until_complete(startup())

        def close(self):
            if self._closed:
                return

            async def shutdown():
                for handler in self.app.router.on_shutdown:
                    if asyncio.iscoroutinefunction(handler):
                        await handler()
                    else:
                        handler()

            try:
                self.loop.run_until_complete(shutdown())
            finally:
                asyncio.set_event_loop(self._previous_loop)
                self.loop.close()
                self._closed = True
        
        def _call(self, method, path, json_data=None):
            """Make a synchronous call to the ASGI app."""
            
            # Build ASGI scope
            scope: dict[str, Any] = {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": method,
                "scheme": "http",
                "path": path,
                "query_string": b"",
                "root_path": "",
                "headers": [],
                "server": ("testserver", 80),
                "client": ("127.0.0.1", 8000),
                "state": {},
            }
            
            # Add JSON content-type if needed
            if json_data is not None:
                body = json_module.dumps(json_data).encode("utf-8")
                scope["headers"].append((b"content-type", b"application/json"))
            else:
                body = b""
            
            # Create receive and send callables
            body_sent = False
            response_started = False
            response_status = None
            response_headers = []
            response_body = BytesIO()
            
            async def receive():
                nonlocal body_sent
                if not body_sent:
                    body_sent = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return {"type": "http.disconnect"}
            
            async def send(message):
                nonlocal response_started, response_status, response_headers
                if message["type"] == "http.response.start":
                    response_started = True
                    response_status = message["status"]
                    response_headers = message.get("headers", [])
                elif message["type"] == "http.response.body":
                    response_body.write(message.get("body", b""))
            
            # Call the app
            self.loop.run_until_complete(self.app(scope, receive, send))
            
            # Create a response-like object
            class Response:
                def __init__(self, status, headers, body):
                    self.status_code = status
                    self.headers = {k.decode(): v.decode() for k, v in headers}
                    self._body = body.getvalue()
                
                def json(self):
                    return json_module.loads(self._body.decode())
            
            return Response(response_status, response_headers, response_body)
        
        def get(self, path):
            """Make a GET request."""
            return self._call("GET", path)
        
        def post(self, path, json=None):
            """Make a POST request with optional JSON body."""
            return self._call("POST", path, json_data=json)
    
    startup_free_test_classes = (
        "test_system.TestReportAgentSystem",
        "test_system.TestSessionLifecycleAPI",
        "test_system.TestStartupInitialization",
    )
    if any(argument.startswith(startup_free_test_classes) for argument in sys.argv):
        testclient = None
    else:
        startup_service = StubService()
        startup_engine = importlib.import_module("sqlalchemy").create_engine("sqlite://")
        startup_specs = importlib.import_module("agent.toolmodule").discover(startup_service)
        # The seam is the whole startup helper, not the service class: patching it bypasses
        # the connection check entirely, which the lane runs with a stopped database.
        # The probe returns True so /health still answers 200 and the agent is built over
        # the stub; ChatLiteLLM constructs without connecting, so this stays offline.
        with patch(
            "main.initialize_tool_service_with_retry",
            new=AsyncMock(return_value=(startup_engine, startup_service, startup_specs)),
        ), patch("main.probe_llm_proxy", new=AsyncMock(return_value=True)):
            # One loop owns startup, the saver, all synchronous calls, and shutdown.
            testclient = ASGITestClient(app)
except Exception as e:
    import traceback

    print(f"⚠️ Warning: Could not initialize in-process test client: {e}")
    traceback.print_exc()
    testclient = None


def setUpModule():
    """Offline suite: only loopback and the Compose database host are reachable."""
    _test_net_guard.install()


class TestGameDataService(unittest.TestCase):
    """Test the default tool module against the MySQL test database.

    Set BD_REQUIRE_MYSQL to turn an unreachable database from a class-wide skip into a
    failure, which is what makes this class a usable gate rather than a silent pass.
    """

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        try:
            from bd_shared.config import DATABASE_URL
            from bd_shared.tools.bez_durakov import build_service

            from agent.engine import build_read_only_engine

            service = build_service(build_read_only_engine(DATABASE_URL))
            # SQLAlchemy connects lazily, so without this probe an unreachable
            # database leaves every sibling's "Service not available" skip dead.
            with service.db.engine.connect():
                pass
            cls.service = service
        except Exception as e:
            if os.environ.get("BD_REQUIRE_MYSQL"):
                raise
            print(f"⚠️ Warning: Could not initialize the default tool module: {e}")
            cls.service = None

    def test_service_initialization(self):
        """Test that service initializes correctly."""
        if self.service is None:
            self.skipTest("Service not available")

        self.assertIsNotNone(self.service.db, "Initialized service should own a database handle")

    def test_write_is_refused_on_mysql(self):
        """Given the injected engine, When a write runs, Then MySQL refuses it.

        The statement is never committed, so a mechanism that failed would leave nothing
        behind; the assertion is on the refusal itself.
        """
        if self.service is None:
            self.skipTest("Service not available")

        sqlalchemy = importlib.import_module("sqlalchemy")

        with self.service.db.engine.connect() as connection:
            self.assertEqual(
                connection.execute(
                    sqlalchemy.text("SELECT @@session.transaction_read_only")
                ).scalar(),
                1,
            )
            with self.assertRaises(Exception) as caught:
                connection.execute(
                    sqlalchemy.text("INSERT INTO teams (team_name) VALUES ('bd-readonly-probe')")
                )

        self.assertIn("read only transaction", str(caught.exception).lower())
        print("✅ MySQL refuses a write through the injected engine")

    def test_get_all_games_summary(self):
        """Test getting all games summary."""
        if self.service is None:
            self.skipTest("Service not available")

        try:
            pandas_module = __import__("pandas")
        except ImportError:
            self.skipTest("pandas not available")

        df = self.service.get_all_games_summary()
        self.assertIsInstance(df, pandas_module.DataFrame, "Should return DataFrame")
        print(f"✅ Found {len(df)} games in database")

    def test_get_all_teams(self):
        """Test getting all teams."""
        if self.service is None:
            self.skipTest("Service not available")

        try:
            pandas_module = __import__("pandas")
        except ImportError:
            self.skipTest("pandas not available")

        df = self.service.get_all_teams()
        self.assertIsInstance(df, pandas_module.DataFrame, "Should return DataFrame")
        print(f"✅ Found {len(df)} teams in database")

    def test_get_team_game_scores(self):
        """Test getting team game scores."""
        if self.service is None:
            self.skipTest("Service not available")

        try:
            pandas_module = __import__("pandas")
        except ImportError:
            self.skipTest("pandas not available")

        df = self.service.get_team_game_scores()
        self.assertIsInstance(df, pandas_module.DataFrame, "Should return DataFrame")
        print(f"✅ Found {len(df)} team game score records")

    def test_regression_get_team_game_scores_filters_zero_game_id(self):
        if self.service is None:
            self.skipTest("Service not available")

        with patch.object(self.service.db, "get_team_game_scores", return_value=[]) as mock_method:
            df = self.service.get_team_game_scores(0)

            mock_method.assert_called_once_with(game_id=0)
            self.assertTrue(df.empty, "Filtered zero game_id query should still return a DataFrame")

        print("✅ Service get_team_game_scores: game_id=0 still applies filtering")

    def test_regression_service_get_game_by_id_returns_none_for_missing_game(self):
        if self.service is None:
            self.skipTest("Service not available")

        with patch.object(self.service.db, "get_game_data", side_effect=ValueError("missing")):
            self.assertIsNone(self.service.get_game_by_id(999999))

        print("✅ Service get_game_by_id: missing game returns None")

    def test_regression_service_get_game_by_id_reraises_unexpected_errors(self):
        if self.service is None:
            self.skipTest("Service not available")

        with patch.object(self.service.db, "get_game_data", side_effect=RuntimeError("db exploded")):
            with self.assertRaises(RuntimeError):
                _ = self.service.get_game_by_id(123)

        print("✅ Service get_game_by_id: unexpected errors are re-raised")

    def test_regression_service_get_team_wins(self):
        """Regression test for get_team_wins() service method.
        
        Tests the underlying service method that powers the win-prompt routing.
        Ensures no 'No module named db' import errors occur at service level.
        """
        if self.service is None:
            self.skipTest("Service not available")

        # Test get_team_wins without year
        result = self.service.get_team_wins("однажды было дважды")
        
        # Verify response structure
        self.assertIsInstance(result, dict, "Should return dictionary")
        self.assertIn("team_name", result, "Result should have team_name")
        self.assertIn("wins_count", result, "Result should have wins_count")
        self.assertIn("games_played", result, "Result should have games_played")
        self.assertIn("wins", result, "Result should have wins list")
        
        # Verify no error strings in result
        result_str = str(result)
        self.assertNotIn("No module named 'db'", result_str,
                        "Result should not contain import error")
        
        print(f"✅ Service get_team_wins: {result['wins_count']} wins in {result['games_played']} games")

    def test_regression_service_get_team_wins_with_year(self):
        """Regression test for get_team_wins() with year parameter.
        
        Tests that year filtering works correctly in the service method.
        """
        if self.service is None:
            self.skipTest("Service not available")

        # Test get_team_wins with year=2025
        result = self.service.get_team_wins("однажды было дважды", year=2025)
        
        # Verify response structure
        self.assertIsInstance(result, dict, "Should return dictionary")
        self.assertEqual(result.get("year"), 2025, "Year should be set to 2025")
        self.assertIn("wins_count", result, "Result should have wins_count")
        
        # Verify no error strings in result
        result_str = str(result)
        self.assertNotIn("No module named 'db'", result_str,
                        "Result should not contain import error")
        
        print(f"✅ Service get_team_wins(year=2025): {result['wins_count']} wins")

    def test_regression_service_get_team_statistics(self):
        """Regression test for get_team_statistics() service method.
        
        Tests the underlying service method for generic team stats.
        Ensures no 'No module named db' import errors occur.
        """
        if self.service is None:
            self.skipTest("Service not available")

        result = self.service.get_team_statistics("однажды было дважды")
        
        # Verify response structure
        self.assertIsInstance(result, dict, "Should return dictionary")
        self.assertIn("team_name", result, "Result should have team_name")
        
        # Verify no error strings in result
        result_str = str(result)
        self.assertNotIn("No module named 'db'", result_str,
                        "Result should not contain import error")

        print("✅ Service get_team_statistics executed successfully")

    def test_regression_service_get_team_statistics_reraises_missing_team(self):
        if self.service is None:
            self.skipTest("Service not available")

        with patch.object(self.service.db, "get_team_by_name", return_value=None) as mock_lookup:
            with self.assertRaises(ValueError):
                self.service.get_team_statistics("missing team")

            mock_lookup.assert_called_once_with("missing team")

        print("✅ Service get_team_statistics: missing team is re-raised")


class TestReportAgentSystem(unittest.IsolatedAsyncioTestCase):
    """The report system on the only path it now has, driven by a scripted model.

    The service-level assertions are unchanged: which tool a request reaches, what the
    answer says, that the turn is checkpointed and that a raising service surfaces as a
    failure envelope. What changed is that a scripted model chooses the tool, where the
    deleted regex interpreter used to.
    """

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        cls.checkpoint = importlib.import_module("langgraph.checkpoint.sqlite.aio")
        cls.messages = importlib.import_module("langchain_core.messages")
        cls.report_module = importlib.import_module("agents.report_runtime")

    def _script(self, calls, answer):
        """One scripted turn: the listed tool calls, then a final answer."""
        scripted = [
            self.messages.AIMessage(
                content="",
                tool_calls=[_tool_call(name, args, f"call-{index}")],
            )
            for index, (name, args) in enumerate(calls)
        ]
        scripted.append(self.messages.AIMessage(content=answer))
        return ScriptedStub(scripted)

    async def test_agent_initialization(self):
        """Test that agent system initializes."""
        async with self.checkpoint.AsyncSqliteSaver.from_conn_string(":memory:") as saver:
            agent_system = self.report_module.ReportAgentSystem(
                service=StubService(),
                model_client=ScriptedStub([]),
                checkpointer=saver,
            )

            self.assertIsNotNone(agent_system, "Agent system should be initialized")

    async def test_regression_agents_enabled_with_api_key(self):
        scripted_message = "Отчёт готов: покажи все игры"
        model_client = ScriptedStub(
            [self.messages.AIMessage(content=scripted_message)]
        )
        async with self.checkpoint.AsyncSqliteSaver.from_conn_string(":memory:") as saver:
            enabled_system = self.report_module.ReportAgentSystem(
                service=StubService(),
                model_client=model_client,
                checkpointer=saver,
            )

            response = await enabled_system.process_user_request(
                "покажи все игры", "enabled-mode"
            )
            self.assertIsInstance(response, dict, "Response should be a dictionary")
            self.assertTrue(response.get("success"), "The request should succeed")
            self.assertEqual(response["message"], scripted_message)

            checkpoint_tuple = await saver.aget_tuple(
                {"configurable": {"thread_id": "enabled-mode"}}
            )
            self.assertIsNotNone(checkpoint_tuple)
            if checkpoint_tuple is None:
                self.fail("A turn must checkpoint its conversation")
            history = checkpoint_tuple.checkpoint["channel_values"]["messages"]
            self.assertIsInstance(history, list, "History should be a list")
            self.assertGreaterEqual(
                len(history), 2,
                "A turn should record at least user+assistant history entries",
            )

    async def test_regression_agent_system_uses_injected_service(self):
        injected_service = StubService()
        async with self.checkpoint.AsyncSqliteSaver.from_conn_string(":memory:") as saver:
            system = self.report_module.ReportAgentSystem(
                service=injected_service,
                model_client=ScriptedStub([]),
                checkpointer=saver,
            )

            self.assertIs(system.service, injected_service)
        print("✅ Agent system reuses injected data service")

    async def test_process_request_all_games(self):
        """Test processing a request that reaches the all-games tool."""
        service = StubService()
        service.results["get_all_games_summary"] = [{"game_id": 1}]
        async with self.checkpoint.AsyncSqliteSaver.from_conn_string(":memory:") as saver:
            agent_system = self.report_module.ReportAgentSystem(
                service=service,
                model_client=self._script(
                    [("get_all_games_summary", {})], "Все игры перечислены."
                ),
                checkpointer=saver,
            )

            response = await agent_system.process_user_request(
                "покажи все игры", "all-games"
            )
            self.assertIsInstance(response, dict, "Should return dictionary")
            self.assertIn("success", response, "Response should have success field")
            self.assertTrue(response["success"])
            # The docstring claims the all-games tool is reached, so assert that rather than
            # only that the turn succeeded.
            self.assertEqual(response["query_info"][0]["tool"], "get_all_games_summary")
        print(f"✅ Request processed: {response.get('message', 'No message')}")

    async def test_conversation_history(self):
        """Test conversation history tracking."""
        async with self.checkpoint.AsyncSqliteSaver.from_conn_string(":memory:") as saver:
            agent_system = self.report_module.ReportAgentSystem(
                service=StubService(),
                model_client=ScriptedStub([self.messages.AIMessage(content="Готово.")]),
                checkpointer=saver,
            )
            config = {"configurable": {"thread_id": "history"}}
            self.assertIsNone(await saver.aget_tuple(config))

            await agent_system.process_user_request("тест", "history")
            checkpoint_tuple = await saver.aget_tuple(config)
            self.assertIsNotNone(checkpoint_tuple)
            if checkpoint_tuple is None:
                self.fail("A turn must checkpoint its conversation")
            history = checkpoint_tuple.checkpoint["channel_values"]["messages"]
            self.assertIsInstance(history, list, "History should be a list")
            self.assertGreaterEqual(len(history), 2)
        print(f"✅ Conversation history has {len(history)} entries")

    async def test_regression_team_wins_2025(self):
        """Keep the win-route assertion on list-shaped ``query_info``.

        Previously failed with: 'No module named db' import error. The tool the turn
        reaches is now chosen by the scripted model rather than by a regex router, but the
        assertion that the trace records get_team_wins is unchanged.
        """
        service = StubService()
        service.results["get_team_wins"] = {"team_name": "Однажды было дважды", "wins": []}
        async with self.checkpoint.AsyncSqliteSaver.from_conn_string(":memory:") as saver:
            agent_system = self.report_module.ReportAgentSystem(
                service=service,
                model_client=self._script(
                    [("get_team_wins", {"team_name": "Однажды было дважды", "year": 2025})],
                    "Победы за 2025 год перечислены.",
                ),
                checkpointer=saver,
            )
            user_prompt = "Сделай отчёт о том, в каких играх за 2025 год побеждала команда Однажды было дважды"
            response = await agent_system.process_user_request(user_prompt, "team-wins")

            self.assertIsInstance(response, dict, "Should return dictionary")
            self.assertIn("success", response, "Response should have success field")
            self.assertTrue(response["success"])
            self.assertNotIn(
                "No module named 'db'",
                str(response),
                "Response should not contain import error 'No module named db'",
            )
            self.assertEqual(response["query_info"][0]["tool"], "get_team_wins")
        print("✅ Team wins 2025 prompt: correctly routed to get_team_wins")

    async def test_regression_generic_team_statistics(self):
        """Keep the team-statistics route assertion on list-shaped ``query_info``."""
        service = StubService()
        service.results["get_team_statistics"] = {
            "team_name": "Однажды было дважды",
            "games_played": 3,
        }
        async with self.checkpoint.AsyncSqliteSaver.from_conn_string(":memory:") as saver:
            agent_system = self.report_module.ReportAgentSystem(
                service=service,
                model_client=self._script(
                    [("get_team_statistics", {"team_name": "Однажды было дважды"})],
                    "Статистика собрана.",
                ),
                checkpointer=saver,
            )
            user_prompt = "статистика команды Однажды было дважды"
            response = await agent_system.process_user_request(
                user_prompt, "team-statistics"
            )

            self.assertIsInstance(response, dict, "Should return dictionary")
            self.assertIn("success", response, "Response should have success field")
            self.assertTrue(response["success"])
            self.assertNotIn(
                "No module named 'db'",
                str(response),
                "Response should not contain import error 'No module named db'",
            )
            self.assertEqual(
                response["query_info"][0]["tool"], "get_team_statistics"
            )
        print("✅ Generic team statistics prompt: correctly routed to get_team_statistics")

    async def test_regression_team_statistics_missing_team_returns_error_response(self):
        service = StubService()
        # The marked handle is re-executed to build the report payload, and it is that
        # second call that fails here, so the raising service surfaces as a failure
        # envelope rather than as an in-band tool message.
        missing_team = patch.object(
            service,
            "get_team_statistics",
            side_effect=[
                {"team_name": "missing team", "games_played": 0},
                ValueError("Team missing team not found"),
            ],
        )
        async with self.checkpoint.AsyncSqliteSaver.from_conn_string(":memory:") as saver:
            agent_system = self.report_module.ReportAgentSystem(
                service=service,
                model_client=ScriptedStub(
                    [
                        self.messages.AIMessage(
                            content="",
                            tool_calls=[
                                _tool_call(
                                    "mark_report",
                                    {
                                        "handle": {
                                            "tool": "get_team_statistics",
                                            "args": {"team_name": "missing team"},
                                        }
                                    },
                                    "mark-1",
                                )
                            ],
                        ),
                        self.messages.AIMessage(content="Команда не найдена."),
                    ]
                ),
                checkpointer=saver,
            )

            with missing_team:
                response = await agent_system.process_user_request(
                    "статистика команды missing team", "missing-team"
                )

            self.assertFalse(
                response.get("success"),
                "Missing team should not look like a successful report",
            )
            self.assertIn("not found", response.get("error", "").lower())
        print("✅ Agent team statistics: missing team returns error response")


class TestAPI(unittest.TestCase):
    """Test the FastAPI endpoints."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures.

        A missing client is a failure, not a skip: this family carries the only proof that
        the surviving routes are the ones the plan leaves behind, and eleven silent skips
        would keep the lane green while proving nothing.
        """
        if testclient is None:
            raise RuntimeError(
                "The in-process test client failed to build; see the module-level traceback above"
            )
        cls.client = testclient

    def setUp(self):
        main_module = importlib.import_module("main")
        session_store = importlib.import_module("session_store")

        setattr(
            main_module,
            "sessions",
            session_store.SessionIndex(
                max_size=session_store.MAX_SESSIONS,
                ttl=getattr(main_module, "CHECKPOINT_TTL_SECONDS"),
            ),
        )
        setattr(main_module, "pinned", {})
        setattr(main_module, "admission_lock", asyncio.Lock())

    @classmethod
    def tearDownClass(cls):
        if cls.client is not None:
            cls.client.close()
            cls.client = None

    def test_health_endpoint(self):
        """Test the health check endpoint."""
        response = self.client.get("/health")

        self.assertEqual(response.status_code, 200, "Health check should return 200")
        data = response.json()
        self.assertIn("status", data, "Should have status field")
        print(f"✅ API health check passed: {data.get('status')}")

    def test_openapi_lists_legacy_and_workspace_paths(self):
        """Workspace routes extend the four legacy paths without restoring retired APIs."""
        main_module = importlib.import_module("main")

        self.assertEqual(
            sorted(main_module.app.openapi()["paths"]),
            sorted([
                "/api/chat",
                "/api/clear/{session_id}",
                "/api/history/{session_id}",
                "/health",
                "/api/workspace",
                "/api/projects",
                "/api/projects/{project_id}",
                "/api/projects/{project_id}/info",
                "/api/projects/{project_id}/sources",
                "/api/chats",
                "/api/chats/{chat_id}",
                "/api/chats/{chat_id}/analysis/{result_id}",
                "/api/chats/{chat_id}/project-interview",
                "/api/chats/{chat_id}/messages",
                "/api/sources/{source_id}",
                "/api/sources/{source_id}/reports/{report}",
                "/api/sources/{source_id}/explorer/catalog",
                "/api/sources/{source_id}/explorer/goals",
                "/api/sources/{source_id}/explorer",
                "/api/model-connections/discover",
                "/api/model-connections",
                "/api/model-connections/{model_id}",
                "/api/jobs/{job_id}",
                "/api/jobs/{job_id}/cancel",
            ]),
        )
        print("✅ API surface: legacy and workspace paths, no retired endpoints")

    def test_chat_refuses_with_503_when_no_model_is_reachable(self):
        """Given no reachable model, When chat is called through real routing, Then it answers 503."""
        main_module = importlib.import_module("main")

        with (
            patch.object(main_module, "agent_system", None),
            patch.object(main_module, "llm_proxy_healthy", False),
            patch.object(
                main_module,
                "probe_once",
                new=AsyncMock(return_value=("transient", None, None)),
            ),
        ):
            response = self.client.post("/api/chat", json={"message": "привет"})

        self.assertEqual(response.status_code, 503)
        body = response.json()
        self.assertFalse(body["success"])
        self.assertEqual(body["message"], "Для ответа нужна доступная языковая модель.")
        self.assertTrue(body["error"])
        print("✅ API chat: refuses with 503 when no model is reachable")

    def test_regression_api_team_wins_2025(self):
        """Regression test for the chat API with the historical team wins 2025 prompt.

        What this proves: the route answers 200 with a JSON body and no import error, for the
        exact prompt that once failed with 'No module named db'.

        What it no longer proves: routing. The deleted regex interpreter used to answer this
        deterministically. The turn now reaches a real ChatLiteLLM whose outbound call the
        socket guard blocks, so it always takes the failure path and this case would pass even
        if tool selection were broken. It deliberately does not assert `success`. The routing
        coverage lives in TestReportAgentSystem's scripted cases, and the surviving-route
        coverage in test_openapi_lists_legacy_and_workspace_paths.
        """
        user_prompt = "Сделай отчёт о том, в каких играх за 2025 год побеждала команда Однажды было дважды"

        response = self.client.post("/api/chat", json={"message": user_prompt})

        self.assertEqual(response.status_code, 200, "Chat endpoint should return 200")
        data = response.json()
        self.assertIsInstance(data, dict, "Response should be dictionary")
        self.assertNotIn(
            "No module named 'db'",
            str(data),
            "API response should not contain import error",
        )
        print("✅ API team wins 2025 prompt: returned successfully")

    def test_regression_api_generic_team_statistics(self):
        """Regression test for the chat API with a generic team statistics prompt.

        Same scope as test_regression_api_team_wins_2025 above: it proves the route answers
        200 with a JSON body and no import error, and deliberately does not assert `success`,
        so it no longer proves routing. See that docstring for why.
        """
        user_prompt = "статистика команды Однажды было дважды"

        response = self.client.post("/api/chat", json={"message": user_prompt})

        self.assertEqual(response.status_code, 200, "Chat endpoint should return 200")
        data = response.json()
        self.assertIsInstance(data, dict, "Response should be dictionary")
        self.assertNotIn(
            "No module named 'db'",
            str(data),
            "API response should not contain import error",
        )
        print("✅ API generic team statistics prompt: returned successfully")

    def test_regression_health_returns_503_without_tool_service(self):
        import main as main_module

        with patch.object(main_module, "tool_service", None):
            response = self.client.get("/health")

        self.assertEqual(
            response.status_code, 503, "Health should return 503 when the tool service is unavailable"
        )
        print("✅ API health: returns 503 when the tool service is unavailable")

    def test_regression_chat_without_session_id_assigns_unique_id(self):
        """Chat without session_id must mint a fresh server-side id, not the literal "default"."""
        import main as main_module

        class _StubAgent:
            async def process_user_request(self, _msg, session_id):
                return {
                    "success": True,
                    "data": None,
                    "message": "ok",
                    "query_info": [],
                    "timestamp": "t",
                }

        with patch.object(main_module, "agent_system", _StubAgent()):
            response = self.client.post("/api/chat", json={"message": "hi"})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        sid = body.get("session_id")
        self.assertIsInstance(sid, str)
        self.assertTrue(sid, "Response must include a non-empty session_id")
        self.assertNotEqual(sid, "default", "Server must not fall back to the shared 'default' id")
        self.assertFalse(
            self.client.loop.run_until_complete(main_module.sessions.is_live("default")),
            "Server must not create a shared 'default' session entry",
        )
        self.assertTrue(
            self.client.loop.run_until_complete(main_module.sessions.is_live(sid)),
            "Session must be stored under the assigned id",
        )
        print("✅ API chat: assigns server-side session_id when client omits it")

    def test_regression_chat_without_session_id_yields_distinct_sessions(self):
        """Two anonymous chat calls must not collide on a shared session."""
        import main as main_module

        class _StubAgent:
            async def process_user_request(self, _msg, session_id):
                return {
                    "success": True,
                    "data": None,
                    "message": "ok",
                    "query_info": [],
                    "timestamp": "t",
                }

        with patch.object(main_module, "agent_system", _StubAgent()):
            r1 = self.client.post("/api/chat", json={"message": "a"})
            r2 = self.client.post("/api/chat", json={"message": "b"})

        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)
        sid1 = r1.json().get("session_id")
        sid2 = r2.json().get("session_id")
        self.assertTrue(sid1 and sid2)
        self.assertNotEqual(sid1, sid2, "Anonymous callers must not share session state")
        print("✅ API chat: anonymous callers get distinct session ids")

    def test_regression_chat_with_explicit_session_id_is_preserved(self):
        """Client-supplied session_id must be echoed back unchanged."""
        import main as main_module

        class _StubAgent:
            async def process_user_request(self, _msg, session_id):
                return {
                    "success": True,
                    "data": None,
                    "message": "ok",
                    "query_info": [],
                    "timestamp": "t",
                }

        explicit = "client-supplied-id-12345"

        with patch.object(main_module, "agent_system", _StubAgent()):
            response = self.client.post(
                "/api/chat", json={"message": "hi", "session_id": explicit}
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get("session_id"), explicit,
                         "Explicit client session_id must be preserved")
        self.assertTrue(
            self.client.loop.run_until_complete(main_module.sessions.is_live(explicit))
        )
        print("✅ API chat: explicit client session_id is preserved")


class _LifecycleCheckpointTuple:
    def __init__(self, messages):
        self.checkpoint = {"channel_values": {"messages": messages}}


class _LifecycleSaver:
    def __init__(self):
        self.deleted = []
        self.delete_failures = {}
        self.threads = {}

    async def adelete_thread(self, session_id):
        self.deleted.append(session_id)
        remaining_failures = self.delete_failures.get(session_id, 0)
        if remaining_failures:
            self.delete_failures[session_id] = remaining_failures - 1
            raise RuntimeError(f"delete failed for {session_id}")
        self.threads.pop(session_id, None)

    async def aget_tuple(self, config):
        session_id = config["configurable"]["thread_id"]
        messages = self.threads.get(session_id)
        if messages is None:
            return None
        return _LifecycleCheckpointTuple(messages)


class _LifecycleAgent:
    def __init__(
        self,
        result=None,
        saver=None,
        releases=None,
        expected_starts=0,
    ):
        self.result = result or {
            "success": True,
            "data": None,
            "message": "ok",
            "query_info": [{"tool": "stub", "args": {}}],
            "timestamp": "t",
        }
        self.saver = saver
        self.releases = releases or {}
        self.expected_starts = expected_starts
        self.calls = []
        self.all_started = asyncio.Event()

    async def process_user_request(self, user_message, session_id):
        self.calls.append((user_message, session_id))
        if len(self.calls) >= self.expected_starts:
            self.all_started.set()

        if self.saver is not None:
            message_module = importlib.import_module("langchain_core.messages")
            self.saver.threads[session_id] = [
                message_module.HumanMessage(content=user_message),
                message_module.AIMessage(
                    content="",
                    tool_calls=[{"name": "stub", "args": {}, "id": "call-1"}],
                ),
                message_module.ToolMessage(content="tool data", tool_call_id="call-1"),
                message_module.AIMessage(content="ok"),
            ]

        release = self.releases.get(user_message)
        if release is not None:
            await release.wait()
        return dict(self.result)


class TestSessionLifecycleAPI(unittest.IsolatedAsyncioTestCase):
    def __init__(self, methodName="runTest"):
        super().__init__(methodName)
        self.main: Any = None
        self.session_store: Any = None
        self.previous: dict[str, Any] = {}
        self.saver = _LifecycleSaver()

    async def asyncSetUp(self):
        main_module = importlib.import_module("main")
        session_store = importlib.import_module("session_store")

        self.main = main_module
        self.session_store = session_store
        self.previous = {
            "admission_lock": self.main.admission_lock,
            "agent_system": self.main.agent_system,
            "checkpoint_saver": self.main.checkpoint_saver,
            "pinned": self.main.pinned,
            "sessions": self.main.sessions,
        }
        self.main.admission_lock = asyncio.Lock()
        self.main.pinned = {}
        self.main.sessions = session_store.SessionIndex(max_size=4, ttl=60)
        self.saver = _LifecycleSaver()
        self.main.checkpoint_saver = self.saver
        self.main.agent_system = _LifecycleAgent()

    async def asyncTearDown(self):
        for name, value in self.previous.items():
            setattr(self.main, name, value)

    def _set_capacity(self, max_size, ttl=60):
        self.main.sessions = self.session_store.SessionIndex(
            max_size=max_size,
            ttl=ttl,
        )

    async def _request(self, method, path, payload=None):
        headers = []
        body = b""
        if payload is not None:
            headers.append((b"content-type", b"application/json"))
            body = json_module.dumps(payload).encode("utf-8")

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": path,
            "query_string": b"",
            "root_path": "",
            "headers": headers,
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 8000),
            "state": {},
        }
        request_sent = False
        response_status = None
        response_parts = []

        async def receive():
            nonlocal request_sent
            if not request_sent:
                request_sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.disconnect"}

        async def send(message):
            nonlocal response_status
            if message["type"] == "http.response.start":
                response_status = message["status"]
            elif message["type"] == "http.response.body":
                response_parts.append(message.get("body", b""))

        await self.main.app(scope, receive, send)
        response_body = json_module.loads(b"".join(response_parts).decode("utf-8"))
        return response_status, response_body

    async def test_in_flight_session_is_never_evicted(self):
        self._set_capacity(1)
        release = asyncio.Event()
        agent = _LifecycleAgent(releases={"hold": release}, expected_starts=1)
        self.main.agent_system = agent

        held_request = asyncio.create_task(
            self._request(
                "POST",
                "/api/chat",
                {"message": "hold", "session_id": "held"},
            )
        )
        await asyncio.wait_for(agent.all_started.wait(), timeout=1)
        status, body = await self._request(
            "POST",
            "/api/chat",
            {"message": "next", "session_id": "next"},
        )

        self.assertEqual(status, 503)
        self.assertEqual(body["detail"], "Сервер перегружен, повторите позже")
        self.assertTrue(await self.main.sessions.is_live("held"))
        self.assertFalse(await self.main.sessions.is_live("next"))
        self.assertEqual(len(self.main.sessions), 1)

        release.set()
        held_status, _ = await held_request
        self.assertEqual(held_status, 200)

    async def test_delete_failure_retains_victim_and_retries_it(self):
        self._set_capacity(1)
        saver = self.saver
        await self.main.sessions.touch("old")
        saver.delete_failures["old"] = 1

        failed_status, _ = await self._request(
            "POST",
            "/api/chat",
            {"message": "first", "session_id": "first"},
        )
        self.assertEqual(failed_status, 500)
        self.assertTrue(await self.main.sessions.is_live("old"))

        retry_status, _ = await self._request(
            "POST",
            "/api/chat",
            {"message": "second", "session_id": "second"},
        )
        self.assertEqual(retry_status, 200)
        self.assertEqual(saver.deleted, ["old", "old"])
        self.assertFalse(await self.main.sessions.is_live("old"))
        self.assertTrue(await self.main.sessions.is_live("second"))

    async def test_clear_unknown_session_returns_200(self):
        status, body = await self._request("POST", "/api/clear/unknown")

        self.assertEqual(status, 200)
        self.assertTrue(body["success"])
        self.assertEqual(self.saver.deleted, ["unknown"])

    async def test_all_pinned_capacity_returns_503_without_overshoot(self):
        self._set_capacity(2)
        await self.main.sessions.touch("one")
        await self.main.sessions.touch("two")
        self.main.pinned = {"one": 1, "two": 1}

        status, body = await self._request(
            "POST",
            "/api/chat",
            {"message": "new", "session_id": "new"},
        )

        self.assertEqual(status, 503)
        self.assertEqual(body["detail"], "Сервер перегружен, повторите позже")
        self.assertEqual(len(self.main.sessions), 2)
        self.assertNotIn("new", self.main.pinned)

    async def test_two_requests_keep_same_session_pinned_until_both_finish(self):
        first_release = asyncio.Event()
        second_release = asyncio.Event()
        agent = _LifecycleAgent(
            releases={"first": first_release, "second": second_release},
            expected_starts=2,
        )
        self.main.agent_system = agent

        first = asyncio.create_task(
            self._request(
                "POST",
                "/api/chat",
                {"message": "first", "session_id": "shared"},
            )
        )
        second = asyncio.create_task(
            self._request(
                "POST",
                "/api/chat",
                {"message": "second", "session_id": "shared"},
            )
        )
        await asyncio.wait_for(agent.all_started.wait(), timeout=1)
        self.assertEqual(self.main.pinned["shared"], 2)

        first_release.set()
        first_status, _ = await first
        self.assertEqual(first_status, 200)
        self.assertEqual(self.main.pinned["shared"], 1)

        second_release.set()
        second_status, _ = await second
        self.assertEqual(second_status, 200)
        self.assertNotIn("shared", self.main.pinned)

    async def test_simultaneous_admissions_never_double_pick_or_overshoot(self):
        self._set_capacity(2)
        await self.main.sessions.touch("old")
        first_release = asyncio.Event()
        second_release = asyncio.Event()
        agent = _LifecycleAgent(
            releases={"first": first_release, "second": second_release},
            expected_starts=2,
        )
        self.main.agent_system = agent

        first = asyncio.create_task(
            self._request(
                "POST",
                "/api/chat",
                {"message": "first", "session_id": "first"},
            )
        )
        second = asyncio.create_task(
            self._request(
                "POST",
                "/api/chat",
                {"message": "second", "session_id": "second"},
            )
        )
        await asyncio.wait_for(agent.all_started.wait(), timeout=1)

        self.assertEqual(len(self.main.sessions), 2)
        self.assertEqual(self.saver.deleted, ["old"])
        self.assertEqual(self.main.pinned, {"first": 1, "second": 1})

        first_release.set()
        second_release.set()
        self.assertEqual((await first)[0], 200)
        self.assertEqual((await second)[0], 200)

    async def test_request_cancellation_always_unpins(self):
        release = asyncio.Event()
        agent = _LifecycleAgent(releases={"hold": release}, expected_starts=1)
        self.main.agent_system = agent
        request = asyncio.create_task(
            self._request(
                "POST",
                "/api/chat",
                {"message": "hold", "session_id": "cancelled"},
            )
        )
        await asyncio.wait_for(agent.all_started.wait(), timeout=1)
        self.assertEqual(self.main.pinned, {"cancelled": 1})

        request.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await request

        self.assertNotIn("cancelled", self.main.pinned)
        self.assertTrue(await self.main.sessions.is_live("cancelled"))

    async def test_expired_requested_session_is_deleted_then_readmitted(self):
        clock = _FakeClock()
        with patch.object(self.session_store, "time", clock):
            self._set_capacity(1, ttl=1)
            await self.main.sessions.touch("expired")
            clock.advance(2)

            status, _ = await self._request(
                "POST",
                "/api/chat",
                {"message": "fresh", "session_id": "expired"},
            )

            self.assertEqual(status, 200)
            self.assertEqual(self.saver.deleted, ["expired"])
            self.assertTrue(await self.main.sessions.is_live("expired"))

    async def test_failed_admission_deletion_leaves_no_pin(self):
        self._set_capacity(1)
        await self.main.sessions.touch("old")
        self.saver.delete_failures["old"] = 1

        status, _ = await self._request(
            "POST",
            "/api/chat",
            {"message": "new", "session_id": "new"},
        )

        self.assertEqual(status, 500)
        self.assertNotIn("new", self.main.pinned)
        self.assertTrue(await self.main.sessions.is_live("old"))
        self.assertFalse(await self.main.sessions.is_live("new"))

    async def test_recursion_and_timeout_failures_are_200_json(self):
        for name, error in (("recursion", "recursion_limit"), ("timeout", "timeout")):
            with self.subTest(name=name):
                self.main.agent_system = _LifecycleAgent(
                    result={
                        "success": False,
                        "data": None,
                        "error": error,
                        "message": f"{name} failure",
                        "query_info": [],
                        "timestamp": "t",
                    }
                )
                status, body = await self._request(
                    "POST",
                    "/api/chat",
                    {"message": name, "session_id": name},
                )

                self.assertEqual(status, 200)
                self.assertFalse(body["success"])
                self.assertNotIn("mode", body)
                self.assertEqual(body["query_info"], [])
                self.assertEqual(body["error"], error)

    async def test_failures_and_successes_keep_list_shaped_query_info(self):
        for label, success in (("failed", False), ("succeeded", True)):
            with self.subTest(outcome=label):
                query_info = [{"tool": f"{label}_tool", "args": {}}]
                self.main.agent_system = _LifecycleAgent(
                    result={
                        "success": success,
                        "data": None,
                        "message": "ok",
                        "query_info": query_info,
                        "timestamp": "t",
                    }
                )
                status, body = await self._request(
                    "POST",
                    "/api/chat",
                    {"message": label, "session_id": label},
                )

                self.assertEqual(status, 200)
                self.assertIsInstance(body["query_info"], list)
                self.assertEqual(body["query_info"], query_info)

    async def test_chat_history_clear_history_flow(self):
        saver = self.saver
        self.main.agent_system = _LifecycleAgent(saver=saver)

        chat_status, _ = await self._request(
            "POST",
            "/api/chat",
            {"message": "hello", "session_id": "flow"},
        )
        history_status, history = await self._request("GET", "/api/history/flow")
        clear_status, clear = await self._request("POST", "/api/clear/flow")
        empty_status, empty = await self._request("GET", "/api/history/flow")

        self.assertEqual(chat_status, 200)
        self.assertEqual(history_status, 200)
        self.assertEqual(
            history["history"],
            [
                {"role": "user", "content": "hello"},
                {"role": "assistant", "content": "ok", "reasoning": None},
            ],
        )
        self.assertEqual(clear_status, 200)
        self.assertTrue(clear["success"])
        self.assertEqual(empty_status, 200)
        self.assertEqual(empty["history"], [])
        self.assertFalse(await self.main.sessions.is_live("flow"))

    async def test_orphaned_history_is_deleted_on_sight(self):
        message_module = importlib.import_module("langchain_core.messages")
        self.saver.threads["orphan"] = [
            message_module.HumanMessage(content="orphaned")
        ]

        status, body = await self._request("GET", "/api/history/orphan")

        self.assertEqual(status, 200)
        self.assertEqual(body["history"], [])
        self.assertEqual(self.saver.deleted, ["orphan"])

    async def test_expired_history_is_deleted_on_sight(self):
        clock = _FakeClock()
        with patch.object(self.session_store, "time", clock):
            self._set_capacity(1, ttl=1)
            await self.main.sessions.touch("expired-history")
            self.saver.threads["expired-history"] = []
            clock.advance(2)

            status, body = await self._request("GET", "/api/history/expired-history")

            self.assertEqual(status, 200)
            self.assertEqual(body["history"], [])
            self.assertEqual(self.saver.deleted, ["expired-history"])
            self.assertFalse(await self.main.sessions.is_live("expired-history"))


class _ScriptedEngine:
    """An engine whose connect() follows a script, so the retry loop runs offline.

    The lane has no reachable database, and the check startup now performs is a real
    connection, so the two cases that drive the retry loop replace the engine rather than
    the service.
    """

    def __init__(self, failures: int, *, error: Exception):
        self._failures = failures
        self._error = error
        self.attempts = 0
        self.disposals = 0

    def connect(self):
        self.attempts += 1
        if self.attempts <= self._failures:
            raise self._error
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_exc_info):
        return False

    def execute(self, _statement):
        return None

    def dispose(self):
        self.disposals += 1
        return None


class TestStartupInitialization(unittest.TestCase):
    class ProbeResponse:
        def __init__(self, healthy_endpoints, unhealthy_endpoints, status_code=200):
            self.status_code = status_code
            self._body = {
                "healthy_endpoints": healthy_endpoints,
                "unhealthy_endpoints": unhealthy_endpoints,
            }

        def json(self):
            return self._body

    class RawProbeResponse:
        def __init__(self, body, status_code=200):
            self.status_code = status_code
            self._body = body

        def json(self):
            return self._body

    class RaisingJsonResponse:
        def __init__(self, status_code):
            self.status_code = status_code

        def json(self):
            raise ValueError("invalid JSON")

    @staticmethod
    def _get_main_module():
        import main as main_module
        return main_module

    @staticmethod
    async def _reset_startup_state(main_module):
        from session_store import SessionIndex

        if main_module.checkpoint_connection is not None:
            await main_module.checkpoint_connection.close()
        main_module.agent_system = None
        main_module.checkpoint_connection = None
        main_module.checkpoint_saver = None
        main_module.tool_engine = None
        main_module.tool_service = None
        main_module.knowledge = None
        main_module.llm_proxy_healthy = False
        main_module.sessions = SessionIndex(
            ttl=main_module.CHECKPOINT_TTL_SECONDS,
        )

    @staticmethod
    def _tool_service_patch(main_module, service=None):
        """Patch the startup seam with a ready triple, bypassing the connection check.

        Startup now opens a real connection, and the lane runs against a stopped database,
        so a test that only needs startup to complete replaces the whole helper. The two
        cases that drive the retry loop patch Engine.connect instead.
        """
        sqlalchemy = importlib.import_module("sqlalchemy")
        toolmodule = importlib.import_module("agent.toolmodule")
        resolved = StubService() if service is None else service
        engine = sqlalchemy.create_engine("sqlite://")
        return patch.object(
            main_module,
            "initialize_tool_service_with_retry",
            new=AsyncMock(return_value=(engine, resolved, toolmodule.discover(resolved))),
        )

    def _run_probe_startup(self, main_module, request_effects):
        created_agents = []

        def fake_agent_system(**kwargs):
            created_agents.append(kwargs)
            return object()

        async def run_test():
            probe_sleep = AsyncMock()
            await self._reset_startup_state(main_module)
            with self._tool_service_patch(main_module, object()), \
                 patch.object(main_module, "ReportAgentSystem", side_effect=fake_agent_system), \
                 patch.object(main_module, "CHECKPOINT_DB_PATH", ":memory:"), \
                 patch.object(main_module, "probe_sleep", probe_sleep), \
                 patch.object(main_module.requests, "get", side_effect=request_effects) as request_get, \
                 self.assertLogs(main_module.logger, level="WARNING") as captured_logs:
                await main_module.startup_event()

            probe_logs = [
                message
                for message in captured_logs.output
                if "LiteLLM probe classified" in message
            ]
            # The mode string is gone; what a probe verdict now decides is whether the
            # agent was built at all and whether /health reports the proxy up.
            agent_built = bool(created_agents)
            proxy_healthy = main_module.llm_proxy_healthy
            request_count = request_get.call_count
            sleep_count = probe_sleep.await_count
            await main_module.shutdown_event()
            self.assertEqual(
                probe_sleep.await_args_list,
                [call(main_module.PROBE_RETRY_DELAY_SECONDS)] * sleep_count,
            )
            self.assertEqual(len(probe_logs), 1)
            self.assertEqual(agent_built, proxy_healthy)
            return proxy_healthy, request_count, sleep_count, probe_logs[0]

        return asyncio.run(run_test())

    # This class deliberately has no tearDownClass. It used to close the module-level
    # `testclient`, a client it never uses and that TestAPI owns and already closes. Now that
    # TestAPI.setUpClass raises rather than skipping when the client is missing, nulling that
    # global from here would turn any run order that puts this class first into a misleading
    # "failed to build" error.

    def _assert_startup_without_knowledge(self, knowledge_dir, expected_warning):
        knowledge_module = importlib.import_module("agent.knowledge")
        runtime_module = importlib.import_module("agents.report_runtime")
        message_module = importlib.import_module("langchain_core.messages")
        main_module = self._get_main_module()

        async def run_test():
            model = ScriptedStub([message_module.AIMessage(content="ready")])
            startup_error = None
            agent_built = False
            prompt = None
            await self._reset_startup_state(main_module)
            with (
                patch.object(main_module, "KNOWLEDGE_DIR", knowledge_dir),
                self._tool_service_patch(main_module),
                patch.object(main_module, "CHECKPOINT_DB_PATH", ":memory:"),
                patch.object(
                    main_module,
                    "probe_llm_proxy",
                    new=AsyncMock(return_value=True),
                ),
                patch.object(
                    runtime_module,
                    "_new_model_client",
                    return_value=model,
                ),
                patch.object(
                    runtime_module,
                    "build_graph",
                    wraps=runtime_module.build_graph,
                ) as graph_builder,
                patch.object(
                    main_module.logger,
                    "warning",
                    wraps=main_module.logger.warning,
                ) as warning_logger,
            ):
                try:
                    await main_module.startup_event()
                except Exception as error:
                    startup_error = error
                else:
                    system = main_module.agent_system
                    if system is None:
                        raise AssertionError("Startup completed without an agent system")
                    agent_built = True
                    prompt = graph_builder.call_args.args[3]
                finally:
                    if main_module.checkpoint_connection is not None:
                        await main_module.shutdown_event()

            rendered_warnings = [
                args.args[0] % args.args[1:]
                for args in warning_logger.call_args_list
            ]
            return startup_error, agent_built, prompt, model.bound_tool_names, rendered_warnings

        startup_error, agent_built, prompt, tool_names, rendered_warnings = asyncio.run(
            run_test()
        )

        # "Exactly one" scopes to decision F2's knowledge-warning concern; startup logs
        # unrelated concerns under separate, already-covered contracts that this
        # exact-message count intentionally does not constrain.
        self.assertEqual(rendered_warnings.count(expected_warning), 1)
        self.assertIsNone(startup_error)
        self.assertTrue(agent_built)
        self.assertNotIn("read_knowledge", tool_names)
        self.assertEqual(prompt, knowledge_module.compose_system_prompt(None))
        self.assertIsNone(main_module.knowledge)

    def test_unset_knowledge_dir_warns_once_and_keeps_neutral_agent(self):
        self._assert_startup_without_knowledge(
            None,
            "Knowledge folder is not configured (dataset.knowledge_dir is unset); the agent runs without dataset knowledge.",
        )

    def test_missing_knowledge_dir_warns_once_and_keeps_neutral_agent(self):
        missing_path = Path("definitely-missing-knowledge-folder")
        self.assertFalse(missing_path.exists())
        self._assert_startup_without_knowledge(
            missing_path,
            f"Knowledge folder not found at {missing_path.resolve()}; the agent runs without dataset knowledge.",
        )

    def test_shipped_knowledge_logs_once_and_serves_read_knowledge_chat(self):
        message_module = importlib.import_module("langchain_core.messages")
        runtime_module = importlib.import_module("agents.report_runtime")
        main_module = self._get_main_module()
        knowledge_folder = Path("/bd_shared/knowledge/bez_durakov")
        rules_text = (knowledge_folder / "rules.md").read_text(encoding="utf-8")
        model = ScriptedStub(
            [
                message_module.AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "read_knowledge",
                            "args": {"topic": "rules"},
                            "id": "startup-knowledge-1",
                            "type": "tool_call",
                        }
                    ],
                ),
                message_module.AIMessage(content="Правила прочитаны."),
            ]
        )

        asyncio.run(self._reset_startup_state(main_module))
        with (
            patch.object(main_module, "KNOWLEDGE_DIR", knowledge_folder),
            patch.object(main_module, "DATABASE_NAME", "bez_durakov"),
            self._tool_service_patch(main_module),
            patch.object(main_module, "CHECKPOINT_DB_PATH", ":memory:"),
            patch.object(
                main_module,
                "probe_llm_proxy",
                new=AsyncMock(return_value=True),
            ),
            patch.object(runtime_module, "_new_model_client", return_value=model),
            self.assertLogs(main_module.logger, level="INFO") as captured_logs,
        ):
            client = ASGITestClient(main_module.app)
            try:
                response = client.post(
                    "/api/chat",
                    json={"message": "Объясни правила", "session_id": "knowledge"},
                )
            finally:
                client.close()

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertTrue(body["success"])
        self.assertNotIn("mode", body)
        self.assertEqual(
            body["query_info"],
            [{"tool": "read_knowledge", "args": {"topic": "rules"}}],
        )
        tool_messages = [
            message
            for message in model.requests[1]
            if isinstance(message, message_module.ToolMessage)
        ]
        self.assertEqual([message.content for message in tool_messages], [rules_text])

        rendered_logs = [record.getMessage() for record in captured_logs.records]
        expected_info = "Knowledge loaded: dataset=bez_durakov, topics=3"
        self.assertEqual(
            rendered_logs.count(expected_info),
            1,
            f"missing info line: {expected_info}",
        )
        self.assertFalse(
            any(
                message.startswith("Knowledge folder is not configured")
                or message.startswith("Knowledge folder not found at")
                for message in rendered_logs
            )
        )

    def _assert_invalid_knowledge_folder_aborts(
        self,
        manifest_text,
        expected_fragments,
        *,
        expect_manifest_path=True,
    ):
        knowledge_module = importlib.import_module("agent.knowledge")
        main_module = self._get_main_module()

        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            manifest_path = folder / "manifest.toml"
            if manifest_text is not None:
                manifest_path.write_text(manifest_text, encoding="utf-8")

            async def run_test():
                await self._reset_startup_state(main_module)
                tool_service_initializer = AsyncMock()
                proxy_probe = AsyncMock()
                with (
                    patch.object(main_module, "KNOWLEDGE_DIR", folder),
                    patch.object(main_module, "DATABASE_NAME", "bez_durakov"),
                    patch.object(main_module, "KNOWLEDGE_MAX_PERSONA_CHARS", 5),
                    patch.object(
                        main_module,
                        "initialize_tool_service_with_retry",
                        new=tool_service_initializer,
                    ),
                    patch.object(
                        main_module,
                        "probe_llm_proxy",
                        new=proxy_probe,
                    ),
                    self.assertLogs(
                        main_module.logger,
                        level="DEBUG",
                    ) as captured_logs,
                ):
                    with self.assertRaises(
                        knowledge_module.KnowledgeError
                    ) as raised:
                        await main_module.startup_event()

                detail = str(raised.exception)
                if expect_manifest_path:
                    self.assertIn(str(manifest_path), detail)
                for fragment in expected_fragments:
                    self.assertIn(fragment, detail)

                rendered_logs = [record.getMessage() for record in captured_logs.records]
                self.assertEqual(
                    [
                        (record.levelname, record.getMessage())
                        for record in captured_logs.records
                        if record.getMessage().startswith(
                            "Knowledge folder is invalid:"
                        )
                    ],
                    [("ERROR", f"Knowledge folder is invalid: {detail}")],
                )
                self.assertNotIn("Tool module loaded", "\n".join(rendered_logs))
                tool_service_initializer.assert_not_awaited()
                proxy_probe.assert_not_awaited()
                self.assertIsNone(main_module.checkpoint_connection)
                self.assertIsNone(main_module.checkpoint_saver)
                self.assertIsNone(main_module.agent_system)

            asyncio.run(run_test())

    def test_invalid_knowledge_folder_missing_manifest_aborts_before_the_tool_service_loads(self):
        self._assert_invalid_knowledge_folder_aborts(None, ("manifest.toml",))

    def test_invalid_knowledge_folder_unparseable_manifest_aborts_before_the_tool_service_loads(self):
        self._assert_invalid_knowledge_folder_aborts("[[[\n", ("TOML",))

    def test_invalid_knowledge_folder_unknown_key_aborts_before_the_tool_service_loads(self):
        self._assert_invalid_knowledge_folder_aborts(
            'dataset = "bez_durakov"\npersona = "x"\nlanguage = "ru"\n',
            ("language",),
        )

    def test_invalid_knowledge_folder_bad_dataset_aborts_before_the_tool_service_loads(self):
        self._assert_invalid_knowledge_folder_aborts(
            'dataset = "Bad_Dataset"\npersona = "x"\n',
            ("dataset",),
        )

    def test_invalid_knowledge_folder_empty_persona_aborts_before_the_tool_service_loads(self):
        self._assert_invalid_knowledge_folder_aborts(
            'dataset = "bez_durakov"\npersona = ""\n',
            ("persona",),
        )

    def test_invalid_knowledge_folder_overlong_persona_aborts_before_the_tool_service_loads(self):
        self._assert_invalid_knowledge_folder_aborts(
            'dataset = "bez_durakov"\npersona = "xxxxxx"\n',
            ("persona", "max_persona_chars"),
        )

    def test_invalid_knowledge_folder_dataset_mismatch_aborts_before_the_tool_service_loads(self):
        self._assert_invalid_knowledge_folder_aborts(
            'dataset = "wrong_db"\npersona = "x"\n',
            ("wrong_db", "bez_durakov"),
            expect_manifest_path=False,
        )

    def test_knowledge_loads_once_before_the_tool_service_and_the_probe(self):
        main_module = self._get_main_module()

        original_knowledge_loader = main_module.load_knowledge

        async def run_test(proxy_healthy):
            call_order = []
            loaded_knowledge = None
            created_agents = []

            def record_knowledge_load(*args, **kwargs):
                nonlocal loaded_knowledge
                call_order.append("loader")
                loaded_knowledge = original_knowledge_loader(*args, **kwargs)
                return loaded_knowledge

            async def record_tool_service_initialization():
                call_order.append("tool_service")
                sqlalchemy = importlib.import_module("sqlalchemy")
                return sqlalchemy.create_engine("sqlite://"), object(), ()

            async def record_probe(*_args, **_kwargs):
                call_order.append("probe")
                return proxy_healthy

            def fake_agent_system(**kwargs):
                created_agents.append(kwargs)
                return object()

            await self._reset_startup_state(main_module)
            with (
                patch.object(
                    main_module,
                    "load_knowledge",
                    side_effect=record_knowledge_load,
                    create=True,
                ) as knowledge_loader,
                patch.object(
                    main_module,
                    "initialize_tool_service_with_retry",
                    side_effect=record_tool_service_initialization,
                ),
                patch.object(main_module, "probe_llm_proxy", side_effect=record_probe),
                patch.object(
                    main_module,
                    "ReportAgentSystem",
                    side_effect=fake_agent_system,
                ),
                patch.object(main_module, "CHECKPOINT_DB_PATH", ":memory:"),
            ):
                await main_module.startup_event()
                await main_module.health_check(fastapi.Response())
                loader_call_count = knowledge_loader.call_count

            await main_module.shutdown_event()
            return call_order, loader_call_count, created_agents, loaded_knowledge

        for proxy_healthy in (True, False):
            with self.subTest(proxy_healthy=proxy_healthy):
                call_order, loader_call_count, created_agents, loaded_knowledge = asyncio.run(
                    run_test(proxy_healthy)
                )

                self.assertEqual(call_order, ["loader", "tool_service", "probe"])
                self.assertEqual(loader_call_count, 1)
                # A healthy probe builds the agent; an unhealthy one leaves it unbuilt and
                # the backend refuses to serve until a later chat attempt re-probes.
                self.assertEqual(bool(created_agents), proxy_healthy)
                if proxy_healthy:
                    self.assertIs(created_agents[0]["knowledge"], loaded_knowledge)

    def test_invalid_limits_abort_startup_when_knowledge_dir_is_unset(self):
        knowledge_module = importlib.import_module("agent.knowledge")
        main_module = self._get_main_module()

        async def run_test():
            await self._reset_startup_state(main_module)
            with (
                patch.object(main_module, "KNOWLEDGE_DIR", None),
                patch.object(main_module, "KNOWLEDGE_MAX_TOPICS", 0),
                patch.object(main_module, "load_knowledge") as knowledge_loader,
                patch.object(
                    main_module,
                    "initialize_tool_service_with_retry",
                    new=AsyncMock(),
                ) as tool_service_initializer,
            ):
                with self.assertRaises(knowledge_module.KnowledgeError) as raised:
                    await main_module.startup_event()

            self.assertEqual(raised.exception.key, "knowledge_max_topics")
            knowledge_loader.assert_not_called()
            tool_service_initializer.assert_not_awaited()

        asyncio.run(run_test())

    def test_configured_knowledge_byte_limit_is_validated_before_the_tool_service_loads(self):
        knowledge_module = importlib.import_module("agent.knowledge")
        main_module = self._get_main_module()

        class ValidationCaptured(Exception):
            pass

        async def run_test():
            await self._reset_startup_state(main_module)
            invalid_tool_initializer = AsyncMock()
            invalid_proxy_probe = AsyncMock()
            with (
                patch.object(main_module, "KNOWLEDGE_DIR", None),
                patch.object(main_module, "KNOWLEDGE_MAX_BYTES_PER_TURN", 0),
                patch.object(
                    main_module,
                    "initialize_tool_service_with_retry",
                    new=invalid_tool_initializer,
                ),
                patch.object(
                    main_module,
                    "probe_llm_proxy",
                    new=invalid_proxy_probe,
                ),
                self.assertLogs(main_module.logger, level="DEBUG") as captured_logs,
            ):
                with self.assertRaises(knowledge_module.KnowledgeError) as raised:
                    await main_module.startup_event()

            self.assertEqual(
                raised.exception.key,
                "knowledge_max_bytes_per_turn",
            )
            invalid_tool_initializer.assert_not_awaited()
            invalid_proxy_probe.assert_not_awaited()
            self.assertNotIn(
                "Tool module loaded",
                "\n".join(record.getMessage() for record in captured_logs.records),
            )

            await self._reset_startup_state(main_module)
            valid_tool_initializer = AsyncMock()
            valid_proxy_probe = AsyncMock()
            with (
                patch.object(main_module, "KNOWLEDGE_DIR", None),
                patch.object(main_module, "KNOWLEDGE_MAX_BYTES_PER_TURN", 5000),
                patch.object(
                    main_module,
                    "validate_limits",
                    side_effect=ValidationCaptured,
                ) as validate_limits,
                patch.object(
                    main_module,
                    "initialize_tool_service_with_retry",
                    new=valid_tool_initializer,
                ),
                patch.object(
                    main_module,
                    "probe_llm_proxy",
                    new=valid_proxy_probe,
                ),
            ):
                with self.assertRaises(ValidationCaptured):
                    await main_module.startup_event()

            validated_limits = validate_limits.call_args.args[0]
            self.assertEqual(validated_limits.max_bytes_per_turn, 5000)
            valid_tool_initializer.assert_not_awaited()
            valid_proxy_probe.assert_not_awaited()

        asyncio.run(run_test())

    UNREACHABLE_URL = "postgresql+psycopg://reporter:sup3rs3cret@db.example:5432/warehouse"

    def test_startup_retries_the_connection_check_before_succeeding(self):
        """Given a database that comes up late, When startup runs, Then it retries and proceeds."""
        main_module = self._get_main_module()
        engine = _ScriptedEngine(failures=2, error=RuntimeError("db not ready"))
        created_agent_system = object()

        async def run_test():
            with patch.object(main_module, "build_read_only_engine", return_value=engine), \
                 patch.object(main_module, "ReportAgentSystem", side_effect=lambda **_kwargs: created_agent_system), \
                 patch.object(main_module, "CHECKPOINT_DB_PATH", ":memory:"), \
                 patch.object(main_module, "probe_llm_proxy", new=AsyncMock(return_value=True)), \
                 patch.object(main_module, "startup_sleep", new=AsyncMock()) as mock_sleep:
                await self._reset_startup_state(main_module)
                await main_module.startup_event()

            self.assertEqual(engine.attempts, 3)
            self.assertEqual(mock_sleep.await_count, 2)
            self.assertIs(main_module.tool_engine, engine)
            self.assertIsNotNone(main_module.tool_service)
            self.assertIs(main_module.agent_system, created_agent_system)
            await main_module.shutdown_event()

        asyncio.run(run_test())
        print("✅ Startup retries the database connection check before succeeding")

    def test_startup_builds_exactly_one_engine_and_hands_it_to_the_factory(self):
        """Given startup, When it runs, Then one engine is built and the factory receives it."""
        main_module = self._get_main_module()
        engine = _ScriptedEngine(failures=0, error=RuntimeError("unused"))
        loaded = []

        def fake_loader(import_path, given_engine):
            loaded.append((import_path, given_engine))
            return StubService(), ()

        async def run_test():
            with patch.object(
                main_module, "build_read_only_engine", return_value=engine
            ) as engine_builder, \
                 patch.object(main_module, "load_tool_module", side_effect=fake_loader), \
                 patch.object(main_module, "ReportAgentSystem", side_effect=lambda **_kwargs: object()), \
                 patch.object(main_module, "CHECKPOINT_DB_PATH", ":memory:"), \
                 patch.object(main_module, "probe_llm_proxy", new=AsyncMock(return_value=True)):
                await self._reset_startup_state(main_module)
                await main_module.startup_event()
                await main_module.shutdown_event()

            self.assertEqual(engine_builder.call_count, 1)
            self.assertEqual(len(loaded), 1)
            self.assertIs(loaded[0][1], engine)
            self.assertEqual(loaded[0][0], main_module.DATASET_TOOLS_MODULE)

        asyncio.run(run_test())
        print("✅ Startup builds one engine and injects it into the factory")

    def _assert_unreachable_line(self, records, *, attempts):
        """The single AC-14 line, naming the target and carrying no credential."""
        lines = [
            record.getMessage()
            for record in records
            if record.getMessage().startswith("Database is unreachable")
        ]
        self.assertEqual(len(lines), 1)
        self.assertTrue(
            lines[0].startswith(
                f"Database is unreachable after {attempts} attempts: "
                "dialect=postgresql host=db.example port=5432 database=warehouse reason="
            ),
            lines[0],
        )
        for record in records:
            self.assertNotIn("sup3rs3cret", record.getMessage())

    def test_an_unreachable_database_exits_after_five_attempts_with_one_line(self):
        """Given an unreachable database, When startup runs, Then it gives up loudly and once."""
        main_module = self._get_main_module()
        engine = _ScriptedEngine(
            failures=main_module.STARTUP_RETRY_ATTEMPTS,
            error=RuntimeError("connection refused"),
        )

        async def run_test():
            await self._reset_startup_state(main_module)
            with patch.object(main_module, "DATABASE_URL", self.UNREACHABLE_URL), \
                 patch.object(main_module, "build_read_only_engine", return_value=engine), \
                 patch.object(main_module, "startup_sleep", new=AsyncMock()) as mock_sleep, \
                 self.assertLogs(main_module.logger, level="WARNING") as captured_logs:
                with self.assertRaises(RuntimeError):
                    await main_module.startup_event()

            self.assertEqual(engine.attempts, main_module.STARTUP_RETRY_ATTEMPTS)
            self.assertEqual(mock_sleep.await_count, main_module.STARTUP_RETRY_ATTEMPTS - 1)
            self.assertEqual(
                mock_sleep.await_args_list,
                [call(main_module.STARTUP_RETRY_DELAY_SECONDS)]
                * (main_module.STARTUP_RETRY_ATTEMPTS - 1),
            )
            self._assert_unreachable_line(
                captured_logs.records, attempts=main_module.STARTUP_RETRY_ATTEMPTS
            )
            self.assertIsNone(main_module.agent_system)

        asyncio.run(run_test())
        print("✅ Startup fails fast after bounded database retries")

    def test_an_unusable_dialect_reports_the_same_line_without_attempting(self):
        """Given an uninstalled dialect, When the engine is built, Then one line names the target."""
        main_module = self._get_main_module()
        sqlalchemy_exc = importlib.import_module("sqlalchemy.exc")

        async def run_test():
            await self._reset_startup_state(main_module)
            with patch.object(main_module, "DATABASE_URL", self.UNREACHABLE_URL), \
                 patch.object(
                     main_module,
                     "build_read_only_engine",
                     side_effect=sqlalchemy_exc.NoSuchModuleError(
                         "Can't load plugin: sqlalchemy.dialects:nosuch"
                     ),
                 ), \
                 patch.object(main_module, "startup_sleep", new=AsyncMock()) as mock_sleep, \
                 self.assertLogs(main_module.logger, level="ERROR") as captured_logs:
                with self.assertRaises(sqlalchemy_exc.NoSuchModuleError):
                    await main_module.startup_event()

            self.assertEqual(mock_sleep.await_count, 0)
            self._assert_unreachable_line(captured_logs.records, attempts=0)

        asyncio.run(run_test())
        print("✅ An unusable dialect reports the unreachable line without retrying")

    def test_a_malformed_url_reports_one_line_rather_than_a_traceback(self):
        """Given a URL that will not parse, When startup runs, Then it still reports one line.

        A malformed URL raises from make_url itself, before any engine is built, which is the
        first misconfiguration an operator swapping databases hits.
        """
        main_module = self._get_main_module()
        sqlalchemy_exc = importlib.import_module("sqlalchemy.exc")

        async def run_test():
            await self._reset_startup_state(main_module)
            with patch.object(main_module, "DATABASE_URL", "definitely not a url"), \
                 patch.object(main_module, "startup_sleep", new=AsyncMock()) as mock_sleep, \
                 self.assertLogs(main_module.logger, level="ERROR") as captured_logs:
                with self.assertRaises(sqlalchemy_exc.ArgumentError):
                    await main_module.startup_event()

            self.assertEqual(mock_sleep.await_count, 0)
            lines = [
                record.getMessage()
                for record in captured_logs.records
                if record.getMessage().startswith("Database is unreachable")
            ]
            self.assertEqual(len(lines), 1, lines)
            self.assertIn("after 0 attempts", lines[0])
            self.assertIn("dialect=unparsed", lines[0])
            self.assertIsNone(main_module.agent_system)

        asyncio.run(run_test())
        print("✅ A malformed database URL reports the unreachable line, not a traceback")

    def test_a_broken_tool_module_aborts_startup_with_the_preflight_message(self):
        """Given a bad module, When startup runs, Then it raises what the preflight prints."""
        main_module = self._get_main_module()
        toolmodule = importlib.import_module("agent.toolmodule")
        engine = _ScriptedEngine(failures=0, error=RuntimeError("unused"))
        cases = {
            "unimportable": toolmodule.ToolModuleError(
                "could not be imported: No module named 'nope'", module="nope"
            ),
            "missing factory": toolmodule.ToolModuleError(
                "has no build_service factory", module="operator.module"
            ),
            "undocumented method": toolmodule.ToolModuleError(
                "has no docstring", module="operator.module", method="silent"
            ),
        }

        for label, error in cases.items():
            with self.subTest(case=label):

                async def run_test(raised_error=error):
                    await self._reset_startup_state(main_module)
                    disposals_before = engine.disposals
                    with patch.object(main_module, "build_read_only_engine", return_value=engine), \
                         patch.object(main_module, "load_tool_module", side_effect=raised_error):
                        with self.assertRaises(toolmodule.ToolModuleError) as caught:
                            await main_module.startup_event()
                    self.assertEqual(str(caught.exception), str(raised_error))
                    self.assertIsNone(main_module.agent_system)
                    # The connection check already checked a connection out of the pool, and
                    # the caller never receives the engine, so nothing else could dispose it.
                    self.assertEqual(engine.disposals, disposals_before + 1)
                    self.assertIsNone(main_module.tool_engine)

                asyncio.run(run_test())

        print("✅ A broken tool module aborts startup and hands the engine back")

    def test_a_dataset_config_error_aborts_startup_naming_the_key(self):
        """Given a [dataset] misconfiguration, When startup runs, Then it aborts naming the key."""
        main_module = self._get_main_module()
        message = "dataset.tools_module is not configured; add a [dataset] section"

        async def run_test():
            await self._reset_startup_state(main_module)
            with patch.object(main_module, "DATASET_CONFIG_ERROR", message):
                with self.assertRaises(RuntimeError) as caught:
                    await main_module.startup_event()

            self.assertEqual(str(caught.exception), message)
            self.assertIsNone(main_module.agent_system)

        asyncio.run(run_test())
        print("✅ A dataset config error aborts startup naming the key")

    def test_probe_failure_keeps_process_up_and_refuses_to_serve(self):
        """Given an offline proxy, When startup probes it, Then the process serves 503 on both."""
        main_module = self._get_main_module()
        created_agents = []

        def fake_agent_system(**kwargs):
            created_agents.append(kwargs)
            return object()

        async def run_test():
            probe_sleep = AsyncMock()
            await self._reset_startup_state(main_module)
            with self._tool_service_patch(main_module, object()), \
                 patch.object(main_module, "ReportAgentSystem", side_effect=fake_agent_system), \
                 patch.object(main_module, "CHECKPOINT_DB_PATH", ":memory:"), \
                 patch.object(main_module, "probe_sleep", probe_sleep), \
                 patch.object(
                     main_module.requests,
                     "get",
                     side_effect=main_module.requests.ConnectionError("offline"),
                 ) as request_get:
                await main_module.startup_event()

                health_response = fastapi.Response()
                health = await main_module.health_check(health_response)

                chat_response = fastapi.Response()
                chat = await main_module.chat(
                    main_module.ChatMessage(message="привет"), chat_response
                )

            self.assertEqual(created_agents, [])
            self.assertIsNone(main_module.agent_system)
            self.assertEqual(health_response.status_code, 503)
            self.assertFalse(health["services"]["llm_proxy"])
            self.assertEqual(chat_response.status_code, 503)
            self.assertFalse(chat.success)
            self.assertTrue(chat.error)
            self.assertEqual(chat.message, "Для ответа нужна доступная языковая модель.")
            # Five startup attempts plus one re-probe from the refused chat call.
            self.assertEqual(request_get.call_count, main_module.PROBE_RETRY_ATTEMPTS + 1)
            self.assertEqual(probe_sleep.await_count, main_module.PROBE_RETRY_ATTEMPTS - 1)
            await main_module.shutdown_event()

        asyncio.run(run_test())
        print("✅ An unreachable model keeps the process up and refuses to serve")

    def test_probe_failure_recovers_on_a_later_chat_attempt(self):
        """Given a proxy that comes back, When chat is called again, Then the agent is built."""
        main_module = self._get_main_module()
        created_agents = []

        def fake_agent_system(**kwargs):
            created_agents.append(kwargs)

            class _Agent:
                async def process_user_request(self, _message, session_id):
                    return {
                        "success": True,
                        "data": None,
                        "message": "готово",
                        "query_info": [],
                        "timestamp": "t",
                    }

            return _Agent()

        async def run_test():
            probe_sleep = AsyncMock()
            healthy = self.ProbeResponse(["gpt-4o"], [])
            offline = main_module.requests.ConnectionError("offline")
            # Five failures for startup, one more for the first chat attempt, then healthy.
            effects = [offline] * (main_module.PROBE_RETRY_ATTEMPTS + 1) + [healthy]
            await self._reset_startup_state(main_module)
            with self._tool_service_patch(main_module, object()), \
                 patch.object(main_module, "ReportAgentSystem", side_effect=fake_agent_system), \
                 patch.object(main_module, "CHECKPOINT_DB_PATH", ":memory:"), \
                 patch.object(main_module, "probe_sleep", probe_sleep), \
                 patch.object(main_module.requests, "get", side_effect=effects) as request_get:
                await main_module.startup_event()

                first_response = fastapi.Response()
                first = await main_module.chat(
                    main_module.ChatMessage(message="первый"), first_response
                )
                attempts_after_first = request_get.call_count

                second_response = fastapi.Response()
                second = await main_module.chat(
                    main_module.ChatMessage(message="второй"), second_response
                )
                attempts_after_second = request_get.call_count

                health_response = fastapi.Response()
                health = await main_module.health_check(health_response)

            self.assertEqual(first_response.status_code, 503)
            self.assertFalse(first.success)
            self.assertEqual(second_response.status_code, 200)
            self.assertTrue(second.success)
            self.assertEqual(second.message, "готово")
            self.assertEqual(len(created_agents), 1)
            # Exactly one extra probe per chat attempt, no in-request retries.
            self.assertEqual(attempts_after_first, main_module.PROBE_RETRY_ATTEMPTS + 1)
            self.assertEqual(attempts_after_second, main_module.PROBE_RETRY_ATTEMPTS + 2)
            self.assertEqual(health_response.status_code, 200)
            self.assertTrue(health["services"]["llm_proxy"])
            await main_module.shutdown_event()

        asyncio.run(run_test())
        print("✅ A later chat attempt re-probes and recovers")

    def test_healthy_probe_builds_the_agent_and_health_reports_proxy_up(self):
        """Given a deeply healthy proxy, When startup probes it, Then the agent is built."""
        main_module = self._get_main_module()
        created_agents = []

        def fake_agent_system(**kwargs):
            created_agents.append(kwargs)
            return object()

        async def run_test():
            probe_sleep = AsyncMock()
            response = self.ProbeResponse(["gpt-4o"], [])
            await self._reset_startup_state(main_module)
            with self._tool_service_patch(main_module, object()), \
                 patch.object(main_module, "ReportAgentSystem", side_effect=fake_agent_system), \
                 patch.object(main_module, "CHECKPOINT_DB_PATH", ":memory:"), \
                 patch.object(main_module, "probe_sleep", probe_sleep), \
                 patch.object(main_module.requests, "get", return_value=response) as request_get:
                await main_module.startup_event()
                health = await main_module.health_check(fastapi.Response())

            self.assertEqual(len(created_agents), 1)
            self.assertIs(created_agents[0]["checkpointer"], main_module.checkpoint_saver)
            self.assertTrue(health["services"]["llm_proxy"])
            self.assertEqual(request_get.call_count, 1)
            self.assertEqual(probe_sleep.await_count, 0)
            await main_module.shutdown_event()

        asyncio.run(run_test())

    def test_unrelated_unhealthy_endpoints_still_elect_agent(self):
        config_module = importlib.import_module("bd_shared.config")
        main_module = self._get_main_module()
        created_agents = []

        def fake_agent_system(**kwargs):
            created_agents.append(kwargs)
            return object()

        async def run_test():
            probe_sleep = AsyncMock()
            response = self.ProbeResponse(["selected-model"], ["unrelated-model"])
            await self._reset_startup_state(main_module)
            with self._tool_service_patch(main_module, object()), \
                 patch.object(main_module, "ReportAgentSystem", side_effect=fake_agent_system), \
                 patch.object(main_module, "CHECKPOINT_DB_PATH", ":memory:"), \
                 patch.object(main_module, "AGENT_MODEL", "selected-model", create=True), \
                 patch.object(main_module, "probe_sleep", probe_sleep), \
                 patch.object(main_module.requests, "get", return_value=response) as request_get:
                await main_module.startup_event()

            await main_module.shutdown_event()

            self.assertEqual(len(created_agents), 1)
            request_get.assert_called_once_with(
                f"{main_module.LITELLM_BASE_URL}/health",
                params={"model": "selected-model"},
                timeout=config_module.PROBE_REQUEST_TIMEOUT_SECONDS,
            )
            self.assertEqual(probe_sleep.await_count, 0)

        asyncio.run(run_test())

    def test_probe_response_classifier_follows_decision_table(self):
        main_module = self._get_main_module()
        cases = (
            ("direct permanent status", 401, "not-json", "permanent"),
            (
                "healthy wins over nested permanent",
                200,
                {
                    "healthy_endpoints": ["model"],
                    "unhealthy_endpoints": [{"exception_status": 401}],
                },
                "healthy",
            ),
            (
                "nested permanent status",
                503,
                {
                    "healthy_endpoints": [],
                    "unhealthy_endpoints": [{"exception_status": 403}],
                },
                "permanent",
            ),
            (
                "legacy unhealthy string",
                503,
                {"healthy_endpoints": [], "unhealthy_endpoints": ["401"]},
                "transient",
            ),
            (
                "truthy non-list healthy endpoints",
                200,
                {"healthy_endpoints": "model", "unhealthy_endpoints": []},
                "transient",
            ),
            ("non-dict body", 503, "unavailable", "transient"),
        )

        for name, status_code, body, expected in cases:
            with self.subTest(name=name):
                self.assertEqual(
                    main_module._classify_probe_response(status_code, body),
                    expected,
                )

    def test_permanent_nested_probe_failure_stops_after_one_attempt(self):
        main_module = self._get_main_module()
        attempts = main_module.PROBE_RETRY_ATTEMPTS

        for exception_status in (400, 401, 403, 404):
            with self.subTest(exception_status=exception_status):
                response = self.ProbeResponse(
                    [],
                    [{"exception_status": exception_status}],
                    status_code=503,
                )
                proxy_healthy, request_count, sleep_count, probe_log = self._run_probe_startup(
                    main_module,
                    [response] * attempts,
                )

                self.assertFalse(proxy_healthy)
                self.assertEqual(request_count, 1)
                self.assertEqual(sleep_count, 0)
                self.assertIn("verdict=permanent", probe_log)
                self.assertIn(f"exception_status={exception_status}", probe_log)

    def test_permanent_direct_probe_failure_stops_after_one_attempt(self):
        main_module = self._get_main_module()
        attempts = main_module.PROBE_RETRY_ATTEMPTS

        for status_code in (400, 401, 403, 404):
            with self.subTest(status_code=status_code):
                response = self.ProbeResponse([], [], status_code=status_code)
                proxy_healthy, request_count, sleep_count, probe_log = self._run_probe_startup(
                    main_module,
                    [response] * attempts,
                )

                self.assertFalse(proxy_healthy)
                self.assertEqual(request_count, 1)
                self.assertEqual(sleep_count, 0)
                self.assertIn("verdict=permanent", probe_log)
                self.assertIn(f"status={status_code}", probe_log)

    def test_transient_probe_failure_exhausts_retry_budget(self):
        main_module = self._get_main_module()
        attempts = main_module.PROBE_RETRY_ATTEMPTS
        cases = (
            (
                "timeout",
                [main_module.requests.Timeout("timed out") for _ in range(attempts)],
            ),
            ("rate limited", [self.ProbeResponse([], [], 429)] * attempts),
            ("unmarked server error", [self.ProbeResponse([], [], 503)] * attempts),
            ("non-dict body", [self.RawProbeResponse("unavailable", 503)] * attempts),
            ("malformed JSON", [self.RaisingJsonResponse(503)] * attempts),
            (
                "legacy unhealthy string",
                [self.ProbeResponse([], ["401"], 503)] * attempts,
            ),
        )

        for name, request_effects in cases:
            with self.subTest(name=name):
                proxy_healthy, request_count, sleep_count, probe_log = self._run_probe_startup(
                    main_module,
                    request_effects,
                )

                self.assertFalse(proxy_healthy)
                self.assertEqual(request_count, attempts)
                self.assertEqual(sleep_count, attempts - 1)
                self.assertIn("verdict=transient", probe_log)

    def test_healthy_probe_wins_over_nested_permanent_failure(self):
        main_module = self._get_main_module()
        response = self.ProbeResponse(
            ["model"],
            [{"exception_status": 401}],
            status_code=200,
        )

        proxy_healthy, request_count, sleep_count, probe_log = self._run_probe_startup(
            main_module,
            [response],
        )

        self.assertTrue(proxy_healthy)
        self.assertEqual(request_count, 1)
        self.assertEqual(sleep_count, 0)
        self.assertIn("verdict=healthy", probe_log)

    def test_transient_probe_recovers_on_next_attempt(self):
        main_module = self._get_main_module()
        responses = [
            self.ProbeResponse([], ["unrelated"], 500),
            self.ProbeResponse(["model"], [], 200),
        ]

        proxy_healthy, request_count, sleep_count, probe_log = self._run_probe_startup(
            main_module,
            responses,
        )

        self.assertTrue(proxy_healthy)
        self.assertEqual(request_count, 2)
        self.assertEqual(sleep_count, 1)
        self.assertIn("verdict=healthy", probe_log)

    def test_direct_401_stays_permanent_when_json_raises(self):
        main_module = self._get_main_module()
        attempts = main_module.PROBE_RETRY_ATTEMPTS
        response = self.RaisingJsonResponse(401)

        proxy_healthy, request_count, sleep_count, probe_log = self._run_probe_startup(
            main_module,
            [response] * attempts,
        )

        self.assertFalse(proxy_healthy)
        self.assertEqual(request_count, 1)
        self.assertEqual(sleep_count, 0)
        self.assertIn("verdict=permanent", probe_log)
        self.assertIn("status=401", probe_log)

    def test_truthy_non_list_healthy_endpoints_remains_transient(self):
        main_module = self._get_main_module()
        attempts = main_module.PROBE_RETRY_ATTEMPTS
        responses = [self.ProbeResponse("model", [], 200)] * attempts

        proxy_healthy, request_count, sleep_count, probe_log = self._run_probe_startup(
            main_module,
            responses,
        )

        self.assertFalse(proxy_healthy)
        self.assertEqual(request_count, attempts)
        self.assertEqual(sleep_count, attempts - 1)
        self.assertIn("verdict=transient", probe_log)

    def test_rebuild_trims_1026_threads_to_newest_1024(self):
        """Given persisted overflow, When rebuilding, Then only the newest 1024 threads survive."""
        import importlib

        main_module = self._get_main_module()
        checkpoint_module = importlib.import_module("langgraph.checkpoint.sqlite.aio")
        checkpoint_base = importlib.import_module("langgraph.checkpoint.base")
        session_store = importlib.import_module("session_store")

        async def run_test():
            await self._reset_startup_state(main_module)
            previous_saver = main_module.checkpoint_saver
            previous_sessions = main_module.sessions
            async with checkpoint_module.AsyncSqliteSaver.from_conn_string(":memory:") as saver:
                await saver.setup()
                for index in range(1026):
                    checkpoint = checkpoint_base.empty_checkpoint()
                    checkpoint["id"] = f"00000000-0000-6000-8000-{index:012d}"
                    await saver.aput(
                        {
                            "configurable": {
                                "thread_id": f"thread-{index:04d}",
                                "checkpoint_ns": "",
                            }
                        },
                        checkpoint,
                        {},
                        {},
                    )

                main_module.checkpoint_saver = saver
                main_module.sessions = session_store.SessionIndex(max_size=1024)
                with patch.object(
                    saver,
                    "adelete_thread",
                    wraps=saver.adelete_thread,
                ) as delete_thread:
                    await main_module.rebuild_session_index()

                self.assertEqual(len(main_module.sessions), 1024)
                self.assertTrue(await main_module.sessions.is_live("thread-1025"))
                self.assertTrue(await main_module.sessions.is_live("thread-0002"))
                self.assertFalse(await main_module.sessions.is_live("thread-0001"))
                self.assertFalse(await main_module.sessions.is_live("thread-0000"))
                self.assertEqual(
                    [call.args[0] for call in delete_thread.await_args_list],
                    ["thread-0001", "thread-0000"],
                )
                self.assertIsNone(
                    await saver.aget_tuple(
                        {"configurable": {"thread_id": "thread-0000"}}
                    )
                )

            main_module.checkpoint_saver = previous_saver
            main_module.sessions = previous_sessions

        asyncio.run(run_test())

    def test_health_still_returns_503_without_a_tool_service(self):
        """Given no tool service, When health is requested, Then readiness remains unavailable."""
        main_module = self._get_main_module()

        async def run_test():
            with patch.object(main_module, "tool_service", None):
                with self.assertRaises(main_module.HTTPException) as raised:
                    await main_module.health_check(fastapi.Response())

            self.assertEqual(raised.exception.status_code, 503)

        asyncio.run(run_test())

    def test_shutdown_closes_checkpoint_connection(self):
        """Given an initialized saver, When shutdown runs, Then its SQLite connection closes."""
        main_module = self._get_main_module()

        async def run_test():
            await self._reset_startup_state(main_module)
            with self._tool_service_patch(main_module, object()), \
                 patch.object(main_module, "ReportAgentSystem", return_value=object()), \
                 patch.object(main_module, "CHECKPOINT_DB_PATH", ":memory:"), \
                 patch.object(main_module, "probe_llm_proxy", new=AsyncMock(return_value=False)):
                await main_module.startup_event()

            connection = getattr(main_module, "checkpoint_connection")
            self.assertIsNotNone(connection)
            await main_module.shutdown_event()

            assert connection is not None
            with self.assertRaises(ValueError):
                await connection.execute("SELECT 1")

        asyncio.run(run_test())


class _FakeClock:
    """Deterministic stand-in for the `time` module read by session_store.

    Patched in as `session_store.time` so TTL behaviour is exercised without
    sleeping, and without disturbing the global clock the event loop runs on.
    """

    def __init__(self, start: float = 1000.0):
        self._now = start

    def monotonic(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


class TestSessionIndex(unittest.IsolatedAsyncioTestCase):
    """Unit tests for the async SessionIndex (recency LRU + monotonic TTL).

    Ported from the synchronous TestSessionStore suite. Two families of
    assertions are INTENTIONALLY rewritten:

    * sentinel-value asserts (`store["a"] is sentinel`) become membership and
      recency asserts — the index stores monotonic timestamps, never agent
      objects (owner decision 2026-08-01);
    * self-eviction asserts become caller-driven cap pressure — the index never
      evicts by itself, the caller asks for a victim and drops it, so checkpoint
      removal stays ordered delete-then-forget (spec D1).
    """

    def _module(self):
        import session_store
        return session_store

    def _index(self, max_size: int = 4, ttl: float = 60.0):
        return self._module().SessionIndex(max_size=max_size, ttl=ttl)

    def _patch_clock(self, start: float = 1000.0) -> "_FakeClock":
        clock = _FakeClock(start)
        patcher = patch.object(self._module(), "time", clock)
        patcher.start()
        self.addCleanup(patcher.stop)
        return clock

    async def test_touch_admits_a_session(self):
        """Given an empty index, When a sid is touched, Then that sid is live.

        Replaces test_basic_set_get_contains: there is no stored value to
        identity-check, liveness is the whole contract.
        """
        index = self._index()

        await index.touch("a")

        self.assertTrue(await index.is_live("a"))
        self.assertEqual(len(index), 1)
        print("✅ SessionIndex: touch admits a session id")

    async def test_unknown_session_is_not_live(self):
        """Given an empty index, When an unknown sid is probed, Then it is not live."""
        index = self._index()

        self.assertFalse(await index.is_live("missing"))
        print("✅ SessionIndex: unknown session id is not live")

    async def test_lru_victim_is_the_least_recently_touched(self):
        """Given a, b, c touched and a re-touched, When a victim is asked for, Then b."""
        index = self._index(max_size=3)
        for sid in ("a", "b", "c"):
            await index.touch(sid)

        await index.touch("a")

        self.assertEqual(await index.lru_victim({}), "b")
        print("✅ SessionIndex: LRU victim is the least recently touched session")

    async def test_expired_session_is_not_live(self):
        """Given a touched sid, When the monotonic clock passes the TTL, Then not live."""
        clock = self._patch_clock()
        index = self._index(ttl=60.0)
        await index.touch("x")

        clock.advance(60.1)

        self.assertFalse(await index.is_live("x"))
        print("✅ SessionIndex: session stops being live once its TTL elapses")

    async def test_expired_ids_lists_only_expired_sessions(self):
        """Given one aged and one fresh sid, When expired_ids is read, Then only the aged one."""
        clock = self._patch_clock()
        index = self._index(ttl=60.0)
        await index.touch("old")
        clock.advance(30.0)
        await index.touch("fresh")

        clock.advance(40.0)

        self.assertEqual(await index.expired_ids(), ["old"])
        print("✅ SessionIndex: expired_ids reports only sessions past their TTL")

    async def test_expiry_check_never_drops_entries(self):
        """Given an expired sid, When it is inspected, Then it stays until the caller drops it.

        The caller deletes the checkpoint thread first and only then forgets the
        entry (spec D1), so the index must never self-purge on inspection.
        """
        clock = self._patch_clock()
        index = self._index(ttl=60.0)
        await index.touch("x")
        clock.advance(61.0)

        await index.expired_ids()
        await index.is_live("x")

        self.assertEqual(len(index), 1)
        await index.drop("x")
        self.assertEqual(len(index), 0)
        print("✅ SessionIndex: expiry inspection leaves removal to the caller")

    async def test_drop_of_unknown_session_is_a_noop(self):
        """Given an unknown sid, When it is dropped, Then nothing raises and nothing changes.

        Replaces test_getitem_missing_raises_keyerror: the index has no
        __getitem__, and drop must stay idempotent so a failed thread deletion
        can be retried on the next eviction (spec D1).
        """
        index = self._index()
        await index.touch("a")

        await index.drop("missing")

        self.assertEqual(len(index), 1)
        print("✅ SessionIndex: dropping an unknown session is a no-op")

    async def test_repeated_touch_does_not_grow_the_index(self):
        """Given a sid already present, When it is touched again, Then the size is unchanged."""
        index = self._index(max_size=2)
        await index.touch("a")
        await index.touch("b")

        await index.touch("a")

        self.assertEqual(len(index), 2)
        print("✅ SessionIndex: re-touching an existing session does not grow the index")

    async def test_caller_driven_eviction_holds_the_cap(self):
        """Given a full index, When the caller evicts the victim and admits one, Then len is capped.

        Replaces test_capacity_hard_cap: eviction moved out of the index, so the
        cap is proven through the caller's victim/drop/touch sequence.
        """
        index = self._index(max_size=10)
        for i in range(10):
            await index.touch(str(i))

        victim = await index.lru_victim({})
        await index.drop(victim)
        await index.touch("overflow")

        self.assertEqual(victim, "0")
        self.assertEqual(len(index), 10)
        print("✅ SessionIndex: caller-driven eviction never exceeds the cap")

    async def test_max_1024_sessions(self):
        """Given the default index, When 1024 sids are admitted, Then the cap holds at 1024."""
        session_store = self._module()
        self.assertEqual(session_store.MAX_SESSIONS, 1024)
        index = session_store.SessionIndex()
        for i in range(1024):
            await index.touch(str(i))
        self.assertEqual(len(index), 1024)

        victim = await index.lru_victim({})
        await index.drop(victim)
        await index.touch("one_more")

        self.assertEqual(len(index), 1024)
        print("✅ SessionIndex: default MAX_SESSIONS=1024 is enforced by the caller loop")

    async def test_lru_victim_skips_pinned_sessions(self):
        """Given a pinned LRU sid, When a victim is asked for, Then the next unpinned sid.

        `pinned` is a REFCOUNT mapping: a count above zero protects, a zero
        count does not (in-flight requests, spec D3).
        """
        index = self._index(max_size=3)
        for sid in ("a", "b", "c"):
            await index.touch(sid)

        victim = await index.lru_victim({"a": 2, "b": 0})

        self.assertEqual(victim, "b")
        print("✅ SessionIndex: pinned sessions are skipped as eviction victims")

    async def test_lru_victim_returns_none_when_every_session_is_pinned(self):
        """Given every sid pinned, When a victim is asked for, Then None (caller answers 503)."""
        index = self._index(max_size=2)
        await index.touch("a")
        await index.touch("b")

        self.assertIsNone(await index.lru_victim({"a": 1, "b": 3}))
        print("✅ SessionIndex: all-pinned capacity yields no victim")

    async def test_seed_installs_newest_first_ids_in_lru_order(self):
        """Given newest-first ids, When seeded, Then the last one is the first victim."""
        index = self._index(max_size=4)

        await index.seed(["newest", "middle", "oldest"])

        self.assertEqual(len(index), 3)
        self.assertEqual(await index.lru_victim({}), "oldest")
        print("✅ SessionIndex: seed installs newest-first input in oldest-first LRU order")

    async def test_ttl_defaults_to_the_configured_checkpoint_ttl(self):
        """Given no ttl argument, When the clock crosses CHECKPOINT_TTL_SECONDS, Then it expires.

        Proves the single source of truth (AC-26): the old SESSION_TTL_SECONDS
        literal is gone and the default comes from bd_shared.config.
        """
        import importlib
        session_store = self._module()
        ttl = importlib.import_module("bd_shared.config").CHECKPOINT_TTL_SECONDS
        clock = self._patch_clock()
        index = session_store.SessionIndex()
        await index.touch("x")

        clock.advance(ttl - 1)
        self.assertTrue(await index.is_live("x"))
        clock.advance(2)

        self.assertFalse(await index.is_live("x"))
        print("✅ SessionIndex: default TTL comes from bd_shared.config.CHECKPOINT_TTL_SECONDS")

    def test_index_exposes_no_container_protocol(self):
        """Given an index, When `in` is used on it, Then TypeError.

        An async __contains__ would return a coroutine, which `in` coerces to a
        truthy bool — every membership test would silently pass (oracle #5).
        """
        index = self._index()

        with self.assertRaises(TypeError):
            _ = "a" in index
        print("✅ SessionIndex: no container protocol, liveness must be awaited")


def run_tests():
    """Run all tests."""
    print("=" * 80)
    print("🧪 Running Web Reporting System Tests")
    print("=" * 80)
    print()

    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    # Add test classes
    suite.addTests(loader.loadTestsFromTestCase(TestSessionIndex))
    suite.addTests(loader.loadTestsFromTestCase(TestGameDataService))
    suite.addTests(loader.loadTestsFromTestCase(TestReportAgentSystem))
    suite.addTests(loader.loadTestsFromTestCase(TestAPI))
    suite.addTests(loader.loadTestsFromTestCase(TestSessionLifecycleAPI))
    suite.addTests(loader.loadTestsFromTestCase(TestStartupInitialization))

    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Print summary
    print()
    print("=" * 80)
    print("📊 Test Summary")
    print("=" * 80)
    print(f"Tests run: {result.testsRun}")
    print(f"Successes: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Skipped: {len(result.skipped)}")

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
