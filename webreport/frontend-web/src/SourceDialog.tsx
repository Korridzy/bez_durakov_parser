import { useEffect, useRef, useState } from "react";
import {
  Activity,
  ChartNoAxesCombined,
  Check,
  Database,
  CircleAlert,
  FileText,
  Eye,
  EyeOff,
  Globe2,
  LayoutDashboard,
  Plus,
  Radio,
  Settings2,
  Smartphone,
  Target,
  Trash2,
} from "lucide-react";
import type { Project, Provider, Report, Source, Workspace } from "./types";
import { api, ApiError, dayLabel, number, post } from "./api";
import { Alert, ExternalLink, Modal, ProviderIcon, Spinner } from "./ui";
import { Select } from "./Select";
import { ReportPeriod } from "./ReportPeriod";
import { MetrikaExplorer } from "./MetrikaExplorer";
import { AnalyticsChart, chartColors } from "./AnalyticsChart";
import "./source-report.css";

const reportNames: Record<string, string> = {
  overview: "Обзор",
  channels: "Каналы",
  devices: "Устройства",
  pages: "Страницы",
  geography: "География",
  goals: "Цели",
  events: "События",
};
const colors = chartColors;
const reportIcons: Record<string, typeof LayoutDashboard> = {
  overview: LayoutDashboard,
  channels: Radio,
  devices: Smartphone,
  pages: FileText,
  geography: Globe2,
  goals: Target,
  events: Activity,
};

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
    ...Object.fromEntries(
      (providers.find((p) => p.id === existing?.provider)?.fields || [])
        .filter((field) => !field.secret)
        .map((field) => [
          field.key,
          existing?.config?.[field.key] ||
            existing?.metadata[field.key] ||
            (field.kind === "select" ? "US" : ""),
        ]),
    ),
  });
  const [name, setName] = useState(existing?.name || "");
  const [remember, setRemember] = useState(existing?.remembered || false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [visible, setVisible] = useState(false);
  const provider = providers.find((p) => p.id === providerId)!;
  const reuseKey =
    !!existing &&
    (existing.has_credentials ?? existing.connected) &&
    existing.connection_status !== "reconnect";
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
      {existing && !reuseKey && (
        <p className="reconnect-prompt" role="status">
          Введите ключ ещё раз, чтобы восстановить доступ к данным.
        </p>
      )}
      <div className="field">
        <label htmlFor="source-provider">Система аналитики</label>
        <Select
          id="source-provider"
          label="Система аналитики"
          disabled={!!existing || busy}
          value={providerId}
          onChange={(value) => {
            setProviderId(value);
            setValues({ region: "US" });
            setError("");
            setVisible(false);
          }}
          options={providers.map((p) => ({
            value: p.id,
            label: p.name,
            icon: <ProviderIcon id={p.id} />,
          }))}
        />
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
          <label htmlFor={"source-" + field.key}>
            {field.label}
            {field.secret && reuseKey && (
              <span className="credential-present">
                <Check size={12} />
                Ключ уже подключён
              </span>
            )}
          </label>
          {field.kind === "select" ? (
            <Select
              id={"source-" + field.key}
              label={field.label}
              value={values[field.key] || "US"}
              onChange={(value) => setValues({ ...values, [field.key]: value })}
              disabled={busy}
              options={(field.options || []).map((o) => ({
                value: o,
                label: o,
              }))}
            />
          ) : field.kind === "json" ? (
            <textarea
              id={"source-" + field.key}
              className="credential-json"
              aria-label={field.label}
              required={!reuseKey}
              rows={4}
              value={values[field.key] || ""}
              onChange={(e) =>
                setValues({ ...values, [field.key]: e.target.value })
              }
              placeholder={
                reuseKey
                  ? "Вставьте новый JSON, чтобы заменить ключ"
                  : "Вставьте содержимое JSON-файла"
              }
              spellCheck={false}
              autoComplete="off"
              disabled={busy}
            />
          ) : (
            <div className="secret-input">
              <input
                id={"source-" + field.key}
                required={!field.secret || !reuseKey}
                type={field.secret && !visible ? "password" : "text"}
                autoComplete="off"
                value={values[field.key] || ""}
                onChange={(e) =>
                  setValues({ ...values, [field.key]: e.target.value })
                }
                placeholder={
                  field.secret && reuseKey
                    ? "Введите новый ключ, чтобы заменить текущий"
                    : field.placeholder
                }
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
          disabled={busy}
          onChange={(e) => setRemember(e.target.checked)}
        />
        <span>Сохранять ключ после перезапуска сервера</span>
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
                {reuseKey ? "Сохранить" : "Подключить"}
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
  initialSource,
  onProjectInfo,
  onDescribeProject,
  busy,
}: {
  workspace: Workspace;
  project: Project;
  onClose: () => void;
  onRefresh: () => Promise<Workspace>;
  onPreview: (s: Source) => void;
  initialAdd?: boolean;
  initialSource?: Source;
  onProjectInfo: () => void;
  onDescribeProject: () => void;
  busy: boolean;
}) {
  const sources = workspace.sources.filter((s) => s.project_id === project.id);
  const [form, setForm] = useState(
    !!initialSource || initialAdd,
  );
  const [editing, setEditing] = useState<Source | undefined>(initialSource);
  const [error, setError] = useState("");
  const [removeId, setRemoveId] = useState("");
  return (
    <Modal
      title={
        form
          ? editing
            ? editing.connected
              ? "Настройки источника"
              : "Переподключить источник"
            : "Добавить источник"
          : "Источники проекта"
      }
      onClose={onClose}
    >
      {form ? (
        <SourceForm
          key={editing?.id || "new"}
          providers={workspace.providers}
          projectId={project.id}
          existing={editing}
          onSaved={async (source) => {
            await onRefresh();
            onClose();
            onPreview(source);
          }}
          onBack={() => {
            setForm(false);
            setEditing(undefined);
          }}
        />
      ) : (
        <div className="source-manager">
          <div className="modal-context">
            {project.name}
            <span>Доступны во всех чатах проекта</span>
          </div>
          <div className={"connection-row project-info-manager " + (!project.info?.content ? "missing-info" : "")}>
            {project.info?.content ? <FileText size={24} /> : <CircleAlert size={24} />}
            <button className="connection-info" disabled={!project.info?.content && busy}
              onClick={project.info?.content ? onProjectInfo : onDescribeProject}>
              <strong>{project.info?.content ? "Информация о проекте" : "Нет информации о проекте"}</strong>
              <span>{project.info?.content ? "Сводка, которую учитывает агент" : "Опишите проект в чате"}</span>
            </button>
            <button className="icon-button" aria-label="Открыть сводку о проекте" onClick={onProjectInfo}><FileText size={16} /></button>
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
                  {!source.connected
                    ? " · Нужен ключ"
                    : source.connection_status === "error"
                      ? " · Нет связи"
                      : ""}
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

export function SourcePreview(props: React.ComponentProps<typeof StandardSourcePreview>) {
  return props.source.provider === "metrika" ? <MetrikaExplorer {...props} /> : <StandardSourcePreview {...props} />;
}

function StandardSourcePreview({
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
  const [report, setReport] = useState("overview");
  const [dates, setDates] = useState(defaultPeriod);
  const [data, setData] = useState<Report>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [metric, setMetric] = useState("users");
  const [loadingMore, setLoadingMore] = useState(false);
  const [pageError, setPageError] = useState("");
  const reportVersion = useRef(0);
  const notify = useRef(onConnectionChange);
  notify.current = onConnectionChange;
  const connectionResult = (error?: ApiError) => {
    // Invalid report parameters do not mean the connection itself is broken.
    if (error && ![0, 401, 403, 429, 502, 503, 504].includes(error.status))
      return;
    const needsKey = !!error && [401, 403].includes(error.status);
    notify.current(
      {
        ...source,
        connected: !needsKey,
        connection_status: needsKey ? "reconnect" : error ? "error" : "ready",
        connection_error: error?.message,
      },
      needsKey,
    );
  };
  const resultHandler = useRef(connectionResult);
  resultHandler.current = connectionResult;
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
        if (controller.signal.aborted) return;
        setData(result);
        setMetric(result.metrics?.[0]?.key || "users");
        resultHandler.current();
      })
      .catch((e) => {
        if (!controller.signal.aborted && e.name !== "AbortError") {
          setError(e.message);
          resultHandler.current(e);
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => {
      controller.abort();
      reportVersion.current++;
    };
  }, [source.id, report, dates, refresh]);
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
      resultHandler.current();
      setData((previous) =>
        previous
          ? { ...next, rows: [...(previous.rows || []), ...(next.rows || [])] }
          : next,
      );
    } catch (error) {
      if (version === reportVersion.current) {
        setPageError((error as Error).message);
        resultHandler.current(error as ApiError);
      }
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
      fullscreen
      actions={
        <>
          <button
            className="icon-button"
            aria-label="Настройки источника"
            onClick={onManage}
          >
            <Settings2 size={17} />
          </button>
        </>
      }
    >
      <div className="source-overview">
        <aside className="report-sidebar">
          <div className="report-source">
            <ProviderIcon id={provider.id} large />
            <div>
              <strong>{provider.name}</strong>
              <span
                title={
                  source.metadata.site ||
                  source.metadata.counter_id ||
                  source.metadata.property_id
                }
              >
                {source.metadata.site ||
                  source.metadata.counter_id ||
                  source.metadata.property_id ||
                  source.metadata.timezone}
              </span>
            </div>
          </div>
          <nav className="report-tabs" aria-label="Разделы источника">
            {provider.reports.map((key) => {
              const Icon = reportIcons[key] || ChartNoAxesCombined;
              return (
                <button
                  key={key}
                  className={report === key ? "active" : ""}
                  aria-current={report === key ? "page" : undefined}
                  aria-controls="source-report-content"
                  onClick={() => {
                    setReport(key);
                    setRefresh(0);
                  }}
                >
                  <Icon size={18} aria-hidden="true" />
                  <span>{reportNames[key] || key}</span>
                </button>
              );
            })}
          </nav>
        </aside>
        <div className="report-main">
          <ReportPeriod
            dates={dates}
            loading={loading}
            onChange={(next) => {
              setDates((current) =>
                current.date1 === next.date1 && current.date2 === next.date2
                  ? current
                  : next,
              );
              setRefresh(0);
            }}
            onRefresh={() => setRefresh((value) => value + 1)}
          />
          <section
            id="source-report-content"
            aria-label={reportNames[report] || report}
            aria-busy={loading}
          >
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
                              "metric-card " +
                              (metric === m.key ? "selected" : "")
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
                      <AnalyticsChart series={data.series || []} metric={metric} label={selected?.label || metric}
                    format={selected?.format} color={colors[(data.metrics || []).findIndex(m => m.key === metric)] || colors[0]} />
                  {!data.series?.length && (
                        <p className="empty-report">
                          За этот период данных нет.
                        </p>
                      )}
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
                          new Date(data.fetched_at).toLocaleTimeString(
                            "ru-RU",
                            {
                              hour: "2-digit",
                              minute: "2-digit",
                            },
                          )
                        : ""}
                    </span>
                  </div>
                </>
              )
            )}
          </section>
        </div>
      </div>
    </Modal>
  );
}
