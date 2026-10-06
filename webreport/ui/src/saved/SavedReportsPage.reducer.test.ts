/**
 * Exhaustive settle oracle for the Saved Reports reducer.
 *
 * The page issues one report GET per selection. Between the moment it is
 * issued (navigate away and back to r1) and the moment it settles, any
 * sequence of confirmed mutations - of THIS report or of OTHER reports - can
 * land. This test enumerates every ordering of every subset of a fixed event
 * set, every issue point inside it and every settle kind, and checks the
 * outcome against rules written independently of the reducer:
 *
 * - settled means settled: after its own request settles the preview is never
 *   «loading» (it is ready, an error or «missing»);
 * - a successful response shows the highest version known for r1 (the server
 *   never goes back in version, and a confirmed Update is server truth too);
 * - a failed response is real unless a successful Update of r1 itself was
 *   confirmed AFTER the request was issued - then that update is shown;
 * - mutations of other reports never decide r1's outcome;
 * - the list never lists an unsaved report and always carries the highest
 *   known version of each report.
 */
import { describe, expect, it } from "vitest";

import type { Report, ReportCard } from "../api/types";
import { initialState, reducer } from "./SavedReportsPage";
import type { SavedAction, SavedState } from "./SavedReportsPage";

function card(id: string, version: number): ReportCard {
  return {
    id,
    chat_id: "c1",
    title: `Отчёт ${id}`,
    question: "Сколько очков набрали команды?",
    tool: "read_rows",
    args: { table: "results" },
    generated_at: `2026-09-2${String(version)}T10:00:00Z`,
    version,
    saved_at: "2026-09-29T09:00:00Z",
    row_count: version,
    created_at: "2026-09-20T10:00:00Z",
  };
}

const report = (id: string, version: number): Report => ({ ...card(id, version), data: [{ v: version }] });

type Event =
  | { kind: "updateOk"; id: string; version: number }
  | { kind: "updateFail"; id: string }
  | { kind: "unsaveOk"; id: string };

const EVENTS: Event[] = [
  { kind: "updateOk", id: "r1", version: 3 },
  { kind: "updateOk", id: "r1", version: 4 },
  { kind: "updateOk", id: "r2", version: 2 },
  { kind: "updateFail", id: "r1" },
  { kind: "unsaveOk", id: "r2" },
  { kind: "unsaveOk", id: "r1" },
];

type Settle = "resolve" | "fail" | "missing";
const SETTLES: Settle[] = ["resolve", "fail", "missing"];

/** Every ordering of every subset of `events` in which r1's versions stay monotonic. */
function* orderings(events: Event[], prefix: Event[] = []): Generator<Event[]> {
  yield prefix;
  for (let i = 0; i < events.length; i += 1) {
    const event = events[i] as Event;
    if (event.kind === "updateOk" && prefix.some((e) => e.kind === "updateOk" && e.id === event.id && e.version > event.version)) {
      continue; // the server never returns a lower version for the same report
    }
    yield* orderings([...events.slice(0, i), ...events.slice(i + 1)], [...prefix, event]);
  }
}

function actionsOf(event: Event): SavedAction[] {
  switch (event.kind) {
    case "updateOk":
      return [
        { type: "updateStarted", reportId: event.id },
        { type: "updateSucceeded", report: report(event.id, event.version) },
      ];
    case "updateFail":
      return [
        { type: "updateStarted", reportId: event.id },
        { type: "updateFailed", reportId: event.id, text: "Обновить не удалось: x. Показана версия от y" },
      ];
    case "unsaveOk":
      return [{ type: "unsaveStarted" }, { type: "unsaveSucceeded", reportId: event.id }];
  }
}

const apply = (state: SavedState, actions: SavedAction[]) => actions.reduce(reducer, state);

const r1Versions = (events: Event[]) =>
  events.flatMap((e) => (e.kind === "updateOk" && e.id === "r1" ? [e.version] : []));

interface Case {
  before: Event[];
  after: Event[];
  settle: Settle;
}

function* cases(): Generator<Case> {
  for (const sequence of orderings(EVENTS)) {
    for (let p = 0; p <= sequence.length; p += 1) {
      for (const settle of SETTLES) {
        yield { before: sequence.slice(0, p), after: sequence.slice(p), settle };
      }
    }
  }
}

const label = (c: Case) =>
  `[${c.before.map(describeEvent).join(" ")}] GET [${c.after.map(describeEvent).join(" ")}] ${c.settle}`;

function describeEvent(e: Event): string {
  return e.kind === "updateOk" ? `${e.kind}:${e.id}@${String(e.version)}` : `${e.kind}:${e.id}`;
}

function runCase(c: Case): SavedState {
  // Mount on /saved/r1 with the list [r1@2, r2@1] loaded before any mutation.
  let state = initialState("r1");
  state = apply(state, [
    { type: "reportLoaded", seq: state.previewSeq, issuedAt: state.generation, report: report("r1", 2) },
    { type: "listLoaded", seq: state.listSeq, issuedAt: state.generation, cards: [card("r1", 2), card("r2", 1)] },
  ]);
  for (const event of c.before) state = apply(state, actionsOf(event));

  // Navigate away and back: this issues the report GET under test.
  state = apply(state, [
    { type: "select", reportId: "r2" },
    { type: "select", reportId: "r1" },
  ]);
  const seq = state.previewSeq;
  const issuedAt = state.generation;
  const serverVersionAtIssue = Math.max(2, ...r1Versions(c.before));

  for (const event of c.after) state = apply(state, actionsOf(event));

  const settled: SavedAction =
    c.settle === "resolve"
      ? { type: "reportLoaded", seq, issuedAt, report: report("r1", serverVersionAtIssue) }
      : {
          type: "reportFailed",
          seq,
          issuedAt,
          reportId: "r1",
          missing: c.settle === "missing",
          message: "Связь с сервером потеряна",
        };
  return reducer(state, settled);
}

describe("SavedReportsPage reducer settle oracle", () => {
  const all = [...cases()];

  it("enumerates a non-trivial space", () => {
    expect(all.length).toBeGreaterThan(10_000);
  });

  it("never leaves the preview loading after its request settled, and shows the right version", () => {
    const failures: string[] = [];
    for (const c of all) {
      const state = runCase(c);
      const highest = Math.max(2, ...r1Versions([...c.before, ...c.after]));
      const updatedAfterIssue = r1Versions(c.after).length > 0;

      const expected =
        c.settle === "resolve" || updatedAfterIssue
          ? { kind: "ready", report: expect.objectContaining({ id: "r1", version: highest }) }
          : c.settle === "fail"
            ? { kind: "error", message: "Связь с сервером потеряна" }
            : { kind: "missing" };

      try {
        expect(state.preview).toEqual(expected);
        expect(state.preview.kind).not.toBe("loading");
      } catch (error) {
        failures.push(`${label(c)}: ${(error as Error).message.split("\n")[0] ?? ""} -> ${JSON.stringify(state.preview)}`);
      }
    }
    expect(failures.slice(0, 10)).toEqual([]);
    expect(failures.length).toBe(0);
  });

  it("keeps the list free of unsaved reports and at the highest known versions", () => {
    const failures: string[] = [];
    for (const c of all) {
      const state = runCase(c);
      const events = [...c.before, ...c.after];
      const unsaved = new Set(events.flatMap((e) => (e.kind === "unsaveOk" ? [e.id] : [])));
      const expectedRows = [
        ["r1", Math.max(2, ...r1Versions(events))],
        ["r2", events.some((e) => e.kind === "updateOk" && e.id === "r2") ? 2 : 1],
      ]
        .filter(([id]) => !unsaved.has(id as string))
        .map(([id, version]) => `${String(id)}@${String(version)}`);
      const rows = state.items.map((item) => `${item.id}@${String(item.version)}`);
      if (JSON.stringify(rows) !== JSON.stringify(expectedRows)) {
        failures.push(`${label(c)}: ${JSON.stringify(rows)} != ${JSON.stringify(expectedRows)}`);
      }
    }
    expect(failures.slice(0, 10)).toEqual([]);
    expect(failures.length).toBe(0);
  });
});
