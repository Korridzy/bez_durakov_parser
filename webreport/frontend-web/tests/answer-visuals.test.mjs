import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";

const { outputText } = ts.transpileModule(
  readFileSync(new URL("../src/answer-visuals.ts", import.meta.url), "utf8"),
  {
    compilerOptions: {
      target: ts.ScriptTarget.ES2022,
      module: ts.ModuleKind.ES2022,
    },
  },
);
const {
  parseVisual,
  copyAnswer,
  visualColor,
  visualNumber,
  limitVisualBlocks,
} = await import(
  `data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`
);
// Validate the actual examples inserted into the backend's system prompt.
const examples = JSON.parse(
  readFileSync(
    new URL(
      "../../backend/workspace/answer_visual_examples.json",
      import.meta.url,
    ),
    "utf8",
  ),
);
const parse = (value) => parseVisual(JSON.stringify(value));
const chart = () => structuredClone(examples[1]);
const metrics = () => structuredClone(examples[0]);

test("a Markdown answer has a fresh four-visual budget including nested blocks", () => {
  const make = () => ({
    type: "root",
    children: Array.from({ length: 5 }, () => ({
      type: "blockquote",
      children: [{ type: "code", lang: "dig-visual" }],
    })),
  });
  const first = make();
  const transform = limitVisualBlocks();
  transform(first);
  assert.deepEqual(
    first.children.map((n) => n.children[0].lang),
    [
      "dig-visual",
      "dig-visual",
      "dig-visual",
      "dig-visual",
      "dig-visual-limit",
    ],
  );
  const second = make();
  transform(second);
  assert.equal(second.children[0].children[0].lang, "dig-visual");
});

test("the examples taught to the model render and preserve missing values", () => {
  for (const example of examples) assert.ok(parse(example));
  assert.equal(parse(chart()).data[1].users, null);
  assert.equal(parse(metrics()).items[0].trend[2], null);
  for (const kind of ["line", "area", "bar"])
    assert.equal(parse({ ...chart(), kind }).kind, kind);
});
test("malformed, unsupported and oversized blocks fail without throwing", () => {
  for (const value of [
    "",
    "{",
    "null",
    "[]",
    '{"version":2}',
    "x".repeat(64001),
  ])
    assert.equal(parseVisual(value), null);
  for (const changes of [
    { version: 2 },
    { kind: "pie" },
    { type: "html" },
    { source: "" },
    { series: [] },
    { data: [] },
    { format: "currency" },
  ])
    assert.equal(parse({ ...chart(), ...changes }), null);
});
test("missing numbers are never coerced into zero; nonfinite values are rejected", () => {
  for (const invalid of [undefined, "12", "3,8%", true, {}, 1e16]) {
    const data = chart();
    data.data[0].users = invalid;
    assert.equal(parse(data), null);
  }
  assert.equal(
    parseVisual(
      JSON.stringify(chart()).replace('"users":1800', '"users":1e999'),
    ),
    null,
  );
  const noValues = chart();
  noValues.data.forEach((row) => (row.users = null));
  assert.equal(parse(noValues), null);
  const zero = chart();
  zero.data[0].users = 0;
  assert.equal(parse(zero).data[0].users, 0);
});
test("series, categories, keys and row counts are bounded and unambiguous", () => {
  for (const invalid of [
    "constructor",
    "prototype",
    "__proto__",
    "a.b",
    "a[0]",
  ]) {
    const data = chart();
    data.series[0].key = invalid;
    assert.equal(parse(data), null);
  }
  const duplicate = chart();
  duplicate.data[1].date = duplicate.data[0].date;
  assert.equal(parse(duplicate), null);
  const sameKey = chart();
  sameKey.series[0].key = sameKey.x_key;
  assert.equal(parse(sameKey), null);
  assert.equal(
    parse({
      ...chart(),
      data: Array.from({ length: 121 }, (_, i) => ({
        date: String(i),
        users: i,
        visits: i,
      })),
    }),
    null,
  );
});
test("rendering uses only known fields, not model-supplied library properties", () => {
  const input = chart();
  input.onClick = "fetch('/private')";
  input.colors = ["red"];
  input.data[0].dangerouslySetInnerHTML = { __html: "<script>bad()</script>" };
  const block = parse(input);
  assert.equal(block.onClick, undefined);
  assert.equal(block.colors, undefined);
  assert.deepEqual(Object.keys(block.data[0]), ["date", "users", "visits"]);
});
test("card comparisons require a baseline; unknown values stay unknown", () => {
  const input = metrics();
  delete input.items[0].comparison;
  assert.equal(parse(input), null);
  const unknown = metrics();
  unknown.items[1].value = null;
  assert.equal(parse(unknown).items[1].value, null);
  const unlabeled = metrics();
  delete unlabeled.items[0].trend_label;
  assert.equal(parse(unlabeled), null);
  assert.equal(
    parse({ ...metrics(), items: Array(7).fill(metrics().items[1]) }),
    null,
  );
});
test("color identities survive ordering and value formatting preserves sign, gaps and tiny rates", () => {
  assert.equal(visualColor("users"), visualColor("users"));
  assert.notEqual(visualColor("users"), visualColor("visits"));
  const before = ["users", "visits", "custom_metric"].map(visualColor);
  assert.deepEqual(
    ["custom_metric", "visits", "users"].map(visualColor).reverse(),
    before,
  );
  assert.equal(visualNumber(null), "—");
  assert.equal(visualNumber(0), "0");
  assert.equal(visualNumber(3.8, "percent"), "3,8%");
  assert.equal(visualNumber(-90, "duration"), "−1 мин 30 с");
  assert.notEqual(visualNumber(0.0000001, "percent"), "0%");
});
test("copying a mixed answer retains prose and produces a readable contiguous table", () => {
  const answer = `Вывод\n\n\`\`\`dig-visual\n${JSON.stringify(chart())}\n\`\`\`\n\nПосле графика`;
  const text = copyAnswer(answer);
  assert.ok(text.startsWith("Вывод"));
  assert.ok(text.endsWith("После графика"));
  assert.ok(
    text.includes(
      "| Дата | Посетители | Визиты |\n| --- | ---: | ---: |\n| 2026-09-01 |",
    ),
  );
  assert.ok(text.includes("| 2026-09-02 | — |"));
  assert.ok(!text.includes("dig-visual"));
  assert.equal(
    copyAnswer('```json\n{"test":1}\n```'),
    '```json\n{"test":1}\n```',
  );
  assert.equal(
    copyAnswer("```dig-visual\ninvalid\n```"),
    "```dig-visual\ninvalid\n```",
  );
});
