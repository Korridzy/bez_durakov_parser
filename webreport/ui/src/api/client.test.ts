import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "./client";
import { ApiError as ClientApiError } from "./client";
import { ApiError } from "./types";
import type { Chat, Report, ReportCard, Run } from "./types";

const fetchMock = vi.fn<typeof fetch>();

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function brokenBodyResponse(status: number): Response {
  const stream = new ReadableStream({
    start(controller) {
      controller.error(new TypeError("socket reset"));
    },
  });
  return new Response(stream, {
    status,
    headers: { "content-type": "application/json" },
  });
}

function requestOf(call: number): { url: string; init: RequestInit } {
  const [input, init] = fetchMock.mock.calls[call] ?? [];
  return { url: String(input), init: init ?? {} };
}

function headerOf(init: RequestInit, name: string): string | null {
  return new Headers(init.headers).get(name);
}

const chat: Chat = {
  id: "c1",
  title: "Первый вопрос",
  auto_title: true,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  last_message_at: null,
  report_count: 0,
};

const card: ReportCard = {
  id: "r1",
  chat_id: "c1",
  title: "Сводка",
  question: "покажи сводку",
  tool: "summary",
  args: { limit: 10 },
  generated_at: "2026-01-01T00:00:00Z",
  version: 1,
  saved_at: null,
  row_count: 2,
  created_at: "2026-01-01T00:00:00Z",
};

const report: Report = { ...card, data: [{ a: 1 }, { a: 2 }] };

const run: Run = {
  request_id: "0123456789abcdef0123456789abcdef",
  chat_id: "c1",
  state: "running",
  created_at: "2026-01-01T00:00:00Z",
  finished_at: null,
  error: null,
  response: null,
};

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  fetchMock.mockReset();
  vi.unstubAllGlobals();
});

describe("success path", () => {
  it("parses the JSON body of a 200 response", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(200, chat));

    const result = await api.getChat("c1");

    expect(result).toEqual(chat);
    const { url, init } = requestOf(0);
    expect(url).toBe("/api/chats/c1");
    expect(init.method).toBe("GET");
  });

  it("serialises a JSON request body with the content type", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(201, chat));

    await api.createChat({ title: "Новый" });

    const { url, init } = requestOf(0);
    expect(url).toBe("/api/chats");
    expect(init.method).toBe("POST");
    expect(init.body).toBe(JSON.stringify({ title: "Новый" }));
    expect(headerOf(init, "content-type")).toBe("application/json");
  });

  it("builds the chat list query string from the given parameters only", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(200, { items: [chat], next_cursor: null }),
    );

    const page = await api.listChats({ q: "первый вопрос", limit: 20 });

    expect(page.items).toEqual([chat]);
    expect(requestOf(0).url).toBe(
      "/api/chats?q=%D0%BF%D0%B5%D1%80%D0%B2%D1%8B%D0%B9+%D0%B2%D0%BE%D0%BF%D1%80%D0%BE%D1%81&limit=20",
    );
  });

  it("resolves an empty 204 response without parsing", async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 204 }));

    await expect(api.deleteChat("c1")).resolves.toBeUndefined();
    expect(requestOf(0).init.method).toBe("DELETE");
  });

  it("returns the accepted run of a sent message", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(202, run));

    const result = await api.sendMessage("c1", {
      request_id: run.request_id,
      message: "покажи сводку",
    });

    expect(result).toEqual(run);
    expect(requestOf(0).url).toBe("/api/chats/c1/messages");
  });
});

describe("error envelope", () => {
  it("maps a 409 envelope to ApiError with the contract code", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(409, {
        error: { code: "chat_busy", message: "Чат занят, дождитесь ответа" },
      }),
    );

    const failure = await api.sendMessage("c1", {
      request_id: run.request_id,
      message: "ещё",
    }).catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(ApiError);
    const apiError = failure as ApiError;
    expect(apiError.status).toBe(409);
    expect(apiError.code).toBe("chat_busy");
    expect(apiError.message).toBe("Чат занят, дождитесь ответа");
  });

  it("keeps the unchanged report of a 502 update_failed body", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(502, {
        error: { code: "update_failed", message: "Не удалось обновить: ToolError" },
        report,
      }),
    );

    const failure = await api.updateReport("r1").catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(ApiError);
    const apiError = failure as ApiError;
    expect(apiError.status).toBe(502);
    expect(apiError.code).toBe("update_failed");
    expect((apiError.body as { report: Report }).report).toEqual(report);
  });

  it("maps a legacy detail body to a status code", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(409, { detail: "Чат занят, дождитесь ответа" }),
    );

    const failure = await api.clearSession("s1").catch((error: unknown) => error);

    const apiError = failure as ApiError;
    expect(apiError.status).toBe(409);
    expect(apiError.code).toBe("http_409");
    expect(apiError.message).toBe("Чат занят, дождитесь ответа");
  });

  it("uses the first message of a FastAPI validation body", async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse(422, {
        detail: [{ loc: ["body", "title"], msg: "Value error, слишком длинно", type: "value_error" }],
      }),
    );

    const failure = await api.renameChat("c1", "x").catch((error: unknown) => error);

    const apiError = failure as ApiError;
    expect(apiError.status).toBe(422);
    expect(apiError.code).toBe("http_422");
    expect(apiError.message).toBe("слишком длинно");
  });
});

describe("malformed and failed transports", () => {
  it("maps a network failure to ApiError with status 0", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));

    const failure = await api.listSavedReports().catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(ApiError);
    const apiError = failure as ApiError;
    expect(apiError.status).toBe(0);
    expect(apiError.code).toBe("network");
    expect(apiError.message.length).toBeGreaterThan(0);
  });

  it("maps a 502 HTML body to ApiError without a parse error", async () => {
    fetchMock.mockResolvedValueOnce(
      new Response("<html><body>502 Bad Gateway</body></html>", {
        status: 502,
        headers: { "content-type": "text/html" },
      }),
    );

    const failure = await api.getReport("r1").catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(ApiError);
    const apiError = failure as ApiError;
    expect(apiError.status).toBe(502);
    expect(apiError.code).toBe("http_502");
    expect(apiError.body).toBeNull();
  });

  it("maps an empty 500 body to ApiError", async () => {
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 500 }));

    const failure = await api.getRun(run.request_id).catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(ApiError);
    const apiError = failure as ApiError;
    expect(apiError.status).toBe(500);
    expect(apiError.code).toBe("http_500");
    expect(apiError.body).toBeNull();
  });

  it("maps a body read failure on a 200 response to a network ApiError", async () => {
    fetchMock.mockResolvedValueOnce(brokenBodyResponse(200));

    const failure = await api.getReport("r1").catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(ApiError);
    const apiError = failure as ApiError;
    expect(apiError.status).toBe(0);
    expect(apiError.code).toBe("network");
  });

  it("maps a body read failure on a 502 response to a network ApiError", async () => {
    fetchMock.mockResolvedValueOnce(brokenBodyResponse(502));

    const failure = await api.getReport("r1").catch((error: unknown) => error);

    expect(failure).toBeInstanceOf(ApiError);
    const apiError = failure as ApiError;
    expect(apiError.status).toBe(0);
    expect(apiError.code).toBe("network");
  });

  it("re-throws an AbortError untouched", async () => {
    const abort = new DOMException("aborted", "AbortError");
    fetchMock.mockRejectedValueOnce(abort);

    await expect(api.getChatStatus("c1")).rejects.toBe(abort);
  });
});

describe("contract types", () => {
  it("exports the same ApiError from types.ts and client.ts", () => {
    expect(ClientApiError).toBe(ApiError);
    const error = new ApiError(409, "chat_busy", "Чат занят");
    expect(error).toBeInstanceOf(Error);
    expect(error.name).toBe("ApiError");
  });
});

describe("request correlation", () => {
  it("sends a fresh 32-hex X-Request-ID with every call", async () => {
    fetchMock.mockImplementation(() => Promise.resolve(jsonResponse(200, [])));

    await api.listChatReports("c1");
    await api.listSavedReports();
    await api.getHealth();

    const ids = fetchMock.mock.calls.map(([, init]) =>
      headerOf(init ?? {}, "x-request-id"),
    );
    expect(ids).toHaveLength(3);
    for (const id of ids) {
      expect(id).toMatch(/^[0-9a-f]{32}$/);
    }
    expect(new Set(ids).size).toBe(3);
  });
});
