"""
Shared fixtures for the agent test families.

Import-light on purpose: no langgraph/langchain/pandas imports at module level,
so importing this module stays safe outside the backend image. Heavy imports are
resolved dynamically in setUpClass of the case bases defined here.
"""
import importlib
import threading
import unittest
from datetime import date
from typing import Any

TOOL_NAMES = (
    "get_all_games_summary",
    "get_game_by_id",
    "get_games_by_date_range",
    "get_team_game_scores",
    "get_all_teams",
    "get_team_statistics",
    "get_team_wins",
    "get_top_teams",
)

TOOL_PARAMS = {
    "get_all_games_summary": (),
    "get_game_by_id": ("game_id",),
    "get_games_by_date_range": ("start_date", "end_date"),
    "get_team_game_scores": ("game_id",),
    "get_all_teams": (),
    "get_team_statistics": ("team_name",),
    "get_team_wins": ("team_name", "year"),
    "get_top_teams": ("limit",),
}


class StubService:
    """Test double for GameDataService with byte-identical signatures.

    ToolRegistry introspects these signatures at construction and validates
    caller arguments against them, so a signature drift here would silently
    weaken every dispatch assertion. RegistryDispatchTests.test_stub_mirrors_real_service
    pins the double against the real class to keep that honest.
    """

    def __init__(self):
        self.calls = []
        self.results = {}
        self.raises = {}
        self.call_threads = []

    def _record(self, name, kwargs):
        self.calls.append((name, kwargs))
        self.call_threads.append(threading.get_ident())
        if name in self.raises:
            raise self.raises[name]
        return self.results.get(name)

    def get_all_games_summary(self):
        return self._record("get_all_games_summary", {})

    def get_game_by_id(self, game_id):
        return self._record("get_game_by_id", {"game_id": game_id})

    def get_games_by_date_range(self, start_date, end_date=None):
        return self._record(
            "get_games_by_date_range",
            {"start_date": start_date, "end_date": end_date},
        )

    def get_team_game_scores(self, game_id=None):
        return self._record("get_team_game_scores", {"game_id": game_id})

    def get_all_teams(self):
        return self._record("get_all_teams", {})

    def get_team_statistics(self, team_name):
        return self._record("get_team_statistics", {"team_name": team_name})

    def get_team_wins(self, team_name, year=None):
        return self._record("get_team_wins", {"team_name": team_name, "year": year})

    def get_top_teams(self, limit=10):
        return self._record("get_top_teams", {"limit": limit})


class RegistryCaseBase(unittest.IsolatedAsyncioTestCase):
    """Fixture base for every ToolRegistry case family.

    Carries no test methods of its own: the families in the sibling
    test_agent_registry_*.py modules subclass it, and test_agent.TestRegistry
    aggregates those families so the plan's acceptance path keeps working.
    """

    def __init__(self, methodName: str = "runTest"):
        super().__init__(methodName)
        # Declared here so the fixture attributes exist from construction; setUp
        # below is still what builds the per-test values. ToolRegistry is imported
        # dynamically in setUpClass, so no static type is available for `registry`.
        self.service: StubService = StubService()
        self.registry: Any = None
        self.dispatch_cases: dict[str, dict[str, Any]] = {}

    @classmethod
    def setUpClass(cls):
        cls.pd = importlib.import_module("pandas")
        cls.numpy = importlib.import_module("numpy")
        registry_module = importlib.import_module("agent.registry")
        cls.ToolRegistry = registry_module.ToolRegistry
        cls.ToolError = registry_module.ToolError

    def setUp(self):
        self.service = StubService()
        self.registry = self.ToolRegistry(self.service)
        # Every parameter is supplied explicitly, so the recorded kwargs can be
        # compared for identity with the requested args without defaults masking drift.
        self.dispatch_cases = {
            "get_all_games_summary": {},
            "get_game_by_id": {"game_id": 7},
            "get_games_by_date_range": {
                "start_date": date(2025, 1, 1),
                "end_date": date(2025, 12, 31),
            },
            "get_team_game_scores": {"game_id": 3},
            "get_all_teams": {},
            "get_team_statistics": {"team_name": "Однажды было дважды"},
            "get_team_wins": {"team_name": "Однажды было дважды", "year": 2025},
            "get_top_teams": {"limit": 5},
        }
