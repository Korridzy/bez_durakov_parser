import { useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  Check,
  ChevronDown,
  Database,
  Eye,
  EyeOff,
  Maximize2,
  Minimize2,
  Plus,
  RefreshCw,
  Settings2,
  Trash2,
} from "lucide-react";
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import type { Project, Provider, Report, Source, Workspace } from "./types";
import { api, dayLabel, number, post } from "./api";
import { Alert, ExternalLink, Modal, ProviderIcon, Spinner } from "./ui";

const reportNames: Record<string, string> = {
  overview: "Обзор",
  channels: "Каналы",
  devices: "Устройства",
  pages: "Страницы",
  geography: "География",
  goals: "Цели",
  events: "События",
};
const colors = ["var(--accent-strong)", "#82aaa3", "#b597cb", "#d7a76c"];

export function SourceForm({
  providers,
  projectId,
  existing,
  onSaved,
  onBack,
}: {
  providers: Provider[];
  projectId: string;
  existing?: Source;
  onSaved: (source: Source) => void;
  onBack: () => void;
}) {
  const [providerId, setProviderId] = useState(existing?.provider || "metrika");
  const [values, setValues] = useState<Record<string, string>>({
    region: "US",
  });
  const [name, setName] = useState(existing?.name || "");
  const [remember, setRemember] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [visible, setVisible] = useState(false);
  const provider = providers.find((p) => p.id === providerId)!;
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      const body = { provider: providerId, name, config: values, remember };
      const source = await api<Source>(
        existing
          ? "/sources/" + existing.id
          : "/projects/" + projectId + "/sources",
        { method: existing ? "PUT" : "POST", body: JSON.stringify(body) },
      );
      setValues({ region: "US" });
      onSaved(source);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <form className="connection-form" onSubmit={submit}>
      <div className="field">
        <label htmlFor="source-provider">Система аналитики</label>
        <div className="select-with-icon">
          <ProviderIcon id={providerId} />
          <select
            id="source-provider"
            disabled={!!existing || busy}
            value={providerId}
            onChange={(e) => {
              setProviderId(e.target.value);
              setValues({ region: "US" });
              setError("");
              setVisible(false);
            }}
          >
            {providers.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
          <ChevronDown size={16} />
        </div>
      </div>
      <div className="field">
        <label htmlFor="source-name">
          Название <span>необязательно</span>
        </label>
        <input
          id="source-name"
          value={name}
          maxLength={100}
          onChange={(e) => setName(e.target.value)}
          placeholder={provider.name}
          disabled={busy}
        />
      </div>
      {provider.fields.map((field) => (
        <div className="field" key={providerId + field.key}>
          <label htmlFor={"source-" + field.key}>{field.label}</label>
          {field.kind === "select" ? (
            <select
              id={"source-" + field.key}
              value={values[field.key] || "US"}
              onChange={(e) =>
                setValues({ ...values, [field.key]: e.target.value })
              }
              disabled={busy}
            >
              {field.options?.map((o) => (
                <option key={o}>{o}</option>
              ))}
            </select>
          ) : field.kind === "json" ? (
            <textarea
              id={"source-" + field.key}
              className="credential-json"
              aria-label={field.label}
              required
              rows={4}
              value={values[field.key] || ""}
              onChange={(e) =>
                setValues({ ...values, [field.key]: e.target.value })
              }
              placeholder="Вставьте содержимое JSON-файла"
              spellCheck={false}
              autoComplete="off"
              disabled={busy}
            />
          ) : (
            <div className="secret-input">
              <input
                id={"source-" + field.key}
                required
                type={field.secret && !visible ? "password" : "text"}
                autoComplete="off"
                value={values[field.key] || ""}
                onChange={(e) =>
                  setValues({ ...values, [field.key]: e.target.value })
                }
                placeholder={field.placeholder}
                spellCheck={false}
                disabled={busy}
              />
              {field.secret && (
                <button
                  className="icon-button"
                  type="button"
                  aria-label={visible ? "Скрыть ключ" : "Показать ключ"}
                  onClick={() => setVisible(!visible)}
                >
                  {visible ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              )}
            </div>
          )}
          {field.help && <small className="field-help">{field.help}</small>}
        </div>
      ))}
      <label className="check-field">
        <input
          type="checkbox"
          checked={remember}
          onChange={(e) => setRemember(e.target.checked)}
        />
        <span>
          Запомнить подключение на этом компьютере
          <small>
            {remember
              ? "Ключ хранится на сервере в зашифрованном виде."
              : "Без сохранения ключ действует до перезапуска сервера."}
          </small>
        </span>
      </label>
      {error && <Alert>{error}</Alert>}
      <div className="form-bottom">
        <ExternalLink href={provider.docs}>Как получить доступ</ExternalLink>
        <div className="inline">
          <button
            type="button"
            className="secondary-button"
            onClick={onBack}
            disabled={busy}
          >
            Назад
          </button>
          <button className="primary-button" disabled={busy}>
            {busy ? (
              <Spinner label="Проверяю доступ…" />
            ) : (
              <>
                <Check size={16} />
                Подключить
              </>
            )}
          </button>
        </div>
      </div>
    </form>
  );
}

export function SourcesDialog({
  workspace,
  project,
  onClose,
  onRefresh,
  onPreview,
  initialAdd = false,
}: {
  workspace: Workspace;
  project: Project;
  onClose: () => void;
  onRefresh: () => Promise<Workspace>;
  onPreview: (s: Source) => void;
  initialAdd?: boolean;
}) {
  const sources = workspace.sources.filter((s) => s.project_id === project.id);
  const [form, setForm] = useState(initialAdd || !sources.length);
  const [editing, setEditing] = useState<Source>();
  const [error, setError] = useState("");
  const [removeId, setRemoveId] = useState("");
  return (
    <Modal
      title={
        form
          ? editing
            ? "Переподключить источник"
            : "Добавить источник"
          : "Источники проекта"
      }
      onClose={onClose}
    >
      {form ? (
        <SourceForm
          providers={workspace.providers}
          projectId={project.id}
          existing={editing}
          onSaved={async (source) => {
            await onRefresh();
            onClose();
            onPreview(source);
          }}
          onBack={() => {
            if (!sources.length) onClose();
            else {
              setForm(false);
              setEditing(undefined);
            }
          }}
        />
      ) : (
        <div className="source-manager">
          <div className="modal-context">
            {project.name}
            <span>Доступны во всех чатах проекта</span>
          </div>
          {sources.map((source) => (
            <div className="connection-row" key={source.id}>
              <ProviderIcon id={source.provider} large />
              <button
                className="connection-info"
                onClick={() => onPreview(source)}
              >
                <strong>{source.name}</strong>
                <span>
                  {
                    workspace.providers.find((p) => p.id === source.provider)
                      ?.name
                  }
                  {source.connected ? "" : " · Нужен ключ"}
                </span>
              </button>
              <button
                className="icon-button"
                aria-label={"Настроить " + source.name}
                onClick={() => {
                  setEditing(source);
                  setForm(true);
                }}
              >
                <Settings2 size={16} />
              </button>
              {removeId === source.id ? (
                <>
                  <button
                    className="danger-button"
                    onClick={async () => {
                      try {
                        await api("/sources/" + source.id, {
                          method: "DELETE",
                        });
                        setRemoveId("");
                        await onRefresh();
                      } catch (e) {
                        setError((e as Error).message);
                      }
                    }}
                  >
                    Отключить
                  </button>
                  <button
                    className="text-button"
                    onClick={() => setRemoveId("")}
                  >
                    Отмена
                  </button>
                </>
              ) : (
                <button
                  className="icon-button"
                  aria-label={"Отключить " + source.name}
                  onClick={() => setRemoveId(source.id)}
                >
                  <Trash2 size={16} />
                </button>
              )}
            </div>
          ))}
          {error && <Alert>{error}</Alert>}
          <button className="add-connection" onClick={() => setForm(true)}>
            <Plus size={18} />
            Добавить источник
          </button>
        </div>
      )}
    </Modal>
  );
}

function ChartTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: readonly {
    value?: number | string;
    name?: string;
    color?: string;
  }[];
  label?: string | number;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="chart-tooltip">
      <strong>{dayLabel(String(label))}</strong>
      {payload.map((p, i) => (
        <div key={i}>
          <span style={{ background: p.color }} />
          <span>{p.name}</span>
          <b>{number(p.value)}</b>
        </div>
      ))}
    </div>
  );
}

export function SourcePreview({
  source,
  provider,
  defaultPeriod,
  onClose,
  onManage,
}: {
  source: Source;
  provider: Provider;
  defaultPeriod: { date1: string; date2: string };
  onClose: () => void;
  onManage: () => void;
}) {
  const [report, setReport] = useState("overview");
  const [dates, setDates] = useState(defaultPeriod);
  const [range, setRange] = useState("30");
  const [data, setData] = useState<Report>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [fullscreen, setFullscreen] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [metric, setMetric] = useState("users");
  const [loadingMore, setLoadingMore] = useState(false);
  const [pageError, setPageError] = useState("");
  const reportVersion = useRef(0);
  useEffect(() => {
    reportVersion.current++;
    const controller = new AbortController();
    setLoadingMore(false);
    setLoading(true);
    setError("");
    setPageError("");
    setData(undefined);
    api<Report>(
      `/sources/${source.id}/reports/${report}?date1=${dates.date1}&date2=${dates.date2}&refresh=${refresh > 0}`,
      { signal: controller.signal },
    )
      .then((result) => {
        setData(result);
        setMetric(result.metrics?.[0]?.key || "users");
      })
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => {
      controller.abort();
      reportVersion.current++;
    };
  }, [source.id, report, dates, refresh]);
  const pickRange = (days: string) => {
    setRange(days);
    if (days === "custom") return;
    const end = new Date(defaultPeriod.date2 + "T12:00:00");
    const start = new Date(end);
    start.setDate(start.getDate() - Number(days) + 1);
    const local = (d: Date) =>
      `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    setDates({ date1: local(start), date2: local(end) });
  };
  const selected = data?.metrics?.find((m) => m.key === metric);
  const loadMore = async () => {
    const version = reportVersion.current;
    setLoadingMore(true);
    setPageError("");
    try {
      const next = await api<Report>(
        `/sources/${source.id}/reports/${report}?date1=${dates.date1}&date2=${dates.date2}&page=${(data?.page || 1) + 1}`,
      );
      if (version !== reportVersion.current) return;
      setData((previous) =>
        previous
          ? { ...next, rows: [...(previous.rows || []), ...(next.rows || [])] }
          : next,
      );
    } catch (error) {
      if (version === reportVersion.current)
        setPageError((error as Error).message);
    } finally {
      if (version === reportVersion.current) setLoadingMore(false);
    }
  };
  const nonChart = ["bounce"];
  const topRows = data?.rows?.slice(0, 7) || [];
  const firstColumn = data?.columns?.[0];
  const numericColumn = data?.columns?.find((k) =>
    data.rows?.some((r) => typeof r[k] === "number"),
  );
  return (
    <Modal
      title={source.name}
      onClose={onClose}
      wide
      fullscreen={fullscreen}
      actions={
        <>
          <button
            className="icon-button"
            aria-label="Настройки источника"
            onClick={onManage}
          >
            <Settings2 size={17} />
          </button>
          <button
            className="icon-button"
            aria-label={fullscreen ? "Свернуть окно" : "Развернуть окно"}
            onClick={() => setFullscreen(!fullscreen)}
          >
            {fullscreen ? <Minimize2 size={17} /> : <Maximize2 size={17} />}
          </button>
        </>
      }
    >
      <div className="source-overview">
        <div className="source-meta">
          <div className="inline">
            <ProviderIcon id={provider.id} />
            <span>{provider.name}</span>
            <span className="meta-separator">/</span>
            <span>
              {source.metadata.site ||
                source.metadata.counter_id ||
                source.metadata.property_id ||
                source.metadata.timezone}
            </span>
          </div>
          <ExternalLink href={provider.docs}>API</ExternalLink>
        </div>
        <div className="report-controls">
          <nav className="report-tabs" aria-label="Разделы источника">
            {provider.reports.map((key) => (
              <button
                key={key}
                className={report === key ? "active" : ""}
                onClick={() => {
                  setReport(key);
                  setRefresh(0);
                }}
              >
                {reportNames[key]}
              </button>
            ))}
          </nav>
          <div className="date-controls">
            <select
              aria-label="Период отчёта"
              value={range}
              onChange={(e) => pickRange(e.target.value)}
            >
              <option value="7">7 дней</option>
              <option value="30">30 дней</option>
              <option value="90">90 дней</option>
              <option value="custom">Свой период</option>
            </select>
            <button
              className="icon-button"
              aria-label="Обновить данные"
              disabled={loading}
              onClick={() => setRefresh((v) => v + 1)}
            >
              <RefreshCw size={16} className={loading ? "spin" : ""} />
            </button>
          </div>
        </div>
        {range === "custom" && (
          <div className="custom-dates">
            <label>
              С
              <input
                type="date"
                aria-label="Начало периода"
                value={dates.date1}
                max={dates.date2}
                onChange={(e) =>
                  e.target.value &&
                  setDates({ ...dates, date1: e.target.value })
                }
              />
            </label>
            <label>
              По
              <input
                type="date"
                aria-label="Конец периода"
                value={dates.date2}
                min={dates.date1}
                onChange={(e) =>
                  e.target.value &&
                  setDates({ ...dates, date2: e.target.value })
                }
              />
            </label>
          </div>
        )}
        {loading ? (
          <div className="report-loading">
            <div className="metric-skeletons">
              {[1, 2, 3, 4].map((n) => (
                <div className="skeleton" key={n} />
              ))}
            </div>
            <div className="skeleton chart-skeleton" />
            <Spinner label="Загружаю данные…" />
          </div>
        ) : error ? (
          <div className="report-error">
            <Database size={30} />
            <h3>Не удалось загрузить данные</h3>
            <p>{error}</p>
            <div className="inline">
              <button className="secondary-button" onClick={onManage}>
                Проверить подключение
              </button>
              <button
                className="primary-button"
                onClick={() => setRefresh((v) => v + 1)}
              >
                Повторить
              </button>
            </div>
          </div>
        ) : (
          data && (
            <>
              {report === "overview" ? (
                <>
                  <div className="metrics">
                    {data.metrics?.map((m, i) => (
                      <button
                        key={m.key}
                        className={
                          "metric-card " + (metric === m.key ? "selected" : "")
                        }
                        disabled={nonChart.includes(m.key)}
                        onClick={() => setMetric(m.key)}
                        style={
                          {
                            "--metric-color": colors[i % colors.length],
                          } as React.CSSProperties
                        }
                      >
                        <span>{m.label}</span>
                        <strong>
                          {number(m.value)}
                          {m.format === "percent" && <small>%</small>}
                        </strong>
                        {metric === m.key && (
                          <span className="metric-indicator" />
                        )}
                      </button>
                    ))}
                  </div>
                  <div className="chart-heading">
                    <h3>{selected?.label || "Динамика"}</h3>
                    <span>
                      {dayLabel(dates.date1)} — {dayLabel(dates.date2)}
                    </span>
                  </div>
                  <div className="trend-chart">
                    <ResponsiveContainer width="100%" height="100%">
                      <AreaChart
                        data={data.series || []}
                        margin={{ top: 12, right: 8, bottom: 0, left: -16 }}
                      >
                        <defs>
                          <linearGradient
                            id="trendFill"
                            x1="0"
                            y1="0"
                            x2="0"
                            y2="1"
                          >
                            <stop
                              offset="0%"
                              stopColor={colors[0]}
                              stopOpacity={0.22}
                            />
                            <stop
                              offset="100%"
                              stopColor={colors[0]}
                              stopOpacity={0.01}
                            />
                          </linearGradient>
                        </defs>
                        <CartesianGrid
                          vertical={false}
                          stroke="#eef0f2"
                          strokeDasharray="3 5"
                        />
                        <XAxis
                          dataKey="date"
                          axisLine={false}
                          tickLine={false}
                          tickFormatter={dayLabel}
                          minTickGap={50}
                          tick={{ fill: "#8a8d92", fontSize: 12 }}
                          dy={12}
                        />
                        <YAxis
                          axisLine={false}
                          tickLine={false}
                          tickFormatter={(v) => number(v)}
                          tick={{ fill: "#8a8d92", fontSize: 12 }}
                        />
                        <Tooltip content={<ChartTooltip />} />
                        <Area
                          type="monotone"
                          dataKey={metric}
                          name={selected?.label || metric}
                          stroke={colors[0]}
                          strokeWidth={2.5}
                          fill="url(#trendFill)"
                          activeDot={{ r: 5, stroke: "white", strokeWidth: 3 }}
                          dot={false}
                        />
                      </AreaChart>
                    </ResponsiveContainer>
                  </div>
                  {!data.series?.length && (
                    <p className="empty-report">За этот период данных нет.</p>
                  )}
                  <div className="explore-links">
                    {provider.reports
                      .filter((r) => r !== "overview")
                      .map((r, i) => (
                        <button
                          key={r}
                          onClick={() => {
                            setReport(r);
                            setRefresh(0);
                          }}
                        >
                          <span
                            className="explore-mark"
                            style={{ background: colors[i % colors.length] }}
                          />
                          <span>{reportNames[r]}</span>
                          <ArrowRight size={15} />
                        </button>
                      ))}
                  </div>
                </>
              ) : (
                <>
                  <div className="chart-heading">
                    <h3>{reportNames[report]}</h3>
                    <span>
                      {data.total_rows !== undefined
                        ? `${number(data.total_rows)} записей`
                        : ""}
                    </span>
                  </div>
                  {topRows.length > 0 && firstColumn && numericColumn && (
                    <div className="horizontal-bars">
                      {topRows.map((r, i) => {
                        const maximum = Math.max(
                          ...topRows.map(
                            (row) => Number(row[numericColumn]) || 0,
                          ),
                          1,
                        );
                        return (
                          <div className="bar-row" key={i}>
                            <span
                              className="bar-name"
                              title={String(r[firstColumn])}
                            >
                              {String(r[firstColumn])}
                            </span>
                            <div className="bar-track">
                              <div
                                style={{
                                  width:
                                    Math.max(
                                      0,
                                      ((Number(r[numericColumn]) || 0) /
                                        maximum) *
                                        100,
                                    ) + "%",
                                  background: colors[i % colors.length],
                                }}
                              />
                            </div>
                            <strong>{number(r[numericColumn])}</strong>
                          </div>
                        );
                      })}
                    </div>
                  )}
                  <div className="table-scroll report-table">
                    <table>
                      <thead>
                        <tr>
                          {data.columns?.map((k) => (
                            <th key={k}>{k}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {data.rows?.map((row, i) => (
                          <tr key={i}>
                            {data.columns?.map((k) => (
                              <td
                                key={k}
                                title={
                                  typeof row[k] === "string"
                                    ? String(row[k])
                                    : undefined
                                }
                              >
                                {typeof row[k] === "object"
                                  ? JSON.stringify(row[k])
                                  : number(row[k])}
                              </td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                    {!data.rows?.length && (
                      <div className="empty-report">
                        За этот период данных нет.
                      </div>
                    )}
                  </div>
                </>
              )}
              {data.has_more && (
                <button
                  className="add-connection"
                  onClick={() => void loadMore()}
                  disabled={loadingMore}
                >
                  {loadingMore ? (
                    <Spinner label="Загружаю…" />
                  ) : (
                    `Показать ещё · ${number(data.rows?.length || 0)} из ${number(data.total_rows)}`
                  )}
                </button>
              )}
              {pageError && <Alert>{pageError}</Alert>}
              <div className="report-footnote">
                <span>
                  {data.sampled
                    ? `Выборка ${number((data.sample_share || 0) * 100)}%`
                    : "Данные API"}
                  {data.limited ? " · Показаны первые 50 записей" : ""}
                  {data.note ? " · " + data.note : ""}
                </span>
                <span>
                  {data.cached ? "Из кеша · " : ""}
                  {data.fetched_at
                    ? "Обновлено " +
                      new Date(data.fetched_at).toLocaleTimeString("ru-RU", {
                        hour: "2-digit",
                        minute: "2-digit",
                      })
                    : ""}
                </span>
              </div>
            </>
          )
        )}
      </div>
    </Modal>
  );
}
