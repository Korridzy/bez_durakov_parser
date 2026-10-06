import { usePrefersReducedMotion } from "../motion/usePrefersReducedMotion";

export type ThinkingPhase = "thinking" | "reading" | "cancelling";

export const THINKING_PHASE_TEXT: Record<ThinkingPhase, string> = {
  thinking: "Думаю…",
  reading: "Читаю данные…",
  cancelling: "Отменяю…",
};

interface ThinkingMarkProps {
  phase: ThinkingPhase;
}

/**
 * Abstract status mark for an active run: a trio of concentric arcs drawn in
 * currentColor, animated by CSS keyframes only. When the user prefers reduced
 * motion the `is-animated` class is left off and the same arcs stay static;
 * the status text is identical in both cases.
 */
export function ThinkingMark({ phase }: ThinkingMarkProps) {
  const reducedMotion = usePrefersReducedMotion();
  const markClass = reducedMotion ? "thinking-mark" : "thinking-mark is-animated";

  return (
    <div className="thinking" role="status" aria-live="polite">
      <svg
        className={markClass}
        viewBox="0 0 28 28"
        width="28"
        height="28"
        aria-hidden="true"
        focusable="false"
      >
        <circle
          className="thinking-mark__arc thinking-mark__arc--outer"
          cx="14"
          cy="14"
          r="12"
          pathLength="100"
        />
        <circle
          className="thinking-mark__arc thinking-mark__arc--middle"
          cx="14"
          cy="14"
          r="8"
          pathLength="100"
        />
        <circle
          className="thinking-mark__arc thinking-mark__arc--inner"
          cx="14"
          cy="14"
          r="4"
          pathLength="100"
        />
      </svg>
      <span className="thinking__text">{THINKING_PHASE_TEXT[phase]}</span>
    </div>
  );
}

export default ThinkingMark;
