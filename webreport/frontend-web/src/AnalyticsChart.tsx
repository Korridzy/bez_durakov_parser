import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useState,
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
import { dayLabel, number } from "./api";

export const chartColors = [
  "#247e91",
  "#466db2",
  "#8370b6",
  "#b58238",
  "#538c78",
  "#a65f7d",
  "#647a98",
  "#b17453",
];
export function metricValue(value: unknown, format = "number") {
  if (value === null || value === undefined) return "—";
  if (format === "duration") {
    const seconds = Math.round(Number(value));
    return `${Math.floor(seconds / 60)} м ${seconds % 60} с`;
  }
  return number(value) + (format === "percent" ? "%" : "");
}
export function timeLabel(value: string, group = "day", full = false) {
  const clock = value.match(/[T ](\d{2}:\d{2})/)?.[1];
  if (["minute", "dekaminute", "hour"].includes(group) && clock)
    return full ? `${dayLabel(value)} · ${clock}` : clock;
  return dayLabel(value);
}

function ChartHint({
  active,
  payload,
  label,
  group,
  format,
  onVisibility,
}: {
  active?: boolean;
  payload?: readonly {
    name?: string;
    value?: unknown;
    color?: string;
    dataKey?: unknown;
    payload?: Record<string, unknown>;
  }[];
  label?: unknown;
  group: string;
  format: string;
  onVisibility: (active: boolean) => void;
}) {
  const visible = !!active && !!payload?.length;
  useLayoutEffect(() => {
    onVisibility(visible);
    return () => onVisibility(false);
  }, [visible, onVisibility]);
  if (!visible) return null;
  return (
    <div className="chart-tooltip">
      <strong>{timeLabel(String(label), group, true)}</strong>
      {payload!.map((item, i) => (
        <div key={i}>
          <span style={{ background: item.color }} />
          <span>
            {item.name}
            {item.dataKey === "previous" && item.payload?.previousDate ? (
              <small className="comparison-date">
                {timeLabel(String(item.payload.previousDate), group, true)}
              </small>
            ) : null}
          </span>
          <b>{metricValue(item.value, format)}</b>
        </div>
      ))}
    </div>
  );
}

export function AnalyticsChart({
  series,
  metric,
  label,
  format = "number",
  group = "day",
  color = chartColors[0],
  kind = "area",
  comparison,
}: {
  series: Record<string, unknown>[];
  metric: string;
  label: string;
  format?: string;
  group?: string;
  color?: string;
  kind?: "area" | "line" | "bar";
  comparison?: Record<string, unknown>[];
}) {
  const gradient = useId().replace(/:/g, "");
  const [visible, setVisible] = useState(false);
  const [animateTooltip, setAnimateTooltip] = useState(false);
  const [reduced, setReduced] = useState(
    () => matchMedia("(prefers-reduced-motion: reduce)").matches,
  );
  const visibility = useCallback((active: boolean) => {
    setVisible(active);
    if (!active) setAnimateTooltip(false);
  }, []);
  useEffect(() => {
    const preference = matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReduced(preference.matches);
    preference.addEventListener("change", update);
    return () => preference.removeEventListener("change", update);
  }, []);
  useEffect(() => {
    if (!visible) return;
    // Paint at the actual first coordinate before enabling movement. This also
    // resets after mouse leave, empty payload, keyboard dismissal and re-entry.
    let second = 0;
    const first = requestAnimationFrame(() => {
      second = requestAnimationFrame(() => setAnimateTooltip(true));
    });
    return () => {
      cancelAnimationFrame(first);
      cancelAnimationFrame(second);
    };
  }, [visible]);
  const rows = series.map((row, index) => ({
    ...row,
    previous: comparison?.[index]?.[metric],
    previousDate: comparison?.[index]?.date,
  }));
  return (
    <div className="trend-chart" aria-label={`График: ${label}`}>
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart
          data={rows}
          margin={{ top: 14, right: 14, bottom: 8, left: 2 }}
        >
          <defs>
            <linearGradient id={gradient} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.15} />
              <stop offset="100%" stopColor={color} stopOpacity={0.015} />
            </linearGradient>
          </defs>
          <CartesianGrid
            vertical={false}
            stroke="#e4eaf0"
            strokeDasharray="3 5"
          />
          <XAxis
            dataKey="date"
            axisLine={{ stroke: "#97a6b7", strokeWidth: 1.2 }}
            tickLine={false}
            tickFormatter={(value) => timeLabel(value, group)}
            minTickGap={40}
            tick={{ fill: "#6d7c8e", fontSize: 11 }}
            dy={10}
          />
          <YAxis
            axisLine={false}
            tickLine={false}
            tickFormatter={(value) =>
              format === "duration"
                ? `${Math.round(value / 60)} м`
                : number(value)
            }
            tick={{ fill: "#6d7c8e", fontSize: 11 }}
            width={55}
          />
          <ReferenceLine y={0} stroke="#97a6b7" strokeWidth={1.2} />
          <Tooltip
            animationDuration={67}
            animationEasing="linear"
            isAnimationActive={animateTooltip && !reduced}
            cursor={{
              stroke: "#8998aa",
              strokeWidth: 1,
              strokeDasharray: "3 3",
            }}
            content={
              <ChartHint
                group={group}
                format={format}
                onVisibility={visibility}
              />
            }
          />
          {kind === "bar" ? (
            <Bar
              dataKey={metric}
              name={label}
              fill={color}
              maxBarSize={32}
              animationDuration={500}
              isAnimationActive={!reduced}
            />
          ) : kind === "line" ? (
            <Line
              type="linear"
              dataKey={metric}
              name={label}
              stroke={color}
              strokeWidth={2.5}
              dot={series.length === 1}
              activeDot={{ r: 5, stroke: "white", strokeWidth: 2 }}
              animationDuration={500}
              isAnimationActive={!reduced}
            />
          ) : (
            <Area
              type="linear"
              dataKey={metric}
              name={label}
              stroke={color}
              strokeWidth={2.5}
              fill={`url(#${gradient})`}
              dot={series.length === 1 ? { r: 4, strokeWidth: 2 } : false}
              activeDot={{ r: 5, stroke: "white", strokeWidth: 2 }}
              animationDuration={500}
              isAnimationActive={!reduced}
            />
          )}
          {comparison && (
            <Line
              type="linear"
              dataKey="previous"
              name="Предыдущий период"
              stroke="#a37a4b"
              strokeWidth={2}
              strokeDasharray="5 4"
              dot={comparison.length === 1}
              connectNulls={false}
              isAnimationActive={false}
            />
          )}
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}
