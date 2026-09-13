import type { AnalysisChart } from "../src/AnalysisPanel";
export const analysisId = "a".repeat(32);
export const analysisFixture: AnalysisChart = {
  version: 1, kind: "line", title: "Россия и США · активность по часам",
  subtitle: "12 сентября 2026 · московское время, UTC+3 · синтетические данные",
  note: "Посетители по часам. Эти значения не измеряют одновременный онлайн. Пропуск данных остаётся разрывом линии.",
  format: "number", unit: "чел.", x_label: "Московское время", y_label: "", source_result: "b".repeat(32),
  series: [{ key: "s0", label: "Россия" }, { key: "s1", label: "США" }],
  data: Array.from({ length: 24 }, (_, hour) => ({ x: `${String(hour).padStart(2, "0")}:00`, s0: hour === 6 ? null : Math.round(35 + 30 * Math.sin((hour + 9) / 4)), s1: Math.round(25 + 20 * Math.sin((hour + 2) / 4)) })),
  provenance: { operation: "run_python", inputs: { visits: "synthetic-result" }, code: "result = frames['visits'].pivot(index='hour', columns='country', values='users').reset_index()", sources: [{ operation: "metrika_timeseries", metadata: { timezone: "+03:00", sampled: false } }] },
};
