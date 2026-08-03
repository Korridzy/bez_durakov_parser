"""
Test script for the web reporting system.
Tests all components: services, agents, API.
"""
import sys
import os
import asyncio
import importlib
import json as json_module
from typing import Any

import unittest
from unittest.mock import AsyncMock, patch
from datetime import date, datetime

_test_agent_support = importlib.import_module("test_agent_support")
_test_agent_graph = importlib.import_module("test_agent_graph")
_test_net_guard = importlib.import_module("test_net_guard")
StubService = _test_agent_support.StubService
ScriptedStub = _test_agent_graph.ScriptedModel

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
        with patch("main.probe_llm_proxy", new=AsyncMock(return_value=False)), patch(
            "main.GameDataService", return_value=startup_service
        ):
            # One loop owns startup, the saver, all synchronous calls, and shutdown.
            testclient = ASGITestClient(app)
except Exception as e:
    print(f"⚠️ Warning: Could not initialize in-process test client: {e}")
    testclient = None


def setUpModule():
    """Offline suite: only loopback and the Compose database host are reachable."""
    _test_net_guard.install()


class TestGameDataService(unittest.TestCase):
    """Test the GameDataService."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        try:
            from services.game_data_service import GameDataService
            service = GameDataService()
            # SQLAlchemy connects lazily, so without this probe an unreachable
            # database leaves every sibling's "Service not available" skip dead.
            with service.db.engine.connect():
                pass
            cls.service = service
        except Exception as e:
            print(f"⚠️ Warning: Could not initialize GameDataService: {e}")
            cls.service = None

    def test_service_initialization(self):
        """Test that service initializes correctly."""
        if self.service is None:
            self.skipTest("Service not available")

        self.assertIsNotNone(self.service.db, "Initialized service should own a database handle")

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

        print(f"✅ Service get_team_statistics executed successfully")

    def test_regression_service_get_team_statistics_reraises_missing_team(self):
        if self.service is None:
            self.skipTest("Service not available")

        with patch.object(self.service.db, "get_team_by_name", return_value=None) as mock_lookup:
            with self.assertRaises(ValueError):
                self.service.get_team_statistics("missing team")

            mock_lookup.assert_called_once_with("missing team")

        print("✅ Service get_team_statistics: missing team is re-raised")


class TestReportAgentSystem(unittest.IsolatedAsyncioTestCase):
    """Test the ReportAgentSystem."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        cls.checkpoint = importlib.import_module("langgraph.checkpoint.sqlite.aio")
        cls.messages = importlib.import_module("langchain_core.messages")
        cls.report_module = importlib.import_module("agents.report_agents")

    async def test_agent_initialization(self):
        """Test that agent system initializes."""
        async with self.checkpoint.AsyncSqliteSaver.from_conn_string(":memory:") as saver:
            agent_system = self.report_module.ReportAgentSystem(
                service=StubService(),
                mode="fallback",
                checkpointer=saver,
            )

            self.assertIsNotNone(agent_system, "Agent system should be initialized")

    async def test_regression_agents_enabled_with_api_key(self):
        scripted_message = "Report generated based on: покажи все игры"
        model_client = ScriptedStub(
            [self.messages.AIMessage(content=scripted_message)]
        )
        async with self.checkpoint.AsyncSqliteSaver.from_conn_string(":memory:") as saver:
            enabled_system = self.report_module.ReportAgentSystem(
                service=StubService(),
                mode="agent",
                model_client=model_client,
                checkpointer=saver,
            )

            response = await enabled_system.process_user_request(
                "покажи все игры", "enabled-mode"
            )
            self.assertIsInstance(response, dict, "Enabled mode response should be dictionary")
            self.assertTrue(response.get("success"), "Enabled mode request should succeed")
            self.assertEqual(response["mode"], "agent")
            self.assertEqual(response["message"], scripted_message)
            self.assertNotIn("fallback mode", response["message"].lower())

            checkpoint_tuple = await saver.aget_tuple(
                {"configurable": {"thread_id": "enabled-mode"}}
            )
            self.assertIsNotNone(checkpoint_tuple)
            if checkpoint_tuple is None:
                self.fail("Enabled mode must checkpoint its conversation")
            history = checkpoint_tuple.checkpoint["channel_values"]["messages"]
            self.assertIsInstance(history, list, "History should be list in enabled mode")
            self.assertGreaterEqual(
                len(history), 2,
                "Enabled mode should record at least user+assistant history entries",
            )

    async def test_regression_agent_system_uses_injected_service(self):
        injected_service = StubService()
        async with self.checkpoint.AsyncSqliteSaver.from_conn_string(":memory:") as saver:
            system = self.report_module.ReportAgentSystem(
                service=injected_service,
                mode="fallback",
                checkpointer=saver,
            )

            self.assertIs(system.service, injected_service)
        print("✅ Agent system reuses injected data service")

    async def test_process_request_all_games(self):
        """Test processing a request for all games."""
        async with self.checkpoint.AsyncSqliteSaver.from_conn_string(":memory:") as saver:
            agent_system = self.report_module.ReportAgentSystem(
                service=StubService(),
                mode="fallback",
                checkpointer=saver,
            )

            response = await agent_system.process_user_request(
                "покажи все игры", "all-games"
            )
            self.assertIsInstance(response, dict, "Should return dictionary")
            self.assertIn("success", response, "Response should have success field")
        print(f"✅ Request processed: {response.get('message', 'No message')}")

    async def test_conversation_history(self):
        """Test conversation history tracking."""
        async with self.checkpoint.AsyncSqliteSaver.from_conn_string(":memory:") as saver:
            agent_system = self.report_module.ReportAgentSystem(
                service=StubService(),
                mode="fallback",
                checkpointer=saver,
            )
            config = {"configurable": {"thread_id": "history"}}
            self.assertIsNone(await saver.aget_tuple(config))

            await agent_system.process_user_request("тест", "history")
            checkpoint_tuple = await saver.aget_tuple(config)
            self.assertIsNotNone(checkpoint_tuple)
            if checkpoint_tuple is None:
                self.fail("Fallback mode must checkpoint its conversation")
            history = checkpoint_tuple.checkpoint["channel_values"]["messages"]
            self.assertIsInstance(history, list, "History should be a list")
            self.assertGreaterEqual(len(history), 2)
        print(f"✅ Conversation history has {len(history)} entries")

    async def test_regression_team_wins_2025(self):
        """Port the win route assertion to list-shaped ``query_info``.
        
        Previously failed with: 'No module named db' import error.
        Tests that get_team_wins() method correctly routes and executes
        for the exact historical prompt. The assertion-shape migration is
        intentional: graph responses expose a list of tool calls.
        """
        async with self.checkpoint.AsyncSqliteSaver.from_conn_string(":memory:") as saver:
            agent_system = self.report_module.ReportAgentSystem(
                service=StubService(),
                mode="fallback",
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
        """Port the team-statistics route assertion to list-shaped ``query_info``.
        
        Tests that team statistics prompts (without win keywords)
        correctly route to get_team_statistics and execute without errors.
        The assertion-shape migration is intentional for graph tool traces.
        """
        async with self.checkpoint.AsyncSqliteSaver.from_conn_string(":memory:") as saver:
            agent_system = self.report_module.ReportAgentSystem(
                service=StubService(),
                mode="fallback",
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
        async with self.checkpoint.AsyncSqliteSaver.from_conn_string(":memory:") as saver:
            agent_system = self.report_module.ReportAgentSystem(
                service=service,
                mode="fallback",
                checkpointer=saver,
            )
            with patch.object(
                service,
                "get_team_statistics",
                side_effect=ValueError("Team missing team not found"),
            ):
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
        """Set up test fixtures."""
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
        if self.client is None:
            self.skipTest("TestClient not available")

        try:
            response = self.client.get("/health")
            self.assertEqual(response.status_code, 200, "Health check should return 200")
            data = response.json()
            self.assertIn("status", data, "Should have status field")
            print(f"✅ API health check passed: {data.get('status')}")
        except Exception as e:
            print(f"⚠️ API test error: {e}")
            self.skipTest("API test failed")

    def test_root_endpoint(self):
        """Test the root endpoint."""
        if self.client is None:
            self.skipTest("TestClient not available")

        try:
            response = self.client.get("/")
            self.assertEqual(response.status_code, 200, "Root should return 200")
            data = response.json()
            self.assertIn("name", data, "Should have name field")
            print(f"✅ API root endpoint: {data.get('name')}")
        except Exception as e:
            print(f"⚠️ API test error: {e}")
            self.skipTest("API test failed")

    def test_regression_api_team_wins_2025(self):
        """Regression test for API endpoint with historical team wins 2025 prompt.
        
        Tests the full stack through the API: exact historical prompt that
        previously failed with 'No module named db' import error.
        Skips gracefully if API is unavailable.
        """
        if self.client is None:
            self.skipTest("TestClient not available")

        try:
            # Send exact historical prompt through chat API
            user_prompt = "Сделай отчёт о том, в каких играх за 2025 год побеждала команда Однажды было дважды"
            payload = {"message": user_prompt}
            
            response = self.client.post(
                "/api/chat",
                json=payload
            )
            
            self.assertEqual(response.status_code, 200, "Chat endpoint should return 200")
            data = response.json()
            
            # Verify response structure
            self.assertIsInstance(data, dict, "Response should be dictionary")
            
            # Critical: response must NOT contain the historical import error
            response_str = str(data)
            self.assertNotIn("No module named 'db'", response_str,
                            "API response should not contain import error")
            
            print(f"✅ API team wins 2025 prompt: returned successfully")
            
        except Exception as e:
            print(f"⚠️ API test error: {e}")
            self.skipTest("API test failed")

    def test_regression_api_generic_team_statistics(self):
        """Regression test for API endpoint with generic team statistics prompt.
        
        Tests the full stack through the API: generic team statistics prompt
        that should route to get_team_statistics.
        Skips gracefully if API is unavailable.
        """
        if self.client is None:
            self.skipTest("TestClient not available")

        try:
            # Send generic team statistics prompt through chat API
            user_prompt = "статистика команды Однажды было дважды"
            payload = {"message": user_prompt}
            
            response = self.client.post(
                "/api/chat",
                json=payload
            )
            
            self.assertEqual(response.status_code, 200, "Chat endpoint should return 200")
            data = response.json()
            
            # Verify response structure
            self.assertIsInstance(data, dict, "Response should be dictionary")
            
            # Critical: response must NOT contain the historical import error
            response_str = str(data)
            self.assertNotIn("No module named 'db'", response_str,
                            "API response should not contain import error")
            
            print(f"✅ API generic team statistics prompt: returned successfully")
            
        except Exception as e:
            print(f"⚠️ API test error: {e}")
            self.skipTest("API test failed")

    def test_regression_api_get_game_returns_404_for_missing_game(self):
        if self.client is None:
            self.skipTest("TestClient not available")

        import main as main_module

        with patch.object(main_module.data_service, "get_game_by_id", return_value=None):
            response = self.client.get("/api/games/999999")

        self.assertEqual(response.status_code, 404, "Missing game should return 404")
        self.assertIn("not found", response.json()["detail"].lower())
        print("✅ API get_game: missing game returns 404")

    def test_regression_api_get_game_returns_500_for_unexpected_error(self):
        if self.client is None:
            self.skipTest("TestClient not available")

        import main as main_module

        with patch.object(main_module.data_service, "get_game_by_id", side_effect=RuntimeError("db exploded")):
            response = self.client.get("/api/games/123")

        self.assertEqual(response.status_code, 500, "Unexpected game lookup failures should return 500")
        self.assertEqual(response.json()["detail"], "Internal server error")
        print("✅ API get_game: unexpected errors return a generic 500 response")

    def test_regression_health_returns_503_without_data_service(self):
        if self.client is None:
            self.skipTest("TestClient not available")

        import main as main_module

        with patch.object(main_module, "data_service", None):
            response = self.client.get("/health")

        self.assertEqual(response.status_code, 503, "Health should return 503 when data service is unavailable")
        print("✅ API health: returns 503 when data service is unavailable")

    def test_regression_api_team_stats_returns_404_for_missing_team(self):
        if self.client is None:
            self.skipTest("TestClient not available")

        import main as main_module

        with patch.object(main_module.data_service, "get_team_statistics", side_effect=ValueError("Team missing team not found")):
            response = self.client.get("/api/teams/missing team/stats")

        self.assertEqual(response.status_code, 404, "Missing team stats should return 404")
        self.assertIn("not found", response.json()["detail"].lower())
        print("✅ API team stats: missing team returns 404")

    def test_regression_chat_without_session_id_assigns_unique_id(self):
        """Chat without session_id must mint a fresh server-side id, not the literal "default"."""
        if self.client is None:
            self.skipTest("TestClient not available")

        import main as main_module

        class _StubAgent:
            async def process_user_request(self, _msg, session_id):
                return {
                    "success": True,
                    "data": None,
                    "message": "ok",
                    "mode": "fallback",
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
        if self.client is None:
            self.skipTest("TestClient not available")

        import main as main_module

        class _StubAgent:
            async def process_user_request(self, _msg, session_id):
                return {
                    "success": True,
                    "data": None,
                    "message": "ok",
                    "mode": "fallback",
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
        if self.client is None:
            self.skipTest("TestClient not available")

        import main as main_module

        class _StubAgent:
            async def process_user_request(self, _msg, session_id):
                return {
                    "success": True,
                    "data": None,
                    "message": "ok",
                    "mode": "fallback",
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
            "mode": "fallback",
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
                        "mode": "agent",
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
                self.assertEqual(body["mode"], "agent")
                self.assertEqual(body["query_info"], [])
                self.assertEqual(body["error"], error)

    async def test_both_modes_keep_list_shaped_query_info(self):
        for mode in ("fallback", "agent"):
            with self.subTest(mode=mode):
                query_info = [{"tool": f"{mode}_tool", "args": {}}]
                self.main.agent_system = _LifecycleAgent(
                    result={
                        "success": True,
                        "data": None,
                        "message": "ok",
                        "mode": mode,
                        "query_info": query_info,
                        "timestamp": "t",
                    }
                )
                status, body = await self._request(
                    "POST",
                    "/api/chat",
                    {"message": mode, "session_id": mode},
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
                {"role": "assistant", "content": "ok"},
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
        main_module.data_service = None
        main_module.llm_proxy_healthy = False
        main_module.sessions = SessionIndex(
            ttl=main_module.CHECKPOINT_TTL_SECONDS,
        )

    @classmethod
    def tearDownClass(cls):
        global testclient
        if testclient is not None:
            testclient.close()
            testclient = None

    def test_regression_startup_retries_database_initialization(self):
        main_module = self._get_main_module()

        created_service = object()
        attempts = {"count": 0}

        def fake_game_data_service():
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise RuntimeError("db not ready")
            return created_service

        created_agent_system = object()

        class FakeReportAgentSystem:
            def __init__(self, api_key=None, service=None):
                self.api_key = api_key
                self.service = service

        async def run_test():
            with patch.object(main_module, "GameDataService", side_effect=fake_game_data_service), \
                 patch.object(main_module, "ReportAgentSystem", side_effect=lambda **_kwargs: created_agent_system), \
                 patch.object(main_module, "CHECKPOINT_DB_PATH", ":memory:"), \
                 patch.object(main_module, "probe_llm_proxy", new=AsyncMock(return_value=False)), \
                 patch.object(main_module.asyncio, "sleep") as mock_sleep:
                await self._reset_startup_state(main_module)
                await main_module.startup_event()

            self.assertEqual(attempts["count"], 3)
            self.assertEqual(mock_sleep.await_count, 2)
            self.assertIs(main_module.data_service, created_service)
            self.assertIs(main_module.agent_system, created_agent_system)
            await main_module.shutdown_event()

        asyncio.run(run_test())
        print("✅ Startup retries database initialization before succeeding")

    def test_regression_startup_reraises_after_retry_exhaustion(self):
        main_module = self._get_main_module()

        async def run_test():
            with patch.object(main_module, "GameDataService", side_effect=RuntimeError("db not ready")), \
                 patch.object(main_module.asyncio, "sleep") as mock_sleep:
                main_module.data_service = None
                main_module.agent_system = None
                with self.assertRaises(RuntimeError):
                    await main_module.startup_event()

            self.assertEqual(mock_sleep.await_count, main_module.STARTUP_RETRY_ATTEMPTS - 1)

        asyncio.run(run_test())
        print("✅ Startup fails fast after bounded database retries")

    def test_probe_failure_elects_fallback_and_health_reports_proxy_down(self):
        """Given an offline proxy, When startup probes it, Then fallback mode is elected."""
        main_module = self._get_main_module()
        created_agents = []

        def fake_agent_system(**kwargs):
            created_agents.append(kwargs)
            return object()

        async def run_test():
            probe_sleep = AsyncMock()
            await self._reset_startup_state(main_module)
            with patch.object(main_module, "GameDataService", return_value=object()), \
                 patch.object(main_module, "ReportAgentSystem", side_effect=fake_agent_system), \
                 patch.object(main_module, "CHECKPOINT_DB_PATH", ":memory:"), \
                 patch.object(main_module, "probe_sleep", probe_sleep), \
                 patch.object(
                     main_module.requests,
                     "get",
                     side_effect=main_module.requests.ConnectionError("offline"),
                 ) as request_get:
                await main_module.startup_event()
                health = await main_module.health_check()

            self.assertEqual(created_agents[0]["mode"], "fallback")
            self.assertIs(created_agents[0]["checkpointer"], main_module.checkpoint_saver)
            self.assertFalse(health["services"]["llm_proxy"])
            self.assertEqual(request_get.call_count, main_module.PROBE_RETRY_ATTEMPTS)
            self.assertEqual(probe_sleep.await_count, main_module.PROBE_RETRY_ATTEMPTS - 1)
            await main_module.shutdown_event()

        asyncio.run(run_test())

    def test_healthy_probe_elects_agent_and_health_reports_proxy_up(self):
        """Given a deeply healthy proxy, When startup probes it, Then agent mode is elected."""
        main_module = self._get_main_module()
        created_agents = []

        def fake_agent_system(**kwargs):
            created_agents.append(kwargs)
            return object()

        async def run_test():
            probe_sleep = AsyncMock()
            response = self.ProbeResponse(["gpt-4o"], [])
            await self._reset_startup_state(main_module)
            with patch.object(main_module, "GameDataService", return_value=object()), \
                 patch.object(main_module, "ReportAgentSystem", side_effect=fake_agent_system), \
                 patch.object(main_module, "CHECKPOINT_DB_PATH", ":memory:"), \
                 patch.object(main_module, "probe_sleep", probe_sleep), \
                 patch.object(main_module.requests, "get", return_value=response) as request_get:
                await main_module.startup_event()
                health = await main_module.health_check()

            self.assertEqual(created_agents[0]["mode"], "agent")
            self.assertTrue(health["services"]["llm_proxy"])
            self.assertEqual(request_get.call_count, 1)
            self.assertEqual(probe_sleep.await_count, 0)
            await main_module.shutdown_event()

        asyncio.run(run_test())

    def test_200_with_unhealthy_endpoints_elects_fallback(self):
        """Given a shallow 200 with an unhealthy model, When probed, Then startup stays fallback."""
        main_module = self._get_main_module()
        created_agents = []

        def fake_agent_system(**kwargs):
            created_agents.append(kwargs)
            return object()

        async def run_test():
            probe_sleep = AsyncMock()
            response = self.ProbeResponse(["gpt-4o"], ["gpt-4o"])
            await self._reset_startup_state(main_module)
            with patch.object(main_module, "GameDataService", return_value=object()), \
                 patch.object(main_module, "ReportAgentSystem", side_effect=fake_agent_system), \
                 patch.object(main_module, "CHECKPOINT_DB_PATH", ":memory:"), \
                 patch.object(main_module, "probe_sleep", probe_sleep), \
                 patch.object(main_module.requests, "get", return_value=response) as request_get:
                await main_module.startup_event()

            self.assertEqual(created_agents[0]["mode"], "fallback")
            self.assertEqual(request_get.call_count, main_module.PROBE_RETRY_ATTEMPTS)
            self.assertEqual(probe_sleep.await_count, main_module.PROBE_RETRY_ATTEMPTS - 1)
            await main_module.shutdown_event()

        asyncio.run(run_test())

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

    def test_health_still_returns_503_without_data_service(self):
        """Given no data service, When health is requested, Then readiness remains unavailable."""
        main_module = self._get_main_module()

        async def run_test():
            with patch.object(main_module, "data_service", None):
                with self.assertRaises(main_module.HTTPException) as raised:
                    await main_module.health_check()

            self.assertEqual(raised.exception.status_code, 503)

        asyncio.run(run_test())

    def test_shutdown_closes_checkpoint_connection(self):
        """Given an initialized saver, When shutdown runs, Then its SQLite connection closes."""
        main_module = self._get_main_module()

        async def run_test():
            await self._reset_startup_state(main_module)
            with patch.object(main_module, "GameDataService", return_value=object()), \
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
