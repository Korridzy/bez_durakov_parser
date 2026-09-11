"""
ToolRegistry dispatch, argument validation and error-mapping cases.

Aggregated into test_agent.TestRegistry, which is the public path the plan's
acceptance commands use.
"""
import importlib
import inspect
import threading
import typing
import unittest
from datetime import date
from unittest.mock import patch

# Sibling modules resolve through the container's /app entry, not through a
# static path the host checker can model - same convention as bd_shared imports.
_support = importlib.import_module("test_agent_support")
TOOL_NAMES = _support.TOOL_NAMES
TOOL_PARAMS = _support.TOOL_PARAMS
StubService = _support.StubService
RegistryCaseBase = _support.RegistryCaseBase


class RegistryDispatchTests(RegistryCaseBase):

    def test_names_are_exactly_the_eight_service_tools(self):
        """Given a registry, When names is read, Then it is a frozenset of the 8 method names."""
        self.assertIsInstance(self.registry.names, frozenset)
        self.assertEqual(self.registry.names, frozenset(TOOL_NAMES))

    def test_param_specs_carry_each_methods_parameter_names(self):
        """Given a registry, When param_specs is read, Then each tool lists its parameters in order."""
        self.assertEqual(set(self.registry.param_specs), set(TOOL_NAMES))
        for name, expected in TOOL_PARAMS.items():
            with self.subTest(tool=name):
                self.assertEqual(tuple(self.registry.param_specs[name]), expected)

    def test_stub_mirrors_real_service(self):
        """Given the real GameDataService, When signatures are compared, Then the double matches."""
        service_module = importlib.import_module("bd_shared.tools.bez_durakov")

        for name in TOOL_NAMES:
            with self.subTest(tool=name):
                real_method = getattr(service_module.GameDataService, name)
                stub_method = getattr(StubService, name)
                real = inspect.signature(real_method)
                stub = inspect.signature(stub_method)
                self.assertEqual(
                    list(real.parameters)[1:],
                    list(stub.parameters)[1:],
                )

    def test_stub_carries_the_docstrings_and_hints_discovery_requires(self):
        """Given discovery's rules, When the double is inspected, Then it satisfies them like the real class.

        Discovery refuses a method without a docstring or with an unannotated parameter, so a
        double that lost either would fail every registry family at construction rather than
        at the assertion that cares.
        """
        service_module = importlib.import_module("bd_shared.tools.bez_durakov")

        for name in TOOL_NAMES:
            with self.subTest(tool=name):
                real_method = getattr(service_module.GameDataService, name)
                stub_method = getattr(StubService, name)

                self.assertTrue(inspect.getdoc(real_method))
                self.assertTrue(inspect.getdoc(stub_method))

                real_hints = typing.get_type_hints(real_method)
                stub_hints = typing.get_type_hints(stub_method)
                real_hints.pop("return", None)
                stub_hints.pop("return", None)
                self.assertEqual(real_hints, stub_hints)

    def test_names_follow_the_discovered_service_rather_than_a_fixed_list(self):
        """Given a service with a different method set, When a registry is built, Then names follow it."""

        class NarrowService:
            """A service that shares no method name with the default one."""

            def list_stations(self) -> dict:
                """Return every station."""
                return {}

            def station_total(self, station: str) -> dict:
                """Return the total for one station."""
                return {"station": station}

            def _helper(self) -> None:
                """Underscored, so never a tool."""

        registry = self.ToolRegistry(NarrowService())

        self.assertEqual(registry.names, frozenset({"list_stations", "station_total"}))
        self.assertEqual(registry.param_specs["station_total"], ("station",))
        self.assertEqual(registry.param_specs["list_stations"], ())

    async def test_execute_raw_dispatches_identical_kwargs_for_all_eight(self):
        """Given each tool, When execute_raw runs, Then the service receives the same kwargs."""
        for name, args in self.dispatch_cases.items():
            with self.subTest(tool=name):
                self.service.calls.clear()
                await self.registry.execute_raw(name, dict(args))

                self.assertEqual(self.service.calls, [(name, args)])

    async def test_execute_raw_preserves_service_defaults_for_omitted_args(self):
        """Given omitted optional args, When execute_raw runs, Then service defaults apply."""
        await self.registry.execute_raw("get_top_teams", {})

        self.assertEqual(self.service.calls, [("get_top_teams", {"limit": 10})])

    async def test_execute_raw_runs_off_the_event_loop(self):
        """Given a sync service method, When execute_raw runs, Then it executes on a worker thread."""
        await self.registry.execute_raw("get_all_teams", {})

        self.assertNotEqual(self.service.call_threads, [threading.get_ident()])

    async def test_execute_normalized_converts_off_the_event_loop(self):
        """Given a DataFrame result, When execute_normalized runs, Then to_dict leaves the loop thread."""
        conversion_threads = []

        class RecordingFrame(self.pd.DataFrame):
            @property
            def _constructor(self):
                return RecordingFrame

            def to_dict(self, *args, **kwargs):
                conversion_threads.append(threading.get_ident())
                return super().to_dict(*args, **kwargs)

        self.service.results["get_all_games_summary"] = RecordingFrame([{"game_id": 1}])

        records, cols = await self.registry.execute_normalized("get_all_games_summary", {})

        self.assertEqual(records, [{"game_id": 1}])
        self.assertEqual(cols, ["game_id"])
        self.assertEqual(len(conversion_threads), 1)
        self.assertNotIn(threading.get_ident(), conversion_threads)

    async def test_execute_response_converts_off_the_event_loop(self):
        """Given a frame-like result, When execute_response runs, Then to_dict leaves the loop thread."""
        conversion_threads = []

        class RecordingResult:
            def to_dict(self, orient):
                conversion_threads.append(threading.get_ident())
                return [{"team_name": "X", "orient": orient}]

        self.service.results["get_top_teams"] = RecordingResult()

        response = await self.registry.execute_response("get_top_teams", {"limit": 1})

        self.assertEqual(response, [{"team_name": "X", "orient": "records"}])
        self.assertEqual(len(conversion_threads), 1)
        self.assertNotIn(threading.get_ident(), conversion_threads)

    async def test_execute_raw_resolves_the_method_late(self):
        """Given a method patched after construction, When execute_raw runs, Then the patch is used."""
        patched_calls = []

        def patched(limit=10):
            patched_calls.append(limit)
            return None

        with patch.object(self.service, "get_top_teams", patched):
            await self.registry.execute_raw("get_top_teams", {"limit": 3})

        self.assertEqual(patched_calls, [3])
        self.assertEqual(self.service.calls, [])

    async def test_execute_raw_coerces_iso_dates_for_date_range(self):
        """Given ISO date strings, When get_games_by_date_range runs, Then date objects arrive."""
        await self.registry.execute_raw(
            "get_games_by_date_range",
            {"start_date": "2025-01-01", "end_date": "2025-12-31"},
        )

        _, kwargs = self.service.calls[0]
        self.assertEqual(kwargs["start_date"], date(2025, 1, 1))
        self.assertEqual(kwargs["end_date"], date(2025, 12, 31))
        self.assertIs(type(kwargs["start_date"]), date)
        self.assertIs(type(kwargs["end_date"]), date)

    async def test_execute_raw_leaves_other_tools_string_args_untouched(self):
        """Given a date-like string on another tool, When it runs, Then no coercion happens."""
        await self.registry.execute_raw("get_team_statistics", {"team_name": "2025-01-01"})

        self.assertEqual(self.service.calls, [("get_team_statistics", {"team_name": "2025-01-01"})])

    async def test_execute_raw_rejects_malformed_iso_date(self):
        """Given an unparsable date string, When execute_raw runs, Then ToolError is raised."""
        with self.assertRaises(self.ToolError):
            await self.registry.execute_raw(
                "get_games_by_date_range",
                {"start_date": "31-12-2025"},
            )

        self.assertEqual(self.service.calls, [])

    def test_validate_args_accepts_known_parameters(self):
        """Given supported kwargs, When validate_args runs, Then it does not raise."""
        self.registry.validate_args("get_team_wins", {"team_name": "X", "year": 2025})

    def test_validate_args_rejects_unknown_parameter(self):
        """Given an unsupported kwarg, When validate_args runs, Then ToolError names it."""
        with self.assertRaises(self.ToolError) as caught:
            self.registry.validate_args("get_top_teams", {"bogus_kw": 1})

        self.assertIn("bogus_kw", str(caught.exception))

    def test_validate_args_rejects_unknown_tool(self):
        """Given an unknown tool name, When validate_args runs, Then ToolError is raised."""
        with self.assertRaises(self.ToolError):
            self.registry.validate_args("bogus", {})

    async def test_unknown_tool_raises_tool_error_on_every_entry_point(self):
        """Given an unknown tool, When any execute API runs, Then ToolError is raised."""
        for method in ("execute_raw", "execute_normalized", "execute_response"):
            with self.subTest(api=method):
                with self.assertRaises(self.ToolError):
                    await getattr(self.registry, method)("bogus", {})

    async def test_unsupported_kwarg_surfaces_as_tool_error(self):
        """Given an unsupported kwarg, When execute_raw runs, Then ToolError replaces TypeError."""
        with self.assertRaises(self.ToolError):
            await self.registry.execute_raw("get_top_teams", {"bogus_kw": 1})

        self.assertEqual(self.service.calls, [])

    async def test_missing_required_arg_surfaces_as_tool_error(self):
        """Given a missing required arg, When execute_raw runs, Then the TypeError becomes ToolError."""
        with self.assertRaises(self.ToolError):
            await self.registry.execute_raw("get_team_statistics", {})

    async def test_domain_error_surfaces_as_tool_error(self):
        """Given a service ValueError, When execute_raw runs, Then ToolError carries its text."""
        self.service.raises["get_team_statistics"] = ValueError("Team Ghost not found")

        with self.assertRaises(self.ToolError) as caught:
            await self.registry.execute_raw("get_team_statistics", {"team_name": "Ghost"})

        self.assertIn("Team Ghost not found", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
