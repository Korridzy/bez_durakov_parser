"""
Tests for the LangGraph report agent.

Kept import-light on purpose: no langgraph/langchain imports at module level,
so this module stays runnable before the agent dependencies land in the image.
Heavy imports belong inside the setUp of the classes that need them.

Case families live in sibling test_agent_*.py modules and are aggregated here,
because the plan addresses every acceptance command as test_agent.<Class>.
The families are reached through their module object rather than imported by
name, so unittest.main() below collects each family exactly once - through the
aggregate - instead of a second standalone time.
"""
import importlib
import os
import sys
import unittest
from unittest.mock import patch

# Parent of the mounted bd_shared directory, same convention as main.py:16
sys.path.insert(0, '/')

registry_dispatch = importlib.import_module("test_agent_registry_dispatch")
registry_shapes = importlib.import_module("test_agent_registry_shapes")
tools_commands = importlib.import_module("test_agent_tools_commands")
tools_metadata = importlib.import_module("test_agent_tools_metadata")
graph_cases = importlib.import_module("test_agent_graph")
report_agent_cases = importlib.import_module("test_agent_report_agent")
checkpointer_cases = importlib.import_module("test_agent_checkpointer")
knowledge_cases = importlib.import_module("test_agent_knowledge")
knowledge_config_cases = importlib.import_module("test_agent_config")
net_guard = importlib.import_module("test_net_guard")

CHECKPOINT_PATH_ENV = "BD_CHECKPOINT_DB_PATH"


def setUpModule():
    """Offline suite: only loopback and the Compose database host are reachable."""
    net_guard.install()


class TestAgentConfig(unittest.TestCase):
    """Agent settings exposed by bd_shared.config."""

    def _reload_config(self, env=None, unset=()):
        """Reload bd_shared.config under a temporary environment.

        bd_shared becomes importable only through the runtime path bootstrap above,
        so the module is resolved dynamically rather than by a static import statement.
        """
        config_module = importlib.import_module("bd_shared.config")

        with patch.dict(os.environ, {"BD_CONFIG_FILE": "config.toml", **(env or {})}):
            for name in unset:
                os.environ.pop(name, None)
            return importlib.reload(config_module)

    def tearDown(self):
        # Reloads above mutate the shared module object; restore ambient state.
        self._reload_config()

    def test_agent_bounds_defaults(self):
        """Given no overrides, When config loads, Then agent bounds are the spec integers."""
        config_module = self._reload_config()

        self.assertEqual(config_module.AGENT_RECURSION_LIMIT, 8)
        self.assertEqual(config_module.AGENT_TIMEOUT_SECONDS, 120)
        self.assertEqual(config_module.AGENT_MAX_ROWS_PER_FETCH, 256)
        self.assertEqual(config_module.AGENT_MAX_ROWS_PER_RUN, 1024)
        self.assertEqual(config_module.CHECKPOINT_TTL_SECONDS, 3600)

    def test_agent_bounds_are_integers(self):
        """Given no overrides, When config loads, Then bounds are int, not str."""
        config_module = self._reload_config()

        for name in (
            "AGENT_RECURSION_LIMIT",
            "AGENT_TIMEOUT_SECONDS",
            "AGENT_MAX_ROWS_PER_FETCH",
            "AGENT_MAX_ROWS_PER_RUN",
            "CHECKPOINT_TTL_SECONDS",
            "PROBE_RETRY_ATTEMPTS",
            "PROBE_RETRY_DELAY_SECONDS",
            "PROBE_REQUEST_TIMEOUT_SECONDS",
            "LLM_MAX_RETRIES",
            "LLM_REQUEST_TIMEOUT_SECONDS",
        ):
            with self.subTest(constant=name):
                self.assertIsInstance(getattr(config_module, name), int)

    def test_retry_policy_defaults(self):
        """Given no overrides, When config loads, Then probe and LLM retry budgets are the spec integers."""
        config_module = self._reload_config()

        self.assertEqual(config_module.PROBE_RETRY_ATTEMPTS, 5)
        self.assertEqual(config_module.PROBE_RETRY_DELAY_SECONDS, 2)
        self.assertEqual(config_module.PROBE_REQUEST_TIMEOUT_SECONDS, 10)
        self.assertEqual(config_module.LLM_MAX_RETRIES, 0)
        self.assertEqual(config_module.LLM_REQUEST_TIMEOUT_SECONDS, 60)

    def test_alternate_config_file_supplies_its_own_values(self):
        """Given BD_CONFIG_FILE selects test_config.toml, When config reloads, Then that file's
        values win over the in-code defaults, and BD_DOCKER picks its docker_url."""
        config_module = self._reload_config(
            {"BD_CONFIG_FILE": "test_config.toml", "BD_DOCKER": "true"}
        )

        self.assertEqual(config_module.PROBE_RETRY_ATTEMPTS, 4)
        self.assertEqual(config_module.PROBE_RETRY_DELAY_SECONDS, 1)
        self.assertEqual(config_module.PROBE_REQUEST_TIMEOUT_SECONDS, 9)
        self.assertEqual(config_module.LLM_MAX_RETRIES, 1)
        self.assertEqual(config_module.LLM_REQUEST_TIMEOUT_SECONDS, 59)
        self.assertEqual(
            config_module.DATABASE_URL,
            "mysql+pymysql://root:devpass@mysql:3306/bez_durakov_test",
        )

    def test_llm_proxy_defaults(self):
        """Given no overrides, When config loads, Then proxy URL and model match the spec."""
        config_module = self._reload_config()

        self.assertEqual(config_module.LITELLM_BASE_URL, "http://litellm:4000")
        self.assertEqual(config_module.AGENT_MODEL, "gpt-4o")

    def test_checkpoint_db_path_default(self):
        """Given BD_CHECKPOINT_DB_PATH is absent, When config loads, Then the config default wins."""
        config_module = self._reload_config(unset=(CHECKPOINT_PATH_ENV,))

        self.assertEqual(config_module.CHECKPOINT_DB_PATH, "/data/checkpoints.db")

    def test_checkpoint_db_path_env_override(self):
        """Given BD_CHECKPOINT_DB_PATH is set, When config loads, Then the env value wins."""
        config_module = self._reload_config({CHECKPOINT_PATH_ENV: "/tmp/x.db"})

        self.assertEqual(config_module.CHECKPOINT_DB_PATH, "/tmp/x.db")


class TestRegistry(
    registry_dispatch.RegistryDispatchTests,
    registry_shapes.RegistryShapeTests,
):
    """ToolRegistry: the single dispatch and normalization surface over GameDataService."""


class TestTools(
    tools_metadata.ToolMetadataTests,
    tools_commands.ToolCommandTests,
):
    """Bounded LangGraph tools over ToolRegistry, exercised through ToolNode."""


class TestGraph(graph_cases.GraphTests):
    """Bounded sequential ReAct graph exercised with an offline scripted model."""


class TestKnowledgeConfig(knowledge_config_cases.KnowledgeConfigTests):
    pass


class TestKnowledge(knowledge_cases.KnowledgeTypesTests):
    pass


class TestReportAgentSystem(report_agent_cases.ReportAgentSystemTests):
    """Fixed-mode report adapter with frozen fallback and checkpoint continuity."""


class TestCheckpointer(checkpointer_cases.TestCheckpointerCases):
    pass


class TestPrompt(checkpointer_cases.TestPromptCases):
    pass

if __name__ == "__main__":
    unittest.main()
