"""Operator tool surface scoped to the sources of exactly one project."""

import pandas as pd

from .catalog import PROVIDERS
from .http import ConnectorError
from .metrika import default_period, period
from .providers import adapter


class AnalyticsService:
    def __init__(self, sources, credentials, report_reader):
        self._sources = {s["id"]: s for s in sources}
        self._credentials = credentials
        self._read = report_reader

    def list_sources(self) -> pd.DataFrame:
        """List this project's connected analytics sources and their available reports. Call this first; source IDs are required by the other analytics tools."""
        return pd.DataFrame(
            [
                {
                    "source_id": s["id"],
                    "name": s["name"],
                    "provider": s["provider"],
                    "reports": PROVIDERS[s["provider"]]["reports"],
                    "metadata": s.get("metadata", {}),
                }
                for s in self._sources.values()
            ]
        )

    def analytics_overview(
        self, source_id: str, date_from: str = "", date_to: str = ""
    ) -> dict:
        """Get bounded summary metrics and daily trends from one project source. Dates are YYYY-MM-DD; omitted dates use the last 30 complete days. Never sum daily unique users into period uniques."""
        self._source(source_id)
        start, end = self._dates(date_from, date_to)
        return self._read(source_id, "overview", start, end)

    def analytics_report(
        self,
        source_id: str,
        report: str,
        date_from: str = "",
        date_to: str = "",
        page: int = 1,
    ) -> dict:
        """Read a detailed report available from list_sources: channels, devices, pages, geography, goals or events. Metrica supports pages of 50 rows (page starts at 1); request the next page to discover more goals or rows. The result includes rows, sampling, total count and pagination metadata. Mention any sampling or limiting note in the answer."""
        self._source(source_id)
        start, end = self._dates(date_from, date_to)
        result = self._read(source_id, report, start, end, page=page)
        return result

    def metrika_query(
        self,
        source_id: str,
        metrics: str = "ym:s:users,ym:s:visits",
        dimensions: str = "",
        date_from: str = "",
        date_to: str = "",
        limit: int = 100,
        filters: str = "",
    ) -> dict:
        """Query a connected Yandex Metrica counter, read-only, up to 500 rows and 366 days. Supply Reporting API metrics/dimensions (comma-separated), e.g. ym:s:visits and ym:s:lastTrafficSource. Filters use Metrica's filter syntax. Only the saved counter is accessible. The result includes totals and sampling metadata."""
        source = self._source(source_id)
        if source["provider"] != "metrika":
            raise ConnectorError("Этот источник не является Яндекс Метрикой.")
        start, end = self._dates(date_from, date_to)
        return adapter("metrika", self._credentials[source_id]).query(
            start, end, metrics, dimensions, limit, filters
        )

    def _source(self, source_id):
        if source_id not in self._sources:
            raise ConnectorError("Источник не принадлежит текущему проекту.")
        return self._sources[source_id]

    def _dates(self, start, end):
        default_start, default_end = default_period()
        return period(start or default_start, end or default_end)
