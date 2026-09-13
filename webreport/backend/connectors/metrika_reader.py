"""Compose exact Metrica totals, drill-down tables and reusable time-series."""

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .http import ConnectorError
from .metrika_explorer import DIMENSIONS, METRICS, ExplorerQuery
from .report_cache import ReportCache


class MetrikaReader:
    def __init__(self, cache=None):
        self.cache = cache if cache is not None else ReportCache()

    @staticmethod
    def namespace(source):
        return (source["id"], source.get("updated_at", source.get("created_at", "")))

    def goals(self, source, client, refresh=False):
        return self.cache.fetch(("goals", self.namespace(source)), client.goals, 300, refresh)[0]

    def read(self, source, client, query: ExplorerQuery):
        try:
            zone = ZoneInfo(source.get("metadata", {}).get("timezone") or "UTC")
        except (ZoneInfoNotFoundError, ValueError):
            zone = ZoneInfo("UTC")
        now = datetime.now(zone)
        today = now.date().isoformat()
        if query.date2 > today:
            raise ConnectorError("Конец периода не может быть позже сегодняшнего дня в часовом поясе счётчика.")
        if query.goal_id and query.goal_id not in {g["id"] for g in self.goals(source, client, query.refresh)}:
            raise ConnectorError("Эта цель не найдена в выбранном счётчике.")
        group = query.resolved_group
        names = [query.metric_name(key) for key in query.metrics]
        dims = [query.dimension_name(key) for key in query.dimensions]
        expression = query.filter_expression()
        scope = (self.namespace(source), tuple(names), expression, query.accuracy, query.attribution)
        ttl = 60 if query.date2 == today else 300
        refresh = query.refresh or bool(source.get("connection_error"))
        sort_key = query.sort or query.metrics[0]
        sort = ("-" if query.descending else "") + (query.metric_name(sort_key) if sort_key in METRICS else query.dimension_name(sort_key))
        summary, summary_cached, summary_at = self.cache.fetch(
            ("totals", scope, query.date1, query.date2),
            lambda: client.query(query.date1, query.date2, ",".join(names), limit=1,
                                 filters=expression, accuracy=query.accuracy), ttl, refresh,
        )
        timeline, series_cached, series_at = self.cache.series(
            scope + (group,), query.date1, query.date2,
            lambda: client.time_series(query.date1, query.date2, ",".join(names), group, expression, query.accuracy),
            ttl, refresh,
        )
        rows, dimension_values, table_at = [], [], summary_at
        table_cached = True
        table = {}
        if dims:
            table, table_cached, table_at = self.cache.fetch(
                ("table", scope, tuple(dims), query.date1, query.date2, query.page, sort, query.include_undefined),
                lambda: client.query(query.date1, query.date2, ",".join(names), ",".join(dims), 50,
                                     expression, (query.page - 1) * 50 + 1, accuracy=query.accuracy,
                                     sort=sort, include_undefined=query.include_undefined), ttl, refresh,
            )
            for index, raw in enumerate(table["rows"]):
                rows.append({**{k: raw.get(n) for k, n in zip(query.dimensions, dims)},
                             **{k: raw.get(n) for k, n in zip(query.metrics, names)}})
                raw_dimensions = (table.get("row_dimensions") or [])
                values = raw_dimensions[index] if index < len(raw_dimensions) else []
                dimension_values.append({k: str((v.get("name") if query.dimension_name(k).endswith("Name") else v.get("id")) or v.get("name") or "")
                                         for k, v in zip(query.dimensions, values)})
        series = []
        for row in timeline["series"]:
            # Do not draw invented zeroes for future intraday buckets.
            stamp = str(row["date"]).replace("T", " ")
            if len(stamp) > 10 and stamp > now.strftime("%Y-%m-%d %H:%M:%S"):
                continue
            series.append({"date": row["date"], "end": row.get("end"),
                           **{k: row.get(n) for k, n in zip(query.metrics, names)}})
        parts = [summary, timeline] + ([table] if dims else [])
        totals = summary.get("totals", [])
        result = {
            "date1": query.date1, "date2": query.date2, "group": group, "timezone": str(zone),
            "metrics": [dict(key=k, label=METRICS[k][0], format=METRICS[k][2],
                             value=totals[i] if i < len(totals) else None)
                        for i, k in enumerate(query.metrics)],
            "series": series, "rows": rows, "dimension_values": dimension_values,
            "columns": [dict(key=k, label=DIMENSIONS[k][0], kind="dimension") for k in query.dimensions]
                       + [dict(key=k, label=METRICS[k][0], kind="metric", format=METRICS[k][2]) for k in query.metrics],
            "total_rows": table.get("total_rows", 0), "page": query.page,
            "has_more": table.get("total_rows", 0) > query.page * 50,
            "sampled": any(p.get("sampled") for p in parts),
            "sample_share": min(p.get("sample_share", 1) for p in parts),
            "contains_sensitive_data": any(p.get("contains_sensitive_data") for p in parts),
            "data_lag": max(p.get("data_lag", 0) or 0 for p in parts),
            "cached": summary_cached and series_cached and table_cached,
            "cache": {"totals": summary_cached, "series": series_cached, "table": table_cached if dims else None},
            "fetched_at": min(summary_at, series_at, table_at),
        }
        if query.compare:
            previous = self.read(source, client, query.previous())
            result["comparison"] = previous
            result["sampled"] |= previous["sampled"]
            result["sample_share"] = min(result["sample_share"], previous["sample_share"])
            result["contains_sensitive_data"] |= previous["contains_sensitive_data"]
            result["data_lag"] = max(result["data_lag"], previous["data_lag"])
            result["cached"] &= previous["cached"]
            result["fetched_at"] = min(result["fetched_at"], previous["fetched_at"])
        return result
