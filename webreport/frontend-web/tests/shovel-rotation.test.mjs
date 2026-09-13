import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";

const { outputText } = ts.transpileModule(
  readFileSync(
    new URL("../src/mascot/shovel-rotation.ts", import.meta.url),
    "utf8",
  ),
  {
    compilerOptions: {
      target: ts.ScriptTarget.ES2022,
      module: ts.ModuleKind.ES2022,
    },
  },
);
const { ShovelRotation } = await import(
  "data:text/javascript;base64," + Buffer.from(outputText).toString("base64")
);

test("dragging controls both shovel axes and never becomes a greeting on return", () => {
  const rotation = new ShovelRotation();
  assert.equal(rotation.begin(1, 50, 50, 200), true);
  assert.equal(rotation.begin(2, 30, 30, 200), false);
  assert.equal(rotation.move(2, 200, 200), false);
  assert.equal(rotation.move(1, 130, 90), true);
  assert.ok(rotation.yaw > 0.5 && rotation.pitch > 0);
  assert.ok(rotation.pitch < Math.PI / 18);
  rotation.move(1, 50, 50);
  assert.equal(rotation.end(1), false);
  assert.equal(rotation.held, false);
  rotation.begin(3, 50, 50, 200);
  rotation.move(3, 52, 52);
  assert.equal(rotation.end(3), true);
});

test("pitch stays bounded, yaw allows full turns, cancellation and Home recover control", () => {
  const rotation = new ShovelRotation();
  rotation.begin(1, 0, 0, 150);
  rotation.move(1, 900, 900);
  assert.ok(rotation.yaw > Math.PI * 2);
  assert.equal(rotation.pitch, Math.PI / 18);
  rotation.cancel(1);
  assert.equal(rotation.held, false);
  assert.equal(rotation.end(1), false);
  for (let i = 0; i < 30; i++) rotation.key("ArrowUp");
  assert.equal(rotation.pitch, -Math.PI / 18);
  const yawBefore = rotation.yaw;
  rotation.begin(2, 0, 0, 150);
  rotation.move(2, -900, -900);
  assert.ok(rotation.yaw < yawBefore - Math.PI * 2);
  assert.equal(rotation.pitch, -Math.PI / 18);
  rotation.cancel(2);
  for (let i = 0; i < 30; i++) rotation.key("ArrowDown");
  assert.equal(rotation.pitch, Math.PI / 18);
  assert.equal(rotation.key("Home"), true);
  assert.equal(rotation.yaw, 0);
  assert.equal(rotation.pitch, 0);
  assert.equal(rotation.oriented, false);
  assert.equal(rotation.key("Tab"), false);
});
