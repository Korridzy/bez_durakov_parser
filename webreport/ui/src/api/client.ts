/**
 * Typed fetch wrapper over the backend API: one function per contract route.
 *
 * Every call carries a fresh 32-hex `X-Request-ID` (the backend binds it as the
 * request/trace id of its structured logs) and every non-2xx response or
 * transport failure is raised as an `ApiError`, so callers never touch `fetch`
 * or parse envelopes themselves.
 */

import { ApiError } from "./types";
import type {
  Chat,
  ChatDetail,
  ChatMessageBody,
  ChatPage,
  ChatResponse,
  ChatStatus,
  ClearResponse,
  HealthResponse,
  HistoryResponse,
  ListChatsParams,
  Report,
  ReportCard,
  Run,
  SendMessageBody,
} from "./types";

export const NETWORK_ERROR_MESSAGE = "Связь с сервером потеряна";
export const UNREADABLE_ERROR_MESSAGE = "Сервер временно недоступен";
const VALIDATION_ERROR_MESSAGE = "Проверьте заполненные поля";

export { ApiError };

export function newRequestId(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  // RFC 4122 v4 bits, hex without dashes: matches the backend's 32-hex trace id.
  bytes[6] = ((bytes[6] ?? 0) & 0x0f) | 0x40;
  bytes[8] = ((bytes[8] ?? 0) & 0x3f) | 0x80;
  return Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
}

type Method = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

interface RequestOptions {
  body?: unknown;
  signal?: AbortSignal;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function messageFromLegacyDetail(detail: unknown): string | null {
  if (typeof detail === "string") {
    return detail;
  }
  if (Array.isArray(detail)) {
    const first: unknown = detail[0];
    if (isRecord(first) && typeof first.msg === "string") {
      return first.msg.replace(/^Value error, /, "");
    }
    return VALIDATION_ERROR_MESSAGE;
  }
  return null;
}

function toApiError(status: number, body: unknown): ApiError {
  if (isRecord(body)) {
    const envelope = body.error;
    if (
      isRecord(envelope) &&
      typeof envelope.code === "string" &&
      typeof envelope.message === "string"
    ) {
      return new ApiError(status, envelope.code, envelope.message, body);
    }
    const detail = messageFromLegacyDetail(body.detail);
    if (detail !== null) {
      return new ApiError(status, `http_${status}`, detail, body);
    }
  }
  return new ApiError(
    status,
    `http_${status}`,
    UNREADABLE_ERROR_MESSAGE,
    body ?? null,
  );
}

/** `undefined` for an empty body, `null` for a body that is not JSON. */
async function readJson(response: Response): Promise<unknown> {
  const text = await response.text();
  if (text === "") {
    return undefined;
  }
  try {
    return JSON.parse(text) as unknown;
  } catch {
    return null;
  }
}

async function request<T>(
  method: Method,
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const headers = new Headers({
    Accept: "application/json",
    "X-Request-ID": newRequestId(),
  });
  const init: RequestInit = { method, headers };
  if (options.body !== undefined) {
    headers.set("Content-Type", "application/json");
    init.body = JSON.stringify(options.body);
  }
  if (options.signal !== undefined) {
    init.signal = options.signal;
  }

  // Reading the body is part of the transport: a connection dropped after the
  // headers rejects here too, and must map to the same network ApiError.
  let response: Response;
  let body: unknown;
  try {
    response = await fetch(path, init);
    body = await readJson(response);
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }
    throw new ApiError(0, "network", NETWORK_ERROR_MESSAGE);
  }

  if (!response.ok) {
    throw toApiError(response.status, body);
  }
  return body as T;
}

function query(params: object): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params) as [string, unknown][]) {
    if (value !== undefined) {
      search.set(key, String(value));
    }
  }
  const encoded = search.toString();
  return encoded === "" ? "" : `?${encoded}`;
}

const chatPath = (chatId: string) => `/api/chats/${encodeURIComponent(chatId)}`;
const reportPath = (reportId: string) =>
  `/api/reports/${encodeURIComponent(reportId)}`;

/* Chats */

export const createChat = (body: { title?: string } = {}) =>
  request<Chat>("POST", "/api/chats", { body });

export const listChats = (params: ListChatsParams = {}) =>
  request<ChatPage>("GET", `/api/chats${query(params)}`);

export const getChat = (chatId: string) =>
  request<ChatDetail>("GET", chatPath(chatId));

export const renameChat = (chatId: string, title: string) =>
  request<Chat>("PATCH", chatPath(chatId), { body: { title } });

export const deleteChat = (chatId: string) =>
  request<void>("DELETE", chatPath(chatId));

export const sendMessage = (chatId: string, body: SendMessageBody) =>
  request<Run>("POST", `${chatPath(chatId)}/messages`, { body });

export const getChatStatus = (chatId: string, signal?: AbortSignal) =>
  request<ChatStatus>(
    "GET",
    `${chatPath(chatId)}/status`,
    signal === undefined ? {} : { signal },
  );

export const cancelRun = (chatId: string, requestId: string) =>
  request<Run>("POST", `${chatPath(chatId)}/cancel`, {
    body: { request_id: requestId },
  });

export const getRun = (requestId: string) =>
  request<Run>("GET", `/api/runs/${encodeURIComponent(requestId)}`);

/* Reports */

export const listChatReports = (chatId: string) =>
  request<ReportCard[]>("GET", `${chatPath(chatId)}/reports`);

export const getReport = (reportId: string) =>
  request<Report>("GET", reportPath(reportId));

export const saveReport = (reportId: string) =>
  request<ReportCard>("PUT", `${reportPath(reportId)}/saved`, { body: {} });

export const unsaveReport = (reportId: string) =>
  request<void>("DELETE", `${reportPath(reportId)}/saved`);

export const listSavedReports = () =>
  request<ReportCard[]>("GET", "/api/saved-reports");

export const updateReport = (reportId: string) =>
  request<Report>("POST", `${reportPath(reportId)}/update`, { body: {} });

/* Legacy routes and health */

export const chat = (body: ChatMessageBody) =>
  request<ChatResponse>("POST", "/api/chat", { body });

export const getHistory = (sessionId: string) =>
  request<HistoryResponse>(
    "GET",
    `/api/history/${encodeURIComponent(sessionId)}`,
  );

export const clearSession = (sessionId: string) =>
  request<ClearResponse>(
    "POST",
    `/api/clear/${encodeURIComponent(sessionId)}`,
  );

export const getHealth = () => request<HealthResponse>("GET", "/health");
