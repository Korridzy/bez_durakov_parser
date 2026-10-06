/**
 * The messages the browser may still owe the server, one entry per request.
 *
 * A send stores `{chatId, request_id, message}` here before the POST and the
 * entry is removed once the run is known to the transcript (or the send was
 * rejected with a definitive error). After a reload the conversation of that
 * chat finds the entry and resubmits it with the SAME request id, which the
 * backend treats as idempotent (same id + same message -> the existing run).
 *
 * Entries of other chats are never touched by a chat that does not own them.
 */

export const PENDING_STORAGE_KEY = "ui.pending";

export interface PendingMessage {
  chatId: string;
  request_id: string;
  message: string;
}

/** The backend's `request_id` rule; anything else would only earn a 422 on resubmit. */
const REQUEST_ID = /^[0-9a-f]{32}$/;

function isPending(value: unknown): value is PendingMessage {
  if (typeof value !== "object" || value === null) {
    return false;
  }
  const record = value as Record<string, unknown>;
  return (
    typeof record.chatId === "string" &&
    typeof record.request_id === "string" &&
    REQUEST_ID.test(record.request_id) &&
    typeof record.message === "string"
  );
}

function write(entries: PendingMessage[]): void {
  try {
    if (entries.length === 0) {
      sessionStorage.removeItem(PENDING_STORAGE_KEY);
    } else {
      sessionStorage.setItem(PENDING_STORAGE_KEY, JSON.stringify(entries));
    }
  } catch {
    // Storage may be unavailable; the send still goes out, only reload recovery is lost.
  }
}

/** Every stored entry, oldest first; a corrupt value is discarded, malformed items are dropped. */
export function readPendingList(): PendingMessage[] {
  let raw: string | null;
  try {
    raw = sessionStorage.getItem(PENDING_STORAGE_KEY);
  } catch {
    return [];
  }
  if (raw === null) {
    return [];
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch {
    write([]);
    return [];
  }
  const items: unknown[] = Array.isArray(parsed) ? parsed : [parsed];
  const valid = items.filter(isPending);
  if (valid.length !== items.length) {
    write(valid);
  }
  return valid;
}

export function pendingFor(chatId: string): PendingMessage[] {
  return readPendingList().filter((entry) => entry.chatId === chatId);
}

/** Adds the entry, or replaces the one with the same request id. */
export function upsertPending(entry: PendingMessage): void {
  const rest = readPendingList().filter((item) => item.request_id !== entry.request_id);
  write([...rest, entry]);
}

export function removePending(requestId: string): void {
  const list = readPendingList();
  const rest = list.filter((item) => item.request_id !== requestId);
  if (rest.length !== list.length) {
    write(rest);
  }
}
