// Dev-only fixture. No credentials, external calls or real analytics data.
import { createRoot } from "react-dom/client";
import App from "../src/App";
import { applyAccent, defaultAccent } from "../src/theme";
import { visualAnswer } from "./visual-answer-fixture";
import { analysisFixture, analysisId } from "./analysis-fixture";
import "../src/styles.css";
import "../src/expedition.css";

const project = { id: "demo-project", name: "Демо-проект" };
const chats: any[] = [];
const models = [
  {
    id: "system",
    name: "GPT-5.6 Luna",
    provider: "test",
    model_id: "test",
    connected: true,
    system: true,
    efforts: ["auto", "low", "medium", "high"],
  },
];
const catalog = [
  {
    id: "gpt-5.6-terra",
    name: "GPT-5.6 Terra",
    recommendation: "Баланс качества и стоимости",
  },
  {
    id: "gpt-6-astra",
    name: "GPT-6 Astra",
    recommendation: "Для самых сложных задач",
  },
  {
    id: "gpt-5.6-luna",
    name: "GPT-5.6 Luna",
    recommendation: "Быстрые и недорогие ответы",
  },
  {
    id: "gpt-5.6-sol",
    name: "GPT-5.6 Sol",
    recommendation: "Для сложной профессиональной работы",
  },
  ...Array.from({ length: 63 }, (_, i) => ({
    id: `model-${i}`,
    name: `Модель ${i}`,
  })),
];
let running: {
  id: string;
  chat_id: string;
  at: number;
  cancelled?: boolean;
} | null = null;
const workspace = () => ({
  csrf_token: "offline-test",
  projects: [project],
  chats,
  sources: [],
  providers: [],
  models,
  model_providers: [
    { id: "openai", name: "OpenAI", base_url: "" },
    { id: "openrouter", name: "OpenRouter", base_url: "" },
    { id: "deepseek", name: "DeepSeek", base_url: "" },
    { id: "google", name: "Google Gemini", base_url: "" },
    { id: "custom", name: "Совместимый API", base_url: "" },
  ],
  default_period: { date1: "2026-09-01", date2: "2026-09-12" },
  active_jobs: running ? [running] : [],
});
window.fetch = async (input, options) => {
  const path = String(input).replace(/^.*\/api/, ""),
    body = options?.body ? JSON.parse(String(options.body)) : {};
  let data: unknown;
  if (path === "/workspace") data = workspace();
  else if (path === "/model-connections/discover") {
    if (body.token === "rejected")
      return new Response(
        JSON.stringify({
          detail: "Нет доступа. Проверьте ключ и права на проект.",
        }),
        { status: 401 },
      );
    data = { models: body.provider === "openai" ? catalog : catalog.slice(4) };
  } else if (path === "/model-connections") {
    const chosen = catalog.find((model) => model.id === body.model_id)!;
    const model = {
      id: `demo-model-${models.length}`,
      name: chosen.name,
      model_id: chosen.id,
      provider: body.provider,
      connected: true,
      system: false,
      efforts: ["auto", "low", "medium", "high"],
    };
    models.push(model);
    data = model;
  } else if (path === "/chats" && options?.method === "POST") {
    const chat = {
      id: "demo-" + (chats.length + 1),
      project_id: project.id,
      name: "Демо-чат",
      messages: [],
      model_id: "system",
      effort: "auto",
    };
    chats.push(chat);
    data = chat;
  } else if (path.endsWith("/messages")) {
    const chat = chats.find((c) => c.id === path.split("/")[2]);
    chat.messages.push({
      id: crypto.randomUUID(),
      role: "user",
      content: body.message,
    });
    running = { id: body.request_id, chat_id: chat.id, at: Date.now() };
    data = { job_id: running.id };
  } else if (path.endsWith("/cancel")) {
    if (running) running.cancelled = true;
    data = { ok: true };
  } else if (path.startsWith("/jobs/") && running) {
    const elapsed = (Date.now() - running.at) / 1000;
    const completed = elapsed > 4 || running.cancelled;
    data = {
      id: running.id,
      status: completed
        ? running.cancelled
          ? "cancelled"
          : "completed"
        : "running",
      events:
        elapsed > 2
          ? [
              {
                type: "tool",
                text: "analytics_overview",
                state: "running",
                at: "",
              },
            ]
          : [{ type: "status", text: "Обдумываю вопрос…", at: "" }],
    };
    if (completed) {
      if (!running.cancelled)
        chats
          .find((c) => c.id === running!.chat_id)
          .messages.push({
            id: crypto.randomUUID(),
            role: "assistant",
            content:
              new URLSearchParams(location.search).has("visuals")
                ? visualAnswer
                : "Тестовый ответ для проверки интерфейса.\n\nМодель и аналитические сервисы не вызывались.",
            model: "Демо-модель",
            duration_seconds: 4,
            created_at: new Date().toISOString(),
          });
      running = null;
    }
  } else if (path.includes("/analysis/"))
    data = { id: analysisId, kind: "chart", created_at: "2026-09-13T12:00:00Z", value: analysisFixture };
  else if (path.startsWith("/chats/"))
    data = chats.find((c) => c.id === path.split("/")[2]);
  else
    return new Response(
      JSON.stringify({ detail: "Unsupported offline fixture route" }),
      { status: 400, headers: { "Content-Type": "application/json" } },
    );
  return new Response(JSON.stringify(data), {
    headers: { "Content-Type": "application/json" },
  });
};
if (new URLSearchParams(location.search).has("analysis")) {
  chats.push({ id: "analysis-demo", project_id: project.id, name: "Активность игроков", model_id: "system", effort: "auto", messages: [
    { id: "question", role: "user", content: "Покажи за вчера активность игроков из России и США по часам Москвы двумя линиями." },
    { id: "answer", role: "assistant", model: "Демо-модель", content: `Подготовил сравнение по часам московского времени. В этом примере вечерний рост активности России приходится на спад активности США.\n\n[Открыть график · Россия и США](#analysis-${analysisId})\n\nЭто синтетические данные для проверки интерфейса.`, created_at: "2026-09-13T12:00:00Z", duration_seconds: 9 }
  ] });
  localStorage.setItem("wr-selection", JSON.stringify({ chatId: "analysis-demo", projectId: project.id }));
  localStorage.setItem("wr-companion", "none");
}
applyAccent(defaultAccent);
createRoot(document.getElementById("root")!).render(<App />);
