"""
ToolRegistry result-shape cases: normalization, response conversion, and the
absence of the deleted custom-query escape hatch.

Aggregated into test_agent.TestRegistry, which is the public path the plan's
acceptance commands use.
"""
import importlib
import json
import unittest
from datetime import date, datetime
from decimal import Decimal

# Sibling modules resolve through the container's /app entry, not through a
# static path the host checker can model - same convention as bd_shared imports.
RegistryCaseBase = importlib.import_module("test_agent_support").RegistryCaseBase


class RegistryShapeTests(RegistryCaseBase):

    async def test_normalized_dataframe_yields_records_and_columns(self):
        """Given a DataFrame result, When execute_normalized runs, Then records and columns come back."""
        self.service.results["get_all_games_summary"] = self.pd.DataFrame(
            [{"game_id": 1, "game_date": date(2025, 1, 1)},
             {"game_id": 2, "game_date": date(2025, 2, 1)}]
        )

        records, cols = await self.registry.execute_normalized("get_all_games_summary", {})

        self.assertEqual(cols, ["game_id", "game_date"])
        self.assertEqual(
            records,
            [{"game_id": 1, "game_date": "2025-01-01"},
             {"game_id": 2, "game_date": "2025-02-01"}],
        )

    async def test_normalized_dict_yields_single_record_and_keys(self):
        """Given a dict result, When execute_normalized runs, Then it becomes one record."""
        self.service.results["get_team_statistics"] = {"team_name": "X", "games_played": 3}

        records, cols = await self.registry.execute_normalized(
            "get_team_statistics", {"team_name": "X"}
        )

        self.assertEqual(records, [{"team_name": "X", "games_played": 3}])
        self.assertEqual(cols, ["team_name", "games_played"])

    async def test_normalized_id_list_yields_synthesised_item_records(self):
        """Given a bare list, When execute_normalized runs, Then each entry becomes an item record."""
        self.service.results["get_games_by_date_range"] = [11, 12, 13]

        records, cols = await self.registry.execute_normalized(
            "get_games_by_date_range", {"start_date": "2025-01-01"}
        )

        self.assertEqual(records, [{"item": 11}, {"item": 12}, {"item": 13}])
        self.assertEqual(cols, ["item"])

    async def test_normalized_empty_results_yield_empty_pairs(self):
        """Given None or empty results, When execute_normalized runs, Then both parts are empty."""
        empty_results = {
            "none": None,
            "empty_frame": self.pd.DataFrame(),
            "empty_list": [],
            "empty_dict": {},
        }

        for label, value in empty_results.items():
            with self.subTest(result=label):
                self.service.results["get_all_teams"] = value

                records, cols = await self.registry.execute_normalized("get_all_teams", {})

                self.assertEqual(records, [])
                self.assertEqual(cols, [])

    async def test_normalized_converts_json_unsafe_scalars(self):
        """Given numpy/Decimal/date values, When execute_normalized runs, Then output is JSON-safe."""
        self.service.results["get_team_statistics"] = {
            "decimal": Decimal("1.5"),
            "np_int": self.numpy.int64(7),
            "np_float": self.numpy.float64(2.5),
            "day": date(2025, 3, 1),
            "moment": datetime(2025, 3, 1, 12, 30),
            "stamp": self.pd.Timestamp("2025-03-01T12:30:00"),
            "span": self.numpy.timedelta64(90, "s"),
            "category_averages": {"vybor": self.numpy.float64(3.5)},
            "wins": [{"total_points": Decimal("2")}],
        }

        records, _ = await self.registry.execute_normalized(
            "get_team_statistics", {"team_name": "X"}
        )

        self.assertEqual(
            records[0],
            {
                "decimal": 1.5,
                "np_int": 7,
                "np_float": 2.5,
                "day": "2025-03-01",
                "moment": "2025-03-01T12:30:00",
                "stamp": "2025-03-01T12:30:00",
                "span": 90.0,
                "category_averages": {"vybor": 3.5},
                "wins": [{"total_points": 2.0}],
            },
        )
        json.dumps(records)

    async def test_normalized_converts_numpy_datetime64(self):
        """Given numpy datetime64 values, When execute_normalized runs, Then they become ISO strings."""
        self.service.results["get_team_statistics"] = {
            "day64": self.numpy.datetime64("2025-03-01"),
            "moment64": self.numpy.datetime64("2025-03-01T12:30:00"),
            "nanos64": self.numpy.datetime64("2025-03-01T12:30:00.123456789"),
            "nested": [{"day64": self.numpy.datetime64("2025-03-02")}],
        }

        records, _ = await self.registry.execute_normalized(
            "get_team_statistics", {"team_name": "X"}
        )

        self.assertEqual(
            records[0],
            {
                "day64": "2025-03-01",
                "moment64": "2025-03-01T12:30:00",
                "nanos64": "2025-03-01T12:30:00.123456",
                "nested": [{"day64": "2025-03-02"}],
            },
        )
        json.dumps(records)

    async def test_normalized_converts_numpy_timedelta64_to_seconds(self):
        """Given numpy timedelta64 values, When execute_normalized runs, Then each is seconds."""
        self.service.results["get_team_statistics"] = {
            "secs": self.numpy.timedelta64(90, "s"),
            "millis": self.numpy.timedelta64(1500, "ms"),
            "micros": self.numpy.timedelta64(1500, "us"),
            "nanos": self.numpy.timedelta64(1500, "ns"),
            "picos": self.numpy.timedelta64(1500, "ps"),
            "femtos": self.numpy.timedelta64(1500, "fs"),
            "attos": self.numpy.timedelta64(1500, "as"),
            "neg_attos": self.numpy.timedelta64(-1500, "as"),
            "days": self.numpy.timedelta64(2, "D"),
            "years": self.numpy.timedelta64(1, "Y"),
            "missing": self.numpy.timedelta64("NaT"),
            "nested": [{"nanos": self.numpy.timedelta64(1500, "ns")}],
        }

        records, _ = await self.registry.execute_normalized(
            "get_team_statistics", {"team_name": "X"}
        )

        row = records[0]
        self.assertEqual(row["secs"], 90.0)
        self.assertEqual(row["millis"], 1.5)
        self.assertEqual(row["micros"], 0.0015)
        self.assertEqual(row["days"], 172800.0)
        self.assertEqual(row["years"], 31556952.0)
        self.assertIsNone(row["missing"])

        # A relative delta at every magnitude: an absolute default tolerance would
        # accept 0.0 for anything finer than a microsecond.
        fine_units = {
            "nanos": 1.5e-06,
            "picos": 1.5e-09,
            "femtos": 1.5e-12,
            "attos": 1.5e-15,
            "neg_attos": -1.5e-15,
        }
        for key, expected in fine_units.items():
            with self.subTest(field=key):
                self.assertAlmostEqual(row[key], expected, delta=abs(expected) * 1e-06)
        self.assertAlmostEqual(row["nested"][0]["nanos"], 1.5e-06, delta=1.5e-12)
        json.dumps(records, allow_nan=False)

    async def test_normalized_does_not_truncate_rows(self):
        """Given more rows than the per-fetch cap, When normalized, Then every row survives."""
        self.service.results["get_team_game_scores"] = self.pd.DataFrame(
            [{"game_id": index} for index in range(300)]
        )

        records, _ = await self.registry.execute_normalized("get_team_game_scores", {})

        self.assertEqual(len(records), 300)

    async def test_normalized_rejects_unsupported_result_type(self):
        """Given a result that is not a frame/dict/list, When normalized, Then ToolError is raised."""
        self.service.results["get_top_teams"] = 42

        with self.assertRaises(self.ToolError):
            await self.registry.execute_normalized("get_top_teams", {"limit": 1})

    async def test_response_converts_dataframe_to_records(self):
        """Given a DataFrame, When execute_response runs, Then today's records conversion applies."""
        frame = self.pd.DataFrame([{"team_name": "X", "total_points": 5.0}])
        self.service.results["get_top_teams"] = frame

        response = await self.registry.execute_response("get_top_teams", {"limit": 1})

        self.assertEqual(response, frame.to_dict(orient="records"))

    async def test_response_passes_through_dict_list_and_none(self):
        """Given dict/list/None results, When execute_response runs, Then they pass through unchanged."""
        passthrough = {
            "get_team_statistics": {"team_name": "X"},
            "get_games_by_date_range": [11, 12],
        }

        for name, value in passthrough.items():
            with self.subTest(tool=name):
                self.service.results[name] = value

                response = await self.registry.execute_response(
                    name, self.dispatch_cases[name]
                )

                self.assertIs(response, value)

        self.service.results["get_game_by_id"] = None
        self.assertIsNone(await self.registry.execute_response("get_game_by_id", {"game_id": 1}))


if __name__ == "__main__":
    unittest.main()
