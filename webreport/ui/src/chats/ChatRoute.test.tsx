/**
 * The real `/chats/:chatId` route through `App`: sidebar, conversation and the
 * REAL reports panel mounted together, with only the API client mocked.
 */

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ChatDetail, Message, Report, ReportCard } from "../api/types";
import App from "../App";

vi.mock("../api/client", async () => {
  const actual =
    await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ...actual,
    listChats: vi.fn(),
    getChat: vi.fn(),
    listChatReports: vi.fn(),
    getReport: vi.fn(),
    getChatStatus: vi.fn(),
  };
});

import * as client from "../api/client";

const listChats = vi.mocked(client.listChats);
const getChat = vi.mocked(client.getChat);
const listChatReports = vi.mocked(client.listChatReports);
const getReport = vi.mocked(client.getReport);

const REQ = "d".repeat(32);

const r1: ReportCard = {
  id: "r1",
  chat_id: "c1",
  title: "Очки по командам",
  question: "Кто набрал больше очков?",
  tool: "read_rows",
  args: { table: "results" },
  generated_at: "2026-09-29T11:55:00Z",
  version: 1,
  saved_at: null,
  row_count: 2,
  created_at: "2026-09-29T11:55:00Z",
};

const report: Report = {
  ...r1,
  data: [
    { команда: "Альфа", очки: 12 },
    { команда: "Бета", очки: 7 },
  ],
};

const messages: Message[] = [
  {
    id: "m1",
    request_id: REQ,
    role: "user",
    content: "Кто набрал больше очков?",
    reasoning: null,
    state: null,
    report_id: null,
    created_at: "2026-09-29T11:54:00Z",
  },
  {
    id: "m2",
    request_id: REQ,
    role: "assistant",
    content: "Больше всего очков у «Альфы».",
    reasoning: null,
    state: "succeeded",
    report_id: "r1",
    created_at: "2026-09-29T11:55:00Z",
  },
];

const detail: ChatDetail = {
  chat: {
    id: "c1",
    title: "Кто набрал больше очков?",
    auto_title: true,
    created_at: "2026-09-29T11:54:00Z",
    updated_at: "2026-09-29T11:55:00Z",
    last_message_at: "2026-09-29T11:55:00Z",
    report_count: 1,
  },
  messages,
  reports: [r1],
  active_run: null,
  last_run: null,
};

beforeEach(() => {
  listChats.mockReset();
  getChat.mockReset();
  listChatReports.mockReset();
  getReport.mockReset();
  listChats.mockResolvedValue({ items: [detail.chat], next_cursor: null });
  getChat.mockResolvedValue(detail);
  listChatReports.mockResolvedValue([r1]);
  getReport.mockResolvedValue(report);
});

afterEach(() => {
  window.history.replaceState({}, "", "/");
});

function renderAt(path: string) {
  window.history.replaceState({}, "", path);
  return render(<App />);
}

describe("/chats/:chatId route", () => {
  it("mounts the sidebar, the conversation and the real reports panel together", async () => {
    renderAt("/chats/c1");

    expect(await screen.findByText("Больше всего очков у «Альфы».")).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Чаты" })).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Сообщение" })).toBeInTheDocument();

    const panel = await screen.findByRole("complementary", { name: /Отчёты чата/ });
    expect(within(panel).getByRole("heading", { name: "Отчёты чата (1)" })).toBeInTheDocument();
    expect(listChatReports).toHaveBeenCalledWith("c1");
    expect(within(panel).getByRole("button", { name: /Очки по командам/ })).toBeInTheDocument();
  });

  it("opens the report in the panel when its chip in the message is clicked", async () => {
    const user = userEvent.setup();
    renderAt("/chats/c1");

    const chip = await screen.findByRole("button", { name: "Отчёт: Очки по командам" });
    const panel = await screen.findByRole("complementary", { name: /Отчёты чата/ });
    expect(within(panel).queryByRole("button", { name: "К списку" })).toBeNull();

    await user.click(chip);

    await waitFor(() => expect(getReport).toHaveBeenCalledWith("r1"));
    expect(await within(panel).findByRole("button", { name: "К списку" })).toBeInTheDocument();
    expect(within(panel).getByRole("heading", { name: "Очки по командам" })).toBeInTheDocument();
    expect(within(panel).getByRole("cell", { name: "Альфа" })).toBeInTheDocument();
  });
});
