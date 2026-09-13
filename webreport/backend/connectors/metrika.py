"""Yandex Metrica Reporting and Management APIs. Always scoped to one saved counter."""

import re
from datetime import date, timedelta

from .http import ConnectorError, request_json

BASE = "https://api-metrika.yandex.net"
METRICS = ["ym:s:users", "ym:s:visits", "ym:s:pageviews", "ym:s:bounceRate"]
LABELS = ["Посетители", "Визиты", "Просмотры", "Отказы"]
DIMENSIONS = {
    "channels": "ym:s:lastTrafficSource",
    "devices": "ym:s:deviceCategory",
    "pages": "ym:s:startURL",
    "geography": "ym:s:regionCountry",
}


def period(start: str, end: str) -> tuple[str, str]:
    try:
        first, last = date.fromisoformat(start), date.fromisoformat(end)
    except ValueError:
        raise ConnectorError("Укажите даты в формате ГГГГ-ММ-ДД.") from None
    if first > last or (last - first).days > 365:
        raise ConnectorError("Выберите период от 1 до 366 дней.")
    return first.isoformat(), last.isoformat()


def default_period(days: int = 30):
    end = date.today() - timedelta(days=1)
    return (end - timedelta(days=days - 1)).isoformat(), end.isoformat()


class Metrika:
    def __init__(self, config):
        self.config = config
        self.counter_id = str(config["counter_id"])
        if not self.counter_id.isdigit():
            raise ConnectorError("ID счётчика должен состоять из цифр.")

    def _get(self, path, **params):
        return request_json(
            "GET",
            BASE + path,
            headers={"Authorization": "OAuth " + self.config["token"]},
            params=params,
        )

    def metadata(self):
        data = self._get(f"/management/v1/counter/{self.counter_id}")["counter"]
        return {
            "name": data.get("name") or self.counter_id,
            "site": data.get("site", ""),
            "counter_id": self.counter_id,
            "timezone": data.get("time_zone_name", ""),
            "created": data.get("create_time", ""),
        }

    def query(
        self,
        start,
        end,
        metrics="ym:s:users,ym:s:visits",
        dimensions="",
        limit=100,
        filters="",
        offset=1,
        *,
        accuracy="medium",
        sort="",
        include_undefined=False,
        timezone="",
    ):
        period(start, end)
        names = metrics.split(",")
        dims = dimensions.split(",") if dimensions else []
        if (
            not 1 <= len(names) <= 10
            or len(dims) > 3
            or any(not re.fullmatch(r"ym:[su]:[A-Za-z0-9<>]+", n) for n in names + dims)
        ):
            raise ConnectorError("Некорректный набор метрик или группировок.")
        if not 1 <= limit <= 500 or len(filters) > 4000 or not 1 <= offset <= 10000:
            raise ConnectorError("Запрос превышает допустимый размер.")
        params = dict(
            ids=self.counter_id,
            date1=start,
            date2=end,
            metrics=metrics,
            limit=limit,
            offset=offset,
            accuracy=accuracy,
            lang="ru",
        )
        if dimensions:
            if sort and sort.lstrip("-") not in names + dims:
                raise ConnectorError("Сортировка должна быть по столбцу отчёта.")
            params.update(dimensions=dimensions, sort=sort or "-" + names[0], include_undefined=str(include_undefined).lower())
        if accuracy not in {"medium", "full"}:
            raise ConnectorError("Неизвестный режим точности.")
        if filters:
            params["filters"] = filters
        if timezone:
            if not re.fullmatch(r"[+-](?:[01]\d|2[0-3]):[0-5]\d", timezone):
                raise ConnectorError("Часовой пояс задаётся как +03:00 или -05:00.")
            params["timezone"] = timezone
        body = self._get("/stat/v1/data", **params)
        rows = []
        for row in body.get("data", []):
            rows.append(
                {
                    **{
                        n: (v.get("name") or v.get("id") or "Не определено")
                        for n, v in zip(dims, row.get("dimensions", []))
                    },
                    **dict(zip(names, row.get("metrics", []))),
                }
            )
        return {
            "rows": rows,
            "columns": dims + names,
            "totals": body.get("totals", []),
            "sampled": body.get("sampled", False),
            "sample_share": body.get("sample_share", 1),
            "total_rows": body.get("total_rows", len(rows)),
            "row_dimensions": [row.get("dimensions", []) for row in body.get("data", [])],
            "contains_sensitive_data": body.get("contains_sensitive_data", False),
            "data_lag": body.get("data_lag", 0),
            "date1": start,
            "date2": end,
            "timezone": timezone or "counter",
            "offset": offset,
            "has_more": offset - 1 + len(rows) < body.get("total_rows", len(rows)),
        }

    def time_series(self, start, end, metrics, group="day", filters="", accuracy="medium"):
        from .metrika_explorer import GROUPS

        first, last = period(start, end)
        names = metrics.split(",")
        if (group not in GROUPS or not 1 <= len(names) <= 10
                or any(not re.fullmatch(r"ym:s:[A-Za-z0-9]+", n) for n in names)
                or accuracy not in {"medium", "full"} or len(filters) > 4000):
            raise ConnectorError("Некорректные параметры временного ряда.")
        body = self._get("/stat/v1/data/bytime", ids=self.counter_id,
                         date1=first, date2=last, metrics=metrics, group=group,
                         filters=filters, accuracy=accuracy, lang="ru")
        values = (body.get("data") or [{}])[0].get("metrics", [])
        return {
            "series": [{
                "date": interval[0], "end": interval[-1],
                **{key: values[j][i] if j < len(values) and i < len(values[j]) else None
                   for j, key in enumerate(names)},
            } for i, interval in enumerate(body.get("time_intervals", []))],
            "sampled": body.get("sampled", False),
            "sample_share": body.get("sample_share", 1),
            "contains_sensitive_data": body.get("contains_sensitive_data", False),
            "data_lag": body.get("data_lag", 0),
        }

    def goals(self):
        return [{"id": str(goal["id"]), "name": goal.get("name", str(goal["id"])),
                 "type": goal.get("type", "")}
                for goal in self._get(f"/management/v1/counter/{self.counter_id}/goals").get("goals", [])]

    def overview(self, start, end):
        period(start, end)
        totals = self.query(start, end, ",".join(METRICS), limit=1)
        daily = self._get(
            "/stat/v1/data/bytime",
            ids=self.counter_id,
            date1=start,
            date2=end,
            metrics=",".join(METRICS[:3]),
            group="day",
            accuracy="medium",
        )
        values = (daily.get("data") or [{}])[0].get("metrics", [])
        series = [
            {
                "date": interval[0],
                **{
                    key: (values[j][i] if j < len(values) and i < len(values[j]) else 0)
                    for j, key in enumerate(["users", "visits", "views"])
                },
            }
            for i, interval in enumerate(daily.get("time_intervals", []))
        ]
        return {
            "metrics": [
                {
                    "key": key,
                    "label": label,
                    "value": value,
                    "format": "percent" if key == "bounce" else "number",
                }
                for key, label, value in zip(
                    ["users", "visits", "views", "bounce"], LABELS, totals["totals"]
                )
            ],
            "series": series,
            "sampled": totals["sampled"] or daily.get("sampled", False),
            "sample_share": min(totals["sample_share"], daily.get("sample_share", 1)),
            "date1": start,
            "date2": end,
        }

    def report(self, report, start, end, page=1):
        if not 1 <= page <= 200:
            raise ConnectorError("Недопустимая страница отчёта.")
        if report == "goals":
            goals = self._get(f"/management/v1/counter/{self.counter_id}/goals").get(
                "goals", []
            )
            # Fetch goal counts in bounded batches; listing goals itself transfers only metadata.
            rows = []
            for offset in range((page - 1) * 50, min(len(goals), page * 50), 10):
                batch = goals[offset : offset + 10]
                result = self.query(
                    start,
                    end,
                    ",".join(f"ym:s:goal{g['id']}reaches" for g in batch),
                    limit=1,
                )
                rows.extend(
                    {
                        "Название": g.get("name", str(g["id"])),
                        "Достижения": count,
                        "ID": g["id"],
                        "Тип": g.get("type", ""),
                    }
                    for g, count in zip(batch, result["totals"])
                )
            return {
                "rows": rows,
                "columns": ["Название", "Достижения", "ID", "Тип"],
                "total_rows": len(goals),
                "page": page,
                "has_more": len(goals) > page * 50,
            }
        if report not in DIMENSIONS:
            raise ConnectorError("Этот отчёт не поддерживается.")
        raw = self.query(
            start,
            end,
            "ym:s:users,ym:s:visits,ym:s:bounceRate",
            DIMENSIONS[report],
            50,
            offset=(page - 1) * 50 + 1,
        )
        return {
            **raw,
            "page": page,
            "has_more": raw["total_rows"] > page * 50,
            "columns": ["Название", "Посетители", "Визиты", "Отказы, %"],
            "rows": [
                dict(
                    zip(["Название", "Посетители", "Визиты", "Отказы, %"], row.values())
                )
                for row in raw["rows"]
            ],
        }
