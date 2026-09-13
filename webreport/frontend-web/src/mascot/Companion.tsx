import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type RefObject,
} from "react";
import { Expedition } from "./Expedition";
import { SpeechBubble } from "./SpeechBubble";
import type { SceneState, ShovelScene } from "./shovel-scene";
import "./companion.css";

export type CompanionKind = "shovel" | "explorer" | "none";
export type CompanionSpeech = {
  title: string;
  text: string;
  action?: { label: string; onClick: () => void; disabled?: boolean };
};

export function useCompanion() {
  const read = (): CompanionKind => {
    try {
      const value = localStorage.getItem("wr-companion");
      return value === "explorer" || value === "none" ? value : "shovel";
    } catch {
      return "shovel";
    }
  };
  const [kind, setKind] = useState<CompanionKind>(read);
  useEffect(() => {
    try {
      localStorage.setItem("wr-companion", kind);
    } catch {
      /* Storage may be disabled. */
    }
  }, [kind]);
  useEffect(() => {
    const sync = (event: StorageEvent) => {
      if (event.key === "wr-companion") setKind(read());
    };
    window.addEventListener("storage", sync);
    return () => window.removeEventListener("storage", sync);
  }, []);
  return [kind, setKind] as const;
}

export function Shovel({
  activity,
  motion,
  accent,
  engaged = false,
  enabled = true,
  speech,
}: Omit<SceneState, "visible"> & { enabled?: boolean }) {
  const root = useRef<HTMLDivElement>(null),
    canvas = useRef<HTMLCanvasElement>(null);
  const scene = useRef<ShovelScene | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "fallback">(
    "loading",
  );
  const [attempt, setAttempt] = useState(0),
    [visible, setVisible] = useState(true);
  const current = useRef<SceneState>({
    activity,
    motion,
    accent,
    engaged,
    speech,
    visible,
  });
  current.current = {
    activity,
    motion,
    accent,
    engaged,
    speech,
    visible: visible && enabled,
  };
  useEffect(() => {
    const observer = new IntersectionObserver(([entry]) =>
      setVisible(entry.isIntersecting),
    );
    if (root.current) observer.observe(root.current);
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    let cancelled = false;
    const target = canvas.current;
    setStatus("loading");
    const fallback = () => {
      if (!cancelled) setStatus("fallback");
    };
    // The Three.js bundle is requested only when the shovel is actually selected.
    void import("./shovel-scene")
      .then(async ({ createShovelScene, loadShovelAssets }) => {
        if (cancelled || !target) return;
        const assets = await loadShovelAssets();
        if (cancelled) {
          assets.mouths.dispose();
          assets.island.dispose();
          return;
        }
        try {
          scene.current = createShovelScene(
            target,
            current.current,
            fallback,
            assets,
          );
        } catch (error) {
          assets.mouths.dispose();
          assets.island.dispose();
          throw error;
        }
        setStatus("ready");
      })
      .catch(fallback);
    return () => {
      cancelled = true;
      // React effect replay / HMR can reuse the same canvas. Dispose its GPU
      // resources, but only lose the context when that DOM canvas is retired.
      scene.current?.dispose(canvas.current !== target);
      scene.current = null;
    };
  }, [attempt]);
  useEffect(() => {
    scene.current?.update(current.current);
  }, [activity, motion, accent, engaged, visible, enabled, speech]);
  useEffect(() => {
    if (status === "fallback") {
      scene.current?.dispose();
      scene.current = null;
    }
  }, [status]);
  return (
    <div className="shovel-companion" ref={root} data-status={status}>
      {status !== "ready" && (
        <img
          className="shovel-fallback"
          src="/mascot/shovel-concept.png"
          alt="Улыбающаяся лопата с глазами на летающем островке"
        />
      )}
      <canvas
        key={attempt}
        ref={canvas}
        tabIndex={status === "ready" ? 0 : -1}
        aria-hidden={status !== "ready"}
        aria-label="Лопата-помощник"
        className={status === "ready" ? "" : "shovel-loading"}
      />
      {status === "fallback" && (
        <button
          className="companion-retry"
          onClick={() => setAttempt((value) => value + 1)}
          title="Объёмная сцена недоступна. Показана иллюстрация."
        >
          Повторить запуск 3D
        </button>
      )}
    </div>
  );
}

// One mounted scene travels between two layout anchors, preserving its camera and animation.
export function CompanionStage({
  kind,
  compact,
  active = true,
  heroAnchor,
  dockAnchor,
  activity,
  motion,
  accent,
  engaged,
  speech,
}: {
  active?: boolean;
  kind: CompanionKind;
  compact: boolean;
  heroAnchor: RefObject<HTMLDivElement | null>;
  dockAnchor: RefObject<HTMLDivElement | null>;
  speech?: CompanionSpeech;
} & Omit<SceneState, "visible" | "speech">) {
  const root = useRef<HTMLDivElement>(null);
  const lastMode = useRef(compact);
  const [travel, setTravel] = useState(false);
  const [box, setBox] = useState<{
    x: number;
    y: number;
    width: number;
    height: number;
    visible: boolean;
  }>();
  useLayoutEffect(() => {
    const stage = root.current,
      anchor = compact ? dockAnchor.current : heroAnchor.current;
    const parent = stage?.parentElement;
    if (!stage || !anchor || !parent || !active) {
      setBox((previous) =>
        previous ? { ...previous, visible: false } : undefined,
      );
      return;
    }
    if (lastMode.current !== compact) {
      setTravel(true);
      lastMode.current = compact;
    }
    let frame = 0;
    const measure = () => {
      frame = 0;
      const a = anchor.getBoundingClientRect(),
        p = parent.getBoundingClientRect();
      const next = {
        x: a.left - p.left,
        y: a.top - p.top,
        width: a.width,
        height: a.height,
        visible: a.bottom > p.top + 65 && a.top < p.bottom && a.width > 0,
      };
      setBox((before) =>
        before &&
        Object.keys(next).every(
          (key) =>
            before[key as keyof typeof next] === next[key as keyof typeof next],
        )
          ? before
          : next,
      );
    };
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(measure);
    };
    const observer = new ResizeObserver(schedule);
    observer.observe(anchor);
    observer.observe(parent);
    parent
      .querySelectorAll(
        ".conversation-scroll, .composer-dock, .conversation, .welcome",
      )
      .forEach((el) => observer.observe(el));
    window.addEventListener("resize", schedule);
    document.addEventListener("scroll", schedule, true);
    parent.addEventListener("animationend", schedule);
    measure();
    const timer = setTimeout(() => {
      setTravel(false);
      schedule();
    }, 750);
    return () => {
      clearTimeout(timer);
      cancelAnimationFrame(frame);
      observer.disconnect();
      window.removeEventListener("resize", schedule);
      document.removeEventListener("scroll", schedule, true);
      parent.removeEventListener("animationend", schedule);
    };
  }, [kind, compact, active, heroAnchor, dockAnchor]);
  if (kind === "none") return null;
  return (
    <div
      ref={root}
      className={"companion-stage " + (compact ? "is-compact" : "is-hero")}
      data-travel={travel && motion}
      style={{
        transform: `translate(${box?.x || 0}px, ${box?.y || 0}px)`,
        width: box?.width || 1,
        height: box?.height || 1,
        visibility: box?.visible ? "visible" : "hidden",
      }}
    >
      {kind === "shovel" ? (
        <Shovel
          activity={activity}
          motion={motion}
          accent={accent}
          engaged={engaged}
          speech={speech ? speech.title + " " + speech.text : undefined}
          enabled={!!box?.visible && active}
        />
      ) : (
        <Expedition activity={activity} motion={motion} compact={compact} />
      )}
      {speech && (
        <SpeechBubble>
          <strong>{speech.title}</strong>
          <p>{speech.text}</p>
          {speech.action && (
            <button
              className="companion-speech-action"
              onClick={speech.action.onClick}
              disabled={speech.action.disabled}
            >
              {speech.action.label}
              <span aria-hidden="true"> →</span>
            </button>
          )}
        </SpeechBubble>
      )}
    </div>
  );
}
