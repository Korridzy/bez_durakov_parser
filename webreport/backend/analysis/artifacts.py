"""Validated data-only chart contract shared with the analysis side panel."""

import math
from .storage import rows_at

KINDS = {"line", "area", "bar", "stacked_bar", "scatter", "histogram", "heatmap", "funnel", "table"}


def source_warnings(provenance):
    warnings = []
    metadata = provenance.get("metadata", {})
    if metadata.get("sampled"):
        share = metadata.get("sample_share")
        warnings.append("Источник использовал выборку" + (f": {share * 100:.1f}% данных." if isinstance(share, (int, float)) else "."))
    if metadata.get("limited") or metadata.get("has_more"):
        warnings.append("В одном из исходных запросов получена часть строк. Проверьте полноту объединения страниц в расчёте.")
    if metadata.get("contains_sensitive_data"):
        warnings.append("Источник может скрывать некоторые значения из-за порога конфиденциальности.")
    lag = metadata.get("data_lag")
    if isinstance(lag, (float, int)) and lag > 0:
        warnings.append(f"Задержка обновления источника: {lag:g} с.")
    for source in provenance.get("sources", []):
        warnings.extend(source_warnings(source))
    return list(dict.fromkeys(warnings))


def make_artifact(record, *, title, kind, x, series, table="rows", subtitle="", note="",
                  value_format="number", unit="", y="", bins=20, x_label="", y_label=""):
    if kind not in KINDS or value_format not in {"number", "percent", "duration"}:
        raise ValueError("Unsupported chart kind or number format")
    if not title.strip() or len(title) > 120 or len(subtitle) > 240 or len(note) > 1000 or len(unit) > 24:
        raise ValueError("Chart labels exceed their limits")
    if len(x_label) > 120 or len(y_label) > 120:
        raise ValueError("Axis labels must have at most 120 characters")
    rows = rows_at(record["value"], table)
    if not rows:
        raise ValueError("No rows to plot; explain the missing data instead")
    if not 1 <= len(series) <= 6 or any(set(s) != {"column", "label"} for s in series):
        raise ValueError("Supply 1–6 series, each with column and label")
    if len({s["column"] for s in series}) != len(series):
        raise ValueError("Series columns must be distinct")
    if any(not isinstance(s["label"], str) or not 1 <= len(s["label"]) <= 80 for s in series):
        raise ValueError("Series labels must have 1–80 characters")
    if kind in {"scatter", "histogram", "heatmap", "funnel"} and len(series) != 1:
        raise ValueError("This chart kind takes exactly one value series")

    def number(value):
        if value is None:
            return None
        if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or abs(value) > 1e15:
            raise ValueError("Chart values must be finite numbers or null; calculate and convert them first")
        return value

    data = []
    for index, row in enumerate(rows):
        if x not in row or any(s["column"] not in row for s in series):
            raise ValueError("A requested column is missing from the data")
        category = str(index) if kind == "histogram" else number(row[x]) if kind == "scatter" else str(row[x]) if row[x] is not None else ""
        if category is None or category == "" or len(str(category)) > 120:
            raise ValueError("Every row needs an x value")
        item = {"x": category, **{f"s{i}": number(row[s["column"]]) for i, s in enumerate(series)}}
        if kind == "heatmap":
            if y not in row or row[y] is None or not 1 <= len(str(row[y])) <= 120:
                raise ValueError("Heatmaps require a second category column y")
            item["y"] = str(row[y])
        data.append(item)
    if kind == "histogram":
        if not 2 <= bins <= 60:
            raise ValueError("Use 2–60 histogram bins")
        values = [row["s0"] for row in data if row["s0"] is not None]
        if not values:
            raise ValueError("No observed values for a histogram")
        low, high = min(values), max(values)
        width = (high - low) / bins if high != low else 1
        count = bins if high != low else 1
        counts = [0] * count
        for value in values:
            counts[min(int((value - low) / width), count - 1)] += 1
        data = [{"x": f"{low + i * width:.5g} – {low + (i + 1) * width:.5g}", "s0": n} for i, n in enumerate(counts)]
        series = [{"column": series[0]["column"], "label": "Количество наблюдений"}]
        value_format, unit = "number", ""
    if len(data) > (2000 if kind in {"scatter", "table"} else 1600):
        raise ValueError("Too many chart points; aggregate explicitly using run_python")
    if kind == "heatmap" and len({d["x"] for d in data}) * len({d["y"] for d in data}) > 1600:
        raise ValueError("Heatmap exceeds 1600 cells including gaps; aggregate or filter its categories first")
    if kind not in {"scatter", "histogram", "table"}:
        keys = [(d["x"], d.get("y")) for d in data]
        if len(keys) != len(set(keys)):
            raise ValueError("Duplicate categories; aggregate or pivot the data first")
    if any(all(row[f"s{i}"] is None for row in data) for i in range(len(series))):
        raise ValueError("Each series needs at least one observed value")
    if kind == "funnel":
        values = [row["s0"] for row in data]
        if len(values) > 20 or any(v is None or v < 0 for v in values) or values != sorted(values, reverse=True):
            raise ValueError("A funnel needs up to 20 ordered, nonnegative, nonincreasing step counts")
    return {"version": 1, "kind": kind, "title": title, "subtitle": subtitle, "note": note,
            "format": value_format, "unit": unit, "x_label": x_label or x, "y_label": y_label or y,
            "series": [{"key": f"s{i}", "label": s["label"]} for i, s in enumerate(series)],
            "data": data, "source_result": record["id"], "provenance": record["provenance"],
            "warnings": source_warnings(record["provenance"])}
