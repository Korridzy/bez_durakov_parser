/**
 * One record per report, shared by every surface of the panel (card, inline
 * preview, fullscreen dialog): D3 - one object in both views.
 *
 * A record holds two facts ordered independently on ONE clock (a request takes
 * a position when it is ISSUED, a mutation one more when it is confirmed):
 *
 *  - `content` (title, version, generated_at, row_count, ...): from the server
 *    snapshot with the highest version, ties broken by the newest issue
 *    position. The server's version is monotonic, so a lower version never
 *    replaces a higher one; a PUT response contributes content only as of the
 *    request's ISSUE position (its card was built no later than that), a
 *    DELETE contributes none.
 *  - `bookmark` (saved_at): from the fact with the highest position - a
 *    response's issue position, or a mutation's CONFIRMATION position, which
 *    is why our confirmed Save/Unsave beats every request issued before it and
 *    yields to every request issued after it.
 *
 * A confirmation is AMBIGUOUS when an observation of the report was issued
 * after the mutation (learned already, or still in flight): the server executed
 * the mutation somewhere between its issue and the delivery of its response, so
 * the client cannot know whether that observation saw the state before or after
 * the execution - a delayed acknowledgement does not mean delayed execution.
 * Then (1) a learned newer observation stays the displayed truth, the
 * acknowledgement never overrides it; (2) an observation still in flight lets
 * the acknowledgement apply as the freshest LEARNED fact, and a response issued
 * before the confirmation cannot undo it; and in both cases (3) the record asks
 * for a RECONCILE: a report GET issued after the acknowledgement, whose answer
 * is authoritative by the ordinary issue-order rules (`reconcile` counts the
 * requests, the GETs issued and the GETs completed: at most one in flight, a
 * later ambiguous acknowledgement gets its own GET after it - an in-flight one
 * was issued before that acknowledgement and cannot speak for it). Without any
 * observation issued after the mutation the acknowledgement is simply the
 * freshest fact. A failed mutation was not applied: only its optimistic layer
 * goes and the newest observation shows. A report the server says is gone is
 * forgotten altogether (`forgetReport`; the panel's gone rule decides when).
 *
 * Arrival order never decides either fact. On top sits at most one optimistic
 * bookmark of a mutation in flight, removed by its own outcome only.
 *
 * The preview's `data` belongs to the version it was fetched with; when the
 * record's version moves past it the panel re-fetches (see `ReportsPanel`).
 */

import type { ReportCard } from "../api/types";

export interface ReportRecord {
  content: { card: ReportCard; seq: number };
  bookmark: { saved_at: string | null; seq: number };
  /** The one mutation in flight, if any. */
  optimistic: { mutationId: number; saved_at: string | null } | null;
  /** Reconcile GETs after ambiguous acknowledgements: requested, issued, completed. */
  reconcile: { requested: number; issued: number; completed: number };
}

const NO_RECONCILE: ReportRecord["reconcile"] = { requested: 0, issued: 0, completed: 0 };

/** `null` remembers a gone id without retaining its data, optimism or pending work. */
export type ReportRecords = ReadonlyMap<string, ReportRecord | null>;

export const NO_RECORDS: ReportRecords = new Map();

function withRecord(records: ReportRecords, id: string, record: ReportRecord): ReportRecords {
  const next = new Map(records);
  next.set(id, record);
  return next;
}

function newerContent(
  current: ReportRecord["content"],
  card: ReportCard,
  seq: number,
): ReportRecord["content"] {
  const newer =
    card.version > current.card.version ||
    (card.version === current.card.version && seq > current.seq);
  return newer ? { card, seq } : current;
}

function newerBookmark(
  current: ReportRecord["bookmark"],
  saved_at: string | null,
  seq: number,
): ReportRecord["bookmark"] {
  return seq > current.seq ? { saved_at, seq } : current;
}

/** Folds a snapshot issued at `seq` into both facts; older knowledge changes nothing. */
export function observe(records: ReportRecords, card: ReportCard, seq: number): ReportRecords {
  const entry = records.get(card.id);
  // A response already in flight cannot bring a deleted report back.
  if (entry === null) {
    return records;
  }
  if (entry === undefined) {
    return withRecord(records, card.id, {
      content: { card, seq },
      bookmark: { saved_at: card.saved_at, seq },
      optimistic: null,
      reconcile: NO_RECONCILE,
    });
  }
  const content = newerContent(entry.content, card, seq);
  const bookmark = newerBookmark(entry.bookmark, card.saved_at, seq);
  return content === entry.content && bookmark === entry.bookmark
    ? records
    : withRecord(records, card.id, { ...entry, content, bookmark });
}

export function observeAll(
  records: ReportRecords,
  cards: readonly ReportCard[],
  seq: number,
): ReportRecords {
  return cards.reduce((acc, card) => observe(acc, card, seq), records);
}

/**
 * Starts a mutation on the displayed `card` (always an already-observed one:
 * a card the user can click was rendered from its record).
 */
export function beginMutation(
  records: ReportRecords,
  card: ReportCard,
  mutationId: number,
  saved_at: string | null,
): ReportRecords {
  if (records.get(card.id) === null) {
    return records;
  }
  const entry = records.get(card.id) ?? {
    content: { card, seq: 0 },
    bookmark: { saved_at: card.saved_at, seq: 0 },
    optimistic: null,
    reconcile: NO_RECONCILE,
  };
  return withRecord(records, card.id, { ...entry, optimistic: { mutationId, saved_at } });
}

export interface Confirmation {
  /** The mutation's id, which is also the position of its issue. */
  mutationId: number;
  /** The position of the confirmation: where its bookmark fact stands. */
  confirmedSeq: number;
  /** The PUT response (content as of the issue, bookmark as confirmed); `null` for DELETE. */
  response: ReportCard | null;
  /** An observation of the report issued after the mutation is still in flight. */
  pendingNewer: boolean;
}

/**
 * The server confirmed the mutation: a bookmark fact of now unless a newer
 * observation is already known, content (if any) of the issue, and a reconcile
 * request whenever the outcome is ambiguous (see the header).
 */
export function confirmMutation(
  records: ReportRecords,
  id: string,
  { mutationId, confirmedSeq, response, pendingNewer }: Confirmation,
): ReportRecords {
  const entry = records.get(id);
  if (entry == null) {
    return records;
  }
  const learnedNewer = entry.bookmark.seq > mutationId;
  const saved_at = response === null ? null : response.saved_at;
  return withRecord(records, id, {
    content: response === null ? entry.content : newerContent(entry.content, response, mutationId),
    bookmark: learnedNewer ? entry.bookmark : newerBookmark(entry.bookmark, saved_at, confirmedSeq),
    optimistic: entry.optimistic?.mutationId === mutationId ? null : entry.optimistic,
    reconcile:
      learnedNewer || pendingNewer
        ? { ...entry.reconcile, requested: entry.reconcile.requested + 1 }
        : entry.reconcile,
  });
}

/** A reconcile GET is due: one was requested and none is in flight. */
export function wantsReconcile(entry: ReportRecord | null): entry is ReportRecord {
  return entry !== null &&
    entry.reconcile.requested > entry.reconcile.issued &&
    entry.reconcile.issued === entry.reconcile.completed;
}

export function reconcileIssued(records: ReportRecords, id: string): ReportRecords {
  const entry = records.get(id);
  if (entry == null) {
    return records;
  }
  return withRecord(records, id, {
    ...entry,
    reconcile: { ...entry.reconcile, issued: entry.reconcile.issued + 1 },
  });
}

/** A reconcile GET finished (a forgotten report has nothing to complete). */
export function reconcileCompleted(records: ReportRecords, id: string): ReportRecords {
  const entry = records.get(id);
  if (entry == null) {
    return records;
  }
  return withRecord(records, id, {
    ...entry,
    reconcile: { ...entry.reconcile, completed: entry.reconcile.completed + 1 },
  });
}

/** The report is gone: everything known about it goes, pending reconciles included. */
export function forgetReport(records: ReportRecords, id: string): ReportRecords {
  if (records.get(id) === null) {
    return records;
  }
  const next = new Map(records);
  next.set(id, null);
  return next;
}

/** The mutation failed: only its own optimistic layer goes. */
export function failMutation(records: ReportRecords, id: string, mutationId: number): ReportRecords {
  const entry = records.get(id);
  if (entry == null || entry.optimistic?.mutationId !== mutationId) {
    return records;
  }
  return withRecord(records, id, { ...entry, optimistic: null });
}

/** The card every surface renders: content + bookmark, the optimistic bookmark on top. */
export function effectiveCard(records: ReportRecords, id: string): ReportCard | undefined {
  const entry = records.get(id);
  if (entry == null) {
    return undefined;
  }
  const { card } = entry.content;
  const saved_at =
    entry.optimistic !== null ? entry.optimistic.saved_at : entry.bookmark.saved_at;
  return saved_at === card.saved_at ? card : { ...card, saved_at };
}
