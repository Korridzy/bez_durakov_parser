/** Versioned, data-only blocks embedded in an assistant's Markdown response. */
export const VISUAL_LANGUAGE = "dig-visual";
export const MAX_VISUAL_LENGTH = 64_000;
export const MAX_VISUAL_BLOCKS = 4;

type MarkdownNode = {
  type: string;
  lang?: string | null;
  children?: MarkdownNode[];
};
/** Each Markdown tree gets its own budget, including blocks nested in lists/quotes. */
export function limitVisualBlocks() {
  return (tree: MarkdownNode) => {
    let count = 0;
    const visit = (node: MarkdownNode) => {
      if (
        node.type === "code" &&
        node.lang === VISUAL_LANGUAGE &&
        ++count > MAX_VISUAL_BLOCKS
      )
        node.lang = `${VISUAL_LANGUAGE}-limit`;
      node.children?.forEach(visit);
    };
    visit(tree);
  };
}
export type ValueFormat = "number" | "percent" | "duration";
type Presentation = { format: ValueFormat; unit?: string };
type BaseVisual = {
  version: 1;
  title: string;
  subtitle?: string;
  source: string;
  note?: string;
};
export type MetricCard = Presentation & {
  key: string;
  label: string;
  value: number | null;
  change_percent?: number;
  comparison?: string;
  sentiment: "good" | "bad" | "neutral";
  trend?: (number | null)[];
  trend_label?: string;
};
export type MetricsVisual = BaseVisual & {
  type: "metrics";
  items: MetricCard[];
};
export type ChartVisual = BaseVisual &
  Presentation & {
    type: "chart";
    kind: "line" | "area" | "bar";
    x_key: string;
    x_label?: string;
    series: { key: string; label: string }[];
    data: Record<string, string | number | null>[];
  };
export type AnswerVisual = MetricsVisual | ChartVisual;

const object = (value: unknown): Record<string, unknown> => {
  if (!value || typeof value !== "object" || Array.isArray(value))
    throw new Error("Expected an object");
  return value as Record<string, unknown>;
};
const text = (value: unknown, max = 120): string => {
  if (typeof value !== "string" || !value.trim() || value.length > max)
    throw new Error("Invalid label");
  return value.trim();
};
const optionalText = (value: unknown, max: number) =>
  value === undefined ? undefined : text(value, max);
const numeric = (value: unknown): number => {
  if (
    typeof value !== "number" ||
    !Number.isFinite(value) ||
    Math.abs(value) > 1e15
  )
    throw new Error("Invalid number");
  return value;
};
const nullableNumber = (value: unknown) =>
  value === null ? null : numeric(value);
const key = (value: unknown): string => {
  const result = text(value, 48);
  if (
    !/^[a-z][a-z0-9_]*$/.test(result) ||
    ["constructor", "prototype"].includes(result)
  )
    throw new Error("Invalid data key");
  return result;
};
function list(value: unknown, max: number): unknown[] {
  if (!Array.isArray(value) || !value.length || value.length > max)
    throw new Error("Invalid item count");
  return value;
}
function unique(keys: string[]) {
  if (new Set(keys).size !== keys.length) throw new Error("Duplicate key");
}
function presentation(raw: Record<string, unknown>): Presentation {
  const format = raw.format ?? "number";
  if (format !== "number" && format !== "percent" && format !== "duration")
    throw new Error("Unknown number format");
  const unit = optionalText(raw.unit, 16);
  if (unit && format !== "number") throw new Error("Conflicting units");
  return { format, unit };
}

/** Project known fields only. Never evaluate code, resolve URLs or pass model props to a chart. */
export function parseVisual(source: string): AnswerVisual | null {
  try {
    if (source.length > MAX_VISUAL_LENGTH) return null;
    const raw = object(JSON.parse(source));
    if (raw.version !== 1) return null;
    const base: BaseVisual = {
      version: 1,
      title: text(raw.title),
      subtitle: optionalText(raw.subtitle, 240),
      source: text(raw.source, 240),
      note: optionalText(raw.note, 500),
    };
    if (raw.type === "metrics") {
      const items = list(raw.items, 6).map((item): MetricCard => {
        const card = object(item);
        const change =
          card.change_percent === undefined
            ? undefined
            : numeric(card.change_percent);
        const comparison = optionalText(card.comparison, 120);
        if ((change !== undefined) !== (comparison !== undefined))
          throw new Error("A change needs a comparison period");
        const sentiment = card.sentiment ?? "neutral";
        if (!["good", "bad", "neutral"].includes(String(sentiment)))
          throw new Error("Unknown change meaning");
        const trend =
          card.trend === undefined
            ? undefined
            : list(card.trend, 60).map(nullableNumber);
        const trendLabel = optionalText(card.trend_label, 120);
        if (
          trend &&
          (!trendLabel || trend.length < 2 || trend.every((v) => v === null))
        )
          throw new Error("A trend needs observed values and a period");
        return {
          key: key(card.key),
          label: text(card.label, 80),
          value: nullableNumber(card.value),
          ...presentation(card),
          change_percent: change,
          comparison,
          sentiment: sentiment as MetricCard["sentiment"],
          trend,
          trend_label: trendLabel,
        };
      });
      unique(items.map((item) => item.key));
      return { ...base, type: "metrics", items };
    }
    if (
      raw.type !== "chart" ||
      !["line", "area", "bar"].includes(String(raw.kind))
    )
      return null;
    const xKey = key(raw.x_key);
    const series = list(raw.series, 4).map((item) => {
      const spec = object(item);
      return { key: key(spec.key), label: text(spec.label, 80) };
    });
    unique([xKey, ...series.map((s) => s.key)]);
    const data = list(raw.data, 120).map((item) => {
      const row = object(item);
      const result: Record<string, string | number | null> = {
        [xKey]: text(row[xKey], 100),
      };
      for (const s of series) result[s.key] = nullableNumber(row[s.key]);
      return result;
    });
    unique(data.map((row) => String(row[xKey])));
    if (series.some((s) => data.every((row) => row[s.key] === null)))
      return null;
    return {
      ...base,
      ...presentation(raw),
      type: "chart",
      kind: raw.kind as ChartVisual["kind"],
      x_key: xKey,
      x_label: optionalText(raw.x_label, 80),
      series,
      data,
    };
  } catch {
    return null;
  }
}

// Stable colors depend on a metric key, never its position in a particular answer.
const palette = [
  "#8061ad",
  "#cc655b",
  "#3c867c",
  "#ab7b30",
  "#557dae",
  "#a25d83",
];
const metricColors: Record<string, string> = {
  users: palette[0],
  visits: palette[1],
  pageviews: palette[2],
  revenue: palette[3],
  conversions: palette[4],
  conversion_rate: palette[4],
  bounce_rate: palette[5],
};
export function visualColor(metric: string): string {
  if (Object.hasOwn(metricColors, metric)) return metricColors[metric];
  let hash = 0;
  for (const char of metric)
    hash = (Math.imul(hash, 31) + char.charCodeAt(0)) | 0;
  return palette[(hash >>> 0) % palette.length];
}
export function visualNumber(
  value: number | null,
  format: ValueFormat = "number",
  unit?: string,
  compact = false,
): string {
  if (value === null) return "—";
  if (format === "duration") {
    const seconds = Math.round(Math.abs(value));
    const hours = Math.floor(seconds / 3600);
    const minutes = Math.floor((seconds % 3600) / 60);
    return `${value < 0 ? "−" : ""}${hours ? `${hours} ч ` : ""}${minutes ? `${minutes} мин ` : ""}${seconds % 60 || (!hours && !minutes) ? `${seconds % 60} с` : ""}`.trim();
  }
  const number = new Intl.NumberFormat("ru-RU", {
    maximumFractionDigits: 6,
    ...(value !== 0 && Math.abs(value) < 1e-6
      ? { notation: "scientific" as const }
      : {}),
    ...(compact
      ? { notation: "compact" as const, maximumFractionDigits: 1 }
      : {}),
  }).format(value);
  return number + (format === "percent" ? "%" : unit ? ` ${unit}` : "");
}

/** Copy a readable text equivalent instead of implementation JSON. */
export function copyAnswer(text: string): string {
  return text.replace(
    /^(`{3,}|~{3,})dig-visual[^\S\n]*\r?\n([\s\S]*?)^\1[^\S\n]*$/gm,
    (original, _fence, source) => {
      const block = parseVisual(source);
      if (!block) return original;
      const escape = (value: string) =>
        value.replace(/\|/g, "\\|").replace(/\r?\n/g, " ");
      const lines = [block.title, block.subtitle || ""];
      if (block.type === "metrics") {
        lines.push(
          ...block.items.map(
            (item) =>
              `${item.label}: ${visualNumber(item.value, item.format, item.unit)}` +
              (item.change_percent !== undefined
                ? ` (${item.change_percent > 0 ? "+" : ""}${visualNumber(item.change_percent, "percent")}; ${item.comparison})`
                : ""),
          ),
        );
      } else {
        lines.push(
          [
            `| ${[block.x_label || block.x_key, ...block.series.map((s) => s.label)].map(escape).join(" | ")} |`,
            `| ${["---", ...block.series.map(() => "---:")].join(" | ")} |`,
            ...block.data.map(
              (row) =>
                `| ${[String(row[block.x_key]), ...block.series.map((s) => visualNumber(row[s.key] as number | null, block.format, block.unit))].map(escape).join(" | ")} |`,
            ),
          ].join("\n"),
        );
      }
      lines.push(block.source, block.note || "");
      return lines.filter(Boolean).join("\n\n");
    },
  );
}
