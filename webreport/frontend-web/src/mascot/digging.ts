export const DIG_CYCLE = 3.8;
export const DIG_IMPACT = 1.42;
export const DIG_THROW = 2.24;
export type DigPhase =
  | "lift"
  | "aim"
  | "strike"
  | "impact"
  | "lever"
  | "scoop"
  | "recover"
  | "think";
const smooth = (t: number) => {
  const x = Math.max(0, Math.min(1, t));
  return x * x * (3 - 2 * x);
};

// Height is measured from the planted blade tip, in world units.
const keys: readonly [number, number, number, DigPhase][] = [
  [0, 0, 0.02, "lift"],
  [1, 0.48, -0.17, "aim"],
  [1.2, 0.52, -0.19, "strike"],
  [DIG_IMPACT, -0.36, 0.22, "impact"],
  [1.67, -0.33, 0.27, "lever"],
  [2.18, -0.16, -0.34, "scoop"],
  [2.58, 0.2, -0.52, "recover"],
  [3.08, 0, 0.02, "think"],
  [DIG_CYCLE, 0, 0.02, "lift"],
];

export function diggingPose(elapsed: number) {
  const time = ((elapsed % DIG_CYCLE) + DIG_CYCLE) % DIG_CYCLE;
  let i = 0;
  while (i < keys.length - 2 && time >= keys[i + 1][0]) i++;
  const [start, y0, p0, phase] = keys[i];
  const [end, y1, p1] = keys[i + 1];
  const t = (time - start) / (end - start);
  // Acceleration into the ground; a short recoil happens after the impact.
  const weight = phase === "strike" ? t * t : smooth(t);
  const recoil =
    phase === "impact" ? Math.sin(t * Math.PI * 3) * (1 - t) * 0.024 : 0;
  return {
    phase,
    height: y0 + (y1 - y0) * weight + recoil,
    pitch: p0 + (p1 - p0) * weight,
    roll: -0.035 + (phase === "think" ? Math.sin(t * Math.PI) * 0.09 : 0),
  };
}

export function diggingEvents(before: number, after: number) {
  const events: { kind: "impact" | "throw"; time: number }[] = [];
  for (
    let cycle = Math.floor(before / DIG_CYCLE);
    cycle <= Math.floor(after / DIG_CYCLE);
    cycle++
  ) {
    for (const [at, kind] of [
      [DIG_IMPACT, "impact"],
      [DIG_THROW, "throw"],
    ] as const) {
      const time = cycle * DIG_CYCLE + at;
      if (time > before && time <= after) events.push({ kind, time });
    }
  }
  return events;
}

// Ballistic flight followed by one little bounce and a quick settle/shrink.
export function dirtParticle(index: number, age: number, thrown: boolean) {
  const delay = (index % 4) * 0.017;
  const t = age - delay;
  const gravity = 4.2;
  const height = thrown ? 0.22 : 0.025;
  const velocity = (thrown ? 1.18 : 0.7) + (index % 5) * 0.095;
  const flight =
    (velocity + Math.sqrt(velocity * velocity + 2 * gravity * height)) /
    gravity;
  const end = flight + 0.28;
  const radius = 0.034 + (index % 5) * 0.011;
  const angle = index * 2.39996 + (thrown ? 0.8 : 0);
  const travel = Math.max(0, Math.min(t, flight));
  const fade = 1 - smooth((t - flight - 0.06) / 0.22);
  const y =
    t <= flight
      ? height + velocity * Math.max(0, t) - (gravity * Math.max(0, t) ** 2) / 2
      : Math.max(0, Math.sin(Math.min(1, (t - flight) / 0.18) * Math.PI)) *
        0.045;
  return {
    visible: t >= 0 && t < end,
    size: radius * fade,
    x: Math.cos(angle) * travel * (thrown ? 1.35 : 0.85),
    y: Math.max(0, y) + radius * fade,
    z: 0.2 + Math.abs(Math.sin(angle)) * travel * (thrown ? 0.8 : 0.62),
  };
}
