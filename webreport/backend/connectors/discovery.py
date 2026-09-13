"""Source descriptions and bounded reading of official field documentation."""

from html.parser import HTMLParser
import re
from functools import lru_cache

import requests
from .http import ConnectorError, request_json
from .metrika_explorer import METRICS, DIMENSIONS

DOCS = {
    "metrika": {
        "fields": "https://yandex.ru/dev/metrika/ru/stat/attrandmetr/dim_all",
        "query": "https://yandex.ru/dev/metrika/ru/stat/openapi/data",
        "time": "https://yandex.ru/dev/metrika/ru/stat/openapi/bytime",
        "filters": "https://yandex.ru/dev/metrika/ru/stat/segmentation",
    },
    "ga4": {
        "fields": "https://developers.google.com/analytics/devguides/reporting/data/v1/api-schema",
        "query": "https://developers.google.com/analytics/devguides/reporting/data/v1/rest/v1beta/properties/runReport",
    },
    "matomo": {"query": "https://developer.matomo.org/api-reference/reporting-api"},
    "amplitude": {"query": "https://amplitude.com/docs/apis/analytics/dashboard-rest"},
    "mixpanel": {"query": "https://developer.mixpanel.com/reference/segmentation-query"},
    "posthog": {"query": "https://posthog.com/docs/api/queries"},
}


class DocumentText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.skip = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "svg"}:
            self.skip += 1
        if tag in {"p", "h1", "h2", "h3", "h4", "li", "tr", "br", "pre"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "svg"}:
            self.skip = max(0, self.skip - 1)
        if tag in {"p", "h1", "h2", "h3", "h4", "li", "tr", "pre"}:
            self.parts.append("\n")

    def handle_data(self, value):
        if not self.skip:
            self.parts.append(value)


@lru_cache(maxsize=16)
def official_text(provider, topic):
    url = DOCS.get(provider, {}).get(topic)
    if not url:
        raise ConnectorError("Нет такого раздела документации. Посмотрите source_schema.")
    try:
        with requests.get(url, timeout=(5, 25), allow_redirects=False, stream=True) as response:
            if response.status_code != 200:
                raise ConnectorError("Документация временно недоступна; используйте каталог полей.")
            chunks, size = [], 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > 8 * 1024 * 1024:
                    raise ConnectorError("Документ превышает допустимый размер.")
                chunks.append(chunk)
        parser = DocumentText()
        parser.feed(b"".join(chunks).decode("utf-8", errors="replace"))
        return url, "\n".join(line.strip() for line in "".join(parser.parts).splitlines() if line.strip())
    except requests.RequestException:
        raise ConnectorError("Не удалось прочитать официальную документацию.") from None


def documentation(provider, topic, search, offset):
    if not 0 <= offset <= 2_000_000 or len(search) > 150:
        raise ConnectorError("Недопустимый поиск в документации.")
    url, content = official_text(provider, topic)
    if search:
        matches = list(re.finditer(re.escape(search), content, re.IGNORECASE))
        # The field catalogue has a table of contents before the actual definitions.
        snippets = [content[max(0, m.start() - 100):m.start() + 1600] for m in matches[:5]]
        return {"url": url, "matches": len(matches), "text": "\n\n".join(snippets), "untrusted_reference": True}
    return {"url": url, "text": content[offset:offset + 7000], "next_offset": offset + 7000 if offset + 7000 < len(content) else None,
            "untrusted_reference": True}


def source_catalog(source, client, section):
    provider = source["provider"]
    if section == "overview":
        return {"source_id": source["id"], "name": source["name"], "provider": provider,
                "metadata": source.get("metadata", {}), "documentation": DOCS.get(provider, {}),
                "sections": ["overview", "fields", "goals"] if provider == "metrika" else ["overview", "fields"],
                "note": "Catalogued fields describe available query capabilities, not proof that every field has recorded values. Inspect sample values with a query."}
    if provider == "metrika":
        if section == "goals":
            return {"rows": client.goals(), "note": "Configured goals; not a complete inventory of all in-game events."}
        if section == "fields":
            metrics = [{"name": "ym:s:" + v[1], "label": v[0], "format": v[2]} for v in METRICS.values()]
            dimensions = [{"name": "ym:s:" + v[1].replace("{attribution}", "lastSign"), "label": v[0]} for v in DIMENSIONS.values()]
            dimensions += [{"name": "ym:s:" + key, "label": label} for key, label in {
                "date": "Дата визита", "dateTime": "Время визита", "hour": "Час визита",
                "startOfHour": "Дата и время начала часа", "clientID": "Идентификатор браузера",
                "visitDuration": "Длительность визита, секунды", "isNewUser": "Новый посетитель",
                "regionCountry": "Страна (ID)", "paramsLevel1": "Параметры визита: ключ",
                "paramsLevel2": "Параметры визита: второй уровень",
                "paramsLevel3": "Параметры визита: третий уровень",
            }.items()]
            return {"metrics": metrics, "dimensions": dimensions,
                    "complete": False, "more_fields": "Use source_documentation(topic='fields', search='field name or keyword'). Raw documented Reporting API names are accepted by metrika_query.",
                    "examples": {"country_duration": {"metrics": "ym:s:visits,ym:s:avgVisitDurationSeconds", "dimensions": "ym:s:regionCountryName"},
                                 "short_visits": {"metrics": "ym:s:visits", "dimensions": "ym:s:date", "filters": "ym:s:visitDuration<60"},
                                 "parameters": {"metrics": "ym:s:visits", "dimensions": "ym:s:paramsLevel1,ym:s:paramsLevel2"}},
                    "rules": ["Filters use API expressions, e.g. ym:s:regionCountryName=='Россия'. Names use lang=ru.",
                              "Goal placeholders must be replaced by a real goal ID from section=goals.",
                              "Use metrika_timeseries for hour/day/minute rows with explicit timezone like +03:00.",
                              "Metrics/dimensions are comma-separated. offset is 1-based. Fetch all relevant pages before global ranking.",
                              "Never mix incompatible event/session scopes. Consult definitions if unsure."]}
    if provider == "ga4" and section == "fields":
        body = request_json("GET", f"https://analyticsdata.googleapis.com/v1beta/properties/{client.config['property_id']}/metadata",
                            headers={"Authorization": "Bearer " + client._access_token()})
        return {"dimensions": body.get("dimensions", []), "metrics": body.get("metrics", [])}
    return {"note": "Use available reports to inspect real fields and event names, and source_documentation for native query syntax.",
            "documentation": DOCS.get(provider, {})}
