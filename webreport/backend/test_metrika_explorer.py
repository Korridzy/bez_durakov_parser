"""Offline correctness and cache contracts for the interactive Metrica reader."""
import unittest
from datetime import date, timedelta
from unittest.mock import Mock

from pydantic import ValidationError

from connectors.http import ConnectorError
from connectors.metrika import Metrika
from connectors.metrika_explorer import ExplorerQuery
from connectors.metrika_reader import MetrikaReader
from connectors.report_cache import ReportCache


class FakeMetrika:
    def __init__(self):
        self.queries = []
        self.timelines = []
        self.sampled = False
        self.goals = Mock(return_value=[{"id":"12", "name":"Synthetic goal"}])

    def query(self, start, end, metrics, dimensions="", limit=1, filters="", offset=1, **kwargs):
        self.queries.append((start, end, metrics, dimensions, filters, offset, kwargs))
        names = metrics.split(",")
        dims = dimensions.split(",") if dimensions else []
        days = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
        return {"totals":[days + 100] * len(names), "rows":[{**dict.fromkeys(names, 10), **dict.fromkeys(dims, "Россия")} ] if dims else [],
                "row_dimensions":[[{"id":"225", "name":"Россия"} for _ in dims]],
                "sampled":False, "sample_share":1, "total_rows":103 if dims else 0}

    def time_series(self, start, end, metrics, group, filters, accuracy):
        self.timelines.append((start,end,metrics,group,filters,accuracy))
        days = (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
        return {"series":[{"date":(date.fromisoformat(start)+timedelta(days=i)).isoformat(), **dict.fromkeys(metrics.split(","), 50)} for i in range(days)],
                "sampled":self.sampled, "sample_share":.5 if self.sampled else 1}


class ExplorerContracts(unittest.TestCase):
    def setUp(self):
        self.time = [0]
        self.cache = ReportCache(clock=lambda:self.time[0])
        self.reader = MetrikaReader(self.cache)
        self.client = FakeMetrika()
        self.source = {"id":"first-source", "updated_at":"revision-1", "metadata":{"timezone":"Europe/Moscow"}}
        self.month = ExplorerQuery(date1="2026-08-01", date2="2026-08-30")

    def read(self, **changes):
        return self.reader.read(self.source, self.client, ExplorerQuery(**{**self.month.model_dump(), **changes}))

    def test_subrange_reuses_points_but_recalculates_period_uniques(self):
        self.read()
        week = self.read(date1="2026-08-24")
        self.assertEqual(len(self.client.timelines),1)
        self.assertEqual(len(self.client.queries),2)
        self.assertEqual(len(week["series"]),7)
        self.assertEqual(week["metrics"][0]["value"],107)
        self.assertNotEqual(week["metrics"][0]["value"],sum(row["users"] for row in week["series"]))
        self.assertEqual(week["cache"],{"totals":False,"series":True,"table":None})
        self.assertTrue(self.read(date1="2026-08-24")["cached"])

    def test_granularity_reuses_totals_and_table(self):
        self.read(dimensions=["country"])
        result = self.read(dimensions=["country"],group="hour")
        self.assertEqual(len(self.client.queries),2)
        self.assertEqual(len(self.client.timelines),2)
        self.assertTrue(result["cache"]["totals"])
        self.assertTrue(result["cache"]["table"])
        self.assertEqual(result["dimension_values"],[{"country":"Россия"}])

    def test_filters_accuracy_attribution_and_source_revision_are_isolated(self):
        self.read()
        self.read(filters=[{"field":"country","value":"Россия"}])
        self.read(accuracy="full")
        self.read(attribution="first")
        self.source["id"] = "second-source"
        self.read()
        self.source["updated_at"] = "revision-2"
        self.read()
        self.assertEqual(len(self.client.timelines),6)

    def test_expiration_refresh_and_known_connection_errors_bypass_cache(self):
        self.read()
        self.read(refresh=True)
        self.assertEqual(len(self.client.timelines),2)
        self.time[0] = 301
        self.read()
        self.assertEqual(len(self.client.timelines),3)
        self.source["connection_error"] = "temporary"
        self.read()
        self.assertEqual(len(self.client.timelines),4)

    def test_sampled_and_weekly_results_are_not_sliced(self):
        self.client.sampled = True
        self.read()
        self.read(date1="2026-08-24")
        self.read(group="week")
        self.read(group="week",date1="2026-08-24")
        self.assertEqual(len(self.client.timelines),4)

    def test_pagination_and_sort_share_the_timeline_and_totals(self):
        first = self.read(dimensions=["country"])
        second = self.read(dimensions=["country"], page=2, sort="visits", descending=False)
        self.assertEqual(len(self.client.timelines),1)
        self.assertEqual(len(self.client.queries),3)
        self.assertEqual(self.client.queries[-1][5],51)
        self.assertEqual(self.client.queries[-1][-1]["sort"],"ym:s:visits")
        self.assertTrue(first["has_more"])
        self.assertEqual(second["page"],2)

    def test_comparison_uses_same_filters_and_separate_exact_totals(self):
        result = self.read(compare=True, filters=[{"field":"country","value":"Россия"}])
        previous = result["comparison"]
        self.assertEqual((previous["date1"],previous["date2"]),("2026-07-02","2026-07-31"))
        self.assertEqual(self.client.queries[0][4],self.client.queries[1][4])
        self.assertEqual(previous["metrics"][0]["value"],130)

    def test_goal_is_checked_against_the_saved_counter(self):
        result = self.read(metrics=["conversion"], sort="conversion", goal_id="12")
        self.assertEqual(result["metrics"][0]["format"],"percent")
        self.assertIn("ym:s:goal12conversionRate", self.client.queries[0])
        with self.assertRaises(ConnectorError):
            self.read(metrics=["conversion"],sort="conversion",goal_id="99")

    def test_comparison_exposes_sampling_and_privacy_from_previous_period(self):
        self.read()
        self.client.sampled = True
        original = self.client.time_series
        def private_series(*args):
            return {**original(*args), "contains_sensitive_data": True, "data_lag": 180}
        self.client.time_series = private_series
        result = self.read(compare=True)
        self.assertTrue(result["sampled"])
        self.assertTrue(result["contains_sensitive_data"])
        self.assertEqual(result["sample_share"], .5)
        self.assertEqual(result["data_lag"], 180)
        self.assertFalse(result["cached"])
        self.assertTrue(result["cache"]["series"])

    def test_request_validation_and_filter_escaping(self):
        query = ExplorerQuery(date1="2026-08-01",date2="2026-08-01", filters=[{"field":"landing","value":"x' OR 1 \\ y"}])
        self.assertEqual(query.filter_expression(), "ym:s:startURL=='x\\' OR 1 \\\\ y'")
        self.assertEqual(query.resolved_group,"dekaminute")
        for changes in [{"group":"minute"},{"dimensions":["unknown"]},{"metrics":["conversion"]},
                        {"sort":"views","metrics":["users"]},{"counter_id":"another"},
                        {"filters":[{"field":"robot","operator":"contains","value":"Yes"}]}]:
            with self.subTest(changes=changes), self.assertRaises((ValidationError,ConnectorError)):
                ExplorerQuery(**{**self.month.model_dump(),**changes})

    def test_time_series_keeps_intraday_timestamps_and_missing_values(self):
        client = Metrika({"counter_id":"123","token":"synthetic"})
        client._get = Mock(return_value={"time_intervals":[["2026-08-01 00:00:00","2026-08-01 00:09:59"],["2026-08-01 00:10:00","2026-08-01 00:19:59"]],"data":[{"metrics":[[5]]}]})
        result = client.time_series("2026-08-01","2026-08-01","ym:s:users", "dekaminute")
        self.assertEqual(result["series"][0]["date"],"2026-08-01 00:00:00")
        self.assertIsNone(result["series"][1]["ym:s:users"])

    def test_cache_bounds_and_returns_independent_values(self):
        cache = ReportCache(capacity=2)
        value, _, _ = cache.fetch("a",lambda:{"rows":[1]})
        value["rows"].append(2)
        self.assertEqual(cache.fetch("a",lambda:None)[0],{"rows":[1]})
        cache.fetch("b",lambda:2)
        cache.fetch("c",lambda:3)
        self.assertEqual(len(cache.entries),2)
        self.assertNotIn("a",cache.entries)


if __name__ == "__main__":
    unittest.main()
