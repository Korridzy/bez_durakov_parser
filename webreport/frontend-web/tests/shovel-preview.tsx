// Offline visual fixture. It never calls the workspace API or a model provider.
import { useState } from "react";
import { createRoot } from "react-dom/client";
import { Shovel } from "../src/mascot/Companion";
import { SpeechBubble } from "../src/mascot/SpeechBubble";
import type { Activity } from "../src/mascot/Expedition";
import "../src/styles.css";
import "../src/expedition.css";

if (new URLSearchParams(location.search).has("fallback")) {
  const original = HTMLCanvasElement.prototype.getContext;
  // Simulate one failed WebGL startup, then let the visible retry button recover.
  HTMLCanvasElement.prototype.getContext = function (
    ...args: Parameters<typeof original>
  ) {
    if (String(args[0]).startsWith("webgl")) {
      HTMLCanvasElement.prototype.getContext = original;
      throw new Error("Offline fixture: WebGL unavailable on first attempt");
    }
    return original.apply(this, args);
  } as typeof original;
}
function Preview() {
  const [activity, setActivity] = useState<Activity>("welcome"),
    [motion, setMotion] = useState(true),
    [compact, setCompact] = useState(false);
  return (
    <main
      style={{
        minHeight: "100dvh",
        display: "grid",
        justifyItems: "center",
        alignContent: "center",
        gap: 18,
        containerType: "inline-size",
        background: "radial-gradient(ellipse at 35% 30%, #e9e0f3, #fcf9f8 70%)",
      }}
    >
      <div
        className={compact ? "is-compact" : "is-hero"}
        style={{
          position: "relative",
          width: compact ? 254 : "min(410px, 92vw)",
          height: compact ? 220 : "min(330px, 50vh)",
          marginTop: 150,
        }}
      >
        <Shovel
          activity={activity}
          motion={motion}
          accent="#ed786b"
          engaged={activity === "thinking"}
        />
        <SpeechBubble>
          <strong>
            {activity === "working"
              ? "Копаю…"
              : activity === "thinking"
                ? "Так-так…"
                : "Хей!"}
          </strong>
          <p>
            {activity === "working"
              ? "Сейчас найду самое интересное."
              : activity === "thinking"
                ? "Сейчас разберусь."
                : "Какие вопросы по проекту?"}
          </p>
        </SpeechBubble>
      </div>
      <div
        style={{
          display: "flex",
          gap: 8,
          flexWrap: "wrap",
          justifyContent: "center",
        }}
      >
        {(
          [
            ["welcome", "Приветствие"],
            ["thinking", "Думает"],
            ["working", "Копает"],
            ["success", "Готово"],
            ["error", "Ошибка"],
          ] as const
        ).map(([value, label]) => (
          <button
            className="secondary-button"
            key={value}
            aria-pressed={activity === value}
            onClick={() => setActivity(value)}
          >
            {label}
          </button>
        ))}
      </div>
      <label>
        <input
          type="checkbox"
          checked={motion}
          onChange={(event) => setMotion(event.target.checked)}
        />{" "}
        Анимация
      </label>
      <label>
        <input
          type="checkbox"
          checked={compact}
          onChange={(event) => setCompact(event.target.checked)}
        />{" "}
        Компактный вид
      </label>
    </main>
  );
}
createRoot(document.getElementById("root")!).render(<Preview />);
