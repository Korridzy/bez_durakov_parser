import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  MemoryRouter,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/types";
import type { Report, ReportCard } from "../api/types";
import { formatGeneratedAt } from "../reports/ReportPreview";
import { SavedReportsPage } from "./SavedReportsPage";

vi.mock("../api/client", async () => {
  const actual =
    await vi.importActual<typeof import("../api/client")>("../api/client");
  return {
    ...actual,
    listSavedReports: vi.fn(),
    getReport: vi.fn(),
    updateReport: vi.fn(),
    unsaveReport: vi.fn(),
  };
});

import * as client from "../api/client";

const listSavedReports = vi.mocked(client.listSavedReports);
const getReport = vi.mocked(client.getReport);
const updateReport = vi.mocked(client.updateReport);
const unsaveReport = vi.mocked(client.unsaveReport);

function card(over: Partial<ReportCard> & { id: string }): ReportCard {
  return {
    chat_id: "c1",
    title: `Отчёт ${over.id}`,
    question: "Сколько очков набрали команды?",
    tool: "read_rows",
    args: { table: "results", limit: 10 },
    generated_at: "2026-09-28T10:15:00Z",
    version: 2,
    saved_at: "2026-09-29T09:00:00Z",
    row_count: 2,
    created_at: "2026-09-28T10:15:00Z",
    ...over,
  };
}

function full(base: ReportCard, data: unknown = defaultData): Report {
  return { ...base, data };
}

const defaultData = [
  { команда: "Альфа", очки: 10 },
  { команда: "Бета", очки: 7 },
];

const r1 = card({
  id: "r1",
  title: "Итоги сезона",
  generated_at: "2026-09-28T10:15:00Z",
  saved_at: "2026-09-29T09:00:00Z",
});
const r2 = card({
  id: "r2",
  chat_id: null,
  title: "Составы команд",
  generated_at: "2026-09-20T08:00:00Z",
  version: 1,
  saved_at: "2026-09-27T09:00:00Z",
  args: { table: "rosters" },
});
const r3 = card({
  id: "r3",
  chat_id: "c3",
  title: "Посещаемость",
  generated_at: "2026-09-10T12:00:00Z",
  version: 4,
  saved_at: "2026-09-25T09:00:00Z",
});

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function Harness() {
  const location = useLocation();
  return (
    <>
      <SavedReportsPage />
      <span data-testid="path">{location.pathname}</span>
    </>
  );
}

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/saved" element={<Harness />} />
        <Route path="/saved/:reportId" element={<Harness />} />
        <Route
          path="/chats/:chatId"
          element={<span data-testid="chat-page">чат</span>}
        />
      </Routes>
    </MemoryRouter>,
  );
}

const pathShown = () => screen.getByTestId("path").textContent;

const list = () => screen.getByRole("navigation", { name: "Сохранённые отчёты" });

const preview = () => screen.getByRole("article");

function mockReports(...cards: ReportCard[]) {
  listSavedReports.mockResolvedValue(cards);
  getReport.mockImplementation((id) => {
    const found = cards.find((item) => item.id === id);
    return found === undefined
      ? Promise.reject(new ApiError(404, "not_found", "Отчёт не найден"))
      : Promise.resolve(full(found));
  });
}

async function renderSelected(path = "/saved/r1") {
  renderAt(path);
  await screen.findByRole("article");
  return userEvent.setup();
}

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("SavedReportsPage", () => {
  it("lists saved reports with generation dates and the origin link or label", async () => {
    mockReports(r1, r2);
    renderAt("/saved/r1");

    const nav = await screen.findByRole("navigation", { name: "Сохранённые отчёты" });
    const rows = within(nav).getAllByRole("listitem");
    expect(rows).toHaveLength(2);

    const first = rows[0] as HTMLElement;
    expect(within(first).getByText("Итоги сезона")).toBeInTheDocument();
    expect(
      within(first).getByText(`Сформирован ${formatGeneratedAt(r1.generated_at)}`),
    ).toBeInTheDocument();
    expect(within(first).getByRole("link", { name: "Открыть чат" })).toHaveAttribute(
      "href",
      "/chats/c1",
    );

    const second = rows[1] as HTMLElement;
    expect(within(second).getByText("Составы команд")).toBeInTheDocument();
    expect(within(second).getByText("Чат удалён")).toBeInTheDocument();
    expect(within(second).queryByRole("link", { name: "Открыть чат" })).toBeNull();
  });

  it("selects the deep-linked report and loads its preview", async () => {
    mockReports(r1, r2);
    renderAt("/saved/r2");

    const article = await screen.findByRole("article");
    expect(getReport).toHaveBeenCalledWith("r2");
    expect(within(article).getByRole("heading", { name: "Составы команд" })).toBeInTheDocument();
    expect(within(article).getByText("Чат удалён")).toBeInTheDocument();
    expect(within(list()).getByRole("link", { name: /Составы команд/ })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("opens the most recent saved report on /saved", async () => {
    mockReports(r1, r2);
    renderAt("/saved");

    await waitFor(() => expect(pathShown()).toBe("/saved/r1"));
    const article = await screen.findByRole("article");
    expect(within(article).getByRole("heading", { name: "Итоги сезона" })).toBeInTheDocument();
    expect(within(article).getByRole("link", { name: "Открыть чат" })).toHaveAttribute(
      "href",
      "/chats/c1",
    );
  });

  it("loads the preview of a report picked from the list", async () => {
    mockReports(r1, r2);
    const user = await renderSelected("/saved/r1");

    await user.click(within(list()).getByRole("link", { name: /Составы команд/ }));

    await waitFor(() =>
      expect(within(preview()).getByRole("heading", { name: "Составы команд" })).toBeInTheDocument(),
    );
    expect(pathShown()).toBe("/saved/r2");
    expect(getReport).toHaveBeenLastCalledWith("r2");
  });

  it("shows the empty state when nothing is saved", async () => {
    listSavedReports.mockResolvedValue([]);
    renderAt("/saved");

    expect(await screen.findByText("Сохранённых отчётов пока нет")).toBeInTheDocument();
    expect(getReport).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Обновить" })).toBeNull();
  });

  it("replaces the preview and the list date and version after a successful update", async () => {
    mockReports(r1, r2);
    const user = await renderSelected("/saved/r1");
    const fresh = full(
      { ...r1, generated_at: "2026-09-30T07:45:00Z", version: 3, row_count: 3 },
      [...defaultData, { команда: "Гамма", очки: 1 }],
    );
    updateReport.mockResolvedValue(fresh);

    await user.click(screen.getByRole("button", { name: "Обновить" }));

    expect(updateReport).toHaveBeenCalledWith("r1");
    const newDate = formatGeneratedAt(fresh.generated_at);
    await waitFor(() =>
      expect(within(preview()).getByText(`Сформирован: ${newDate}`)).toBeInTheDocument(),
    );
    expect(within(preview()).getByText("Версия 3")).toBeInTheDocument();
    expect(within(preview()).getByRole("cell", { name: "Гамма" })).toBeInTheDocument();
    expect(within(list()).getByText(`Сформирован ${newDate}`)).toBeInTheDocument();
    expect(within(list()).getByText("Версия 3")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("keeps the old preview and names the old date when the update fails with 502", async () => {
    mockReports(r1, r2);
    const user = await renderSelected("/saved/r1");
    updateReport.mockRejectedValue(
      new ApiError(502, "update_failed", "Инструмент вернул ошибку: ToolError", {
        error: { code: "update_failed", message: "Инструмент вернул ошибку: ToolError" },
        report: full(r1),
      }),
    );

    await user.click(screen.getByRole("button", { name: "Обновить" }));

    const oldDate = formatGeneratedAt(r1.generated_at);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      `Обновить не удалось: Инструмент вернул ошибку: ToolError. Показана версия от ${oldDate}`,
    );
    expect(within(preview()).getByText(`Сформирован: ${oldDate}`)).toBeInTheDocument();
    expect(within(preview()).getByText("Версия 2")).toBeInTheDocument();
    expect(within(preview()).getByRole("cell", { name: "Альфа" })).toBeInTheDocument();
    expect(within(list()).getByText(`Сформирован ${oldDate}`)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Обновить" })).toBeEnabled();
  });

  it("treats a network error like a failed update with «Нет связи с сервером»", async () => {
    mockReports(r1, r2);
    const user = await renderSelected("/saved/r1");
    updateReport.mockRejectedValue(new ApiError(0, "network", "Связь с сервером потеряна"));

    await user.click(screen.getByRole("button", { name: "Обновить" }));

    const oldDate = formatGeneratedAt(r1.generated_at);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      `Обновить не удалось: Нет связи с сервером. Показана версия от ${oldDate}`,
    );
    expect(within(preview()).getByText(`Сформирован: ${oldDate}`)).toBeInTheDocument();
    expect(within(preview()).getByText("Версия 2")).toBeInTheDocument();
  });

  it("shows «Отчёт занят, повторите позже» on 409", async () => {
    mockReports(r1, r2);
    const user = await renderSelected("/saved/r1");
    updateReport.mockRejectedValue(
      new ApiError(409, "report_busy", "Отчёт обновляется", {
        error: { code: "report_busy", message: "Отчёт обновляется" },
      }),
    );

    await user.click(screen.getByRole("button", { name: "Обновить" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Отчёт занят, повторите позже");
    expect(within(preview()).getByText("Версия 2")).toBeInTheDocument();
  });

  it("disables «Обновить» while in flight, shows the reading mark and ignores a second click", async () => {
    mockReports(r1, r2);
    const user = await renderSelected("/saved/r1");
    const pending = deferred<Report>();
    updateReport.mockReturnValue(pending.promise);

    const button = screen.getByRole("button", { name: "Обновить" });
    await user.dblClick(button);
    await user.click(button);

    expect(updateReport).toHaveBeenCalledTimes(1);
    expect(button).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent("Читаю данные…");

    pending.resolve(full({ ...r1, generated_at: "2026-09-30T07:45:00Z", version: 3 }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Обновить" })).toBeEnabled());
    expect(screen.queryByRole("status")).toBeNull();
    expect(within(preview()).getByText("Версия 3")).toBeInTheDocument();
  });

  it("keeps the list usable during an update and never overwrites the newly selected preview", async () => {
    mockReports(r1, r2);
    const user = await renderSelected("/saved/r1");
    const pending = deferred<Report>();
    updateReport.mockReturnValue(pending.promise);
    await user.click(screen.getByRole("button", { name: "Обновить" }));

    await user.click(within(list()).getByRole("link", { name: /Составы команд/ }));
    await waitFor(() =>
      expect(within(preview()).getByRole("heading", { name: "Составы команд" })).toBeInTheDocument(),
    );

    const freshDate = "2026-09-30T07:45:00Z";
    pending.resolve(full({ ...r1, generated_at: freshDate, version: 3 }));

    await waitFor(() =>
      expect(within(list()).getByText(`Сформирован ${formatGeneratedAt(freshDate)}`)).toBeInTheDocument(),
    );
    expect(within(preview()).getByRole("heading", { name: "Составы команд" })).toBeInTheDocument();
    expect(within(preview()).getByText("Версия 1")).toBeInTheDocument();
  });

  it("keeps the updated date and version when the saved-list GET resolves after the update", async () => {
    const pendingList = deferred<ReportCard[]>();
    listSavedReports.mockReturnValue(pendingList.promise);
    getReport.mockResolvedValue(full(r1));
    renderAt("/saved/r1");
    await screen.findByRole("article");
    const user = userEvent.setup();
    const freshDate = "2026-09-30T07:45:00Z";
    updateReport.mockResolvedValue(full({ ...r1, generated_at: freshDate, version: 3 }));

    await user.click(screen.getByRole("button", { name: "Обновить" }));
    await waitFor(() => expect(within(preview()).getByText("Версия 3")).toBeInTheDocument());

    // The list request issued before the update now returns the old cards.
    pendingList.resolve([r1, r2]);

    const rows = await within(list()).findAllByRole("listitem");
    const row = rows[0] as HTMLElement;
    await waitFor(() =>
      expect(within(row).getByText(`Сформирован ${formatGeneratedAt(freshDate)}`)).toBeInTheDocument(),
    );
    expect(within(row).getByText("Версия 3")).toBeInTheDocument();
    expect(within(row).queryByText(`Сформирован ${formatGeneratedAt(r1.generated_at)}`)).toBeNull();
    expect(within(preview()).getByText("Версия 3")).toBeInTheDocument();
  });

  it("keeps the updated preview when a report GET issued before the update resolves after it", async () => {
    listSavedReports.mockResolvedValue([r1, r2]);
    const lateGet = deferred<Report>();
    let r1Gets = 0;
    getReport.mockImplementation((id) => {
      if (id === "r1") {
        r1Gets += 1;
        return r1Gets === 1 ? Promise.resolve(full(r1)) : lateGet.promise;
      }
      return Promise.resolve(full(r2));
    });
    const user = await renderSelected("/saved/r1");
    const pendingUpdate = deferred<Report>();
    updateReport.mockReturnValue(pendingUpdate.promise);
    await user.click(screen.getByRole("button", { name: "Обновить" }));

    // Navigate away and back while the update is in flight: the second GET of r1 stays pending.
    await user.click(within(list()).getByRole("link", { name: /Составы команд/ }));
    await waitFor(() =>
      expect(within(preview()).getByRole("heading", { name: "Составы команд" })).toBeInTheDocument(),
    );
    await user.click(within(list()).getByRole("link", { name: /Итоги сезона/ }));
    await waitFor(() => expect(r1Gets).toBe(2));
    expect(screen.queryByRole("article")).toBeNull();

    const freshDate = "2026-09-30T07:45:00Z";
    pendingUpdate.resolve(
      full({ ...r1, generated_at: freshDate, version: 3 }, [...defaultData, { команда: "Гамма", очки: 1 }]),
    );
    await waitFor(() => expect(within(list()).getByText("Версия 3")).toBeInTheDocument());

    // The old GET lands last with version 2: it must not win over the update.
    lateGet.resolve(full(r1));

    const article = await screen.findByRole("article");
    expect(within(article).getByRole("heading", { name: "Итоги сезона" })).toBeInTheDocument();
    expect(within(article).getByText("Версия 3")).toBeInTheDocument();
    expect(within(article).getByText(`Сформирован: ${formatGeneratedAt(freshDate)}`)).toBeInTheDocument();
    expect(within(article).getByRole("cell", { name: "Гамма" })).toBeInTheDocument();
    expect(within(list()).getByText("Версия 3")).toBeInTheDocument();
  });

  it("does not resurrect an unsaved report when the saved-list GET resolves after the unsave", async () => {
    const pendingList = deferred<ReportCard[]>();
    listSavedReports.mockReturnValue(pendingList.promise);
    getReport.mockResolvedValue(full(r1));
    unsaveReport.mockResolvedValue(undefined);
    renderAt("/saved/r1");
    await screen.findByRole("article");
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Убрать из сохранённых" }));
    expect(unsaveReport).toHaveBeenCalledWith("r1");
    await waitFor(() => expect(pathShown()).toBe("/saved"));

    // The list request issued before the DELETE now returns the snapshot that still has r1.
    pendingList.resolve([r1]);

    expect(await screen.findByText("Сохранённых отчётов пока нет")).toBeInTheDocument();
    expect(within(list()).queryByRole("listitem")).toBeNull();
    expect(pathShown()).toBe("/saved");
    expect(screen.queryByRole("article")).toBeNull();
    expect(getReport).toHaveBeenCalledTimes(1);
  });

  it("drops an unsaved report from a late list even after a successful update, and selects the survivor", async () => {
    const pendingList = deferred<ReportCard[]>();
    listSavedReports.mockReturnValue(pendingList.promise);
    getReport.mockImplementation((id) => Promise.resolve(full(id === "r1" ? r1 : r2)));
    unsaveReport.mockResolvedValue(undefined);
    renderAt("/saved/r1");
    await screen.findByRole("article");
    const user = userEvent.setup();
    updateReport.mockResolvedValue(full({ ...r1, generated_at: "2026-09-30T07:45:00Z", version: 3 }));

    await user.click(screen.getByRole("button", { name: "Обновить" }));
    await waitFor(() => expect(within(preview()).getByText("Версия 3")).toBeInTheDocument());
    await user.click(screen.getByRole("button", { name: "Убрать из сохранённых" }));
    await waitFor(() => expect(pathShown()).toBe("/saved"));

    pendingList.resolve([r1, r2]);

    await waitFor(() => expect(pathShown()).toBe("/saved/r2"));
    const rows = await within(list()).findAllByRole("listitem");
    expect(rows).toHaveLength(1);
    expect(within(rows[0] as HTMLElement).getByText("Составы команд")).toBeInTheDocument();
    expect(within(list()).queryByText("Итоги сезона")).toBeNull();
    await waitFor(() =>
      expect(within(preview()).getByRole("heading", { name: "Составы команд" })).toBeInTheDocument(),
    );
  });

  it("selects the survivor when the list GET and the DELETE settle in the same batch (list first)", async () => {
    const pendingList = deferred<ReportCard[]>();
    listSavedReports.mockReturnValue(pendingList.promise);
    getReport.mockImplementation((id) => Promise.resolve(full(id === "r1" ? r1 : r2)));
    const pendingDelete = deferred<void>();
    unsaveReport.mockReturnValue(pendingDelete.promise);
    renderAt("/saved/r1");
    await screen.findByRole("article");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Убрать из сохранённых" }));

    // Both responses settle before React commits anything in between.
    await act(async () => {
      pendingList.resolve([r1, r2]);
      pendingDelete.resolve();
    });

    await waitFor(() => expect(pathShown()).toBe("/saved/r2"));
    const rows = await within(list()).findAllByRole("listitem");
    expect(rows).toHaveLength(1);
    expect(within(rows[0] as HTMLElement).getByText("Составы команд")).toBeInTheDocument();
    expect(screen.queryByText("Сохранённых отчётов пока нет")).toBeNull();
    await waitFor(() =>
      expect(within(preview()).getByRole("heading", { name: "Составы команд" })).toBeInTheDocument(),
    );
  });

  it("selects the survivor when the DELETE and the list GET settle in the same batch (DELETE first)", async () => {
    const pendingList = deferred<ReportCard[]>();
    listSavedReports.mockReturnValue(pendingList.promise);
    getReport.mockImplementation((id) => Promise.resolve(full(id === "r1" ? r1 : r2)));
    const pendingDelete = deferred<void>();
    unsaveReport.mockReturnValue(pendingDelete.promise);
    renderAt("/saved/r1");
    await screen.findByRole("article");
    const user = userEvent.setup();
    await user.click(screen.getByRole("button", { name: "Убрать из сохранённых" }));

    await act(async () => {
      pendingDelete.resolve();
      pendingList.resolve([r1, r2]);
    });

    await waitFor(() => expect(pathShown()).toBe("/saved/r2"));
    const rows = await within(list()).findAllByRole("listitem");
    expect(rows).toHaveLength(1);
    expect(within(rows[0] as HTMLElement).getByText("Составы команд")).toBeInTheDocument();
    expect(within(list()).queryByText("Итоги сезона")).toBeNull();
    await waitFor(() =>
      expect(within(preview()).getByRole("heading", { name: "Составы команд" })).toBeInTheDocument(),
    );
  });

  it("keeps a list that lands between the unsave click and the DELETE completing", async () => {
    const pendingList = deferred<ReportCard[]>();
    listSavedReports.mockReturnValue(pendingList.promise);
    getReport.mockImplementation((id) => Promise.resolve(full(id === "r1" ? r1 : r2)));
    const pendingDelete = deferred<void>();
    unsaveReport.mockReturnValue(pendingDelete.promise);
    renderAt("/saved/r1");
    await screen.findByRole("article");
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Убрать из сохранённых" }));
    pendingList.resolve([r1, r2]);
    await within(list()).findAllByRole("listitem");
    pendingDelete.resolve();

    await waitFor(() => expect(pathShown()).toBe("/saved/r2"));
    const rows = await within(list()).findAllByRole("listitem");
    expect(rows).toHaveLength(1);
    expect(within(rows[0] as HTMLElement).getByText("Составы команд")).toBeInTheDocument();
    await waitFor(() =>
      expect(within(preview()).getByRole("heading", { name: "Составы команд" })).toBeInTheDocument(),
    );
  });

  it("trusts a list fetched after the unsave (a re-saved report may legitimately return)", async () => {
    listSavedReports.mockRejectedValueOnce(new ApiError(0, "network", "Связь с сервером потеряна"));
    getReport.mockImplementation((id) => Promise.resolve(full(id === "r1" ? r1 : r2)));
    unsaveReport.mockResolvedValue(undefined);
    renderAt("/saved/r1");
    await screen.findByRole("article");
    expect(await screen.findByText("Сервер недоступен")).toBeInTheDocument();
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Убрать из сохранённых" }));
    await waitFor(() => expect(pathShown()).toBe("/saved"));

    // «Повторить» issues a NEW request after the unsave: its answer is server truth.
    listSavedReports.mockResolvedValueOnce([r1, r2]);
    await user.click(screen.getByRole("button", { name: "Повторить" }));

    const rows = await within(list()).findAllByRole("listitem");
    expect(rows).toHaveLength(2);
    await waitFor(() => expect(pathShown()).toBe("/saved/r1"));
  });

  it("keeps the user's new selection when the unsave of another report completes", async () => {
    mockReports(r1, r2, r3);
    const user = await renderSelected("/saved/r1");
    const pendingDelete = deferred<void>();
    unsaveReport.mockReturnValue(pendingDelete.promise);

    await user.click(screen.getByRole("button", { name: "Убрать из сохранённых" }));
    await user.click(within(list()).getByRole("link", { name: /Посещаемость/ }));
    await waitFor(() =>
      expect(within(preview()).getByRole("heading", { name: "Посещаемость" })).toBeInTheDocument(),
    );

    pendingDelete.resolve();

    await waitFor(() => expect(within(list()).queryByText("Итоги сезона")).toBeNull());
    expect(pathShown()).toBe("/saved/r3");
    expect(within(preview()).getByRole("heading", { name: "Посещаемость" })).toBeInTheDocument();
  });

  it("shows the server's version after a failed update when a late report GET lands", async () => {
    listSavedReports.mockResolvedValue([r1, r2]);
    const lateGet = deferred<Report>();
    let r1Gets = 0;
    getReport.mockImplementation((id) => {
      if (id === "r1") {
        r1Gets += 1;
        return r1Gets === 1 ? Promise.resolve(full(r1)) : lateGet.promise;
      }
      return Promise.resolve(full(r2));
    });
    const user = await renderSelected("/saved/r1");
    updateReport.mockRejectedValue(new ApiError(502, "update_failed", "Инструмент вернул ошибку"));
    await user.click(screen.getByRole("button", { name: "Обновить" }));
    await screen.findByRole("alert");

    await user.click(within(list()).getByRole("link", { name: /Составы команд/ }));
    await waitFor(() =>
      expect(within(preview()).getByRole("heading", { name: "Составы команд" })).toBeInTheDocument(),
    );
    await user.click(within(list()).getByRole("link", { name: /Итоги сезона/ }));
    await waitFor(() => expect(r1Gets).toBe(2));

    lateGet.resolve(full({ ...r1, generated_at: "2026-09-29T20:00:00Z", version: 5 }));

    const article = await screen.findByRole("article");
    expect(within(article).getByText("Версия 5")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Обновить" })).toBeEnabled();
  });

  it("shows the last selection after two quick switches even when the earlier GET resolves last", async () => {
    listSavedReports.mockResolvedValue([r1, r2, r3]);
    const slowR2 = deferred<Report>();
    getReport.mockImplementation((id) => (id === "r2" ? slowR2.promise : Promise.resolve(full(id === "r1" ? r1 : r3))));
    const user = await renderSelected("/saved/r1");

    await user.click(within(list()).getByRole("link", { name: /Составы команд/ }));
    await user.click(within(list()).getByRole("link", { name: /Посещаемость/ }));
    await waitFor(() =>
      expect(within(preview()).getByRole("heading", { name: "Посещаемость" })).toBeInTheDocument(),
    );

    slowR2.resolve(full(r2));
    await waitFor(() => expect(getReport).toHaveBeenCalledWith("r3"));

    expect(within(preview()).getByRole("heading", { name: "Посещаемость" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Составы команд" })).toBeNull();
    expect(pathShown()).toBe("/saved/r3");
  });

  it("surfaces the failure of an r1 GET issued after r1's update even when r2's update confirms later", async () => {
    listSavedReports.mockResolvedValue([r1, r2]);
    const lateR1 = deferred<Report>();
    let r1Gets = 0;
    getReport.mockImplementation((id) => {
      if (id === "r1") {
        r1Gets += 1;
        return r1Gets === 1 ? Promise.resolve(full(r1)) : lateR1.promise;
      }
      return Promise.resolve(full(r2));
    });
    const user = await renderSelected("/saved/r1");

    // 1. Update r1 -> v3 (confirmed).
    updateReport.mockResolvedValueOnce(full({ ...r1, generated_at: "2026-09-30T07:45:00Z", version: 3 }));
    await user.click(screen.getByRole("button", { name: "Обновить" }));
    await waitFor(() => expect(within(preview()).getByText("Версия 3")).toBeInTheDocument());

    // 2. Open r2 and start its update; hold the response.
    await user.click(within(list()).getByRole("link", { name: /Составы команд/ }));
    await waitFor(() =>
      expect(within(preview()).getByRole("heading", { name: "Составы команд" })).toBeInTheDocument(),
    );
    const pendingR2 = deferred<Report>();
    updateReport.mockReturnValueOnce(pendingR2.promise);
    await user.click(screen.getByRole("button", { name: "Обновить" }));

    // 3. Return to r1: a new r1 GET is issued AFTER r1's update; hold it.
    await user.click(within(list()).getByRole("link", { name: /Итоги сезона/ }));
    await waitFor(() => expect(r1Gets).toBe(2));
    expect(screen.getByText("Загрузка отчёта…")).toBeInTheDocument();

    // 4. r2's update confirms (a mutation of ANOTHER report).
    await act(async () => {
      pendingR2.resolve(full({ ...r2, generated_at: "2026-09-30T08:00:00Z", version: 2 }));
    });
    await waitFor(() => expect(within(list()).getByText("Версия 2")).toBeInTheDocument());

    // 5. The r1 GET fails: it is newer than r1's own update, so the failure is real.
    await act(async () => {
      lateR1.reject(new ApiError(0, "network", "Связь с сервером потеряна"));
    });

    expect(await screen.findByRole("link", { name: "К списку" })).toBeInTheDocument();
    expect(screen.queryByText("Загрузка отчёта…")).toBeNull();
    expect(screen.queryByRole("article")).toBeNull();
    expect(pathShown()).toBe("/saved/r1");
    expect(within(list()).getByText("Версия 3")).toBeInTheDocument();
  });

  it("removes the entry on unsave and selects the next one", async () => {
    mockReports(r1, r2, r3);
    const user = await renderSelected("/saved/r2");
    unsaveReport.mockResolvedValue(undefined);

    await user.click(screen.getByRole("button", { name: "Убрать из сохранённых" }));

    expect(unsaveReport).toHaveBeenCalledWith("r2");
    await waitFor(() => expect(pathShown()).toBe("/saved/r3"));
    expect(within(list()).queryByText("Составы команд")).toBeNull();
    expect(within(list()).getAllByRole("listitem")).toHaveLength(2);
    await waitFor(() =>
      expect(within(preview()).getByRole("heading", { name: "Посещаемость" })).toBeInTheDocument(),
    );
  });

  it("falls back to the previous entry when the last one is unsaved, then to the empty state", async () => {
    mockReports(r1, r2);
    const user = await renderSelected("/saved/r2");
    unsaveReport.mockResolvedValue(undefined);

    await user.click(screen.getByRole("button", { name: "Убрать из сохранённых" }));
    await waitFor(() => expect(pathShown()).toBe("/saved/r1"));
    await waitFor(() =>
      expect(within(preview()).getByRole("heading", { name: "Итоги сезона" })).toBeInTheDocument(),
    );

    await user.click(screen.getByRole("button", { name: "Убрать из сохранённых" }));
    await waitFor(() => expect(pathShown()).toBe("/saved"));
    expect(await screen.findByText("Сохранённых отчётов пока нет")).toBeInTheDocument();
    expect(screen.queryByRole("article")).toBeNull();
  });

  it("shows «Отчёт не найден» for a deep link to a missing report", async () => {
    mockReports(r1);
    renderAt("/saved/gone");

    expect(await screen.findByText("Отчёт не найден")).toBeInTheDocument();
    expect(screen.queryByRole("article")).toBeNull();
    expect(screen.queryByRole("button", { name: "Обновить" })).toBeNull();
    expect(screen.getByRole("link", { name: "К списку" })).toHaveAttribute("href", "/saved");
  });

  it("shows «Сервер недоступен» with a retry when the list cannot be loaded", async () => {
    listSavedReports.mockRejectedValueOnce(new ApiError(0, "network", "Связь с сервером потеряна"));
    listSavedReports.mockResolvedValueOnce([r1]);
    getReport.mockResolvedValue(full(r1));
    renderAt("/saved");
    const user = userEvent.setup();

    expect(await screen.findByText("Сервер недоступен")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Повторить" }));

    await waitFor(() => expect(pathShown()).toBe("/saved/r1"));
    expect(within(list()).getByText("Итоги сезона")).toBeInTheDocument();
  });
});
