/**
 * One chat: transcript, composer and the run lifecycle around them.
 *
 * All state lives in the pure reducer of `chatState.ts`; this component only
 * (a) turns route changes, clicks and typing into actions, (b) runs the side
 * effects the state asks for - each `queued` phase is issued exactly once and
 * its outcome dispatched back with the generation it belongs to - and
 * (c) renders. The reducer decides what a late reply still means, so nothing
 * here compares ids or reads refs to guess whether a response is stale.
 *
 * Persistence outside React: the URL (`/chats/:chatId`, `/chats/new`) and the
 * pending list of `pending.ts`, which mirrors `state.pending` so a reload can
 * resubmit the question with its original request id.
 */

import { useCallback, useEffect, useReducer, useRef, useState, type ReactNode } from "react";
import { Link, useNavigate } from "react-router-dom";

import { cancelRun, createChat, getChat, sendMessage } from "../api/client";
import { ApiError } from "../api/types";
import { ReportsProvider } from "../reports/ReportsContext";
import { ChatLayout, ReportsToggle } from "../layout/ChatLayout";
import type { ThinkingPhase } from "../thinking/ThinkingMark";
import { NEW_CHAT_ID } from "./ChatList";
import { Composer } from "./Composer";
import { CONNECTION_RETRY_TEXT, Conversation } from "./Conversation";
import {
  canSend,
  chatReducer,
  detailKnows,
  initialChatState,
  pickResubmit,
  type ErrorInfo,
  type PendingRequest,
} from "./chatState";
import { pendingFor, removePending, upsertPending } from "./pending";
import { useRunPolling } from "./useRunPolling";

export { CONNECTION_RETRY_TEXT };
export const CHAT_NOT_FOUND_TEXT = "Чат не найден";

/** `request_id = crypto.randomUUID().replaceAll("-", "")`: 32 hex chars, the backend's rule. */
function newRequestId(): string {
  return crypto.randomUUID().replaceAll("-", "");
}

function chatPath(chatId: string): string {
  return `/chats/${encodeURIComponent(chatId)}`;
}

/** Only `ApiError` is a state; anything else is a programming error and must surface. */
function toErrorInfo(error: unknown): ErrorInfo {
  if (!(error instanceof ApiError)) {
    throw error;
  }
  return { status: error.status, code: error.code, message: error.message };
}

export interface ChatViewProps {
  /** The `:chatId` route param; `undefined` on `/chats`, `"new"` on `/chats/new`. */
  chatId: string | undefined;
  /** Called when the chats list may have changed (chat created, run finished). */
  onChatsChanged?: () => void;
}

export function ChatView({ chatId, onChatsChanged }: ChatViewProps) {
  const navigate = useNavigate();
  const resolvedId = chatId === undefined || chatId === NEW_CHAT_ID ? null : chatId;

  const [state, dispatch] = useReducer(chatReducer, initialChatState);
  const [retryNonce, setRetryNonce] = useState(0);
  const generation = useRef(0);
  const onChatsChangedRef = useRef(onChatsChanged);
  onChatsChangedRef.current = onChatsChanged;
  const notifyChats = useCallback(() => onChatsChangedRef.current?.(), []);

  /* Route change: a new generation; stale replies of the previous one are ignored by the reducer. */
  useEffect(() => {
    const gen = ++generation.current;
    const id = resolvedId;
    const stored = id === null ? null : (pendingFor(id)[0] ?? null);
    dispatch({ type: "chatSwitched", gen, chatId: id, stored });
    if (id === null) {
      return;
    }
    getChat(id).then(
      (detail) => {
        const entries = pendingFor(id);
        for (const entry of entries) {
          if (detailKnows(detail, entry.request_id)) {
            removePending(entry.request_id); // Already answered or running server-side.
          }
        }
        dispatch({
          type: "loadSucceeded",
          gen,
          detail,
          resubmit: pickResubmit(entries, id, detail),
        });
      },
      (error: unknown) => dispatch({ type: "loadFailed", gen, error: toErrorInfo(error) }),
    );
  }, [resolvedId, retryNonce]);

  /* Storage mirrors the pending request: written when one is accepted, removed when it resolves
     in the same generation (a chat switch leaves the other chat's entry for its own recovery). */
  const seenPending = useRef<{ gen: number; pending: PendingRequest | null }>({
    gen: 0,
    pending: null,
  });
  useEffect(() => {
    const previous = seenPending.current;
    seenPending.current = { gen: state.gen, pending: state.pending };
    if (state.pending !== null) {
      if (
        state.chatId !== null &&
        state.pending.phase !== "recovering" &&
        previous.pending?.request_id !== state.pending.request_id
      ) {
        upsertPending({
          chatId: state.chatId,
          request_id: state.pending.request_id,
          message: state.pending.message,
        });
      }
    } else if (previous.pending !== null && previous.gen === state.gen) {
      removePending(previous.pending.request_id);
    }
  }, [state.pending, state.gen, state.chatId]);

  /* Outbox: a queued request is POSTed exactly once. */
  useEffect(() => {
    const { pending, chatId: id, gen } = state;
    if (pending === null || pending.phase !== "queued" || id === null) {
      return;
    }
    const { request_id, message } = pending;
    dispatch({ type: "postIssued", request_id });
    sendMessage(id, { request_id, message }).then(
      (run) => {
        dispatch({ type: "postSucceeded", gen, request_id, run });
        notifyChats();
      },
      (error: unknown) =>
        dispatch({ type: "postFailed", gen, request_id, error: toErrorInfo(error) }),
    );
  }, [state.pending, state.chatId, state.gen, notifyChats]);

  /* `/chats/new`: the chat row is created first; the entry is stored for it, then the URL is
     replaced and the load of the new chat submits the entry through the recovery path. */
  useEffect(() => {
    const { creating, gen } = state;
    if (creating === null || creating.phase !== "queued") {
      return;
    }
    dispatch({ type: "createIssued", request_id: creating.request_id });
    createChat().then(
      (created) => {
        upsertPending({
          chatId: created.id,
          request_id: creating.request_id,
          message: creating.message,
        });
        notifyChats();
        dispatch({ type: "createSucceeded", gen, chatId: created.id });
      },
      (error: unknown) => dispatch({ type: "createFailed", gen, error: toErrorInfo(error) }),
    );
  }, [state.creating, state.gen, notifyChats]);

  useEffect(() => {
    if (state.navigateTo !== null) {
      navigate(chatPath(state.navigateTo), { replace: true });
    }
  }, [state.navigateTo, navigate]);

  /* Cancel: issued once per click; the reply is reconciled by the reducer. */
  useEffect(() => {
    const { cancel, chatId: id, gen } = state;
    if (cancel === null || cancel.phase !== "queued" || id === null) {
      return;
    }
    const { request_id } = cancel;
    dispatch({ type: "cancelIssued", request_id });
    cancelRun(id, request_id).then(
      (run) => dispatch({ type: "cancelResponse", gen, request_id, run }),
      (error: unknown) =>
        dispatch({ type: "cancelFailed", gen, request_id, error: toErrorInfo(error) }),
    );
  }, [state.cancel, state.chatId, state.gen]);

  /* Transcript refetch: the latest ticket wins; every refetch means the chats list may have changed. */
  useEffect(() => {
    const { refetchWanted, refetchIssued, chatId: id, gen, load } = state;
    if (refetchWanted <= refetchIssued || id === null || load !== "ready") {
      return;
    }
    const seq = refetchWanted;
    dispatch({ type: "refetchIssued", seq });
    notifyChats();
    getChat(id).then(
      (detail) => dispatch({ type: "refetched", gen, seq, detail }),
      (error: unknown) =>
        dispatch({ type: "refetchFailed", gen, seq, error: toErrorInfo(error) }),
    );
  }, [state.refetchWanted, state.refetchIssued, state.chatId, state.gen, state.load, notifyChats]);

  const { gen } = state;
  useRunPolling(state.chatId, state.activeRun !== null && state.load === "ready", {
    onStatus: (status) => {
      dispatch({ type: "pollResult", gen, status });
      return status.active_run !== null;
    },
    onNotFound: () => dispatch({ type: "pollNotFound", gen }),
    onConnection: (lost) => dispatch({ type: "connection", gen, lost }),
  });

  /* Derived view state */
  const { pending, activeRun, cancel, creating, draft, notice } = state;
  const inFlight = pending?.phase === "queued" || pending?.phase === "posting";
  const busy = creating !== null || inFlight || activeRun !== null;
  const stopping = cancel !== null || activeRun?.state === "cancelling";
  const phase: ThinkingPhase = stopping ? "cancelling" : "thinking";
  const awaitingRetry = pending?.phase === "retry";

  let main: ReactNode;
  if (state.load === "not_found") {
    main = (
      <div className="chat-note" role="alert">
        <p className="chat-note__title">{CHAT_NOT_FOUND_TEXT}</p>
        <p className="chat-note__text">Возможно, чат был удалён.</p>
        <Link className="button button-secondary" to="/chats">
          К списку чатов
        </Link>
      </div>
    );
  } else if (state.load === "error") {
    main = (
      <div className="chat-note" role="alert">
        <p className="chat-note__title">{state.loadError}</p>
        <button
          type="button"
          className="button button-secondary"
          onClick={() => setRetryNonce((n) => n + 1)}
        >
          Повторить
        </button>
      </div>
    );
  } else {
    main = (
      <>
        <div className="chat-scroll" aria-busy={state.load === "loading"}>
          <div className="chat-column">
            {state.load === "loading" && pending === null ? (
              <p className="chat-loading">Загрузка…</p>
            ) : (
              <Conversation
                messages={state.messages}
                reports={state.reports}
                optimistic={pending}
                busy={busy}
                phase={phase}
                connectionLost={state.connectionLost}
              />
            )}
          </div>
        </div>
        <div className="chat-composer-bar">
          <div className="chat-column">
            <ReportsToggle count={state.reports.length} />
            {awaitingRetry ? (
              <div className="chat-notice is-retry" role="alert">
                <span>{CONNECTION_RETRY_TEXT}</span>
                <span className="chat-notice__actions">
                  <button
                    type="button"
                    className="button button-secondary"
                    onClick={() => dispatch({ type: "retryRequested" })}
                  >
                    Повторить
                  </button>
                  <button
                    type="button"
                    className="button button-secondary"
                    onClick={() => dispatch({ type: "pendingDiscarded" })}
                  >
                    Отменить отправку
                  </button>
                </span>
              </div>
            ) : null}
            {notice === null ? null : (
              <div className="chat-notice is-error" role="alert">
                <span>{notice.text}</span>
                {notice.refetch ? (
                  <button
                    type="button"
                    className="button button-secondary"
                    onClick={() => dispatch({ type: "refetchRequested" })}
                  >
                    Обновить
                  </button>
                ) : null}
              </div>
            )}
            <Composer
              value={draft}
              onChange={(value) => dispatch({ type: "draftChanged", value })}
              onSend={() =>
                dispatch({ type: "sendRequested", request_id: newRequestId(), message: draft })
              }
              onStop={() => dispatch({ type: "cancelClicked" })}
              stoppable={activeRun !== null}
              canSend={canSend(state) && draft.trim() !== ""}
              stopping={stopping}
            />
          </div>
        </div>
      </>
    );
  }

  return (
    <ReportsProvider
      chatId={state.chatId}
      refreshToken={state.completedRun?.request_id ?? null}
      highlightReportId={state.completedRun?.response?.report?.id ?? null}
    >
      <ChatLayout>{main}</ChatLayout>
    </ReportsProvider>
  );
}

export default ChatView;
