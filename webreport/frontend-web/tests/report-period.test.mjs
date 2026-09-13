import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";

const { outputText } = ts.transpileModule(
  readFileSync(new URL("../src/report-period.ts", import.meta.url), "utf8"),
  {
    compilerOptions: {
      target: ts.ScriptTarget.ES2022,
      module: ts.ModuleKind.ES2022,
    },
  },
);
const { presetDates, matchingPreset, periodError } = await import(
  `data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`
);

test("today and yesterday use calendar dates, including the year boundary", () => {
  const now = new Date(2026, 0, 1, 0, 15);
  assert.deepEqual(presetDates("today", now), {
    date1: "2026-01-01",
    date2: "2026-01-01",
  });
  assert.deepEqual(presetDates("yesterday", now), {
    date1: "2025-12-31",
    date2: "2025-12-31",
  });
});

test("rolling periods include exactly 7, 30 or 90 complete days across leap day", () => {
  const now = new Date(2024, 2, 1);
  assert.deepEqual(presetDates("week", now), {
    date1: "2024-02-23",
    date2: "2024-02-29",
  });
  assert.deepEqual(presetDates("month", now), {
    date1: "2024-01-31",
    date2: "2024-02-29",
  });
  assert.deepEqual(presetDates("quarter", now), {
    date1: "2023-12-02",
    date2: "2024-02-29",
  });
});

test("the selected preset reflects the actual dates, including a custom initial period", () => {
  const now = new Date(2026, 8, 13);
  assert.equal(
    matchingPreset({ date1: "2026-08-14", date2: "2026-09-12" }, now),
    "month",
  );
  assert.equal(
    matchingPreset({ date1: "2026-09-01", date2: "2026-09-12" }, now),
    undefined,
  );
});

test("custom dates allow one day and 366 inclusive days, reject invalid requests", () => {
  const validate = (date1, date2) =>
    periodError({ date1, date2 }, "2026-09-13");
  assert.equal(validate("2026-09-13", "2026-09-13"), "");
  assert.equal(validate("2024-01-01", "2024-12-31"), "");
  assert.ok(validate("2024-01-01", "2025-01-01"));
  assert.ok(validate("2026-09-13", "2026-09-12"));
  assert.ok(validate("2026-09-13", "2026-09-14"));
  assert.ok(validate("", "2026-09-13"));
});
