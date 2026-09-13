import {
  Component,
  useId,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";
import {
  Area,
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { ArrowDownRight, ArrowUpRight, ChevronDown, Minus } from "lucide-react";
import {
  parseVisual,
  visualColor,
  visualNumber,
  type AnswerVisual as Visual,
  type ChartVisual,
  type MetricCard,
} from "./answer-visuals";
import "./answer-visuals.css";

function VisualFallback() {
  return (
    <div className="answer-visual-fallback" role="note">
      Не удалось отобразить визуализацию. Попросите показать эти данные
      таблицей.
    </div>
  );
}
class VisualBoundary extends Component<
  { children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  render() {
    return this.state.failed ? <VisualFallback /> : this.props.children;
  }
}

function Sparkline({ item, color }: { item: MetricCard; color: string }) {
  if (!item.trend) return null;
  const values = item.trend.filter((v): v is number => v !== null);
  const min = Math.min(...values),
    max = Math.max(...values);
  const y = (value: number) =>
    max === min ? 17 : 30 - ((value - min) / (max - min)) * 26;
  let connected = false;
  const path = item.trend
    .map((value, i) => {
      if (value === null) {
        connected = false;
        return "";
      }
      const command = connected ? "L" : "M";
      connected = true;
      return `${command}${4 + (i / (item.trend!.length - 1)) * 112},${y(value)}`;
    })
    .join(" ");
  return (
    <div className="answer-sparkline">
      <svg viewBox="0 0 120 34" role="img" aria-label={item.trend_label}>
        <title>
          {item.trend_label}:{" "}
          {item.trend
            .map((v) => visualNumber(v, item.format, item.unit))
            .join(", ")}
        </title>
        <path
          d={path}
          fill="none"
          stroke={color}
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      <span>{item.trend_label}</span>
    </div>
  );
}
function Metric({ item }: { item: MetricCard }) {
  const color = visualColor(item.key);
  const DeltaIcon = !item.change_percent
    ? Minus
    : item.change_percent > 0
      ? ArrowUpRight
      : ArrowDownRight;
  return (
    <div
      className="answer-metric"
      style={{ "--metric-color": color } as CSSProperties}
    >
      <span className="answer-metric-label">
        <i aria-hidden="true" />
        {item.label}
      </span>
      <strong className="answer-metric-value">
        {visualNumber(item.value, item.format, item.unit)}
      </strong>
      {item.change_percent !== undefined && (
        <div className="answer-metric-comparison">
          <span className={`answer-metric-change ${item.sentiment}`}>
            <DeltaIcon size={14} aria-hidden="true" />
            {item.change_percent > 0 ? "+" : ""}
            {visualNumber(item.change_percent, "percent")}
          </span>
          <span>{item.comparison}</span>
        </div>
      )}
      <Sparkline item={item} color={color} />
    </div>
  );
}

function ChartHint({
  active,
  payload,
  label,
  block,
}: {
  active?: boolean;
  payload?: readonly { dataKey?: unknown; value?: unknown }[];
  label?: unknown;
  block: ChartVisual;
}) {
  if (!active || !payload?.length) return null;
  const row = block.data.find((row) => row[block.x_key] === label);
  return (
    <div className="answer-chart-hint">
      <strong>{String(label ?? "")}</strong>
      {block.series.map((s) => (
        <div key={s.key}>
          <i style={{ background: visualColor(s.key) }} />
          <span>{s.label}</span>
          <b>
            {visualNumber(
              (row?.[s.key] ?? null) as number | null,
              block.format,
              block.unit,
            )}
          </b>
        </div>
      ))}
    </div>
  );
}
function Chart({ block }: { block: ChartVisual }) {
  const gradient = useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const [showData, setShowData] = useState(false);
  return (
    <>
      <div className="answer-chart-legend" aria-label="Показатели графика">
        {block.series.map((s, i) => (
          <span key={s.key}>
            <i
              aria-hidden="true"
              style={{
                borderColor: visualColor(s.key),
                borderTopStyle: i % 2 ? "dashed" : "solid",
              }}
            />
            {s.label}
          </span>
        ))}
        {(block.unit || block.format !== "number") && (
          <span className="answer-chart-unit">
            {block.unit || (block.format === "percent" ? "%" : "Длительность")}
          </span>
        )}
      </div>
      <div
        className="answer-chart-canvas"
        role="group"
        aria-label={`График: ${block.title}. Точные значения доступны в таблице под графиком.`}
      >
        <ResponsiveContainer width="100%" height="100%" minWidth={0}>
          <ComposedChart
            data={block.data}
            accessibilityLayer
            margin={{ top: 10, right: 16, bottom: 12, left: 0 }}
          >
            <defs>
              {block.series.map((s) => (
                <linearGradient
                  key={s.key}
                  id={`${gradient}-${s.key}`}
                  x1="0"
                  y1="0"
                  x2="0"
                  y2="1"
                >
                  <stop
                    offset="0%"
                    stopColor={visualColor(s.key)}
                    stopOpacity={0.2}
                  />
                  <stop
                    offset="100%"
                    stopColor={visualColor(s.key)}
                    stopOpacity={0.025}
                  />
                </linearGradient>
              ))}
            </defs>
            <CartesianGrid
              vertical={false}
              stroke="#e4ddec"
              strokeDasharray="3 5"
            />
            <XAxis
              dataKey={block.x_key}
              axisLine={false}
              tickLine={false}
              minTickGap={28}
              tick={{ fill: "#786c85", fontSize: 11 }}
              dy={8}
              tickFormatter={(value) => {
                const label = String(value);
                const date = label.match(
                  /^\d{4}-(\d{2})-(\d{2})(?:[T ](\d{2}:\d{2}))?/,
                );
                if (date)
                  return `${date[2]}.${date[1]}${date[3] ? ` ${date[3]}` : ""}`;
                return label.length > 18 ? `${label.slice(0, 16)}…` : label;
              }}
            />
            <YAxis
              axisLine={false}
              tickLine={false}
              width={66}
              domain={[
                (min: number) => Math.min(0, min),
                (max: number) => Math.max(0, max),
              ]}
              tick={{ fill: "#786c85", fontSize: 11 }}
              tickFormatter={(value) =>
                visualNumber(Number(value), block.format, undefined, true)
              }
            />
            <ReferenceLine y={0} stroke="#c8bdd4" />
            <Tooltip
              isAnimationActive={false}
              filterNull={false}
              cursor={
                block.kind === "bar"
                  ? { fill: "#8061ad0a" }
                  : { stroke: "#b1a3c0", strokeDasharray: "3 3" }
              }
              content={<ChartHint block={block} />}
            />
            {block.series.map((s, i) =>
              block.kind === "bar" ? (
                <Bar
                  key={s.key}
                  dataKey={s.key}
                  name={s.label}
                  fill={visualColor(s.key)}
                  maxBarSize={38}
                  radius={[4, 4, 0, 0]}
                  isAnimationActive={false}
                />
              ) : block.kind === "area" ? (
                <Area
                  key={s.key}
                  type="linear"
                  dataKey={s.key}
                  name={s.label}
                  stroke={visualColor(s.key)}
                  strokeWidth={2.5}
                  strokeDasharray={i % 2 ? "5 3" : undefined}
                  fill={`url(#${gradient}-${s.key})`}
                  connectNulls={false}
                  dot={{
                    r: block.data.length <= 14 ? 3 : 1.5,
                    fill: visualColor(s.key),
                    stroke: "white",
                    strokeWidth: 1.5,
                  }}
                  activeDot={{ r: 5, stroke: "white", strokeWidth: 2 }}
                  isAnimationActive={false}
                />
              ) : (
                <Line
                  key={s.key}
                  type="linear"
                  dataKey={s.key}
                  name={s.label}
                  stroke={visualColor(s.key)}
                  strokeWidth={2.5}
                  strokeDasharray={i % 2 ? "5 3" : undefined}
                  connectNulls={false}
                  dot={{
                    r: block.data.length <= 14 ? 3 : 1.5,
                    fill: visualColor(s.key),
                    stroke: "white",
                    strokeWidth: 1.5,
                  }}
                  activeDot={{ r: 5, stroke: "white", strokeWidth: 2 }}
                  isAnimationActive={false}
                />
              ),
            )}
          </ComposedChart>
        </ResponsiveContainer>
      </div>
      <details
        className="answer-chart-data"
        onToggle={(e) => setShowData(e.currentTarget.open)}
      >
        <summary>
          <ChevronDown size={14} aria-hidden="true" />
          {showData ? "Скрыть данные" : "Показать данные"}
          <span>Строк: {block.data.length}</span>
        </summary>
        {showData && (
          <div
            className="table-scroll answer-table"
            role="region"
            aria-label={`Данные: ${block.title}`}
            tabIndex={0}
          >
            <table>
              <thead>
                <tr>
                  <th scope="col">{block.x_label || block.x_key}</th>
                  {block.series.map((s) => (
                    <th scope="col" key={s.key}>
                      {s.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {block.data.map((row, i) => (
                  <tr key={i}>
                    <td>{String(row[block.x_key])}</td>
                    {block.series.map((s) => (
                      <td key={s.key}>
                        {visualNumber(
                          row[s.key] as number | null,
                          block.format,
                          block.unit,
                        )}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </details>
    </>
  );
}
function VisualContent({ block }: { block: Visual }) {
  return (
    <section
      className={`answer-visual answer-visual-${block.type}`}
      aria-label={block.title}
    >
      <header className="answer-visual-heading">
        <h3>{block.title}</h3>
        {block.subtitle && <p>{block.subtitle}</p>}
      </header>
      {block.type === "metrics" ? (
        <div className="answer-metrics-grid">
          {block.items.map((item) => (
            <Metric key={item.key} item={item} />
          ))}
        </div>
      ) : (
        <Chart block={block} />
      )}
      <footer className="answer-visual-footer">
        <span>{block.source}</span>
        {block.note && <p>{block.note}</p>}
      </footer>
    </section>
  );
}
export function AnswerVisualBlock({ source }: { source: string }) {
  const block = parseVisual(source);
  if (!block) return <VisualFallback />;
  return (
    <VisualBoundary key={source}>
      <VisualContent block={block} />
    </VisualBoundary>
  );
}
