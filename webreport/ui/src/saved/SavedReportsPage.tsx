/**
 * Saved Reports tab (`/saved`, `/saved/:reportId`): the bookmarked reports
 * from every chat on the left, the selected report's preview on the right.
 *
 * «Обновить» replays the report's stored handle on the server; a success
 * replaces the preview and the list entry's date, a failure keeps the version
 * on screen and says why. The list stays usable while an update runs.
 *
 * All page state lives in ONE reducer. Every response and every confirmed
 * mutation is an action that reconciles against the reducer's own current
 * state, so the order in which responses settle - even inside one React
 * batch - cannot change the outcome. Effects only issue requests and perform
 * the navigation the reducer decided; nothing is read from refs or closures.
 *
 * Ordering is tracked on one timeline (`generation`) but decided PER REPORT:
 * a response is reconciled only against confirmed mutations of the report(s)
 * it is about that landed after it was issued. A settled report request always
 * ends the preview's loading state: ready, error or missing.
 */

import { useEffect, useReducer } from "react";
import { Link, NavLink, useNavigate, useParams } from "react-router-dom";

import {
  getReport,
  listSavedReports,
  unsaveReport,
  updateReport,
} from "../api/client";
import { ApiError } from "../api/types";
import type { Report, ReportCard } from "../api/types";
import { ReportPreview, formatGeneratedAt } from "../reports/ReportPreview";
import { ThinkingMark } from "../thinking/ThinkingMark";

export const SERVER_UNAVAILABLE = "Сервер недоступен";
export const NETWORK_UPDATE_MESSAGE = "Нет связи с сервером";
export const REPORT_BUSY_MESSAGE = "Отчёт занят, повторите позже";
export const REPORT_MISSING_MESSAGE = "Отчёт не найден";
export const EMPTY_MESSAGE = "Сохранённых отчётов пока нет";

const savedPath = (reportId: string) => `/saved/${encodeURIComponent(reportId)}`;
const chatPath = (chatId: string) => `/chats/${encodeURIComponent(chatId)}`;

function describeError(error: unknown): string {
  if (error instanceof ApiError) {
    return error.status === 0 ? SERVER_UNAVAILABLE : error.message;
  }
  return error instanceof Error ? error.message : String(error);
}

/** The inline text after a failed «Обновить»: the shown version stays on screen. */
export function describeUpdateError(error: unknown, shown: ReportCard): string {
  if (error instanceof ApiError && error.code === "report_busy") {
    return REPORT_BUSY_MESSAGE;
  }
  const reason =
    error instanceof ApiError && error.status === 0
      ? NETWORK_UPDATE_MESSAGE
      : describeError(error);
  return `Обновить не удалось: ${reason}. Показана версия от ${formatGeneratedAt(shown.generated_at)}`;
}

/* State */

type ListStatus = "loading" | "ready" | "error";

type PreviewState =
  | { kind: "idle" }
  | { kind: "loading" }
  | { kind: "ready"; report: Report }
  | { kind: "missing" }
  | { kind: "error"; message: string };

interface Notice {
  reportId: string;
  text: string;
}

/** A confirmed Update and the generation at which it was confirmed. */
interface UpdateRecord {
  report: Report;
  at: number;
}

export interface SavedState {
  /* Mutation ledger. `generation` is the page-wide sequence of confirmed
     mutations (Update 200, Unsave 204); a response carries the generation it
     was issued at. Per report id, `updated` / `unsaved` record the result and
     the generation at which THAT report's mutation was confirmed. A response is
     reconciled against exactly the mutations of the reports it is about that
     were confirmed after it was issued (`at > issuedAt`): unsaved ids are
     dropped, updated ids version-merged (`version` is monotonic per report).
     Everything else is server truth (a report re-saved elsewhere may
     legitimately return; a mutation of another report says nothing). */
  generation: number;
  updated: ReadonlyMap<string, UpdateRecord>;
  unsaved: ReadonlyMap<string, number>;

  /* Saved list. `listSeq` identifies the request whose answer is awaited. */
  listSeq: number;
  listStatus: ListStatus;
  listError: string | null;
  items: ReportCard[];

  /* Selection (mirrors the route param) and its preview. `previewSeq`
     identifies the report request whose answer is awaited. */
  selected: string | undefined;
  previewSeq: number;
  preview: PreviewState;

  updatingId: string | null;
  removing: boolean;
  notice: Notice | null;

  /** Navigation decided by the reducer; the page performs it and acknowledges. */
  navigateTo: string | null;
}

export type SavedAction =
  | { type: "select"; reportId: string | undefined }
  | { type: "retryList" }
  | { type: "listLoaded"; seq: number; issuedAt: number; cards: ReportCard[] }
  | { type: "listFailed"; seq: number; message: string }
  | { type: "reportLoaded"; seq: number; issuedAt: number; report: Report }
  | {
      type: "reportFailed";
      seq: number;
      issuedAt: number;
      reportId: string;
      missing: boolean;
      message: string;
    }
  | { type: "updateStarted"; reportId: string }
  | { type: "updateSucceeded"; report: Report }
  | { type: "updateFailed"; reportId: string; text: string }
  | { type: "unsaveStarted" }
  | { type: "unsaveSucceeded"; reportId: string }
  | { type: "unsaveFailed"; reportId: string; text: string }
  | { type: "navigated" };

export function initialState(reportId: string | undefined): SavedState {
  return {
    generation: 0,
    updated: new Map(),
    unsaved: new Map(),
    listSeq: 0,
    listStatus: "loading",
    listError: null,
    items: [],
    selected: reportId,
    previewSeq: 0,
    preview: reportId === undefined ? { kind: "idle" } : { kind: "loading" },
    updatingId: null,
    removing: false,
    notice: null,
    navigateTo: null,
  };
}

/** The confirmed Update of `id` that landed after a request issued at `issuedAt`. */
function updateAfter(state: SavedState, id: string, issuedAt: number): Report | undefined {
  const record = state.updated.get(id);
  return record !== undefined && record.at > issuedAt ? record.report : undefined;
}

/** Whether `id` was unsaved after a request issued at `issuedAt`. */
function unsavedAfter(state: SavedState, id: string, issuedAt: number): boolean {
  const at = state.unsaved.get(id);
  return at !== undefined && at > issuedAt;
}

function newestCard<T extends ReportCard>(card: T, fresh: Report | undefined): T {
  if (fresh === undefined || fresh.version <= card.version) return card;
  return {
    ...card,
    generated_at: fresh.generated_at,
    version: fresh.version,
    row_count: fresh.row_count,
  };
}

function newestReport(report: Report, fresh: Report | undefined): Report {
  return fresh === undefined || fresh.version <= report.version ? report : fresh;
}

function reconcileCards(cards: ReportCard[], issuedAt: number, state: SavedState): ReportCard[] {
  return cards
    .filter((card) => !unsavedAfter(state, card.id, issuedAt))
    .map((card) => newestCard(card, updateAfter(state, card.id, issuedAt)));
}

export function reducer(state: SavedState, action: SavedAction): SavedState {
  switch (action.type) {
    case "select": {
      if (action.reportId === state.selected) return state;
      return {
        ...state,
        selected: action.reportId,
        previewSeq: state.previewSeq + 1,
        preview: action.reportId === undefined ? { kind: "idle" } : { kind: "loading" },
        // A failure notice belongs to the report it was shown on.
        notice: null,
      };
    }
    case "retryList":
      return { ...state, listSeq: state.listSeq + 1, listStatus: "loading", listError: null };
    case "listLoaded": {
      if (action.seq !== state.listSeq) return state;
      return {
        ...state,
        listStatus: "ready",
        listError: null,
        items: reconcileCards(action.cards, action.issuedAt, state),
      };
    }
    case "listFailed": {
      if (action.seq !== state.listSeq) return state;
      return { ...state, listStatus: "error", listError: action.message };
    }
    case "reportLoaded": {
      if (action.seq !== state.previewSeq) return state;
      const report = newestReport(
        action.report,
        updateAfter(state, action.report.id, action.issuedAt),
      );
      return {
        ...state,
        preview: { kind: "ready", report },
        // A fresher report also refreshes its own list entry (one object, two views).
        items: state.items.map((item) =>
          item.id === report.id && report.version > item.version
            ? {
                ...item,
                generated_at: report.generated_at,
                version: report.version,
                row_count: report.row_count,
              }
            : item,
        ),
      };
    }
    case "reportFailed": {
      if (action.seq !== state.previewSeq) return state;
      // A confirmed Update of this very report that landed after the request
      // was issued is newer than the failure: show it (the preview normally
      // holds it already). Every other failure is real - a settled request
      // never leaves the preview loading.
      const fresh = updateAfter(state, action.reportId, action.issuedAt);
      if (fresh !== undefined) {
        const { preview } = state;
        const shown =
          preview.kind === "ready" && preview.report.id === fresh.id
            ? newestReport(preview.report, fresh)
            : fresh;
        return { ...state, preview: { kind: "ready", report: shown } };
      }
      return {
        ...state,
        preview: action.missing ? { kind: "missing" } : { kind: "error", message: action.message },
      };
    }
    case "updateStarted":
      return { ...state, updatingId: action.reportId, notice: null };
    case "updateSucceeded": {
      const generation = state.generation + 1;
      const fresh = action.report;
      const updated = new Map(state.updated);
      updated.set(fresh.id, { report: fresh, at: generation });
      const { preview } = state;
      // The update result is a full Report: while its report is the selection it
      // is shown at once, whether the preview was ready, still loading or failed.
      let nextPreview = preview;
      if (preview.kind === "ready" && preview.report.id === fresh.id) {
        nextPreview = { kind: "ready", report: newestReport(preview.report, fresh) };
      } else if (state.selected === fresh.id) {
        nextPreview = { kind: "ready", report: fresh };
      }
      return {
        ...state,
        generation,
        updated,
        items: state.items.map((item) => (item.id === fresh.id ? newestCard(item, fresh) : item)),
        preview: nextPreview,
        updatingId: null,
      };
    }
    case "updateFailed":
      return {
        ...state,
        updatingId: null,
        notice: { reportId: action.reportId, text: action.text },
      };
    case "unsaveStarted":
      return { ...state, removing: true, notice: null };
    case "unsaveSucceeded": {
      const generation = state.generation + 1;
      const unsaved = new Map(state.unsaved);
      unsaved.set(action.reportId, generation);
      const index = state.items.findIndex((item) => item.id === action.reportId);
      const rest = state.items.filter((item) => item.id !== action.reportId);
      // Select the neighbour only when the removed report is the one open; a
      // selection the user made meanwhile is kept.
      let navigateTo = state.navigateTo;
      if (state.selected === action.reportId) {
        const next = rest[index] ?? rest[index - 1];
        navigateTo = next === undefined ? "/saved" : savedPath(next.id);
      }
      return {
        ...state,
        generation,
        unsaved,
        items: rest,
        removing: false,
        navigateTo,
      };
    }
    case "unsaveFailed":
      return {
        ...state,
        removing: false,
        notice: { reportId: action.reportId, text: action.text },
      };
    case "navigated":
      return { ...state, navigateTo: null };
  }
}

/* List */

interface SavedListProps {
  items: ReportCard[];
  status: ListStatus;
  error: string | null;
  onRetry: () => void;
}

function SavedList({ items, status, error, onRetry }: SavedListProps) {
  return (
    <nav className="saved-list" aria-label="Сохранённые отчёты">
      <div className="saved-list__head">
        <h1 className="saved-list__heading">Сохранённые отчёты</h1>
        {status === "ready" ? (
          <span className="saved-list__count" aria-label={`Отчётов: ${String(items.length)}`}>
            {items.length}
          </span>
        ) : null}
      </div>
      <div className="saved-list__body">
        {status === "loading" ? <p className="saved-list__note">Загрузка…</p> : null}
        {status === "error" ? (
          <div className="saved-list__error" role="alert">
            <span>{error}</span>
            <button type="button" className="button button-secondary" onClick={onRetry}>
              Повторить
            </button>
          </div>
        ) : null}
        {status === "ready" && items.length === 0 ? (
          <div className="saved-empty">
            <p className="saved-empty__title">{EMPTY_MESSAGE}</p>
            <p className="saved-empty__text">
              Нажмите «Сохранить» у отчёта в чате — он появится здесь и будет
              обновляться по актуальным данным.
            </p>
          </div>
        ) : null}
        {items.length > 0 ? (
          <ul className="saved-rows">
            {items.map((item) => (
              <li key={item.id} className="saved-row">
                <NavLink className="saved-row__link" to={savedPath(item.id)} title={item.title}>
                  <span className="saved-row__title">{item.title}</span>
                  <span className="saved-row__meta">
                    <span>Сформирован {formatGeneratedAt(item.generated_at)}</span>
                    <span className="saved-row__version">Версия {item.version}</span>
                  </span>
                </NavLink>
                <span className="saved-row__origin">
                  {item.chat_id === null ? (
                    <span className="saved-row__orphan">Чат удалён</span>
                  ) : (
                    <Link className="saved-row__chat" to={chatPath(item.chat_id)}>
                      Открыть чат
                    </Link>
                  )}
                </span>
              </li>
            ))}
          </ul>
        ) : null}
      </div>
    </nav>
  );
}

/* Page */

export function SavedReportsPage() {
  const { reportId } = useParams();
  const navigate = useNavigate();
  const [state, dispatch] = useReducer(reducer, reportId, initialState);

  // The route is the source of the selection: sync it during render so no
  // action can ever observe a selection that lags the URL.
  if (state.selected !== reportId) {
    dispatch({ type: "select", reportId });
  }

  // Issue the saved-list request for `listSeq`; its answer carries the ledger
  // generation it was issued at (the generation of this render).
  const { listSeq, previewSeq, selected, generation } = state;
  useEffect(() => {
    listSavedReports().then(
      (cards) => dispatch({ type: "listLoaded", seq: listSeq, issuedAt: generation, cards }),
      (error: unknown) =>
        dispatch({ type: "listFailed", seq: listSeq, message: describeError(error) }),
    );
  }, [listSeq]); // `generation` is sampled at issue time, not a trigger

  // Issue the report request for `previewSeq` (one per selection).
  useEffect(() => {
    if (selected === undefined) return;
    getReport(selected).then(
      (report) => dispatch({ type: "reportLoaded", seq: previewSeq, issuedAt: generation, report }),
      (error: unknown) =>
        dispatch({
          type: "reportFailed",
          seq: previewSeq,
          issuedAt: generation,
          reportId: selected,
          missing: error instanceof ApiError && error.status === 404,
          message: describeError(error),
        }),
    );
  }, [previewSeq]); // `selected` and `generation` are sampled per sequence, not triggers

  // Navigation decided by the reducer (after an unsave).
  const { navigateTo } = state;
  useEffect(() => {
    if (navigateTo === null) return;
    navigate(navigateTo, { replace: true });
    dispatch({ type: "navigated" });
  }, [navigateTo, navigate]);

  // `/saved` without an id opens the most recently saved report.
  const { listStatus, items } = state;
  useEffect(() => {
    if (selected !== undefined || listStatus !== "ready" || navigateTo !== null) return;
    const first = items[0];
    if (first !== undefined) {
      navigate(savedPath(first.id), { replace: true });
    }
  }, [selected, listStatus, items, navigateTo, navigate]);

  const busy = state.updatingId !== null || state.removing;

  const update = async (shown: Report) => {
    if (busy) return;
    dispatch({ type: "updateStarted", reportId: shown.id });
    try {
      const fresh = await updateReport(shown.id);
      dispatch({ type: "updateSucceeded", report: fresh });
    } catch (error) {
      dispatch({ type: "updateFailed", reportId: shown.id, text: describeUpdateError(error, shown) });
    }
  };

  const unsave = async (shown: Report) => {
    if (busy) return;
    dispatch({ type: "unsaveStarted" });
    try {
      await unsaveReport(shown.id);
      dispatch({ type: "unsaveSucceeded", reportId: shown.id });
    } catch (error) {
      dispatch({
        type: "unsaveFailed",
        reportId: shown.id,
        text: `Убрать не удалось: ${describeError(error)}`,
      });
    }
  };

  const { preview, notice, updatingId } = state;
  const shownNotice =
    notice !== null && preview.kind === "ready" && preview.report.id === notice.reportId
      ? notice.text
      : null;

  return (
    <div className="saved-layout">
      <SavedList
        items={items}
        status={listStatus}
        error={state.listError}
        onRetry={() => dispatch({ type: "retryList" })}
      />
      <section className="saved-main" aria-label="Просмотр отчёта">
        {preview.kind === "loading" ? <p className="saved-main__note">Загрузка отчёта…</p> : null}
        {preview.kind === "missing" ? (
          <div className="saved-main__note">
            <p>{REPORT_MISSING_MESSAGE}</p>
            <Link to="/saved">К списку</Link>
          </div>
        ) : null}
        {preview.kind === "error" ? (
          <div className="saved-main__note" role="alert">
            <p>{preview.message}</p>
            <Link to="/saved">К списку</Link>
          </div>
        ) : null}
        {preview.kind === "ready" ? (
          <>
            <div className="saved-toolbar">
              {updatingId === preview.report.id ? <ThinkingMark phase="reading" /> : null}
              <div className="saved-toolbar__actions">
                <button
                  type="button"
                  className="button button-secondary"
                  onClick={() => void unsave(preview.report)}
                  disabled={busy}
                >
                  Убрать из сохранённых
                </button>
                <button
                  type="button"
                  className="button button-primary"
                  onClick={() => void update(preview.report)}
                  disabled={busy}
                >
                  Обновить
                </button>
              </div>
            </div>
            {shownNotice !== null ? (
              <p className="saved-notice" role="alert">
                {shownNotice}
              </p>
            ) : null}
            <ReportPreview
              report={preview.report}
              orphan={preview.report.chat_id === null}
              chatLink={
                preview.report.chat_id === null ? undefined : (
                  <Link className="saved-chat-link" to={chatPath(preview.report.chat_id)}>
                    Открыть чат
                  </Link>
                )
              }
            />
          </>
        ) : null}
      </section>
    </div>
  );
}

export default SavedReportsPage;
