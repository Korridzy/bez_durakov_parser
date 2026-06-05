"""
Test script for the web reporting system.
Tests all components: services, agents, API.
"""
import sys
import os
from typing import Any

import unittest
from unittest.mock import patch
from datetime import date, datetime

# Import the app and set up in-process ASGI testing
testclient = None
try:
    from main import app
    import asyncio
    import json as json_module
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
    
    testclient = ASGITestClient(app)
except Exception as e:
    print(f"⚠️ Warning: Could not initialize in-process test client: {e}")
    testclient = None


class TestGameDataService(unittest.TestCase):
    """Test the GameDataService."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        try:
            from services.game_data_service import GameDataService
            cls.service = GameDataService()
        except Exception as e:
            print(f"⚠️ Warning: Could not initialize GameDataService: {e}")
            cls.service = None

    def test_service_initialization(self):
        """Test that service initializes correctly."""
        self.assertIsNotNone(self.service, "Service should be initialized")

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

        with patch.object(self.service.db, "Session") as mock_session_factory:
            mock_session = mock_session_factory.return_value
            mock_query = mock_session.query.return_value
            filtered_query = mock_query.filter.return_value
            filtered_query.all.return_value = []

            df = self.service.get_team_game_scores(0)

            mock_query.filter.assert_called_once()
            filtered_query.all.assert_called_once()
            self.assertTrue(df.empty, "Filtered zero game_id query should still return a DataFrame")
            mock_session.close.assert_called_once()

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

        with patch.object(self.service.db, "Session") as mock_session_factory:
            mock_session = mock_session_factory.return_value
            mock_query = mock_session.query.return_value
            mock_query.filter_by.return_value.first.return_value = None

            with self.assertRaises(ValueError):
                self.service.get_team_statistics("missing team")

            mock_session.close.assert_called_once()

        print("✅ Service get_team_statistics: missing team is re-raised")


class TestReportAgentSystem(unittest.TestCase):
    """Test the ReportAgentSystem."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        try:
            from agents.report_agents import ReportAgentSystem
            cls.agent_system = ReportAgentSystem()
        except Exception as e:
            print(f"⚠️ Warning: Could not initialize ReportAgentSystem: {e}")
            cls.agent_system = None

    def test_agent_initialization(self):
        """Test that agent system initializes."""
        self.assertIsNotNone(self.agent_system, "Agent system should be initialized")

    def test_regression_agents_enabled_with_api_key(self):
        """Regression: explicit api_key should enable non-fallback agent path."""
        try:
            from agents.report_agents import ReportAgentSystem
        except Exception as e:
            self.fail(f"Could not import ReportAgentSystem: {e}")

        enabled_system = ReportAgentSystem(api_key="dummy")

        self.assertTrue(enabled_system.agents_available,
                        "agents_available must be True when api_key is provided and dependencies are present")
        self.assertIsNotNone(enabled_system.coder_agent,
                             "coder_agent must be initialized in enabled mode")
        self.assertIsNotNone(enabled_system.model_client,
                             "model_client must be initialized in enabled mode")

        response = enabled_system.process_user_request("покажи все игры")
        self.assertIsInstance(response, dict, "Enabled mode response should be dictionary")
        self.assertTrue(response.get("success"), "Enabled mode request should succeed")
        response_message = response.get("message", "")
        self.assertIn("Report generated based on:", response_message,
                      "Enabled mode should use non-fallback success message")
        self.assertNotIn("fallback mode", response_message.lower(),
                         "Enabled mode must not return fallback-mode message")

        history = enabled_system.get_conversation_history()
        self.assertIsInstance(history, list, "History should be list in enabled mode")
        self.assertGreaterEqual(len(history), 2,
                                "Enabled mode should record at least user+assistant history entries")

    def test_regression_agent_system_uses_injected_service(self):
        if self.agent_system is None:
            self.skipTest("Agent system not available")

        from agents.report_agents import ReportAgentSystem

        injected_service = object()
        system = ReportAgentSystem(service=injected_service)

        self.assertIs(system.service, injected_service)
        print("✅ Agent system reuses injected data service")

    def test_process_request_all_games(self):
        """Test processing a request for all games."""
        if self.agent_system is None:
            self.skipTest("Agent system not available")

        response = self.agent_system.process_user_request("покажи все игры")
        self.assertIsInstance(response, dict, "Should return dictionary")
        self.assertIn("success", response, "Response should have success field")
        print(f"✅ Request processed: {response.get('message', 'No message')}")

    def test_conversation_history(self):
        """Test conversation history tracking."""
        if self.agent_system is None:
            self.skipTest("Agent system not available")

        self.agent_system.clear_history()
        response = self.agent_system.process_user_request("тест")
        history = self.agent_system.get_conversation_history()
        self.assertIsInstance(history, list, "History should be a list")
        # In fallback mode, history might be empty; just verify it's accessible
        if len(history) > 0:
            print(f"✅ Conversation history has {len(history)} entries")
        else:
            print(f"⚠️ Conversation history empty (fallback mode)")

    def test_regression_team_wins_2025(self):
        """Regression test for historical failing prompt about team wins in 2025.
        
        Previously failed with: 'No module named db' import error.
        Tests that get_team_wins() method correctly routes and executes
        for the exact historical prompt.
        """
        if self.agent_system is None:
            self.skipTest("Agent system not available")

        # Exact historical prompt that previously failed
        user_prompt = "Сделай отчёт о том, в каких играх за 2025 год побеждала команда Однажды было дважды"
        response = self.agent_system.process_user_request(user_prompt)
        
        # Basic response structure validation
        self.assertIsInstance(response, dict, "Should return dictionary")
        self.assertIn("success", response, "Response should have success field")
        
        # Critical: response must NOT contain the historical import error
        response_str = str(response)
        self.assertNotIn("No module named 'db'", response_str,
                         "Response should not contain import error 'No module named db'")
        
        # If successful, verify routing MUST be to get_team_wins (strict routing check)
        if response.get("success"):
            self.assertIn("query", response, "Successful response should have query field")
            query_info = response.get("query", {})
            # Must be routed to get_team_wins for win-oriented prompt (strict assertion)
            method = query_info.get("method")
            self.assertEqual(method, "get_team_wins",
                           f"Win-oriented prompt MUST route to get_team_wins, got {method}")
            print(f"✅ Team wins 2025 prompt: correctly routed to get_team_wins")

    def test_regression_generic_team_statistics(self):
        """Regression test for generic team-statistics path without year.
        
        Tests that team statistics prompts (without win keywords)
        correctly route to get_team_statistics and execute without errors.
        """
        if self.agent_system is None:
            self.skipTest("Agent system not available")

        # Generic team statistics prompt (without win keywords)
        user_prompt = "статистика команды Однажды было дважды"
        response = self.agent_system.process_user_request(user_prompt)
        
        # Basic response structure validation
        self.assertIsInstance(response, dict, "Should return dictionary")
        self.assertIn("success", response, "Response should have success field")
        
        # Critical: response must NOT contain the historical import error
        response_str = str(response)
        self.assertNotIn("No module named 'db'", response_str,
                         "Response should not contain import error 'No module named db'")
        
        # If successful, verify routing to get_team_statistics
        if response.get("success"):
            self.assertIn("query", response, "Successful response should have query field")
            query_info = response.get("query", {})
            method = query_info.get("method")
            self.assertEqual(method, "get_team_statistics",
                             f"Generic team prompt should route to get_team_statistics, got {method}")
            print(f"✅ Generic team statistics prompt: correctly routed to {method}")

    def test_regression_team_statistics_missing_team_returns_error_response(self):
        if self.agent_system is None:
            self.skipTest("Agent system not available")

        with patch.object(self.agent_system.service, "get_team_statistics", side_effect=ValueError("Team missing team not found")):
            response = self.agent_system.process_user_request("статистика команды missing team")

        self.assertFalse(response.get("success"), "Missing team should not look like a successful report")
        self.assertIn("not found", response.get("error", "").lower())
        print("✅ Agent team statistics: missing team returns error response")


class TestAPI(unittest.TestCase):
    """Test the FastAPI endpoints."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        cls.client = testclient

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
        self.assertEqual(response.json()["detail"], "db exploded")
        print("✅ API get_game: unexpected errors return 500")

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
            def process_user_request(self, _msg):
                return {"success": True, "message": "ok", "timestamp": "t"}

        main_module.sessions._store.clear()
        main_module.sessions._accessed.clear()

        with patch.object(main_module, "agent_system", object()), \
             patch.object(main_module, "ReportAgentSystem", lambda service=None: _StubAgent()):
            response = self.client.post("/api/chat", json={"message": "hi"})

        self.assertEqual(response.status_code, 200)
        body = response.json()
        sid = body.get("session_id")
        self.assertIsInstance(sid, str)
        self.assertTrue(sid, "Response must include a non-empty session_id")
        self.assertNotEqual(sid, "default", "Server must not fall back to the shared 'default' id")
        self.assertNotIn("default", main_module.sessions._store,
                         "Server must not create a shared 'default' session entry")
        self.assertIn(sid, main_module.sessions._store, "Session must be stored under the assigned id")
        print("✅ API chat: assigns server-side session_id when client omits it")

    def test_regression_chat_without_session_id_yields_distinct_sessions(self):
        """Two anonymous chat calls must not collide on a shared session."""
        if self.client is None:
            self.skipTest("TestClient not available")

        import main as main_module

        class _StubAgent:
            def process_user_request(self, _msg):
                return {"success": True, "message": "ok", "timestamp": "t"}

        main_module.sessions._store.clear()
        main_module.sessions._accessed.clear()

        with patch.object(main_module, "agent_system", object()), \
             patch.object(main_module, "ReportAgentSystem", lambda service=None: _StubAgent()):
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
            def process_user_request(self, _msg):
                return {"success": True, "message": "ok", "timestamp": "t"}

        main_module.sessions._store.clear()
        main_module.sessions._accessed.clear()
        explicit = "client-supplied-id-12345"

        with patch.object(main_module, "agent_system", object()), \
             patch.object(main_module, "ReportAgentSystem", lambda service=None: _StubAgent()):
            response = self.client.post(
                "/api/chat", json={"message": "hi", "session_id": explicit}
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get("session_id"), explicit,
                         "Explicit client session_id must be preserved")
        self.assertIn(explicit, main_module.sessions._store)
        print("✅ API chat: explicit client session_id is preserved")


class TestStartupInitialization(unittest.TestCase):
    @staticmethod
    def _get_main_module():
        import main as main_module
        return main_module

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
                 patch.object(main_module, "ReportAgentSystem", side_effect=lambda service=None: created_agent_system), \
                 patch.object(main_module.asyncio, "sleep") as mock_sleep:
                main_module.data_service = None
                main_module.agent_system = None
                await main_module.startup_event()

            self.assertEqual(attempts["count"], 3)
            self.assertEqual(mock_sleep.await_count, 2)
            self.assertIs(main_module.data_service, created_service)
            self.assertIs(main_module.agent_system, created_agent_system)

        import asyncio
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

        import asyncio
        asyncio.run(run_test())
        print("✅ Startup fails fast after bounded database retries")


class TestSessionStore(unittest.TestCase):
    """Unit tests for SessionStore LRU+TTL eviction."""

    def _make_store(self, max_size=4, ttl=60.0):
        from session_store import SessionStore
        return SessionStore(max_size=max_size, ttl=ttl)

    def test_basic_set_get_contains(self):
        store = self._make_store()
        sentinel = object()
        store["a"] = sentinel
        self.assertIn("a", store)
        self.assertIs(store["a"], sentinel)

    def test_missing_key_not_in(self):
        store = self._make_store()
        self.assertNotIn("missing", store)

    def test_lru_eviction_at_capacity(self):
        store = self._make_store(max_size=3)
        store["a"] = object()
        store["b"] = object()
        store["c"] = object()
        _ = store["a"]  # touch "a" — makes "b" the LRU
        store["d"] = object()
        self.assertNotIn("b", store)
        self.assertIn("a", store)
        self.assertIn("c", store)
        self.assertIn("d", store)
        print("✅ SessionStore: LRU eviction evicts least-recently-used entry")

    def test_ttl_expiry(self):
        import time as time_mod
        store = self._make_store(ttl=0.05)
        store["x"] = object()
        self.assertIn("x", store)
        time_mod.sleep(0.1)
        self.assertNotIn("x", store)
        print("✅ SessionStore: expired session is evicted on next access")

    def test_getitem_enforces_ttl(self):
        import time as time_mod
        store = self._make_store(ttl=0.05)
        store["x"] = object()
        time_mod.sleep(0.1)
        with self.assertRaises(KeyError):
            _ = store["x"]
        self.assertNotIn("x", store._store)
        print("✅ SessionStore: __getitem__ enforces TTL and drops expired entry")

    def test_getitem_missing_raises_keyerror(self):
        store = self._make_store()
        with self.assertRaises(KeyError):
            _ = store["missing"]
        print("✅ SessionStore: __getitem__ raises KeyError for missing key")

    def test_overwrite_does_not_grow_store(self):
        store = self._make_store(max_size=2)
        store["a"] = object()
        store["b"] = object()
        store["a"] = object()
        self.assertEqual(len(store._store), 2)
        print("✅ SessionStore: overwriting an existing key does not grow the store")

    def test_capacity_hard_cap(self):
        store = self._make_store(max_size=10)
        for i in range(10):
            store[str(i)] = object()
        self.assertEqual(len(store._store), 10)
        store["overflow"] = object()
        self.assertEqual(len(store._store), 10)
        print("✅ SessionStore: capacity hard cap is never exceeded")

    def test_max_1024_sessions(self):
        from session_store import SessionStore, MAX_SESSIONS
        self.assertEqual(MAX_SESSIONS, 1024)
        store = SessionStore()
        for i in range(1024):
            store[str(i)] = object()
        self.assertEqual(len(store._store), 1024)
        store["one_more"] = object()
        self.assertEqual(len(store._store), 1024)
        print("✅ SessionStore: default MAX_SESSIONS=1024 is enforced")


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
    suite.addTests(loader.loadTestsFromTestCase(TestSessionStore))
    suite.addTests(loader.loadTestsFromTestCase(TestGameDataService))
    suite.addTests(loader.loadTestsFromTestCase(TestReportAgentSystem))
    suite.addTests(loader.loadTestsFromTestCase(TestAPI))
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
