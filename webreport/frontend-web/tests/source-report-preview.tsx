// Dev-only fixture: synthetic values, no credentials or external API calls.
import { createRoot } from "react-dom/client";
import { SourcePreview } from "../src/SourceDialog";
import { applyAccent, defaultAccent } from "../src/theme";
import { localDate, presetDates } from "../src/report-period";
import "../src/styles.css";

import catalog from "./explorer-catalog.json";
import type { ExplorerQuery } from "../src/metrika-types";

function fixtureReport(query: ExplorerQuery): any {
  const step =
    {
      minute: 1,
      dekaminute: 10,
      hour: 60,
      day: 1440,
      week: 10080,
      month: 43200,
    }[
      query.group === "auto"
        ? query.date1 === query.date2
          ? "dekaminute"
          : "day"
        : query.group
    ] || 1440;
  const group =
    query.group === "auto"
      ? query.date1 === query.date2
        ? "dekaminute"
        : "day"
      : query.group;
  const start = new Date(query.date1 + "T00:00:00"),
    end = new Date(query.date2 + "T23:59:59");
  const series = [];
  for (
    let at = start.getTime();
    at <= end.getTime() && series.length < 1600;
    at += step * 60000
  ) {
    const date = new Date(at),
      i = series.length;
    const stamp =
      localDate(date) +
      (step < 1440
        ? " " +
          String(date.getHours()).padStart(2, "0") +
          ":" +
          String(date.getMinutes()).padStart(2, "0") +
          ":00"
        : "");
    series.push({
      date: stamp,
      ...Object.fromEntries(
        query.metrics.map((key, index) => [
          key,
          key === "duration"
            ? 300 + ((i * 51) % 150)
            : key === "bounce" || key === "conversion"
              ? 3 + (i % 4)
              : 300 + ((i * 71) % 240) + index * 100,
        ]),
      ),
    });
  }
  const metrics = query.metrics.map((key) => ({
    ...catalog.metrics.find((m) => m.key === key)!,
    value:
      key === "bounce" || key === "conversion"
        ? 5.6
        : key === "duration"
          ? 573
          : 1820,
  }));
  const rows = Array.from({ length: query.page === 1 ? 50 : 3 }, (_, i) => ({
    ...Object.fromEntries(
      query.dimensions.map((key, n) => [
        key,
        (key === "country"
          ? ["Россия", "Вьетнам", "США"]
          : key === "device"
            ? ["Смартфоны", "ПК", "Планшеты"]
            : ["Пример A", "Пример B", "Пример C"])[(i + n) % 3] +
          " " +
          (i + 1 + (query.page - 1) * 50),
      ]),
    ),
    ...Object.fromEntries(
      query.metrics.map((key, index) => [
        key,
        key === "bounce" || key === "conversion" || key === "new_share"
          ? 3 + (i % 7)
          : key === "depth"
            ? 1.7 + (i % 3)
            : 1720 - i * 31 + index * 100,
      ]),
    ),
  }));
  const report = {
    date1: query.date1,
    date2: query.date2,
    group,
    timezone: "Europe/Moscow",
    metrics,
    series,
    rows,
    dimension_values: rows.map((row) =>
      Object.fromEntries(query.dimensions.map((key) => [key, row[key]])),
    ),
    columns: [
      ...query.dimensions.map((key) => ({
        key,
        label: catalog.dimensions.find((d) => d.key === key)?.label,
        kind: "dimension",
      })),
      ...metrics.map((m) => ({ ...m, kind: "metric" })),
    ],
    total_rows: 53,
    page: query.page,
    has_more: query.page === 1,
    sampled: false,
    sample_share: 1,
    contains_sensitive_data: false,
    data_lag: 60,
    cached: false,
    cache: { totals: false, series: false, table: false },
    fetched_at: new Date().toISOString(),
  };
  if (!query.compare) return report;
  const days =
    Math.round((Date.parse(query.date2) - Date.parse(query.date1)) / 86400000) +
    1;
  const previousEnd = new Date(start);
  previousEnd.setDate(previousEnd.getDate() - 1);
  const previousStart = new Date(previousEnd);
  previousStart.setDate(previousStart.getDate() - days + 1);
  return {
    ...report,
    comparison: fixtureReport({
      ...query,
      date1: localDate(previousStart),
      date2: localDate(previousEnd),
      compare: false,
    }),
  };
}
window.fetch = async (input, options) => {
  const url = new URL(String(input), location.origin);
  const data = url.pathname.endsWith("/catalog")
    ? catalog
    : url.pathname.endsWith("/goals")
      ? {
          goals: [
            { id: "12", name: "Завершён уровень", type: "action" },
            { id: "13", name: "Возвращение в игру", type: "action" },
          ],
        }
      : fixtureReport(JSON.parse(String(options?.body)));
  return new Response(JSON.stringify(data), {
    headers: { "Content-Type": "application/json" },
  });
};
applyAccent(defaultAccent);
// Browser acceptance trace: inspect the first visible frame separately from
// subsequent cursor movement, including re-entry after leaving the chart.
const trace = document.createElement("output");
trace.id = "tooltip-trace";
trace.style.cssText =
  "position:fixed;bottom:0;left:0;z-index:100;color:#536a7e;background:#fff;font:9px monospace;max-width:360px";
document.body.append(trace);
let wasVisible = false,
  lastTransform = "";
const events: { event: string; transition: string; transform: string }[] = [];
new MutationObserver(() => {
  const tooltip = document.querySelector<HTMLElement>(
    ".recharts-tooltip-wrapper",
  );
  const visible = !!tooltip && tooltip.style.visibility === "visible";
  const transform = tooltip?.style.transform || "";
  if (visible && (!wasVisible || transform !== lastTransform)) {
    events.push({
      event: wasVisible ? "move" : "enter",
      transition: tooltip!.style.transition,
      transform,
    });
    if (events.length > 16) events.shift();
    trace.textContent = JSON.stringify(events);
  }
  wasVisible = visible;
  lastTransform = transform;
}).observe(document.body, {
  attributes: true,
  attributeFilter: ["style"],
  subtree: true,
});
createRoot(document.getElementById("root")!).render(
  <SourcePreview
    source={{
      id: "demo",
      project_id: "demo",
      name: "Демо · аналитика сайта",
      provider: "metrika",
      connected: true,
      metadata: { site: "example.com" },
    }}
    provider={{
      id: "metrika",
      name: "Яндекс Метрика",
      color: "",
      description: "",
      docs: "",
      fields: [],
      reports: [
        "overview",
        "channels",
        "devices",
        "pages",
        "geography",
        "goals",
      ],
    }}
    defaultPeriod={presetDates("month")}
    onClose={() => {}}
    onManage={() => {}}
    onConnectionChange={() => {}}
  />,
);
