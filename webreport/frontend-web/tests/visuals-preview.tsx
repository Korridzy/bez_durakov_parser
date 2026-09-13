import { createRoot } from "react-dom/client";
import { MessageView } from "../src/Conversation";
import { applyAccent, defaultAccent } from "../src/theme";
import { visualAnswer, edgeVisualAnswer } from "./visual-answer-fixture";
import "../src/styles.css";
import "../src/expedition.css";

applyAccent(defaultAccent);
createRoot(document.getElementById("root")!).render(
  <main className="conversation">
    <p style={{ color: "var(--subtle)", fontSize: 12 }}>
      Dig AI · Графики и показатели в ответах · Синтетические данные
    </p>
    <MessageView
      onRetry={() => {}}
      message={{
        id: "visual-preview",
        role: "assistant",
        model: "Демо-модель",
        content: new URLSearchParams(location.search).has("edges")
          ? edgeVisualAnswer
          : visualAnswer,
      }}
    />
  </main>,
);
