import type { Chat, ChatDetail, ChatStatus, Message, Report, ReportCard, Run } from "../src/api/types";
import {
  ANSWER_WITH_REASONING, QUESTION, REASONING_FULL, REPORT_ARGS, REPORT_DATA, REPORT_TITLE,
} from "./testData";

export class TestApiError extends Error {
  constructor(readonly status: number, readonly code: string, message: string) {
    super(message);
    this.name = "TestApiError";
  }
}

export interface Completion {
  readonly answer?: string;
  readonly reasoning?: string | null;
  readonly failure?: string;
  readonly title?: string;
  readonly report?: boolean;
}

interface SeedOptions extends Completion {
  readonly saved?: boolean;
  readonly reportTitle?: string;
}

export function reportCard(report: Report): ReportCard {
  const { data: _data, ...card } = report;
  return card;
}

/** Mutable test-owned API state. Nothing completes by wall-clock or timer. */
export class TestApiState {
  readonly chats = new Map<string, Chat>();
  readonly messages = new Map<string, Message[]>();
  readonly runs = new Map<string, Run>();
  readonly reports = new Map<string, Report>();
  readonly questions = new Map<string, string>();
  updateFailure = false;
  private sequence = 0;
  private minute = 0;

  id(): string {
    return (++this.sequence).toString(16).padStart(32, "0");
  }

  now(): string {
    return new Date(Date.UTC(2026, 8, 29, 12, ++this.minute)).toISOString().replace(".000Z", "Z");
  }

  createChat(title?: string): string {
    const id = this.id();
    const now = this.now();
    this.chats.set(id, {
      id, title: title ?? "Новый чат", auto_title: title === undefined,
      created_at: now, updated_at: now, last_message_at: null, report_count: 0,
    });
    this.messages.set(id, []);
    return id;
  }

  chat(id: string): Chat {
    const chat = this.chats.get(id);
    if (chat === undefined) throw new TestApiError(404, "not_found", "Чат не найден");
    return chat;
  }

  report(id: string): Report {
    const report = this.reports.get(id);
    if (report === undefined) throw new TestApiError(404, "not_found", "Не найдено");
    return report;
  }

  run(id: string): Run {
    const run = this.runs.get(id);
    if (run === undefined) throw new TestApiError(404, "not_found", "Запрос не найден");
    return run;
  }

  status(chatId: string): ChatStatus {
    this.chat(chatId);
    const runs = [...this.runs.values()].filter((run) => run.chat_id === chatId).reverse();
    return {
      active_run: runs.find((run) => run.state === "running" || run.state === "cancelling") ?? null,
      last_run: runs[0] ?? null,
    };
  }

  cards(chatId: string): ReportCard[] {
    return [...this.reports.values()].filter((report) => report.chat_id === chatId)
      .reverse().map(reportCard);
  }

  detail(chatId: string): ChatDetail {
    return {
      chat: { ...this.chat(chatId), report_count: this.cards(chatId).length },
      messages: this.messages.get(chatId) ?? [], reports: this.cards(chatId), ...this.status(chatId),
    };
  }

  startRun(chatId: string, message: string, requestId = this.id()): string {
    const chat = this.chat(chatId);
    const existing = this.runs.get(requestId);
    if (existing !== undefined) {
      if (existing.chat_id !== chatId || this.questions.get(requestId) !== message) {
        throw new TestApiError(409, "request_conflict", "Идентификатор запроса уже использован");
      }
      return existing.request_id;
    }
    if (this.status(chatId).active_run !== null) {
      throw new TestApiError(409, "chat_busy", "Чат занят, дождитесь ответа");
    }
    const now = this.now();
    this.runs.set(requestId, {
      request_id: requestId, chat_id: chatId, state: "running", created_at: now,
      finished_at: null, error: null, response: null,
    });
    this.questions.set(requestId, message);
    this.messages.get(chatId)?.push({
      id: this.id(), request_id: requestId, role: "user", content: message, reasoning: null,
      state: null, report_id: null, created_at: now,
    });
    if (chat.auto_title && chat.last_message_at === null) {
      chat.title = [...message.replace(/\s+/g, " ").trim()].slice(0, 80).join("");
    }
    chat.updated_at = now;
    chat.last_message_at = now;
    return requestId;
  }

  completeRun(id: string, completion: Completion = {}): void {
    const run = this.run(id);
    if (run.state !== "running") throw new TestApiError(409, "request_conflict", "Запрос завершён");
    const chat = this.chat(run.chat_id);
    const now = this.now();
    const failed = completion.failure !== undefined;
    const content = completion.failure ?? completion.answer ?? ANSWER_WITH_REASONING;
    const reasoning = completion.reasoning === undefined ? REASONING_FULL : completion.reasoning;
    let card: ReportCard | null = null;
    if (!failed && completion.report !== false) {
      const report: Report = {
        id: this.id(), chat_id: run.chat_id, title: completion.title ?? REPORT_TITLE,
        question: this.questions.get(id) ?? QUESTION, tool: "read_rows", args: { ...REPORT_ARGS },
        generated_at: now, version: 1, saved_at: null, row_count: REPORT_DATA.length,
        created_at: now, data: structuredClone(REPORT_DATA),
      };
      this.reports.set(report.id, report);
      card = reportCard(report);
    }
    this.messages.get(run.chat_id)?.push({
      id: this.id(), request_id: id, role: "assistant", content, reasoning,
      state: failed ? "failed" : "succeeded", report_id: card?.id ?? null, created_at: now,
    });
    run.state = failed ? "failed" : "succeeded";
    run.finished_at = now;
    run.error = failed ? { code: "timeout", message: content } : null;
    run.response = {
      success: !failed, session_id: run.chat_id, data: null, query_info: [],
      message: content, timestamp: now, error: failed ? content : null,
      reasoning, scope_verdict: null, report: card,
    };
    chat.report_count = this.cards(chat.id).length;
    chat.updated_at = now;
    chat.last_message_at = now;
  }

  cancel(chatId: string, id: string): { readonly status: number; readonly run: Run } {
    const run = this.run(id);
    if (run.chat_id !== chatId) throw new TestApiError(404, "not_found", "Запрос не найден");
    if (run.state !== "running" && run.state !== "cancelling") return { status: 200, run };
    const accepted: Run = { ...run, state: "cancelling" };
    run.state = "cancelled";
    run.finished_at = this.now();
    this.messages.get(chatId)?.push({
      id: this.id(), request_id: id, role: "assistant", content: "Запрос отменён",
      reasoning: null, state: "cancelled", report_id: null, created_at: run.finished_at,
    });
    return { status: 202, run: accepted };
  }

  deleteChat(chatId: string): void {
    if (this.status(chatId).active_run !== null) {
      throw new TestApiError(409, "chat_busy", "Чат занят, дождитесь ответа");
    }
    for (const report of this.reports.values()) {
      if (report.chat_id !== chatId) continue;
      if (report.saved_at === null) this.reports.delete(report.id);
      else report.chat_id = null;
    }
    for (const run of this.runs.values()) {
      if (run.chat_id === chatId) {
        this.runs.delete(run.request_id);
        this.questions.delete(run.request_id);
      }
    }
    this.messages.delete(chatId);
    this.chats.delete(chatId);
  }

  seedFinished(options: SeedOptions = {}) {
    const chatId = this.createChat(options.title ?? "Результаты");
    const requestId = this.startRun(chatId, QUESTION);
    this.completeRun(requestId, {
      ...options, title: options.reportTitle ?? REPORT_TITLE,
    });
    const reportId = this.run(requestId).response?.report?.id ?? null;
    if (options.saved && reportId !== null) this.report(reportId).saved_at = this.now();
    return { chatId, requestId, reportId };
  }

  updateReport(id: string): Report {
    const report = this.report(id);
    if (report.chat_id !== null && this.status(report.chat_id).active_run !== null) {
      throw new TestApiError(409, "report_busy", "Отчёт занят, повторите позже");
    }
    if (this.updateFailure) {
      throw new TestApiError(502, "update_failed", "Не удалось обновить отчёт (RuntimeError)");
    }
    report.version += 1;
    report.generated_at = this.now();
    report.data = [{ название: "Первая строка", значение: 9876.54321 }];
    report.row_count = 1;
    return report;
  }
}
