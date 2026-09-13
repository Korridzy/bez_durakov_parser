import { useEffect, useId, useRef, useState } from "react";
import { blendPose, idleAction, poseFor, ribbonPath, type Action } from "./rig";

export type Activity =
  "welcome" | "working" | "thinking" | "success" | "rest" | "error";
const actions: Action[] = ["wave", "think", "work", "found", "idle"];

export function Expedition({
  activity,
  compact = false,
  motion = true,
  pose: previewPose,
}: {
  activity: Activity;
  compact?: boolean;
  motion?: boolean;
  pose?: Action;
}) {
  const root = useRef<HTMLButtonElement>(null);
  const rig = useRef(poseFor("idle", 0));
  const sequence = useRef(0);
  const [manual, setManual] = useState<Action | null>(null);
  const [visible, setVisible] = useState(true);
  const [reduced, setReduced] = useState(
    () => matchMedia("(prefers-reduced-motion: reduce)").matches,
  );
  const id = useId().replace(/:/g, "");
  const paintFill = (name: string) => `url(#${id}-${name})`;
  const animate = motion && visible && !reduced;

  useEffect(() => {
    const query = matchMedia("(prefers-reduced-motion: reduce)");
    const change = () => setReduced(query.matches);
    query.addEventListener("change", change);
    let intersecting = true;
    const check = () =>
      setVisible(intersecting && document.visibilityState === "visible");
    const observer = new IntersectionObserver(([entry]) => {
      intersecting = entry.isIntersecting;
      check();
    });
    if (root.current) observer.observe(root.current);
    document.addEventListener("visibilitychange", check);
    check();
    return () => {
      query.removeEventListener("change", change);
      document.removeEventListener("visibilitychange", check);
      observer.disconnect();
    };
  }, []);
  useEffect(() => {
    setManual(null);
  }, [activity]);
  useEffect(() => {
    if (!manual || !animate) return;
    const timer = setTimeout(() => setManual(null), 6500);
    return () => clearTimeout(timer);
  }, [manual, animate]);

  useEffect(() => {
    const node = root.current;
    if (!node) return;
    const parts = Object.fromEntries(
      Array.from(node.querySelectorAll<SVGElement>("[data-part]")).map((el) => [
        el.dataset.part!,
        el,
      ]),
    );
    const grass = Array.from(
      node.querySelectorAll<SVGPathElement>(".island-grass"),
    );
    let frame = 0,
      previous = 0;
    const start = performance.now();
    const set = (part: string, attr: string, value: string | number) =>
      parts[part]?.setAttribute(attr, String(value));
    const paint = (time: number) => {
      const t = animate ? (time - start) / 1000 : 0;
      const action =
        previewPose ||
        manual ||
        (activity === "working"
          ? "work"
          : activity === "thinking"
            ? "think"
            : activity === "error"
              ? "puzzled"
              : activity === "success"
                ? t < 6
                  ? "found"
                  : "idle"
                : activity === "welcome" && animate
                  ? idleAction(t)
                  : "idle");
      node.dataset.action = action;
      node.dataset.animated = String(animate);
      const dt = previous ? Math.min((time - previous) / 1000, 0.1) : 0.033;
      previous = time;
      rig.current = blendPose(
        rig.current,
        poseFor(action, t),
        animate ? 1 - Math.exp(-dt * 5) : 1,
      );
      const p = rig.current;
      set("body", "transform", `rotate(${p.bodyAngle} 0 -7)`);
      set(
        "head",
        "transform",
        `translate(0 ${p.headY}) rotate(${p.headAngle})`,
      );
      set(
        "free-hand",
        "transform",
        `translate(${p.handX} ${p.handY}) rotate(${p.handAngle})`,
      );
      // The grip is a child of the shovel, so they cannot drift apart.
      set(
        "shovel",
        "transform",
        `translate(${p.shovelX} ${p.shovelY}) rotate(${p.shovelAngle})`,
      );
      const blink = animate && t % 5.7 > 5.54 ? 0.14 : 1;
      for (const side of ["left", "right"]) {
        set(`eye-${side}`, "ry", 4.7 * blink);
        set(`eye-${side}`, "cy", p.gazeY);
        set(`glint-${side}`, "opacity", blink < 1 ? 0 : 0.9);
        set(`glint-${side}`, "cy", p.gazeY - 1.6);
      }
      set(
        "brow-left",
        "d",
        `M-19,${-12 + p.browLeft} Q-14,${-15 + p.browLeft} -9,-12`,
      );
      set(
        "brow-right",
        "d",
        `M9,-12 Q14,${-15 + p.browRight} 19,${-12 + p.browRight}`,
      );
      set("mouth", "d", `M-7,13 Q0,${13 + p.smile * 10} 7,13`);
      set("discovery", "transform", `translate(${p.handX} ${p.handY - 26})`);
      set("discovery", "opacity", p.sparkle);
      set("scarf-tail", "d", ribbonPath(-12, -65, -36, 8, t));
      set("flag", "d", ribbonPath(270, 45, 96, 18, t));
      set("flag-light", "d", ribbonPath(270, 45, 96, 5, t));
      grass.forEach((blade, i) => {
        const x = Number(blade.dataset.x),
          y = Number(blade.dataset.y),
          h = Number(blade.dataset.length);
        const lean = ((i % 3) - 1) * 6 + Math.sin(t * 1.2 + i * 0.6) * 3;
        blade.setAttribute(
          "d",
          `M${x},${y} Q${x + lean * 0.3},${y - h * 0.7} ${x + lean},${y - h} Q${x + lean * 0.65 + 1},${y - h * 0.4} ${x + 2.5},${y}Z`,
        );
      });
    };
    const loop = (time: number) => {
      if (time - previous >= 1000 / 30) paint(time);
      frame = requestAnimationFrame(loop);
    };
    paint(start);
    if (animate) frame = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(frame);
  }, [activity, animate, manual, previewPose]);

  return (
    <button
      ref={root}
      type="button"
      className={`expedition ${compact ? "compact" : "hero"}`}
      aria-label="Исследователь — показать другую эмоцию"
      title="Нажмите: исследователь покажет другую эмоцию"
      onClick={() => setManual(actions[sequence.current++ % actions.length])}
    >
      <svg
        viewBox={compact ? "50 30 330 245" : "0 0 420 280"}
        fill="none"
        aria-hidden="true"
        focusable="false"
      >
        <defs>
          <linearGradient
            id={`${id}-meadow`}
            x1="90"
            y1="145"
            x2="270"
            y2="220"
            gradientUnits="userSpaceOnUse"
          >
            <stop stopColor="#f6f4df" />
            <stop offset="1" stopColor="#dbe5d9" />
          </linearGradient>
          <linearGradient
            id={`${id}-rock`}
            x1="130"
            y1="180"
            x2="280"
            y2="270"
            gradientUnits="userSpaceOnUse"
          >
            <stop stopColor="#e5dcf5" />
            <stop offset="1" stopColor="#bca7df" />
          </linearGradient>
          <linearGradient
            id={`${id}-skin`}
            x1="-22"
            y1="-22"
            x2="24"
            y2="28"
            gradientUnits="userSpaceOnUse"
          >
            <stop stopColor="#ffe0bd" />
            <stop offset="1" stopColor="#edb5a0" />
          </linearGradient>
          <linearGradient
            id={`${id}-coat`}
            x1="-20"
            y1="-60"
            x2="24"
            y2="-10"
            gradientUnits="userSpaceOnUse"
          >
            <stop stopColor="#756784" />
            <stop offset="1" stopColor="#494259" />
          </linearGradient>
          <radialGradient id={`${id}-haze`}>
            <stop stopColor="#e8dff8" stopOpacity=".8" />
            <stop offset="1" stopColor="#f4edfb" stopOpacity="0" />
          </radialGradient>
        </defs>
        <ellipse cx="213" cy="164" rx="193" ry="102" fill={paintFill("haze")} />
        <circle cx="100" cy="94" r="27" fill="#fff3dd" opacity=".7" />
        <g className="island">
          <path d="M61 184 201 220 176 263 116 238Z" fill={paintFill("rock")} />
          <path d="m201 220 153-40-50 67-57 23Z" fill="#cbb8e8" />
          <path d="m201 220 46 50-12-59Z" fill="#e8ddf5" />
          <path d="m61 184 55 54 9-52Z" fill="#f0e9f8" />
          <path d="m305 224 20-15-6 34-12 8Z" fill="#ddd0ef" />
          <path
            d="M61 184q50-26 134-38 90 7 159 34-55 28-153 40-85-17-140-36Z"
            fill={paintFill("meadow")}
          />
          <path
            d="M64 185q66 12 137 31 90-12 149-35"
            stroke="#fffdf3"
            strokeWidth="2"
            opacity=".8"
          />
          <g className="island-arch">
            <path d="m300 125 16-9 19 13v50l-17 6v-46Z" fill="#bca9dc" />
            <path
              d="M282 178v-42q18-29 36 0v49l-10-3v-41q-8-20-16 0v40Z"
              fill="#e3d8f2"
            />
            <path d="M286 135q14-21 28 0" stroke="#f6f0fc" strokeWidth="3" />
          </g>
          {Array.from({ length: 55 }, (_, i) => {
            const u = ((i * 37) % 101) / 101,
              v = ((i * 61 + 17) % 103) / 103;
            const x = 72 + u * 130 + v * 137,
              y = 182 - u * 31 + v * 34;
            if (x > 133 && x < 250 && y > 159) return null;
            return (
              <path
                key={i}
                className="island-grass"
                data-x={x}
                data-y={y}
                data-length={10 + (i % 15)}
                fill={["#719582", "#9bb292", "#b8c7a0"][i % 3]}
              />
            );
          })}
          <path
            d="m260 183 10-144"
            stroke="#776a86"
            strokeWidth="2"
            strokeLinecap="round"
          />
          <circle cx="270" cy="39" r="2.4" fill="#776a86" />
          <path data-part="flag" fill="var(--accent)" opacity=".85" />
          <path data-part="flag-light" fill="#fff" opacity=".3" />
          <ellipse
            cx="256"
            cy="202"
            rx="20"
            ry="5"
            fill="#bbc4b6"
            opacity=".35"
          />
          <path d="m255 177 13 20-13 14-12-14Z" fill="#b6a0d6" />
          <path d="m255 177 13 20-13 14Z" fill="#e7dcf8" />
          <path d="m278 191 6 9-6 7-5-7Z" fill="#d1c0e8" />
          <path d="m110 191 9-8 10 9-7 6Z" fill="#cdc8dc" />
        </g>
        <g className="explorer-rig" transform="translate(174 199)">
          <ellipse cy="4" rx="33" ry="6" fill="#68637b" opacity=".15" />
          <g data-part="boots">
            <path d="M-22-18h17v19q-10 5-23 0-1-7 6-19Z" fill="#4c455a" />
            <path d="M5-18h17q7 11 6 19-13 5-23 0Z" fill="#4c455a" />
            <path
              d="M-27 2h21M6 2h21"
              stroke="#b6a9bc"
              strokeWidth="2"
              strokeLinecap="round"
            />
          </g>
          <g data-part="body">
            <path data-part="scarf-tail" fill="var(--accent)" />
            <path
              d="M-17-65q17-8 34 0l9 45q-8 6-22 4L0-29l-4 13q-15 2-22-4Z"
              fill={paintFill("coat")}
            />
            <path d="M-12-62q12 4 24 0l-2 17h-20Z" fill="#fff3dc" />
            <path
              d="m-15-59 2 20M15-59l-2 20"
              stroke="#a497af"
              strokeWidth="3"
              strokeLinecap="round"
            />
            <circle cx="-12" cy="-40" r="2" fill="#e8d5ad" />
            <circle cx="12" cy="-40" r="2" fill="#e8d5ad" />
            <path
              d="M-9-33H9v9q-9 7-18 0Z"
              fill="#81738e"
              stroke="#9b8ba5"
              strokeWidth=".8"
            />
            <path d="m-17-67 17 6 17-6-6 11H-11Z" fill="var(--accent)" />
            <g data-part="head">
              <ellipse cx="-30" cy="2" rx="6" ry="8" fill="#efbba2" />
              <ellipse cx="30" cy="2" rx="6" ry="8" fill="#efbba2" />
              <path
                d="M-31-11q-1-23 31-24 31 1 31 24v16q-2 26-31 27-29-1-31-27Z"
                fill={paintFill("skin")}
              />
              <path
                d="M-31-2q-9-17 1-29 7-9 21-7 12-12 24-3 16-1 21 14 4 12-4 22l-5-13q-18 5-30-9-8 14-22 14l-2 15Z"
                fill="#423d54"
              />
              <path
                d="M-24-28q12-10 27-5"
                stroke="#655a73"
                strokeWidth="3"
                strokeLinecap="round"
                opacity=".65"
              />
              <ellipse
                cx="-20"
                cy="10"
                rx="6"
                ry="3.5"
                fill="#e9a196"
                opacity=".48"
              />
              <ellipse
                cx="20"
                cy="10"
                rx="6"
                ry="3.5"
                fill="#e9a196"
                opacity=".48"
              />
              <ellipse data-part="eye-left" cx="-13" rx="3.1" fill="#3f354e" />
              <ellipse data-part="eye-right" cx="13" rx="3.1" fill="#3f354e" />
              <circle
                data-part="glint-left"
                cx="-13.8"
                r=".95"
                fill="#fff8ef"
              />
              <circle
                data-part="glint-right"
                cx="12.2"
                r=".95"
                fill="#fff8ef"
              />
              <g stroke="#635064" strokeWidth="2" strokeLinecap="round">
                <path data-part="brow-left" />
                <path data-part="brow-right" />
              </g>
              <path
                d="M-2 4q-3 5 3 5"
                stroke="#d99987"
                strokeWidth="1.8"
                strokeLinecap="round"
              />
              <path
                data-part="mouth"
                stroke="#995e68"
                strokeWidth="2.2"
                strokeLinecap="round"
              />
            </g>
          </g>
          <g data-part="free-hand">
            <path
              d="M-7 6q-4-3-3-8l1-8q1-4 4-2l1 5v-6q3-4 5 0l1 6 3-3q4-1 4 3L7 3Q6 11-2 11Z"
              fill="#f4c5a8"
            />
            <path
              d="M-6 7q5 3 10 0"
              stroke="#dfaa97"
              strokeWidth="1.2"
              strokeLinecap="round"
            />
          </g>
          <g data-part="shovel">
            <path
              d="M0-17v54"
              stroke="#a2858c"
              strokeWidth="4"
              strokeLinecap="round"
            />
            <path
              d="M-6-27H6L4-17H-4Z"
              stroke="var(--accent)"
              strokeWidth="3.5"
              strokeLinejoin="round"
            />
            <path d="M-10 29h20l2 16Q0 57-12 45Z" fill="var(--accent)" />
            <path
              d="M1 32v15"
              stroke="#ffe0cd"
              strokeWidth="2"
              strokeLinecap="round"
              opacity=".65"
            />
            <g data-part="grip">
              <path
                d="M-7-5q1-4 5-3l8 2q4 2 3 7-1 6-6 6H-3q-6-1-6-6Z"
                fill="#f4c5a8"
              />
              <path
                d="M-4-2 3 0M-4 2l6 1"
                stroke="#dfaa97"
                strokeWidth="1.1"
                strokeLinecap="round"
              />
            </g>
          </g>
          <g data-part="discovery">
            <path d="m0-14 9 11-9 14-9-14Z" fill="#b49bd8" />
            <path d="m0-14 9 11-9 14Z" fill="#e5d6f8" />
            <path
              d="M-16-14v7m-3.5-3.5h7M16-4v7m-3.5-3.5h7"
              stroke="#c4a4bb"
              strokeWidth="1.5"
              strokeLinecap="round"
            />
          </g>
        </g>
      </svg>
    </button>
  );
}
