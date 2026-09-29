/**
 * Chats sidebar: searchable list of chats with «Новый чат», inline rename,
 * confirmed delete and URL-driven selection.
 *
 * «Новый чат» only navigates to `/chats/new`; the server row is created lazily
 * by the conversation on the first send, so repeated clicks never leave empty
 * chats behind. `/chats` without an id opens the most recent chat.
 */

import {
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent,
} from "react";
import { NavLink, useNavigate } from "react-router-dom";

import { ApiError } from "../api/types";
import type { Chat } from "../api/types";
import { collapseWhitespace, useChats, useSidebarOpen } from "./useChats";

export const NEW_CHAT_ID = "new";
export const NEW_CHAT_PATH = `/chats/${NEW_CHAT_ID}`;

const SERVER_UNAVAILABLE = "Сервер недоступен";
const CHAT_BUSY_MESSAGE = "Дождитесь завершения ответа";

const chatPath = (chatId: string) => `/chats/${encodeURIComponent(chatId)}`;

/* Relative time */

const relativeFormat = new Intl.RelativeTimeFormat("ru", {
  numeric: "always",
  style: "short",
});
const dayMonthFormat = new Intl.DateTimeFormat("ru-RU", {
  day: "numeric",
  month: "short",
});
const dayMonthYearFormat = new Intl.DateTimeFormat("ru-RU", {
  day: "numeric",
  month: "short",
  year: "numeric",
});

const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

export function formatRelativeTime(iso: string, now: number): string {
  const then = Date.parse(iso);
  if (Number.isNaN(then)) {
    return "";
  }
  const elapsed = Math.max(0, now - then);
  if (elapsed < MINUTE) {
    return "только что";
  }
  if (elapsed < HOUR) {
    return relativeFormat.format(-Math.floor(elapsed / MINUTE), "minute");
  }
  if (elapsed < DAY) {
    return relativeFormat.format(-Math.floor(elapsed / HOUR), "hour");
  }
  if (elapsed < 7 * DAY) {
    return relativeFormat.format(-Math.floor(elapsed / DAY), "day");
  }
  const date = new Date(then);
  const sameYear = date.getFullYear() === new Date(now).getFullYear();
  return (sameYear ? dayMonthFormat : dayMonthYearFormat).format(date);
}

function describeError(error: ApiError): string {
  if (error.status === 0) {
    return SERVER_UNAVAILABLE;
  }
  if (error.code === "chat_busy") {
    return CHAT_BUSY_MESSAGE;
  }
  return error.message;
}

/* Icons (currentColor, decorative) */

function KebabIcon() {
  return (
    <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" focusable="false">
      <circle cx="8" cy="3" r="1.5" fill="currentColor" />
      <circle cx="8" cy="8" r="1.5" fill="currentColor" />
      <circle cx="8" cy="13" r="1.5" fill="currentColor" />
    </svg>
  );
}

function PanelIcon({ open }: { open: boolean }) {
  return (
    <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" focusable="false">
      <rect
        x="1.5"
        y="2.5"
        width="13"
        height="11"
        rx="1.5"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.4"
      />
      <line x1="6" y1="2.5" x2="6" y2="13.5" stroke="currentColor" strokeWidth="1.4" />
      {open ? null : (
        <rect x="1.5" y="2.5" width="4.5" height="11" rx="1.5" fill="currentColor" />
      )}
    </svg>
  );
}

function PlusIcon() {
  return (
    <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true" focusable="false">
      <path d="M8 2.5v11M2.5 8h11" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
    </svg>
  );
}

/* Row menu */

interface RowMenuProps {
  chat: Chat;
  onRename: () => void;
  onDelete: () => void;
  onClose: () => void;
}

function RowMenu({ chat, onRename, onDelete, onClose }: RowMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    menuRef.current?.querySelector<HTMLButtonElement>("[role=menuitem]")?.focus();
    const onPointerDown = (event: PointerEvent) => {
      if (!menuRef.current?.parentElement?.contains(event.target as Node)) {
        onClose();
      }
    };
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, [onClose]);

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") {
      event.stopPropagation();
      onClose();
      return;
    }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const buttons = Array.from(
        menuRef.current?.querySelectorAll<HTMLButtonElement>("[role=menuitem]") ?? [],
      );
      const index = buttons.findIndex((button) => button === document.activeElement);
      const step = event.key === "ArrowDown" ? 1 : -1;
      buttons[(index + step + buttons.length) % buttons.length]?.focus();
    }
  };

  return (
    <div
      ref={menuRef}
      className="chat-row-menu"
      role="menu"
      aria-label={`Действия с чатом «${chat.title}»`}
      onKeyDown={onKeyDown}
    >
      <button type="button" role="menuitem" className="chat-row-menu-item" onClick={onRename}>
        Переименовать
      </button>
      <button
        type="button"
        role="menuitem"
        className="chat-row-menu-item is-danger"
        onClick={onDelete}
      >
        Удалить
      </button>
    </div>
  );
}

/* Delete confirmation */

interface ConfirmDeleteProps {
  chat: Chat;
  busy: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}

function ConfirmDelete({ chat, busy, onConfirm, onCancel }: ConfirmDeleteProps) {
  const titleId = useId();
  const textId = useId();
  const cancelRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    cancelRef.current?.focus();
  }, []);

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape" && !busy) {
      event.stopPropagation();
      onCancel();
    }
  };

  return (
    <div className="chat-dialog-backdrop" onKeyDown={onKeyDown}>
      <div
        className="chat-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={textId}
      >
        <h3 id={titleId} className="chat-dialog-title">
          Удалить чат «{chat.title}»?
        </h3>
        <p id={textId} className="chat-dialog-text">
          Сообщения и несохранённые отчёты будут удалены. Сохранённые отчёты
          останутся во вкладке «Сохранённые отчёты».
        </p>
        <div className="chat-dialog-actions">
          <button
            ref={cancelRef}
            type="button"
            className="button button-secondary"
            onClick={onCancel}
            disabled={busy}
          >
            Отмена
          </button>
          <button
            type="button"
            className="button button-danger"
            onClick={onConfirm}
            disabled={busy}
          >
            Удалить
          </button>
        </div>
      </div>
    </div>
  );
}

/* Row */

interface ChatRowProps {
  chat: Chat;
  now: number;
  menuOpen: boolean;
  editing: boolean;
  onToggleMenu: () => void;
  onCloseMenu: () => void;
  onStartRename: () => void;
  onCommitRename: (value: string) => void;
  onCancelRename: () => void;
  onAskDelete: () => void;
}

function ChatRow({
  chat,
  now,
  menuOpen,
  editing,
  onToggleMenu,
  onCloseMenu,
  onStartRename,
  onCommitRename,
  onCancelRename,
  onAskDelete,
}: ChatRowProps) {
  const [draft, setDraft] = useState(chat.title);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (editing) {
      setDraft(chat.title);
      inputRef.current?.focus();
      inputRef.current?.select();
    }
  }, [editing, chat.title]);

  const onInputKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter") {
      event.preventDefault();
      onCommitRename(draft);
    } else if (event.key === "Escape") {
      event.preventDefault();
      onCancelRename();
    }
  };

  return (
    <li className={`chat-row${menuOpen ? " has-menu" : ""}`}>
      {editing ? (
        <div className="chat-row-edit">
          <input
            ref={inputRef}
            className="chat-row-input"
            type="text"
            aria-label="Новое название чата"
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            onKeyDown={onInputKeyDown}
            onBlur={() => onCommitRename(draft)}
          />
        </div>
      ) : (
        <NavLink className="chat-row-link" to={chatPath(chat.id)} title={chat.title}>
          <span className="chat-row-title">{chat.title}</span>
          <span className="chat-row-meta">
            <span className="chat-row-time">
              {chat.last_message_at === null
                ? "Нет сообщений"
                : formatRelativeTime(chat.last_message_at, now)}
            </span>
            {chat.report_count > 0 ? (
              <span className="chat-row-badge" aria-label={`Отчётов: ${chat.report_count}`}>
                {chat.report_count}
              </span>
            ) : null}
          </span>
        </NavLink>
      )}
      {editing ? null : (
        <div className="chat-row-actions">
          <button
            type="button"
            className="icon-button chat-row-kebab"
            aria-label={`Действия с чатом «${chat.title}»`}
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            onClick={onToggleMenu}
          >
            <KebabIcon />
          </button>
          {menuOpen ? (
            <RowMenu
              chat={chat}
              onRename={onStartRename}
              onDelete={onAskDelete}
              onClose={onCloseMenu}
            />
          ) : null}
        </div>
      )}
    </li>
  );
}

/* Sidebar */

export interface ChatListProps {
  /** The `:chatId` route param; `undefined` on `/chats`, `"new"` on `/chats/new`. */
  selectedChatId: string | undefined;
  /** Any change of this value (after mount) reloads the list, e.g. after a run finished. */
  refreshKey?: number;
}

export function ChatList({ selectedChatId, refreshKey }: ChatListProps) {
  const navigate = useNavigate();
  const chats = useChats();
  const [open, setOpen] = useSidebarOpen();
  const [menuFor, setMenuFor] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const editingRef = useRef<string | null>(null);
  const [confirming, setConfirming] = useState<Chat | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const now = Date.now();

  const { items, status, activeQuery, reload } = chats;

  const seenRefreshKey = useRef(refreshKey);
  useEffect(() => {
    if (refreshKey !== seenRefreshKey.current) {
      seenRefreshKey.current = refreshKey;
      reload();
    }
  }, [refreshKey, reload]);

  // `/chats` without an id opens the most recent chat, or the empty new-chat
  // route when none exists. A search in progress shows its results instead.
  useEffect(() => {
    if (selectedChatId !== undefined || status !== "ready" || activeQuery !== "") {
      return;
    }
    const first = items[0];
    navigate(first === undefined ? NEW_CHAT_PATH : chatPath(first.id), { replace: true });
  }, [selectedChatId, status, activeQuery, items, navigate]);

  const closeMenu = useCallback(() => setMenuFor(null), []);

  const startRename = (chat: Chat) => {
    setMenuFor(null);
    setActionError(null);
    editingRef.current = chat.id;
    setEditingId(chat.id);
  };

  const cancelRename = () => {
    editingRef.current = null;
    setEditingId(null);
  };

  const commitRename = async (chat: Chat, value: string) => {
    if (editingRef.current !== chat.id) {
      return; // Already committed or cancelled (Enter followed by blur).
    }
    editingRef.current = null;
    setEditingId(null);
    const title = collapseWhitespace(value);
    if (title === "" || title === chat.title) {
      return;
    }
    try {
      await chats.rename(chat.id, title);
    } catch (caught) {
      if (!(caught instanceof ApiError)) {
        throw caught;
      }
      setActionError(describeError(caught));
    }
  };

  const askDelete = (chat: Chat) => {
    setMenuFor(null);
    setActionError(null);
    setConfirming(chat);
  };

  const confirmDelete = async () => {
    if (confirming === null) {
      return;
    }
    const target = confirming;
    setDeleting(true);
    try {
      await chats.remove(target.id);
      setConfirming(null);
      if (target.id === selectedChatId) {
        const index = items.findIndex((item) => item.id === target.id);
        const neighbour = items[index + 1] ?? items[index - 1];
        navigate(neighbour === undefined ? NEW_CHAT_PATH : chatPath(neighbour.id), {
          replace: true,
        });
      }
    } catch (caught) {
      if (!(caught instanceof ApiError)) {
        throw caught;
      }
      setConfirming(null);
      setActionError(describeError(caught));
    } finally {
      setDeleting(false);
    }
  };

  if (!open) {
    return (
      <nav className="chat-sidebar is-collapsed" aria-label="Чаты">
        <button
          type="button"
          className="icon-button"
          aria-label="Показать список чатов"
          aria-expanded={false}
          onClick={() => setOpen(true)}
        >
          <PanelIcon open={false} />
        </button>
        <button
          type="button"
          className="icon-button"
          aria-label="Новый чат"
          onClick={() => navigate(NEW_CHAT_PATH)}
        >
          <PlusIcon />
        </button>
      </nav>
    );
  }

  const listError = chats.error === null ? null : describeError(chats.error);
  const showEmpty = status === "ready" && items.length === 0;

  return (
    <nav className="chat-sidebar" aria-label="Чаты">
      <div className="chat-sidebar-head">
        <h2 className="chat-sidebar-heading">
          Чаты
        </h2>
        <button
          type="button"
          className="icon-button"
          aria-label="Скрыть список чатов"
          aria-expanded={true}
          onClick={() => setOpen(false)}
        >
          <PanelIcon open={true} />
        </button>
      </div>

      <div className="chat-sidebar-tools">
        <button
          type="button"
          className="button button-primary chat-new-button"
          onClick={() => navigate(NEW_CHAT_PATH)}
        >
          <PlusIcon />
          Новый чат
        </button>
        <input
          className="chat-search"
          type="search"
          aria-label="Поиск чатов"
          placeholder="Поиск по чатам"
          autoComplete="off"
          value={chats.query}
          onChange={(event) => chats.setQuery(event.target.value)}
        />
      </div>

      <div className="chat-sidebar-body" aria-busy={status === "loading"}>
        {status === "loading" && items.length === 0 ? (
          <p className="chat-sidebar-note">Загрузка…</p>
        ) : null}
        {showEmpty ? (
          <p className="chat-sidebar-note">
            {activeQuery === "" ? "Чатов пока нет" : "Ничего не найдено"}
          </p>
        ) : null}
        {items.length > 0 ? (
          <ul className="chat-list">
            {items.map((chat) => (
              <ChatRow
                key={chat.id}
                chat={chat}
                now={now}
                menuOpen={menuFor === chat.id}
                editing={editingId === chat.id}
                onToggleMenu={() => setMenuFor(menuFor === chat.id ? null : chat.id)}
                onCloseMenu={closeMenu}
                onStartRename={() => startRename(chat)}
                onCommitRename={(value) => void commitRename(chat, value)}
                onCancelRename={cancelRename}
                onAskDelete={() => askDelete(chat)}
              />
            ))}
          </ul>
        ) : null}
        {chats.nextCursor !== null && status === "ready" ? (
          <button
            type="button"
            className="button button-secondary chat-more-button"
            onClick={chats.loadMore}
            disabled={chats.loadingMore}
          >
            {chats.loadingMore ? "Загрузка…" : "Показать ещё"}
          </button>
        ) : null}
        {listError !== null ? (
          <div className="chat-sidebar-error" role="alert">
            <p>{listError}</p>
            <button type="button" className="button button-secondary" onClick={chats.retry}>
              Повторить
            </button>
          </div>
        ) : null}
        {actionError !== null ? (
          <p className="chat-sidebar-error" role="alert">
            {actionError}
          </p>
        ) : null}
      </div>

      {confirming === null ? null : (
        <ConfirmDelete
          chat={confirming}
          busy={deleting}
          onConfirm={() => void confirmDelete()}
          onCancel={() => setConfirming(null)}
        />
      )}
    </nav>
  );
}
