"""Bounded, read-only Metrica report builder and its public capability catalogue.

Reference: https://yandex.ru/dev/metrika/ru/stat/ (checked 2026-09-13).
Only session-scope dimensions/metrics are combined here; hit-scope reports need
their own metric set. Source credentials and counter selection stay server-owned.
"""

from datetime import date, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .http import ConnectorError
from .metrika import period


METRICS = {
    "users": ("Посетители", "users", "number"),
    "visits": ("Визиты", "visits", "number"),
    "views": ("Просмотры", "pageviews", "number"),
    "bounce": ("Отказы", "bounceRate", "percent"),
    "depth": ("Глубина просмотра", "pageDepth", "number"),
    "duration": ("Время на сайте", "avgVisitDurationSeconds", "duration"),
    "new_users": ("Новые посетители", "newUsers", "number"),
    "new_share": ("Доля новых посетителей", "percentNewVisitors", "percent"),
    "goal_reaches": ("Достижения цели", "goal{goal}reaches", "number"),
    "goal_visits": ("Целевые визиты", "goal{goal}visits", "number"),
    "goal_users": ("Целевые посетители", "goal{goal}users", "number"),
    "conversion": ("Конверсия", "goal{goal}conversionRate", "percent"),
}
# Fields with Name suffix accept human-readable filter values with lang=ru.
DIMENSIONS = {
    "channel": ("Канал привлечения", "{attribution}TrafficSourceName", "Источники"),
    "search_engine": ("Поисковая система", "{attribution}SearchEngineRootName", "Источники"),
    "search_phrase": ("Поисковая фраза", "{attribution}SearchPhrase", "Источники"),
    "referrer": ("Ссылающаяся страница", "referer", "Источники"),
    "utm_source": ("UTM source", "{attribution}UTMSource", "UTM-метки"),
    "utm_medium": ("UTM medium", "{attribution}UTMMedium", "UTM-метки"),
    "utm_campaign": ("UTM campaign", "{attribution}UTMCampaign", "UTM-метки"),
    "utm_content": ("UTM content", "{attribution}UTMContent", "UTM-метки"),
    "utm_term": ("UTM term", "{attribution}UTMTerm", "UTM-метки"),
    "device": ("Тип устройства", "deviceCategoryName", "Технологии"),
    "browser": ("Браузер", "browserName", "Технологии"),
    "os": ("Операционная система", "operatingSystemRootName", "Технологии"),
    "screen": ("Разрешение экрана", "screenResolution", "Технологии"),
    "country": ("Страна", "regionCountryName", "География"),
    "region": ("Регион", "regionAreaName", "География"),
    "city": ("Город", "regionCityName", "География"),
    "landing": ("Страница входа", "startURL", "Страницы"),
    "exit": ("Страница выхода", "endURL", "Страницы"),
    "new_visitor": ("Новый посетитель", "isNewUser", "Аудитория"),
    "gender": ("Пол", "gender", "Аудитория"),
    "age": ("Возраст", "ageIntervalName", "Аудитория"),
    "robot": ("Робот", "isRobot", "Аудитория"),
    "visit_param": ("Параметр визита · уровень 1", "paramsLevel1", "Параметры"),
    "visit_param2": ("Параметр визита · уровень 2", "paramsLevel2", "Параметры"),
    "visit_param3": ("Параметр визита · уровень 3", "paramsLevel3", "Параметры"),
}
PRESETS = [
    dict(id="overview", label="Обзор", dimensions=[]),
    dict(id="channels", label="Каналы", dimensions=["channel"]),
    dict(id="campaigns", label="UTM-метки", dimensions=["utm_source", "utm_campaign"]),
    dict(id="audience", label="Аудитория", dimensions=["new_visitor"]),
    dict(id="devices", label="Устройства", dimensions=["device"]),
    dict(id="pages", label="Страницы", dimensions=["landing"]),
    dict(id="geography", label="География", dimensions=["country"]),
    dict(id="goals", label="Цели", dimensions=[]),
    dict(id="parameters", label="Параметры", dimensions=["visit_param", "visit_param2"]),
    dict(id="custom", label="Свой отчёт", dimensions=[]),
]
GROUPS = {"minute": 1440, "dekaminute": 144, "hour": 24, "day": 1, "week": 1 / 7, "month": 1 / 28}
ATTRIBUTIONS = {"last_sign": "lastSign", "last": "last", "first": "first"}


class SegmentFilter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    field: str = Field(max_length=40)
    operator: Literal["eq", "neq", "contains", "not_contains"] = "eq"
    value: str = Field(min_length=1, max_length=250)


class ExplorerQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date1: str
    date2: str
    metrics: list[str] = Field(default_factory=lambda: ["users", "visits", "views", "bounce"], min_length=1, max_length=8)
    dimensions: list[str] = Field(default_factory=list, max_length=3)
    filters: list[SegmentFilter] = Field(default_factory=list, max_length=8)
    filter_mode: Literal["and", "or"] = "and"
    group: Literal["auto", "minute", "dekaminute", "hour", "day", "week", "month"] = "auto"
    accuracy: Literal["medium", "full"] = "medium"
    attribution: Literal["last_sign", "last", "first"] = "last_sign"
    include_undefined: bool = True
    goal_id: str = Field(default="", max_length=20, pattern=r"^\d*$")
    sort: str = Field(default="", max_length=40)
    descending: bool = True
    page: int = Field(default=1, ge=1, le=200)
    compare: bool = False
    refresh: bool = False

    @model_validator(mode="after")
    def validate_query(self):
        self.date1, self.date2 = period(self.date1, self.date2)
        if len(set(self.metrics)) != len(self.metrics) or len(set(self.dimensions)) != len(self.dimensions):
            raise ValueError("Не повторяйте показатели и группировки.")
        if any(key not in METRICS for key in self.metrics):
            raise ValueError("Неизвестный показатель.")
        if any(key not in DIMENSIONS for key in self.dimensions + [f.field for f in self.filters]):
            raise ValueError("Неизвестная группировка или фильтр.")
        if any("{goal}" in METRICS[key][1] for key in self.metrics) and not self.goal_id:
            raise ValueError("Выберите цель для показателей конверсии.")
        if self.sort and self.sort not in self.metrics + self.dimensions:
            raise ValueError("Сортировка должна быть по столбцу отчёта.")
        if any(f.field in {"new_visitor", "robot", "gender"} and f.operator not in {"eq", "neq"} for f in self.filters):
            raise ValueError("Для этого признака доступны только «равно» и «не равно».")
        if self.group != "auto" and self.days * GROUPS[self.group] > 1600:
            raise ValueError("Слишком много точек: сократите период или выберите более крупный интервал.")
        return self

    @property
    def days(self):
        return (date.fromisoformat(self.date2) - date.fromisoformat(self.date1)).days + 1

    @property
    def resolved_group(self):
        return self.group if self.group != "auto" else "dekaminute" if self.days == 1 else "day"

    def metric_name(self, key):
        return "ym:s:" + METRICS[key][1].format(goal=self.goal_id)

    def dimension_name(self, key):
        return "ym:s:" + DIMENSIONS[key][1].format(attribution=ATTRIBUTIONS[self.attribution])

    def filter_expression(self):
        operators = {"eq": "==", "neq": "!=", "contains": "=@", "not_contains": "!@"}
        parts = []
        for item in self.filters:
            value = item.value.replace("\\", "\\\\").replace("'", "\\'")
            parts.append(f"{self.dimension_name(item.field)}{operators[item.operator]}'{value}'")
        return (" AND " if self.filter_mode == "and" else " OR ").join(parts)

    def previous(self):
        last = date.fromisoformat(self.date1) - timedelta(days=1)
        return self.model_copy(update={"date1": (last - timedelta(days=self.days - 1)).isoformat(), "date2": last.isoformat(), "compare": False, "page": 1, "dimensions": []})


def explorer_catalog():
    return {
        "metrics": [dict(key=k, label=v[0], format=v[2], goal="{goal}" in v[1]) for k, v in METRICS.items()],
        "dimensions": [dict(key=k, label=v[0], category=v[2], operators=["eq", "neq"] if k in {"new_visitor", "robot", "gender"} else ["eq", "neq", "contains", "not_contains"]) for k, v in DIMENSIONS.items()],
        "presets": PRESETS,
        "max_points": 1600,
    }
