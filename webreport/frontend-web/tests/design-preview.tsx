// Visual fixture for the reading layout; no backend or model requests.
import { useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { Atmosphere } from "../src/Atmosphere";
import { Composer } from "../src/Composer";
import { MessageView } from "../src/Conversation";
import { Sidebar } from "../src/Sidebar";
import { Shovel } from "../src/mascot/Companion";
import { applyAccent, defaultAccent } from "../src/theme";
import type { Chat, Model, Project, Source } from "../src/types";
import { edgeVisualAnswer, visualAnswer } from "./visual-answer-fixture";
import "../src/styles.css";
import "../src/expedition.css";

const noop = () => {};
const reading = new URLSearchParams(location.search).has("reading");
const projects = [
  { id: "demo", name: "Демо-проект" },
  ...(reading ? [{ id: "product", name: "Продуктовая аналитика" }] : []),
] as Project[];
const chats = [
  { id: "chat", project_id: "demo", name: "Посещаемость за неделю" },
  ...(reading ? [
    { id: "channels", project_id: "demo", name: "Откуда приходят посетители" },
    { id: "retention", project_id: "demo", name: "Возвращаемость и новые пользователи" },
    { id: "funnel", project_id: "product", name: "Воронка регистрации" },
    { id: "cohorts", project_id: "product", name: "Сравнение недельных когорт" },
  ] : []),
] as Chat[];
const readingAnswer = `За неделю сайт посетили **14 555 человек**, которые совершили **22 699 визитов**. В среднем это 1,56 визита на посетителя. Основную часть аудитории привёл поиск, а рекламные кампании дали чуть меньше трети всего трафика.

## Что изменилось за неделю

Рост распределён неравномерно: поисковый трафик увеличился, а прямых заходов стало немного меньше. Чтобы понять причину, стоит сравнить качество этих посещений, а не только их количество.

- **Поиск:** 8 420 посетителей, рост на 12,4%.
- **Реклама:** 4 180 посетителей, рост на 8,1%.
- **Прямые заходы:** 1 955 посетителей, снижение на 2,3%.

### Что проверить дальше

1. Сравнить конверсию по источникам за одинаковые дни недели.
2. Разделить аудиторию на новых и вернувшихся посетителей.
   - Посмотреть, какие страницы приводят к повторному визиту.
   - Проверить мобильные устройства отдельно.
3. Сопоставить расходы на рекламу с количеством целевых действий.

> Изменение посещаемости само по себе ещё не объясняет изменение продаж. Для вывода нужны данные о целевых действиях.

Если конверсия остаётся стабильной, следующий шаг — проверить, какие страницы дали прирост. Если она падает, полезнее сначала разобрать путь посетителя до целевого действия.`;
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
                content: reading ? readingAnswer : new URLSearchParams(location.search).has("visuals")
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
            <div className="companion-anchor compact">
              <Shovel activity="rest" motion={motion} accent={defaultAccent} />
            </div>
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
