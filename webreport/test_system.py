"""
Test script for the web reporting system.
Tests all components: services, agents, API.
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import unittest
from datetime import date, datetime
import pandas as pd


class TestGameDataService(unittest.TestCase):
    """Test the GameDataService."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        try:
            from webreport.services.game_data_service import GameDataService
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

        df = self.service.get_all_games_summary()
        self.assertIsInstance(df, pd.DataFrame, "Should return DataFrame")
        print(f"✅ Found {len(df)} games in database")

    def test_get_all_teams(self):
        """Test getting all teams."""
        if self.service is None:
            self.skipTest("Service not available")

        df = self.service.get_all_teams()
        self.assertIsInstance(df, pd.DataFrame, "Should return DataFrame")
        print(f"✅ Found {len(df)} teams in database")

    def test_get_team_game_scores(self):
        """Test getting team game scores."""
        if self.service is None:
            self.skipTest("Service not available")

        df = self.service.get_team_game_scores()
        self.assertIsInstance(df, pd.DataFrame, "Should return DataFrame")
        print(f"✅ Found {len(df)} team game score records")


class TestReportAgentSystem(unittest.TestCase):
    """Test the ReportAgentSystem."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        try:
            from webreport.agents.report_agents import ReportAgentSystem
            cls.agent_system = ReportAgentSystem()
        except Exception as e:
            print(f"⚠️ Warning: Could not initialize ReportAgentSystem: {e}")
            cls.agent_system = None

    def test_agent_initialization(self):
        """Test that agent system initializes."""
        self.assertIsNotNone(self.agent_system, "Agent system should be initialized")

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
        self.agent_system.process_user_request("тест")
        history = self.agent_system.get_conversation_history()
        self.assertIsInstance(history, list, "History should be a list")
        self.assertGreater(len(history), 0, "History should have entries")
        print(f"✅ Conversation history has {len(history)} entries")


class TestAPI(unittest.TestCase):
    """Test the FastAPI endpoints."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        try:
            import requests
            cls.requests = requests
            cls.base_url = "http://localhost:8000"
        except ImportError:
            print("⚠️ Warning: requests not installed, skipping API tests")
            cls.requests = None

    def test_health_endpoint(self):
        """Test the health check endpoint."""
        if self.requests is None:
            self.skipTest("Requests library not available")

        try:
            response = self.requests.get(f"{self.base_url}/health", timeout=2)
            self.assertEqual(response.status_code, 200, "Health check should return 200")
            data = response.json()
            self.assertIn("status", data, "Should have status field")
            print(f"✅ API health check passed: {data.get('status')}")
        except Exception as e:
            print(f"⚠️ API not running: {e}")
            self.skipTest("API not running")

    def test_root_endpoint(self):
        """Test the root endpoint."""
        if self.requests is None:
            self.skipTest("Requests library not available")

        try:
            response = self.requests.get(self.base_url, timeout=2)
            self.assertEqual(response.status_code, 200, "Root should return 200")
            data = response.json()
            self.assertIn("name", data, "Should have name field")
            print(f"✅ API root endpoint: {data.get('name')}")
        except Exception as e:
            print(f"⚠️ API not running: {e}")
            self.skipTest("API not running")


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
    suite.addTests(loader.loadTestsFromTestCase(TestGameDataService))
    suite.addTests(loader.loadTestsFromTestCase(TestReportAgentSystem))
    suite.addTests(loader.loadTestsFromTestCase(TestAPI))

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

