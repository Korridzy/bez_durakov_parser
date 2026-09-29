/**
 * The transcript of one chat: user bubbles, assistant blocks with Markdown,
 * the collapsed «Рассуждения» expander above the answer, state markers,
 * report chips and the thinking mark while a run is active. Pure rendering.
 */

import { useEffect, useRef } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

import type { Message, ReportCard } from "../api/types";
import { usePrefersReducedMotion } from "../motion/usePrefersReducedMotion";
import { useReports } from "../reports/ReportsContext";
import { ThinkingMark, type ThinkingPhase } from "../thinking/ThinkingMark";

export const CONNECTION_RETRY_TEXT = "Нет связи с сервером, повторяю…";
const REASONING_LABEL = "Рассуждения";
const REASONING_PARTIAL_LABEL = "Рассуждения (неполные)";
const EMPTY_TITLE = "Задайте вопрос по данным";
const EMPTY_TEXT =
  "Ответы, рассуждения и отчёты этого чата сохранятся и будут доступны после перезагрузки.";

function UserBubble({ content }: { content: string }) {
  return (
    <div className="msg msg--user">
      <div className="msg__bubble">{content}</div>
    </div>
  );
}

function ReportChip({ reportId, title }: { reportId: string; title: string | undefined }) {
  const { openReport } = useReports();
  return (
    <button type="button" className="msg__report-chip" onClick={() => openReport(reportId)}>
      <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true" focusable="false">
        <rect x="2" y="2" width="12" height="12" rx="1.5" fill="none" stroke="currentColor" strokeWidth="1.4" />
        <path
          d="M4.5 9.5l2-2 2 1.5 3-3"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.4"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
      <span>{title === undefined ? "Отчёт" : `Отчёт: ${title}`}</span>
    </button>
  );
}

function AssistantBlock({ message, reportTitle }: { message: Message; reportTitle: string | undefined }) {
  const isMarker = message.state !== null && message.state !== "succeeded";
  const reasoning =
    message.reasoning !== null && message.reasoning.trim() !== "" ? message.reasoning : null;
  return (
    <article className={`msg msg--assistant${isMarker ? ` is-${message.state}` : ""}`}>
      {reasoning === null ? null : (
        <details className="msg__reasoning">
          <summary className="msg__reasoning-summary">
            {isMarker ? REASONING_PARTIAL_LABEL : REASONING_LABEL}
          </summary>
          <div className="msg__reasoning-body markdown">
            <Markdown remarkPlugins={[remarkGfm]}>{reasoning}</Markdown>
          </div>
        </details>
      )}
      {isMarker ? (
        <p className="msg__marker" role={message.state === "failed" ? "alert" : "status"}>
          {message.content}
        </p>
      ) : (
        <div className="msg__body markdown">
          <Markdown remarkPlugins={[remarkGfm]}>{message.content}</Markdown>
        </div>
      )}
      {message.report_id === null ? null : (
        <div className="msg__chips">
          <ReportChip reportId={message.report_id} title={reportTitle} />
        </div>
      )}
    </article>
  );
}

export interface ConversationProps {
  messages: Message[];
  reports: ReportCard[];
  /** The question sent but not yet in the transcript. */
  optimistic: { request_id: string; message: string } | null;
  /** A run is active or a send is in flight: show the thinking mark. */
  busy: boolean;
  phase: ThinkingPhase;
  connectionLost: boolean;
}

export function Conversation({
  messages,
  reports,
  optimistic,
  busy,
  phase,
  connectionLost,
}: ConversationProps) {
  const endRef = useRef<HTMLDivElement>(null);
  const reducedMotion = usePrefersReducedMotion();
  const showOptimistic =
    optimistic !== null && !messages.some((item) => item.request_id === optimistic.request_id);

  useEffect(() => {
    const end = endRef.current;
    if (end !== null && typeof end.scrollIntoView === "function") {
      end.scrollIntoView({ block: "end", behavior: reducedMotion ? "auto" : "smooth" });
    }
  }, [messages.length, showOptimistic, busy, reducedMotion]);

  if (messages.length === 0 && !showOptimistic && !busy) {
    return (
      <div className="conversation conversation--empty">
        <h2 className="conversation__empty-title">{EMPTY_TITLE}</h2>
        <p className="conversation__empty-text">{EMPTY_TEXT}</p>
      </div>
    );
  }

  const titleOf = (reportId: string) => reports.find((card) => card.id === reportId)?.title;

  return (
    <div className="conversation" role="log" aria-label="Сообщения">
      {messages.map((item) =>
        item.role === "user" ? (
          <UserBubble key={item.id} content={item.content} />
        ) : (
          <AssistantBlock
            key={item.id}
            message={item}
            reportTitle={item.report_id === null ? undefined : titleOf(item.report_id)}
          />
        ),
      )}
      {showOptimistic ? <UserBubble content={optimistic.message} /> : null}
      {busy ? (
        <div className="msg msg--thinking">
          <ThinkingMark phase={phase} />
          {connectionLost ? <p className="msg__connection">{CONNECTION_RETRY_TEXT}</p> : null}
        </div>
      ) : null}
      <div ref={endRef} aria-hidden="true" />
    </div>
  );
}
