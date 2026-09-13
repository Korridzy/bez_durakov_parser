import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";

const source = readFileSync(
  new URL("../src/mascot/rig.ts", import.meta.url),
  "utf8",
);
const { outputText } = ts.transpileModule(source, {
  compilerOptions: {
    target: ts.ScriptTarget.ES2022,
    module: ts.ModuleKind.ES2022,
  },
});
const { poseFor, blendPose, idleAction, ribbonPath } = await import(
  "data:text/javascript;base64," + Buffer.from(outputText).toString("base64")
);
const actions = ["idle", "work", "think", "wave", "found", "puzzled"];

test("gestures keep the face upright and the floating hands outside the torso", () => {
  for (const action of actions)
    for (let t = 0; t < 30; t += 0.1) {
      const p = poseFor(action, t);
      assert.ok(Object.values(p).every(Number.isFinite), action);
      assert.ok(Math.abs(p.bodyAngle) <= 2);
      assert.ok(Math.abs(p.headAngle) <= 6);
      assert.ok(p.headY >= -99 && p.headY <= -97);
      assert.ok(p.handX <= -38 && p.handX >= -46);
      assert.ok(p.shovelX >= 40 && p.shovelX <= 46);
      assert.ok(p.shovelY >= -55 && p.shovelY <= -49);
      assert.ok(Math.abs(p.shovelAngle) <= 15);
    }
});

test("every emotion blends continuously without overshoot or mutation", () => {
  for (const from of actions)
    for (const to of actions) {
      let p = poseFor(from, 1);
      const initial = structuredClone(p),
        target = poseFor(to, 1);
      for (let frame = 0; frame < 120; frame++) {
        const next = blendPose(p, target, 1 - Math.exp(-5 / 30));
        for (const key of Object.keys(next)) {
          assert.ok(next[key] >= Math.min(initial[key], target[key]) - 1e-8);
          assert.ok(next[key] <= Math.max(initial[key], target[key]) + 1e-8);
        }
        p = next;
      }
      for (const key of Object.keys(p))
        assert.ok(Math.abs(p[key] - target[key]) < 0.001);
      assert.deepEqual(poseFor(from, 1), initial);
    }
});

test("the flag moves while its attachment stays fixed", () => {
  assert.notEqual(
    ribbonPath(270, 45, 96, 18, 0),
    ribbonPath(270, 45, 96, 18, 1),
  );
  for (let t = 0; t < 30; t += 0.5) {
    const path = ribbonPath(270, 45, 96, 18, t);
    assert.ok(path.startsWith("M270.00,45.00"));
    assert.ok(!/NaN|Infinity/.test(path));
  }
});

test("the welcome loop stays calm with occasional thought and greeting", () => {
  const seen = new Set(Array.from({ length: 30 }, (_, t) => idleAction(t)));
  assert.deepEqual(seen, new Set(["idle", "think", "wave"]));
});
