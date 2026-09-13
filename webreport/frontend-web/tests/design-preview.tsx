// Visual fixture for the reading layout; no backend or model requests.
import { useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { Atmosphere } from "../src/Atmosphere";
import { Composer } from "../src/Composer";
import { MessageView } from "../src/Conversation";
import { Sidebar } from "../src/Sidebar";
import { Expedition } from "../src/mascot/Expedition";
import { applyAccent, defaultAccent } from "../src/theme";
import type { Chat, Model, Project, Source } from "../src/types";
import { edgeVisualAnswer, visualAnswer } from "./visual-answer-fixture";
import "../src/styles.css";
import "../src/expedition.css";

const noop = () => {};
const projects = [{ id: "demo", name: "Демо-проект" }] as Project[];
const chats = [
  { id: "chat", project_id: "demo", name: "Посещаемость за неделю" },
] as Chat[];
const sources = [
  {
    id: "source",
    provider: "yandex_metrika",
    name: "Яндекс Метрика",
    connected: true,
  },
] as Source[];
const models = [
  {
    id: "model",
    name: "Демо-модель",
    connected: true,
    efforts: ["auto", "high"],
  },
] as Model[];

function Preview() {
  const [value, setValue] = useState("");
  const [motion, setMotion] = useState(true);
  const [sidebar, setSidebar] = useState(window.innerWidth > 700);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  return (
    <div
      className={`app ${sidebar ? "" : "sidebar-hidden"}`}
      data-motion={motion}
    >
      <div className="sidebar-shell">
        <Sidebar
          visible={sidebar}
          projects={projects}
          chats={chats}
          projectId="demo"
          chatId="chat"
          onProject={noop}
          onChat={noop}
          onNewChat={noop}
          onNewProject={noop}
          onSettings={noop}
          onClose={() => setSidebar(false)}
          onRename={noop}
          onDelete={noop}
          activeChatIds={[]}
        />
      </div>
      <main className="main-panel reading-expedition">
        <Atmosphere />
        <header className="workspace-header">
          <label>
            <input
              type="checkbox"
              checked={motion}
              onChange={(e) => setMotion(e.target.checked)}
            />{" "}
            Движение
          </label>
        </header>
        <div className="conversation-scroll">
          <div className="conversation">
            <div className="message user-message">
              <div>Сколько посетителей было за неделю?</div>
            </div>
            <MessageView
              onRetry={noop}
              message={{
                id: "table-preview",
                role: "assistant",
                content: new URLSearchParams(location.search).has("visuals")
                  ? visualAnswer
                  : new URLSearchParams(location.search).has("visual-edges")
                  ? edgeVisualAnswer
                  : new URLSearchParams(location.search).has("wide")
                  ? "### Подробности по источникам\n\n| Источник | Посетители | Визиты | Просмотры | Отказы | Глубина | Время | Конверсия | Цели | Изменение |\n|:--|--:|--:|--:|--:|--:|--:|--:|--:|--:|\n| Поиск | 8 420 | 10 265 | 22 350 | 18,4% | 2,18 | 02:45 | 3,8% | 320 | +12,4% |\n| Реклама | 4 180 | 4 890 | 9 510 | 23,1% | 1,94 | 01:52 | 2,9% | 121 | +8,1% |"
                  : "За выбранный период сайт посетили **14 555 человек**. Основной источник — поиск.\n\n| Источник | Посетители | Доля | Изменение |\n|:--|--:|--:|--:|\n| Поиск | 8 420 | 57,8% | +12,4% |\n| Реклама | 4 180 | 28,7% | +8,1% |\n| Прямые заходы | 1 955 | 13,4% | −2,3% |\n\n### Что стоит проверить\n\n| Наблюдение | Следующий шаг |\n|:--|:--|\n| **Растёт органический трафик** | Сравнить посадочные страницы и проверить, сохраняется ли рост конверсии у новых посетителей. |\n| Реклама приводит меньше посетителей | Посмотреть стоимость привлечения и качество трафика по кампаниям. |",
                data: [
                  { Источник: "Поиск", Посетители: 8420, Визиты: 10265 },
                  { Источник: "Реклама", Посетители: 4180, Визиты: 4890 },
                ],
                model: "Демо-модель · синтетические данные",
              }}
            />
          </div>
        </div>
        <div className="composer-dock">
          <div className="companion-slot">
            <Expedition activity="rest" compact motion={motion} />
          </div>
          <Composer
            sources={sources}
            hasDataset={false}
            hasProjectInfo={false}
            onProjectInfo={noop}
            interview={false}
            onEndInterview={noop}
            highlight={0}
            onSource={noop}
            onManageSources={noop}
            value={value}
            onChange={setValue}
            onSend={() => setValue("")}
            onCancel={noop}
            running={false}
            disabled={false}
            models={models}
            modelId="model"
            onModel={noop}
            effort="high"
            onEffort={noop}
            onAddModel={noop}
            onAddSource={noop}
            inputRef={inputRef}
          />
        </div>
      </main>
    </div>
  );
}
applyAccent(defaultAccent);
createRoot(document.getElementById("root")!).render(<Preview />);
