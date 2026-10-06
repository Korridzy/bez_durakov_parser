import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import type { ChatDetail, Report } from "./api/types";

vi.mock("./api/client", async () => ({
  ...(await vi.importActual<typeof import("./api/client")>("./api/client")),
  listChats: vi.fn(),
  getChat: vi.fn(),
  listChatReports: vi.fn(),
  getReport: vi.fn(),
}));

import * as client from "./api/client";

const report: Report = {
  id: "r1", chat_id: "c1", title: "Результаты за период", question: "Покажи результаты",
  tool: "read_rows", args: {}, generated_at: "2026-09-29T12:00:00Z",
  created_at: "2026-09-29T12:00:00Z", saved_at: null, version: 1, row_count: 1,
  data: [{ название: "Первая строка", значение: 1234.5678 }],
};
const detail: ChatDetail = {
  chat: {
    id: "c1", title: "Покажи результаты", auto_title: true,
    created_at: report.created_at, updated_at: report.created_at,
    last_message_at: report.created_at, report_count: 1,
  },
  messages: [{
    id: "m1", request_id: "a".repeat(32), role: "assistant", content: "Готовый ответ",
    reasoning: null, state: "succeeded", report_id: "r1", created_at: report.created_at,
  }],
  reports: [report], active_run: null, last_run: null,
};

let viewport = 1440;
const mediaListeners = new Set<() => void>();
function resize(width: number) {
  act(() => {
    viewport = width;
    Object.defineProperty(window, "innerWidth", { configurable: true, value: width });
    for (const listener of mediaListeners) listener();
  });
}

beforeEach(() => {
  localStorage.clear();
  sessionStorage.clear();
  vi.mocked(client.listChats).mockResolvedValue({ items: [detail.chat], next_cursor: null });
  vi.mocked(client.getChat).mockResolvedValue(detail);
  vi.mocked(client.listChatReports).mockResolvedValue([report]);
  vi.mocked(client.getReport).mockResolvedValue(report);
  vi.stubGlobal("matchMedia", (query: string) => ({
    get matches() {
      const max = /max-width:\s*(\d+)px/.exec(query)?.[1];
      return max !== undefined && viewport <= Number(max);
    },
    media: query,
    addEventListener: (_event: string, listener: () => void) => mediaListeners.add(listener),
    removeEventListener: (_event: string, listener: () => void) => mediaListeners.delete(listener),
  }));
  resize(1440);
});

afterEach(() => {
  vi.unstubAllGlobals();
  mediaListeners.clear();
  window.history.replaceState({}, "", "/");
});

async function openChat() {
  window.history.replaceState({}, "", "/chats/c1");
  const rendered = render(<App />);
  await screen.findByText("Готовый ответ");
  return rendered;
}

describe("responsive layout", () => {
  it.each([360, 768, 900])("uses closed drawers at %i px", async (width) => {
    resize(width);
    await openChat();
    expect(screen.getByRole("button", { name: "Отчёты (1)" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Чаты" })).toBeVisible();
    expect(screen.queryByRole("complementary", { name: "Отчёты чата" })).toBeNull();
    expect(screen.queryByRole("navigation", { name: "Чаты" })).toBeNull();
  });

  it.each([901, 1024, 1199])("keeps the sidebar and toggles reports at %i px", async (width) => {
    resize(width);
    await openChat();
    expect(screen.getByRole("navigation", { name: "Чаты" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Отчёты (1)" })).toBeVisible();
    expect(screen.queryByRole("complementary", { name: "Отчёты чата" })).toBeNull();
  });

  it.each([1200, 1440])("renders the reports inline at %i px", async (width) => {
    resize(width);
    await openChat();
    expect(screen.getByRole("complementary", { name: "Отчёты чата" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Отчёты (1)" })).toBeNull();
  });

  it("contains reports focus while keeping the composer in the focus scope", async () => {
    resize(360);
    const user = userEvent.setup();
    await openChat();
    const trigger = screen.getByRole("button", { name: "Отчёты (1)" });
    await user.click(trigger);
    const drawer = screen.getByRole("dialog", { name: "Отчёты чата" });
    const close = within(drawer).getByRole("button", { name: "Закрыть отчёты" });
    expect(close).toHaveFocus();
    const composer = screen.getByRole("textbox", { name: "Сообщение" });
    composer.focus();
    expect(composer).toHaveFocus();
    // Empty composer has a disabled submit: Tab wraps to the drawer, not the page.
    await user.tab();
    expect(close).toHaveFocus();
    expect(document.body.style.overflow).toBe("hidden");
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog", { name: "Отчёты чата" })).toBeNull();
    expect(trigger).toHaveFocus();
    expect(document.body.style.overflow).toBe("");
  });

  it("traps sidebar focus and closes on Escape and backdrop", async () => {
    resize(360);
    const user = userEvent.setup();
    await openChat();
    const trigger = screen.getByRole("button", { name: "Чаты" });
    await user.click(trigger);
    const drawer = screen.getByRole("dialog", { name: "Список чатов" });
    const close = within(drawer).getByRole("button", { name: "Закрыть список чатов" });
    expect(close).toHaveFocus();
    await user.tab({ shift: true });
    expect(drawer.contains(document.activeElement)).toBe(true);
    await user.keyboard("{Escape}");
    expect(trigger).toHaveFocus();
    await user.click(trigger);
    await user.click(screen.getByTestId("sidebar-backdrop"));
    expect(screen.queryByRole("dialog", { name: "Список чатов" })).toBeNull();
  });

  it("tabs from the last report control into the composer group in both directions", async () => {
    resize(360);
    const user = userEvent.setup();
    await openChat();
    const trigger = screen.getByRole("button", { name: "Отчёты (1)" });
    await user.click(trigger);
    const drawer = screen.getByRole("dialog", { name: "Отчёты чата" });
    const save = within(drawer).getByRole("button", { name: "Сохранить" });
    save.focus();
    await user.tab();
    expect(trigger).toHaveFocus();
    await user.tab();
    expect(screen.getByRole("textbox", { name: "Сообщение" })).toHaveFocus();
    await user.tab({ shift: true });
    expect(trigger).toHaveFocus();
    await user.tab({ shift: true });
    expect(save).toHaveFocus();
  });

  it("hands off reports to the sidebar without leaking the scroll lock or focus", async () => {
    resize(360);
    const user = userEvent.setup();
    await openChat();
    await user.click(screen.getByRole("button", { name: "Отчёты (1)" }));
    const sidebarTrigger = screen.getByRole("button", { name: "Чаты" });
    await user.click(sidebarTrigger);
    expect(screen.queryByRole("dialog", { name: "Отчёты чата" })).toBeNull();
    expect(screen.getByRole("button", { name: "Закрыть список чатов" })).toHaveFocus();
    expect(document.body.style.overflow).toBe("hidden");
    await user.keyboard("{Escape}");
    expect(document.body.style.overflow).toBe("");
    expect(sidebarTrigger).toHaveFocus();
  });

  it.each(["true", "false", "{corrupt", "0"])(
    "ignores persisted %s for transient mobile visibility without overwriting it",
    async (stored) => {
      localStorage.setItem("ui.sidebarOpen", stored);
      resize(360);
      const user = userEvent.setup();
      await openChat();
      expect(screen.queryByRole("navigation", { name: "Чаты" })).toBeNull();
      await user.click(screen.getByRole("button", { name: "Чаты" }));
      expect(screen.getByRole("searchbox", { name: "Поиск чатов" })).toBeVisible();
      await user.keyboard("{Escape}");
      expect(localStorage.getItem("ui.sidebarOpen")).toBe(stored);
      resize(1440);
      expect(screen.queryByRole("searchbox", { name: "Поиск чатов" }) !== null)
        .toBe(stored !== "false");
    },
  );

  it("keeps the desktop collapsed preference across reload and responsive changes", async () => {
    const user = userEvent.setup();
    const view = await openChat();
    await user.click(screen.getByRole("button", { name: "Скрыть список чатов" }));
    expect(localStorage.getItem("ui.sidebarOpen")).toBe("false");
    view.unmount();
    await openChat();
    expect(screen.getByRole("button", { name: "Показать список чатов" })).toBeVisible();
    resize(360);
    await user.click(screen.getByRole("button", { name: "Чаты" }));
    resize(1440);
    expect(document.body.style.overflow).toBe("");
    expect(screen.getByRole("button", { name: "Показать список чатов" })).toBeVisible();
  });

  it("opens reports from a message chip again after dismissing the same preview", async () => {
    resize(360);
    const user = userEvent.setup();
    await openChat();
    const chip = screen.getByRole("button", { name: "Отчёт: Результаты за период" });
    await user.click(chip);
    expect(await screen.findByRole("cell", { name: "1234.5678" })).toBeVisible();
    await user.keyboard("{Escape}");
    await user.click(chip);
    expect(screen.getByRole("dialog", { name: "Отчёты чата" })).toBeVisible();
    expect(screen.getByRole("cell", { name: "1234.5678" })).toBeVisible();
  });
});
