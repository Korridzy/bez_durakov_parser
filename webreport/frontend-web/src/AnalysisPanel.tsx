import { useEffect, useRef, useState } from "react";
import { Area, Bar, CartesianGrid, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis } from "recharts";
import { BarChart3, ChevronDown, Download, Table2, X } from "lucide-react";
import { api } from "./api";
import { Alert, Spinner } from "./ui";
import { visualColor, visualNumber, type ValueFormat } from "./answer-visuals";
import "./analysis-panel.css";

type Row = Record<string, string | number | null>;
export type AnalysisChart = {
  version: 1; kind: "line" | "area" | "bar" | "stacked_bar" | "scatter" | "histogram" | "heatmap" | "funnel" | "table";
  title: string; subtitle: string; note: string; format: ValueFormat; unit: string;
  x_label: string; y_label: string; series: { key: string; label: string }[]; data: Row[];
  source_result: string; provenance: Record<string, unknown>;
  warnings?: string[];
};
type Artifact = { id: string; kind: "chart"; created_at: string; value: AnalysisChart };

function download(chart: AnalysisChart) {
  const cell = (v: unknown) => {
    let value = v == null ? "" : String(v);
    if (/^[=+\-@\t\r]/.test(value)) value = "'" + value;
    return '"' + value.replaceAll('"', '""') + '"';
  };
  const keys = ["x", ...(chart.kind === "heatmap" ? ["y"] : []), ...chart.series.map(s => s.key)];
  const labels = [chart.x_label, ...(chart.kind === "heatmap" ? [chart.y_label] : []), ...chart.series.map(s => s.label)];
  const csv = "\uFEFF" + [labels, ...chart.data.map(r => keys.map(k => r[k]))].map(r => r.map(cell).join(",")).join("\r\n");
  const url = URL.createObjectURL(new Blob([csv], { type: "text/csv;charset=utf-8" }));
  const a = document.createElement("a");
  a.href = url; a.download = "analysis.csv"; a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function ValueTable({ chart }: { chart: AnalysisChart }) {
  const [count, setCount] = useState(100);
  return <>
    <div className="analysis-table table-scroll answer-table" tabIndex={0} role="region" aria-label="Данные анализа">
      <table><thead><tr><th>{chart.x_label}</th>{chart.kind === "heatmap" && <th>{chart.y_label}</th>}{chart.series.map(s => <th key={s.key}>{s.label}</th>)}</tr></thead>
        <tbody>{chart.data.slice(0, count).map((r, i) => <tr key={i}><td>{r.x}</td>{chart.kind === "heatmap" && <td>{r.y}</td>}{chart.series.map(s => <td key={s.key}>{visualNumber(r[s.key] as number | null, chart.format, chart.unit)}</td>)}</tr>)}</tbody>
      </table>
    </div>
    {count < chart.data.length && <button className="secondary-button" onClick={() => setCount(n => n + 100)}>Ещё 100 строк</button>}
  </>;
}

function Heatmap({ chart }: { chart: AnalysisChart }) {
  const xs = [...new Set(chart.data.map(r => String(r.x)))], ys = [...new Set(chart.data.map(r => String(r.y)))];
  const values = chart.data.map(r => r.s0).filter((v): v is number => typeof v === "number");
  const low = Math.min(...values), high = Math.max(...values);
  const lookup = new Map(chart.data.map(r => [JSON.stringify([String(r.x), String(r.y)]), r.s0]));
  return <div className="analysis-heatmap" role="region" tabIndex={0} aria-label={chart.title}>
    <table><thead><tr><th>{chart.y_label} / {chart.x_label}</th>{xs.map(x => <th key={x}>{x}</th>)}</tr></thead>
      <tbody>{ys.map(y => <tr key={y}><th>{y}</th>{xs.map(x => {
        const v = lookup.get(JSON.stringify([x, y]));
        const alpha = typeof v === "number" ? 0.09 + 0.68 * (high === low ? 0.5 : (v - low) / (high - low)) : 0;
        return <td key={x} title={`${x} · ${y}: ${visualNumber(v as number | null ?? null, chart.format, chart.unit)}`} style={{ backgroundColor: `rgba(128, 97, 173, ${alpha})` }}>{visualNumber(v as number | null ?? null, chart.format, chart.unit)}</td>;
      })}</tr>)}</tbody>
    </table><p>Интенсивность цвета: от {visualNumber(low, chart.format, chart.unit)} до {visualNumber(high, chart.format, chart.unit)}. Пропуски обозначены «—».</p>
  </div>;
}

function Funnel({ chart }: { chart: AnalysisChart }) {
  const first = Number(chart.data[0]?.s0 || 0);
  return <ol className="analysis-funnel">{chart.data.map((row, i) => {
    const value = Number(row.s0), previous = i ? Number(chart.data[i - 1].s0) : null;
    return <li key={i}><div><span>{i + 1}. {row.x}</span><strong>{visualNumber(value, chart.format, chart.unit)}</strong></div>
      <div className="analysis-funnel-track"><i style={{ width: `${first ? value / first * 100 : 0}%` }} /></div>
      <small>{first ? visualNumber(value / first * 100, "percent") + " от первого шага" : "Нет участников"}{previous ? ` · потеря на шаге ${visualNumber((previous - value) / previous * 100, "percent")}` : ""}</small>
    </li>;
  })}</ol>;
}

export function AnalysisVisualization({ chart }: { chart: AnalysisChart }) {
  const [hidden, setHidden] = useState<string[]>([]);
  if (chart.kind === "table") return <ValueTable chart={chart} />;
  if (chart.kind === "heatmap") return <Heatmap chart={chart} />;
  if (chart.kind === "funnel") return <Funnel chart={chart} />;
  const scatter = chart.kind === "scatter";
  const format = (n: unknown) => visualNumber(typeof n === "number" ? n : null, chart.format, chart.unit);
  const axisFormat = (n: unknown) => visualNumber(typeof n === "number" ? n : null, chart.format, "", true);
  return <>
    <div className="analysis-legend">{chart.series.map(s => <button key={s.key} aria-pressed={!hidden.includes(s.key)} onClick={() => setHidden(current => current.includes(s.key) ? current.filter(k => k !== s.key) : current.length < chart.series.length - 1 ? [...current, s.key] : current)}><i style={{ background: visualColor(s.label) }} />{s.label}</button>)}</div>
    <div className="analysis-plot" role="group" aria-label={chart.title}>
      <ResponsiveContainer width="100%" height="100%" minWidth={0}>
        {scatter ? <ScatterChart margin={{ top: 16, right: 20, bottom: 25, left: 5 }}>
          <CartesianGrid strokeDasharray="3 5" stroke="#e4ddec" />
          <XAxis type="number" dataKey="x" name={chart.x_label} tickLine={false} />
          <YAxis type="number" dataKey="s0" name={chart.series[0].label} tickFormatter={axisFormat} width={70} tickLine={false} />
          <Tooltip cursor={{ strokeDasharray: "3 3" }} />
          <Scatter data={chart.data.filter(r => r.s0 !== null)} fill={visualColor(chart.series[0].label)} isAnimationActive={false} />
        </ScatterChart> : <ComposedChart data={chart.data} accessibilityLayer margin={{ top: 16, right: 20, bottom: 25, left: 5 }}>
          <CartesianGrid vertical={false} strokeDasharray="3 5" stroke="#e4ddec" />
          <XAxis dataKey="x" tickLine={false} axisLine={false} minTickGap={35} tick={{ fill: "#786c85", fontSize: 11 }} tickFormatter={v => String(v).length > 18 ? String(v).slice(0, 16) + "…" : String(v)} />
          <YAxis tickFormatter={axisFormat} width={70} axisLine={false} tickLine={false} domain={[(min: number) => Math.min(0, min), (max: number) => Math.max(0, max)]} />
          <ReferenceLine y={0} stroke="#c8bdd4" />
          <Tooltip isAnimationActive={false} filterNull={false} formatter={(value, name) => [format(value), name]} contentStyle={{ border: "1px solid #e4ddec", borderRadius: 12, boxShadow: "0 8px 30px #40305018" }} />
          {chart.series.map((s, i) => hidden.includes(s.key) ? null : ["bar", "stacked_bar", "histogram"].includes(chart.kind) ?
            <Bar key={s.key} dataKey={s.key} name={s.label} fill={visualColor(s.label)} stackId={chart.kind === "stacked_bar" ? "total" : undefined} radius={[3, 3, 0, 0]} maxBarSize={45} isAnimationActive={false} /> : chart.kind === "area" ?
              <Area key={s.key} dataKey={s.key} name={s.label} type="linear" stroke={visualColor(s.label)} fill={visualColor(s.label)} fillOpacity={0.12} connectNulls={false} strokeWidth={2.5} isAnimationActive={false} /> :
              <Line key={s.key} dataKey={s.key} name={s.label} type="linear" stroke={visualColor(s.label)} strokeDasharray={i % 2 ? "5 3" : undefined} connectNulls={false} strokeWidth={2.5} dot={chart.data.length < 30} activeDot={{ r: 5 }} isAnimationActive={false} />)}
        </ComposedChart>}
      </ResponsiveContainer>
    </div>
    <div className="analysis-axis-caption">{chart.x_label} · {chart.unit || (chart.format === "percent" ? "%" : chart.format === "duration" ? "Длительность" : "Значение")}</div>
  </>;
}

export function AnalysisPanel({ chatId, resultId, onClose, modal }: { chatId: string; resultId: string; onClose: () => void; modal: boolean }) {
  const [record, setRecord] = useState<Artifact>(), [error, setError] = useState(""), [tab, setTab] = useState("chart");
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    const previous = document.activeElement;
    heading.current?.focus();
    let stopped = false;
    void api<Artifact>(`/chats/${chatId}/analysis/${resultId}`).then(value => { if (!stopped) setRecord(value); }).catch(e => { if (!stopped) setError(e.message); });
    return () => { stopped = true; if (previous instanceof HTMLElement && previous.isConnected) previous.focus(); };
  }, [chatId, resultId]);
  const chart = record?.value;
  return <aside className="analysis-panel" role={modal ? "dialog" : "complementary"} aria-modal={modal || undefined} aria-labelledby="analysis-title" onKeyDown={e => {
    if (e.key === "Escape") { e.stopPropagation(); onClose(); }
    if (modal && e.key === "Tab") {
      const focusable = e.currentTarget.querySelectorAll<HTMLElement>('button, a[href], [tabindex="0"]');
      const first = focusable[0], last = focusable[focusable.length - 1];
      if (e.shiftKey && (document.activeElement === first || document.activeElement === heading.current)) { e.preventDefault(); last?.focus(); }
      else if (!e.shiftKey && document.activeElement === last) { e.preventDefault(); first?.focus(); }
    }
  }}>
    <header className="analysis-panel-header"><div><BarChart3 size={20} /><span>Результат анализа</span></div><button className="icon-button" aria-label="Закрыть анализ" onClick={onClose}><X size={20} /></button></header>
    <div className="analysis-panel-body"><h2 id="analysis-title" tabIndex={-1} ref={heading}>{chart?.title || "Открываю результат…"}</h2>
      {error && <Alert>{error}</Alert>}{!chart && !error && <Spinner label="Загружаю данные…" />}
      {chart && <><p className="analysis-subtitle">{chart.subtitle}</p>
        <div className="analysis-toolbar"><div role="group" aria-label="Вид результата"><button className={tab === "chart" ? "selected" : ""} onClick={() => setTab("chart")}><BarChart3 size={15} />График</button><button className={tab === "table" ? "selected" : ""} onClick={() => setTab("table")}><Table2 size={15} />Данные</button></div><button onClick={() => download(chart)}><Download size={15} />CSV</button></div>
        {tab === "table" ? <ValueTable chart={chart} /> : <AnalysisVisualization chart={chart} />}
        {chart.note && <p className="analysis-note">{chart.note}</p>}
        {chart.warnings?.map((warning, i) => <p key={i} className="analysis-note">{warning}</p>)}
        <p className="analysis-saved">Сохранённый результат · {new Date(record.created_at).toLocaleString("ru-RU")} · {chart.data.length} строк</p>
        <details className="analysis-method"><summary><ChevronDown size={15} />Источник и способ расчёта</summary><p>Параметры исходных запросов и выполненный код. Данные графика зафиксированы при расчёте.</p><pre>{JSON.stringify(chart.provenance, null, 2)}</pre></details>
      </>}
    </div>
  </aside>;
}
