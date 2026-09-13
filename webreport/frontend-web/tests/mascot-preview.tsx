import { useState } from "react";
import { createRoot } from "react-dom/client";
import { Expedition } from "../src/mascot/Expedition";
import type { Action } from "../src/mascot/rig";
import { applyAccent, defaultAccent } from "../src/theme";
import "../src/styles.css";
import "../src/expedition.css";

applyAccent(defaultAccent);
function Preview() {
  const [pose, setPose] = useState<Action>("idle"),
    [motion, setMotion] = useState(true);
  const names: Record<Action, string> = {
    idle: "Стоять",
    work: "За работой",
    think: "Задуматься",
    wave: "Помахать",
    found: "Находка",
    puzzled: "Вопрос",
  };
  return (
    <main style={{ maxWidth: 880, margin: "40px auto", padding: 24 }}>
      <h1>Эмоции исследователя</h1>
      <div
        style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBlock: 24 }}
      >
        {Object.entries(names).map(([value, label]) => (
          <button
            className="secondary-button"
            aria-pressed={pose === value}
            key={value}
            onClick={() => setPose(value as Action)}
          >
            {label}
          </button>
        ))}
      </div>
      <label>
        <input
          type="checkbox"
          checked={motion}
          onChange={(e) => setMotion(e.target.checked)}
        />{" "}
        Анимация
      </label>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-around",
          minHeight: 350,
        }}
      >
        <Expedition activity="welcome" pose={pose} motion={motion} />
        <Expedition activity="welcome" pose={pose} motion={motion} compact />
      </div>
    </main>
  );
}
createRoot(document.getElementById("root")!).render(<Preview />);
