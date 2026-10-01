// Preserve the four old Streamlit reasoning scenarios verbatim.
export const REASONING_FULL =
  "Шаг 1: выбираю инструмент выборки очков.\n\n" +
  "Шаг 2: сортирую команды и оформляю таблицу.";
export const REASONING_PARTIAL = "Шаг 1: выбираю инструмент выборки очков.";
export const ANSWER_WITH_REASONING = "Отчёт по очкам команд готов.";
export const ANSWER_WITHOUT_REASONING = "Отчёт без рассуждений готов.";
export const FAILURE_MESSAGE = "Не удалось построить отчёт: превышено время ожидания.";
export const REPORT_TITLE = "Результаты за период";
export const QUESTION = "Покажи результаты за период";
export const REPORT_ARGS = { table: "results", period: "2026-09", limit: 20 } as const;
export const REPORT_DATA = [
  { название: "Первая строка", значение: 1234.5678 },
  { название: "Вторая строка", значение: 37 },
];
