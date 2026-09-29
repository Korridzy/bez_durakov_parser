/**
 * TypeScript mirror of the backend API contract (`## Scope > API contract`).
 *
 * Every shape is a plain JSON object exactly as the backend serialises it;
 * timestamps are ISO-8601 UTC strings ending with `Z`, ids are 32 hex chars.
 */

export type RunState =
  | "running"
  | "cancelling"
  | "succeeded"
  | "failed"
  | "cancelled"
  | "interrupted";

export type MessageState = "succeeded" | "failed" | "cancelled" | "interrupted";

export type MessageRole = "user" | "assistant";

export interface Chat {
  id: string;
  title: string;
  auto_title: boolean;
  created_at: string;
  updated_at: string;
  last_message_at: string | null;
  report_count: number;
}

export interface Message {
  id: string;
  request_id: string;
  role: MessageRole;
  content: string;
  reasoning: string | null;
  /** `null` on user rows. */
  state: MessageState | null;
  report_id: string | null;
  created_at: string;
}

export interface ApiErrorInfo {
  code: string;
  message: string;
}

/** The error envelope every new route returns for non-2xx responses. */
export interface ApiErrorEnvelope {
  error: ApiErrorInfo;
}

/** A 502 `update_failed` body carries the unchanged report next to the error. */
export interface UpdateFailedEnvelope extends ApiErrorEnvelope {
  report: Report;
}

/**
 * The one error the API client raises: a non-2xx response mapped from its
 * envelope (`status` = HTTP status, `code` = contract code or `http_<status>`)
 * or a transport failure (`status` 0, `code` "network").
 */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  /** The parsed JSON body when the server sent one, otherwise `null`. */
  readonly body: unknown;

  constructor(status: number, code: string, message: string, body: unknown = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.body = body;
  }
}

export interface ReportCard {
  id: string;
  /** `null` once the originating chat was deleted («Чат удалён»). */
  chat_id: string | null;
  title: string;
  question: string;
  tool: string;
  args: Record<string, unknown>;
  generated_at: string;
  version: number;
  saved_at: string | null;
  row_count: number | null;
  created_at: string;
}

export interface Report extends ReportCard {
  /** Exactly what the tool returned; a list of row objects for tabular tools. */
  data: unknown;
}

/** The legacy `/api/chat` envelope plus the optional retained report card. */
export interface ChatResponse {
  success: boolean;
  session_id: string;
  data: unknown;
  query_info: Record<string, unknown>[];
  message: string;
  timestamp: string;
  error: string | null;
  reasoning: string | null;
  scope_verdict: string | null;
  report: ReportCard | null;
}

export interface Run {
  request_id: string;
  chat_id: string;
  state: RunState;
  created_at: string;
  finished_at: string | null;
  error: ApiErrorInfo | null;
  /** Set only for `succeeded` / `failed`; `data` is always `null` over HTTP. */
  response: ChatResponse | null;
}

export interface ChatPage {
  items: Chat[];
  next_cursor: string | null;
}

export interface ChatDetail {
  chat: Chat;
  messages: Message[];
  reports: ReportCard[];
  active_run: Run | null;
  last_run: Run | null;
}

export interface ChatStatus {
  active_run: Run | null;
  last_run: Run | null;
}

export interface ListChatsParams {
  q?: string;
  limit?: number;
  cursor?: string;
}

export interface SendMessageBody {
  request_id: string;
  message: string;
}

/* Legacy routes (unchanged contracts). */

export interface ChatMessageBody {
  message: string;
  session_id?: string;
}

export interface HistoryEntry {
  role: MessageRole;
  content: string;
  reasoning?: string | null;
}

export interface HistoryResponse {
  session_id?: string;
  history: HistoryEntry[];
}

export interface ClearResponse {
  success: boolean;
  message: string;
}

export interface HealthResponse {
  status: string;
  timestamp: string;
  services: {
    database: boolean;
    agents: boolean;
    llm_proxy: boolean;
  };
}
