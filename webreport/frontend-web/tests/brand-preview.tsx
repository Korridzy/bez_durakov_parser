// Local design tool: no workspace API, model requests or saved user settings.
import { useRef, useState, type PointerEvent } from "react";
import { createRoot } from "react-dom/client";
import { BrandMark, brandLayout } from "../src/BrandMark";
import "../src/styles.css";
import "../src/expedition.css";
import "./brand-preview.css";

function Preview() {
  const [layout, setLayout] = useState(brandLayout);
  const [selected, setSelected] = useState("sparkle-large");
  const [copied, setCopied] = useState("");
  const drag = useRef<{
    id: number;
    x: number;
    y: number;
    left: number;
    top: number;
    scale: number;
  } | null>(null);
  const layer = layout.layers.find((item) => item.id === selected)!;
  const change = (values: Partial<typeof layer>) => {
    setCopied("");
    setLayout((before) => ({
      ...before,
      layers: before.layers.map((item) =>
        item.id === selected ? { ...item, ...values } : item,
      ),
    }));
  };
  const down = (event: PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    event.preventDefault();
    const bounds = event.currentTarget.getBoundingClientRect();
    drag.current = {
      id: event.pointerId,
      x: event.clientX,
      y: event.clientY,
      left: layer.x,
      top: layer.y,
      scale: layout.canvas / bounds.width,
    };
    event.currentTarget.setPointerCapture(event.pointerId);
  };
  const move = (event: PointerEvent<HTMLDivElement>) => {
    const start = drag.current;
    if (!start || start.id !== event.pointerId) return;
    const bound = (value: number) =>
      Math.max(-500, Math.min(1000, Math.round(value)));
    change({
      x: bound(start.left + (event.clientX - start.x) * start.scale),
      y: bound(start.top + (event.clientY - start.y) * start.scale),
    });
  };
  const end = (event: PointerEvent<HTMLDivElement>) => {
    if (drag.current?.id === event.pointerId) drag.current = null;
    if (event.currentTarget.hasPointerCapture(event.pointerId))
      event.currentTarget.releasePointerCapture(event.pointerId);
  };
  return (
    <main className="brand-workbench">
      <header>
        <h1>Расположение значка</h1>
        <p>
          Выбери элемент и двигай его на макете. Положение и размер можно задать
          числами.
        </p>
      </header>
      <section className="brand-workbench-grid">
        <div>
          <div
            className="brand-workbench-canvas"
            onPointerDown={down}
            onPointerMove={move}
            onPointerUp={end}
            onPointerCancel={end}
            onLostPointerCapture={() => {
              drag.current = null;
            }}
          >
            <BrandMark layout={layout} />
          </div>
          <div className="brand-workbench-sample">
            <span style={{ width: 35, height: 35 }}>
              <BrandMark layout={layout} />
            </span>
            <strong>Dig AI</strong>
            <span>В размере сайта</span>
          </div>
        </div>
        <div className="brand-workbench-controls">
          <fieldset>
            <legend>Элемент</legend>
            {layout.layers.map((item) => (
              <label key={item.id}>
                <input
                  type="radio"
                  name="layer"
                  checked={selected === item.id}
                  onChange={() => setSelected(item.id)}
                />
                {item.label}
              </label>
            ))}
          </fieldset>
          {(
            [
              ["x", "По горизонтали"],
              ["y", "По вертикали"],
              ["size", "Размер"],
            ] as const
          ).map(([key, label]) => (
            <label className="brand-workbench-number" key={key}>
              {label}
              <input
                type="number"
                value={layer[key]}
                min={key === "size" ? 40 : -500}
                max={key === "size" ? 1500 : 1000}
                onChange={(event) => {
                  const value = event.target.valueAsNumber;
                  if (Number.isFinite(value)) change({ [key]: value });
                }}
              />
            </label>
          ))}
          <button
            className="secondary-button"
            onClick={() => {
              setLayout(brandLayout);
              setCopied("");
            }}
          >
            Вернуть исходное положение
          </button>
          <button
            className="primary-button"
            onClick={async () => {
              try {
                await navigator.clipboard.writeText(
                  JSON.stringify(layout, null, 2),
                );
                setCopied("Расположение скопировано");
              } catch {
                setCopied("Не удалось скопировать расположение");
              }
            }}
          >
            Скопировать расположение
          </button>
          <p role="status">
            {copied ||
              "Это макет. Изменения на сайт переносим из скопированного расположения."}
          </p>
        </div>
      </section>
    </main>
  );
}
const root = createRoot(document.getElementById("root")!);
root.render(<Preview />);
if (import.meta.hot) import.meta.hot.dispose(() => root.unmount());
