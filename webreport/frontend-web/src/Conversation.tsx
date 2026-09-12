import { useState } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Check,
  ChevronDown,
  ChevronRight,
  Copy,
  RotateCcw,
  CheckCheck,
} from "lucide-react";
import type { Job, Message } from "./types";
import { Spinner } from "./ui";
import { number } from "./api";

export function MarkdownText({ text }: { text: string }) {
  return (
    <div className="markdown">
      <Markdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ children, ...props }) => (
            <a {...props} target="_blank" rel="noreferrer">
              {children}
            </a>
          ),
          table: ({ children }) => (
            <div className="table-scroll">
              <table>{children}</table>
            </div>
          ),
        }}
      >
        {text}
      </Markdown>
    </div>
  );
}
export function Reasoning({
  text,
  partial = false,
}: {
  text: string;
  partial?: boolean;
}) {
  return (
    <details className="reasoning">
      <summary>
        <ChevronRight size={14} />
        {partial ? "Рассуждения (неполные)" : "Рассуждения"}
      </summary>
      <div>
        <MarkdownText text={text} />
      </div>
    </details>
  );
}
function DataResult({ data }: { data: unknown }) {
  const rows = Array.isArray(data)
    ? data
    : typeof data === "object" && data !== null && "rows" in data
      ? (data as { rows: unknown[] }).rows
      : [];
  const records = rows.filter(
    (r): r is Record<string, unknown> =>
      !!r && typeof r === "object" && !Array.isArray(r),
  );
  if (!records.length) return null;
  const keys = Object.keys(records[0])
    .filter((k) => records.every((r) => typeof r[k] !== "object"))
    .slice(0, 10);
  if (!keys.length) return null;
  return (
    <details className="inline-data">
      <summary>
        Данные ответа <span>{records.length}</span>
        <ChevronDown size={14} />
      </summary>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              {keys.map((k) => (
                <th key={k}>{k}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {records.slice(0, 100).map((r, i) => (
              <tr key={i}>
                {keys.map((k) => (
                  <td key={k}>{number(r[k])}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}
export function MessageView({
  message,
  onRetry,
}: {
  message: Message;
  onRetry: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const timestamp = message.created_at ? new Date(message.created_at) : null;
  const receivedAt =
    timestamp && Number.isFinite(timestamp.getTime()) ? timestamp : null;
  if (message.role === "user")
    return (
      <article className="message user-message">
        <div>{message.content}</div>
      </article>
    );
  if (message.role === "error")
    return (
      <article className="message error-message">
        {message.reasoning && <Reasoning text={message.reasoning} partial />}
        <p>{message.content}</p>
        <button className="text-button" onClick={onRetry}>
          <RotateCcw size={14} />
          Повторить
        </button>
      </article>
    );
  return (
    <article className="message assistant-message">
      {message.reasoning && <Reasoning text={message.reasoning} />}
      <MarkdownText text={message.content} />
      <DataResult data={message.data} />
      <div className="answer-actions">
        <button
          className="icon-button"
          aria-label={copied ? "Скопировано" : "Скопировать ответ"}
          onClick={async () => {
            try {
              await navigator.clipboard.writeText(message.content);
              setCopied(true);
              setTimeout(() => setCopied(false), 1800);
            } catch {
              setCopied(false);
            }
          }}
        >
          {copied ? <Check size={15} /> : <Copy size={15} />}
        </button>
        <span>{message.model}</span>
        {message.duration_seconds != null &&
          Number.isFinite(message.duration_seconds) && (
            <span className="answer-meta" title="Время выполнения">
              {formatDuration(message.duration_seconds)}
            </span>
          )}
        {receivedAt && (
          <time
            className="answer-meta"
            dateTime={message.created_at}
            title={receivedAt.toLocaleString("ru-RU")}
          >
            {receivedAt.toLocaleTimeString("ru-RU", {
              hour: "2-digit",
              minute: "2-digit",
            })}
          </time>
        )}
      </div>
    </article>
  );
}
function formatDuration(seconds: number) {
  const total = Math.max(1, Math.round(seconds));
  const hours = Math.floor(total / 3600),
    minutes = Math.floor((total % 3600) / 60),
    rest = total % 60;
  return [
    hours ? `${hours} ч` : "",
    minutes ? `${minutes} мин` : "",
    rest || (!hours && !minutes) ? `${rest} с` : "",
  ]
    .filter(Boolean)
    .join(" ");
}
const toolNames: Record<string, string> = {
  list_sources: "Проверяю источники проекта",
  analytics_overview: "Загружаю сводку",
  analytics_report: "Получаю подробный отчёт",
  metrika_query: "Запрашиваю данные Метрики",
  read_rows: "Читаю данные",
  mark_report: "Подготавливаю результат",
  read_knowledge: "Изучаю описание данных",
};
export function JobView({
  job,
  connection,
}: {
  job: Job | null;
  connection: string;
}) {
  const events = job?.events || [];
  const last = events.filter((e) => e.type !== "reasoning").at(-1);
  const reasoning = events
    .filter((e) => e.type === "reasoning")
    .map((e) => e.text)
    .join("\n\n");
  return (
    <article
      className="message progress-message"
      role="status"
      aria-live="polite"
    >
      <Spinner
        label={
          connection ||
          (last?.type === "tool"
            ? toolNames[last.text] || "Работаю с данными…"
            : last?.text) ||
          "Сообщение отправлено…"
        }
      />
      {reasoning && <Reasoning text={reasoning} />}
      <details className="request-details">
        <summary>
          Ход запроса
          <ChevronDown size={13} />
        </summary>
        <ol>
          {events
            .filter((e) => e.type !== "reasoning")
            .map((e, i) => (
              <li key={i}>
                <span>
                  {e.type === "tool"
                    ? toolNames[e.text] || "Инструмент: " + e.text
                    : e.text}
                </span>
                {e.state === "completed" && <CheckCheck size={13} />}
              </li>
            ))}
        </ol>
      </details>
    </article>
  );
}
