export type ExplorerFilter = {
  field: string;
  operator: "eq" | "neq" | "contains" | "not_contains";
  value: string;
};
export type ExplorerQuery = {
  date1: string;
  date2: string;
  metrics: string[];
  dimensions: string[];
  filters: ExplorerFilter[];
  filter_mode: "and" | "or";
  group: string;
  accuracy: "medium" | "full";
  attribution: "last_sign" | "last" | "first";
  include_undefined: boolean;
  goal_id: string;
  sort: string;
  descending: boolean;
  page: number;
  compare: boolean;
};
export type ExplorerMetric = {
  key: string;
  label: string;
  format: string;
  goal?: boolean;
};
export type ExplorerCatalog = {
  metrics: ExplorerMetric[];
  dimensions: {
    key: string;
    label: string;
    category: string;
    operators: ExplorerFilter["operator"][];
  }[];
  presets: { id: string; label: string; dimensions: string[] }[];
  max_points: number;
};
export type ExplorerReport = {
  date1: string;
  date2: string;
  group: string;
  timezone: string;
  metrics: (ExplorerMetric & { value: number | null })[];
  series: Record<string, unknown>[];
  rows: Record<string, unknown>[];
  dimension_values: Record<string, string>[];
  columns: {
    key: string;
    label: string;
    kind: "dimension" | "metric";
    format?: string;
  }[];
  total_rows: number;
  page: number;
  has_more: boolean;
  sampled: boolean;
  sample_share: number;
  contains_sensitive_data: boolean;
  data_lag: number;
  cached: boolean;
  cache: { totals: boolean; series: boolean; table: boolean | null };
  fetched_at: string;
  comparison?: ExplorerReport;
};
export const operatorLabels = {
  eq: "равно",
  neq: "не равно",
  contains: "содержит",
  not_contains: "не содержит",
};
export const groups = [
  { value: "auto", label: "Авто", points: 0 },
  { value: "minute", label: "По минутам", points: 1440 },
  { value: "dekaminute", label: "По 10 минут", points: 144 },
  { value: "hour", label: "По часам", points: 24 },
  { value: "day", label: "По дням", points: 1 },
  { value: "week", label: "По неделям", points: 1 / 7 },
  { value: "month", label: "По месяцам", points: 1 / 28 },
];
export const daysInQuery = (query: { date1: string; date2: string }) =>
  Math.round((Date.parse(query.date2) - Date.parse(query.date1)) / 86400000) +
  1;

export function counterToday(timezone?: string) {
  try {
    const parts = new Intl.DateTimeFormat("en", {
      timeZone: timezone || undefined,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
    }).formatToParts(new Date());
    return ["year", "month", "day"]
      .map((type) => parts.find((p) => p.type === type)!.value)
      .join("-");
  } catch {
    const date = new Date();
    return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
  }
}
