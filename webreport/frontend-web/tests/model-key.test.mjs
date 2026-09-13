import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";

const { outputText } = ts.transpileModule(
  readFileSync(new URL("../src/model-key.ts", import.meta.url), "utf8"),
  { compilerOptions: { module: ts.ModuleKind.ES2022 } },
);
const { modelKeyError } = await import(
  `data:text/javascript;base64,${Buffer.from(outputText).toString("base64")}`
);

test("obvious paste mistakes cannot be submitted as model credentials", () => {
  for (const value of [
    "",
    "   ",
    "Bearer synthetic",
    "Authorization: Bearer synthetic",
    "synthetic token",
    "synthetic\ntoken",
    "synthetic\ttoken",
    "ключ",
    "synthetic\u200btoken",
    "synthetic\u0000token",
    "synthetic\u007ftoken",
  ])
    assert.notEqual(modelKeyError(value), "");
});

test("opaque keys have no guessed prefix, alphabet or fixed length", () => {
  for (const value of [
    "sk-synthetic",
    "sk-proj-synthetic",
    "sk-or-v1-synthetic",
    "AIza-synthetic",
    "future_format.123+/=",
    "x",
    "x".repeat(300),
    " \n synthetic-token \r\n ",
  ])
    assert.equal(modelKeyError(value), "");
});
