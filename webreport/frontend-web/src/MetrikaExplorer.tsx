import { useEffect, useRef, useState } from "react";
import {
  Activity,
  ArrowDown,
  ArrowUp,
  ChartColumn,
  ChartNoAxesCombined,
  Download,
  FileText,
  Globe2,
  LayoutDashboard,
  Radio,
  Settings2,
  SlidersHorizontal,
  Smartphone,
  Table2,
  Tags,
  Target,
  Users,
} from "lucide-react";
import type { Source, Provider } from "./types";
import { api, ApiError, dayLabel, number } from "./api";
import { Modal, ProviderIcon, Spinner } from "./ui";
import { Select } from "./Select";
import { ReportPeriod } from "./ReportPeriod";
import {
  AnalyticsChart,
  chartColors,
  metricValue,
  timeLabel,
} from "./AnalyticsChart";
import { ExplorerControls } from "./ExplorerControls";
import {
  counterToday,
  daysInQuery,
  groups,
  type ExplorerCatalog,
  type ExplorerQuery,
  type ExplorerReport,
} from "./metrika-types";
import "./metrika-explorer.css";

const icons: Record<string, typeof LayoutDashboard> = {
  overview: LayoutDashboard,
  channels: Radio,
  campaigns: Tags,
  audience: Users,
  devices: Smartphone,
  pages: FileText,
  geography: Globe2,
  goals: Target,
  parameters: SlidersHorizontal,
  custom: ChartNoAxesCombined,
};

function exportRows(report: ExplorerReport, timeline: boolean) {
  const columns = timeline
    ? [{ key: "date", label: "Дата и время" }, ...report.metrics]
    : report.columns;
  const rows = timeline ? report.series : report.rows;
  const cell = (value: unknown) => {
    let text = String(value ?? "");
    if (typeof value === "string" && /^[=+\-@\t\r]/.test(text))
      text = "'" + text;
    return '"' + text.replaceAll('"', '""') + '"';
  };
  const csv =
    "\uFEFF" +
    [
      columns.map((c) => cell(c.label)).join(";"),
      ...rows.map((row) => columns.map((c) => cell(row[c.key])).join(";")),
    ].join("\r\n");
  const url = URL.createObjectURL(
    new Blob([csv], { type: "text/csv;charset=utf-8" }),
  );
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `metrika-${report.date1}-${report.date2}${timeline ? "-timeline" : `-page-${report.page}`}.csv`;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export function MetrikaExplorer({
  source,
  provider,
  defaultPeriod,
  onClose,
  onManage,
  onConnectionChange,
}: {
  source: Source;
  provider: Provider;
  defaultPeriod: { date1: string; date2: string };
  onClose: () => void;
  onManage: () => void;
  onConnectionChange: (source: Source, needsKey?: boolean) => void;
}) {
  const [catalog, setCatalog] = useState<ExplorerCatalog>();
  const [catalogError, setCatalogError] = useState("");
  const [preset, setPreset] = useState("overview");
  const [query, setQuery] = useState<ExplorerQuery>({
    ...defaultPeriod,
    metrics: ["users", "visits", "views", "bounce"],
    dimensions: [],
    filters: [],
    filter_mode: "and",
    group: "auto",
    accuracy: "medium",
    attribution: "last_sign",
    include_undefined: true,
    goal_id: "",
    sort: "users",
    descending: true,
    page: 1,
    compare: false,
  });
  const [data, setData] = useState<ExplorerReport>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [metric, setMetric] = useState("users");
  const [kind, setKind] = useState<"area" | "line" | "bar">("area");
  const [goals, setGoals] =
    useState<{ id: string; name: string; type: string }[]>();
  const [goalsError, setGoalsError] = useState("");
  const [goalRefresh, setGoalRefresh] = useState(0);
  const [goalSearch, setGoalSearch] = useState("");
  const [pointLimit, setPointLimit] = useState(50);
  const [tableSearch, setTableSearch] = useState("");
  const notify = useRef(onConnectionChange);
  notify.current = onConnectionChange;
  const sourceRef = useRef(source);
  sourceRef.current = source;
  const base = `/sources/${source.id}/explorer`;
  const today = counterToday(source.metadata.timezone);
  const change = (next: ExplorerQuery) => {
    setQuery(next);
    setRefresh(0);
    setTableSearch("");
    setPointLimit(50);
  };

  useEffect(() => {
    const controller = new AbortController();
    api<ExplorerCatalog>(base + "/catalog", { signal: controller.signal })
      .then((result) => {
        if (!controller.signal.aborted) setCatalog(result);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setCatalogError(e.message);
      });
    return () => controller.abort();
  }, [base]);
  useEffect(() => {
    if (preset !== "goals") return;
    const controller = new AbortController();
    setGoalsError("");
    api<{ goals: { id: string; name: string; type: string }[] }>(
      base + `/goals?refresh=${goalRefresh > 0}`,
      { signal: controller.signal },
    )
      .then((result) => {
        if (!controller.signal.aborted) setGoals(result.goals);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setGoalsError(e.message);
      });
    return () => controller.abort();
  }, [base, preset, goalRefresh]);
  useEffect(() => {
    if (preset === "goals" && !query.goal_id) {
      setLoading(false);
      return;
    }
    const controller = new AbortController();
    setLoading(true);
    setError("");
    api<ExplorerReport>(base, {
      method: "POST",
      body: JSON.stringify({ ...query, refresh: refresh > 0 }),
      signal: controller.signal,
    })
      .then((result) => {
        if (controller.signal.aborted) return;
        setData(result);
        setMetric((current) =>
          result.metrics.some((m) => m.key === current)
            ? current
            : result.metrics[0].key,
        );
        notify.current({
          ...sourceRef.current,
          connected: true,
          connection_status: "ready",
          connection_error: undefined,
        });
      })
      .catch((e: ApiError) => {
        if (controller.signal.aborted) return;
        setData(undefined);
        setError(e.message);
        if ([0, 401, 403, 429, 502, 503, 504].includes(e.status)) {
          const needsKey = [401, 403].includes(e.status);
          notify.current(
            {
              ...sourceRef.current,
              connected: !needsKey,
              connection_status: needsKey ? "reconnect" : "error",
              connection_error: e.message,
            },
            needsKey,
          );
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [base, query, refresh, preset]);

  const pickPreset = (id: string) => {
    setPreset(id);
    setData(undefined);
    const isGoal = id === "goals";
    const regularMetrics = query.metrics.filter(
      (k) => !catalog?.metrics.find((m) => m.key === k)?.goal,
    );
    const metrics = isGoal
      ? query.metrics
      : regularMetrics.length
        ? regularMetrics
        : ["users", "visits", "views", "bounce"];
    change({
      ...query,
      dimensions: catalog?.presets.find((p) => p.id === id)?.dimensions || [],
      page: 1,
      metrics,
      ...(isGoal ? {} : { goal_id: "" }),
      sort: metrics[0],
    });
  };
  const selectGoal = (id: string) =>
    change({
      ...query,
      goal_id: id,
      metrics: ["goal_reaches", "conversion", "goal_users", "goal_visits"],
      dimensions: [],
      sort: "goal_reaches",
      page: 1,
    });
  const selected =
    data?.metrics.find((m) => m.key === metric) || data?.metrics[0];
  const colorFor = (key: string) =>
    chartColors[
      Math.max(0, catalog?.metrics.findIndex((m) => m.key === key) || 0) %
        chartColors.length
    ];
  const availableGroups = groups.filter(
    (g) => !g.points || daysInQuery(query) * g.points <= 1600,
  );
  const goalPending = preset === "goals" && !query.goal_id;
  const matchingGoals = goals?.filter((g) =>
    `${g.name} ${g.id}`.toLowerCase().includes(goalSearch.toLowerCase()),
  );
  const displayedGoals = goals?.filter(
    (g) => g.id === query.goal_id || matchingGoals?.includes(g),
  );
  const tableSearchable = !!catalog?.dimensions
    .find((d) => d.key === data?.columns[0]?.key)
    ?.operators.includes("contains");
  const addRowFilter = (index: number) => {
    if (!data) return;
    const dims = data.columns.filter((c) => c.kind === "dimension");
    const extra = dims.map((d) => ({
      field: d.key,
      operator: "eq" as const,
      value:
        data.dimension_values[index]?.[d.key] ||
        String(data.rows[index][d.key] ?? ""),
    }));
    // Drilling into a row is an intersection. Keep the user's OR segment intact
    // rather than silently changing its meaning; ask for an AND segment first.
    if (query.filter_mode === "or" && query.filters.length) return;
    change({
      ...query,
      page: 1,
      filters: [
        ...query.filters.filter((f) => !extra.some((e) => e.field === f.field)),
        ...extra,
      ],
    });
  };
  return (
    <Modal
      title={source.name}
      fullscreen
      wide
      onClose={onClose}
      actions={
        <button
          className="icon-button"
          aria-label="Настройки источника"
          onClick={onManage}
        >
          <Settings2 size={17} />
        </button>
      }
    >
      <div className="source-overview metrika-explorer">
        <aside className="report-sidebar">
          <div className="report-source">
            <ProviderIcon id={provider.id} large />
            <div>
              <strong>{provider.name}</strong>
              <span title={source.metadata.site}>
                {source.metadata.site || source.metadata.counter_id}
              </span>
            </div>
          </div>
          <nav className="report-tabs" aria-label="Разделы источника">
            {catalog?.presets.map((item) => {
              const Icon = icons[item.id] || Activity;
              return (
                <button
                  key={item.id}
                  aria-current={preset === item.id ? "page" : undefined}
                  className={preset === item.id ? "active" : ""}
                  onClick={() => pickPreset(item.id)}
                >
                  <Icon size={18} />
                  <span>{item.label}</span>
                </button>
              );
            })}
          </nav>
        </aside>
        <div className="report-main">
          <ReportPeriod
            dates={query}
            today={today}
            loading={loading}
            onRefresh={() => setRefresh((v) => v + 1)}
            onChange={(dates) => {
              const points =
                groups.find((g) => g.value === query.group)?.points || 0;
              change({
                ...query,
                ...dates,
                page: 1,
                group:
                  points * daysInQuery(dates) > 1600 ? "auto" : query.group,
              });
            }}
          >
            <div className="explorer-granularity">
              <Select
                id="explorer-group"
                label="Интервал графика"
                value={query.group}
                options={availableGroups}
                onChange={(group) => change({ ...query, group, page: 1 })}
              />
            </div>
          </ReportPeriod>
          {catalog ? (
            <ExplorerControls
              query={query}
              catalog={catalog}
              onChange={change}
            />
          ) : catalogError ? (
            <div role="alert" className="error-notice">
              {catalogError}
              <button className="text-button" onClick={onClose}>
                Закрыть
              </button>
            </div>
          ) : (
            <Spinner label="Открываю настройки отчётов…" />
          )}
          {preset === "goals" && (
            <div className="explorer-goals">
              <div>
                <Target size={19} />
                <strong>Цель и конверсия</strong>
              </div>
              {goalsError ? (
                <p role="alert">
                  {goalsError}{" "}
                  <button
                    className="text-button"
                    onClick={() => setGoalRefresh((v) => v + 1)}
                  >
                    Повторить
                  </button>
                </p>
              ) : !goals ? (
                <Spinner label="Загружаю цели счётчика…" />
              ) : goals.length ? (
                <div className="explorer-goal-picker">
                  <input
                    className="explorer-search"
                    aria-label="Найти цель"
                    placeholder={`Найти среди ${goals.length} целей…`}
                    value={goalSearch}
                    onChange={(event) => setGoalSearch(event.target.value)}
                  />
                  <Select
                    id="explorer-goal"
                    label="Цель счётчика"
                    value={query.goal_id}
                    options={[
                      { value: "", label: "Выберите цель" },
                      ...(displayedGoals || []).map((g) => ({
                        value: g.id,
                        label: g.name,
                      })),
                    ]}
                    onChange={selectGoal}
                  />
                  {!matchingGoals?.length && (
                    <small>Цели не найдены. Измените запрос.</small>
                  )}
                </div>
              ) : (
                <p>В этом счётчике пока нет настроенных целей.</p>
              )}
            </div>
          )}
          {error && (
            <div className="explorer-error" role="alert">
              <strong>Не удалось получить отчёт</strong>
              <p>{error}</p>
              <button
                className="secondary-button"
                onClick={() => setRefresh((v) => v + 1)}
              >
                Повторить
              </button>
            </div>
          )}
          {!goalPending && (
            <section
              className={
                "explorer-results " + (loading && data ? "updating" : "")
              }
              aria-label="Данные отчёта"
              aria-busy={loading}
            >
              {loading && (
                <div className="explorer-loading" role="status">
                  <Spinner
                    label={data ? "Обновляю отчёт…" : "Загружаю данные…"}
                  />
                </div>
              )}
              {data && (
                <>
                  <div className="metrics explorer-metrics">
                    {data.metrics.map((m) => {
                      const previous = data.comparison?.metrics.find(
                        (p) => p.key === m.key,
                      )?.value;
                      const delta =
                        previous != null && m.value != null
                          ? m.value - previous
                          : null;
                      const deltaText =
                        delta === null
                          ? ""
                          : m.format === "percent"
                            ? `${delta > 0 ? "+" : ""}${number(delta)} п.п.`
                            : previous
                              ? `${delta > 0 ? "+" : ""}${number((delta / previous) * 100)}%`
                              : delta === 0
                                ? "0%"
                                : "ранее 0";
                      return (
                        <button
                          className={
                            "metric-card " +
                            (metric === m.key ? "selected" : "")
                          }
                          key={m.key}
                          aria-pressed={metric === m.key}
                          onClick={() => setMetric(m.key)}
                          style={
                            {
                              "--metric-color": colorFor(m.key),
                            } as React.CSSProperties
                          }
                        >
                          <span>{m.label}</span>
                          <strong>{metricValue(m.value, m.format)}</strong>
                          {data.comparison && (
                            <small
                              className="metric-comparison"
                              title="Изменение к предыдущему периоду"
                            >
                              {deltaText || "Нет сравнения"}
                            </small>
                          )}
                          {metric === m.key && (
                            <span className="metric-indicator" />
                          )}
                        </button>
                      );
                    })}
                  </div>
                  <div className="explorer-chart-heading">
                    <div>
                      <h3>{selected?.label}</h3>
                      <span>
                        {dayLabel(data.date1)}
                        {data.date1 !== data.date2
                          ? ` — ${dayLabel(data.date2)}`
                          : ""}{" "}
                        · {groups.find((g) => g.value === data.group)?.label} ·{" "}
                        {data.timezone}
                      </span>
                    </div>
                    <div className="chart-kind" aria-label="Вид графика">
                      {(
                        [
                          ["area", "С заливкой", ChartNoAxesCombined],
                          ["line", "Линия", Activity],
                          ["bar", "Столбцы", ChartColumn],
                        ] as const
                      ).map(([value, label, Icon]) => (
                        <button
                          key={value}
                          aria-label={label}
                          aria-pressed={kind === value}
                          title={label}
                          onClick={() => setKind(value)}
                        >
                          <Icon size={16} />
                        </button>
                      ))}
                    </div>
                  </div>
                  {data.series.length ? (
                    <AnalyticsChart
                      key={data.date1 + data.date2 + data.group}
                      series={data.series}
                      metric={selected?.key || metric}
                      label={selected?.label || metric}
                      format={selected?.format}
                      group={data.group}
                      kind={kind}
                      color={colorFor(metric)}
                      comparison={data.comparison?.series}
                    />
                  ) : (
                    <div className="empty-report">
                      За этот период нет точек для графика.
                    </div>
                  )}
                  {data.comparison && (
                    <div className="comparison-legend">
                      <span>
                        <i style={{ background: colorFor(metric) }} />
                        Выбранный период
                      </span>
                      <span>
                        <i style={{ background: "#a37a4b" }} />
                        {dayLabel(data.comparison.date1)} —{" "}
                        {dayLabel(data.comparison.date2)}
                      </span>
                    </div>
                  )}
                  {data.columns.some((c) => c.kind === "dimension") ? (
                    <>
                      <div className="explorer-table-toolbar">
                        <span>{number(data.total_rows)} строк</span>
                        {tableSearchable && (
                          <form
                            onSubmit={(event) => {
                              event.preventDefault();
                              if (
                                tableSearch.trim() &&
                                query.filters.length < 8 &&
                                !(
                                  query.filters.length &&
                                  query.filter_mode === "or"
                                )
                              )
                                change({
                                  ...query,
                                  page: 1,
                                  filters: [
                                    ...query.filters,
                                    {
                                      field: data.columns[0].key,
                                      operator: "contains",
                                      value: tableSearch.trim(),
                                    },
                                  ],
                                });
                            }}
                          >
                            <input
                              aria-label="Найти в отчёте"
                              placeholder={`Найти: ${data.columns[0].label.toLowerCase()}`}
                              value={tableSearch}
                              maxLength={150}
                              onChange={(event) =>
                                setTableSearch(event.target.value)
                              }
                            />
                            <button
                              type="submit"
                              disabled={
                                !tableSearch.trim() ||
                                query.filters.length >= 8 ||
                                !!(
                                  query.filters.length &&
                                  query.filter_mode === "or"
                                )
                              }
                            >
                              Найти
                            </button>
                          </form>
                        )}
                        <button
                          className="text-button"
                          onClick={() => exportRows(data, false)}
                          title="Экспорт 50 строк текущей страницы"
                        >
                          <Download size={14} />
                          CSV страницы
                        </button>
                      </div>
                      <div className="table-scroll report-table explorer-table">
                        <table>
                          <thead>
                            <tr>
                              {data.columns.map((column) => (
                                <th key={column.key}>
                                  <button
                                    onClick={() =>
                                      change({
                                        ...query,
                                        sort: column.key,
                                        descending:
                                          query.sort === column.key
                                            ? !query.descending
                                            : true,
                                        page: 1,
                                      })
                                    }
                                  >
                                    {column.label}
                                    {query.sort === column.key &&
                                      (query.descending ? (
                                        <ArrowDown size={12} />
                                      ) : (
                                        <ArrowUp size={12} />
                                      ))}
                                  </button>
                                </th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {data.rows.map((row, index) => (
                              <tr key={index}>
                                {data.columns.map((column, i) => (
                                  <td key={column.key}>
                                    {i === 0 ? (
                                      <button
                                        className="drilldown-value"
                                        title={
                                          query.filter_mode === "or" &&
                                          query.filters.length
                                            ? "Для перехода в сегмент выберите объединение фильтров «И»"
                                            : "Показать только этот сегмент"
                                        }
                                        disabled={
                                          loading ||
                                          query.filters.length +
                                            query.dimensions.length >
                                            8 ||
                                          !!(
                                            query.filter_mode === "or" &&
                                            query.filters.length
                                          ) ||
                                          !data.dimension_values[index]?.[
                                            column.key
                                          ]
                                        }
                                        onClick={() => addRowFilter(index)}
                                      >
                                        {String(
                                          row[column.key] ?? "Не определено",
                                        )}
                                      </button>
                                    ) : column.kind === "metric" ? (
                                      metricValue(
                                        row[column.key],
                                        column.format,
                                      )
                                    ) : (
                                      String(row[column.key] ?? "—")
                                    )}
                                  </td>
                                ))}
                              </tr>
                            ))}
                          </tbody>
                        </table>
                        {!data.rows.length && (
                          <div className="empty-report">
                            Нет строк для выбранного сегмента.
                          </div>
                        )}
                      </div>
                      <div className="explorer-pagination">
                        <span>
                          {data.rows.length
                            ? `${(data.page - 1) * 50 + 1}–${(data.page - 1) * 50 + data.rows.length} из ${number(data.total_rows)}`
                            : "0 строк"}
                        </span>
                        <button
                          className="secondary-button"
                          disabled={loading || data.page === 1}
                          onClick={() =>
                            change({ ...query, page: data.page - 1 })
                          }
                        >
                          Назад
                        </button>
                        <button
                          className="secondary-button"
                          disabled={
                            loading || !data.has_more || data.page >= 200
                          }
                          onClick={() =>
                            change({ ...query, page: data.page + 1 })
                          }
                        >
                          Далее
                        </button>
                      </div>
                    </>
                  ) : null}
                  <details className="timeline-table">
                    <summary>
                      <Table2 size={15} />
                      Точки графика <span>{data.series.length}</span>
                    </summary>
                    <div className="timeline-actions">
                      <span>Каждая строка — отдельный временной интервал</span>
                      <button
                        className="text-button"
                        onClick={() => exportRows(data, true)}
                      >
                        <Download size={14} />
                        CSV графика
                      </button>
                    </div>
                    <div className="table-scroll report-table">
                      <table>
                        <thead>
                          <tr>
                            <th>Дата и время</th>
                            {data.metrics.map((m) => (
                              <th key={m.key}>{m.label}</th>
                            ))}
                          </tr>
                        </thead>
                        <tbody>
                          {data.series.slice(0, pointLimit).map((row, i) => (
                            <tr key={i}>
                              <td>
                                {timeLabel(String(row.date), data.group, true)}
                              </td>
                              {data.metrics.map((m) => (
                                <td key={m.key}>
                                  {metricValue(row[m.key], m.format)}
                                </td>
                              ))}
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    {data.series.length > pointLimit && (
                      <button
                        className="text-button"
                        onClick={() => setPointLimit((n) => n + 100)}
                      >
                        Показать ещё 100 точек
                      </button>
                    )}
                  </details>
                  <footer className="explorer-footnote">
                    <div>
                      {data.sampled && (
                        <span className="sampling-badge">
                          Выборка {number(data.sample_share * 100)}%
                        </span>
                      )}
                      {data.contains_sensitive_data && (
                        <span>
                          Некоторые данные Метрика скрывает для малых групп.
                        </span>
                      )}
                      {data.data_lag > 0 && (
                        <span>
                          Задержка данных: {Math.ceil(data.data_lag / 60)} мин.
                        </span>
                      )}
                      <span>
                        Итоги и средние рассчитаны Метрикой за весь период.
                      </span>
                    </div>
                    <div>
                      <span>
                        {data.cached
                          ? "Из кеша"
                          : Object.values(data.cache).some(Boolean) ||
                              data.comparison?.cached
                            ? "Часть данных из кеша"
                            : "Данные обновлены"}
                      </span>
                      <time>
                        {new Date(data.fetched_at).toLocaleTimeString("ru-RU", {
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                      </time>
                    </div>
                  </footer>
                </>
              )}
            </section>
          )}
        </div>
      </div>
    </Modal>
  );
}
