import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/types";
import type { Report, ReportCard } from "../api/types";
import { formatGeneratedAt } from "./ReportPreview";
import {
  PANEL_WIDTH_STEP,
  PANEL_WIDTH_STORAGE_KEY,
  ReportsPanel,
} from "./ReportsPanel";
import { ReportsProvider, useReports } from "./ReportsContext";

vi.mock("../api/client", async () => {
  const actual =
    await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ...actual,
    listChatReports: vi.fn(),
    getReport: vi.fn(),
    saveReport: vi.fn(),
    unsaveReport: vi.fn(),
  };
});

import * as client from "../api/client";

const listChatReports = vi.mocked(client.listChatReports);
const getReport = vi.mocked(client.getReport);
const saveReport = vi.mocked(client.saveReport);
const unsaveReport = vi.mocked(client.unsaveReport);

function card(over: Partial<ReportCard> & { id: string }): ReportCard {
  return {
    chat_id: "c1",
    title: `Отчёт ${over.id}`,
    question: `Вопрос ${over.id}`,
    tool: "read_rows",
    args: { table: "results", limit: 10 },
    generated_at: "2026-09-28T10:15:00Z",
    version: 1,
    saved_at: null,
    row_count: 3,
    created_at: "2026-09-28T10:15:00Z",
    ...over,
  };
}

function report(base: ReportCard, data: unknown): Report {
  return { ...base, data };
}

const rows = [
  { команда: "Альфа", очки: 1234.5678 },
  { команда: "Бета", очки: 42 },
];

const c1Cards = [
  card({ id: "r1", title: "Итоги сезона", row_count: 2 }),
  card({ id: "r2", title: "Лучшие игроки", saved_at: "2026-09-28T11:00:00Z" }),
];
const c2Cards = [card({ id: "r9", chat_id: "c2", title: "Чужой отчёт" })];

const byChat: Record<string, ReportCard[]> = { c1: c1Cards, c2: c2Cards };

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

/** A stand-in for todo 13's chip: opens a report through the context. */
function Chip({ id }: { id: string }) {
  const { openReport } = useReports();
  return (
    <button type="button" onClick={() => openReport(id)}>
      Отчёт: {id}
    </button>
  );
}

/** A stand-in for todo 13's "run completed" hook: refreshes with a highlight. */
function Refresher({ highlight }: { highlight: string }) {
  const { refresh } = useReports();
  return (
    <button type="button" onClick={() => refresh(highlight)}>
      refresh
    </button>
  );
}

function renderPanel(chatId: string | null = "c1", extra?: React.ReactNode) {
  return render(
    <ReportsProvider chatId={chatId}>
      {extra}
      <ReportsPanel />
    </ReportsProvider>,
  );
}

const panel = () => screen.getByRole("complementary", { name: "Отчёты чата" });
const cards = () => within(panel()).queryAllByRole("listitem");
/** `aria-busy` of the scrolling list/preview region (the only element carrying it). */
const listBusy = () => panel().querySelector(".reports-panel__scroll")?.getAttribute("aria-busy");
const saveButtonIn = (scope: HTMLElement) =>
  within(scope).getByRole("button", {
    name: /Сохранить|Убрать из сохранённых/,
  });

beforeEach(() => {
  localStorage.clear();
  listChatReports.mockReset();
  getReport.mockReset();
  saveReport.mockReset();
  unsaveReport.mockReset();
  listChatReports.mockImplementation((chatId) =>
    Promise.resolve(byChat[chatId] ?? []),
  );
  getReport.mockImplementation((id) => {
    const found = [...c1Cards, ...c2Cards].find((item) => item.id === id);
    return found === undefined
      ? Promise.reject(new ApiError(404, "not_found", "Отчёт не найден"))
      : Promise.resolve(report(found, rows));
  });
  // PUT answers with the same report's card, bookmarked (a server never renames it).
  saveReport.mockImplementation((id) => {
    const found = [...c1Cards, ...c2Cards].find((item) => item.id === id) ?? card({ id });
    return Promise.resolve({ ...found, saved_at: "2026-09-29T12:00:00Z" });
  });
  unsaveReport.mockResolvedValue(undefined);
});

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("ReportsPanel list", () => {
  it("lists only the given chat's cards with title, date, rows and the saved star", async () => {
    renderPanel("c1");

    expect(
      await within(panel()).findByRole("heading", { name: "Отчёты чата (2)" }),
    ).toBeInTheDocument();
    expect(listChatReports).toHaveBeenCalledTimes(1);
    expect(listChatReports).toHaveBeenCalledWith("c1");

    const items = cards();
    expect(items).toHaveLength(2);
    expect(screen.queryByText("Чужой отчёт")).toBeNull();

    const first = within(items[0]!);
    expect(first.getByRole("button", { name: /Итоги сезона/ })).toBeInTheDocument();
    const expected = new Intl.DateTimeFormat("ru-RU", {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(new Date("2026-09-28T10:15:00Z"));
    expect(first.getByText(expected)).toBeInTheDocument();
    expect(first.getByText("Строк: 2")).toBeInTheDocument();
    expect(saveButtonIn(items[0]!)).toHaveAttribute("aria-pressed", "false");
    expect(saveButtonIn(items[1]!)).toHaveAttribute("aria-pressed", "true");
  });

  it("shows the empty state and never fetches for a chat without a server row", async () => {
    listChatReports.mockResolvedValue([]);
    const { rerender } = renderPanel(null);

    expect(
      screen.getByText("Отчёты появятся здесь, когда агент вернёт данные"),
    ).toBeInTheDocument();
    expect(listChatReports).not.toHaveBeenCalled();

    rerender(
      <ReportsProvider chatId="c3">
        <ReportsPanel />
      </ReportsProvider>,
    );
    await waitFor(() => expect(listChatReports).toHaveBeenCalledWith("c3"));
    expect(
      await screen.findByText("Отчёты появятся здесь, когда агент вернёт данные"),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Отчёты чата (0)" })).toBeInTheDocument();
  });

  it("refresh() reloads the list and highlights the new card", async () => {
    const user = userEvent.setup();
    renderPanel("c1", <Refresher highlight="r3" />);
    await screen.findByRole("heading", { name: "Отчёты чата (2)" });

    listChatReports.mockResolvedValue([
      card({ id: "r3", title: "Новый отчёт" }),
      ...c1Cards,
    ]);
    await user.click(screen.getByRole("button", { name: "refresh" }));

    await screen.findByRole("heading", { name: "Отчёты чата (3)" });
    expect(listChatReports).toHaveBeenCalledTimes(2);
    const items = cards();
    expect(items[0]).toHaveClass("is-highlighted");
    expect(within(items[0]!).getByText("Новый отчёт")).toBeInTheDocument();
    expect(items[1]).not.toHaveClass("is-highlighted");
  });
});

describe("ReportsPanel preview", () => {
  it("opens the preview with title and parameters from a card and returns with «К списку»", async () => {
    const user = userEvent.setup();
    renderPanel("c1");
    await screen.findByRole("heading", { name: "Отчёты чата (2)" });

    await user.click(screen.getByRole("button", { name: /Итоги сезона/ }));

    expect(getReport).toHaveBeenCalledWith("r1");
    expect(
      await screen.findByRole("heading", { level: 2, name: "Итоги сезона" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Параметры" })).toBeInTheDocument();
    expect(screen.getByText("Вопрос r1")).toBeInTheDocument();
    expect(screen.getByText("results")).toBeInTheDocument();
    expect(within(screen.getByRole("table")).getByText("1234.5678")).toBeInTheDocument();
    expect(cards()).toHaveLength(0);

    await user.click(screen.getByRole("button", { name: "К списку" }));
    expect(await screen.findByRole("button", { name: /Итоги сезона/ })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Параметры" })).toBeNull();
  });

  it("openReport() from the context opens the preview", async () => {
    const user = userEvent.setup();
    renderPanel("c1", <Chip id="r2" />);
    await screen.findByRole("heading", { name: "Отчёты чата (2)" });

    await user.click(screen.getByRole("button", { name: "Отчёт: r2" }));

    expect(
      await screen.findByRole("heading", { level: 2, name: "Лучшие игроки" }),
    ).toBeInTheDocument();
    expect(getReport).toHaveBeenCalledWith("r2");
  });

  it("shows «Отчёт не найден» and returns to the list when the report is gone (404)", async () => {
    const user = userEvent.setup();
    renderPanel("c1", <Chip id="gone" />);
    await screen.findByRole("heading", { name: "Отчёты чата (2)" });
    listChatReports.mockResolvedValue([c1Cards[1]!]);

    await user.click(screen.getByRole("button", { name: "Отчёт: gone" }));

    expect(await screen.findByRole("status")).toHaveTextContent("Отчёт не найден");
    expect(screen.queryByRole("button", { name: "К списку" })).toBeNull();
    expect(screen.queryByRole("heading", { name: "Параметры" })).toBeNull();
    // The list is refreshed so a card of a deleted report disappears too.
    await screen.findByRole("heading", { name: "Отчёты чата (1)" });
    expect(listChatReports).toHaveBeenCalledTimes(2);
    expect(cards()).toHaveLength(1);
  });

  it("toggles fullscreen through a dialog that Escape closes", async () => {
    const user = userEvent.setup();
    renderPanel("c1");
    await screen.findByRole("heading", { name: "Отчёты чата (2)" });
    await user.click(screen.getByRole("button", { name: /Итоги сезона/ }));
    await screen.findByRole("heading", { level: 2, name: "Итоги сезона" });

    await user.click(screen.getByRole("button", { name: "На весь экран" }));

    const dialog = screen.getByRole("dialog", { name: "Итоги сезона" });
    expect(dialog).toHaveAttribute("open");
    expect(within(dialog).getByRole("heading", { name: "Параметры" })).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Свернуть" })).toBeInTheDocument();

    await user.keyboard("{Escape}");

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    // The inline preview stays open after leaving fullscreen.
    expect(screen.getByRole("heading", { level: 2, name: "Итоги сезона" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "На весь экран" })).toBeInTheDocument();
  });
});

describe("ReportsPanel save", () => {
  it("save is optimistic on the card and calls PUT", async () => {
    const user = userEvent.setup();
    const pending = deferred<ReportCard>();
    saveReport.mockReturnValue(pending.promise);
    renderPanel("c1");
    await screen.findByRole("heading", { name: "Отчёты чата (2)" });

    const button = saveButtonIn(cards()[0]!);
    expect(button).toHaveAccessibleName("Сохранить");
    await user.click(button);

    expect(saveReport).toHaveBeenCalledWith("r1");
    expect(saveButtonIn(cards()[0]!)).toHaveAttribute("aria-pressed", "true");
    expect(saveButtonIn(cards()[0]!)).toHaveAccessibleName("Убрать из сохранённых");

    pending.resolve(card({ id: "r1", saved_at: "2026-09-29T12:00:00Z" }));
    await waitFor(() => expect(saveButtonIn(cards()[0]!)).toBeEnabled());
    expect(saveButtonIn(cards()[0]!)).toHaveAttribute("aria-pressed", "true");
  });

  it("unsave calls DELETE from the preview and the card follows", async () => {
    const user = userEvent.setup();
    renderPanel("c1");
    await screen.findByRole("heading", { name: "Отчёты чата (2)" });
    await user.click(screen.getByRole("button", { name: /Лучшие игроки/ }));
    await screen.findByRole("heading", { level: 2, name: "Лучшие игроки" });

    const toggle = screen.getByRole("button", { name: "Убрать из сохранённых" });
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    await user.click(toggle);

    expect(unsaveReport).toHaveBeenCalledWith("r2");
    expect(await screen.findByRole("button", { name: "Сохранить" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );

    await user.click(screen.getByRole("button", { name: "К списку" }));
    await screen.findByRole("heading", { name: "Отчёты чата (2)" });
    expect(saveButtonIn(cards()[1]!)).toHaveAttribute("aria-pressed", "false");
  });

  it("reverts the star and shows the error when saving fails", async () => {
    const user = userEvent.setup();
    saveReport.mockRejectedValue(new ApiError(0, "network", "Связь с сервером потеряна"));
    renderPanel("c1");
    await screen.findByRole("heading", { name: "Отчёты чата (2)" });

    await user.click(saveButtonIn(cards()[0]!));

    await waitFor(() =>
      expect(saveButtonIn(cards()[0]!)).toHaveAttribute("aria-pressed", "false"),
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Не удалось сохранить отчёт: Связь с сервером потеряна",
    );
    expect(saveButtonIn(cards()[0]!)).toBeEnabled();
  });
});

describe("ReportsPanel width", () => {
  it("falls back to the default width when localStorage holds garbage", async () => {
    localStorage.setItem(PANEL_WIDTH_STORAGE_KEY, "not-a-number");
    renderPanel("c1");
    await screen.findByRole("heading", { name: "Отчёты чата (2)" });

    // The contract default (min 360 px), not the exported constant: a coordinated
    // change of both must still fail here.
    expect(panel().style.getPropertyValue("--reports-panel-current")).toBe("360px");
  });

  it("restores a stored width and resizes from the keyboard, persisting the value", async () => {
    const user = userEvent.setup();
    localStorage.setItem(PANEL_WIDTH_STORAGE_KEY, "480");
    renderPanel("c1");
    await screen.findByRole("heading", { name: "Отчёты чата (2)" });

    expect(panel().style.getPropertyValue("--reports-panel-current")).toBe("480px");

    const handle = screen.getByRole("separator", { name: "Изменить ширину панели отчётов" });
    handle.focus();
    await user.keyboard("{ArrowLeft}");

    const widened = 480 + PANEL_WIDTH_STEP;
    expect(panel().style.getPropertyValue("--reports-panel-current")).toBe(
      `${String(widened)}px`,
    );
    expect(handle).toHaveAttribute("aria-valuenow", String(widened));
    expect(localStorage.getItem(PANEL_WIDTH_STORAGE_KEY)).toBe(String(widened));

    await user.keyboard("{ArrowRight}");
    expect(localStorage.getItem(PANEL_WIDTH_STORAGE_KEY)).toBe("480");
  });
});

/*
 * Orderings of {list GET, report GET, Save, Unsave, chatId change,
 * refreshToken change, fullscreen}. Every response is a deferred promise the
 * test settles by hand; no timers.
 */

function Tree({
  chatId,
  refreshToken = null,
  extra,
}: {
  chatId: string | null;
  refreshToken?: string | null;
  extra?: React.ReactNode;
}) {
  return (
    <ReportsProvider chatId={chatId} refreshToken={refreshToken}>
      {extra}
      <ReportsPanel />
    </ReportsProvider>
  );
}

const unsavedR1 = card({ id: "r1", title: "Итоги сезона", row_count: 2 });
const savedR1 = { ...unsavedR1, saved_at: "2026-09-29T12:00:00Z" };
const r2 = c1Cards[1]!;

describe("ReportsPanel orderings: save vs list/report responses", () => {
  it("a list GET issued before Save and answered after its success keeps the star saved", async () => {
    const user = userEvent.setup();
    renderPanel("c1", <Refresher highlight="r1" />);
    await screen.findByRole("heading", { name: "Отчёты чата (2)" });

    const stale = deferred<ReportCard[]>();
    listChatReports.mockReturnValueOnce(stale.promise);
    await user.click(screen.getByRole("button", { name: "refresh" }));
    expect(listChatReports).toHaveBeenCalledTimes(2);

    await user.click(saveButtonIn(cards()[0]!));
    await waitFor(() => expect(saveButtonIn(cards()[0]!)).toBeEnabled());
    expect(saveButtonIn(cards()[0]!)).toHaveAttribute("aria-pressed", "true");

    stale.resolve([unsavedR1, r2]);
    await waitFor(() => expect(listBusy()).toBe("false"));
    expect(saveButtonIn(cards()[0]!)).toHaveAttribute("aria-pressed", "true");
    expect(saveButtonIn(cards()[1]!)).toHaveAttribute("aria-pressed", "true");
  });

  it("a list GET issued before Unsave and answered after its success keeps the star cleared", async () => {
    const user = userEvent.setup();
    renderPanel("c1", <Refresher highlight="r2" />);
    await screen.findByRole("heading", { name: "Отчёты чата (2)" });

    const stale = deferred<ReportCard[]>();
    listChatReports.mockReturnValueOnce(stale.promise);
    await user.click(screen.getByRole("button", { name: "refresh" }));

    await user.click(saveButtonIn(cards()[1]!));
    expect(unsaveReport).toHaveBeenCalledWith("r2");
    await waitFor(() => expect(saveButtonIn(cards()[1]!)).toBeEnabled());

    stale.resolve([unsavedR1, r2]);
    await waitFor(() => expect(listBusy()).toBe("false"));
    expect(saveButtonIn(cards()[1]!)).toHaveAttribute("aria-pressed", "false");
  });

  it("a list GET issued after a confirmed Save reflects the server (server wins later)", async () => {
    const user = userEvent.setup();
    renderPanel("c1", <Refresher highlight="r1" />);
    await screen.findByRole("heading", { name: "Отчёты чата (2)" });

    await user.click(saveButtonIn(cards()[0]!));
    await waitFor(() => expect(saveButtonIn(cards()[0]!)).toBeEnabled());
    expect(saveButtonIn(cards()[0]!)).toHaveAttribute("aria-pressed", "true");

    // Someone unsaved it elsewhere: a request issued after our save must show that.
    listChatReports.mockResolvedValueOnce([unsavedR1, r2]);
    await user.click(screen.getByRole("button", { name: "refresh" }));
    await waitFor(() =>
      expect(saveButtonIn(cards()[0]!)).toHaveAttribute("aria-pressed", "false"),
    );
  });

  it("a list GET answered while the PUT is still in flight keeps the optimistic star; a failing PUT then reverts", async () => {
    const user = userEvent.setup();
    const put = deferred<ReportCard>();
    saveReport.mockReturnValueOnce(put.promise);
    renderPanel("c1", <Refresher highlight="r1" />);
    await screen.findByRole("heading", { name: "Отчёты чата (2)" });

    await user.click(saveButtonIn(cards()[0]!));
    expect(saveButtonIn(cards()[0]!)).toHaveAttribute("aria-pressed", "true");

    listChatReports.mockResolvedValueOnce([unsavedR1, r2]);
    await user.click(screen.getByRole("button", { name: "refresh" }));
    await waitFor(() => expect(listChatReports).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(listBusy()).toBe("false"));
    expect(saveButtonIn(cards()[0]!)).toHaveAttribute("aria-pressed", "true");
    expect(saveButtonIn(cards()[0]!)).toBeDisabled();

    put.reject(new ApiError(0, "network", "Связь с сервером потеряна"));
    await waitFor(() =>
      expect(saveButtonIn(cards()[0]!)).toHaveAttribute("aria-pressed", "false"),
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Не удалось сохранить отчёт");

    // No leftover override: the next list response is shown as the server sent it.
    listChatReports.mockResolvedValueOnce([savedR1, r2]);
    await user.click(screen.getByRole("button", { name: "refresh" }));
    await waitFor(() =>
      expect(saveButtonIn(cards()[0]!)).toHaveAttribute("aria-pressed", "true"),
    );
  });

  it("re-opening a report while its PUT is in flight keeps the optimistic star in the preview", async () => {
    const user = userEvent.setup();
    const put = deferred<ReportCard>();
    saveReport.mockReturnValueOnce(put.promise);
    renderPanel("c1");
    await screen.findByRole("heading", { name: "Отчёты чата (2)" });

    await user.click(screen.getByRole("button", { name: /Итоги сезона/ }));
    await screen.findByRole("heading", { level: 2, name: "Итоги сезона" });
    await user.click(screen.getByRole("button", { name: "Сохранить" }));
    expect(saveReport).toHaveBeenCalledWith("r1");

    // Back and re-open: the new GET is answered by a server that has not saved yet.
    await user.click(screen.getByRole("button", { name: "К списку" }));
    await user.click(screen.getByRole("button", { name: /Итоги сезона/ }));
    await screen.findByRole("heading", { level: 2, name: "Итоги сезона" });
    expect(getReport).toHaveBeenCalledTimes(2);
    const toggle = screen.getByRole("button", { name: "Убрать из сохранённых" });
    expect(toggle).toHaveAttribute("aria-pressed", "true");
    expect(toggle).toBeDisabled();

    // That GET was issued after the PUT, so the confirmation is ambiguous: the
    // reconcile GET (the server has applied the PUT by now) settles it.
    getReport.mockResolvedValueOnce(report(savedR1, rows));
    put.resolve(savedR1);
    await waitFor(() => expect(getReport).toHaveBeenCalledTimes(3));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Убрать из сохранённых" })).toBeEnabled(),
    );
    expect(screen.getByRole("button", { name: "Убрать из сохранённых" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("Save from the fullscreen dialog survives a list refresh issued earlier", async () => {
    const user = userEvent.setup();
    renderPanel("c1", <Refresher highlight="r1" />);
    await screen.findByRole("heading", { name: "Отчёты чата (2)" });
    const stale = deferred<ReportCard[]>();
    listChatReports.mockReturnValueOnce(stale.promise);
    await user.click(screen.getByRole("button", { name: "refresh" }));

    await user.click(screen.getByRole("button", { name: /Итоги сезона/ }));
    await screen.findByRole("heading", { level: 2, name: "Итоги сезона" });
    await user.click(screen.getByRole("button", { name: "На весь экран" }));
    const dialog = screen.getByRole("dialog", { name: "Итоги сезона" });
    await user.click(within(dialog).getByRole("button", { name: "Сохранить" }));
    await waitFor(() =>
      expect(within(dialog).getByRole("button", { name: "Убрать из сохранённых" })).toBeEnabled(),
    );

    stale.resolve([unsavedR1, r2]);
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    await user.click(screen.getByRole("button", { name: "К списку" }));
    await screen.findByRole("heading", { name: "Отчёты чата (2)" });
    expect(saveButtonIn(cards()[0]!)).toHaveAttribute("aria-pressed", "true");
  });
});

describe("ReportsPanel orderings: chat switch", () => {
  it("switching chats never shows the previous chat's cards, even while the new list loads", async () => {
    const pending = deferred<ReportCard[]>();
    const { rerender } = render(<Tree chatId="c1" />);
    await screen.findByRole("heading", { name: "Отчёты чата (2)" });

    listChatReports.mockReturnValueOnce(pending.promise);
    rerender(<Tree chatId="c2" />);

    expect(screen.queryByRole("button", { name: /Итоги сезона/ })).toBeNull();
    expect(cards()).toHaveLength(0);
    expect(screen.getByRole("heading", { name: "Отчёты чата (0)" })).toBeInTheDocument();
    expect(screen.getByText("Загружаю отчёты…")).toBeInTheDocument();
    await waitFor(() => expect(listChatReports).toHaveBeenCalledWith("c2"));

    pending.resolve(c2Cards);
    await screen.findByRole("button", { name: /Чужой отчёт/ });
    expect(screen.queryByRole("button", { name: /Итоги сезона/ })).toBeNull();
  });

  it("a late list response of the previous chat is discarded", async () => {
    const user = userEvent.setup();
    const lateC1 = deferred<ReportCard[]>();
    const { rerender } = render(<Tree chatId="c1" extra={<Refresher highlight="r1" />} />);
    await screen.findByRole("heading", { name: "Отчёты чата (2)" });
    listChatReports.mockReturnValueOnce(lateC1.promise);
    await user.click(screen.getByRole("button", { name: "refresh" }));

    rerender(<Tree chatId="c2" extra={<Refresher highlight="r1" />} />);
    await screen.findByRole("button", { name: /Чужой отчёт/ });

    lateC1.resolve(c1Cards);
    await waitFor(() => expect(listChatReports).toHaveBeenCalledTimes(3));
    expect(screen.getByRole("heading", { name: "Отчёты чата (1)" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Итоги сезона/ })).toBeNull();
    expect(cards()[0]).not.toHaveClass("is-highlighted");
  });

  it("switching chats closes the preview and the fullscreen dialog; returning lands on the list without the old highlight", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<Tree chatId="c1" extra={<Refresher highlight="r2" />} />);
    await screen.findByRole("heading", { name: "Отчёты чата (2)" });
    await user.click(screen.getByRole("button", { name: "refresh" }));
    await waitFor(() => expect(cards()[1]).toHaveClass("is-highlighted"));
    await user.click(screen.getByRole("button", { name: /Итоги сезона/ }));
    await screen.findByRole("heading", { level: 2, name: "Итоги сезона" });
    await user.click(screen.getByRole("button", { name: "На весь экран" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    rerender(<Tree chatId="c2" extra={<Refresher highlight="r2" />} />);

    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByRole("heading", { level: 2, name: "Итоги сезона" })).toBeNull();
    expect(screen.queryByRole("button", { name: "К списку" })).toBeNull();
    await screen.findByRole("button", { name: /Чужой отчёт/ });

    rerender(<Tree chatId="c1" extra={<Refresher highlight="r2" />} />);
    await screen.findByRole("button", { name: /Итоги сезона/ });
    expect(screen.queryByRole("button", { name: "К списку" })).toBeNull();
    expect(cards()[1]).not.toHaveClass("is-highlighted");
  });

  it("a report GET of the previous chat answered after the switch opens nothing", async () => {
    const user = userEvent.setup();
    const slow = deferred<Report>();
    getReport.mockReturnValueOnce(slow.promise);
    const { rerender } = render(<Tree chatId="c1" />);
    await screen.findByRole("heading", { name: "Отчёты чата (2)" });
    await user.click(screen.getByRole("button", { name: /Итоги сезона/ }));
    await screen.findByText("Загружаю отчёт…");

    rerender(<Tree chatId="c2" />);
    await screen.findByRole("button", { name: /Чужой отчёт/ });
    slow.resolve(report(unsavedR1, rows));

    await waitFor(() => expect(getReport).toHaveBeenCalledTimes(1));
    expect(screen.queryByRole("heading", { level: 2, name: "Итоги сезона" })).toBeNull();
    expect(screen.getByRole("button", { name: /Чужой отчёт/ })).toBeInTheDocument();
  });

  it("the «Отчёт не найден» notice does not follow to the next chat", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<Tree chatId="c1" extra={<Chip id="gone" />} />);
    await screen.findByRole("heading", { name: "Отчёты чата (2)" });
    await user.click(screen.getByRole("button", { name: "Отчёт: gone" }));
    await screen.findByRole("status");

    rerender(<Tree chatId="c2" extra={<Chip id="gone" />} />);

    expect(screen.queryByRole("status")).toBeNull();
    await screen.findByRole("button", { name: /Чужой отчёт/ });
    expect(screen.queryByRole("status")).toBeNull();
  });
});

describe("ReportsPanel orderings: refreshToken and fullscreen", () => {
  it("a refreshToken change of the same chat keeps the current cards visible while reloading", async () => {
    const pending = deferred<ReportCard[]>();
    const { rerender } = render(<Tree chatId="c1" refreshToken="run-1" />);
    await screen.findByRole("heading", { name: "Отчёты чата (2)" });

    listChatReports.mockReturnValueOnce(pending.promise);
    rerender(<Tree chatId="c1" refreshToken="run-2" />);

    await waitFor(() => expect(listChatReports).toHaveBeenCalledTimes(2));
    expect(cards()).toHaveLength(2);
    expect(listBusy()).toBe("true");

    pending.resolve([card({ id: "r3", title: "Новый отчёт" }), ...c1Cards]);
    await screen.findByRole("heading", { name: "Отчёты чата (3)" });
  });

  it("a refreshToken change while fullscreen keeps the dialog open", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<Tree chatId="c1" refreshToken="run-1" />);
    await screen.findByRole("heading", { name: "Отчёты чата (2)" });
    await user.click(screen.getByRole("button", { name: /Итоги сезона/ }));
    await screen.findByRole("heading", { level: 2, name: "Итоги сезона" });
    await user.click(screen.getByRole("button", { name: "На весь экран" }));

    rerender(<Tree chatId="c1" refreshToken="run-2" />);
    await waitFor(() => expect(listChatReports).toHaveBeenCalledTimes(2));

    expect(screen.getByRole("dialog", { name: "Итоги сезона" })).toHaveAttribute("open");
    expect(getReport).toHaveBeenCalledTimes(1);
  });
});

/*
 * Report timeline oracle - a model written independently of the panel. A mock
 * server holds the report: its bookmark and its content version; a third actor
 * flips the bookmark ("foreign") or Updates the report ("update", version + 1)
 * between events without telling the UI. One clock of "moments": every request
 * takes its moment when it is ISSUED (the server answers with its state of that
 * moment, however late the response arrives), every PUT/DELETE takes one when
 * issued, one when the server EXECUTES it ("execute" - unknown to the UI,
 * anywhere between the issue and the delivery of the response) and one when
 * its response is delivered. Two independent facts:
 *  - the bookmark: the server's bookmark as of the newest moment the UI has
 *    heard from (a response's issue moment, a mutation's confirmation moment),
 *    with the in-flight optimistic value on top while a mutation is pending; a
 *    failed mutation reverts to that value. A confirmation is AMBIGUOUS when
 *    any observation of the report was issued after the mutation (learned or
 *    still in flight): the UI cannot know whether the server executed the
 *    mutation before or after what that observation saw, so the confirmation
 *    must not override a learned newer observation, and the UI reconciles with
 *    a report GET issued after the confirmation - whose answer is the truth.
 *  - the content (version): the highest version the UI has seen in any
 *    response - a PUT response carries the content of its EXECUTION moment, a
 *    confirmation adds no content, and a version never goes back.
 *  - gone: another visitor may delete the report ("delete": unsaved, deleted
 *    with its chat). Any observation issued after that - a list of the chat
 *    without the report, a report GET answered 404, the reconcile GET included
 *    - teaches the UI that the report is gone: no card, no preview; when the
 *    preview was open at that moment the notice "Отчёт не найден" shows until
 *    another report is opened or the chat is switched.
 * Arrival order never decides. A response the UI discards (a chat switch, a
 * closed preview) is simply never learned. Every response is a deferred
 * promise; no timers.
 */

type Mutation = "save-ok" | "save-fail" | "unsave-ok" | "unsave-fail";
type Held = "list" | "report";
type Step =
  | { kind: "mutate"; m: Mutation; deferred?: boolean }
  /* the server executes the pending mutation now (before its response is delivered) */
  | { kind: "execute" }
  /* the pending mutation's response is delivered (executing it first if not yet) */
  | { kind: "settle" }
  | { kind: "foreign" }
  /* another visitor's Update: version + 1 with a new date and row count */
  | { kind: "update" }
  /* another visitor unsaves the report and deletes its chat: the report is gone */
  | { kind: "delete" }
  /* a list GET whose response is held until `resolve-list` */
  | { kind: "issue-list" }
  | { kind: "resolve-list" }
  /* a list GET answered at once */
  | { kind: "new-list" }
  /* a report GET whose response is held until `resolve-report`; the preview stays open */
  | { kind: "issue-report" }
  | { kind: "resolve-report" }
  /* a report GET answered at once, then back to the list */
  | { kind: "report" }
  /* «К списку» while the report GET is still held: its response is discarded */
  | { kind: "back" }
  /* a report GET answered at once; the preview STAYS open until `close` */
  | { kind: "open" }
  | { kind: "close" }
  /* the fullscreen dialog of the open preview */
  | { kind: "fullscreen" }
  | { kind: "unfullscreen" }
  | { kind: "switch-away" }
  | { kind: "switch-back" };

const NETWORK = () => new ApiError(0, "network", "Связь с сервером потеряна");
const isSave = (m: Mutation) => m.startsWith("save");
const isOk = (m: Mutation) => m.endsWith("ok");
const stepsFrom = (saved: boolean): Mutation[] =>
  saved ? ["unsave-ok", "unsave-fail"] : ["save-ok", "save-fail"];

interface ServerReport {
  saved: boolean;
  version: number;
  deleted: boolean;
}

/** The mock server's card of r1 for a state; versions above 1 carry a new date and row count. */
const r1At = ({ saved, version }: ServerReport): ReportCard => {
  const base = saved ? savedR1 : unsavedR1;
  return version === 1
    ? base
    : { ...base, version, generated_at: "2026-09-30T08:00:00Z", row_count: 2 + version };
};

/** Pure model of what the panel must show; also used to generate valid sequences. */
class Oracle {
  server: ServerReport;
  private now = 0;
  /** `history[t]` = the server's report right after moment `t`. */
  private readonly history: ServerReport[];
  /** The newest bookmark fact the UI has learned: its moment and its value. */
  private heard = 0;
  private heardSaved: boolean;
  /** The highest content version the UI has seen. */
  private knownVersion: number;
  private readonly held = new Map<Held, number>();
  private pendingMutation: { m: Mutation; issued: number; executedAt: number | null } | null =
    null;
  /** Whether the last delivered confirmation was ambiguous and reconciled. */
  reconciled = false;
  /** The UI has learned that the report is gone (sticky). */
  gone = false;
  /** The not-found notice is showing: the preview was open when the UI learned it. */
  noticeShown = false;
  private previewOpen = false;

  constructor(initial: boolean) {
    this.server = { saved: initial, version: 1, deleted: false };
    this.history = [this.server];
    this.heardSaved = initial;
    this.knownVersion = 1;
  }

  /** What the star must show right now. */
  displayed(): boolean {
    return this.pendingMutation === null ? this.heardSaved : isSave(this.pendingMutation.m);
  }

  /** The version every surface must show right now. */
  displayedVersion(): number {
    return this.knownVersion;
  }

  apply(step: Step): void {
    switch (step.kind) {
      case "mutate": {
        const issued = this.moment();
        this.pendingMutation = { m: step.m, issued, executedAt: null };
        if (step.deferred !== true) {
          this.execute();
          this.deliver();
        }
        break;
      }
      case "execute":
        this.execute();
        break;
      case "settle":
        this.execute();
        this.deliver();
        break;
      case "foreign":
        this.server = { ...this.server, saved: !this.server.saved };
        break;
      case "update":
        this.server = { ...this.server, version: this.server.version + 1 };
        break;
      case "delete":
        this.server = { ...this.server, saved: false, deleted: true };
        break;
      case "issue-list":
        this.held.set("list", this.moment());
        break;
      case "issue-report":
        this.openPreview();
        this.held.set("report", this.moment());
        break;
      case "resolve-list":
        this.learn(this.held.get("list")!);
        this.held.delete("list");
        break;
      case "resolve-report":
        this.learn(this.held.get("report")!);
        this.held.delete("report");
        // The harness goes back to the list right after a held report settles.
        this.previewOpen = false;
        break;
      case "report":
      case "open":
        this.openPreview();
        this.learn(this.moment());
        if (step.kind === "report") {
          this.previewOpen = false;
        }
        break;
      case "new-list":
      case "switch-back":
        this.learn(this.moment());
        break;
      case "back":
      case "close":
        this.previewOpen = false;
        break;
      case "switch-away":
        this.previewOpen = false;
        this.noticeShown = false;
        break;
      case "fullscreen":
      case "unfullscreen":
        break;
    }
  }

  /** Opening a preview clears the notice; a gone report closes it again at once. */
  private openPreview(): void {
    this.previewOpen = true;
    this.noticeShown = false;
  }

  /** The UI discarded the held response (chat switch, closed preview): never learned. */
  discard(kind: Held): void {
    this.held.delete(kind);
  }

  private moment(): number {
    this.now += 1;
    this.history[this.now] = this.server;
    return this.now;
  }

  /** A response: the bookmark and the content of its issue moment - or that the report is gone. */
  private learn(moment: number): void {
    if (this.history[moment]!.deleted) {
      this.gone = true;
      if (this.previewOpen) {
        this.noticeShown = true;
        this.previewOpen = false;
      }
      return;
    }
    this.learnBookmark(moment);
    this.learnContent(moment);
  }

  /** Learning the server state of an older moment adds nothing to newer knowledge. */
  private learnBookmark(moment: number, saved = this.history[moment]!.saved): void {
    if (moment > this.heard) {
      this.heard = moment;
      this.heardSaved = saved;
    }
  }

  /** A version never goes back. */
  private learnContent(moment: number): void {
    this.knownVersion = Math.max(this.knownVersion, this.history[moment]!.version);
  }

  /** The server executes the pending mutation (a failing one never reaches it). */
  private execute(): void {
    const pending = this.pendingMutation!;
    if (!isOk(pending.m) || pending.executedAt !== null) {
      return;
    }
    this.server = { ...this.server, saved: isSave(pending.m) };
    pending.executedAt = this.moment();
  }

  private deliver(): void {
    const { m, issued, executedAt } = this.pendingMutation!;
    this.pendingMutation = null;
    this.reconciled = false;
    if (!isOk(m)) {
      return;
    }
    const observedAfter =
      this.heard > issued || [...this.held.values()].some((moment) => moment > issued);
    if (observedAfter) {
      // Ambiguous: the reconcile GET issued after the confirmation tells the truth.
      this.learn(this.moment());
      this.reconciled = true;
    } else {
      // The confirmation is the freshest fact: what the mutation did.
      this.learnBookmark(this.moment(), isSave(m));
    }
    // A PUT response's card is the content of the execution moment; a DELETE carries none.
    if (isSave(m)) {
      this.learnContent(executedAt!);
    }
  }
}

function simulateDisplayed(initial: boolean, steps: Step[]): boolean {
  const o = new Oracle(initial);
  for (const s of steps) {
    o.apply(s);
  }
  return o.displayed();
}

const starOf = (el: HTMLElement) => el.getAttribute("aria-pressed") === "true";

/**
 * A response held by the test: the snapshot is what the server had when the
 * request was issued - or the error it answered with (a 404 for a gone report).
 */
interface HeldResponse<T> {
  d: ReturnType<typeof deferred<T>>;
  snapshot: T;
  error?: ApiError;
}

const NOT_FOUND = () => new ApiError(404, "not_found", "Отчёт не найден");

/** Settles a held response and flushes the panel's handlers (registered earlier, so they run first). */
async function settleHeld<T>(held: HeldResponse<T>): Promise<void> {
  await act(async () => {
    if (held.error !== undefined) {
      held.d.reject(held.error);
      await held.d.promise.catch(() => undefined);
    } else {
      held.d.resolve(held.snapshot);
      await held.d.promise;
    }
  });
}

async function runTimeline(initial: boolean, steps: Step[]) {
  const user = userEvent.setup();
  const oracle = new Oracle(initial);
  const extra = (
    <>
      <Refresher highlight="r1" />
      <Chip id="r1" />
    </>
  );
  const tree = (chatId: string) => <Tree chatId={chatId} extra={extra} />;
  /** The chat's list as the server has it now: a deleted report is simply absent. */
  const listNow = () => (oracle.server.deleted ? [r2] : [r1At(oracle.server), r2]);
  listChatReports.mockImplementation((chatId) =>
    Promise.resolve(chatId === "c1" ? listNow() : c2Cards),
  );
  getReport.mockImplementation(() =>
    oracle.server.deleted
      ? Promise.reject(NOT_FOUND())
      : Promise.resolve(report(r1At(oracle.server), rows)),
  );
  const { rerender } = render(tree("c1"));
  await screen.findByRole("heading", { name: "Отчёты чата (2)" });
  expect(starOf(saveButtonIn(cards()[0]!))).toBe(initial);

  let heldList: HeldResponse<ReportCard[]> | null = null;
  let heldReport: HeldResponse<Report> | null = null;
  /** The mutation in flight: the mock server executes it and delivers its response separately. */
  let heldMutation: { m: Mutation; execute: () => void; deliver: () => void } | null = null;
  let away = false;
  let previewOpen = false;
  let previewLoading = false;
  let fullscreen = false;

  /**
   * Every element showing r1's star right now: the card in list mode, the
   * preview toolbar, plus the dialog's own toggle in fullscreen. The count is
   * part of the contract: a surface that silently stops rendering the star
   * would otherwise pass every check.
   */
  const expectedStars = () =>
    away || oracle.gone ? 0 : !previewOpen ? 1 : previewLoading ? 0 : fullscreen ? 2 : 1;
  /** r1's card in the list, if the list shows one. */
  const r1Card = (): HTMLElement | null =>
    within(panel()).queryByRole("button", { name: /Итоги сезона/ })?.closest("li") ?? null;
  const r1Stars = (): HTMLElement[] => {
    if (away) {
      return [];
    }
    if (!previewOpen) {
      const item = r1Card();
      return item === null ? [] : [saveButtonIn(item)];
    }
    return within(panel()).queryAllByRole("button", { name: /Сохранить|Убрать из сохранённых/ });
  };
  /** The star the user acts on: the dialog's in fullscreen, else the only one. */
  const r1Star = (): HTMLElement => r1Stars().at(-1)!;

  /**
   * Every element showing r1's version right now: the card's «Версия N» meta
   * (only above version 1), the inline preview's or the dialog's «Версия N».
   */
  const r1Versions = (): HTMLElement[] => {
    if (away || (previewOpen && previewLoading)) {
      return [];
    }
    const scope = previewOpen ? panel() : r1Card();
    return scope === null ? [] : within(scope).queryAllByText(/^Версия \d+$/);
  };
  const expectedVersions = () =>
    away || oracle.gone || (previewOpen && previewLoading)
      ? 0
      : previewOpen || oracle.displayedVersion() > 1
        ? 1
        : 0;

  const check = async (label: string) => {
    if (oracle.gone) {
      // The panel closed the preview (and its dialog) by itself.
      previewOpen = false;
      previewLoading = false;
      fullscreen = false;
    }
    const expected = oracle.displayed();
    const versionText = `Версия ${String(oracle.displayedVersion())}`;
    await waitFor(() => {
      const stars = r1Stars();
      expect(stars, label).toHaveLength(expectedStars());
      for (const star of stars) {
        expect(starOf(star), label).toBe(expected);
      }
      expect(
        r1Versions().map((el) => el.textContent),
        label,
      ).toEqual(Array<string>(expectedVersions()).fill(versionText));
      if (!away) {
        expect(screen.queryByRole("dialog") !== null, `${label}: dialog`).toBe(fullscreen);
        expect(screen.queryByRole("button", { name: "К списку" }) !== null, `${label}: preview`).toBe(
          previewOpen,
        );
      }
      const notice = within(panel()).queryByRole("status");
      expect(notice?.textContent ?? null, `${label}: notice`).toBe(
        !away && oracle.noticeShown ? "Отчёт не найден" : null,
      );
    });
  };

  const issueList = async (): Promise<HeldResponse<ReportCard[]>> => {
    const held = { d: deferred<ReportCard[]>(), snapshot: listNow() };
    listChatReports.mockReturnValueOnce(held.d.promise);
    await user.click(screen.getByRole("button", { name: "refresh" }));
    return held;
  };

  const issueReport = async (): Promise<HeldResponse<Report>> => {
    const held: HeldResponse<Report> = {
      d: deferred<Report>(),
      snapshot: report(r1At(oracle.server), rows),
      ...(oracle.server.deleted ? { error: NOT_FOUND() } : {}),
    };
    getReport.mockReturnValueOnce(held.d.promise);
    await user.click(screen.getByRole("button", { name: "Отчёт: r1" }));
    previewOpen = true;
    previewLoading = true;
    await screen.findByText("Загружаю отчёт…");
    return held;
  };

  const back = async () => {
    await user.click(screen.getByRole("button", { name: "К списку" }));
    previewOpen = false;
    previewLoading = false;
    await screen.findByRole("button", { name: /Итоги сезона/ });
  };

  /** Settles a held report GET; when its preview is still open, checks the preview star. */
  const resolveReport = async (held: HeldResponse<Report>, stay: boolean) => {
    await settleHeld(held);
    if (previewOpen && !oracle.gone) {
      await screen.findByRole("heading", { level: 2, name: "Итоги сезона" });
      previewLoading = false;
      expect(starOf(r1Star()), "preview star").toBe(oracle.displayed());
      if (!stay) {
        await back();
      }
    }
  };

  for (const step of steps) {
    switch (step.kind) {
      case "mutate": {
        const m = step.m;
        // The mock server executes the mutation at an explicit moment (`execute`,
        // or at delivery when the sequence has none); a PUT answers with the card
        // as the server had it right after executing - however late it lands.
        let response: ReportCard | null = null;
        const execute = () => {
          if (!isOk(m) || response !== null) {
            return;
          }
          oracle.server = { ...oracle.server, saved: isSave(m) };
          response = r1At(oracle.server);
        };
        if (isSave(m)) {
          const d = deferred<ReportCard>();
          saveReport.mockReturnValueOnce(d.promise);
          heldMutation = {
            m,
            execute,
            deliver: () => {
              execute();
              if (isOk(m)) {
                d.resolve(response!);
              } else {
                d.reject(NETWORK());
              }
            },
          };
        } else {
          const d = deferred<void>();
          unsaveReport.mockReturnValueOnce(d.promise);
          heldMutation = {
            m,
            execute,
            deliver: () => {
              execute();
              if (isOk(m)) {
                d.resolve();
              } else {
                d.reject(NETWORK());
              }
            },
          };
        }
        expect(starOf(r1Star())).toBe(oracle.displayed());
        await user.click(r1Star());
        oracle.apply(step);
        if (step.deferred === true) {
          for (const star of r1Stars()) {
            expect(starOf(star)).toBe(isSave(m));
            expect(star).toBeDisabled();
          }
        } else {
          heldMutation.deliver();
          heldMutation = null;
          await waitFor(() => expect(r1Star()).toBeEnabled());
          expect(screen.queryByRole("alert") !== null).toBe(!isOk(m));
        }
        break;
      }
      case "execute":
        heldMutation!.execute();
        oracle.apply(step);
        break;
      case "settle": {
        const held = heldMutation!;
        heldMutation = null;
        held.deliver();
        oracle.apply(step);
        if (!away && !(previewOpen && previewLoading) && !oracle.gone) {
          await waitFor(() => expect(r1Star()).toBeEnabled());
          expect(screen.queryByRole("alert") !== null).toBe(!isOk(held.m));
        }
        if (oracle.reconciled && !oracle.gone) {
          // Ambiguous confirmation: after the reconcile GET the UI equals the
          // server itself, whichever execution order the sequence chose.
          expect(oracle.displayed()).toBe(oracle.server.saved);
          await waitFor(() => {
            for (const star of r1Stars()) {
              expect(starOf(star), "true server state after reconcile").toBe(oracle.server.saved);
            }
          });
        }
        break;
      }
      case "foreign":
      case "update":
      case "delete":
        oracle.apply(step);
        break;
      case "issue-list":
        heldList = await issueList();
        oracle.apply(step);
        break;
      case "resolve-list": {
        const held = heldList!;
        heldList = null;
        await settleHeld(held);
        if (away) {
          // Discarded by the panel while another chat is open: never learned.
          oracle.discard("list");
        } else {
          oracle.apply(step);
        }
        break;
      }
      case "new-list": {
        const held = await issueList();
        oracle.apply(step);
        await settleHeld(held);
        break;
      }
      case "issue-report":
        heldReport = await issueReport();
        oracle.apply(step);
        break;
      case "resolve-report": {
        const held = heldReport!;
        heldReport = null;
        if (previewOpen) {
          oracle.apply(step);
        } else {
          // The preview was closed (or the chat switched): the answer is discarded.
          oracle.discard("report");
        }
        await resolveReport(held, false);
        break;
      }
      case "report":
      case "open": {
        const held = await issueReport();
        oracle.apply(step);
        await resolveReport(held, step.kind === "open");
        break;
      }
      case "back":
      case "close":
        await back();
        oracle.apply(step);
        break;
      case "fullscreen":
        await user.click(screen.getByRole("button", { name: "На весь экран" }));
        expect(screen.getByRole("dialog", { name: "Итоги сезона" })).toHaveAttribute("open");
        fullscreen = true;
        oracle.apply(step);
        break;
      case "unfullscreen":
        // Focus may sit outside the dialog after a refresh click, so the button, not Escape.
        await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Свернуть" }));
        await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
        fullscreen = false;
        oracle.apply(step);
        break;
      case "switch-away":
        rerender(tree("c2"));
        away = true;
        previewOpen = false;
        previewLoading = false;
        fullscreen = false;
        await screen.findByRole("button", { name: /Чужой отчёт/ });
        expect(screen.queryByRole("dialog")).toBeNull();
        oracle.apply(step);
        break;
      case "switch-back": {
        const held = { d: deferred<ReportCard[]>(), snapshot: listNow() };
        listChatReports.mockReturnValueOnce(held.d.promise);
        rerender(tree("c1"));
        away = false;
        oracle.apply(step);
        await settleHeld(held);
        // r2 is always there; r1 may be gone by now.
        await screen.findByRole("button", { name: /Лучшие игроки/ });
        break;
      }
    }
    await check(`after ${step.kind}${"m" in step ? ` ${step.m}` : ""}`);
  }

  // A final list issued after everything reconciles the UI with the server,
  // in the open preview (and its dialog) as well as on the card.
  const final = await issueList();
  oracle.apply({ kind: "new-list" });
  await settleHeld(final);
  await check("after the final list");
  for (const star of r1Stars()) {
    expect(starOf(star)).toBe(oracle.server.saved);
  }
  if (oracle.server.deleted) {
    expect(r1Card()).toBeNull();
    return;
  }
  if (previewOpen) {
    if (fullscreen) {
      await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Свернуть" }));
      await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
      fullscreen = false;
    }
    await back();
  }
  expect(starOf(saveButtonIn(r1Card()!))).toBe(oracle.server.saved);
}

interface Case {
  name: string;
  initial: boolean;
  steps: Step[];
}

const describeSteps = (steps: Step[]) =>
  steps
    .map((s) => (s.kind === "mutate" ? `${s.m}${s.deferred === true ? "(pending)" : ""}` : s.kind))
    .join(" > ");

function withObservation(kind: "old-list" | "new-list" | "report"): {
  pre: Step[];
  post: Step[];
} {
  return kind === "old-list"
    ? { pre: [{ kind: "issue-list" }], post: [{ kind: "resolve-list" }] }
    : { pre: [], post: [{ kind }] };
}

const cases: Case[] = [];

/* Table 1: our own 1-2 mutations x one response around them, settled or mid-flight. */
for (const initial of [false, true]) {
  for (const first of stepsFrom(initial)) {
    const seqs: Mutation[][] = [[first]];
    const afterFirst = simulateDisplayed(initial, [{ kind: "mutate", m: first }]);
    for (const second of stepsFrom(afterFirst)) {
      seqs.push([first, second]);
    }
    for (const seq of seqs) {
      for (const kind of ["old-list", "new-list", "report"] as const) {
        const { pre, post } = withObservation(kind);
        const settled: Step[] = [...pre, ...seq.map((m) => ({ kind: "mutate", m }) as Step), ...post];
        cases.push({ name: `own | ${describeSteps(settled)}`, initial, steps: settled });
        if (kind !== "report") {
          const head = seq.slice(0, -1).map((m) => ({ kind: "mutate", m }) as Step);
          const last: Step = { kind: "mutate", m: seq[seq.length - 1]!, deferred: true };
          const mid: Step[] = [...pre, ...head, last, ...post, { kind: "settle" }];
          cases.push({ name: `own | ${describeSteps(mid)}`, initial, steps: mid });
        }
      }
    }
  }
}

/* Table 2: a foreign visitor flips the bookmark after our confirmed mutation; we may
   or may not observe it before our next mutation, which then succeeds or fails. */
for (const initial of [false, true]) {
  const first = stepsFrom(initial).find(isOk)!;
  for (const observe1 of ["none", "new-list", "report"] as const) {
    const prefix: Step[] = [{ kind: "mutate", m: first }, { kind: "foreign" }];
    if (observe1 !== "none") {
      prefix.push({ kind: observe1 });
    }
    const shown = simulateDisplayed(initial, prefix);
    for (const second of stepsFrom(shown)) {
      for (const kind of ["old-list", "new-list", "report"] as const) {
        const { pre, post } = withObservation(kind);
        const settled: Step[] = [...pre, ...prefix, { kind: "mutate", m: second }, ...post];
        cases.push({ name: `foreign(${observe1}) | ${describeSteps(settled)}`, initial, steps: settled });
        if (kind !== "report") {
          const mid: Step[] = [
            ...pre,
            ...prefix,
            { kind: "mutate", m: second, deferred: true },
            ...post,
            { kind: "settle" },
          ];
          cases.push({ name: `foreign(${observe1}) | ${describeSteps(mid)}`, initial, steps: mid });
        }
      }
    }
  }
}

/* Table 3: two server observations of r1 resolved in the OPPOSITE order of issue
   with a foreign flip between them - list/report in both orders, two lists, two
   reports (the older one closed with "back"), a chat switch - with and without our
   own confirmed mutation before, and with our mutation (ok/fail, settled or still
   in flight) between the newer observation and the older resolution. */
const reorderings: { name: string; steps: Step[] }[] = [
  {
    name: "older list after newer report",
    steps: [
      { kind: "issue-list" },
      { kind: "foreign" },
      { kind: "report" },
      { kind: "resolve-list" },
    ],
  },
  {
    name: "older report after newer list",
    steps: [
      { kind: "issue-report" },
      { kind: "foreign" },
      { kind: "new-list" },
      { kind: "resolve-report" },
    ],
  },
  {
    name: "older list after newer list",
    steps: [
      { kind: "issue-list" },
      { kind: "foreign" },
      { kind: "new-list" },
      { kind: "resolve-list" },
    ],
  },
  {
    name: "older report after newer report",
    steps: [
      { kind: "issue-report" },
      { kind: "back" },
      { kind: "foreign" },
      { kind: "report" },
      { kind: "resolve-report" },
    ],
  },
  {
    name: "older list across a chat switch",
    steps: [
      { kind: "issue-list" },
      { kind: "foreign" },
      { kind: "switch-away" },
      { kind: "resolve-list" },
      { kind: "switch-back" },
    ],
  },
];
for (const initial of [false, true]) {
  for (const own of ["none", "confirmed"] as const) {
    const prefix: Step[] =
      own === "none" ? [] : [{ kind: "mutate", m: stepsFrom(initial).find(isOk)! }];
    for (const r of reorderings) {
      const steps = [...prefix, ...r.steps];
      cases.push({ name: `reorder(${own}) ${r.name} | ${describeSteps(steps)}`, initial, steps });
    }
    const head: Step[] = [...prefix, { kind: "issue-list" }, { kind: "foreign" }, { kind: "report" }];
    const shown = simulateDisplayed(initial, head);
    for (const m of stepsFrom(shown)) {
      const settled: Step[] = [...head, { kind: "mutate", m }, { kind: "resolve-list" }];
      cases.push({ name: `reorder(${own}) | ${describeSteps(settled)}`, initial, steps: settled });
      const mid: Step[] = [
        ...head,
        { kind: "mutate", m, deferred: true },
        { kind: "resolve-list" },
        { kind: "settle" },
      ];
      cases.push({ name: `reorder(${own}) | ${describeSteps(mid)}`, initial, steps: mid });
    }
  }
}

describe("ReportsPanel orderings: two server observations of one report", () => {
  it("round-4 reviewer sequence: our Unsave ok, a list GET is held, another visitor saves, a newer report GET shows saved, the older list lands -> card and preview stay saved", async () => {
    const user = userEvent.setup();
    listChatReports.mockResolvedValueOnce([savedR1, r2]);
    renderPanel(
      "c1",
      <>
        <Refresher highlight="r1" />
        <Chip id="r1" />
      </>,
    );
    await screen.findByRole("heading", { name: "Отчёты чата (2)" });
    expect(saveButtonIn(cards()[0]!)).toHaveAttribute("aria-pressed", "true");

    await user.click(saveButtonIn(cards()[0]!));
    expect(unsaveReport).toHaveBeenCalledWith("r1");
    await waitFor(() => expect(saveButtonIn(cards()[0]!)).toBeEnabled());
    expect(saveButtonIn(cards()[0]!)).toHaveAttribute("aria-pressed", "false");

    // The list GET sees the server still unsaved; its response is held.
    const older = { d: deferred<ReportCard[]>(), snapshot: [unsavedR1, r2] };
    listChatReports.mockReturnValueOnce(older.d.promise);
    await user.click(screen.getByRole("button", { name: "refresh" }));

    // Another visitor saves it; a report GET issued after that sees it saved.
    getReport.mockResolvedValueOnce(report(savedR1, rows));
    await user.click(screen.getByRole("button", { name: "Отчёт: r1" }));
    await screen.findByRole("heading", { level: 2, name: "Итоги сезона" });
    expect(screen.getByRole("button", { name: "Убрать из сохранённых" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await user.click(screen.getByRole("button", { name: "К списку" }));
    await screen.findByRole("button", { name: /Итоги сезона/ });
    expect(saveButtonIn(cards()[0]!)).toHaveAttribute("aria-pressed", "true");

    // The older list lands last: it must not undo the newer-issued observation.
    await settleHeld(older);
    await waitFor(() => expect(listBusy()).toBe("false"));
    expect(saveButtonIn(cards()[0]!)).toHaveAttribute("aria-pressed", "true");
    expect(saveButtonIn(cards()[0]!)).toHaveAccessibleName("Убрать из сохранённых");

    getReport.mockResolvedValueOnce(report(savedR1, rows));
    await user.click(screen.getByRole("button", { name: "Отчёт: r1" }));
    await screen.findByRole("heading", { level: 2, name: "Итоги сезона" });
    expect(screen.getByRole("button", { name: "Убрать из сохранённых" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("the reverse order: a held report GET must not undo a later-issued list that saw another visitor's Save", async () => {
    const user = userEvent.setup();
    renderPanel(
      "c1",
      <>
        <Refresher highlight="r1" />
        <Chip id="r1" />
      </>,
    );
    await screen.findByRole("heading", { name: "Отчёты чата (2)" });
    expect(saveButtonIn(cards()[0]!)).toHaveAttribute("aria-pressed", "false");

    const older = { d: deferred<Report>(), snapshot: report(unsavedR1, rows) };
    getReport.mockReturnValueOnce(older.d.promise);
    await user.click(screen.getByRole("button", { name: "Отчёт: r1" }));
    await screen.findByText("Загружаю отчёт…");

    // Another visitor saves it; a list GET issued after that sees it saved.
    const newer = { d: deferred<ReportCard[]>(), snapshot: [savedR1, r2] };
    listChatReports.mockReturnValueOnce(newer.d.promise);
    await user.click(screen.getByRole("button", { name: "refresh" }));
    await settleHeld(newer);

    await settleHeld(older);
    await screen.findByRole("heading", { level: 2, name: "Итоги сезона" });
    expect(screen.getByRole("button", { name: "Убрать из сохранённых" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    await user.click(screen.getByRole("button", { name: "К списку" }));
    await screen.findByRole("button", { name: /Итоги сезона/ });
    expect(saveButtonIn(cards()[0]!)).toHaveAttribute("aria-pressed", "true");
  });
});

/* Table 4: a list refresh (the `refreshToken` / reload path) while a preview is
   already READY - inline or fullscreen - x a foreign flip, our own mutation from
   that view (ok / fail / still pending across the refresh), a foreign flip seen
   and then our mutation, an older list resolved after a foreign flip, and a chat
   switch; every check covers the card, the preview toolbar and the dialog. */
for (const initial of [false, true]) {
  for (const view of ["preview", "fullscreen"] as const) {
    const opened: Step[] =
      view === "preview" ? [{ kind: "open" }] : [{ kind: "open" }, { kind: "fullscreen" }];
    const add = (tail: Step[]) => {
      const steps = [...opened, ...tail];
      cases.push({ name: `ready ${view} | ${describeSteps(steps)}`, initial, steps });
    };
    add([{ kind: "foreign" }, { kind: "new-list" }]);
    add([{ kind: "issue-list" }, { kind: "foreign" }, { kind: "resolve-list" }]);
    for (const m of stepsFrom(initial)) {
      add([{ kind: "mutate", m }, { kind: "new-list" }]);
      add([{ kind: "mutate", m, deferred: true }, { kind: "new-list" }, { kind: "settle" }]);
    }
    for (const m of stepsFrom(!initial)) {
      add([{ kind: "foreign" }, { kind: "new-list" }, { kind: "mutate", m }]);
    }
    add([{ kind: "foreign" }, { kind: "switch-away" }, { kind: "switch-back" }]);
    if (view === "fullscreen") {
      add([{ kind: "foreign" }, { kind: "new-list" }, { kind: "unfullscreen" }, { kind: "close" }]);
    }
  }
}

/* Table 5: our PUT/DELETE response is DELAYED while another visitor Updates the
   report (version + 1), flips the bookmark, or both, and a list refresh or a chat
   switch brings the newer content in before the old response lands - from the
   list, the inline preview and the fullscreen dialog; ok and failed responses.
   The delayed response must confirm the bookmark only, never the old content. */
const delayedTails: Step[][] = [
  [{ kind: "update" }, { kind: "new-list" }, { kind: "settle" }],
  [{ kind: "foreign" }, { kind: "new-list" }, { kind: "settle" }],
  [{ kind: "update" }, { kind: "foreign" }, { kind: "new-list" }, { kind: "settle" }],
  [{ kind: "new-list" }, { kind: "settle" }],
  [{ kind: "update" }, { kind: "switch-away" }, { kind: "settle" }, { kind: "switch-back" }],
];
for (const initial of [false, true]) {
  for (const view of ["list", "preview", "fullscreen"] as const) {
    const opened: Step[] =
      view === "list"
        ? []
        : view === "preview"
          ? [{ kind: "open" }]
          : [{ kind: "open" }, { kind: "fullscreen" }];
    // From the list the preview is opened afterwards to read the content there too.
    const inspect: Step[] = view === "list" ? [{ kind: "report" }] : [];
    const add = (tail: Step[]) => {
      const steps = [...opened, ...tail, ...inspect];
      cases.push({ name: `delayed response from ${view} | ${describeSteps(steps)}`, initial, steps });
    };
    const ok = stepsFrom(initial).find(isOk)!;
    const fail = stepsFrom(initial).find((m) => !isOk(m))!;
    for (const tail of delayedTails) {
      add([{ kind: "mutate", m: ok, deferred: true }, ...tail]);
    }
    add([{ kind: "mutate", m: fail, deferred: true }, ...delayedTails[0]!]);
    // The mutation issued AFTER the Update: its response may carry the new content.
    add([{ kind: "update" }, { kind: "mutate", m: ok }]);
  }
}

/* Table 6: an Update from another tab seen through a list refresh or a report GET
   while the preview is open (re-fetch of the rows) or from the list. */
for (const initial of [false, true]) {
  const push = (name: string, steps: Step[]) =>
    cases.push({ name: `${name} | ${describeSteps(steps)}`, initial, steps });
  push("update seen from the list", [{ kind: "update" }, { kind: "new-list" }, { kind: "report" }]);
  push("update seen by opening", [{ kind: "update" }, { kind: "report" }]);
  push("update seen in the open preview", [{ kind: "open" }, { kind: "update" }, { kind: "new-list" }]);
  push("update seen in fullscreen", [
    { kind: "open" },
    { kind: "fullscreen" },
    { kind: "update" },
    { kind: "new-list" },
    { kind: "unfullscreen" },
    { kind: "close" },
  ]);
  push("older list after an update seen in the preview", [
    { kind: "open" },
    { kind: "issue-list" },
    { kind: "update" },
    { kind: "new-list" },
    { kind: "resolve-list" },
  ]);
}

/* Table 7: the confirmation of our PUT/DELETE is delayed while an observation
   of the report is issued after the mutation - so the UI cannot know whether the
   server executed the mutation before or after what the observation saw. The
   mock server executes it explicitly BEFORE (`execute` first) or AFTER the
   foreign change; after the confirmation and its reconcile GET the UI must equal
   the server in both orders. Observation through a list or a report GET,
   learned before the confirmation or still in flight at it; foreign Unsave/Save,
   Update or both; failed responses; from the list, the inline preview and the
   fullscreen dialog. */
for (const initial of [false, true]) {
  for (const view of ["list", "preview", "fullscreen"] as const) {
    const opened: Step[] =
      view === "list"
        ? []
        : view === "preview"
          ? [{ kind: "open" }]
          : [{ kind: "open" }, { kind: "fullscreen" }];
    const ok = stepsFrom(initial).find(isOk)!;
    const fail = stepsFrom(initial).find((m) => !isOk(m))!;
    const pendingOk: Step = { kind: "mutate", m: ok, deferred: true };
    const observations: Step[][] =
      view === "list" ? [[{ kind: "new-list" }], [{ kind: "report" }]] : [[{ kind: "new-list" }]];
    const add = (name: string, tail: Step[]) => {
      const steps = [...opened, ...tail];
      cases.push({ name: `delayed ack from ${view}, ${name} | ${describeSteps(steps)}`, initial, steps });
    };
    for (const obs of observations) {
      add("executed before the foreign flip", [pendingOk, { kind: "execute" }, { kind: "foreign" }, ...obs, { kind: "settle" }]);
      add("executed after the foreign flip", [pendingOk, { kind: "foreign" }, ...obs, { kind: "execute" }, { kind: "settle" }]);
      add("executed before an update", [pendingOk, { kind: "execute" }, { kind: "update" }, ...obs, { kind: "settle" }]);
      add("executed before an update and a flip", [
        pendingOk,
        { kind: "execute" },
        { kind: "foreign" },
        { kind: "update" },
        ...obs,
        { kind: "settle" },
      ]);
      add("failed after a foreign flip", [{ kind: "mutate", m: fail, deferred: true }, { kind: "foreign" }, ...obs, { kind: "settle" }]);
      add("executed before the flip, more changes after the reconcile", [
        pendingOk,
        { kind: "execute" },
        { kind: "foreign" },
        ...obs,
        { kind: "settle" },
        { kind: "foreign" },
        { kind: "new-list" },
      ]);
    }
    // The observation is still in flight when the confirmation lands.
    add("list still in flight at the ack", [
      pendingOk,
      { kind: "execute" },
      { kind: "foreign" },
      { kind: "issue-list" },
      { kind: "settle" },
      { kind: "resolve-list" },
    ]);
    if (view === "list") {
      add("report GET still in flight at the ack", [
        pendingOk,
        { kind: "execute" },
        { kind: "foreign" },
        { kind: "issue-report" },
        { kind: "settle" },
        { kind: "resolve-report" },
      ]);
    }
    // No observation after the mutation: the confirmation stands as the freshest fact.
    add("nothing observed after the mutation", [pendingOk, { kind: "execute" }, { kind: "foreign" }, { kind: "settle" }]);
  }
}

/* Table 8: another visitor deletes the report (unsaved, with its chat). Whatever
   observation issued after that reaches the panel first - a list without it, a
   report GET answered 404 (opening, re-opening, the reconcile GET after an
   ambiguous acknowledgement in either execution order), an older list resolved
   after a newer one, a chat switch - the card disappears; an open preview (inline
   or fullscreen) closes with the notice, which never follows to another chat. */
for (const initial of [false, true]) {
  for (const view of ["list", "preview", "fullscreen"] as const) {
    const opened: Step[] =
      view === "list"
        ? []
        : view === "preview"
          ? [{ kind: "open" }]
          : [{ kind: "open" }, { kind: "fullscreen" }];
    const ok = stepsFrom(initial).find(isOk)!;
    const pendingOk: Step = { kind: "mutate", m: ok, deferred: true };
    const add = (name: string, tail: Step[]) => {
      const steps = [...opened, ...tail];
      cases.push({ name: `gone from ${view}, ${name} | ${describeSteps(steps)}`, initial, steps });
    };
    add("seen through a list", [{ kind: "delete" }, { kind: "new-list" }]);
    add("seen through a held list", [{ kind: "delete" }, { kind: "issue-list" }, { kind: "resolve-list" }]);
    add("an older list with the report lands after the newer one without it", [
      { kind: "issue-list" },
      { kind: "delete" },
      { kind: "new-list" },
      { kind: "resolve-list" },
    ]);
    add("seen through the reconcile GET, executed before the deletion", [
      pendingOk,
      { kind: "execute" },
      { kind: "foreign" },
      { kind: "new-list" },
      { kind: "delete" },
      { kind: "settle" },
    ]);
    add("seen through the reconcile GET before an older held list arrives", [
      pendingOk,
      { kind: "execute" },
      { kind: "foreign" },
      { kind: "issue-list" },
      { kind: "delete" },
      { kind: "settle" },
      { kind: "resolve-list" },
    ]);
    add("seen through a list, then the chat is switched and back", [
      { kind: "delete" },
      { kind: "new-list" },
      { kind: "switch-away" },
      { kind: "switch-back" },
    ]);
    add("seen only after the chat is switched and back", [
      { kind: "delete" },
      { kind: "switch-away" },
      { kind: "switch-back" },
    ]);
    if (view === "list") {
      add("seen by opening it", [{ kind: "delete" }, { kind: "report" }]);
      add("seen by a held report GET", [{ kind: "delete" }, { kind: "issue-report" }, { kind: "resolve-report" }]);
      add("a report GET issued before the deletion still shows it; the next list removes it", [
        { kind: "issue-report" },
        { kind: "delete" },
        { kind: "resolve-report" },
        { kind: "new-list" },
      ]);
    }
  }
}

describe("ReportsPanel: a gone report (404 or missing from a newer list of this chat)", () => {
  const chipAndRefresher = (
    <>
      <Refresher highlight="r1" />
      <Chip id="r1" />
    </>
  );
  const refreshWith = async (user: ReturnType<typeof userEvent.setup>, snapshot: ReportCard[]) => {
    const newer = { d: deferred<ReportCard[]>(), snapshot };
    listChatReports.mockReturnValueOnce(newer.d.promise);
    await user.click(screen.getByRole("button", { name: "refresh" }));
    await settleHeld(newer);
  };
  const openR1 = async (user: ReturnType<typeof userEvent.setup>) => {
    await user.click(screen.getByRole("button", { name: "Отчёт: r1" }));
    await screen.findByRole("heading", { level: 2, name: "Итоги сезона" });
  };
  const expectClosedWithNotice = () => {
    expect(screen.getByRole("status")).toHaveTextContent("Отчёт не найден");
    expect(screen.queryByRole("button", { name: "К списку" })).toBeNull();
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByRole("heading", { name: "Параметры" })).toBeNull();
  };

  it("round-8 reviewer sequence: preview open, ambiguous Save ack, the report was deleted with its chat -> the reconcile GET's 404 closes the preview with the notice; no further GETs for it", async () => {
    const user = userEvent.setup();
    renderPanel("c1", chipAndRefresher);
    await screen.findByRole("heading", { name: "Отчёты чата (2)" });
    await openR1(user);

    const put = { d: deferred<ReportCard>(), snapshot: savedR1 };
    saveReport.mockReturnValueOnce(put.d.promise);
    await user.click(screen.getByRole("button", { name: "Сохранить" }));
    await refreshWith(user, [unsavedR1, r2]);

    // The chat is deleted: the reconcile GET and the list both answer 404.
    getReport.mockRejectedValueOnce(NOT_FOUND());
    listChatReports.mockRejectedValueOnce(new ApiError(404, "not_found", "Чат не найден"));
    await settleHeld(put);
    await waitFor(() => expect(getReport).toHaveBeenCalledTimes(2));
    await waitFor(() => expectClosedWithNotice());
    await waitFor(() => expect(listChatReports).toHaveBeenCalledTimes(3));
    expect(screen.getByRole("alert")).toHaveTextContent("Не удалось загрузить отчёты: Чат не найден");
    expect(getReport).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("button", { name: /Итоги сезона/ })).toBeNull();
  });

  it("404 from the reconcile GET while fullscreen: the dialog closes with the notice", async () => {
    const user = userEvent.setup();
    renderPanel("c1", chipAndRefresher);
    await screen.findByRole("heading", { name: "Отчёты чата (2)" });
    await openR1(user);
    await user.click(screen.getByRole("button", { name: "На весь экран" }));
    const dialog = screen.getByRole("dialog");
    const put = { d: deferred<ReportCard>(), snapshot: savedR1 };
    saveReport.mockReturnValueOnce(put.d.promise);
    await user.click(within(dialog).getByRole("button", { name: "Сохранить" }));
    await refreshWith(user, [unsavedR1, r2]);

    getReport.mockRejectedValueOnce(NOT_FOUND());
    listChatReports.mockResolvedValueOnce([r2]);
    await settleHeld(put);
    await waitFor(() => expectClosedWithNotice());
    await screen.findByRole("heading", { name: "Отчёты чата (1)" });
  });

  it("404 from the version re-fetch closes the preview with the notice", async () => {
    const user = userEvent.setup();
    renderPanel("c1", chipAndRefresher);
    await screen.findByRole("heading", { name: "Отчёты чата (2)" });
    await openR1(user);

    // The list carries version 2, so the preview re-fetches its rows; by then the
    // report is gone: the re-fetch answers 404 and the next list has no r1.
    getReport.mockRejectedValueOnce(NOT_FOUND());
    listChatReports.mockImplementation(() => Promise.resolve([r2]));
    await refreshWith(user, [{ ...unsavedR1, version: 2 }, r2]);
    await waitFor(() => expect(getReport).toHaveBeenCalledTimes(2));
    await waitFor(() => expectClosedWithNotice());
    await screen.findByRole("heading", { name: "Отчёты чата (1)" });
  });

  it("404 from the retry button (Повторить) after a failed load closes the preview with the notice", async () => {
    const user = userEvent.setup();
    getReport.mockRejectedValueOnce(new ApiError(0, "network", "Связь с сервером потеряна"));
    renderPanel("c1", chipAndRefresher);
    await screen.findByRole("heading", { name: "Отчёты чата (2)" });
    await user.click(screen.getByRole("button", { name: "Отчёт: r1" }));
    await screen.findByRole("alert");

    getReport.mockRejectedValueOnce(NOT_FOUND());
    listChatReports.mockResolvedValueOnce([r2]);
    await user.click(screen.getByRole("button", { name: "Повторить" }));
    await waitFor(() => expectClosedWithNotice());
    await screen.findByRole("heading", { name: "Отчёты чата (1)" });
  });

  it("a newer list of this chat without the open report closes the preview with the notice; an older one does not", async () => {
    const user = userEvent.setup();
    renderPanel("c1", chipAndRefresher);
    await screen.findByRole("heading", { name: "Отчёты чата (2)" });

    // A list issued before the report is opened, answered later without it: not newer, ignored.
    const older = { d: deferred<ReportCard[]>(), snapshot: [r2] };
    listChatReports.mockReturnValueOnce(older.d.promise);
    await user.click(screen.getByRole("button", { name: "refresh" }));
    await openR1(user);
    await settleHeld(older);
    expect(screen.getByRole("button", { name: "К списку" })).toBeInTheDocument();
    expect(screen.queryByRole("status")).toBeNull();

    await refreshWith(user, [r2]);
    await waitFor(() => expectClosedWithNotice());
    expect(screen.getByRole("heading", { name: "Отчёты чата (1)" })).toBeInTheDocument();
    expect(listChatReports).toHaveBeenCalledTimes(3);
  });

  it("a 404 for a report that is not open: no notice, the list is refreshed", async () => {
    const user = userEvent.setup();
    renderPanel("c1", chipAndRefresher);
    await screen.findByRole("heading", { name: "Отчёты чата (2)" });
    const put = { d: deferred<ReportCard>(), snapshot: savedR1 };
    saveReport.mockReturnValueOnce(put.d.promise);
    await user.click(saveButtonIn(cards()[0]!));
    await refreshWith(user, [unsavedR1, r2]);

    getReport.mockRejectedValueOnce(NOT_FOUND());
    listChatReports.mockResolvedValueOnce([r2]);
    await settleHeld(put);
    await screen.findByRole("heading", { name: "Отчёты чата (1)" });
    expect(screen.queryByRole("status")).toBeNull();
    expect(screen.queryByRole("button", { name: /Итоги сезона/ })).toBeNull();
  });

  it("the notice does not follow to the next chat and is gone when coming back", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<Tree chatId="c1" extra={chipAndRefresher} />);
    await screen.findByRole("heading", { name: "Отчёты чата (2)" });
    await openR1(user);
    await refreshWith(user, [r2]);
    await waitFor(() => expectClosedWithNotice());

    rerender(<Tree chatId="c2" extra={chipAndRefresher} />);
    expect(screen.queryByRole("status")).toBeNull();
    await screen.findByRole("button", { name: /Чужой отчёт/ });
    expect(screen.queryByRole("status")).toBeNull();

    rerender(<Tree chatId="c1" extra={chipAndRefresher} />);
    await screen.findByRole("button", { name: /Лучшие игроки/ });
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("disappearance cleanup: retry 404 keeps an already-dismissed highlight cleared", async () => {
    const user = userEvent.setup();
    function HighlightProbe() {
      return <span data-testid="highlight">{useReports().highlightId}</span>;
    }
    getReport.mockRejectedValueOnce(NETWORK());
    render(
      <ReportsProvider chatId="c1" highlightReportId="r1">
        <HighlightProbe />
        <ReportsPanel />
      </ReportsProvider>,
    );
    await screen.findByRole("heading", { name: "Отчёты чата (2)" });
    await user.click(screen.getByRole("button", { name: /Итоги сезона/ }));
    await screen.findByRole("alert");
    expect(screen.getByTestId("highlight")).toBeEmptyDOMElement();
    getReport.mockRejectedValueOnce(NOT_FOUND());
    listChatReports.mockResolvedValue([r2]);

    await user.click(screen.getByRole("button", { name: "Повторить" }));
    await screen.findByRole("status");

    expectClosedWithNotice();
    expect(screen.getByTestId("highlight")).toBeEmptyDOMElement();
  });

  it.each(["inline", "fullscreen"] as const)(
    "disappearance cleanup: a queued reconcile stops at 404 in %s",
    async (view) => {
      const user = userEvent.setup();
      renderPanel("c1", chipAndRefresher);
      await screen.findByRole("heading", { name: "Отчёты чата (2)" });
      await openR1(user);
      if (view === "fullscreen") {
        await user.click(screen.getByRole("button", { name: "На весь экран" }));
      }
      const scope = () => screen.queryByRole("dialog") ?? panel();
      const firstPut = { d: deferred<ReportCard>(), snapshot: savedR1 };
      const reconcile = deferred<Report>();
      saveReport.mockReturnValueOnce(firstPut.d.promise);
      await user.click(saveButtonIn(scope()));
      await refreshWith(user, [unsavedR1, r2]);
      getReport.mockReturnValueOnce(reconcile.promise);
      await settleHeld(firstPut);
      expect(getReport).toHaveBeenCalledTimes(2);

      // A second ambiguous ack queues another reconciliation behind the first.
      const secondPut = { d: deferred<ReportCard>(), snapshot: savedR1 };
      saveReport.mockReturnValueOnce(secondPut.d.promise);
      await user.click(saveButtonIn(scope()));
      await refreshWith(user, [unsavedR1, r2]);
      await settleHeld(secondPut);
      listChatReports.mockResolvedValue([r2]);
      await act(async () => {
        reconcile.reject(NOT_FOUND());
        await reconcile.promise.catch(() => undefined);
      });

      expectClosedWithNotice();
      expect(getReport).toHaveBeenCalledTimes(2);
      expect(screen.queryByRole("button", { name: /Итоги сезона/ })).toBeNull();
    },
  );

  it("disappearance cleanup: a late positive reconcile cannot revive a removed record", async () => {
    const user = userEvent.setup();
    renderPanel("c1", chipAndRefresher);
    await screen.findByRole("heading", { name: "Отчёты чата (2)" });
    await openR1(user);
    const firstPut = { d: deferred<ReportCard>(), snapshot: savedR1 };
    const reconcile = { d: deferred<Report>(), snapshot: report(unsavedR1, rows) };
    saveReport.mockReturnValueOnce(firstPut.d.promise);
    await user.click(saveButtonIn(panel()));
    await refreshWith(user, [unsavedR1, r2]);
    getReport.mockReturnValueOnce(reconcile.d.promise);
    await settleHeld(firstPut);

    const secondPut = { d: deferred<ReportCard>(), snapshot: savedR1 };
    saveReport.mockReturnValueOnce(secondPut.d.promise);
    await user.click(saveButtonIn(panel()));
    await refreshWith(user, [r2]);
    expectClosedWithNotice();
    await settleHeld(reconcile);
    await settleHeld(secondPut);

    expectClosedWithNotice();
    expect(screen.queryByRole("button", { name: /Итоги сезона/ })).toBeNull();
    expect(getReport).toHaveBeenCalledTimes(2);
  });

  it("disappearance cleanup: simultaneous reconcile 404s preserve the open report's notice", async () => {
    const user = userEvent.setup();
    renderPanel("c1", chipAndRefresher);
    await screen.findByRole("heading", { name: "Отчёты чата (2)" });
    const put = { d: deferred<ReportCard>(), snapshot: savedR1 };
    const unsave = { d: deferred<void>(), snapshot: undefined };
    saveReport.mockReturnValueOnce(put.d.promise);
    unsaveReport.mockReturnValueOnce(unsave.d.promise);
    await user.click(saveButtonIn(cards()[0]!));
    await user.click(saveButtonIn(cards()[1]!));
    await openR1(user);
    await refreshWith(user, [unsavedR1, r2]);
    const r1Get = deferred<Report>();
    const r2Get = deferred<Report>();
    getReport.mockImplementation((id) => id === "r1" ? r1Get.promise : r2Get.promise);
    await settleHeld(put);
    await settleHeld(unsave);
    listChatReports.mockRejectedValue(new ApiError(404, "not_found", "Чат не найден"));

    await act(async () => {
      r1Get.reject(NOT_FOUND());
      r2Get.reject(NOT_FOUND());
      await Promise.all([r1Get.promise, r2Get.promise].map((p) => p.catch(() => undefined)));
    });

    expectClosedWithNotice();
    expect(cards()).toHaveLength(0);
    expect(getReport).toHaveBeenCalledTimes(3);
  });

  it.each(["back", "another report"] as const)(
    "disappearance cleanup: a preview GET's late 404 refreshes without a notice after %s",
    async (destination) => {
      const user = userEvent.setup();
      const pending = deferred<Report>();
      getReport.mockReturnValueOnce(pending.promise);
      renderPanel("c1", <><Chip id="r1" /><Chip id="r2" /></>);
      await screen.findByRole("heading", { name: "Отчёты чата (2)" });
      await user.click(screen.getByRole("button", { name: "Отчёт: r1" }));
      await screen.findByText("Загружаю отчёт…");
      await user.click(screen.getByRole("button", {
        name: destination === "back" ? "К списку" : "Отчёт: r2",
      }));
      listChatReports.mockResolvedValue([r2]);
      await act(async () => {
        pending.reject(NOT_FOUND());
        await pending.promise.catch(() => undefined);
      });

      expect(listChatReports).toHaveBeenCalledTimes(2);
      expect(screen.queryByRole("status")).toBeNull();
      if (destination === "another report") {
        expect(screen.getByRole("heading", { name: "Лучшие игроки" })).toBeInTheDocument();
      } else {
        expect(cards()).toHaveLength(1);
      }
    },
  );

  it("disappearance cleanup: a late old-chat reconcile does not refresh the next chat", async () => {
    const user = userEvent.setup();
    const { rerender } = render(<Tree chatId="c1" extra={chipAndRefresher} />);
    await screen.findByRole("heading", { name: "Отчёты чата (2)" });
    await openR1(user);
    const put = { d: deferred<ReportCard>(), snapshot: savedR1 };
    const reconcile = deferred<Report>();
    saveReport.mockReturnValueOnce(put.d.promise);
    await user.click(saveButtonIn(panel()));
    await refreshWith(user, [unsavedR1, r2]);
    getReport.mockReturnValueOnce(reconcile.promise);
    await settleHeld(put);
    rerender(<Tree chatId="c2" extra={chipAndRefresher} />);
    await screen.findByRole("button", { name: /Чужой отчёт/ });

    await act(async () => {
      reconcile.reject(NOT_FOUND());
      await reconcile.promise.catch(() => undefined);
    });

    expect(screen.queryByRole("status")).toBeNull();
    expect(listChatReports.mock.calls.filter(([id]) => id === "c2")).toHaveLength(1);
  });
});

describe("ReportsPanel: the open preview renders from the same record as the card", () => {
  const chipAndRefresher = (
    <>
      <Refresher highlight="r1" />
      <Chip id="r1" />
    </>
  );
  const openR1 = async (user: ReturnType<typeof userEvent.setup>) => {
    await user.click(screen.getByRole("button", { name: "Отчёт: r1" }));
    await screen.findByRole("heading", { level: 2, name: "Итоги сезона" });
  };
  const refreshWith = async (user: ReturnType<typeof userEvent.setup>, snapshot: ReportCard[]) => {
    const newer = { d: deferred<ReportCard[]>(), snapshot };
    listChatReports.mockReturnValueOnce(newer.d.promise);
    await user.click(screen.getByRole("button", { name: "refresh" }));
    await settleHeld(newer);
  };

  it("round-5 reviewer sequence: preview open and unsaved, another visitor saves, a list refresh lands -> preview, fullscreen and card all show saved", async () => {
    const user = userEvent.setup();
    renderPanel("c1", chipAndRefresher);
    await screen.findByRole("heading", { name: "Отчёты чата (2)" });
    await openR1(user);
    expect(screen.getByRole("button", { name: "Сохранить" })).toHaveAttribute("aria-pressed", "false");

    await refreshWith(user, [savedR1, r2]);

    expect(screen.getByRole("button", { name: "Убрать из сохранённых" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(getReport).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "На весь экран" }));
    const dialog = screen.getByRole("dialog", { name: "Итоги сезона" });
    expect(
      within(dialog).getByRole("button", { name: "Убрать из сохранённых" }),
    ).toHaveAttribute("aria-pressed", "true");
    await user.click(within(dialog).getByRole("button", { name: "Свернуть" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());

    await user.click(screen.getByRole("button", { name: "К списку" }));
    await screen.findByRole("button", { name: /Итоги сезона/ });
    expect(saveButtonIn(cards()[0]!)).toHaveAttribute("aria-pressed", "true");
  });

  it("the mirror: preview open and saved, another visitor unsaves, a list refresh lands -> the preview shows unsaved", async () => {
    const user = userEvent.setup();
    listChatReports.mockResolvedValueOnce([savedR1, r2]);
    getReport.mockResolvedValueOnce(report(savedR1, rows));
    renderPanel("c1", chipAndRefresher);
    await screen.findByRole("heading", { name: "Отчёты чата (2)" });
    await openR1(user);
    expect(screen.getByRole("button", { name: "Убрать из сохранённых" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    await refreshWith(user, [unsavedR1, r2]);

    expect(screen.getByRole("button", { name: "Сохранить" })).toHaveAttribute("aria-pressed", "false");
  });

  it("a newer list observation with a higher version re-fetches the open preview's data; card and preview show the new version", async () => {
    const user = userEvent.setup();
    renderPanel("c1", chipAndRefresher);
    await screen.findByRole("heading", { name: "Отчёты чата (2)" });
    await openR1(user);
    expect(within(screen.getByRole("table")).getByText("1234.5678")).toBeInTheDocument();
    expect(screen.getByText("Версия 1")).toBeInTheDocument();

    // Updated elsewhere (D3: one object in both views): the list carries version 2.
    const v2 = { ...unsavedR1, version: 2, generated_at: "2026-09-30T08:00:00Z", row_count: 1 };
    getReport.mockResolvedValueOnce(report(v2, [{ команда: "Гамма", очки: 7 }]));
    await refreshWith(user, [v2, r2]);

    await waitFor(() => expect(getReport).toHaveBeenCalledTimes(2));
    expect(await within(await screen.findByRole("table")).findByText("7")).toBeInTheDocument();
    expect(screen.queryByText("1234.5678")).toBeNull();
    expect(screen.getByText("Версия 2")).toBeInTheDocument();
    expect(
      screen.getByText(`Сформирован: ${formatGeneratedAt("2026-09-30T08:00:00Z")}`),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "К списку" }));
    await screen.findByRole("button", { name: /Итоги сезона/ });
    expect(within(cards()[0]!).getByText("Версия 2")).toBeInTheDocument();
    expect(within(cards()[0]!).getByText("Строк: 1")).toBeInTheDocument();
  });

  it("an older-issued report GET carrying a lower version than the record does not stick: the preview re-fetches once", async () => {
    const user = userEvent.setup();
    renderPanel("c1", chipAndRefresher);
    await screen.findByRole("heading", { name: "Отчёты чата (2)" });

    const older = { d: deferred<Report>(), snapshot: report(unsavedR1, rows) };
    getReport.mockReturnValueOnce(older.d.promise);
    await user.click(screen.getByRole("button", { name: "Отчёт: r1" }));
    await screen.findByText("Загружаю отчёт…");

    const v2 = { ...unsavedR1, version: 2 };
    await refreshWith(user, [v2, r2]);
    getReport.mockResolvedValueOnce(report(v2, rows));

    await settleHeld(older);
    await waitFor(() => expect(getReport).toHaveBeenCalledTimes(2));
    await screen.findByRole("heading", { level: 2, name: "Итоги сезона" });
    expect(screen.getByText("Версия 2")).toBeInTheDocument();
    expect(getReport).toHaveBeenCalledTimes(2);
  });

  it("round-6 reviewer sequence: a delayed Save response (version 1) lands after another visitor's Update (version 2) was seen through the list -> card keeps version 2 and the new title, is saved; the preview shows version 2 rows", async () => {
    const user = userEvent.setup();
    const oldR1 = { ...unsavedR1, title: "Старый отчёт" };
    const savedOldR1 = { ...oldR1, saved_at: "2026-09-29T10:00:00Z" };
    const updatedR1 = {
      ...savedOldR1,
      title: "Обновлённый отчёт",
      version: 2,
      generated_at: "2026-09-30T10:00:00Z",
      row_count: 1,
    };
    listChatReports.mockResolvedValueOnce([oldR1, r2]);
    renderPanel("c1", chipAndRefresher);
    await screen.findByRole("button", { name: /Старый отчёт/ });

    const put = { d: deferred<ReportCard>(), snapshot: savedOldR1 };
    saveReport.mockReturnValueOnce(put.d.promise);
    await user.click(saveButtonIn(cards()[0]!));
    expect(saveReport).toHaveBeenCalledWith("r1");

    // Another visitor's Update; a list issued after it shows version 2.
    await refreshWith(user, [updatedR1, r2]);
    expect(screen.getByRole("button", { name: /Обновлённый отчёт/ })).toBeInTheDocument();
    expect(within(cards()[0]!).getByText("Версия 2")).toBeInTheDocument();

    // The old PUT response lands: it never overrides the newer list (which saw
    // the applied bookmark) nor the newer content; the reconcile GET agrees.
    getReport.mockResolvedValue(report(updatedR1, [{ x: 2 }]));
    await settleHeld(put);
    await waitFor(() => expect(getReport).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(saveButtonIn(cards()[0]!)).toBeEnabled());
    expect(saveButtonIn(cards()[0]!)).toHaveAttribute("aria-pressed", "true");
    expect(within(cards()[0]!).getByText("Версия 2")).toBeInTheDocument();
    expect(within(cards()[0]!).getByText("Строк: 1")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Обновлённый отчёт/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Старый отчёт/ })).toBeNull();

    await user.click(screen.getByRole("button", { name: "Отчёт: r1" }));
    await screen.findByRole("heading", { level: 2, name: "Обновлённый отчёт" });
    expect(screen.getByText("Версия 2")).toBeInTheDocument();
    expect(within(screen.getByRole("table")).getByText("2")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Убрать из сохранённых" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });
});

describe("ReportsPanel: a delayed confirmation never overrides a newer observation", () => {
  const chipAndRefresher = (
    <>
      <Refresher highlight="r1" />
      <Chip id="r1" />
    </>
  );
  const refreshWith = async (user: ReturnType<typeof userEvent.setup>, snapshot: ReportCard[]) => {
    const newer = { d: deferred<ReportCard[]>(), snapshot };
    listChatReports.mockReturnValueOnce(newer.d.promise);
    await user.click(screen.getByRole("button", { name: "refresh" }));
    await settleHeld(newer);
  };

  it("round-7 reviewer sequence: the server applied our Save, another visitor unsaved, a list saw it unsaved, then the old Save response lands -> stays unsaved; the reconcile GET confirms", async () => {
    const user = userEvent.setup();
    renderPanel("c1", chipAndRefresher);
    await screen.findByRole("heading", { name: "Отчёты чата (2)" });

    // The backend applies the PUT at once; only its response is in transit.
    const put = { d: deferred<ReportCard>(), snapshot: savedR1 };
    saveReport.mockReturnValueOnce(put.d.promise);
    await user.click(saveButtonIn(cards()[0]!));

    // Another visitor unsaves; a list issued after that sees it unsaved.
    await refreshWith(user, [unsavedR1, r2]);

    getReport.mockResolvedValueOnce(report(unsavedR1, rows));
    await settleHeld(put);
    await waitFor(() => expect(saveButtonIn(cards()[0]!)).toBeEnabled());
    expect(saveButtonIn(cards()[0]!)).toHaveAttribute("aria-pressed", "false");
    await waitFor(() => expect(getReport).toHaveBeenCalledWith("r1"));
    expect(getReport).toHaveBeenCalledTimes(1);
    expect(saveButtonIn(cards()[0]!)).toHaveAttribute("aria-pressed", "false");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("the other execution order: the server applied our Save after the visitor's Unsave -> the reconcile GET shows saved", async () => {
    const user = userEvent.setup();
    renderPanel("c1", chipAndRefresher);
    await screen.findByRole("heading", { name: "Отчёты чата (2)" });

    const put = { d: deferred<ReportCard>(), snapshot: savedR1 };
    saveReport.mockReturnValueOnce(put.d.promise);
    await user.click(saveButtonIn(cards()[0]!));
    await refreshWith(user, [unsavedR1, r2]);

    getReport.mockResolvedValueOnce(report(savedR1, rows));
    await settleHeld(put);
    await waitFor(() => expect(getReport).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(saveButtonIn(cards()[0]!)).toHaveAttribute("aria-pressed", "true"));
    expect(saveButtonIn(cards()[0]!)).toBeEnabled();
  });

  it("the reconcile GET does not blank an open preview, is issued once per report at a time, and a stale one cannot override a later confirmation", async () => {
    const user = userEvent.setup();
    renderPanel("c1", chipAndRefresher);
    await screen.findByRole("heading", { name: "Отчёты чата (2)" });
    await user.click(screen.getByRole("button", { name: "Отчёт: r1" }));
    await screen.findByRole("heading", { level: 2, name: "Итоги сезона" });
    expect(getReport).toHaveBeenCalledTimes(1);

    const put = { d: deferred<ReportCard>(), snapshot: savedR1 };
    saveReport.mockReturnValueOnce(put.d.promise);
    await user.click(screen.getByRole("button", { name: "Сохранить" }));
    await refreshWith(user, [unsavedR1, r2]);

    // The ambiguous confirmation: the newer observation stays, a reconcile GET is held.
    const reconcile = { d: deferred<Report>(), snapshot: report(unsavedR1, rows) };
    getReport.mockReturnValueOnce(reconcile.d.promise);
    await settleHeld(put);
    await waitFor(() => expect(getReport).toHaveBeenCalledTimes(2));
    expect(screen.getByRole("heading", { level: 2, name: "Итоги сезона" })).toBeInTheDocument();
    expect(screen.queryByText("Загружаю отчёт…")).toBeNull();
    const toggle = screen.getByRole("button", { name: "Сохранить" });
    expect(toggle).toHaveAttribute("aria-pressed", "false");
    expect(toggle).toBeEnabled();

    // Save again while the reconcile is in flight: nothing newer was observed
    // since this mutation, so its confirmation stands - and no second GET starts.
    saveReport.mockResolvedValueOnce(savedR1);
    await user.click(toggle);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Убрать из сохранённых" })).toBeEnabled(),
    );
    expect(getReport).toHaveBeenCalledTimes(2);

    // The stale reconcile answer (issued before that confirmation) changes nothing.
    await settleHeld(reconcile);
    expect(screen.getByRole("button", { name: "Убрать из сохранённых" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(getReport).toHaveBeenCalledTimes(2);
  });

  it("a second ambiguous confirmation while a reconcile GET is in flight gets its own GET afterwards, not the stale one", async () => {
    const user = userEvent.setup();
    renderPanel("c1", chipAndRefresher);
    await screen.findByRole("heading", { name: "Отчёты чата (2)" });

    const put = { d: deferred<ReportCard>(), snapshot: savedR1 };
    saveReport.mockReturnValueOnce(put.d.promise);
    await user.click(saveButtonIn(cards()[0]!));
    await refreshWith(user, [unsavedR1, r2]);
    const first = { d: deferred<Report>(), snapshot: report(unsavedR1, rows) };
    getReport.mockReturnValueOnce(first.d.promise);
    await settleHeld(put);
    await waitFor(() => expect(getReport).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(saveButtonIn(cards()[0]!)).toBeEnabled());

    // Second Save; a list issued after it sees the report unsaved; its confirmation is ambiguous too.
    const put2 = { d: deferred<ReportCard>(), snapshot: savedR1 };
    saveReport.mockReturnValueOnce(put2.d.promise);
    await user.click(saveButtonIn(cards()[0]!));
    await refreshWith(user, [unsavedR1, r2]);
    await settleHeld(put2);
    await waitFor(() => expect(saveButtonIn(cards()[0]!)).toBeEnabled());
    expect(saveButtonIn(cards()[0]!)).toHaveAttribute("aria-pressed", "false");
    expect(getReport).toHaveBeenCalledTimes(1);

    // The first reconcile completes; the second one is issued only now and tells the truth.
    getReport.mockResolvedValueOnce(report(savedR1, rows));
    await settleHeld(first);
    await waitFor(() => expect(getReport).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(saveButtonIn(cards()[0]!)).toHaveAttribute("aria-pressed", "true"));
  });

  it("a reconcile GET that fails leaves the newest observation in place; a 404 refreshes the list", async () => {
    const user = userEvent.setup();
    renderPanel("c1", chipAndRefresher);
    await screen.findByRole("heading", { name: "Отчёты чата (2)" });

    const put = { d: deferred<ReportCard>(), snapshot: savedR1 };
    saveReport.mockReturnValueOnce(put.d.promise);
    await user.click(saveButtonIn(cards()[0]!));
    await refreshWith(user, [unsavedR1, r2]);
    getReport.mockRejectedValueOnce(new ApiError(0, "network", "Связь с сервером потеряна"));
    await settleHeld(put);
    await waitFor(() => expect(getReport).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(saveButtonIn(cards()[0]!)).toBeEnabled());
    expect(saveButtonIn(cards()[0]!)).toHaveAttribute("aria-pressed", "false");
    expect(listChatReports).toHaveBeenCalledTimes(2);

    // Gone meanwhile: the list is refreshed so the card disappears.
    const put2 = { d: deferred<ReportCard>(), snapshot: savedR1 };
    saveReport.mockReturnValueOnce(put2.d.promise);
    await user.click(saveButtonIn(cards()[0]!));
    await refreshWith(user, [unsavedR1, r2]);
    getReport.mockRejectedValueOnce(new ApiError(404, "not_found", "Отчёт не найден"));
    listChatReports.mockResolvedValueOnce([r2]);
    await settleHeld(put2);
    await screen.findByRole("heading", { name: "Отчёты чата (1)" });
    expect(screen.queryByRole("button", { name: /Итоги сезона/ })).toBeNull();
  });
});

describe("ReportsPanel bookmark timeline: own and foreign changes x responses", () => {
  it("reviewer sequence: Save ok, another visitor unsaves, a newer list shows it, our next Save fails -> stays unsaved (card and preview)", async () => {
    await runTimeline(false, [
      { kind: "mutate", m: "save-ok" },
      { kind: "foreign" },
      { kind: "new-list" },
      { kind: "mutate", m: "save-fail" },
      { kind: "report" },
    ]);
  });

  it("round-3 reviewer sequence: Save ok, Unsave fails, the pre-Save list lands -> still saved", async () => {
    await runTimeline(false, [
      { kind: "issue-list" },
      { kind: "mutate", m: "save-ok" },
      { kind: "mutate", m: "unsave-fail" },
      { kind: "resolve-list" },
    ]);
  });

  it("success path: a response issued after our confirmed Save and contradicting it wins", async () => {
    await runTimeline(false, [
      { kind: "mutate", m: "save-ok" },
      { kind: "foreign" },
      { kind: "report" },
      { kind: "new-list" },
    ]);
  });

  it.each(
    cases.map((c) => [
      `initially ${c.initial ? "saved" : "unsaved"} | ${c.name}`,
      c,
    ] as const),
  )("%s", async (_name, c) => {
    await runTimeline(c.initial, c.steps);
  });
});
