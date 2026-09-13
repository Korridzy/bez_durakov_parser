import {
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

// The tail belongs to the same closed path as the body, so neither the outline,
// gradient nor shadow has a seam where the two meet. CSS chooses its direction.
export function SpeechBubble({ children }: { children: ReactNode }) {
  const root = useRef<HTMLDivElement>(null);
  const gradient = useId();
  const [size, setSize] = useState({ width: 252, height: 110 });
  useLayoutEffect(() => {
    const element = root.current;
    if (!element) return;
    const measure = () => {
      const width = element.offsetWidth,
        height = element.offsetHeight;
      setSize((previous) =>
        previous.width === width && previous.height === height
          ? previous
          : { width, height },
      );
    };
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    measure();
    return () => observer.disconnect();
  }, []);
  const w = size.width,
    h = size.height;
  const y = Math.max(30, Math.min(h - 32, h * 0.55));
  const x = w * 0.54;
  const top = `M 21 1 H ${w - 17} Q ${w - 1} 1 ${w - 1} 17`;
  const lowerRight = `V ${h - 21} Q ${w - 1} ${h - 1} ${w - 21} ${h - 1}`;
  const left = `H 14 Q 1 ${h - 1} 1 ${h - 14} V 21 Q 1 1 21 1 Z`;
  const rightTail = `${top} V ${y - 12}
    Q ${w - 1} ${y - 7} ${w + 5} ${y - 1}
    L ${w + 21} ${y + 14} Q ${w + 24} ${y + 18} ${w + 19} ${y + 16}
    L ${w - 1} ${y + 10} ${lowerRight} ${left}`;
  const bottomTail = `${top} ${lowerRight} H ${x + 12}
    L ${x + 18} ${h + 18} Q ${x + 19} ${h + 22} ${x + 15} ${h + 19}
    L ${x - 12} ${h - 1} ${left}`;
  return (
    <div
      ref={root}
      className="companion-speech"
      role="status"
      aria-live="polite"
    >
      <svg
        className="companion-speech-shape"
        viewBox={`0 0 ${w} ${h}`}
        aria-hidden="true"
      >
        <defs>
          <linearGradient id={gradient} x1="0" y1="0" x2="1" y2="1">
            <stop offset="5%" stopColor="#ffffff" />
            <stop offset="75%" stopColor="#fcf5ff" />
            <stop offset="100%" stopColor="#f1ddfc" />
          </linearGradient>
        </defs>
        <g
          fill={`url(#${gradient})`}
          stroke="#c6a3dc"
          strokeWidth="1"
          strokeLinejoin="round"
        >
          <path className="speech-tail-right" d={rightTail} />
          <path className="speech-tail-bottom" d={bottomTail} />
        </g>
      </svg>
      <div className="companion-speech-content">{children}</div>
    </div>
  );
}
