"""Bounded native reporting operations; every destination and account is server-owned."""

import re
from datetime import date

from .http import ConnectorError, request_json
from .metrika import period
from .metrika_explorer import GROUPS


def metrika_series(client, start, end, metrics, group, dimensions, filters, timezone, accuracy):
    names, dims = metrics.split(","), dimensions.split(",") if dimensions else []
    if (group not in GROUPS or ((date.fromisoformat(end) - date.fromisoformat(start)).days + 1) * GROUPS.get(group, 1) > 1600
            or not 1 <= len(names) <= 10 or len(dims) > 3
            or any(not re.fullmatch(r"ym:s:[A-Za-z0-9<>]+", n) for n in names + dims)
            or len(filters) > 4000 or accuracy not in {"medium", "full"}):
        raise ConnectorError("Некорректный временной запрос: до 1600 точек, 10 метрик и 3 группировок.")
    params = dict(ids=client.counter_id, date1=start, date2=end, metrics=metrics, group=group,
                  accuracy=accuracy, filters=filters, lang="ru", top_keys=30, include_undefined="true")
    if dimensions:
        params["dimensions"] = dimensions
    if timezone:
        if not re.fullmatch(r"[+-](?:[01]\d|2[0-3]):[0-5]\d", timezone):
            raise ConnectorError("Часовой пояс задаётся как +03:00.")
        params["timezone"] = timezone
    body = client._get("/stat/v1/data/bytime", **params)
    rows = []
    for series in body.get("data", []):
        labels = {k: v.get("name") or v.get("id") or "Не определено" for k, v in zip(dims, series.get("dimensions", []))}
        values = series.get("metrics", [])
        for i, interval in enumerate(body.get("time_intervals", [])):
            rows.append({"date": interval[0], "end": interval[-1], **labels,
                         **{name: values[j][i] if j < len(values) and i < len(values[j]) else None for j, name in enumerate(names)}})
    return {"rows": rows, "date1": start, "date2": end, "timezone": timezone or "counter", "group": group,
            "dimensions": dims, "metrics": names, "totals": body.get("totals", []),
            "sampled": body.get("sampled", False), "sample_share": body.get("sample_share", 1),
            "data_lag": body.get("data_lag", 0), "contains_sensitive_data": body.get("contains_sensitive_data", False),
            "dimension_combinations": body.get("total_rows", len(body.get("data", []))),
            "limited": body.get("total_rows", len(body.get("data", []))) > len(body.get("data", [])),
            "note": "Time buckets describe the requested API metric, not automatically concurrent players. Unknown buckets remain null."}


def native_query(provider, client, body):
    if not isinstance(body, dict):
        raise ConnectorError("Запрос должен быть JSON-объектом.")
    if provider == "ga4":
        allowed = {"dateRanges", "metrics", "dimensions", "dimensionFilter", "metricFilter", "orderBys",
                   "limit", "offset", "keepEmptyRows", "metricAggregations", "cohortSpec"}
        if set(body) - allowed:
            raise ConnectorError("Неизвестные поля GA4: " + ", ".join(sorted(set(body) - allowed)))
        if not body.get("metrics") or len(body["metrics"]) > 10 or len(body.get("dimensions", [])) > 9:
            raise ConnectorError("Укажите до 10 метрик и 9 группировок.")
        if not body.get("dateRanges") and not body.get("cohortSpec"):
            raise ConnectorError("Укажите dateRanges или cohortSpec.")
        for span in body.get("dateRanges", []):
            period(span["startDate"], span["endDate"])
        limit = int(body.get("limit", 500))
        offset = int(body.get("offset", 0))
        if not 1 <= limit <= 2000 or not 0 <= offset <= 100000:
            raise ConnectorError("GA4: limit 1–2000, offset 0–100000.")
        result = request_json("POST", f"https://analyticsdata.googleapis.com/v1beta/properties/{client.config['property_id']}:runReport",
                              headers={"Authorization": "Bearer " + client._access_token()},
                              json={**body, "limit": str(limit), "offset": str(offset), "returnPropertyQuota": True})
        dims = [h["name"] for h in result.get("dimensionHeaders", [])]
        metrics = [h["name"] for h in result.get("metricHeaders", [])]
        rows = [{**{k: v["value"] for k, v in zip(dims, row.get("dimensionValues", []))},
                 **{k: float(v["value"]) for k, v in zip(metrics, row.get("metricValues", []))}}
                for row in result.get("rows", [])]
        return {"rows": rows, "total_rows": result.get("rowCount", len(rows)),
                "has_more": offset + len(rows) < result.get("rowCount", len(rows)),
                "metadata": result.get("metadata", {}), "quota": result.get("propertyQuota", {}), "query": body}
    if provider == "matomo":
        methods = {"VisitsSummary.get", "VisitTime.getVisitInformationPerServerTime", "VisitTime.getByDayOfWeek",
                   "UserCountry.getCountry", "UserCountry.getRegion", "UserCountry.getCity", "Actions.getPageUrls",
                   "Actions.getEntryPageUrls", "Actions.getExitPageUrls", "Events.getCategory", "Events.getAction",
                   "Events.getName", "Goals.get", "Referrers.getReferrerType", "Referrers.getCampaigns",
                   "DevicesDetection.getType", "DevicesDetection.getBrowsers", "UserId.getUsers",
                   "CustomVariables.getCustomVariables", "CustomDimensions.getCustomDimension"}
        method = body.get("method")
        allowed = {"period", "date", "segment", "idGoal", "idDimension", "idSubtable", "filter_limit",
                   "filter_offset", "filter_sort_column", "filter_sort_order", "flat", "expanded", "columns", "showColumns"}
        params = {k: v for k, v in body.items() if k != "method"}
        if method not in methods or set(params) - allowed:
            raise ConnectorError("Unsupported Matomo read operation. Available methods: " + ", ".join(sorted(methods)))
        if not 1 <= int(params.get("filter_limit", 500)) <= 2000 or int(params.get("filter_offset", 0)) < 0:
            raise ConnectorError("Matomo: filter_limit 1–2000, nonnegative filter_offset.")
        result = client._query(method, **{**params, "filter_limit": int(params.get("filter_limit", 500))})
        return {"rows": result if isinstance(result, list) else [result], "query": body,
                "note": "Result may be paginated or nested by date; inspect it before calculating totals."}
    if provider in {"amplitude", "mixpanel"}:
        routes = ({"/events/list", "/events/segmentation", "/funnels", "/retention", "/users"}
                  if provider == "amplitude" else {"/events/names", "/events", "/segmentation", "/retention", "/funnels"})
        endpoint, params = body.get("endpoint"), body.get("params", {})
        if set(body) - {"endpoint", "params"} or endpoint not in routes or not isinstance(params, dict):
            raise ConnectorError("Use endpoint and params; available read endpoints: " + ", ".join(sorted(routes)))
        if any(k.lower() in {"project_id", "api_key", "secret", "secret_key", "token", "token_auth", "username"} for k in params):
            raise ConnectorError("Реквизиты и проект задаются подключением.")
        if len(params) > 25 or any(isinstance(v, (dict, list)) for v in params.values()):
            raise ConnectorError("Native API params must be scalar; encode event/filter objects as JSON strings.")
        result = client._query(endpoint, **params)
        return {"rows": result, "query": body} if isinstance(result, list) else {"data": result, "query": body}
    if provider == "posthog":
        sql = body.get("sql", "")
        if (set(body) != {"sql"} or not isinstance(sql, str) or not re.match(r"\s*(SELECT|WITH)\b", sql, re.I)
                or ";" in sql or len(sql) > 16000):
            raise ConnectorError("PostHog accepts one SELECT/WITH HogQL query without semicolons.")
        # The query API is a reporting endpoint; wrap its output with a row bound.
        response = request_json("POST", f"{client.base}/api/projects/{client.config['project_id']}/query/",
                                headers=client.headers, json={"query": {"kind": "HogQLQuery", "query": f"SELECT * FROM ({sql}) LIMIT 2001"}})
        values = response.get("results", [])
        columns = response.get("columns", [])
        return {"rows": [dict(zip(columns, row)) for row in values[:2000]], "limited": len(values) > 2000,
                "columns": columns, "query": body}
    raise ConnectorError("Use the provider's discovered report operations; Metrica has metrika_query and metrika_timeseries.")
