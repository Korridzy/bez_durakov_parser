"""Tool module discovery and loading cases.

Aggregated into test_agent, which is the public path the plan's acceptance commands use.
"""

import importlib
import sys
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine

from agent.toolmodule import (
    ENVELOPE_NOTE,
    RESERVED_TOOL_NAMES,
    ParamSpec,
    ToolModuleError,
    discover,
    load_tool_module,
)

PROPERTY_CALLS: list[str] = []


class ShapeService:
    """Every parameter shape discovery must accept, plus the two it must skip."""

    def __init__(self):
        self.db = object()
        self.rows = [1, 2, 3]

    @property
    def opened(self) -> bool:
        """A property is never a tool and must never be evaluated at discovery time."""
        PROPERTY_CALLS.append("opened")
        return True

    def no_parameters(self) -> dict:
        """Return everything the service knows.

        Returns:
            A dict, which the tool layer turns into a handle envelope.
        """
        return {}

    def required_scalar(self, name: str) -> dict:
        """Return one record by name."""
        return {"name": name}

    def optional_scalar(self, limit: int = 10) -> list:
        """Return at most limit records."""
        return list(range(limit))

    def takes_date(self, start_date: date) -> list:
        """Return records from a start date."""
        return [start_date]

    def takes_datetime(self, moment: datetime) -> list:
        """Return records from a moment."""
        return [moment]

    def takes_float(self, ratio: float) -> dict:
        """Return records above a ratio."""
        return {"ratio": ratio}

    def takes_bool(self, verbose: bool) -> dict:
        """Return records, verbosely or not."""
        return {"verbose": verbose}

    def union_with_none(self, station: str | None = None) -> dict:
        """Return records for one station or for all of them."""
        return {"station": station}

    def optional_alias(self, year: int | None = None) -> dict:
        """Return records for one year or for all of them."""
        return {"year": year}

    def _private_helper(self) -> None:
        """A leading underscore keeps a helper out of the tool surface."""


class DiscoveryTests(unittest.TestCase):
    """What discovery keeps, what it skips and what it refuses."""

    def setUp(self):
        PROPERTY_CALLS.clear()
        self.specs = {spec.name: spec for spec in discover(ShapeService())}

    def test_every_public_method_becomes_a_tool_in_alphabetical_order(self):
        """Given a service, When it is discovered, Then its public methods are the tools."""
        names = [spec.name for spec in discover(ShapeService())]

        self.assertEqual(names, sorted(names))
        self.assertEqual(
            set(names),
            {
                "no_parameters",
                "optional_alias",
                "optional_scalar",
                "required_scalar",
                "takes_bool",
                "takes_date",
                "takes_datetime",
                "takes_float",
                "union_with_none",
            },
        )

    def test_a_private_method_is_skipped(self):
        """Given an underscored helper, When discovery runs, Then it is not a tool."""
        self.assertNotIn("_private_helper", self.specs)

    def test_a_public_non_callable_attribute_is_skipped(self):
        """Given a public instance attribute, When discovery runs, Then it is skipped."""
        for attribute in ("db", "rows"):
            with self.subTest(attribute=attribute):
                self.assertNotIn(attribute, self.specs)

    def test_a_property_is_skipped_without_being_evaluated(self):
        """Given a property, When discovery runs, Then it is skipped and its getter never runs."""
        self.assertNotIn("opened", self.specs)
        self.assertEqual(PROPERTY_CALLS, [])

    def test_a_method_without_parameters_has_no_params(self):
        """Given a no-argument method, When it is discovered, Then it carries no parameters."""
        self.assertEqual(self.specs["no_parameters"].params, ())

    def test_a_required_scalar_carries_its_wire_type_and_no_default(self):
        """Given a required scalar, When it is discovered, Then it is required on the wire."""
        self.assertEqual(
            self.specs["required_scalar"].params,
            (
                ParamSpec(
                    name="name",
                    wire_type=str,
                    optional=False,
                    needs_date=False,
                    has_default=False,
                    default=None,
                    python_type=str,
                ),
            ),
        )

    def test_an_optional_scalar_keeps_its_default(self):
        """Given a defaulted scalar, When it is discovered, Then the default is preserved."""
        self.assertEqual(
            self.specs["optional_scalar"].params,
            (
                ParamSpec(
                    name="limit",
                    wire_type=int,
                    optional=False,
                    needs_date=False,
                    has_default=True,
                    default=10,
                    python_type=int,
                ),
            ),
        )

    def test_a_float_is_supported(self):
        """Given a float parameter, When it is discovered, Then float is its wire type."""
        self.assertEqual(self.specs["takes_float"].params[0].wire_type, float)

    def test_a_bool_is_supported(self):
        """Given a bool parameter, When it is discovered, Then bool is its wire type."""
        self.assertEqual(self.specs["takes_bool"].params[0].wire_type, bool)

    def test_a_date_reaches_the_wire_as_a_string_and_is_flagged_for_coercion(self):
        """Given a date parameter, When it is discovered, Then it is a string that needs coercion."""
        for name, python_type in (("takes_date", date), ("takes_datetime", datetime)):
            with self.subTest(method=name):
                param = self.specs[name].params[0]
                self.assertEqual(param.wire_type, str)
                self.assertTrue(param.needs_date)
                self.assertIs(param.python_type, python_type)

    def test_a_union_with_none_is_optional(self):
        """Given X | None, When it is discovered, Then the parameter is optional."""
        for name, wire in (("union_with_none", str), ("optional_alias", int)):
            with self.subTest(method=name):
                param = self.specs[name].params[0]
                self.assertEqual(param.wire_type, wire)
                self.assertTrue(param.optional)
                self.assertTrue(param.has_default)
                self.assertIsNone(param.default)

    def test_the_description_is_the_first_paragraph_plus_the_envelope_note(self):
        """Given a Google-style docstring, When it is discovered, Then only the summary survives."""
        self.assertEqual(
            self.specs["no_parameters"].description,
            f"Return everything the service knows.\n{ENVELOPE_NOTE}",
        )

    def test_a_multi_line_summary_is_collapsed_to_one_line(self):
        """Given a wrapped summary, When it is discovered, Then its newlines become spaces."""

        class Wrapped:
            def wrapped_summary(self) -> dict:
                """Return records for a station
                over a whole reporting period.

                Args:
                    nothing.
                """
                return {}

        spec = discover(Wrapped())[0]

        self.assertEqual(
            spec.description,
            f"Return records for a station over a whole reporting period.\n{ENVELOPE_NOTE}",
        )


class DiscoveryRefusalTests(unittest.TestCase):
    """The four ways a method fails the contract, each naming the offending method."""

    def test_a_method_without_a_docstring_is_refused(self):
        """Given no docstring, When discovery runs, Then the method is named in the error."""

        class Undocumented:
            def silent(self) -> dict:
                return {}

        with self.assertRaises(ToolModuleError) as caught:
            discover(Undocumented())

        self.assertEqual(caught.exception.method, "silent")
        self.assertIn("has no docstring", str(caught.exception))

    def test_a_parameter_without_an_annotation_is_refused(self):
        """Given an unannotated parameter, When discovery runs, Then it is refused by name."""

        class Unannotated:
            def loose(self, station) -> dict:
                """Return records for a station."""
                return {"station": station}

        with self.assertRaises(ToolModuleError) as caught:
            discover(Unannotated())

        self.assertEqual(caught.exception.method, "loose")
        self.assertIn("'station' has no type annotation", str(caught.exception))

    def test_an_unsupported_annotation_is_refused(self):
        """Given an annotation outside the supported set, When discovery runs, Then it is refused."""

        class Exotic:
            def complicated(self, payload: dict) -> dict:
                """Return records for a payload."""
                return payload

        with self.assertRaises(ToolModuleError) as caught:
            discover(Exotic())

        self.assertEqual(caught.exception.method, "complicated")
        self.assertIn("unsupported annotation", str(caught.exception))

    def test_a_reserved_name_is_refused(self):
        """Given a method named after a built-in tool, When discovery runs, Then it is refused."""
        for reserved in sorted(RESERVED_TOOL_NAMES):
            with self.subTest(reserved=reserved):
                service = type("Colliding", (), {reserved: lambda self: None})()

                with self.assertRaises(ToolModuleError) as caught:
                    discover(service)

                self.assertEqual(caught.exception.method, reserved)
                self.assertIn("reserved tool name", str(caught.exception))

    def test_a_variadic_parameter_is_refused(self):
        """Given *args, When discovery runs, Then the method is refused rather than mis-described."""

        class Variadic:
            def spread(self, *names: str) -> dict:
                """Return records for several names."""
                return {"names": names}

        with self.assertRaises(ToolModuleError) as caught:
            discover(Variadic())

        self.assertEqual(caught.exception.method, "spread")
        self.assertIn("variadic", str(caught.exception))


VALID_MODULE = '''
"""A stand-in operator module."""


class Service:
    """A stand-in service."""

    def __init__(self, engine):
        self.engine = engine

    def list_rows(self) -> dict:
        """Return every row."""
        return {}


def build_service(engine):
    """Build the service around the injected engine, opening no connection."""
    return Service(engine)
'''

CONNECTING_MODULE = '''
"""A module whose factory connects, which the contract forbids."""


def build_service(engine):
    """Open a connection during construction, which is what the contract forbids."""
    engine.connect()
    return object()
'''

NO_FACTORY_MODULE = '''
"""A module that forgot its factory."""


def make_service(engine):
    """Not the fixed factory name."""
    return object()
'''

RAISING_FACTORY_MODULE = '''
"""A module whose factory raises."""


def build_service(engine):
    """Fail the way a misconfigured operator module fails."""
    raise RuntimeError("the operator module is misconfigured")
'''

UNDOCUMENTED_MODULE = '''
"""A module whose service has an undocumented method."""


class Service:
    """A stand-in service."""

    def __init__(self, engine):
        self.engine = engine

    def silent(self) -> dict:
        return {}


def build_service(engine):
    """Build the service."""
    return Service(engine)
'''


class LoaderTests(unittest.TestCase):
    """Importing the operator's module, calling its factory and reporting what went wrong."""

    def setUp(self):
        self._directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._directory.cleanup)
        self.root = Path(self._directory.name)
        sys.path.insert(0, str(self.root))
        self.addCleanup(sys.path.remove, str(self.root))
        self._written: list[str] = []
        self.addCleanup(self._forget_written)
        self.engine = create_engine("sqlite://")
        self.addCleanup(self.engine.dispose)

    def _forget_written(self):
        for name in self._written:
            sys.modules.pop(name, None)

    def _write(self, name: str, body: str) -> str:
        (self.root / f"{name}.py").write_text(body)
        self._written.append(name)
        importlib.invalidate_caches()
        return name

    def test_a_valid_module_yields_the_service_and_its_specs(self):
        """Given a valid module, When it is loaded, Then the service and its tools come back."""
        name = self._write("fixture_valid", VALID_MODULE)

        service, specs = load_tool_module(name, self.engine)

        self.assertEqual([spec.name for spec in specs], ["list_rows"])
        self.assertIs(service.engine, self.engine)

    def test_loading_opens_no_connection(self):
        """Given an engine whose connect fails, When a module is loaded, Then it still loads."""
        name = self._write("fixture_no_connect", VALID_MODULE)

        with patch.object(
            type(self.engine), "connect", side_effect=AssertionError("the factory connected")
        ):
            _, specs = load_tool_module(name, self.engine)

        self.assertEqual([spec.name for spec in specs], ["list_rows"])

    def test_a_factory_that_connects_surfaces_as_a_module_error(self):
        """Given a factory that connects, When the engine refuses, Then the module is named."""
        name = self._write("fixture_connects", CONNECTING_MODULE)

        with patch.object(
            type(self.engine), "connect", side_effect=RuntimeError("no connection at construction")
        ):
            with self.assertRaises(ToolModuleError) as caught:
                load_tool_module(name, self.engine)

        self.assertEqual(caught.exception.module, name)
        self.assertIn("build_service failed", str(caught.exception))

    def test_an_unimportable_path_names_the_module(self):
        """Given a path that does not import, When it is loaded, Then the module is named."""
        with self.assertRaises(ToolModuleError) as caught:
            load_tool_module("definitely.not.a.module", self.engine)

        self.assertEqual(caught.exception.module, "definitely.not.a.module")
        self.assertIn("could not be imported", str(caught.exception))

    def test_a_module_without_the_factory_names_the_module(self):
        """Given no build_service, When the module is loaded, Then the factory name is reported."""
        name = self._write("fixture_no_factory", NO_FACTORY_MODULE)

        with self.assertRaises(ToolModuleError) as caught:
            load_tool_module(name, self.engine)

        self.assertEqual(caught.exception.module, name)
        self.assertIn("has no build_service factory", str(caught.exception))

    def test_a_raising_factory_names_the_module_and_the_cause(self):
        """Given a factory that raises, When the module is loaded, Then the cause is reported."""
        name = self._write("fixture_raises", RAISING_FACTORY_MODULE)

        with self.assertRaises(ToolModuleError) as caught:
            load_tool_module(name, self.engine)

        self.assertEqual(caught.exception.module, name)
        self.assertIn("the operator module is misconfigured", str(caught.exception))

    def test_a_discovery_failure_names_both_the_module_and_the_method(self):
        """Given an undocumented method, When the module is loaded, Then both names appear."""
        name = self._write("fixture_undocumented", UNDOCUMENTED_MODULE)

        with self.assertRaises(ToolModuleError) as caught:
            load_tool_module(name, self.engine)

        self.assertEqual(caught.exception.module, name)
        self.assertEqual(caught.exception.method, "silent")
        self.assertEqual(str(caught.exception), f"{name}.silent has no docstring")


class DefaultModuleTests(unittest.TestCase):
    """The shipped bez_durakov module, discovered exactly as an operator's own would be."""

    # The post-tightening first paragraphs. Pinned so the prompt cannot silently degrade
    # into the DataFrame talk the Google-style Returns blocks carry.
    EXPECTED_SUMMARIES = {
        "get_all_games_summary": "Get summary of all games.",
        "get_all_teams": "Get all teams.",
        "get_game_by_id": "Get full game data by ID.",
        "get_games_by_date_range": "Get game IDs within an inclusive date range.",
        "get_team_game_scores": "Get team game scores, optionally for one game.",
        "get_team_statistics": "Get statistics for a specific team.",
        "get_team_wins": "Get games won by a specific team.",
        "get_top_teams": "Get top teams by total points.",
    }

    def setUp(self):
        self.engine = create_engine("sqlite://")
        self.addCleanup(self.engine.dispose)
        self.service, self.specs = load_tool_module("bd_shared.tools.bez_durakov", self.engine)

    def test_exactly_the_eight_expected_tools_are_discovered(self):
        """Given the default module, When it is loaded, Then it yields exactly eight tools."""
        names = [spec.name for spec in self.specs]

        self.assertEqual(names, sorted(self.EXPECTED_SUMMARIES))
        self.assertEqual(len(self.specs), 8)

    def test_the_public_database_handle_is_skipped(self):
        """Given the service's public db attribute, When it is discovered, Then it is not a tool."""
        self.assertTrue(hasattr(self.service, "db"))
        self.assertNotIn("db", [spec.name for spec in self.specs])

    def test_the_eight_descriptions_match_the_pinned_list(self):
        """Given the default module, When descriptions are composed, Then they are the pinned text."""
        for spec in self.specs:
            with self.subTest(tool=spec.name):
                self.assertEqual(
                    spec.description,
                    f"{self.EXPECTED_SUMMARIES[spec.name]}\n{ENVELOPE_NOTE}",
                )

    def test_the_date_range_parameters_keep_their_shapes(self):
        """Given the date-range tool, When it is discovered, Then both parameters survive typed."""
        params = {
            param.name: param
            for spec in self.specs
            if spec.name == "get_games_by_date_range"
            for param in spec.params
        }

        self.assertEqual(set(params), {"start_date", "end_date"})
        self.assertTrue(params["start_date"].needs_date)
        self.assertFalse(params["start_date"].has_default)
        self.assertTrue(params["end_date"].optional)
        self.assertIs(params["end_date"].python_type, date)

    def test_the_factory_opens_no_connection(self):
        """Given a failing engine, When the default module is loaded, Then it still loads."""
        with patch.object(
            type(self.engine), "connect", side_effect=AssertionError("the factory connected")
        ):
            _, specs = load_tool_module("bd_shared.tools.bez_durakov", self.engine)

        self.assertEqual(len(specs), 8)


if __name__ == "__main__":
    unittest.main()
