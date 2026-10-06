import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  Link,
  MemoryRouter,
  Route,
  Routes,
  useLocation,
  useParams,
} from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/types";
import type {
  Chat,
  ChatDetail,
  ChatStatus,
  Message,
  ReportCard,
  Run,
} from "../api/types";
import { ChatView, CHAT_NOT_FOUND_TEXT, CONNECTION_RETRY_TEXT } from "./ChatView";
import { PENDING_STORAGE_KEY } from "./pending";
import { POLL_BACKOFF_MS, POLL_INTERVAL_MS } from "./useRunPolling";

vi.mock("../api/client", async () => {
  const actual =
    await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ...actual,
    getChat: vi.fn(),
    createChat: vi.fn(),
    sendMessage: vi.fn(),
    getChatStatus: vi.fn(),
    cancelRun: vi.fn(),
  };
});

// The real panel has its own suite; here it only reports what the context holds,
// so the chips and the highlight plumbing of the conversation can be asserted.
vi.mock("../reports/ReportsPanel", async () => {
  const { useReports } =
    await vi.importActual<typeof import("../reports/ReportsContext")>(
      "../reports/ReportsContext",
    );
  const ReportsPanel = () => {
    const reports = useReports();
    return (
      <div>
        <span data-testid="open-report">{reports.openReportId ?? ""}</span>
        <span data-testid="highlight">{reports.highlightId ?? ""}</span>
        <span data-testid="panel-chat">{reports.chatId ?? ""}</span>
      </div>
    );
  };
  return { ReportsPanel };
});

import * as client from "../api/client";

const getChat = vi.mocked(client.getChat);
const createChat = vi.mocked(client.createChat);
const sendMessage = vi.mocked(client.sendMessage);
const getChatStatus = vi.mocked(client.getChatStatus);
const cancelRun = vi.mocked(client.cancelRun);

const HEX32 = /^[0-9a-f]{32}$/;
const REQ_OLD = "a".repeat(32);
const REQ_ACTIVE = "b".repeat(32);
const REQ_PENDING = "c".repeat(32);

function chat(over: Partial<Chat> & { id: string }): Chat {
  return {
    title: `Чат ${over.id}`,
    auto_title: true,
    created_at: "2026-09-28T10:00:00Z",
    updated_at: "2026-09-29T11:55:00Z",
    last_message_at: "2026-09-29T11:55:00Z",
    report_count: 0,
    ...over,
  };
}

function message(over: Partial<Message> & { id: string; role: Message["role"] }): Message {
  return {
    request_id: REQ_OLD,
    content: "",
    reasoning: null,
    state: over.role === "user" ? null : "succeeded",
    report_id: null,
    created_at: "2026-09-29T11:55:00Z",
    ...over,
  };
}

function card(over: Partial<ReportCard> & { id: string }): ReportCard {
  return {
    chat_id: "c1",
    title: `Отчёт ${over.id}`,
    question: "Сколько игр?",
    tool: "read_rows",
    args: { table: "games" },
    generated_at: "2026-09-29T11:55:00Z",
    version: 1,
    saved_at: null,
    row_count: 2,
    created_at: "2026-09-29T11:55:00Z",
    ...over,
  };
}

function run(over: Partial<Run> & { request_id: string }): Run {
  return {
    chat_id: "c1",
    state: "running",
    created_at: "2026-09-29T11:59:00Z",
    finished_at: null,
    error: null,
    response: null,
    ...over,
  };
}

function succeededRun(requestId: string, report: ReportCard | null = null): Run {
  return run({
    request_id: requestId,
    state: "succeeded",
    finished_at: "2026-09-29T11:59:30Z",
    response: {
      success: true,
      session_id: "c1",
      data: null,
      query_info: [],
      message: "Готово",
      timestamp: "2026-09-29T11:59:30Z",
      error: null,
      reasoning: null,
      scope_verdict: null,
      report,
    },
  });
}

function detail(over: Partial<ChatDetail> = {}): ChatDetail {
  return {
    chat: chat({ id: "c1", title: "Игры за сезон" }),
    messages: [],
    reports: [],
    active_run: null,
    last_run: null,
    ...over,
  };
}

const historyMessages: Message[] = [
  message({ id: "m1", role: "user", content: "Сколько игр за сезон?" }),
  message({
    id: "m2",
    role: "assistant",
    content: "**Всего** 12 игр",
    reasoning: "Считаю строки таблицы игр",
    report_id: "r1",
  }),
];

function status(active: Run | null, last: Run | null = null): ChatStatus {
  return { active_run: active, last_run: last };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

/**
 * Flush resolved promises and the React updates they queued (fake timers stay
 * put). Several act rounds: effects committed by one round may start promises
 * whose results only settle in the next.
 */
async function settle() {
  for (let round = 0; round < 5; round += 1) {
    await act(async () => {
      for (let i = 0; i < 4; i += 1) {
        await Promise.resolve();
      }
    });
  }
}

async function advance(ms: number) {
  await act(async () => {
    vi.advanceTimersByTime(ms);
  });
  await settle();
}

const onChatsChanged = vi.fn();

function Harness() {
  const { chatId } = useParams();
  const location = useLocation();
  return (
    <>
      <ChatView chatId={chatId} onChatsChanged={onChatsChanged} />
      <span data-testid="path">{location.pathname}</span>
      <Link to="/chats/c2">Перейти к c2</Link>
      <Link to="/chats/c1">Перейти к c1</Link>
    </>
  );
}

function renderView(path = "/chats/c1") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/chats" element={<Harness />} />
        <Route path="/chats/:chatId" element={<Harness />} />
      </Routes>
    </MemoryRouter>,
  );
}

const pathShown = () => screen.getByTestId("path").textContent;
/** The stored pending list (`null` when the key is absent). */
const storedPending = () => {
  const raw = sessionStorage.getItem(PENDING_STORAGE_KEY);
  return raw === null ? null : (JSON.parse(raw) as unknown);
};
const entry = (chatId: string, request_id: string, message: string) => ({ chatId, request_id, message });
const composer = () => screen.getByRole("textbox", { name: "Сообщение" });

function setup() {
  return userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
}

async function typeAndSend(text: string) {
  const user = setup();
  await user.type(composer(), text);
  await user.keyboard("{Enter}");
  await settle();
  return user;
}

beforeEach(() => {
  vi.useFakeTimers();
  // Testing Library's async wrapper only advances fake timers when it sees a
  // `jest` global; the shim keeps user-event and `act` from waiting forever.
  (globalThis as { jest?: unknown }).jest = {
    advanceTimersByTime: (ms: number) => vi.advanceTimersByTime(ms),
  };
  sessionStorage.clear();
  onChatsChanged.mockReset();
  getChat.mockReset();
  createChat.mockReset();
  sendMessage.mockReset();
  getChatStatus.mockReset();
  cancelRun.mockReset();
  getChat.mockResolvedValue(detail({ messages: historyMessages, reports: [card({ id: "r1", title: "Игры за сезон" })] }));
  sendMessage.mockImplementation((chatId, body) =>
    Promise.resolve(run({ request_id: body.request_id, chat_id: chatId })),
  );
  getChatStatus.mockResolvedValue(status(null));
});

afterEach(() => {
  delete (globalThis as { jest?: unknown }).jest;
  vi.useRealTimers();
});

describe("ChatView history", () => {
  it("exposes an answer table as a named keyboard-focusable region", async () => {
    getChat.mockResolvedValue(detail({
      messages: [message({
        id: "m-table",
        role: "assistant",
        content: "| Команда | Игр |\n| --- | ---: |\n| Первая | 130 |",
      })],
    }));
    renderView();
    await settle();

    const table = within(screen.getByRole("log")).getByRole("table");
    const region = table.parentElement;
    expect(region).toHaveAttribute("role", "region");
    expect(region).toHaveAttribute("tabindex", "0");
    expect(region).toHaveAttribute("aria-label", expect.stringMatching(/\S/));
    expect(region).toHaveAccessibleName();
    expect(region?.parentElement?.closest(
      'button, a[href], input, select, textarea, summary, [tabindex], [role="button"], [role="link"]',
    )).toBeNull();
    expect(within(table).getAllByRole("columnheader").map((cell) => cell.textContent))
      .toEqual(["Команда", "Игр"]);
    expect(within(table).getAllByRole("cell").map((cell) => cell.textContent))
      .toEqual(["Первая", "130"]);
  });

  it("renders the history with a collapsed reasoning expander above the answer and a report chip", async () => {
    renderView();
    await settle();

    expect(getChat).toHaveBeenCalledWith("c1");
    expect(screen.getByText("Сколько игр за сезон?")).toBeInTheDocument();
    const bold = screen.getByText("Всего");
    expect(bold.tagName).toBe("STRONG");

    const summary = screen.getByText("Рассуждения");
    const details = summary.closest("details");
    expect(details).not.toBeNull();
    expect(details!.open).toBe(false);
    expect(within(details!).getByText("Считаю строки таблицы игр")).toBeInTheDocument();
    // The expander precedes the answer in document order.
    expect(details!.compareDocumentPosition(bold) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    expect(screen.getByRole("button", { name: "Отчёт: Игры за сезон" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Отправить" })).toBeInTheDocument();
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("shows no expander without reasoning, the partial label on a failed message, and the markers", async () => {
    getChat.mockResolvedValue(
      detail({
        messages: [
          message({ id: "m1", role: "assistant", content: "Ответ без рассуждений" }),
          message({
            id: "m2",
            role: "assistant",
            content: "Не удалось получить ответ",
            reasoning: "Начал считать",
            state: "failed",
          }),
          message({ id: "m3", role: "assistant", content: "Запрос отменён", state: "cancelled" }),
          message({
            id: "m4",
            role: "assistant",
            content: "Ответ прерван перезапуском сервера",
            reasoning: "Смотрел таблицу",
            state: "interrupted",
          }),
        ],
      }),
    );
    renderView();
    await settle();

    expect(screen.queryByText("Рассуждения")).toBeNull();
    const partials = screen.getAllByText("Рассуждения (неполные)");
    expect(partials).toHaveLength(2);
    expect(partials[0]!.closest("details")!.open).toBe(false);
    expect(screen.getByRole("alert")).toHaveTextContent("Не удалось получить ответ");
    const markers = screen.getAllByRole("status");
    expect(markers.map((node) => node.textContent)).toEqual([
      "Запрос отменён",
      "Ответ прерван перезапуском сервера",
    ]);
  });

  it("keeps raw HTML in answers inert", async () => {
    getChat.mockResolvedValue(
      detail({
        messages: [
          message({
            id: "m1",
            role: "assistant",
            content:
              'Ответ <script>window.__pwned = 1</script><img src="x" onerror="window.__pwned = 1"> и *курсив*',
          }),
        ],
      }),
    );
    const { container } = renderView();
    await settle();

    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img")).toBeNull();
    expect(screen.getByText("курсив").tagName).toBe("EM");
    expect(container.textContent).toContain("<script>");
    expect((window as { __pwned?: unknown }).__pwned).toBeUndefined();
  });

  it("opens a report through the reports context when its chip is clicked", async () => {
    const user = setup();
    renderView();
    await settle();

    expect(screen.getByTestId("panel-chat")).toHaveTextContent("c1");
    await user.click(screen.getByRole("button", { name: "Отчёт: Игры за сезон" }));
    expect(screen.getByTestId("open-report")).toHaveTextContent("r1");
  });

  it("shows «Чат не найден» with a link to the list when the chat does not exist", async () => {
    getChat.mockRejectedValue(new ApiError(404, "not_found", "Чат не найден"));
    renderView("/chats/gone");
    await settle();

    expect(screen.getByText(CHAT_NOT_FOUND_TEXT)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "К списку чатов" })).toHaveAttribute("href", "/chats");
    expect(screen.queryByRole("textbox", { name: "Сообщение" })).toBeNull();
  });
});

describe("ChatView composer and send", () => {
  it("sends a message: pending entry, POST with a 32-hex id, optimistic bubble, thinking mark, stop button", async () => {
    renderView();
    await settle();

    await typeAndSend("Какая команда набрала больше всего очков?");

    expect(sendMessage).toHaveBeenCalledTimes(1);
    const [chatId, body] = sendMessage.mock.calls[0]!;
    expect(chatId).toBe("c1");
    expect(body.request_id).toMatch(HEX32);
    expect(body.message).toBe("Какая команда набрала больше всего очков?");
    expect(storedPending()).toEqual([entry("c1", body.request_id, body.message)]);
    expect(screen.getByText("Какая команда набрала больше всего очков?")).toBeInTheDocument();
    expect(composer()).toHaveValue("");
    expect(screen.getByRole("status")).toHaveTextContent("Думаю…");
    expect(screen.getByRole("button", { name: "Остановить" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Отправить" })).toBeNull();
    expect(onChatsChanged).toHaveBeenCalled();
  });

  it("does not send empty or whitespace text and keeps Shift+Enter as a newline", async () => {
    renderView();
    await settle();
    const user = setup();

    expect(screen.getByRole("button", { name: "Отправить" })).toBeDisabled();
    await user.type(composer(), "   ");
    await user.keyboard("{Enter}");
    await settle();
    expect(sendMessage).not.toHaveBeenCalled();
    expect(storedPending()).toBeNull();

    await user.clear(composer());
    await user.type(composer(), "строка");
    await user.keyboard("{Shift>}{Enter}{/Shift}");
    await user.type(composer(), "две");
    expect(composer()).toHaveValue("строка\nдве");
    expect(sendMessage).not.toHaveBeenCalled();
  });

  it("polls the status every second and reloads the chat when the run settles", async () => {
    renderView();
    await settle();
    await typeAndSend("Сколько очков?");
    const requestId = sendMessage.mock.calls[0]![1].request_id;
    const reportCard = card({ id: "r2", title: "Очки команд" });
    getChatStatus
      .mockResolvedValueOnce(status(run({ request_id: requestId })))
      .mockResolvedValueOnce(status(null, succeededRun(requestId, reportCard)));
    getChat.mockResolvedValue(
      detail({
        messages: [
          ...historyMessages,
          message({ id: "m3", role: "user", request_id: requestId, content: "Сколько очков?" }),
          message({
            id: "m4",
            role: "assistant",
            request_id: requestId,
            content: "Больше всего очков у команды «Альфа»",
            reasoning: "Сортирую по очкам",
            report_id: "r2",
          }),
        ],
        reports: [card({ id: "r1", title: "Игры за сезон" }), reportCard],
        last_run: succeededRun(requestId, reportCard),
      }),
    );
    onChatsChanged.mockReset();

    await advance(POLL_INTERVAL_MS - 1);
    expect(getChatStatus).not.toHaveBeenCalled();
    await advance(1);
    expect(getChatStatus).toHaveBeenCalledTimes(1);
    expect(getChatStatus.mock.calls[0]![0]).toBe("c1");
    expect(screen.getByRole("status")).toHaveTextContent("Думаю…");

    await advance(POLL_INTERVAL_MS);
    expect(getChatStatus).toHaveBeenCalledTimes(2);
    expect(getChat).toHaveBeenCalledTimes(2);
    expect(screen.getByText("Больше всего очков у команды «Альфа»")).toBeInTheDocument();
    expect(screen.getAllByText("Сколько очков?")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "Отчёт: Очки команд" })).toBeInTheDocument();
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.getByRole("button", { name: "Отправить" })).toBeInTheDocument();
    expect(storedPending()).toBeNull();
    expect(screen.getByTestId("highlight")).toHaveTextContent("r2");
    expect(onChatsChanged).toHaveBeenCalled();

    await advance(POLL_INTERVAL_MS * 3);
    expect(getChatStatus).toHaveBeenCalledTimes(2);
  });

  it("drops the optimistic bubble on 409 chat_busy and shows the message", async () => {
    sendMessage.mockRejectedValue(
      new ApiError(409, "chat_busy", "Чат занят, дождитесь ответа"),
    );
    renderView();
    await settle();

    await typeAndSend("Ещё вопрос");

    // The bubble is gone; the refused question is back in the composer for a later resend.
    expect(screen.queryByText("Ещё вопрос", { selector: ".msg__bubble" })).toBeNull();
    expect(composer()).toHaveValue("Ещё вопрос");
    expect(screen.getByRole("alert")).toHaveTextContent("Чат занят, дождитесь ответа");
    expect(storedPending()).toBeNull();
    expect(screen.getByRole("button", { name: "Отправить" })).toBeInTheDocument();
  });

  it("keeps the pending entry on a network error and retries with the same request id", async () => {
    sendMessage.mockRejectedValueOnce(new ApiError(0, "network", "Связь с сервером потеряна"));
    renderView();
    await settle();

    const user = await typeAndSend("Вопрос без связи");

    expect(screen.getByText(CONNECTION_RETRY_TEXT)).toBeInTheDocument();
    expect(screen.getByText("Вопрос без связи")).toBeInTheDocument();
    const requestId = sendMessage.mock.calls[0]![1].request_id;
    expect(storedPending()).toEqual([entry("c1", requestId, "Вопрос без связи")]);
    expect(screen.queryByRole("status")).toBeNull();

    await user.click(screen.getByRole("button", { name: "Повторить" }));
    await settle();

    expect(sendMessage).toHaveBeenCalledTimes(2);
    expect(sendMessage.mock.calls[1]![1]).toEqual({ request_id: requestId, message: "Вопрос без связи" });
    expect(screen.queryByText(CONNECTION_RETRY_TEXT)).toBeNull();
    expect(screen.getByRole("status")).toHaveTextContent("Думаю…");
    expect(storedPending()).toEqual([entry("c1", requestId, "Вопрос без связи")]);
  });

  it("creates the chat lazily on /chats/new, replaces the URL and then submits", async () => {
    createChat.mockResolvedValue(chat({ id: "c9", title: "Новый чат", last_message_at: null }));
    getChat.mockResolvedValue(detail({ chat: chat({ id: "c9" }) }));
    renderView("/chats/new");
    await settle();

    expect(getChat).not.toHaveBeenCalled();
    expect(screen.getByTestId("panel-chat")).toHaveTextContent("");

    await typeAndSend("Первый вопрос");

    expect(createChat).toHaveBeenCalledTimes(1);
    expect(pathShown()).toBe("/chats/c9");
    expect(getChat).toHaveBeenCalledWith("c9");
    expect(sendMessage).toHaveBeenCalledTimes(1);
    const [chatId, body] = sendMessage.mock.calls[0]!;
    expect(chatId).toBe("c9");
    expect(body.request_id).toMatch(HEX32);
    expect(body.message).toBe("Первый вопрос");
    expect(storedPending()).toEqual([entry("c9", body.request_id, "Первый вопрос")]);
    expect(screen.getByText("Первый вопрос")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Думаю…");
    expect(screen.getByTestId("panel-chat")).toHaveTextContent("c9");
  });
});

describe("ChatView cancel", () => {
  it("cancels the active run from the stop button and shows «Отменяю…» until the marker arrives", async () => {
    const active = run({ request_id: REQ_ACTIVE });
    getChat.mockResolvedValue(
      detail({
        messages: [message({ id: "m1", role: "user", request_id: REQ_ACTIVE, content: "Долгий вопрос" })],
        active_run: active,
      }),
    );
    const cancelling = deferred<Run>();
    cancelRun.mockReturnValue(cancelling.promise);
    const user = setup();
    renderView();
    await settle();

    expect(screen.getByRole("status")).toHaveTextContent("Думаю…");
    await user.click(screen.getByRole("button", { name: "Остановить" }));
    expect(cancelRun).toHaveBeenCalledWith("c1", REQ_ACTIVE);
    expect(screen.getByRole("status")).toHaveTextContent("Отменяю…");

    cancelling.resolve(run({ request_id: REQ_ACTIVE, state: "cancelling" }));
    await settle();
    expect(screen.getByRole("status")).toHaveTextContent("Отменяю…");

    const cancelled = run({ request_id: REQ_ACTIVE, state: "cancelled", finished_at: "2026-09-29T12:00:00Z" });
    getChatStatus.mockResolvedValue(status(null, cancelled));
    getChat.mockResolvedValue(
      detail({
        messages: [
          message({ id: "m1", role: "user", request_id: REQ_ACTIVE, content: "Долгий вопрос" }),
          message({ id: "m2", role: "assistant", request_id: REQ_ACTIVE, content: "Запрос отменён", state: "cancelled" }),
        ],
        last_run: cancelled,
      }),
    );
    await advance(POLL_INTERVAL_MS);

    expect(screen.getByRole("status")).toHaveTextContent("Запрос отменён");
    expect(screen.getByRole("button", { name: "Отправить" })).toBeInTheDocument();
    expect(screen.getByTestId("highlight")).toHaveTextContent("");
  });
});

describe("ChatView reload recovery", () => {
  it("resubmits a pending entry the loaded chat does not contain, with the same request id", async () => {
    sessionStorage.setItem(
      PENDING_STORAGE_KEY,
      JSON.stringify([entry("c1", REQ_PENDING, "Потерянный вопрос")]),
    );
    renderView();
    await settle();

    expect(sendMessage).toHaveBeenCalledTimes(1);
    expect(sendMessage).toHaveBeenCalledWith("c1", { request_id: REQ_PENDING, message: "Потерянный вопрос" });
    expect(screen.getByText("Потерянный вопрос")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Думаю…");
    expect(storedPending()).not.toBeNull();
  });

  it("does not resubmit a pending entry that the chat already answered, and clears it", async () => {
    sessionStorage.setItem(
      PENDING_STORAGE_KEY,
      JSON.stringify([entry("c1", REQ_OLD, "Сколько игр за сезон?")]),
    );
    renderView();
    await settle();

    expect(sendMessage).not.toHaveBeenCalled();
    expect(storedPending()).toBeNull();
    expect(screen.getAllByText("Сколько игр за сезон?")).toHaveLength(1);
  });

  it("leaves a pending entry of another chat alone, drops a malformed request id and survives corrupt JSON", async () => {
    const other = entry("c2", REQ_PENDING, "Чужой вопрос");
    const malformed = entry("c1", "not-a-hex-id", "Кривой вопрос");
    sessionStorage.setItem(PENDING_STORAGE_KEY, JSON.stringify([other, malformed]));
    const first = renderView();
    await settle();

    expect(sendMessage).not.toHaveBeenCalled();
    expect(screen.queryByText("Кривой вопрос")).toBeNull();
    expect(storedPending()).toEqual([other]);
    expect(screen.queryByText("Чужой вопрос")).toBeNull();
    first.unmount();

    sessionStorage.setItem(PENDING_STORAGE_KEY, "{not json");
    renderView();
    await settle();

    expect(sendMessage).not.toHaveBeenCalled();
    expect(sessionStorage.getItem(PENDING_STORAGE_KEY)).toBeNull();
    expect(screen.getByText("Сколько игр за сезон?")).toBeInTheDocument();
  });

  it("starts polling immediately when the loaded chat has an active run", async () => {
    getChat.mockResolvedValue(
      detail({
        messages: [message({ id: "m1", role: "user", request_id: REQ_ACTIVE, content: "Идёт ответ" })],
        active_run: run({ request_id: REQ_ACTIVE }),
      }),
    );
    getChatStatus.mockResolvedValue(status(run({ request_id: REQ_ACTIVE })));
    renderView();
    await settle();

    expect(screen.getByRole("status")).toHaveTextContent("Думаю…");
    expect(screen.getByRole("button", { name: "Остановить" })).toBeInTheDocument();
    await advance(POLL_INTERVAL_MS);
    expect(getChatStatus).toHaveBeenCalledTimes(1);
    await advance(POLL_INTERVAL_MS);
    expect(getChatStatus).toHaveBeenCalledTimes(2);
  });

  it("backs off to 3 s after a network error while polling and returns to 1 s afterwards", async () => {
    getChat.mockResolvedValue(
      detail({
        messages: [message({ id: "m1", role: "user", request_id: REQ_ACTIVE, content: "Идёт ответ" })],
        active_run: run({ request_id: REQ_ACTIVE }),
      }),
    );
    getChatStatus
      .mockRejectedValueOnce(new ApiError(0, "network", "Связь с сервером потеряна"))
      .mockResolvedValue(status(run({ request_id: REQ_ACTIVE })));
    renderView();
    await settle();

    await advance(POLL_INTERVAL_MS);
    expect(getChatStatus).toHaveBeenCalledTimes(1);
    expect(screen.getByText(CONNECTION_RETRY_TEXT)).toBeInTheDocument();

    await advance(POLL_BACKOFF_MS - 1);
    expect(getChatStatus).toHaveBeenCalledTimes(1);
    await advance(1);
    expect(getChatStatus).toHaveBeenCalledTimes(2);
    expect(screen.queryByText(CONNECTION_RETRY_TEXT)).toBeNull();

    await advance(POLL_INTERVAL_MS);
    expect(getChatStatus).toHaveBeenCalledTimes(3);
    expect(screen.getByRole("status")).toHaveTextContent("Думаю…");
  });

  it("stops polling and shows «Чат не найден» when the status returns 404", async () => {
    getChat.mockResolvedValue(
      detail({
        messages: [message({ id: "m1", role: "user", request_id: REQ_ACTIVE, content: "Идёт ответ" })],
        active_run: run({ request_id: REQ_ACTIVE }),
      }),
    );
    getChatStatus.mockRejectedValue(new ApiError(404, "not_found", "Чат не найден"));
    renderView();
    await settle();

    await advance(POLL_INTERVAL_MS);
    expect(getChatStatus).toHaveBeenCalledTimes(1);
    expect(screen.getByText(CHAT_NOT_FOUND_TEXT)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "К списку чатов" })).toHaveAttribute("href", "/chats");

    await advance(POLL_BACKOFF_MS * 2);
    expect(getChatStatus).toHaveBeenCalledTimes(1);
  });
});

/* Interleavings of {POST, poll, cancel, refetch, chat switch, unmount, recovery, retry}. */

const activeDetail = (requestId = REQ_ACTIVE) =>
  detail({
    messages: [message({ id: "m1", role: "user", request_id: requestId, content: "Долгий вопрос" })],
    active_run: run({ request_id: requestId }),
  });

const cancelledDetail = (requestId = REQ_ACTIVE) => {
  const cancelled = run({ request_id: requestId, state: "cancelled", finished_at: "2026-09-29T12:00:00Z" });
  return detail({
    messages: [
      message({ id: "m1", role: "user", request_id: requestId, content: "Долгий вопрос" }),
      message({ id: "m2", role: "assistant", request_id: requestId, content: "Запрос отменён", state: "cancelled" }),
    ],
    last_run: cancelled,
  });
};

const answeredDetail = (requestId: string, question: string, answer: string) =>
  detail({
    messages: [
      ...historyMessages,
      message({ id: "m3", role: "user", request_id: requestId, content: question }),
      message({ id: "m4", role: "assistant", request_id: requestId, content: answer }),
    ],
    last_run: succeededRun(requestId),
  });

const stopButton = () => screen.queryByRole("button", { name: "Остановить" });
const sendButton = () => screen.queryByRole("button", { name: "Отправить" });

describe("ChatView interleavings", () => {
  it.each([
    { reply: "cancelling" as const, name: "a late non-terminal cancel reply" },
    { reply: "cancelled" as const, name: "a late terminal cancel reply" },
  ])("$name after the poll already settled the run never resurrects it and the next question works", async ({ reply }) => {
    getChat.mockResolvedValue(activeDetail());
    const cancelling = deferred<Run>();
    cancelRun.mockReturnValue(cancelling.promise);
    const user = setup();
    renderView();
    await settle();

    await user.click(stopButton()!);
    expect(cancelRun).toHaveBeenCalledWith("c1", REQ_ACTIVE);
    expect(screen.getByRole("status")).toHaveTextContent("Отменяю…");

    // The poll wins the race: the run is terminal and the transcript shows the marker.
    const last = cancelledDetail().last_run;
    getChatStatus.mockResolvedValue(status(null, last));
    getChat.mockResolvedValue(cancelledDetail());
    await advance(POLL_INTERVAL_MS);
    expect(screen.getByRole("status")).toHaveTextContent("Запрос отменён");
    expect(sendButton()).toBeInTheDocument();
    expect(stopButton()).toBeNull();
    const refetches = getChat.mock.calls.length;

    // Now the older cancel reply arrives.
    cancelling.resolve(run({ request_id: REQ_ACTIVE, state: reply, finished_at: reply === "cancelled" ? "2026-09-29T12:00:00Z" : null }));
    await settle();
    await advance(POLL_INTERVAL_MS);

    expect(stopButton()).toBeNull();
    expect(sendButton()).toBeInTheDocument();
    expect(screen.getAllByRole("status")).toHaveLength(1);
    expect(screen.getByRole("status")).toHaveTextContent("Запрос отменён");
    expect(getChat.mock.calls.length).toBe(refetches);

    await typeAndSend("Следующий вопрос");
    expect(sendMessage).toHaveBeenCalledTimes(1);
    expect(stopButton()).toBeInTheDocument();
  });

  it("refuses a second send while the first waits for a retry; «Отменить отправку» releases the composer and restores the text", async () => {
    sendMessage.mockRejectedValueOnce(new ApiError(0, "network", "Связь с сервером потеряна"));
    renderView();
    await settle();
    const user = await typeAndSend("первый вопрос");
    const firstId = sendMessage.mock.calls[0]![1].request_id;
    expect(screen.getByText(CONNECTION_RETRY_TEXT)).toBeInTheDocument();

    await user.type(composer(), "второй вопрос");
    expect(sendButton()).toBeDisabled();
    await user.keyboard("{Enter}");
    fireEvent.submit(composer().closest("form")!);
    await settle();

    expect(sendMessage).toHaveBeenCalledTimes(1);
    expect(storedPending()).toEqual([entry("c1", firstId, "первый вопрос")]);
    expect(screen.getByText("первый вопрос")).toBeInTheDocument();
    expect(composer()).toHaveValue("второй вопрос");

    await user.clear(composer());
    await user.click(screen.getByRole("button", { name: "Отменить отправку" }));
    await settle();

    expect(storedPending()).toBeNull();
    expect(screen.queryByText(CONNECTION_RETRY_TEXT)).toBeNull();
    expect(composer()).toHaveValue("первый вопрос");
    expect(sendButton()).toBeEnabled();

    await user.click(composer());
    await user.keyboard("{Enter}");
    await settle();
    expect(sendMessage).toHaveBeenCalledTimes(2);
    expect(sendMessage.mock.calls[1]![1].request_id).not.toBe(firstId);
  });

  it("resubmits on reload only this chat's stored entry and keeps the other chat's", async () => {
    const other = entry("c2", "9".repeat(32), "Чужой вопрос");
    sessionStorage.setItem(PENDING_STORAGE_KEY, JSON.stringify([other, entry("c1", REQ_PENDING, "Мой вопрос")]));
    renderView();
    await settle();

    expect(sendMessage).toHaveBeenCalledTimes(1);
    expect(sendMessage).toHaveBeenCalledWith("c1", { request_id: REQ_PENDING, message: "Мой вопрос" });
    expect(storedPending()).toEqual([other, entry("c1", REQ_PENDING, "Мой вопрос")]);

    getChatStatus.mockResolvedValue(status(null, succeededRun(REQ_PENDING)));
    getChat.mockResolvedValue(answeredDetail(REQ_PENDING, "Мой вопрос", "Ответ"));
    await advance(POLL_INTERVAL_MS);

    expect(screen.getByText("Ответ")).toBeInTheDocument();
    expect(storedPending()).toEqual([other]);
  });

  it("ignores a late POST reply after a chat switch and keeps the old chat's entry stored", async () => {
    const posting = deferred<Run>();
    sendMessage.mockReturnValue(posting.promise);
    getChat.mockImplementation((chatId) =>
      Promise.resolve(detail({ chat: chat({ id: chatId }), messages: chatId === "c1" ? historyMessages : [] })),
    );
    renderView();
    await settle();
    const user = await typeAndSend("Вопрос в c1");
    const requestId = sendMessage.mock.calls[0]![1].request_id;

    await user.click(screen.getByRole("link", { name: "Перейти к c2" }));
    await settle();
    expect(pathShown()).toBe("/chats/c2");
    expect(screen.queryByText("Вопрос в c1")).toBeNull();

    posting.resolve(run({ request_id: requestId, chat_id: "c1" }));
    await settle();
    await advance(POLL_INTERVAL_MS);

    expect(screen.queryByRole("status")).toBeNull();
    expect(stopButton()).toBeNull();
    expect(getChatStatus).not.toHaveBeenCalled();
    expect(storedPending()).toEqual([entry("c1", requestId, "Вопрос в c1")]);
  });

  it("ignores a late poll reply after a chat switch and after unmount", async () => {
    getChat.mockImplementation((chatId) =>
      Promise.resolve(chatId === "c1" ? activeDetail() : detail({ chat: chat({ id: "c2" }) })),
    );
    const polling = deferred<ChatStatus>();
    getChatStatus.mockReturnValue(polling.promise);
    const user = setup();
    const view = renderView();
    await settle();
    await advance(POLL_INTERVAL_MS);
    expect(getChatStatus).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("link", { name: "Перейти к c2" }));
    await settle();
    polling.resolve(status(run({ request_id: REQ_ACTIVE, chat_id: "c1", state: "cancelling" })));
    await settle();
    await advance(POLL_BACKOFF_MS);

    expect(screen.queryByRole("status")).toBeNull();
    expect(stopButton()).toBeNull();
    expect(getChatStatus).toHaveBeenCalledTimes(1);
    expect(getChat).toHaveBeenCalledTimes(2); // c1 load, c2 load - no refetch from the stale poll.
    view.unmount();
  });

  it("applies only the latest load after c1 -> c2 -> c1: the stale first reply of c1 is ignored", async () => {
    const staleFirst = deferred<ChatDetail>();
    let c1Loads = 0;
    getChat.mockImplementation((chatId) => {
      if (chatId !== "c1") {
        return Promise.resolve(detail({ chat: chat({ id: chatId }) }));
      }
      c1Loads += 1;
      return c1Loads === 1
        ? staleFirst.promise
        : Promise.resolve(answeredDetail("d".repeat(32), "Свежий вопрос", "Свежий ответ"));
    });
    const user = setup();
    renderView();
    await settle();
    expect(screen.getByText("Загрузка…")).toBeInTheDocument();

    await user.click(screen.getByRole("link", { name: "Перейти к c2" }));
    await settle();
    await user.click(screen.getByRole("link", { name: "Перейти к c1" }));
    await settle();
    expect(pathShown()).toBe("/chats/c1");
    expect(screen.getByText("Свежий ответ")).toBeInTheDocument();

    // The first load of c1 answers last, with an active run the chat no longer has.
    staleFirst.resolve(activeDetail());
    await settle();
    await advance(POLL_INTERVAL_MS);

    expect(screen.getByText("Свежий ответ")).toBeInTheDocument();
    expect(screen.queryByText("Долгий вопрос")).toBeNull();
    expect(screen.queryByRole("status")).toBeNull();
    expect(stopButton()).toBeNull();
    expect(sendButton()).toBeInTheDocument();
    expect(getChatStatus).not.toHaveBeenCalled();
  });

  it.each([
    { reply: "cancelling" as const },
    { reply: "cancelled" as const },
  ])("ignores a late $reply cancel reply after a chat switch", async ({ reply }) => {
    getChat.mockImplementation((chatId) =>
      Promise.resolve(chatId === "c1" ? activeDetail() : detail({ chat: chat({ id: "c2" }) })),
    );
    const cancelling = deferred<Run>();
    cancelRun.mockReturnValue(cancelling.promise);
    const user = setup();
    renderView();
    await settle();
    await user.click(stopButton()!);
    expect(cancelRun).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("link", { name: "Перейти к c2" }));
    await settle();
    expect(pathShown()).toBe("/chats/c2");

    cancelling.resolve(
      run({ request_id: REQ_ACTIVE, state: reply, finished_at: reply === "cancelled" ? "2026-09-29T12:00:00Z" : null }),
    );
    await settle();
    await advance(POLL_INTERVAL_MS);

    expect(screen.queryByRole("status")).toBeNull();
    expect(stopButton()).toBeNull();
    expect(sendButton()).toBeInTheDocument();
    expect(getChat).toHaveBeenCalledTimes(2); // c1 load, c2 load - no refetch from the stale reply.
    expect(getChatStatus).not.toHaveBeenCalled();
  });

  it("drops a recovered entry refused with 409 chat_busy, returns its text to the composer and picks up the run holding the chat", async () => {
    sessionStorage.setItem(PENDING_STORAGE_KEY, JSON.stringify([entry("c1", REQ_PENDING, "Мой вопрос")]));
    getChat.mockResolvedValue(activeDetail());
    sendMessage.mockRejectedValueOnce(new ApiError(409, "chat_busy", "Чат занят, дождитесь ответа"));
    renderView();
    await settle();

    expect(sendMessage).toHaveBeenCalledTimes(1);
    expect(sendMessage).toHaveBeenCalledWith("c1", { request_id: REQ_PENDING, message: "Мой вопрос" });
    expect(screen.getByRole("alert")).toHaveTextContent("Чат занят");
    expect(screen.queryByText("Мой вопрос", { selector: ".msg__bubble" })).toBeNull();
    expect(composer()).toHaveValue("Мой вопрос");
    expect(storedPending()).toBeNull();
    expect(stopButton()).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Думаю…");
    await advance(POLL_INTERVAL_MS);
    expect(getChatStatus).toHaveBeenCalledTimes(1);
  });

  it("ignores a poll reply that lands after unmount", async () => {
    getChat.mockResolvedValue(activeDetail());
    const polling = deferred<ChatStatus>();
    getChatStatus.mockReturnValue(polling.promise);
    const view = renderView();
    await settle();
    await advance(POLL_INTERVAL_MS);
    expect(getChatStatus).toHaveBeenCalledTimes(1);

    view.unmount();
    polling.resolve(status(null, cancelledDetail().last_run));
    await settle();
    await advance(POLL_BACKOFF_MS);

    expect(getChat).toHaveBeenCalledTimes(1);
    expect(getChatStatus).toHaveBeenCalledTimes(1);
  });

  it("shows no stop button while the POST is in flight and disables the send button", async () => {
    const posting = deferred<Run>();
    sendMessage.mockReturnValue(posting.promise);
    renderView();
    await settle();
    await typeAndSend("Вопрос");

    expect(stopButton()).toBeNull();
    expect(sendButton()).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("Думаю…");
    expect(cancelRun).not.toHaveBeenCalled();

    posting.resolve(run({ request_id: sendMessage.mock.calls[0]![1].request_id }));
    await settle();
    expect(stopButton()).toBeInTheDocument();
  });

  it("issues one POST for two submits in the same tick", async () => {
    const user = setup();
    renderView();
    await settle();
    await user.type(composer(), "Дважды");
    const form = composer().closest("form")!;

    await act(async () => {
      fireEvent.submit(form);
      fireEvent.submit(form);
    });
    await settle();

    expect(sendMessage).toHaveBeenCalledTimes(1);
    expect(storedPending()).toHaveLength(1);
    expect(screen.getAllByText("Дважды")).toHaveLength(1);
  });

  it("a retry answered with the already finished run settles and shows the answer", async () => {
    sendMessage.mockRejectedValueOnce(new ApiError(0, "network", "Связь с сервером потеряна"));
    renderView();
    await settle();
    const user = await typeAndSend("Быстрый вопрос");
    const requestId = sendMessage.mock.calls[0]![1].request_id;

    sendMessage.mockResolvedValueOnce(succeededRun(requestId));
    getChat.mockResolvedValue(answeredDetail(requestId, "Быстрый вопрос", "Готовый ответ"));
    await user.click(screen.getByRole("button", { name: "Повторить" }));
    await settle();

    expect(sendMessage).toHaveBeenCalledTimes(2);
    expect(screen.getByText("Готовый ответ")).toBeInTheDocument();
    expect(screen.getAllByText("Быстрый вопрос")).toHaveLength(1);
    expect(screen.queryByRole("status")).toBeNull();
    expect(storedPending()).toBeNull();
    await advance(POLL_INTERVAL_MS * 2);
    expect(getChatStatus).not.toHaveBeenCalled();
  });

  it("keeps the bubble and offers «Обновить» when the refetch after settle fails; a successful refetch clears both", async () => {
    renderView();
    await settle();
    const user = await typeAndSend("Вопрос без ответа");
    const requestId = sendMessage.mock.calls[0]![1].request_id;
    getChatStatus.mockResolvedValue(status(null, succeededRun(requestId)));
    getChat.mockRejectedValueOnce(new ApiError(0, "network", "Связь с сервером потеряна"));
    await advance(POLL_INTERVAL_MS);

    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.getByText("Вопрос без ответа")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Сервер недоступен");
    expect(storedPending()).toEqual([entry("c1", requestId, "Вопрос без ответа")]);

    getChat.mockResolvedValue(answeredDetail(requestId, "Вопрос без ответа", "Поздний ответ"));
    await user.click(screen.getByRole("button", { name: "Обновить" }));
    await settle();

    expect(screen.getByText("Поздний ответ")).toBeInTheDocument();
    expect(screen.getAllByText("Вопрос без ответа")).toHaveLength(1);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(storedPending()).toBeNull();
  });

  it.each([
    {
      name: "network error",
      error: new ApiError(0, "network", "Связь с сервером потеряна"),
      expectStored: true,
      expectText: CONNECTION_RETRY_TEXT,
      expectDraft: "",
    },
    {
      name: "503 from the server",
      error: new ApiError(503, "llm_proxy_unavailable", "Модель недоступна"),
      expectStored: false,
      expectText: "Модель недоступна",
      expectDraft: "Первый вопрос",
    },
  ])("created chat whose first POST fails with a $name", async ({ error, expectStored, expectText, expectDraft }) => {
    createChat.mockResolvedValue(chat({ id: "c9", title: "Новый чат", last_message_at: null }));
    getChat.mockResolvedValue(detail({ chat: chat({ id: "c9" }) }));
    sendMessage.mockRejectedValueOnce(error);
    renderView("/chats/new");
    await settle();
    await typeAndSend("Первый вопрос");

    expect(pathShown()).toBe("/chats/c9");
    expect(sendMessage).toHaveBeenCalledTimes(1);
    const requestId = sendMessage.mock.calls[0]![1].request_id;
    expect(screen.getByText(expectText)).toBeInTheDocument();
    expect(storedPending()).toEqual(expectStored ? [entry("c9", requestId, "Первый вопрос")] : null);
    expect(composer()).toHaveValue(expectDraft);
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("picks up the run holding the chat after 409 chat_busy", async () => {
    sendMessage.mockRejectedValueOnce(new ApiError(409, "chat_busy", "Чат занят, дождитесь ответа"));
    renderView();
    await settle();
    getChat.mockResolvedValue(activeDetail());
    await typeAndSend("Ещё вопрос");

    expect(screen.getByRole("alert")).toHaveTextContent("Чат занят");
    expect(screen.queryByText("Ещё вопрос", { selector: ".msg__bubble" })).toBeNull();
    expect(composer()).toHaveValue("Ещё вопрос");
    expect(stopButton()).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Думаю…");
    await advance(POLL_INTERVAL_MS);
    expect(getChatStatus).toHaveBeenCalledTimes(1);
  });
});
