import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import ts from "typescript";

const { outputText } = ts.transpileModule(
  readFileSync(new URL("../src/mascot/digging.ts", import.meta.url), "utf8"),
  {
    compilerOptions: {
      target: ts.ScriptTarget.ES2022,
      module: ts.ModuleKind.ES2022,
    },
  },
);
const {
  DIG_CYCLE,
  DIG_IMPACT,
  DIG_THROW,
  diggingPose,
  diggingEvents,
  dirtParticle,
} = await import(
  "data:text/javascript;base64," + Buffer.from(outputText).toString("base64")
);

test("digging has a slow lift, fast buried impact, leverage and a continuous return", () => {
  const liftSpeed = (diggingPose(0.9).height - diggingPose(0.1).height) / 0.8;
  const strikeSpeed = Math.abs(
    (diggingPose(1.41).height - diggingPose(1.21).height) / 0.2,
  );
  assert.ok(strikeSpeed > liftSpeed * 4);
  assert.ok(diggingPose(DIG_IMPACT).height < -0.3);
  assert.ok(diggingPose(2.15).pitch < -0.25);
  assert.equal(diggingPose(3.5).phase, "think");
  for (const boundary of [
    1,
    1.2,
    DIG_IMPACT,
    1.67,
    2.18,
    2.58,
    3.08,
    DIG_CYCLE,
  ]) {
    const before = diggingPose(boundary - 1e-7),
      after = diggingPose(boundary + 1e-7);
    assert.ok(Math.abs(before.height - after.height) < 0.00001);
    assert.ok(Math.abs(before.pitch - after.pitch) < 0.00001);
    assert.ok(Math.abs(before.roll - after.roll) < 0.00001);
  }
  for (let time = 0; time < DIG_CYCLE * 3; time += 0.013) {
    const pose = diggingPose(time);
    assert.ok(
      Number.isFinite(pose.height) &&
        pose.height >= -0.39 &&
        pose.height <= 0.53,
    );
  }
});

test("each cycle emits exactly one impact and one throw, including skipped frames", () => {
  const events = [];
  for (let t = 0; t < DIG_CYCLE * 3; t += 0.047)
    events.push(...diggingEvents(t, Math.min(t + 0.047, DIG_CYCLE * 3)));
  assert.deepEqual(
    events.map((e) => e.kind),
    ["impact", "throw", "impact", "throw", "impact", "throw"],
  );
  assert.deepEqual(diggingEvents(0, DIG_CYCLE * 3), events);
  assert.equal(diggingEvents(DIG_IMPACT, DIG_THROW - 0.001).length, 0);
});

test("soil particles rise, fall, bounce above the floor and disappear without drifting off the island", () => {
  for (let index = 0; index < 20; index++) {
    const thrown = index >= 8;
    assert.equal(dirtParticle(index, -0.1, thrown).visible, false);
    let highest = 0,
      last = 0,
      fell = false,
      shrank = false;
    for (let age = 0; age < 2; age += 0.01) {
      const p = dirtParticle(index, age, thrown);
      assert.ok([p.x, p.y, p.z, p.size].every(Number.isFinite));
      assert.ok(p.y >= 0 && Math.hypot(p.x, p.z) < 1.45);
      if (!p.visible) continue;
      highest = Math.max(highest, p.y);
      if (highest > 0.1 && p.y < last) fell = true;
      if (p.size < 0.02) shrank = true;
      last = p.y;
    }
    assert.ok(highest > 0.1 && fell && shrank);
    assert.equal(dirtParticle(index, 2, thrown).visible, false);
  }
});
