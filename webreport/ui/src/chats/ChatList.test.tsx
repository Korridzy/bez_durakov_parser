import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  MemoryRouter,
  Route,
  Routes,
  useLocation,
  useParams,
} from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/types";
import type { Chat, ChatPage } from "../api/types";
import { ChatList, NEW_CHAT_PATH } from "./ChatList";
import { SEARCH_DEBOUNCE_MS, SIDEBAR_STORAGE_KEY } from "./useChats";

vi.mock("../api/client", async () => {
  const actual =
    await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ...actual,
    listChats: vi.fn(),
    createChat: vi.fn(),
    renameChat: vi.fn(),
    deleteChat: vi.fn(),
  };
});

import * as client from "../api/client";

const listChats = vi.mocked(client.listChats);
const createChat = vi.mocked(client.createChat);
const renameChat = vi.mocked(client.renameChat);
const deleteChat = vi.mocked(client.deleteChat);

const NOW = new Date("2026-09-29T12:00:00Z");

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

function page(items: Chat[], next_cursor: string | null = null): ChatPage {
  return { items, next_cursor };
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

/** Flush resolved promises and the React updates they queued (fake timers stay put). */
async function settle() {
  await act(async () => {
    for (let i = 0; i < 6; i += 1) {
      await Promise.resolve();
    }
  });
}

async function advance(ms: number) {
  await act(async () => {
    vi.advanceTimersByTime(ms);
  });
  await settle();
}

function Harness() {
  const { chatId } = useParams();
  const location = useLocation();
  return (
    <>
      <ChatList selectedChatId={chatId} />
      <output data-testid="path">{location.pathname}</output>
    </>
  );
}

function renderList(path = "/chats/c1") {
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

function setup() {
  return userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
}

const twoChats = [
  chat({
    id: "c1",
    title: "Игры за сезон",
    last_message_at: "2026-09-29T11:58:30Z",
    report_count: 2,
  }),
  chat({
    id: "c2",
    title: "Лучшие команды",
    last_message_at: "2026-09-27T09:00:00Z",
  }),
];

beforeEach(() => {
  vi.useFakeTimers();
  // Testing Library's async wrapper drains a `setTimeout(0)` and only advances
  // fake timers when it sees a `jest` global; under vitest this shim keeps
  // user-event and `act` from waiting on a timer that never fires.
  (globalThis as { jest?: unknown }).jest = {
    advanceTimersByTime: (ms: number) => vi.advanceTimersByTime(ms),
  };
  vi.setSystemTime(NOW);
  localStorage.clear();
  listChats.mockReset();
  createChat.mockReset();
  renameChat.mockReset();
  deleteChat.mockReset();
  listChats.mockResolvedValue(page(twoChats));
});

afterEach(() => {
  delete (globalThis as { jest?: unknown }).jest;
  vi.useRealTimers();
});

describe("ChatList", () => {
  it("renders rows with title, relative time, report badge and the selected row", async () => {
    renderList("/chats/c1");
    await settle();

    const nav = screen.getByRole("navigation", { name: "Чаты" });
    const rows = within(nav).getAllByRole("listitem");
    expect(rows).toHaveLength(2);

    const first = within(rows[0]!);
    expect(first.getByRole("link", { name: /Игры за сезон/ })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(first.getByText("1 мин. назад")).toBeInTheDocument();
    expect(first.getByLabelText("Отчётов: 2")).toHaveTextContent("2");

    const second = within(rows[1]!);
    expect(
      second.getByRole("link", { name: /Лучшие команды/ }),
    ).not.toHaveAttribute("aria-current");
    expect(second.getByText("2 дн. назад")).toBeInTheDocument();
    expect(second.queryByLabelText(/Отчётов/)).toBeNull();

    expect(listChats).toHaveBeenCalledTimes(1);
    expect(listChats).toHaveBeenCalledWith({ limit: 50 });
  });

  it("sends the search query only after the debounce", async () => {
    const user = setup();
    renderList();
    await settle();
    listChats.mockResolvedValue(page([chat({ id: "c9", title: "Найдено" })]));

    await user.type(screen.getByRole("searchbox", { name: "Поиск чатов" }), "игр");
    await advance(SEARCH_DEBOUNCE_MS - 1);
    expect(listChats).toHaveBeenCalledTimes(1);

    await advance(1);
    expect(listChats).toHaveBeenCalledTimes(2);
    expect(listChats).toHaveBeenLastCalledWith({ q: "игр", limit: 50 });
    expect(screen.getByRole("link", { name: /Найдено/ })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Игры за сезон/ })).toBeNull();
  });

  it("passes regex and special characters verbatim and keeps very long titles intact", async () => {
    const user = setup();
    const longTitle = "Ж".repeat(80);
    renderList();
    await settle();
    listChats.mockResolvedValue(page([chat({ id: "c7", title: longTitle })]));

    const odd = "a.*(b[c]?\\ %<>&";
    // user-event treats `[` as a key descriptor; `[[` types a literal bracket.
    await user.type(
      screen.getByRole("searchbox", { name: "Поиск чатов" }),
      odd.replace("[", "[["),
    );
    await advance(SEARCH_DEBOUNCE_MS);

    expect(listChats).toHaveBeenLastCalledWith({ q: odd, limit: 50 });
    const link = screen.getByTitle(longTitle);
    expect(link).toHaveAttribute("href", "/chats/c7");
    expect(within(link).getByText(longTitle)).toBeInTheDocument();
  });

  it("sends the search text verbatim (repeated and edge spaces) and omits q for whitespace-only input", async () => {
    const user = setup();
    renderList();
    await settle();
    const box = screen.getByRole("searchbox", { name: "\u041f\u043e\u0438\u0441\u043a \u0447\u0430\u0442\u043e\u0432" });

    // The server search is an exact substring match over stored text, which
    // keeps its original whitespace: 'a  b' must reach it with both spaces.
    await user.type(box, "a  b");
    await advance(SEARCH_DEBOUNCE_MS);
    expect(listChats).toHaveBeenLastCalledWith({ q: "a  b", limit: 50 });

    await user.clear(box);
    await user.type(box, "  \u0438\u0433\u0440\u044b ");
    await advance(SEARCH_DEBOUNCE_MS);
    expect(listChats).toHaveBeenLastCalledWith({ q: "  \u0438\u0433\u0440\u044b ", limit: 50 });

    await user.clear(box);
    await user.type(box, "   ");
    await advance(SEARCH_DEBOUNCE_MS);
    expect(listChats).toHaveBeenLastCalledWith({ limit: 50 });
    expect(screen.getByRole("link", { name: /\u0418\u0433\u0440\u044b \u0437\u0430 \u0441\u0435\u0437\u043e\u043d/ })).toBeInTheDocument();
  });

  it("ignores a slower earlier search response that arrives after a newer one", async () => {
    const user = setup();
    renderList();
    await settle();

    const slow = deferred<ChatPage>();
    const fast = deferred<ChatPage>();
    listChats.mockReturnValueOnce(slow.promise).mockReturnValueOnce(fast.promise);
    const box = screen.getByRole("searchbox", { name: "Поиск чатов" });

    await user.type(box, "a");
    await advance(SEARCH_DEBOUNCE_MS);
    await user.type(box, "b");
    await advance(SEARCH_DEBOUNCE_MS);
    expect(listChats).toHaveBeenCalledTimes(3);
    expect(listChats).toHaveBeenNthCalledWith(2, { q: "a", limit: 50 });
    expect(listChats).toHaveBeenNthCalledWith(3, { q: "ab", limit: 50 });

    fast.resolve(page([chat({ id: "new", title: "Свежий результат" })]));
    await settle();
    slow.resolve(page([chat({ id: "old", title: "Устаревший результат" })]));
    await settle();

    expect(screen.getByRole("link", { name: /Свежий результат/ })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Устаревший результат/ })).toBeNull();
    expect(screen.queryByText("Ничего не найдено")).toBeNull();
  });

  it("navigates to the empty new-chat route without creating a server row", async () => {
    const user = setup();
    renderList("/chats/c1");
    await settle();

    await user.click(screen.getByRole("button", { name: "Новый чат" }));

    expect(pathShown()).toBe(NEW_CHAT_PATH);
    expect(createChat).not.toHaveBeenCalled();
    expect(screen.getByRole("link", { name: /Игры за сезон/ })).not.toHaveAttribute(
      "aria-current",
    );
  });

  it("renames a chat inline through PATCH and shows the new title", async () => {
    const user = setup();
    renameChat.mockResolvedValue(
      chat({ id: "c1", title: "Сезон 2026", auto_title: false }),
    );
    renderList();
    await settle();

    await user.click(
      screen.getByRole("button", { name: "Действия с чатом «Игры за сезон»" }),
    );
    await user.click(screen.getByRole("menuitem", { name: "Переименовать" }));
    const input = screen.getByRole("textbox", { name: "Новое название чата" });
    expect(input).toHaveValue("Игры за сезон");
    await user.clear(input);
    await user.type(input, "  Сезон   2026 {Enter}");
    await settle();

    expect(renameChat).toHaveBeenCalledWith("c1", "Сезон 2026");
    expect(screen.getByRole("link", { name: /Сезон 2026/ })).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "Новое название чата" })).toBeNull();
  });

  it("cancels an inline rename with Escape without calling the API", async () => {
    const user = setup();
    renderList();
    await settle();

    await user.click(
      screen.getByRole("button", { name: "Действия с чатом «Игры за сезон»" }),
    );
    await user.click(screen.getByRole("menuitem", { name: "Переименовать" }));
    await user.type(
      screen.getByRole("textbox", { name: "Новое название чата" }),
      "x{Escape}",
    );

    expect(renameChat).not.toHaveBeenCalled();
    expect(screen.getByRole("link", { name: /Игры за сезон/ })).toBeInTheDocument();
  });

  it("deletes a chat after confirmation and moves the selection to a neighbour", async () => {
    const user = setup();
    deleteChat.mockResolvedValue(undefined);
    renderList("/chats/c1");
    await settle();

    await user.click(
      screen.getByRole("button", { name: "Действия с чатом «Игры за сезон»" }),
    );
    await user.click(screen.getByRole("menuitem", { name: "Удалить" }));
    const dialog = screen.getByRole("dialog", { name: "Удалить чат «Игры за сезон»?" });
    expect(dialog).toHaveTextContent(
      "Сохранённые отчёты останутся во вкладке «Сохранённые отчёты»",
    );
    expect(deleteChat).not.toHaveBeenCalled();

    await user.click(within(dialog).getByRole("button", { name: "Удалить" }));
    await settle();

    expect(deleteChat).toHaveBeenCalledWith("c1");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByRole("link", { name: /Игры за сезон/ })).toBeNull();
    expect(pathShown()).toBe("/chats/c2");
  });

  it("keeps the row and explains a chat_busy conflict on delete", async () => {
    const user = setup();
    deleteChat.mockRejectedValue(
      new ApiError(409, "chat_busy", "Чат занят", {
        error: { code: "chat_busy", message: "Чат занят" },
      }),
    );
    renderList("/chats/c2");
    await settle();

    await user.click(
      screen.getByRole("button", { name: "Действия с чатом «Игры за сезон»" }),
    );
    await user.click(screen.getByRole("menuitem", { name: "Удалить" }));
    await user.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: "Удалить" }),
    );
    await settle();

    expect(screen.getByRole("alert")).toHaveTextContent("Дождитесь завершения ответа");
    expect(screen.getByRole("link", { name: /Игры за сезон/ })).toBeInTheDocument();
    expect(pathShown()).toBe("/chats/c2");
  });

  it("appends the next page through «Показать ещё»", async () => {
    const user = setup();
    listChats.mockReset();
    listChats
      .mockResolvedValueOnce(page(twoChats, "cursor-1"))
      .mockResolvedValueOnce(page([chat({ id: "c3", title: "Третий" })]));
    renderList();
    await settle();

    await user.click(screen.getByRole("button", { name: "Показать ещё" }));
    await settle();

    expect(listChats).toHaveBeenLastCalledWith({ limit: 50, cursor: "cursor-1" });
    const nav = screen.getByRole("navigation", { name: "Чаты" });
    expect(within(nav).getAllByRole("listitem")).toHaveLength(3);
    expect(screen.getByRole("link", { name: /Третий/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Показать ещё" })).toBeNull();
  });

  it("shows «Сервер недоступен» with a retry button when the list request fails", async () => {
    const user = setup();
    listChats.mockReset();
    listChats
      .mockRejectedValueOnce(new ApiError(0, "network", "Связь с сервером потеряна"))
      .mockResolvedValueOnce(page(twoChats));
    renderList();
    await settle();

    expect(screen.getByText("Сервер недоступен")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Повторить" }));
    await settle();

    expect(listChats).toHaveBeenCalledTimes(2);
    expect(screen.queryByText("Сервер недоступен")).toBeNull();
    expect(screen.getByRole("link", { name: /Игры за сезон/ })).toBeInTheDocument();
  });

  it("opens the most recent chat when /chats has no id", async () => {
    renderList("/chats");
    await settle();

    expect(pathShown()).toBe("/chats/c1");
  });

  it("opens the empty new-chat route when /chats has no id and no chats exist", async () => {
    listChats.mockResolvedValue(page([]));
    renderList("/chats");
    await settle();

    expect(pathShown()).toBe(NEW_CHAT_PATH);
    expect(createChat).not.toHaveBeenCalled();
    expect(screen.getByText("Чатов пока нет")).toBeInTheDocument();
  });

  it("persists the collapsed state under ui.sidebarOpen and tolerates a malformed value", async () => {
    const user = setup();
    localStorage.setItem(SIDEBAR_STORAGE_KEY, "{not json");
    renderList();
    await settle();

    expect(screen.getByRole("searchbox", { name: "Поиск чатов" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Скрыть список чатов" }));

    expect(localStorage.getItem(SIDEBAR_STORAGE_KEY)).toBe("false");
    expect(screen.queryByRole("searchbox", { name: "Поиск чатов" })).toBeNull();
    expect(screen.getByRole("navigation", { name: "Чаты" })).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Показать список чатов" }));
    expect(localStorage.getItem(SIDEBAR_STORAGE_KEY)).toBe("true");
    expect(screen.getByRole("searchbox", { name: "Поиск чатов" })).toBeInTheDocument();
  });
});
