"""Read-only adapters for GA4, Matomo, Amplitude, Mixpanel and PostHog."""

import base64
import json
import time

from .http import ConnectorError, public_url, request_json
from .metrika import Metrika, period


def metric(key, label, value, format="number"):
    return dict(key=key, label=label, value=value, format=format)


def table(rows):
    return {
        "rows": rows,
        "columns": list(rows[0]) if rows else [],
        "total_rows": len(rows),
    }


class GA4:
    def __init__(self, config):
        self.config = config
        self._token = None

    def _access_token(self):
        if self._token:
            return self._token
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding

        try:
            account = json.loads(self.config["service_account"])
            encode = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=")
            now = int(time.time())
            claims = dict(
                iss=account["client_email"],
                scope="https://www.googleapis.com/auth/analytics.readonly",
                aud="https://oauth2.googleapis.com/token",
                iat=now,
                exp=now + 3600,
            )
            signed = (
                encode(b'{"alg":"RS256","typ":"JWT"}')
                + b"."
                + encode(json.dumps(claims).encode())
            )
            key = serialization.load_pem_private_key(
                account["private_key"].encode(), password=None
            )
            assertion = (
                signed
                + b"."
                + encode(key.sign(signed, padding.PKCS1v15(), hashes.SHA256()))
            ).decode()
        except (KeyError, TypeError, ValueError):
            raise ConnectorError(
                "Некорректный JSON-ключ сервисного аккаунта Google."
            ) from None
        self._token = request_json(
            "POST",
            "https://oauth2.googleapis.com/token",
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": assertion,
            },
        )["access_token"]
        return self._token

    def _query(self, start, end, metrics, dimensions=None, limit=50):
        period(start, end)
        prop = self.config["property_id"]
        return request_json(
            "POST",
            f"https://analyticsdata.googleapis.com/v1beta/properties/{prop}:runReport",
            headers={"Authorization": "Bearer " + self._access_token()},
            json={
                "dateRanges": [{"startDate": start, "endDate": end}],
                "metrics": [{"name": n} for n in metrics],
                "dimensions": [{"name": n} for n in (dimensions or [])],
                "limit": str(limit),
                "keepEmptyRows": True,
            },
        )

    def metadata(self):
        self._access_token()
        # Data API validation does not require Analytics Admin API permissions.
        from .metrika import default_period

        self._query(*default_period(1), ["activeUsers"], limit=1)
        return {
            "name": "Google Analytics · " + self.config["property_id"],
            "property_id": self.config["property_id"],
        }

    def overview(self, start, end):
        names = ["activeUsers", "sessions", "screenPageViews", "bounceRate"]
        totals = self._query(start, end, names)
        values = [
            float(v["value"])
            for v in (totals.get("rows") or [{"metricValues": [{"value": 0}] * 4}])[0][
                "metricValues"
            ]
        ]
        daily = self._query(start, end, names[:3], ["date"], 366)
        series = []
        for row in daily.get("rows", []):
            day = row["dimensionValues"][0]["value"]
            series.append(
                {
                    "date": f"{day[:4]}-{day[4:6]}-{day[6:]}",
                    **{
                        n: float(v["value"])
                        for n, v in zip(
                            ["users", "visits", "views"], row["metricValues"]
                        )
                    },
                }
            )
        return {
            "metrics": [
                metric("users", "Активные пользователи", values[0]),
                metric("visits", "Сеансы", values[1]),
                metric("views", "Просмотры", values[2]),
                metric("bounce", "Отказы", values[3] * 100, "percent"),
            ],
            "series": sorted(series, key=lambda r: r["date"]),
            "date1": start,
            "date2": end,
        }

    def report(self, report, start, end):
        dimension = {
            "channels": "sessionDefaultChannelGroup",
            "devices": "deviceCategory",
            "pages": "pagePath",
            "geography": "country",
            "events": "eventName",
        }[report]
        result = self._query(start, end, ["activeUsers", "eventCount"], [dimension])
        rows = [
            {
                "Название": r["dimensionValues"][0]["value"],
                "Пользователи": float(r["metricValues"][0]["value"]),
                "События": float(r["metricValues"][1]["value"]),
            }
            for r in result.get("rows", [])
        ]
        return {
            **table(rows),
            "total_rows": result.get("rowCount", len(rows)),
            "limited": result.get("rowCount", len(rows)) > len(rows),
        }


class Matomo:
    def __init__(self, config):
        self.config = config
        self.url = public_url(config["base_url"]) + "/index.php"

    def _query(self, method, **params):
        result = request_json(
            "POST",
            self.url,
            data={
                "module": "API",
                "method": method,
                "idSite": self.config["site_id"],
                "format": "JSON",
                "token_auth": self.config["token"],
                "filter_limit": 50,
                **params,
            },
        )
        if isinstance(result, dict) and result.get("result") == "error":
            raise ConnectorError(
                "Matomo отклонил запрос. Проверьте ID сайта и права токена."
            )
        return result

    def metadata(self):
        body = self._query("SitesManager.getSiteFromId")
        row = body[0] if isinstance(body, list) and body else body
        return {
            "name": row.get("name", "Matomo"),
            "site": row.get("main_url", ""),
            "timezone": row.get("timezone", ""),
        }

    def overview(self, start, end):
        totals = self._query("VisitsSummary.get", period="range", date=f"{start},{end}")
        daily = self._query("VisitsSummary.get", period="day", date=f"{start},{end}")
        # Unique visitors over a range may be disabled by the Matomo operator.
        metrics = [
            metric("visits", "Визиты", totals.get("nb_visits", 0)),
            metric("actions", "Действия", totals.get("nb_actions", 0)),
        ]
        if "nb_uniq_visitors" in totals:
            metrics.insert(0, metric("users", "Посетители", totals["nb_uniq_visitors"]))
        return {
            "metrics": metrics,
            "series": [
                {
                    "date": d,
                    "users": v.get("nb_uniq_visitors"),
                    "visits": v.get("nb_visits", 0),
                    "actions": v.get("nb_actions", 0),
                }
                for d, v in daily.items()
            ],
            "date1": start,
            "date2": end,
        }

    def report(self, report, start, end):
        method = {
            "channels": "Referrers.getReferrerType",
            "devices": "DevicesDetection.getType",
            "pages": "Actions.getPageUrls",
            "geography": "UserCountry.getCountry",
            "events": "Events.getCategory",
            "goals": "Goals.get",
        }[report]
        body = self._query(method, period="range", date=f"{start},{end}")
        if isinstance(body, dict):
            return table([body])
        return table(
            [
                {
                    k: v
                    for k, v in row.items()
                    if isinstance(v, (str, int, float))
                    and k not in {"logo", "url", "idsubdatatable"}
                }
                for row in body[:50]
            ]
        )


class Amplitude:
    def __init__(self, config):
        self.config = config
        self.base = (
            "https://analytics.eu.amplitude.com/api/2"
            if config.get("region") == "EU"
            else "https://amplitude.com/api/2"
        )

    def _query(self, path, **params):
        return request_json(
            "GET",
            self.base + path,
            auth=(self.config["api_key"], self.config["secret_key"]),
            params=params,
        ).get("data", {})

    def metadata(self):
        self._query("/events/list")
        return {"name": "Amplitude", "region": self.config.get("region", "US")}

    def overview(self, start, end):
        body = self._query(
            "/users",
            start=start.replace("-", ""),
            end=end.replace("-", ""),
            m="active",
            i=1,
        )
        values = (body.get("series") or [[]])[0]
        series = [
            {"date": d, "users": v} for d, v in zip(body.get("xValues", []), values)
        ]
        # Daily uniques must not be summed and described as period uniques.
        return {
            "metrics": [
                metric(
                    "users",
                    "В среднем за день",
                    sum(values) / len(values) if values else 0,
                )
            ],
            "series": series,
            "date1": start,
            "date2": end,
        }

    def report(self, report, start, end):
        body = self._query("/events/list")
        return {
            **table(
                [
                    {
                        "Событие": r.get("display", r.get("name", "")),
                        "Активно": r.get("active", True),
                    }
                    for r in body[:100]
                ]
            ),
            "total_rows": len(body),
            "note": "Каталог событий проекта, независимо от выбранного периода. Показано до 100 типов.",
        }


class Mixpanel:
    def __init__(self, config):
        self.config = config
        self.base = {
            "US": "https://mixpanel.com",
            "EU": "https://eu.mixpanel.com",
            "IN": "https://in.mixpanel.com",
        }[config.get("region", "US")] + "/api/query"

    def _query(self, path, **params):
        return request_json(
            "GET",
            self.base + path,
            auth=(self.config["username"], self.config["secret"]),
            params={"project_id": self.config["project_id"], **params},
        )

    def metadata(self):
        self._query("/events/names", type="general", limit=1)
        return {"name": "Mixpanel · " + self.config["project_id"]}

    def overview(self, start, end):
        values = self._event_counts(start, end)
        dates = sorted({day for event in values.values() for day in event})
        series = [
            {"date": day, "events": sum(event.get(day, 0) for event in values.values())}
            for day in dates
        ]
        return {
            "metrics": [
                metric(
                    "events", "События · топ-50 типов", sum(r["events"] for r in series)
                )
            ],
            "series": series,
            "date1": start,
            "date2": end,
            "note": "Сводка по 50 популярным за последние 31 день типам событий.",
        }

    def _event_counts(self, start, end):
        names = self._query("/events/names", type="general", limit=50)
        if not names:
            return {}
        return (
            self._query(
                "/events",
                event=json.dumps(names[:50]),
                from_date=start,
                to_date=end,
                unit="day",
                type="general",
            )
            .get("data", {})
            .get("values", {})
        )

    def report(self, report, start, end):
        values = self._event_counts(start, end)
        return {
            **table(
                sorted(
                    [
                        {"Событие": name, "Количество": sum(days.values())}
                        for name, days in values.items()
                    ],
                    key=lambda r: r["Количество"],
                    reverse=True,
                )
            ),
            "note": "Сводка по 50 популярным за последние 31 день типам событий.",
        }


class PostHog:
    def __init__(self, config):
        self.config = config
        self.base = (
            "https://eu.posthog.com"
            if config.get("region") == "EU"
            else "https://us.posthog.com"
        )
        self.headers = {"Authorization": "Bearer " + config["token"]}

    def metadata(self):
        body = request_json(
            "GET",
            f"{self.base}/api/projects/{self.config['project_id']}/",
            headers=self.headers,
        )
        return {
            "name": body.get("name", "PostHog"),
            "timezone": body.get("timezone", ""),
        }

    def _query(self, sql):
        return request_json(
            "POST",
            f"{self.base}/api/projects/{self.config['project_id']}/query/",
            headers=self.headers,
            json={"query": {"kind": "HogQLQuery", "query": sql}},
        ).get("results", [])

    def _where(self, start, end):
        start, end = period(start, end)
        return f"timestamp >= toDateTime('{start}') AND timestamp < toDateTime('{end}') + INTERVAL 1 DAY"

    def overview(self, start, end):
        where = self._where(start, end)
        totals = self._query(
            f"SELECT uniq(person_id), count() FROM events WHERE {where}"
        )
        rows = self._query(
            f"SELECT toDate(timestamp), uniq(person_id), count() FROM events WHERE {where} GROUP BY toDate(timestamp) ORDER BY toDate(timestamp) LIMIT 366"
        )
        return {
            "metrics": [
                metric("users", "Пользователи", totals[0][0]),
                metric("events", "События", totals[0][1]),
            ],
            "series": [
                {"date": str(r[0])[:10], "users": r[1], "events": r[2]} for r in rows
            ],
            "date1": start,
            "date2": end,
        }

    def report(self, report, start, end):
        dimension = {
            "events": "event",
            "pages": "properties.$pathname",
            "devices": "properties.$device_type",
            "geography": "properties.$geoip_country_name",
        }[report]
        rows = self._query(
            f"SELECT {dimension}, count(), uniq(person_id) FROM events WHERE {self._where(start, end)} GROUP BY {dimension} ORDER BY count() DESC LIMIT 50"
        )
        return {
            **table(
                [
                    {
                        "Название": r[0] or "Не определено",
                        "События": r[1],
                        "Пользователи": r[2],
                    }
                    for r in rows
                ]
            ),
            "limited": len(rows) == 50,
        }


ADAPTERS = {
    "metrika": Metrika,
    "ga4": GA4,
    "matomo": Matomo,
    "amplitude": Amplitude,
    "mixpanel": Mixpanel,
    "posthog": PostHog,
}


def adapter(provider, config):
    from .catalog import PROVIDERS

    if provider not in ADAPTERS:
        raise ConnectorError("Неизвестный источник данных.")
    for field in PROVIDERS[provider]["fields"]:
        value = config.get(field["key"], "")
        if not isinstance(value, str) or not value.strip() or len(value) > 20000:
            raise ConnectorError("Заполните поле «" + field["label"] + "».")
        if field["options"] and value not in field["options"]:
            raise ConnectorError("Выберите регион из списка.")
        if field["key"].endswith("_id") and not value.isdigit():
            raise ConnectorError("Идентификатор должен состоять из цифр.")
    return ADAPTERS[provider](config)
