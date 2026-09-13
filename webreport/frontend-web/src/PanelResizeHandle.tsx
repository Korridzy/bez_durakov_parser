import { useEffect, useState, type HTMLAttributes } from "react";
import "./panel-resize.css";

export function usePanelResize({
  storageKey,
  minWidth,
  maxWidth,
  defaultWidth,
  edge,
  disabled = false,
}: {
  storageKey: string;
  minWidth: number;
  maxWidth: number;
  defaultWidth: () => number;
  edge: "left" | "right";
  disabled?: boolean;
}) {
  const [preferredWidth, setPreferredWidth] = useState(() => {
    try {
      const saved = Number(localStorage.getItem(storageKey));
      if (Number.isFinite(saved) && saved >= minWidth) return saved;
    } catch {}
    return defaultWidth();
  });
  const [drag, setDrag] = useState<{
    id: number;
    x: number;
    width: number;
  } | null>(null);
  const resizing = drag !== null;
  const width = Math.min(maxWidth, Math.max(minWidth, preferredWidth));
  const resize = (next: number) =>
    setPreferredWidth(Math.round(Math.min(maxWidth, Math.max(minWidth, next))));
  const direction = edge === "right" ? 1 : -1;

  useEffect(() => {
    if (disabled) setDrag(null);
  }, [disabled]);

  useEffect(() => {
    if (!resizing) return;
    const { cursor, userSelect } = document.body.style;
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    const stop = () => setDrag(null);
    window.addEventListener("blur", stop);
    return () => {
      document.body.style.cursor = cursor;
      document.body.style.userSelect = userSelect;
      window.removeEventListener("blur", stop);
    };
  }, [resizing]);

  useEffect(() => {
    if (resizing) return;
    try {
      localStorage.setItem(storageKey, String(preferredWidth));
    } catch {}
  }, [storageKey, preferredWidth, resizing]);

  const handleProps: HTMLAttributes<HTMLDivElement> = {
    className: `panel-resize-handle edge-${edge}${resizing ? " is-resizing" : ""}`,
    role: "separator",
    tabIndex: 0,
    "aria-orientation": "vertical",
    "aria-valuemin": minWidth,
    "aria-valuemax": maxWidth,
    "aria-valuenow": Math.round(width),
    "aria-valuetext": `${Math.round(width)} пикселей`,
    title: "Потяните, чтобы изменить ширину. Двойной щелчок — исходная ширина",
    onPointerDown: (e) => {
      if (disabled || e.button !== 0 || !e.isPrimary) return;
      e.preventDefault();
      e.currentTarget.focus();
      e.currentTarget.setPointerCapture(e.pointerId);
      setDrag({ id: e.pointerId, x: e.clientX, width });
    },
    onPointerMove: (e) => {
      if (drag?.id === e.pointerId)
        resize(drag.width + direction * (e.clientX - drag.x));
    },
    onPointerUp: (e) => {
      if (drag?.id !== e.pointerId) return;
      resize(drag.width + direction * (e.clientX - drag.x));
      setDrag(null);
      if (e.currentTarget.hasPointerCapture(e.pointerId))
        e.currentTarget.releasePointerCapture(e.pointerId);
    },
    onPointerCancel: () => setDrag(null),
    onLostPointerCapture: () => setDrag(null),
    onDoubleClick: () => resize(defaultWidth()),
    onKeyDown: (e) => {
      const step = (e.shiftKey ? 64 : 24) * direction;
      const next: Record<string, number> = {
        ArrowLeft: width - step,
        ArrowRight: width + step,
        Home: minWidth,
        End: maxWidth,
      };
      if (next[e.key] === undefined || disabled) return;
      e.preventDefault();
      resize(next[e.key]);
    },
  };
  return { width, resizing, disabled, handleProps };
}

export function PanelResizeHandle({
  resize,
  label,
  controls,
}: {
  resize: ReturnType<typeof usePanelResize>;
  label: string;
  controls: string;
}) {
  return resize.disabled ? null : (
    <div {...resize.handleProps} aria-label={label} aria-controls={controls} />
  );
}
