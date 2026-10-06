import type { Page, Request, Route } from "@playwright/test";
import { reportCard, TestApiError, TestApiState } from "./stubState";
import { TestRequestValidationError, testQueryLimit, testRequestBody } from "./testRequestValidation";

const LOOPBACK_HOSTS = new Set(["127.0.0.1", "localhost", "[::1]"]);

function loopback(url: string): boolean {
  return LOOPBACK_HOSTS.has(new URL(url).hostname);
}

function requestId(value: unknown): string {
  if (typeof value !== "string" || !/^[0-9a-f]{32}$/.test(value)) {
    throw new TestApiError(422, "invalid_request", "Неверный request_id");
  }
  return value;
}

function title(value: unknown): string {
  if (typeof value !== "string") {
    throw new TestApiError(422, "invalid_request", "Некорректный запрос");
  }
  const collapsed = value.replace(/\s+/g, " ").trim();
  if ([...collapsed].length < 1 || [...collapsed].length > 80) {
    throw new TestApiError(422, "invalid_request", "Название должно содержать от 1 до 80 символов");
  }
  return collapsed;
}

function normalize(text: string): string {
  return text.normalize("NFKC").toLocaleLowerCase("ru-RU");
}

/** In-page HTTP fixture. API state survives reload; each test gets a new instance. */
export class TestApiStub extends TestApiState {
  readonly externalRequests: string[] = [];
  readonly guardRequests: string[] = [];
  readonly unhandledRequests: string[] = [];
  readonly requests: { readonly method: string; readonly path: string;
    readonly body: Record<string, unknown> | null }[] = [];
  private readonly disconnects: string[] = [];
  private guardMode: "abort" | "fallback" | "off" = "abort";

  constructor(private readonly page: Page) {
    super();
  }

  private readonly observe = (request: Request): void => {
    if (!loopback(request.url())) this.externalRequests.push(request.url());
  };

  private readonly guard = async (route: Route): Promise<void> => {
    if (loopback(route.request().url())) await route.fallback();
    else {
      this.guardRequests.push(route.request().url());
      if (this.guardMode === "fallback") await route.fallback();
      else await route.abort("blockedbyclient");
    }
  };

  async install(options: { readonly guard?: "abort" | "fallback" | "off" } = {}): Promise<void> {
    this.guardMode = options.guard ?? "abort";
    this.page.on("request", this.observe);
    if (this.guardMode !== "off") await this.page.route("**/*", this.guard);
    // Newest route wins: non-loopback API hosts must fall back to the guard.
    await this.page.route("**/api/**", this.handle);
  }

  async dispose(): Promise<void> {
    await this.page.unrouteAll({ behavior: "wait" });
    this.page.off("request", this.observe);
  }

  disconnectNext(method: string, path: string): void {
    this.disconnects.push(`${method} ${path}`);
  }

  private readonly handle = async (route: Route): Promise<void> => {
    const request = route.request();
    // Do not let the more-specific, later API route bypass the egress guard.
    if (!loopback(request.url())) {
      await route.fallback();
      return;
    }
    const url = new URL(request.url());
    const method = request.method();
    const path = url.pathname;
    try {
      const payload = method === "GET" || method === "DELETE" ? null : testRequestBody(request);
      this.requests.push({ method, path, body: payload });
      const disconnect = this.disconnects.indexOf(`${method} ${path}`);
      if (disconnect >= 0) {
        this.disconnects.splice(disconnect, 1);
        await route.abort("connectionreset");
        return;
      }
      const reply = this.dispatch(method, url, payload ?? {});
      await route.fulfill(reply.status === 204
        ? { status: 204 }
        : { status: reply.status, json: reply.json });
    } catch (error) {
      if (error instanceof TestRequestValidationError) {
        await route.fulfill({ status: 422, json: { detail: error.detail } });
        return;
      }
      if (!(error instanceof TestApiError)) throw error;
      const reportId = path.split("/")[3];
      const report = error.code === "update_failed" && reportId !== undefined
        ? this.report(reportId) : undefined;
      await route.fulfill({
        status: error.status,
        json: { error: { code: error.code, message: error.message }, ...(report ? { report } : {}) },
      });
    }
  };

  private dispatch(method: string, url: URL, payload: Record<string, unknown>): {
    readonly status: number; readonly json?: unknown;
  } {
    const path = url.pathname;
    if (path === "/api/chats") {
      switch (method) {
        case "POST": {
          const id = this.createChat(payload.title == null ? undefined : title(payload.title));
          return { status: 201, json: this.chat(id) };
        }
        case "GET": {
          const limit = testQueryLimit(url.searchParams.get("limit"));
          const query = normalize(url.searchParams.get("q") ?? "");
          const items = [...this.chats.values()].filter((chat) => normalize(
            [chat.title, ...(this.messages.get(chat.id) ?? []).map((item) => item.content)].join("\n"),
          ).includes(query)).sort((a, b) =>
            b.updated_at.localeCompare(a.updated_at) || b.id.localeCompare(a.id),
          );
          const cursor = url.searchParams.get("cursor");
          const start = cursor === null ? 0 : items.findIndex((item) => item.id === cursor) + 1;
          const page = items.slice(start, start + limit).map((chat) => ({
            ...chat, report_count: this.cards(chat.id).length,
          }));
          return { status: 200, json: {
            items: page, next_cursor: start + limit < items.length ? page.at(-1)?.id : null,
          } };
        }
      }
    }
    if (method === "GET" && path === "/api/saved-reports") {
      return { status: 200, json: [...this.reports.values()].filter((report) => report.saved_at !== null)
        .sort((a, b) => (b.saved_at ?? "").localeCompare(a.saved_at ?? "")).map(reportCard) };
    }
    const [, , kind, id, action] = path.split("/");
    if (kind === "runs" && id !== undefined && method === "GET") {
      return { status: 200, json: this.run(id) };
    }
    if (kind === "chats" && id !== undefined) {
      this.chat(id);
      switch (`${method} ${action ?? ""}`) {
        case "GET ": return { status: 200, json: this.detail(id) };
        case "PATCH ": {
          const chat = this.chat(id);
          chat.title = title(payload.title);
          chat.auto_title = false;
          chat.updated_at = this.now();
          return { status: 200, json: chat };
        }
        case "DELETE ":
          this.deleteChat(id);
          return { status: 204 };
        case "GET status": return { status: 200, json: this.status(id) };
        case "GET reports": return { status: 200, json: this.cards(id) };
        case "POST messages": {
          if (typeof payload.message !== "string" || payload.message.trim() === "") {
            throw new TestApiError(422, "invalid_request", "Сообщение не должно быть пустым");
          }
          const runId = requestId(payload.request_id);
          const status = this.runs.has(runId) ? 200 : 202;
          this.startRun(id, payload.message, runId);
          return { status, json: this.run(runId) };
        }
        case "POST cancel": {
          const cancelled = this.cancel(id, requestId(payload.request_id));
          return { status: cancelled.status, json: cancelled.run };
        }
      }
    }
    if (kind === "reports" && id !== undefined) {
      const report = this.report(id);
      switch (`${method} ${action ?? ""}`) {
        case "GET ": return { status: 200, json: report };
        case "PUT saved":
          report.saved_at ??= this.now();
          return { status: 200, json: reportCard(report) };
        case "DELETE saved":
          report.saved_at = null;
          return { status: 204 };
        case "POST update": return { status: 200, json: this.updateReport(id) };
      }
    }
    this.unhandledRequests.push(`${method} ${path}`);
    throw new TestApiError(404, "not_found", "Не найдено");
  }
}
