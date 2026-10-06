import { useId, useMemo, useState, type ReactNode } from "react";

import type { Report } from "../api/types";
import { buildCsv } from "./csv";
import {
  formatCell,
  isNumber,
  numericColumns,
  tableModel,
  type TableModel,
} from "./tableModel";

const generatedAtFormat = new Intl.DateTimeFormat("ru-RU", {
  dateStyle: "medium",
  timeStyle: "short",
});

/** Browser-locale rendering of `generated_at`; an unparsable value is shown as-is. */
export function formatGeneratedAt(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : generatedAtFormat.format(date);
}

function formatArg(value: unknown): string {
  return typeof value === "string" ? value : JSON.stringify(value);
}

function downloadText(filename: string, text: string, type: string): void {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

export interface ReportPreviewProps {
  report: Report;
  /** The originating chat was deleted: show «Чат удалён» instead of `chatLink`. */
  orphan?: boolean;
  /** Link back to the chat, rendered by the owning panel (todos 14/15). */
  chatLink?: ReactNode;
}

export function ReportPreview({
  report,
  orphan = false,
  chatLink,
}: ReportPreviewProps) {
  const headingId = useId();
  const paramsId = useId();
  const model = useMemo(() => tableModel(report.data), [report.data]);

  return (
    <article className="report-preview" aria-labelledby={headingId}>
      <header className="report-preview__header">
        <h2 id={headingId} className="report-preview__title">
          {report.title}
        </h2>
        <p className="report-preview__meta">
          <span>Сформирован: {formatGeneratedAt(report.generated_at)}</span>
          <span>Версия {report.version}</span>
          {orphan ? (
            <span className="report-preview__orphan">Чат удалён</span>
          ) : (
            chatLink
          )}
        </p>
      </header>

      <section className="report-params" aria-labelledby={paramsId}>
        <h3 id={paramsId} className="report-params__title">
          Параметры
        </h3>
        <dl className="report-params__list">
          <ParamRow term="Запрос" value={report.question} />
          <ParamRow term="Инструмент" value={report.tool} mono />
          {Object.entries(report.args).map(([key, value]) => (
            <ParamRow key={key} term={key} value={formatArg(value)} mono />
          ))}
          <ParamRow
            term="Строк"
            value={report.row_count === null ? "—" : String(report.row_count)}
          />
        </dl>
      </section>

      <section className="report-body">
        {model ? (
          <TabularBody report={report} model={model} />
        ) : (
          <ScalarBody data={report.data} />
        )}
      </section>
    </article>
  );
}

function ParamRow({
  term,
  value,
  mono = false,
}: {
  term: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="report-params__row">
      <dt className="report-params__term">{term}</dt>
      <dd className={mono ? "report-params__value is-mono" : "report-params__value"}>
        {value}
      </dd>
    </div>
  );
}

function ScalarBody({ data }: { data: unknown }) {
  if (data === null || data === undefined || (Array.isArray(data) && data.length === 0)) {
    return <p className="report-empty">Нет данных</p>;
  }
  if (typeof data === "object") {
    return <pre className="report-json">{JSON.stringify(data, null, 2)}</pre>;
  }
  return <p className="report-scalar">{String(data)}</p>;
}

function TabularBody({ report, model }: { report: Report; model: TableModel }) {
  const chartColumns = useMemo(() => numericColumns(model), [model]);
  const [chosen, setChosen] = useState<string | null>(null);
  const chartColumn =
    chosen !== null && chartColumns.includes(chosen) ? chosen : chartColumns[0];
  const selectId = useId();

  return (
    <>
      <div className="report-toolbar">
        <span className="report-toolbar__summary">
          Записей: {String(model.rows.length)} · Колонок: {String(model.columns.length)}
        </span>
        <button
          type="button"
          className="report-button"
          onClick={() =>
            downloadText(
              `report-${report.id}-v${String(report.version)}.csv`,
              buildCsv(model.columns, model.rows),
              "text/csv;charset=utf-8",
            )
          }
        >
          Скачать CSV
        </button>
      </div>
      <div className="report-table-wrap">
        <table className="report-table">
          <thead>
            <tr>
              {model.columns.map((column) => (
                <th key={column} scope="col">
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {model.rows.map((row, index) => (
              <tr key={index}>
                {model.columns.map((column) => {
                  const value = row[column];
                  return (
                    <td
                      key={column}
                      className={typeof value === "number" ? "is-number" : undefined}
                    >
                      {formatCell(value)}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {chartColumn !== undefined && model.columns[0] !== undefined ? (
        <div className="report-chart">
          <label className="report-chart__control" htmlFor={selectId}>
            <span>Колонка для графика</span>
            <select
              id={selectId}
              className="report-select"
              value={chartColumn}
              onChange={(event) => setChosen(event.target.value)}
            >
              {chartColumns.map((column) => (
                <option key={column} value={column}>
                  {column}
                </option>
              ))}
            </select>
          </label>
          <BarChart
            column={chartColumn}
            labels={model.rows.map((row) => formatCell(row[model.columns[0] ?? ""]))}
            values={model.rows.map((row) => {
              const value = row[chartColumn];
              return isNumber(value) ? value : null;
            })}
          />
        </div>
      ) : null}
    </>
  );
}

/* Chart geometry in SVG user units (1 unit = 1 px at natural size). */
const MIN_SLOT = 32;
const MAX_SLOT = 96;
const TARGET_WIDTH = 640;
const PLOT_HEIGHT = 160;
const PAD_TOP = 12;
const AXIS_GUTTER = 88;
const PAD_RIGHT = 12;
const LABEL_OFFSET = 22;
/* Axis labels are drawn at -40°; these are the per-character extents of that rotated text. */
const LABEL_CHAR_DX = 5;
const LABEL_CHAR_DY = 4.2;
/* Every bar keeps its label; only labels longer than this are visually shortened
   (the full text stays in the label's <title> and in the bar tooltip). */
const LABEL_CHARS = 40;

function shortLabel(label: string): string {
  return label.length > LABEL_CHARS ? `${label.slice(0, LABEL_CHARS - 1)}…` : label;
}

function BarChart({
  column,
  labels,
  values,
}: {
  column: string;
  labels: string[];
  values: (number | null)[];
}) {
  let min = 0;
  let max = 0;
  for (const value of values) {
    if (value === null) continue;
    if (value < min) min = value;
    if (value > max) max = value;
  }
  const span = max - min || 1;
  const y = (value: number) => PAD_TOP + ((max - value) / span) * PLOT_HEIGHT;
  const baseline = y(0);
  const slot = Math.min(
    MAX_SLOT,
    Math.max(MIN_SLOT, Math.floor(TARGET_WIDTH / Math.max(1, values.length))),
  );
  const bar = Math.round(slot * 0.6);
  const shown = labels.map(shortLabel);
  let longest = 0;
  for (const label of shown) {
    if (label.length > longest) longest = label.length;
  }
  const PAD_LEFT = Math.max(AXIS_GUTTER, Math.ceil(8 + longest * LABEL_CHAR_DX));
  const PAD_BOTTOM = LABEL_OFFSET + Math.ceil(longest * LABEL_CHAR_DY) + 8;
  const width = PAD_LEFT + values.length * slot + PAD_RIGHT;
  const height = PAD_TOP + PLOT_HEIGHT + PAD_BOTTOM;
  const labelY = PAD_TOP + PLOT_HEIGHT + LABEL_OFFSET;

  return (
    <div className="report-chart__scroll">
      <svg
        className="report-chart__svg"
        role="img"
        aria-label={`Столбчатая диаграмма: ${column}`}
        viewBox={`0 0 ${String(width)} ${String(height)}`}
        width={width}
        height={height}
      >
        <text className="report-chart__axis" x={PAD_LEFT - 8} y={PAD_TOP + 4}>
          {String(max)}
        </text>
        <text
          className="report-chart__axis"
          x={PAD_LEFT - 8}
          y={PAD_TOP + PLOT_HEIGHT}
        >
          {String(min)}
        </text>
        <line
          className="report-chart__baseline"
          x1={PAD_LEFT}
          x2={width - PAD_RIGHT}
          y1={Math.round(baseline)}
          y2={Math.round(baseline)}
        />
        {values.map((value, index) => {
          const x = PAD_LEFT + index * slot;
          const label = labels[index] ?? "";
          const centre = x + slot / 2;
          /* A non-zero value always shows at least 1 unit so it is not mistaken for 0. */
          const barHeight =
            value === null || value === 0
              ? 0
              : Math.max(1, Math.round(Math.abs(y(value) - baseline)));
          const barTop =
            value !== null && value < 0
              ? Math.round(baseline)
              : Math.round(baseline) - barHeight;
          return (
            <g key={index}>
              {value !== null ? (
                <rect
                  className="report-chart__bar"
                  x={Math.round(x + (slot - bar) / 2)}
                  y={barTop}
                  width={bar}
                  height={barHeight}
                />
              ) : null}
              {/* Full-height transparent hit area: the tooltip is reachable even for a zero-height bar. */}
              <rect
                className="report-chart__hit"
                x={x}
                y={PAD_TOP}
                width={slot}
                height={PLOT_HEIGHT}
                fill="transparent"
              >
                <title>{`${label}: ${value === null ? "—" : String(value)}`}</title>
              </rect>
              <text
                className="report-chart__label"
                x={centre}
                y={labelY}
                transform={`rotate(-40 ${String(centre)} ${String(labelY)})`}
              >
                <title>{label}</title>
                <tspan>{shown[index]}</tspan>
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
