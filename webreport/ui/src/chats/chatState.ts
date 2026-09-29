/**
 * Pure state machine of one chat view.
 *
 * Every asynchronous result (POST reply, poll tick, cancel reply, transcript
 * refetch, chat load) is reconciled HERE against the current state, never in
 * the closure that started the request: a reply carries the generation it was
 * started in (`gen`, bumped on every chat switch) and the id it is about, and
 * the reducer decides whether it still applies. Two invariants follow:
 *
 *  - a run known to be terminal (settled by a poll, a reply or the transcript)
 *    is never resurrected by a later, older reply;
 *  - at most one request per chat is unresolved (queued, posting, waiting for
 *    a retry or submitted but not yet in the transcript); a new send is
 *    refused until it is resolved or explicitly discarded, so the pending
 *    entry in `sessionStorage` always names the question a reload must retry.
 *
 * Side effects (HTTP, storage, navigation) live in `ChatView` and are driven
 * by the state: `queued` phases are picked up by effects that issue the call
 * exactly once and dispatch its outcome.
 */

import type {
  ChatDetail,
  ChatStatus,
  Message,
  ReportCard,
  Run,
  RunState,
} from "../api/types";
import type { PendingMessage } from "./pending";

export type LoadStatus = "loading" | "ready" | "not_found" | "error";

export type PendingPhase =
  /** Found in storage while the transcript loads; may turn out to be answered. */
  | "recovering"
  /** Accepted by the reducer; the outbox effect will POST it. */
  | "queued"
  /** POST in flight. */
  | "posting"
  /** POST failed at the transport; waits for «Повторить» or a discard. */
  | "retry"
  /** Accepted by the server (202/200); shown until the transcript contains it. */
  | "submitted";

export interface PendingRequest {
  request_id: string;
  message: string;
  phase: PendingPhase;
}

export interface CancelRequest {
  request_id: string;
  phase: "queued" | "requesting";
}

export interface ErrorInfo {
  status: number;
  code: string;
  message: string;
}

export interface Notice {
  text: string;
  /** Offers «Обновить» (a transcript refetch) next to the text. */
  refetch: boolean;
}

export interface ChatViewState {
  gen: number;
  chatId: string | null;
  load: LoadStatus;
  loadError: string | null;
  messages: Message[];
  reports: ReportCard[];
  activeRun: Run | null;
  /** The run that finished during this generation (drives the panel refresh + highlight). */
  completedRun: Run | null;
  pending: PendingRequest | null;
  cancel: CancelRequest | null;
  /** `/chats/new`: the message waiting for its chat row. */
  creating: { request_id: string; message: string; phase: "queued" | "requesting" } | null;
  /** Set once the chat row exists; the view navigates and the switch resets the state. */
  navigateTo: string | null;
  connectionLost: boolean;
  notice: Notice | null;
  draft: string;
  /** Refetch tickets: `wanted` > `issued` means the refetch effect has work; `issued` is the only result accepted. */
  refetchWanted: number;
  refetchIssued: number;
}

export type ChatAction =
  | { type: "chatSwitched"; gen: number; chatId: string | null; stored: PendingMessage | null }
  | { type: "loadSucceeded"; gen: number; detail: ChatDetail; resubmit: PendingMessage | null }
  | { type: "loadFailed"; gen: number; error: ErrorInfo }
  | { type: "draftChanged"; value: string }
  | { type: "sendRequested"; request_id: string; message: string }
  | { type: "createIssued"; request_id: string }
  | { type: "createSucceeded"; gen: number; chatId: string }
  | { type: "createFailed"; gen: number; error: ErrorInfo }
  | { type: "postIssued"; request_id: string }
  | { type: "postSucceeded"; gen: number; request_id: string; run: Run }
  | { type: "postFailed"; gen: number; request_id: string; error: ErrorInfo }
  | { type: "retryRequested" }
  | { type: "pendingDiscarded" }
  | { type: "pollResult"; gen: number; status: ChatStatus }
  | { type: "pollNotFound"; gen: number }
  | { type: "connection"; gen: number; lost: boolean }
  | { type: "cancelClicked" }
  | { type: "cancelIssued"; request_id: string }
  | { type: "cancelResponse"; gen: number; request_id: string; run: Run }
  | { type: "cancelFailed"; gen: number; request_id: string; error: ErrorInfo }
  | { type: "refetchRequested" }
  | { type: "refetchIssued"; seq: number }
  | { type: "refetched"; gen: number; seq: number; detail: ChatDetail }
  | { type: "refetchFailed"; gen: number; seq: number; error: ErrorInfo }
  | { type: "noticeDismissed" };

export const SERVER_UNAVAILABLE_TEXT = "Сервер недоступен";

const TERMINAL_STATES: ReadonlySet<RunState> = new Set([
  "succeeded",
  "failed",
  "cancelled",
  "interrupted",
]);

export const isTerminal = (run: Run): boolean => TERMINAL_STATES.has(run.state);

export const initialChatState: ChatViewState = {
  gen: 0,
  chatId: null,
  load: "loading",
  loadError: null,
  messages: [],
  reports: [],
  activeRun: null,
  completedRun: null,
  pending: null,
  cancel: null,
  creating: null,
  navigateTo: null,
  connectionLost: false,
  notice: null,
  draft: "",
  refetchWanted: 0,
  refetchIssued: 0,
};

/* Pure helpers */

/** The transcript (or the active run) already carries this request. */
export function detailKnows(detail: ChatDetail, requestId: string): boolean {
  return (
    detail.messages.some((item) => item.request_id === requestId) ||
    detail.active_run?.request_id === requestId
  );
}

/** The oldest stored entry of this chat the transcript does not know - the one to resubmit. */
export function pickResubmit(
  stored: PendingMessage[],
  chatId: string,
  detail: ChatDetail,
): PendingMessage | null {
  return (
    stored.find((entry) => entry.chatId === chatId && !detailKnows(detail, entry.request_id)) ??
    null
  );
}

function isKnownTerminal(state: ChatViewState, requestId: string): boolean {
  return (
    state.completedRun?.request_id === requestId ||
    state.messages.some((item) => item.role === "assistant" && item.request_id === requestId)
  );
}

function errorText(error: ErrorInfo): string {
  return error.status === 0 ? SERVER_UNAVAILABLE_TEXT : error.message;
}

function settle(state: ChatViewState, lastRun: Run | null, refetch: boolean): ChatViewState {
  return {
    ...state,
    activeRun: null,
    cancel: null,
    connectionLost: false,
    completedRun: lastRun ?? state.completedRun,
    refetchWanted: refetch ? state.refetchWanted + 1 : state.refetchWanted,
  };
}

/** Transcript applied: pending resolved when present, active run reconciled with the server. */
function applyDetail(state: ChatViewState, detail: ChatDetail): ChatViewState {
  let next: ChatViewState = { ...state, messages: detail.messages, reports: detail.reports };
  if (next.pending !== null && detailKnows(detail, next.pending.request_id)) {
    next = { ...next, pending: null };
  }
  if (detail.active_run !== null) {
    if (!isKnownTerminal(next, detail.active_run.request_id)) {
      next = { ...next, activeRun: detail.active_run };
    }
  } else if (next.activeRun !== null && isKnownTerminal(next, next.activeRun.request_id)) {
    // The server shows the answer of the run we still track: it is over, and the transcript is fresh.
    next = settle(next, detail.last_run, false);
  }
  return next;
}

export function canSend(state: ChatViewState): boolean {
  return (
    state.load === "ready" &&
    state.creating === null &&
    state.pending === null &&
    state.activeRun === null
  );
}

/* Reducer */

export function chatReducer(state: ChatViewState, action: ChatAction): ChatViewState {
  switch (action.type) {
    case "chatSwitched":
      return {
        ...initialChatState,
        gen: action.gen,
        chatId: action.chatId,
        load: action.chatId === null ? "ready" : "loading",
        pending:
          action.stored === null
            ? null
            : { request_id: action.stored.request_id, message: action.stored.message, phase: "recovering" },
      };

    case "loadSucceeded": {
      if (action.gen !== state.gen) {
        return state;
      }
      const loaded = applyDetail({ ...state, load: "ready", pending: null }, action.detail);
      return action.resubmit === null
        ? loaded
        : {
            ...loaded,
            pending: {
              request_id: action.resubmit.request_id,
              message: action.resubmit.message,
              phase: "queued",
            },
          };
    }

    case "loadFailed":
      if (action.gen !== state.gen) {
        return state;
      }
      return action.error.status === 404
        ? { ...state, load: "not_found", pending: null }
        : { ...state, load: "error", loadError: errorText(action.error) };

    case "draftChanged":
      return { ...state, draft: action.value };

    case "sendRequested": {
      if (!canSend(state) || action.message.trim() === "") {
        return state;
      }
      const message = action.message.trim();
      const base = { ...state, draft: "", notice: null };
      if (state.chatId === null) {
        return { ...base, creating: { request_id: action.request_id, message, phase: "queued" } };
      }
      return {
        ...base,
        pending: { request_id: action.request_id, message, phase: "queued" },
      };
    }

    case "createIssued":
      if (state.creating?.request_id !== action.request_id || state.creating.phase !== "queued") {
        return state;
      }
      return { ...state, creating: { ...state.creating, phase: "requesting" } };

    case "createSucceeded":
      if (action.gen !== state.gen || state.creating === null) {
        return state;
      }
      return { ...state, navigateTo: action.chatId };

    case "createFailed":
      if (action.gen !== state.gen || state.creating === null) {
        return state;
      }
      return {
        ...state,
        creating: null,
        draft: state.draft.trim() === "" ? state.creating.message : state.draft,
        notice: { text: errorText(action.error), refetch: false },
      };

    case "postIssued":
      if (state.pending?.request_id !== action.request_id || state.pending.phase !== "queued") {
        return state;
      }
      return { ...state, pending: { ...state.pending, phase: "posting" } };

    case "postSucceeded": {
      if (action.gen !== state.gen) {
        return state;
      }
      let next = state;
      if (next.pending?.request_id === action.request_id) {
        next = { ...next, pending: { ...next.pending, phase: "submitted" }, notice: null };
      }
      if (isKnownTerminal(next, action.run.request_id)) {
        return next; // Settled meanwhile by a poll or the transcript.
      }
      return isTerminal(action.run)
        ? settle(next, action.run, true)
        : { ...next, activeRun: action.run };
    }

    case "postFailed": {
      if (action.gen !== state.gen || state.pending?.request_id !== action.request_id) {
        return state;
      }
      if (action.error.status === 0) {
        return { ...state, pending: { ...state.pending, phase: "retry" } };
      }
      if (action.error.status === 404) {
        return { ...state, pending: null, load: "not_found" };
      }
      return {
        ...state,
        pending: null,
        draft: state.draft.trim() === "" ? state.pending.message : state.draft,
        notice: { text: action.error.message, refetch: false },
        // Another run holds the chat: pick it up so the stop button and the mark appear.
        refetchWanted:
          action.error.code === "chat_busy" ? state.refetchWanted + 1 : state.refetchWanted,
      };
    }

    case "retryRequested":
      if (state.pending?.phase !== "retry") {
        return state;
      }
      return { ...state, pending: { ...state.pending, phase: "queued" } };

    case "pendingDiscarded":
      if (state.pending?.phase !== "retry") {
        return state;
      }
      return {
        ...state,
        pending: null,
        draft: state.draft.trim() === "" ? state.pending.message : state.draft,
      };

    case "pollResult": {
      if (action.gen !== state.gen) {
        return state;
      }
      const active = action.status.active_run;
      if (active !== null) {
        return isKnownTerminal(state, active.request_id) ? state : { ...state, activeRun: active };
      }
      return state.activeRun === null ? state : settle(state, action.status.last_run, true);
    }

    case "pollNotFound":
      if (action.gen !== state.gen) {
        return state;
      }
      return { ...state, activeRun: null, cancel: null, load: "not_found" };

    case "connection":
      if (action.gen !== state.gen || state.connectionLost === action.lost) {
        return state;
      }
      return { ...state, connectionLost: action.lost };

    case "cancelClicked":
      if (state.activeRun === null || state.cancel !== null) {
        return state;
      }
      return { ...state, cancel: { request_id: state.activeRun.request_id, phase: "queued" } };

    case "cancelIssued":
      if (state.cancel?.request_id !== action.request_id || state.cancel.phase !== "queued") {
        return state;
      }
      return { ...state, cancel: { ...state.cancel, phase: "requesting" } };

    case "cancelResponse": {
      if (action.gen !== state.gen) {
        return state;
      }
      const next =
        state.cancel?.request_id === action.request_id ? { ...state, cancel: null } : state;
      // A cancel reply only updates the run it was issued for while that run is
      // still the active one; a run settled meanwhile is never resurrected.
      if (next.activeRun?.request_id !== action.run.request_id) {
        return next;
      }
      return isTerminal(action.run) ? settle(next, action.run, true) : { ...next, activeRun: action.run };
    }

    case "cancelFailed": {
      if (action.gen !== state.gen || state.cancel?.request_id !== action.request_id) {
        return state;
      }
      const next = { ...state, cancel: null };
      if (action.error.status === 404) {
        return { ...next, refetchWanted: next.refetchWanted + 1 }; // Already over, or the chat is gone.
      }
      return { ...next, notice: { text: errorText(action.error), refetch: false } };
    }

    case "refetchRequested":
      return { ...state, refetchWanted: state.refetchWanted + 1 };

    case "refetchIssued":
      return action.seq > state.refetchIssued ? { ...state, refetchIssued: action.seq } : state;

    case "refetched":
      if (action.gen !== state.gen || action.seq !== state.refetchIssued) {
        return state;
      }
      // A fresh transcript retires a «refetch failed» notice; other messages stay until the next send.
      return applyDetail(
        { ...state, notice: state.notice?.refetch === true ? null : state.notice },
        action.detail,
      );

    case "refetchFailed":
      if (action.gen !== state.gen || action.seq !== state.refetchIssued) {
        return state;
      }
      if (action.error.status === 404) {
        return { ...state, activeRun: null, cancel: null, load: "not_found" };
      }
      return { ...state, notice: { text: errorText(action.error), refetch: true } };

    case "noticeDismissed":
      return { ...state, notice: null };
  }
}
