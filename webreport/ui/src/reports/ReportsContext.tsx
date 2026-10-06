/**
 * Shared state between the conversation and the reports panel of one chat.
 *
 * The conversation (todo 13) wraps itself and the panel in `ReportsProvider`:
 *
 *   <ReportsProvider chatId={chatId} refreshToken={lastRun?.request_id}
 *                    highlightReportId={lastRun?.response?.report?.id ?? null}>
 *     <ChatView />      // message chips call useReports().openReport(id)
 *     <ReportsPanel />  // renders the cards and the preview
 *   </ReportsProvider>
 *
 * Every change of `refreshToken` reloads the card list; `refresh(id)` does the
 * same imperatively. A chat switch resets the open preview and any pending
 * highlight, so the panel always lands on the new chat's list.
 */

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";

export interface ReportsContextValue {
  /** The chat whose reports the panel shows; `null` for `/chats/new`. */
  chatId: string | null;
  /** The report open in the panel's preview, or `null` while the list shows. */
  openReportId: string | null;
  /** Opens the preview of one report (used by the message chips). */
  openReport: (reportId: string) => void;
  /** Back to the card list. */
  closePreview: () => void;
  /** Reloads the card list; `highlightId` marks the card of a just-finished run. */
  refresh: (highlightId?: string | null) => void;
  /** Bumps on every `refresh()` / `refreshToken` change; the panel refetches on it. */
  refreshKey: string;
  /** Card to highlight after the next load, or `null`. */
  highlightId: string | null;
  /** Clears the highlight (the panel calls it once the card was opened). */
  clearHighlight: () => void;
}

const ReportsContext = createContext<ReportsContextValue | null>(null);

export interface ReportsProviderProps {
  chatId: string | null;
  /** Any value whose change means "the list may have changed" (e.g. the last run id). */
  refreshToken?: string | number | null;
  /** The card to highlight after the `refreshToken` change (e.g. the run's report id). */
  highlightReportId?: string | null;
  children: ReactNode;
}

interface OpenState {
  forChat: string | null;
  reportId: string;
}

interface RefreshState {
  nonce: number;
  highlightId: string | null;
}

export function ReportsProvider({
  chatId,
  refreshToken = null,
  highlightReportId = null,
  children,
}: ReportsProviderProps) {
  const [open, setOpen] = useState<OpenState | null>(null);
  const [manual, setManual] = useState<RefreshState>({ nonce: 0, highlightId: null });
  const [dismissedHighlight, setDismissedHighlight] = useState<string | null>(null);
  const [seenChat, setSeenChat] = useState<string | null>(chatId);

  // Adjust state during render on a chat switch (React's sanctioned pattern):
  // no frame ever shows the previous chat's preview or highlight.
  if (seenChat !== chatId) {
    setSeenChat(chatId);
    setOpen(null);
    setManual((prev) => ({ nonce: prev.nonce, highlightId: null }));
    setDismissedHighlight(null);
  }

  const openReport = useCallback(
    (reportId: string) => setOpen({ forChat: chatId, reportId }),
    [chatId],
  );
  const closePreview = useCallback(() => setOpen(null), []);
  const refresh = useCallback((highlightId: string | null = null) => {
    setManual((prev) => ({ nonce: prev.nonce + 1, highlightId }));
    setDismissedHighlight(null);
  }, []);

  // The preview is keyed to the chat it was opened for: a chat switch lands on the list.
  const openReportId = open !== null && open.forChat === chatId ? open.reportId : null;
  const wanted = manual.highlightId ?? highlightReportId;
  const highlightId = wanted !== null && wanted !== dismissedHighlight ? wanted : null;
  const clearHighlight = useCallback(() => {
    if (wanted !== null) {
      setDismissedHighlight(wanted);
    }
  }, [wanted]);

  const value = useMemo<ReportsContextValue>(
    () => ({
      chatId,
      openReportId,
      openReport,
      closePreview,
      refresh,
      refreshKey: `${String(refreshToken ?? "")}|${String(manual.nonce)}`,
      highlightId,
      clearHighlight,
    }),
    [
      chatId,
      openReportId,
      openReport,
      closePreview,
      refresh,
      refreshToken,
      manual.nonce,
      highlightId,
      clearHighlight,
    ],
  );

  return <ReportsContext.Provider value={value}>{children}</ReportsContext.Provider>;
}

export function useReports(): ReportsContextValue {
  const value = useContext(ReportsContext);
  if (value === null) {
    throw new Error("useReports must be used inside <ReportsProvider>");
  }
  return value;
}
