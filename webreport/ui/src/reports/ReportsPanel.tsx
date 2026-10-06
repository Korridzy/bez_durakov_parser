/**
 * The right-hand panel of one chat: its retained reports as cards, a prominent
 * in-panel preview (with a fullscreen dialog) and the Save bookmark toggle.
 *
 * State lives in `ReportsProvider` (which chat, which report is open, refresh
 * requests) so the conversation can open a report from a message chip; the
 * data itself (cards, the loaded report, save calls) lives here.
 *
 * Per-report fields (title, generated_at, version, row_count, saved_at) have
 * ONE source: the `ReportRecords` map (see `reportRecords.ts` for how content
 * and bookmark are ordered). The card list only orders ids, the preview only
 * holds the fetched `data`; card, preview and fullscreen dialog all render the
 * record, so no surface can disagree with another. A newer observation whose
 * version moved past the loaded `data` makes the preview re-fetch instead of
 * showing new metadata over old rows.
 */

import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type CSSProperties,
  type KeyboardEvent,
  type PointerEvent,
} from "react";

import {
  getReport,
  listChatReports,
  saveReport,
  unsaveReport,
} from "../api/client";
import { ApiError } from "../api/types";
import type { Report, ReportCard } from "../api/types";
import { usePrefersReducedMotion } from "../motion/usePrefersReducedMotion";
import {
  beginMutation,
  confirmMutation,
  effectiveCard,
  failMutation,
  forgetReport,
  NO_RECORDS,
  observe,
  observeAll,
  reconcileCompleted,
  reconcileIssued,
  type ReportRecords,
  wantsReconcile,
} from "./reportRecords";
import { formatGeneratedAt, ReportPreview } from "./ReportPreview";
import { useReports } from "./ReportsContext";

export const PANEL_WIDTH_STORAGE_KEY = "ui.panelWidth";
/** Matches `--reports-panel-width` in styles.css. */
export const DEFAULT_PANEL_WIDTH = 360;
export const MIN_PANEL_WIDTH = 360;
export const PANEL_WIDTH_STEP = 16;
/** The panel never takes more than this share of the viewport. */
const MAX_PANEL_SHARE = 0.6;

export const EMPTY_STATE_TEXT = "Отчёты появятся здесь, когда агент вернёт данные";
export const NOT_FOUND_TEXT = "Отчёт не найден";

function maxPanelWidth(): number {
  return Math.max(MIN_PANEL_WIDTH, Math.floor(window.innerWidth * MAX_PANEL_SHARE));
}

function clampWidth(value: number): number {
  return Math.min(maxPanelWidth(), Math.max(MIN_PANEL_WIDTH, Math.round(value)));
}

/** A stale or hand-edited value never breaks the layout: anything unparsable means the default. */
function readStoredWidth(): number {
  try {
    const raw = localStorage.getItem(PANEL_WIDTH_STORAGE_KEY);
    if (raw === null) {
      return DEFAULT_PANEL_WIDTH;
    }
    const parsed = Number(raw);
    return Number.isFinite(parsed) && parsed > 0 ? clampWidth(parsed) : DEFAULT_PANEL_WIDTH;
  } catch {
    return DEFAULT_PANEL_WIDTH;
  }
}

function storeWidth(value: number): void {
  try {
    localStorage.setItem(PANEL_WIDTH_STORAGE_KEY, String(value));
  } catch {
    // Storage may be full or disabled; the width still applies for this session.
  }
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : "Неизвестная ошибка";
}

type ListStatus = "idle" | "loading" | "ready" | "error";

/** The card list, keyed to the chat it was loaded for: another chat never sees it. */
interface ListState {
  chatId: string | null;
  status: ListStatus;
  /** The order of the newest list response; the fields come from the records. */
  cards: ReportCard[];
  /** Issue position of the response `cards` came from (0 before the first). */
  seq: number;
  error: string | null;
}

interface PreviewState {
  chatId: string | null;
  reportId: string;
  /** Issue position of the GET this preview was opened with. */
  issuedSeq: number;
  status: "loading" | "ready" | "error";
  /** The fetched report; only its `data` (and the version it belongs to) is shown from here. */
  report: Report | null;
  error: string | null;
}

/*
 * A gone report - ONE rule for every path: the open preview is closed with the
 * notice `NOT_FOUND_TEXT` (and its fullscreen dialog with it) when the server
 * answers 404 for that report on ANY GET /api/reports/{id} - opening, the
 * version re-fetch, the retry, the reconcile GET - or when a list of THIS chat
 * issued after the preview's own GET does not contain it (an orphaned saved
 * report lives in the Saved tab, never in a chat's list). The report's record
 * is forgotten (optimistic layer and reconcile bookkeeping with it: no further
 * automatic GETs for it; late responses cannot restore it), a highlight on it
 * stays cleared, and after a 404 the list is refreshed so its card goes too.
 * A 404 for a report that is not open only refreshes its chat's list. The notice
 * stays until another report is opened or the chat is switched; it never shows
 * for another chat.
 */

function StarIcon({ filled }: { filled: boolean }) {
  return (
    <svg
      viewBox="0 0 16 16"
      width="16"
      height="16"
      aria-hidden="true"
      focusable="false"
      className="report-star"
    >
      <path
        d="M8 1.6l1.9 4 4.4.6-3.2 3.1.8 4.4L8 11.6l-3.9 2.1.8-4.4L1.7 6.2l4.4-.6z"
        fill={filled ? "currentColor" : "none"}
        stroke="currentColor"
        strokeWidth="1.3"
        strokeLinejoin="round"
      />
    </svg>
  );
}

interface SaveToggleProps {
  card: ReportCard;
  busy: boolean;
  onToggle: (card: ReportCard) => void;
  /** `icon` for cards, `text` for the preview toolbar. */
  variant: "icon" | "text";
}

function SaveToggle({ card, busy, onToggle, variant }: SaveToggleProps) {
  const saved = card.saved_at !== null;
  const label = saved ? "Убрать из сохранённых" : "Сохранить";
  if (variant === "icon") {
    return (
      <button
        type="button"
        className={saved ? "icon-button report-card__save is-saved" : "icon-button report-card__save"}
        aria-pressed={saved}
        aria-label={label}
        title={label}
        disabled={busy}
        onClick={() => onToggle(card)}
      >
        <StarIcon filled={saved} />
      </button>
    );
  }
  return (
    <button
      type="button"
      className={saved ? "button button-secondary report-save is-saved" : "button button-secondary report-save"}
      aria-pressed={saved}
      disabled={busy}
      onClick={() => onToggle(card)}
    >
      <StarIcon filled={saved} />
      <span>{label}</span>
    </button>
  );
}

interface CardProps {
  card: ReportCard;
  highlighted: boolean;
  saving: boolean;
  onOpen: (id: string) => void;
  onToggleSaved: (card: ReportCard) => void;
}

function Card({ card, highlighted, saving, onOpen, onToggleSaved }: CardProps) {
  const ref = useRef<HTMLLIElement>(null);
  const reducedMotion = usePrefersReducedMotion();

  useEffect(() => {
    if (highlighted && typeof ref.current?.scrollIntoView === "function") {
      ref.current.scrollIntoView({ block: "nearest", behavior: reducedMotion ? "auto" : "smooth" });
    }
  }, [highlighted, reducedMotion]);

  return (
    <li ref={ref} className={highlighted ? "report-card is-highlighted" : "report-card"}>
      <button type="button" className="report-card__open" onClick={() => onOpen(card.id)}>
        <span className="report-card__title">{card.title}</span>
        <span className="report-card__meta">
          <span>{formatGeneratedAt(card.generated_at)}</span>
          {card.row_count !== null ? <span>Строк: {String(card.row_count)}</span> : null}
          {card.version > 1 ? <span>Версия {String(card.version)}</span> : null}
        </span>
      </button>
      <SaveToggle card={card} busy={saving} onToggle={onToggleSaved} variant="icon" />
    </li>
  );
}

interface FullscreenProps {
  report: Report;
  saving: boolean;
  onToggleSaved: (card: ReportCard) => void;
  onClose: () => void;
}

function FullscreenPreview({ report, saving, onToggleSaved, onClose }: FullscreenProps) {
  const ref = useRef<HTMLDialogElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const dialog = ref.current;
    if (dialog === null || dialog.open) {
      return;
    }
    if (typeof dialog.showModal === "function") {
      dialog.showModal();
    } else {
      dialog.setAttribute("open", "");
    }
    // Keyboard users land on the way out; Escape works from anywhere inside.
    closeRef.current?.focus();
  }, []);

  const onKeyDown = (event: KeyboardEvent<HTMLDialogElement>) => {
    if (event.key === "Escape") {
      onClose();
    }
  };

  return (
    <dialog
      ref={ref}
      className="reports-fullscreen"
      aria-label={report.title}
      onClose={onClose}
      onKeyDown={onKeyDown}
    >
      <div className="reports-fullscreen__body">
        <div className="reports-preview__toolbar">
          <button
            ref={closeRef}
            type="button"
            className="button button-secondary"
            onClick={onClose}
          >
            Свернуть
          </button>
          <SaveToggle card={report} busy={saving} onToggle={onToggleSaved} variant="text" />
        </div>
        <div className="reports-fullscreen__scroll">
          <ReportPreview report={report} />
        </div>
      </div>
    </dialog>
  );
}

export function ReportsPanel() {
  const {
    chatId,
    openReportId,
    openReport,
    closePreview,
    refresh,
    refreshKey,
    highlightId,
    clearHighlight,
  } = useReports();
  const headingId = useId();

  const [listState, setListState] = useState<ListState>({
    chatId: null,
    status: "idle",
    cards: [],
    seq: 0,
    error: null,
  });
  /** Batched 404s retain their originating chat, even after navigation. */
  const [notFoundReports, setNotFoundReports] = useState<ReadonlyMap<string, string | null>>(
    () => new Map(),
  );
  const [retryNonce, setRetryNonce] = useState(0);
  const [previewState, setPreviewState] = useState<PreviewState | null>(null);
  const [noticeState, setNoticeState] = useState<{ chatId: string | null; text: string } | null>(
    null,
  );
  const [saveError, setSaveError] = useState<string | null>(null);
  const [savingIds, setSavingIds] = useState<ReadonlySet<string>>(() => new Set());
  const [fullscreen, setFullscreen] = useState(false);
  const [previewNonce, setPreviewNonce] = useState(0);

  // Everything shown is keyed to `chatId`: state loaded for another chat is
  // invisible from the very first render after a switch, before any effect runs.
  const list: ListState =
    listState.chatId === chatId
      ? listState
      : { chatId, status: chatId === null ? "ready" : "loading", cards: [], seq: 0, error: null };
  const preview = previewState !== null && previewState.chatId === chatId ? previewState : null;
  const notice = noticeState !== null && noticeState.chatId === chatId ? noticeState.text : null;

  const listTicket = useRef(0);
  const previewTicket = useRef(0);

  /* The one source of per-report fields (see `reportRecords.ts`). `clock` is
     the one monotonic source of positions (request issue, mutation
     confirmation) and of mutation ids. */
  const [records, setRecords] = useState<ReportRecords>(NO_RECORDS);
  const clock = useRef(0);
  /** Issue positions of the observation requests (list, report, reconcile) still in flight. */
  const inFlight = useRef(new Set<number>());

  const reportNotFound = useCallback((id: string, forChat: string | null) => {
    // Invalidate before completing a reconcile: its queued work must not start.
    setRecords((prev) => forgetReport(prev, id));
    setNotFoundReports((prev) => new Map(prev).set(id, forChat));
  }, []);

  /* Card list: refetched on chat change, on every refresh and on retry. */
  useEffect(() => {
    const ticket = ++listTicket.current;
    if (chatId === null) {
      setListState({ chatId, status: "ready", cards: [], seq: 0, error: null });
      return;
    }
    const issuedSeq = ++clock.current;
    setListState((prev) =>
      prev.chatId === chatId
        ? { ...prev, status: "loading", error: null }
        : { chatId, status: "loading", cards: [], seq: 0, error: null },
    );
    inFlight.current.add(issuedSeq);
    void listChatReports(chatId)
      .then(
        (items) => {
          if (ticket !== listTicket.current) {
            return;
          }
          setRecords((prev) => observeAll(prev, items, issuedSeq));
          setListState({ chatId, status: "ready", cards: items, seq: issuedSeq, error: null });
        },
        (error: unknown) => {
          if (ticket !== listTicket.current) {
            return;
          }
          setListState((prev) => ({
            chatId,
            status: "error",
            cards: prev.chatId === chatId ? prev.cards : [],
            seq: prev.chatId === chatId ? prev.seq : 0,
            error: errorText(error),
          }));
        },
      )
      .finally(() => inFlight.current.delete(issuedSeq));
  }, [chatId, refreshKey, retryNonce]);

  /* Fullscreen belongs to the opened report: another report or chat starts inline. */
  useEffect(() => {
    setFullscreen(false);
  }, [openReportId, chatId]);

  /* The not-found notice belongs to the chat it was raised in and does not come back. */
  useEffect(() => {
    setNoticeState(null);
  }, [chatId]);

  /* Preview: loaded whenever a different report is opened (or its data went
     stale, see `previewStale`); a 404 sends the user back. */
  useEffect(() => {
    const ticket = ++previewTicket.current;
    if (openReportId === null) {
      setPreviewState(null);
      return;
    }
    const issuedSeq = ++clock.current;
    inFlight.current.add(issuedSeq);
    setNoticeState(null);
    setPreviewState((prev) => ({
      chatId,
      reportId: openReportId,
      // A re-fetch of the same report keeps its place on the clock.
      issuedSeq:
        prev !== null && prev.chatId === chatId && prev.reportId === openReportId
          ? prev.issuedSeq
          : issuedSeq,
      status: "loading",
      report: null,
      error: null,
    }));
    void getReport(openReportId)
      .then(
        (report) => {
          if (ticket !== previewTicket.current) {
            return;
          }
          setRecords((prev) => observe(prev, report, issuedSeq));
          setPreviewState((prev) =>
            prev === null ? null : { ...prev, status: "ready", report, error: null },
          );
        },
        (error: unknown) => {
          if (error instanceof ApiError && error.status === 404) {
            reportNotFound(openReportId, chatId);
            return;
          }
          if (ticket !== previewTicket.current) {
            return;
          }
          setPreviewState((prev) =>
            prev === null
              ? null
              : { ...prev, status: "error", report: null, error: errorText(error) },
          );
        },
      )
      .finally(() => inFlight.current.delete(issuedSeq));
  }, [openReportId, previewNonce, chatId, reportNotFound]);

  const missingFromList =
    preview !== null &&
    list.status === "ready" &&
    list.seq > preview.issuedSeq &&
    !list.cards.some((item) => item.id === preview.reportId)
      ? preview.reportId
      : null;

  /* Reconcile after an ambiguous confirmation (see `reportRecords.ts`): a report
     GET issued now, folded into the record like any observation - the preview
     keeps its rows unless the version moved. A 404 follows the gone rule; any
     other failure leaves the newest observation. */
  useEffect(() => {
    for (const [id, entry] of records) {
      if (id === missingFromList || !wantsReconcile(entry)) {
        continue;
      }
      const issuedSeq = ++clock.current;
      inFlight.current.add(issuedSeq);
      setRecords((prev) => reconcileIssued(prev, id));
      void getReport(id)
        .then(
          (report) => {
            setRecords((prev) => reconcileCompleted(observe(prev, report, issuedSeq), id));
          },
          (error: unknown) => {
            if (error instanceof ApiError && error.status === 404) {
              reportNotFound(id, entry.content.card.chat_id);
            } else {
              setRecords((prev) => reconcileCompleted(prev, id));
            }
          },
        )
        .finally(() => inFlight.current.delete(issuedSeq));
    }
  }, [records, missingFromList, reportNotFound]);

  /* The gone rule (see above): a 404 for a report, or a list of this chat issued
     after the preview's GET that does not contain the open report. */
  useEffect(() => {
    if (notFoundReports.size === 0 && missingFromList === null) {
      return;
    }
    const gone = new Set(
      [...notFoundReports].filter(([, forChat]) => forChat === chatId).map(([id]) => id),
    );
    if (gone.size > 0) {
      refresh();
    }
    if (notFoundReports.size > 0) {
      setNotFoundReports(new Map());
    }
    if (missingFromList !== null) {
      gone.add(missingFromList);
      setRecords((prev) => forgetReport(prev, missingFromList));
    }
    setSavingIds((prev) => new Set([...prev].filter((id) => !gone.has(id))));
    // refresh resets a dismissed highlight; dismiss it after that reset.
    if (gone.size > 0 && (highlightId === null || gone.has(highlightId))) {
      clearHighlight();
    }
    if (openReportId !== null && gone.has(openReportId)) {
      setNoticeState({ chatId, text: NOT_FOUND_TEXT });
      closePreview();
    }
  }, [missingFromList, notFoundReports, chatId, openReportId, highlightId, clearHighlight, closePreview, refresh]);

  const toggleSaved = useCallback(
    (target: ReportCard) => {
      const { id } = target;
      const wasSaved = target.saved_at !== null;
      const optimistic = wasSaved ? null : new Date().toISOString();
      // The mutation's id is its issue position: a PUT response's card is content of then.
      const mutationId = ++clock.current;
      setSaveError(null);
      setSavingIds((prev) => new Set(prev).add(id));
      setRecords((prev) => beginMutation(prev, target, mutationId, optimistic));
      const request: Promise<ReportCard | null> = wasSaved
        ? unsaveReport(id).then(() => null)
        : saveReport(id);
      void request
        .then((response) => {
          const confirmedSeq = ++clock.current;
          const pendingNewer = [...inFlight.current].some((seq) => seq > mutationId);
          setRecords((prev) =>
            confirmMutation(prev, id, { mutationId, confirmedSeq, response, pendingNewer }),
          );
        })
        .catch((error: unknown) => {
          // Only this mutation's optimistic layer goes; the confirmed facts are what stands.
          setRecords((prev) => failMutation(prev, id, mutationId));
          setSaveError(
            `${wasSaved ? "Не удалось убрать из сохранённых" : "Не удалось сохранить отчёт"}: ${errorText(error)}`,
          );
        })
        .finally(() => {
          setSavingIds((prev) => {
            const next = new Set(prev);
            next.delete(id);
            return next;
          });
        });
    },
    [],
  );

  /* Every surface renders the record; the list only orders, the preview only adds `data`. */
  const cards = list.cards
    .filter((item) => records.get(item.id) !== null)
    .map((item) => effectiveCard(records, item.id) ?? item);
  const previewRecord =
    preview !== null && preview.report !== null
      ? effectiveCard(records, preview.report.id)
      : undefined;
  // The loaded rows belong to one version; newer metadata over old rows is never shown.
  const previewStale =
    preview !== null &&
    preview.report !== null &&
    previewRecord !== undefined &&
    previewRecord.version !== preview.report.version;
  useEffect(() => {
    if (previewStale) {
      setPreviewNonce((n) => n + 1);
    }
  }, [previewStale]);
  const shownReport: Report | null =
    preview === null || preview.report === null || previewStale
      ? null
      : { ...(previewRecord ?? preview.report), data: preview.report.data };

  const onOpenCard = useCallback(
    (id: string) => {
      if (id === highlightId) {
        clearHighlight();
      }
      openReport(id);
    },
    [highlightId, clearHighlight, openReport],
  );

  /* Resizable width: drag handle on the panel's left edge, keyboard on the separator. */
  const [width, setWidth] = useState<number>(readStoredWidth);
  const drag = useRef<{ startX: number; startWidth: number; latest: number } | null>(null);

  const commitWidth = useCallback((next: number) => {
    const clamped = clampWidth(next);
    setWidth(clamped);
    storeWidth(clamped);
  }, []);

  const onHandlePointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) {
      return;
    }
    event.preventDefault();
    drag.current = { startX: event.clientX, startWidth: width, latest: width };
    if (typeof event.currentTarget.setPointerCapture === "function") {
      event.currentTarget.setPointerCapture(event.pointerId);
    }
  };
  const onHandlePointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const state = drag.current;
    if (state === null) {
      return;
    }
    state.latest = clampWidth(state.startWidth + (state.startX - event.clientX));
    setWidth(state.latest);
  };
  const onHandlePointerEnd = (event: PointerEvent<HTMLDivElement>) => {
    const state = drag.current;
    if (state === null) {
      return;
    }
    drag.current = null;
    if (typeof event.currentTarget.releasePointerCapture === "function") {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    commitWidth(state.latest);
  };
  const onHandleKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const steps: Record<string, number> = {
      ArrowLeft: width + PANEL_WIDTH_STEP,
      ArrowRight: width - PANEL_WIDTH_STEP,
      Home: MIN_PANEL_WIDTH,
      End: maxPanelWidth(),
    };
    const next = steps[event.key];
    if (next !== undefined) {
      event.preventDefault();
      commitWidth(next);
    }
  };

  const previewSaving = shownReport !== null && savingIds.has(shownReport.id);
  const previewLoading = preview !== null && (preview.status === "loading" || previewStale);
  const style = { "--reports-panel-current": `${String(width)}px` } as CSSProperties;

  return (
    <aside className="reports-panel" aria-label="Отчёты чата" style={style}>
      <div
        className="reports-panel__handle"
        role="separator"
        aria-orientation="vertical"
        aria-label="Изменить ширину панели отчётов"
        aria-valuemin={MIN_PANEL_WIDTH}
        aria-valuemax={maxPanelWidth()}
        aria-valuenow={width}
        tabIndex={0}
        onPointerDown={onHandlePointerDown}
        onPointerMove={onHandlePointerMove}
        onPointerUp={onHandlePointerEnd}
        onPointerCancel={onHandlePointerEnd}
        onKeyDown={onHandleKeyDown}
      />
      <div className="reports-panel__body">
        <header className="reports-panel__head">
          <h2 id={headingId} className="reports-panel__heading">
            Отчёты чата ({String(cards.length)})
          </h2>
        </header>

        {saveError !== null ? (
          <p role="alert" className="reports-panel__error">
            {saveError}
          </p>
        ) : null}

        {preview === null ? (
          <div className="reports-panel__scroll" aria-busy={list.status === "loading"}>
            {notice !== null ? (
              <p role="status" className="reports-panel__notice">
                {notice}
              </p>
            ) : null}
            {list.status === "error" ? (
              <div role="alert" className="reports-panel__error">
                <span>Не удалось загрузить отчёты: {list.error}</span>
                <button
                  type="button"
                  className="button button-secondary"
                  onClick={() => setRetryNonce((n) => n + 1)}
                >
                  Повторить
                </button>
              </div>
            ) : null}
            {cards.length > 0 ? (
              <ul className="report-cards" aria-labelledby={headingId}>
                {cards.map((item) => (
                  <Card
                    key={item.id}
                    card={item}
                    highlighted={item.id === highlightId}
                    saving={savingIds.has(item.id)}
                    onOpen={onOpenCard}
                    onToggleSaved={toggleSaved}
                  />
                ))}
              </ul>
            ) : list.status === "loading" ? (
              <p className="reports-panel__empty">Загружаю отчёты…</p>
            ) : list.status === "ready" ? (
              <p className="reports-panel__empty">{EMPTY_STATE_TEXT}</p>
            ) : null}
          </div>
        ) : (
          <div className="reports-preview">
            <div className="reports-preview__toolbar">
              <button type="button" className="button button-secondary" onClick={closePreview}>
                К списку
              </button>
              {shownReport !== null ? (
                <>
                  <SaveToggle
                    card={shownReport}
                    busy={previewSaving}
                    onToggle={toggleSaved}
                    variant="text"
                  />
                  <button
                    type="button"
                    className="button button-secondary reports-preview__expand"
                    onClick={() => setFullscreen(true)}
                  >
                    На весь экран
                  </button>
                </>
              ) : null}
            </div>
            <div className="reports-panel__scroll" aria-busy={previewLoading}>
              {previewLoading ? (
                <p className="reports-panel__empty">Загружаю отчёт…</p>
              ) : null}
              {preview.status === "error" ? (
                <div role="alert" className="reports-panel__error">
                  <span>Не удалось загрузить отчёт: {preview.error}</span>
                  <button
                    type="button"
                    className="button button-secondary"
                    onClick={() => setPreviewNonce((n) => n + 1)}
                  >
                    Повторить
                  </button>
                </div>
              ) : null}
              {shownReport !== null && !fullscreen ? <ReportPreview report={shownReport} /> : null}
            </div>
            {shownReport !== null && fullscreen ? (
              <FullscreenPreview
                report={shownReport}
                saving={previewSaving}
                onToggleSaved={toggleSaved}
                onClose={() => setFullscreen(false)}
              />
            ) : null}
          </div>
        )}
      </div>
    </aside>
  );
}
