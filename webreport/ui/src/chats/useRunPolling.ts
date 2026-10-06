/**
 * Completion polling for an active run (decision D12): `GET /api/chats/{id}/status`
 * every second, every three seconds after a connection error, until the
 * caller reports the run settled or the chat is gone. No SSE, no sockets.
 *
 * The loop is a `setTimeout` chain, so a slow request never overlaps the
 * next one; the in-flight request is aborted on chat switch or unmount.
 */

import { useEffect, useRef } from "react";

import { getChatStatus } from "../api/client";
import { ApiError } from "../api/types";
import type { ChatStatus } from "../api/types";

export const POLL_INTERVAL_MS = 1000;
export const POLL_BACKOFF_MS = 3000;

export interface RunPollingHandlers {
  /** Every successful poll; return `false` to stop the loop (the run settled). */
  onStatus: (status: ChatStatus) => boolean;
  /** The chat vanished (404): the loop stops. */
  onNotFound: () => void;
  /** Connection lost (`true`) or recovered (`false`). */
  onConnection: (lost: boolean) => void;
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

export function useRunPolling(
  chatId: string | null,
  enabled: boolean,
  handlers: RunPollingHandlers,
): void {
  const handlersRef = useRef(handlers);
  handlersRef.current = handlers;

  useEffect(() => {
    if (!enabled || chatId === null) {
      return;
    }
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | null = null;
    const controller = new AbortController();

    const tick = async () => {
      let delay = POLL_INTERVAL_MS;
      try {
        const status = await getChatStatus(chatId, controller.signal);
        if (stopped) {
          return;
        }
        handlersRef.current.onConnection(false);
        if (!handlersRef.current.onStatus(status)) {
          return;
        }
      } catch (error) {
        if (stopped || isAbort(error)) {
          return;
        }
        if (!(error instanceof ApiError)) {
          throw error;
        }
        if (error.status === 404) {
          handlersRef.current.onNotFound();
          return;
        }
        // A transport failure or a transient server error: keep the run
        // alive on screen and ask again more slowly.
        delay = POLL_BACKOFF_MS;
        if (error.status === 0) {
          handlersRef.current.onConnection(true);
        }
      }
      timer = setTimeout(() => void tick(), delay);
    };

    timer = setTimeout(() => void tick(), POLL_INTERVAL_MS);
    return () => {
      stopped = true;
      if (timer !== null) {
        clearTimeout(timer);
      }
      controller.abort();
    };
  }, [chatId, enabled]);
}
