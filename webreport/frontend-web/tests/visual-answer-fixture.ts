// Synthetic data only. Used by the real Markdown/chat renderers in dev previews.
import type { AnswerVisual } from "../src/answer-visuals";

export const fixtureVisuals: AnswerVisual[] = [
  {
    version: 1,
    type: "metrics",
    title: "Неделя в цифрах",
    subtitle: "1–7 сентября 2026 · сравнение с предыдущей неделей",
    source: "Демонстрационный источник · синтетические данные",
    items: [
      {
        key: "users",
        label: "Посетители",
        value: 14555,
        format: "number",
        change_percent: 12.4,
        comparison: "к прошлой неделе",
        sentiment: "neutral",
        trend: [1800, 1920, 2040, 2100, 2150, 2310, 2460],
        trend_label: "Посетители по дням",
      },
      {
        key: "visits",
        label: "Визиты",
        value: 22699,
        format: "number",
        change_percent: 8.1,
        comparison: "к прошлой неделе",
        sentiment: "neutral",
        trend: [2700, 2950, 3100, 3220, 3310, 3600, 3819],
        trend_label: "Визиты по дням",
      },
      {
        key: "conversion_rate",
        label: "Конверсия",
        value: 3.8,
        format: "percent",
        change_percent: 6.2,
        comparison: "к прошлой неделе",
        sentiment: "good",
      },
    ],
    note: "Посетители за период посчитаны отдельно от дневных уникальных посетителей.",
  },
  {
    version: 1,
    type: "chart",
    kind: "area",
    title: "Посещаемость постепенно растёт",
    subtitle: "1–7 сентября 2026 · по дням",
    source: "Демонстрационный источник · синтетические данные",
    format: "number",
    x_key: "date",
    x_label: "Дата",
    series: [
      { key: "users", label: "Посетители" },
      { key: "visits", label: "Визиты" },
    ],
    data: [
      { date: "2026-09-01", users: 1800, visits: 2700 },
      { date: "2026-09-02", users: 1920, visits: 2950 },
      { date: "2026-09-03", users: 2040, visits: 3100 },
      { date: "2026-09-04", users: null, visits: 3220 },
      { date: "2026-09-05", users: 2150, visits: 3310 },
      { date: "2026-09-06", users: 2310, visits: 3600 },
      { date: "2026-09-07", users: 2460, visits: 3819 },
    ],
    note: "За 4 сентября отсутствует число посетителей: линия содержит разрыв.",
  },
  {
    version: 1,
    type: "chart",
    kind: "bar",
    title: "Откуда приходят посетители",
    subtitle: "1–7 сентября 2026",
    source: "Демонстрационный источник · синтетические данные",
    format: "number",
    x_key: "channel",
    x_label: "Источник",
    series: [{ key: "users", label: "Посетители" }],
    data: [
      { channel: "Поиск", users: 8420 },
      { channel: "Реклама", users: 4180 },
      { channel: "Прямые заходы", users: 1955 },
    ],
  },
];
const fence = (block: AnswerVisual) =>
  "```dig-visual\n" + JSON.stringify(block) + "\n```";
export const visualAnswer = [
  "За неделю сайт посетили **14 555 человек**. Посещаемость растёт; основной вклад даёт поиск.",
  fence(fixtureVisuals[0]),
  "### Как менялась посещаемость",
  fence(fixtureVisuals[1]),
  "Динамика визитов остаётся положительной. Для 4 сентября число посетителей неизвестно — сравнивать этот день по двум показателям нельзя.",
  fence(fixtureVisuals[2]),
  "**Следующий шаг:** проверить, сохраняется ли рост конверсии на самых посещаемых страницах.",
].join("\n\n");

export const edgeVisualAnswer = [
  fence({
    ...fixtureVisuals[1],
    kind: "line",
    title: "Одна точка и отрицательное значение",
    subtitle: "1 сентября 2026",
    note: "Одно наблюдение отображается точкой; отрицательный баланс остаётся ниже нуля.",
    series: [{ key: "users", label: "Баланс" }],
    data: [{ date: "2026-09-01", users: -12.5 }],
  } as AnswerVisual),
  "Повреждённый блок не должен ломать остальной ответ:",
  '```dig-visual\n{"version":1,"type":"chart","data":null}\n```',
  "Обычный код должен оставаться кодом:",
  '```json\n{"value":42}\n```',
  "Текст после блоков сохранён.",
].join("\n\n");
