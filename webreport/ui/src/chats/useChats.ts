/**
 * State for the chats sidebar: the first page of `GET /api/chats`, a debounced
 * search query, keyset pagination through «Показать ещё», rename and delete.
 *
 * Every list request carries a ticket; a response whose ticket is no longer the
 * latest is dropped, so a slow earlier search can never overwrite a newer one.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { deleteChat, listChats, renameChat } from "../api/client";
import { ApiError } from "../api/types";
import type { Chat, ListChatsParams } from "../api/types";

export const PAGE_SIZE = 50;
export const SEARCH_DEBOUNCE_MS = 300;
export const SIDEBAR_STORAGE_KEY = "ui.sidebarOpen";

export type ListStatus = "loading" | "ready" | "error";

interface ListRequest {
  q: string;
  cursor: string | null;
}

export interface ChatsState {
  items: Chat[];
  nextCursor: string | null;
  /** Status of the whole list; a failed «Показать ещё» keeps `ready` and sets `error`. */
  status: ListStatus;
  loadingMore: boolean;
  error: ApiError | null;
  /** The raw search input. */
  query: string;
  /** The debounced query the current `items` answer. */
  activeQuery: string;
}

export interface ChatsActions {
  setQuery: (query: string) => void;
  loadMore: () => void;
  /** Re-issues the request that failed last (or the first page). */
  retry: () => void;
  reload: () => void;
  rename: (chatId: string, title: string) => Promise<Chat>;
  remove: (chatId: string) => Promise<void>;
}

export type UseChats = ChatsState & ChatsActions;

/** Trims and collapses whitespace runs to one space (the backend does the same for titles). */
export function collapseWhitespace(text: string): string {
  return text.replace(/\s+/g, " ").trim();
}

export function useChats(): UseChats {
  const [query, setQuery] = useState("");
  const [activeQuery, setActiveQuery] = useState("");
  const [items, setItems] = useState<Chat[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [status, setStatus] = useState<ListStatus>("loading");
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState<ApiError | null>(null);

  const ticket = useRef(0);
  const lastRequest = useRef<ListRequest>({ q: "", cursor: null });

  const fetchPage = useCallback(async (request: ListRequest) => {
    const mine = ++ticket.current;
    lastRequest.current = request;
    setError(null);
    if (request.cursor === null) {
      setStatus("loading");
    } else {
      setLoadingMore(true);
    }

    const params: ListChatsParams = { limit: PAGE_SIZE };
    if (request.q !== "") {
      params.q = request.q;
    }
    if (request.cursor !== null) {
      params.cursor = request.cursor;
    }

    try {
      const page = await listChats(params);
      if (mine !== ticket.current) {
        return;
      }
      setItems((previous) =>
        request.cursor === null ? page.items : [...previous, ...page.items],
      );
      setNextCursor(page.next_cursor);
      setStatus("ready");
    } catch (caught) {
      if (mine !== ticket.current) {
        return;
      }
      if (!(caught instanceof ApiError)) {
        throw caught;
      }
      setError(caught);
      if (request.cursor === null) {
        setStatus("error");
      }
    } finally {
      if (mine === ticket.current) {
        setLoadingMore(false);
      }
    }
  }, []);

  useEffect(() => {
    const handle = setTimeout(() => {
      // The server matches the exact substring against stored text that keeps
      // its original whitespace, so the query goes out verbatim; only an
      // entirely blank input means "no query".
      setActiveQuery(query.trim() === "" ? "" : query);
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(handle);
  }, [query]);

  useEffect(() => {
    void fetchPage({ q: activeQuery, cursor: null });
  }, [activeQuery, fetchPage]);

  const loadMore = useCallback(() => {
    if (nextCursor === null || loadingMore) {
      return;
    }
    void fetchPage({ q: activeQuery, cursor: nextCursor });
  }, [activeQuery, fetchPage, loadingMore, nextCursor]);

  const retry = useCallback(() => {
    void fetchPage(lastRequest.current);
  }, [fetchPage]);

  const reload = useCallback(() => {
    void fetchPage({ q: activeQuery, cursor: null });
  }, [activeQuery, fetchPage]);

  const rename = useCallback(async (chatId: string, title: string) => {
    const updated = await renameChat(chatId, title);
    setItems((previous) =>
      previous.map((item) => (item.id === updated.id ? updated : item)),
    );
    return updated;
  }, []);

  const remove = useCallback(async (chatId: string) => {
    await deleteChat(chatId);
    setItems((previous) => previous.filter((item) => item.id !== chatId));
  }, []);

  return {
    items,
    nextCursor,
    status,
    loadingMore,
    error,
    query,
    activeQuery,
    setQuery,
    loadMore,
    retry,
    reload,
    rename,
    remove,
  };
}

/* Sidebar collapsed state - the only thing this UI persists in localStorage. */

function readSidebarOpen(): boolean {
  try {
    // Anything but an explicit "false" (including stale or malformed values) means open.
    return localStorage.getItem(SIDEBAR_STORAGE_KEY) !== "false";
  } catch {
    return true;
  }
}

function writeSidebarOpen(open: boolean): void {
  try {
    localStorage.setItem(SIDEBAR_STORAGE_KEY, open ? "true" : "false");
  } catch {
    // Storage may be unavailable (private mode, quota); the in-memory state still applies.
  }
}

export function useSidebarOpen(): [boolean, (open: boolean) => void] {
  const [open, setOpenState] = useState(readSidebarOpen);
  const setOpen = useCallback((next: boolean) => {
    setOpenState(next);
    writeSidebarOpen(next);
  }, []);
  return [open, setOpen];
}
