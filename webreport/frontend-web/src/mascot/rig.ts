export type Action = "idle" | "work" | "think" | "wave" | "found" | "puzzled";

/** A front-facing cutout: rotations stay in the drawing plane. No limb rig. */
export type Pose = {
  bodyAngle: number;
  headAngle: number;
  headY: number;
  handX: number;
  handY: number;
  handAngle: number;
  shovelX: number;
  shovelY: number;
  shovelAngle: number;
  smile: number;
  browLeft: number;
  browRight: number;
  gazeY: number;
  sparkle: number;
};

export function poseFor(action: Action, t: number): Pose {
  const breath = Math.sin(t * 1.5);
  const pose: Pose = {
    bodyAngle: breath * 0.7,
    headAngle: -1 + breath * 0.8,
    headY: -98 + breath * 0.6,
    handX: -39,
    handY: -46 + breath,
    handAngle: -8,
    shovelX: 43,
    shovelY: -50,
    shovelAngle: -8,
    smile: 0.5,
    browLeft: 0,
    browRight: 0,
    gazeY: 0,
    sparkle: 0,
  };
  if (action === "work") {
    const rhythm = Math.sin(t * 2.1);
    pose.bodyAngle = 1 + rhythm;
    pose.headAngle = 3 + rhythm;
    pose.shovelY = -52 + rhythm * 3;
    pose.shovelAngle = -9 + rhythm * 6;
    pose.handY = -49 + rhythm * 2;
    pose.gazeY = 1.5;
    pose.smile = 0.25;
  } else if (action === "think" || action === "puzzled") {
    pose.headAngle = -6;
    pose.handX = -38;
    pose.handY = -85 + breath;
    pose.handAngle = -18;
    pose.gazeY = -1.5;
    pose.browLeft = -2;
    pose.browRight = action === "puzzled" ? 3 : 1;
    pose.smile = action === "puzzled" ? -0.3 : 0.15;
  } else if (action === "wave") {
    pose.headAngle = 3;
    pose.handX = -46;
    pose.handY = -99 + breath;
    pose.handAngle = Math.sin(t * 4) * 14;
    pose.smile = 0.9;
    pose.browLeft = -1;
    pose.browRight = -1;
  } else if (action === "found") {
    pose.headAngle = -3;
    pose.handX = -44;
    pose.handY = -69 + breath;
    pose.handAngle = 8;
    pose.smile = 1;
    pose.browLeft = -2;
    pose.browRight = -2;
    pose.sparkle = 1;
  }
  return pose;
}

export function blendPose(from: Pose, to: Pose, amount: number): Pose {
  const result = { ...from };
  for (const key of Object.keys(to) as (keyof Pose)[])
    result[key] = from[key] + (to[key] - from[key]) * amount;
  return result;
}

export function idleAction(t: number): Action {
  const phase = t % 30;
  return phase < 12
    ? "idle"
    : phase < 18
      ? "think"
      : phase < 22
        ? "wave"
        : "idle";
}

export function ribbonPath(
  x: number,
  y: number,
  length: number,
  breadth: number,
  t: number,
) {
  const edge = (u: number) =>
    Math.sin(u * 7 - t * 1.7) * u * 6 + Math.sin(u * 3 - t) * u * 2;
  const points: [number, number][] = [];
  for (let i = 0; i <= 24; i++) {
    const u = i / 24;
    points.push([x + u * length, y + edge(u)]);
  }
  for (let i = 24; i >= 0; i--) {
    const u = i / 24;
    points.push([x + u * length, y + edge(u) + breadth * (1 - u * 0.92)]);
  }
  return (
    points
      .map((p, i) => (i ? "L" : "M") + p.map((v) => v.toFixed(2)).join(","))
      .join(" ") + " Z"
  );
}
