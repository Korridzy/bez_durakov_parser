/**
 * Response-ordering matrix for the Saved Reports page.
 *
 * Dimensions: {report GET, list GET} x {issued before / after the mutation}
 * x {resolves, fails} x {Update ok, Update fail, Unsave ok, Unsave fail, none}
 * x {same route, navigate away and back}. Every constructible cell is data in
 * `CELLS` with its expected preview / list / notice / path; every cell that the
 * UI cannot produce is data in `NOT_CONSTRUCTIBLE` with the reason. A coverage
 * test asserts the two sets partition the full 80-cell product.
 *
 * "Navigate away and back" is any navigation that leaves /saved/r1 and returns
 * to it: a click on the list rows when they exist, otherwise browser
 * Back/Forward through the history (`/saved/r1`, `/saved/r2`, `/saved/r1` are
 * the entries the page was opened with). Browser history makes a report GET
 * possible while the list has no rows and after r1 was unsaved.
 *
 * Every cell ends with the same invariant: once every request has settled the
 * preview is never "Загрузка отчёта…".
 *
 * Rules the expectations encode:
 * - a confirmed mutation (Update 200, Unsave 204) beats every response, success
 *   OR failure, of a request issued before it completed;
 * - a response of a request issued after the last mutation is server truth;
 * - a report GET that lands with a higher version than the list entry refreshes
 *   that entry; a list entry never rewrites preview data;
 * - a failed mutation records nothing; its notice stays until the selection changes;
 * - the list keeps its rows on a list failure (only the status banner appears).
 */
import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/types";
import type { Report, ReportCard } from "../api/types";
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

/* Fixtures */

const r1: ReportCard = {
  id: "r1",
  chat_id: "c1",
  title: "Итоги сезона",
  question: "Сколько очков набрали команды?",
  tool: "read_rows",
  args: { table: "results" },
  generated_at: "2026-09-28T10:15:00Z",
  version: 2,
  saved_at: "2026-09-29T09:00:00Z",
  row_count: 2,
  created_at: "2026-09-28T10:15:00Z",
};
const r2: ReportCard = {
  ...r1,
  id: "r2",
  chat_id: null,
  title: "Составы команд",
  version: 1,
  saved_at: "2026-09-27T09:00:00Z",
};
const data = [
  { команда: "Альфа", очки: 10 },
  { команда: "Бета", очки: 7 },
];
const full = (card: ReportCard): Report => ({ ...card, data });
const UPDATED_AT = "2026-09-30T07:45:00Z";
const EXTERNAL_AT = "2026-10-01T09:00:00Z";
/** What Update 200 returns. */
const r1v3: Report = full({ ...r1, generated_at: UPDATED_AT, version: 3 });
/** What a request issued AFTER the mutation returns for r1 (someone updated it again). */
const r1v5: Report = full({ ...r1, generated_at: EXTERNAL_AT, version: 5 });

const networkError = () => new ApiError(0, "network", "Связь с сервером потеряна");

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
  const navigate = useNavigate();
  return (
    <>
      <SavedReportsPage />
      <span data-testid="path">{location.pathname}</span>
      <button type="button" onClick={() => navigate(-1)}>
        history back
      </button>
      <button type="button" onClick={() => navigate(1)}>
        history forward
      </button>
    </>
  );
}

/** The page opened at `path` after visiting /saved/r1 and /saved/r2 before it. */
function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={["/saved/r1", "/saved/r2", path]} initialIndex={2}>
      <Routes>
        <Route path="/saved" element={<Harness />} />
        <Route path="/saved/:reportId" element={<Harness />} />
      </Routes>
    </MemoryRouter>,
  );
}

const pathShown = () => screen.getByTestId("path").textContent;
const list = () => screen.getByRole("navigation", { name: "Сохранённые отчёты" });

/* The matrix */

type Request = "report" | "list";
type Issued = "old" | "new";
type Settle = "resolve" | "fail";
type Mutation = "updateOk" | "updateFail" | "unsaveOk" | "unsaveFail" | "none";
type Route = "same" | "awayBack";

interface Expected {
  path: string;
  /** Version of the r1 preview, the r2 preview, an error note, or nothing shown. */
  preview: { r1: number } | "r2" | "error" | "none";
  /** `id@version` rows in order, or the failure banner. */
  list: string[] | "error";
  notice: "update" | "unsave" | null;
}

interface Cell {
  request: Request;
  issued: Issued;
  settle: Settle;
  mutation: Mutation;
  route: Route;
  expected: Expected;
}

const R1V2_R2 = ["r1@2", "r2@1"];
const R1V3_R2 = ["r1@3", "r2@1"];
const R1V5_R2 = ["r1@5", "r2@1"];

const CELLS: Cell[] = [
  /* report GET issued BEFORE the mutation completed (needs navigate away/back) */
  { request: "report", issued: "old", settle: "resolve", mutation: "updateOk", route: "awayBack",
    expected: { path: "/saved/r1", preview: { r1: 3 }, list: R1V3_R2, notice: null } },
  { request: "report", issued: "old", settle: "fail", mutation: "updateOk", route: "awayBack",
    expected: { path: "/saved/r1", preview: { r1: 3 }, list: R1V3_R2, notice: null } },
  { request: "report", issued: "old", settle: "resolve", mutation: "updateFail", route: "awayBack",
    expected: { path: "/saved/r1", preview: { r1: 2 }, list: R1V2_R2, notice: "update" } },
  { request: "report", issued: "old", settle: "fail", mutation: "updateFail", route: "awayBack",
    expected: { path: "/saved/r1", preview: "error", list: R1V2_R2, notice: null } },
  { request: "report", issued: "old", settle: "resolve", mutation: "unsaveOk", route: "awayBack",
    expected: { path: "/saved/r2", preview: "r2", list: ["r2@1"], notice: null } },
  { request: "report", issued: "old", settle: "fail", mutation: "unsaveOk", route: "awayBack",
    expected: { path: "/saved/r2", preview: "r2", list: ["r2@1"], notice: null } },
  { request: "report", issued: "old", settle: "resolve", mutation: "unsaveFail", route: "awayBack",
    expected: { path: "/saved/r1", preview: { r1: 2 }, list: R1V2_R2, notice: "unsave" } },
  { request: "report", issued: "old", settle: "fail", mutation: "unsaveFail", route: "awayBack",
    expected: { path: "/saved/r1", preview: "error", list: R1V2_R2, notice: null } },
  { request: "report", issued: "old", settle: "resolve", mutation: "none", route: "awayBack",
    expected: { path: "/saved/r1", preview: { r1: 2 }, list: R1V2_R2, notice: null } },
  { request: "report", issued: "old", settle: "fail", mutation: "none", route: "awayBack",
    expected: { path: "/saved/r1", preview: "error", list: R1V2_R2, notice: null } },

  /* report GET issued AFTER the mutation completed (navigate away/back afterwards) */
  { request: "report", issued: "new", settle: "resolve", mutation: "updateOk", route: "awayBack",
    expected: { path: "/saved/r1", preview: { r1: 5 }, list: R1V5_R2, notice: null } },
  { request: "report", issued: "new", settle: "fail", mutation: "updateOk", route: "awayBack",
    expected: { path: "/saved/r1", preview: "error", list: R1V3_R2, notice: null } },
  { request: "report", issued: "new", settle: "resolve", mutation: "updateFail", route: "awayBack",
    expected: { path: "/saved/r1", preview: { r1: 5 }, list: R1V5_R2, notice: null } },
  { request: "report", issued: "new", settle: "fail", mutation: "updateFail", route: "awayBack",
    expected: { path: "/saved/r1", preview: "error", list: R1V2_R2, notice: null } },
  /* r1 is unsaved (bookmark only): Back reaches its history entry and the GET is served */
  { request: "report", issued: "new", settle: "resolve", mutation: "unsaveOk", route: "awayBack",
    expected: { path: "/saved/r1", preview: { r1: 5 }, list: ["r2@1"], notice: null } },
  { request: "report", issued: "new", settle: "fail", mutation: "unsaveOk", route: "awayBack",
    expected: { path: "/saved/r1", preview: "error", list: ["r2@1"], notice: null } },
  { request: "report", issued: "new", settle: "resolve", mutation: "unsaveFail", route: "awayBack",
    expected: { path: "/saved/r1", preview: { r1: 5 }, list: R1V5_R2, notice: null } },
  { request: "report", issued: "new", settle: "fail", mutation: "unsaveFail", route: "awayBack",
    expected: { path: "/saved/r1", preview: "error", list: R1V2_R2, notice: null } },
  { request: "report", issued: "new", settle: "resolve", mutation: "none", route: "awayBack",
    expected: { path: "/saved/r1", preview: { r1: 5 }, list: R1V5_R2, notice: null } },
  { request: "report", issued: "new", settle: "fail", mutation: "none", route: "awayBack",
    expected: { path: "/saved/r1", preview: "error", list: R1V2_R2, notice: null } },

  /* list GET issued BEFORE the mutation completed (the initial list request) */
  { request: "list", issued: "old", settle: "resolve", mutation: "updateOk", route: "same",
    expected: { path: "/saved/r1", preview: { r1: 3 }, list: R1V3_R2, notice: null } },
  { request: "list", issued: "old", settle: "fail", mutation: "updateOk", route: "same",
    expected: { path: "/saved/r1", preview: { r1: 3 }, list: "error", notice: null } },
  { request: "list", issued: "old", settle: "resolve", mutation: "updateFail", route: "same",
    expected: { path: "/saved/r1", preview: { r1: 2 }, list: R1V2_R2, notice: "update" } },
  { request: "list", issued: "old", settle: "fail", mutation: "updateFail", route: "same",
    expected: { path: "/saved/r1", preview: { r1: 2 }, list: "error", notice: "update" } },
  { request: "list", issued: "old", settle: "resolve", mutation: "unsaveOk", route: "same",
    expected: { path: "/saved/r2", preview: "r2", list: ["r2@1"], notice: null } },
  { request: "list", issued: "old", settle: "fail", mutation: "unsaveOk", route: "same",
    expected: { path: "/saved", preview: "none", list: "error", notice: null } },
  { request: "list", issued: "old", settle: "resolve", mutation: "unsaveFail", route: "same",
    expected: { path: "/saved/r1", preview: { r1: 2 }, list: R1V2_R2, notice: "unsave" } },
  { request: "list", issued: "old", settle: "fail", mutation: "unsaveFail", route: "same",
    expected: { path: "/saved/r1", preview: { r1: 2 }, list: "error", notice: "unsave" } },
  { request: "list", issued: "old", settle: "resolve", mutation: "none", route: "same",
    expected: { path: "/saved/r1", preview: { r1: 2 }, list: R1V2_R2, notice: null } },
  { request: "list", issued: "old", settle: "fail", mutation: "none", route: "same",
    expected: { path: "/saved/r1", preview: { r1: 2 }, list: "error", notice: null } },

  /* list GET issued BEFORE the mutation completed; Back/Forward while it is pending
     (no rows to click; the history entries exist). The re-issued r1 GET resolves at
     once with what the server has at that moment. */
  { request: "list", issued: "old", settle: "resolve", mutation: "updateOk", route: "awayBack",
    expected: { path: "/saved/r1", preview: { r1: 3 }, list: R1V3_R2, notice: null } },
  { request: "list", issued: "old", settle: "fail", mutation: "updateOk", route: "awayBack",
    expected: { path: "/saved/r1", preview: { r1: 3 }, list: "error", notice: null } },
  { request: "list", issued: "old", settle: "resolve", mutation: "updateFail", route: "awayBack",
    expected: { path: "/saved/r1", preview: { r1: 2 }, list: R1V2_R2, notice: "update" } },
  { request: "list", issued: "old", settle: "fail", mutation: "updateFail", route: "awayBack",
    expected: { path: "/saved/r1", preview: { r1: 2 }, list: "error", notice: "update" } },
  { request: "list", issued: "old", settle: "resolve", mutation: "unsaveOk", route: "awayBack",
    expected: { path: "/saved/r2", preview: "r2", list: ["r2@1"], notice: null } },
  { request: "list", issued: "old", settle: "fail", mutation: "unsaveOk", route: "awayBack",
    expected: { path: "/saved", preview: "none", list: "error", notice: null } },
  { request: "list", issued: "old", settle: "resolve", mutation: "unsaveFail", route: "awayBack",
    expected: { path: "/saved/r1", preview: { r1: 2 }, list: R1V2_R2, notice: "unsave" } },
  { request: "list", issued: "old", settle: "fail", mutation: "unsaveFail", route: "awayBack",
    expected: { path: "/saved/r1", preview: { r1: 2 }, list: "error", notice: "unsave" } },
  { request: "list", issued: "old", settle: "resolve", mutation: "none", route: "awayBack",
    expected: { path: "/saved/r1", preview: { r1: 2 }, list: R1V2_R2, notice: null } },
  { request: "list", issued: "old", settle: "fail", mutation: "none", route: "awayBack",
    expected: { path: "/saved/r1", preview: { r1: 2 }, list: "error", notice: null } },

  /* list GET issued AFTER the mutation completed («Повторить» after a failed initial list) */
  { request: "list", issued: "new", settle: "resolve", mutation: "updateOk", route: "same",
    expected: { path: "/saved/r1", preview: { r1: 3 }, list: R1V3_R2, notice: null } },
  { request: "list", issued: "new", settle: "fail", mutation: "updateOk", route: "same",
    expected: { path: "/saved/r1", preview: { r1: 3 }, list: "error", notice: null } },
  { request: "list", issued: "new", settle: "resolve", mutation: "updateFail", route: "same",
    expected: { path: "/saved/r1", preview: { r1: 2 }, list: R1V2_R2, notice: "update" } },
  { request: "list", issued: "new", settle: "fail", mutation: "updateFail", route: "same",
    expected: { path: "/saved/r1", preview: { r1: 2 }, list: "error", notice: "update" } },
  { request: "list", issued: "new", settle: "resolve", mutation: "unsaveOk", route: "same",
    expected: { path: "/saved/r2", preview: "r2", list: ["r2@1"], notice: null } },
  { request: "list", issued: "new", settle: "fail", mutation: "unsaveOk", route: "same",
    expected: { path: "/saved", preview: "none", list: "error", notice: null } },
  { request: "list", issued: "new", settle: "resolve", mutation: "unsaveFail", route: "same",
    expected: { path: "/saved/r1", preview: { r1: 2 }, list: R1V2_R2, notice: "unsave" } },
  { request: "list", issued: "new", settle: "fail", mutation: "unsaveFail", route: "same",
    expected: { path: "/saved/r1", preview: { r1: 2 }, list: "error", notice: "unsave" } },
  { request: "list", issued: "new", settle: "resolve", mutation: "none", route: "same",
    expected: { path: "/saved/r1", preview: { r1: 2 }, list: R1V2_R2, notice: null } },
  { request: "list", issued: "new", settle: "fail", mutation: "none", route: "same",
    expected: { path: "/saved/r1", preview: { r1: 2 }, list: "error", notice: null } },

  /* list GET issued AFTER the mutation («Повторить»); Back/Forward while it is pending.
     After a confirmed Update the re-issued r1 GET already returns v3. */
  { request: "list", issued: "new", settle: "resolve", mutation: "updateOk", route: "awayBack",
    expected: { path: "/saved/r1", preview: { r1: 3 }, list: R1V3_R2, notice: null } },
  { request: "list", issued: "new", settle: "fail", mutation: "updateOk", route: "awayBack",
    expected: { path: "/saved/r1", preview: { r1: 3 }, list: "error", notice: null } },
  { request: "list", issued: "new", settle: "resolve", mutation: "updateFail", route: "awayBack",
    expected: { path: "/saved/r1", preview: { r1: 2 }, list: R1V2_R2, notice: null } },
  { request: "list", issued: "new", settle: "fail", mutation: "updateFail", route: "awayBack",
    expected: { path: "/saved/r1", preview: { r1: 2 }, list: "error", notice: null } },
  { request: "list", issued: "new", settle: "resolve", mutation: "unsaveOk", route: "awayBack",
    expected: { path: "/saved/r2", preview: "r2", list: ["r2@1"], notice: null } },
  { request: "list", issued: "new", settle: "fail", mutation: "unsaveOk", route: "awayBack",
    expected: { path: "/saved", preview: "none", list: "error", notice: null } },
  { request: "list", issued: "new", settle: "resolve", mutation: "unsaveFail", route: "awayBack",
    expected: { path: "/saved/r1", preview: { r1: 2 }, list: R1V2_R2, notice: null } },
  { request: "list", issued: "new", settle: "fail", mutation: "unsaveFail", route: "awayBack",
    expected: { path: "/saved/r1", preview: { r1: 2 }, list: "error", notice: null } },
  { request: "list", issued: "new", settle: "resolve", mutation: "none", route: "awayBack",
    expected: { path: "/saved/r1", preview: { r1: 2 }, list: R1V2_R2, notice: null } },
  { request: "list", issued: "new", settle: "fail", mutation: "none", route: "awayBack",
    expected: { path: "/saved/r1", preview: { r1: 2 }, list: "error", notice: null } },
];

interface NotConstructible {
  request: Request;
  issued: Issued | "any";
  settle: Settle | "any";
  mutation: Mutation | "any";
  route: Route;
  reason: string;
}

const NOT_CONSTRUCTIBLE: NotConstructible[] = [
  {
    request: "report", issued: "any", settle: "any", mutation: "any", route: "same",
    reason:
      "no report GET can be pending on the same route: the selection GET has resolved before «Обновить» / «Убрать» are enabled, a mutation issues no report GET, and Back/Forward is a route change",
  },
];

/* Runner */

const MUTATIONS: Mutation[] = ["updateOk", "updateFail", "unsaveOk", "unsaveFail", "none"];

function cellKey(c: { request: Request; issued: Issued; settle: Settle; mutation: Mutation; route: Route }) {
  return `${c.request}/${c.issued}/${c.settle}/${c.mutation}/${c.route}`;
}

function expandNotConstructible(): Set<string> {
  const keys = new Set<string>();
  for (const n of NOT_CONSTRUCTIBLE) {
    for (const issued of n.issued === "any" ? (["old", "new"] as Issued[]) : [n.issued]) {
      for (const settle of n.settle === "any" ? (["resolve", "fail"] as Settle[]) : [n.settle]) {
        for (const mutation of n.mutation === "any" ? MUTATIONS : [n.mutation]) {
          keys.add(cellKey({ request: n.request, issued, settle, mutation, route: n.route }));
        }
      }
    }
  }
  return keys;
}

function listPayload(issued: Issued, mutation: Mutation): ReportCard[] {
  if (issued === "old") return [r1, r2]; // the snapshot from before the mutation
  if (mutation === "updateOk") return [{ ...r1, generated_at: UPDATED_AT, version: 3 }, r2];
  if (mutation === "unsaveOk") return [r2];
  return [r1, r2];
}

type User = ReturnType<typeof userEvent.setup>;

const r2Shown = () =>
  waitFor(() =>
    expect(within(screen.getByRole("article")).getByRole("heading", { name: "Составы команд" })).toBeInTheDocument(),
  );

/** Leave r1 for r2 and come back through the list rows. */
async function awayAndBackViaLinks(user: User) {
  await user.click(within(list()).getByRole("link", { name: /Составы команд/ }));
  await r2Shown();
  await user.click(within(list()).getByRole("link", { name: /Итоги сезона/ }));
}

/** Browser Back (to the /saved/r2 entry) and Forward (to where we were). */
async function awayAndBackViaHistory(user: User) {
  const origin = pathShown();
  await user.click(screen.getByRole("button", { name: "history back" }));
  await r2Shown();
  await user.click(screen.getByRole("button", { name: "history forward" }));
  await waitFor(() => expect(pathShown()).toBe(origin));
}

/** After Unsave r1 replaced the current entry with /saved/r2 the history is
    [/saved/r1, /saved/r2, /saved/r2]: two Backs reach the unsaved report. */
async function backToUnsavedR1ViaHistory(user: User) {
  await user.click(screen.getByRole("button", { name: "history back" }));
  await user.click(screen.getByRole("button", { name: "history back" }));
  await waitFor(() => expect(pathShown()).toBe("/saved/r1"));
}

async function flush() {
  await act(async () => {});
}

async function runCell(cell: Cell) {
  const listDeferred = deferred<ReportCard[]>();
  const reportDeferred = deferred<Report>();

  if (cell.request === "list") {
    if (cell.issued === "old") {
      listSavedReports.mockReturnValueOnce(listDeferred.promise);
    } else {
      listSavedReports.mockRejectedValueOnce(networkError());
      listSavedReports.mockReturnValueOnce(listDeferred.promise);
    }
  } else {
    listSavedReports.mockResolvedValue([r1, r2]);
  }

  // What the server holds for r1 right now; a confirmed Update advances it.
  let serverR1: Report = full(r1);
  let r1Gets = 0;
  getReport.mockImplementation((id) => {
    if (id === "r1") {
      r1Gets += 1;
      return cell.request === "report" && r1Gets === 2
        ? reportDeferred.promise
        : Promise.resolve(serverR1);
    }
    return Promise.resolve(full(r2));
  });

  renderAt("/saved/r1");
  await screen.findByRole("article");
  if (cell.request === "list" && cell.issued === "new") {
    await screen.findByText("Сервер недоступен");
  }
  const user = userEvent.setup();
  // The list has rows to click only when it resolved before the mutation.
  const awayAndBack = cell.request === "report" ? awayAndBackViaLinks : awayAndBackViaHistory;

  // 1. Start the mutation.
  const mutation = deferred<Report | void>();
  if (cell.mutation === "updateOk" || cell.mutation === "updateFail") {
    updateReport.mockReturnValue(mutation.promise as Promise<Report>);
    await user.click(screen.getByRole("button", { name: "Обновить" }));
  } else if (cell.mutation === "unsaveOk" || cell.mutation === "unsaveFail") {
    unsaveReport.mockReturnValue(mutation.promise as Promise<void>);
    await user.click(screen.getByRole("button", { name: "Убрать из сохранённых" }));
  }

  // 2. Leave and re-select r1 while the mutation is pending: a report GET
  //    "issued before the mutation completed" (for a list cell the pending list
  //    request under test is the old one; the navigation happens meanwhile).
  if (cell.issued === "old" && cell.route === "awayBack") {
    await awayAndBack(user);
    if (cell.request === "report") await waitFor(() => expect(r1Gets).toBe(2));
  }

  // 3. Settle the mutation.
  await act(async () => {
    switch (cell.mutation) {
      case "updateOk":
        serverR1 = r1v3;
        mutation.resolve(r1v3);
        break;
      case "updateFail":
        mutation.reject(new ApiError(502, "update_failed", "Инструмент вернул ошибку"));
        break;
      case "unsaveOk":
        mutation.resolve(undefined);
        break;
      case "unsaveFail":
        mutation.reject(networkError());
        break;
      case "none":
        break;
    }
  });
  if (cell.mutation === "unsaveOk") {
    await waitFor(() => expect(pathShown()).not.toBe("/saved/r1"));
  }

  // 4. A request "issued after the mutation completed".
  if (cell.issued === "new") {
    if (cell.request === "report") {
      if (cell.mutation === "unsaveOk") await backToUnsavedR1ViaHistory(user);
      else await awayAndBack(user);
      await waitFor(() => expect(r1Gets).toBe(2));
    } else {
      await user.click(screen.getByRole("button", { name: "Повторить" }));
      if (cell.route === "awayBack") await awayAndBack(user);
    }
  }

  // 5. Settle the request.
  await act(async () => {
    if (cell.request === "report") {
      if (cell.settle === "resolve") reportDeferred.resolve(cell.issued === "old" ? full(r1) : r1v5);
      else reportDeferred.reject(networkError());
    } else if (cell.settle === "resolve") listDeferred.resolve(listPayload(cell.issued, cell.mutation));
    else listDeferred.reject(networkError());
  });
  await flush();

  // 6. Assert.
  const { expected } = cell;
  await waitFor(() => expect(pathShown()).toBe(expected.path));

  if (expected.list === "error") {
    await waitFor(() => expect(within(list()).getByText("Сервер недоступен")).toBeInTheDocument());
  } else {
    const rows = await within(list()).findAllByRole("listitem");
    const shown = rows.map((row) => {
      const title = within(row).getByRole("link", { name: /Сформирован/ }).getAttribute("href") ?? "";
      const id = title.replace("/saved/", "");
      const version = within(row).getByText(/^Версия \d+$/).textContent?.replace("Версия ", "") ?? "?";
      return `${id}@${version}`;
    });
    expect(shown).toEqual(expected.list);
  }

  if (expected.preview === "none") {
    expect(screen.queryByRole("article")).toBeNull();
    expect(screen.queryByRole("link", { name: "К списку" })).toBeNull();
  } else if (expected.preview === "error") {
    await waitFor(() => expect(screen.getByRole("link", { name: "К списку" })).toBeInTheDocument());
    expect(screen.queryByRole("article")).toBeNull();
  } else if (expected.preview === "r2") {
    const article = await screen.findByRole("article");
    expect(within(article).getByRole("heading", { name: "Составы команд" })).toBeInTheDocument();
  } else {
    const article = await screen.findByRole("article");
    expect(within(article).getByRole("heading", { name: "Итоги сезона" })).toBeInTheDocument();
    expect(within(article).getByText(`Версия ${String(expected.preview.r1)}`)).toBeInTheDocument();
  }

  const updateNotice = screen.queryByText(/^Обновить не удалось/);
  const unsaveNotice = screen.queryByText(/^Убрать не удалось/);
  expect(updateNotice !== null ? "update" : unsaveNotice !== null ? "unsave" : null).toBe(expected.notice);

  // Invariant: every request has settled, so nothing is still loading.
  expect(screen.queryByText("Загрузка отчёта…")).toBeNull();
  expect(within(list()).queryByText("Загрузка…")).toBeNull();
}

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("SavedReportsPage response-ordering matrix", () => {
  it("covers every cell of the product exactly once (constructible or explained)", () => {
    const constructible = new Set(CELLS.map(cellKey));
    expect(constructible.size).toBe(CELLS.length);
    const excluded = expandNotConstructible();
    const all = new Set<string>();
    for (const request of ["report", "list"] as Request[])
      for (const issued of ["old", "new"] as Issued[])
        for (const settle of ["resolve", "fail"] as Settle[])
          for (const mutation of MUTATIONS)
            for (const route of ["same", "awayBack"] as Route[])
              all.add(cellKey({ request, issued, settle, mutation, route }));
    expect(all.size).toBe(80);
    for (const key of constructible) expect(excluded.has(key), `${key} listed twice`).toBe(false);
    const missing = [...all].filter((key) => !constructible.has(key) && !excluded.has(key));
    expect(missing).toEqual([]);
  });

  for (const cell of CELLS) {
    it(cellKey(cell), async () => {
      await runCell(cell);
    });
  }
});
