export type ReportDates = { date1: string; date2: string };
export type PeriodPreset = "today" | "yesterday" | "week" | "month" | "quarter";

export const periodPresets: {
  id: PeriodPreset;
  label: string;
  hint: string;
}[] = [
  { id: "today", label: "Сегодня", hint: "Сегодня, данные за неполный день" },
  { id: "yesterday", label: "Вчера", hint: "Вчера" },
  { id: "week", label: "Неделя", hint: "Последние 7 полных дней" },
  { id: "month", label: "Месяц", hint: "Последние 30 полных дней" },
  { id: "quarter", label: "Квартал", hint: "Последние 90 полных дней" },
];

export const localDate = (date: Date) =>
  `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;

export function presetDates(
  preset: PeriodPreset,
  now = new Date(),
): ReportDates {
  const end = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 12);
  if (preset !== "today") end.setDate(end.getDate() - 1);
  const days = { today: 1, yesterday: 1, week: 7, month: 30, quarter: 90 }[
    preset
  ];
  const start = new Date(end);
  start.setDate(start.getDate() - days + 1);
  return { date1: localDate(start), date2: localDate(end) };
}

export function matchingPreset(dates: ReportDates, now = new Date()) {
  return periodPresets.find(({ id }) => {
    const range = presetDates(id, now);
    return range.date1 === dates.date1 && range.date2 === dates.date2;
  })?.id;
}

export function periodError(dates: ReportDates, today = localDate(new Date())) {
  const first = Date.parse(dates.date1),
    last = Date.parse(dates.date2);
  if (!Number.isFinite(first) || !Number.isFinite(last))
    return "Укажите обе даты.";
  if (first > last) return "Начало периода должно быть не позже его конца.";
  if ((last - first) / 86400000 > 365)
    return "Выберите период не длиннее 366 дней.";
  if (dates.date2 > today) return "Выберите дату не позже сегодняшней.";
  return "";
}
