import { useLayoutEffect, useRef, useState } from "react";

/** A rounded surface only: the control, text and hit area stay rectangular. */
export function Trapezoid({
  radius = 12,
  bottomWide = false,
  slope = 3,
  className = "",
}: {
  radius?: number;
  bottomWide?: boolean;
  slope?: number;
  className?: string;
}) {
  const ref = useRef<SVGSVGElement>(null);
  const [size, setSize] = useState([100, 40]);
  useLayoutEffect(() => {
    const svg = ref.current;
    if (!svg) return;
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      if (width && height) setSize([width, height]);
    });
    observer.observe(svg);
    return () => observer.disconnect();
  }, []);
  const [w, h] = size;
  // Angle from vertical; keep expanded surfaces from tapering too far.
  const inset = Math.min((h - 2) * Math.tan((slope * Math.PI) / 180), 11);
  const top = bottomWide ? inset : 0;
  const bottom = bottomWide ? 0 : inset;
  const vertices = [
    [1 + top, 1.4],
    [w - 1 - top, 1],
    [w - 1 - bottom, h - 1.4],
    [1 + bottom, h - 1],
  ];
  const corners = vertices.map((point, index) => {
    const adjacent = [vertices[(index + 3) % 4], vertices[(index + 1) % 4]];
    const ends = adjacent.map((other) => {
      const length = Math.hypot(other[0] - point[0], other[1] - point[1]);
      const offset = Math.min(radius, length / 3);
      return point.map((v, axis) => v + ((other[axis] - v) * offset) / length);
    });
    return { point, ends };
  });
  const path =
    corners
      .map(
        ({ point, ends }, i) =>
          `${i ? "L" : "M"}${ends[0].join(",")} Q${point.join(",")} ${ends[1].join(",")}`,
      )
      .join(" ") + " Z";
  return (
    <svg
      ref={ref}
      className={`trapezoid ${className}`}
      viewBox={`0 0 ${w} ${h}`}
      preserveAspectRatio="none"
      aria-hidden="true"
      focusable="false"
    >
      <path d={path} />
    </svg>
  );
}
