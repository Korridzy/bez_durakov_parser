import { expect, send, test } from "./fixtures";
import { ANSWER_WITH_REASONING, REPORT_TITLE } from "./testData";

test("new chat sends immediately and retains its answer and report", async ({ page, stub }) => {
  await page.goto("/");
  await expect(page).toHaveURL(/\/chats\/new$/);
  const id = await send(page, "Первый вопрос по данным");
  await expect(page).toHaveURL(/\/chats\/[0-9a-f]{32}$/);
  await expect(page.getByRole("status")).toHaveText("Думаю…");
  await expect(page.getByRole("button", { name: "Остановить", exact: true })).toBeEnabled();
  stub.completeRun(id);
  await expect(page.locator(".msg__body")).toHaveText(ANSWER_WITH_REASONING);
  await expect(page.getByRole("complementary").getByRole("button", { name: new RegExp(`^${REPORT_TITLE} `) }))
    .toBeVisible();
  await expect(page.getByRole("button", { name: "Отправить", exact: true })).toBeVisible();
});

test("stop leaves a cancellation marker without a phantom report and next send works", async ({ page, stub }) => {
  const chatId = stub.createChat();
  await page.goto(`/chats/${chatId}`);
  await send(page, "Отменяемый вопрос");
  const cancelled = page.waitForResponse((r) => r.url().endsWith("/cancel") && r.status() === 202);
  await page.getByRole("button", { name: "Остановить", exact: true }).click();
  await cancelled;
  await expect(page.locator(".msg--assistant.is-cancelled")).toHaveText("Запрос отменён");
  await expect(page.locator(".report-card")).toHaveCount(0);
  stub.completeRun(await send(page, "Следующий вопрос"));
  await expect(page.locator(".msg__body")).toHaveText(ANSWER_WITH_REASONING);
  await expect(page.locator(".msg--user")).toHaveCount(2);
});

test("reload during a run resumes polling without a duplicate post", async ({ page, stub }) => {
  const chatId = stub.createChat();
  await page.goto(`/chats/${chatId}`);
  const id = await send(page, "Долгий вопрос");
  const resumed = page.waitForResponse((r) => r.url().endsWith("/status"));
  await page.reload();
  await expect(page.getByRole("status")).toHaveText("Думаю…");
  await resumed;
  stub.completeRun(id);
  await expect(page.locator(".msg__body")).toHaveText(ANSWER_WITH_REASONING);
  expect(stub.requests.filter((r) => r.method === "POST" && r.path.endsWith("/messages"))).toHaveLength(1);
  await expect(page.locator(".msg--user")).toHaveCount(1);
});

test("reload recovers sessionStorage pending with the original id exactly once", async ({ page, stub }) => {
  const chatId = stub.createChat();
  await page.goto(`/chats/${chatId}`);
  stub.disconnectNext("POST", `/api/chats/${chatId}/messages`);
  await page.getByRole("textbox", { name: "Сообщение", exact: true }).fill("Повтори сохранённый вопрос");
  await page.getByRole("button", { name: "Отправить", exact: true }).click();
  await expect(page.getByRole("button", { name: "Повторить", exact: true })).toBeVisible();
  const pending: { request_id: string }[] = await page.evaluate(() =>
    JSON.parse(sessionStorage.getItem("ui.pending") ?? "[]"),
  );
  const id = pending[0]?.request_id;
  expect(id).toMatch(/^[0-9a-f]{32}$/);
  const accepted = page.waitForResponse((r) => r.url().endsWith("/messages") && r.status() === 202);
  await page.reload();
  await accepted;
  if (id === undefined) throw new Error("Missing pending request");
  stub.completeRun(id);
  await expect(page.locator(".msg__body")).toHaveText(ANSWER_WITH_REASONING);
  await expect(page.locator(".msg--user")).toHaveCount(1);
  const postedIds = stub.requests.filter((r) => r.method === "POST" && r.path.endsWith("/messages"))
    .map((r) => r.body?.request_id);
  expect(postedIds).toEqual([id, id]);
  expect(await page.evaluate(() => sessionStorage.getItem("ui.pending"))).toBeNull();
});

test("search by completed answer reopens its persisted transcript", async ({ page, stub }) => {
  const first = stub.seedFinished({ answer: "Уникальный результат выборки", title: "Первый чат" });
  stub.seedFinished({ answer: "Другая выборка", title: "Второй чат" });
  await page.goto("/chats");
  await page.getByRole("searchbox", { name: "Поиск чатов" }).fill("УНИКАЛЬНЫЙ");
  const sidebar = page.getByRole("navigation", { name: "Чаты", exact: true });
  await expect(sidebar.locator(".chat-row")).toHaveCount(1);
  await sidebar.getByRole("link", { name: /Первый чат/ }).click();
  await expect(page).toHaveURL(`/chats/${first.chatId}`);
  await expect(page.locator(".msg__body")).toHaveText("Уникальный результат выборки");
});

test("409 conflict discovers the active run and keeps the rejected draft", async ({ page, stub }) => {
  const chatId = stub.createChat();
  await page.goto(`/chats/${chatId}`);
  await expect(page.getByRole("textbox", { name: "Сообщение", exact: true })).toBeVisible();
  const active = stub.startRun(chatId, "Уже принятый вопрос");
  const conflict = page.waitForResponse((r) => r.url().endsWith("/messages") && r.status() === 409);
  await page.getByRole("textbox", { name: "Сообщение", exact: true }).fill("Непринятый вопрос");
  await page.getByRole("button", { name: "Отправить", exact: true }).click();
  await conflict;
  await expect(page.getByRole("alert")).toContainText("Чат занят, дождитесь ответа");
  await expect(page.getByRole("textbox", { name: "Сообщение", exact: true })).toHaveValue("Непринятый вопрос");
  stub.completeRun(active);
  await expect(page.locator(".msg__body")).toHaveText(ANSWER_WITH_REASONING);
  await expect(page.locator(".msg--user")).toHaveCount(1);
});

test("network retry reuses the id and publishes only one answer", async ({ page, stub }) => {
  const chatId = stub.createChat();
  await page.goto(`/chats/${chatId}`);
  stub.disconnectNext("POST", `/api/chats/${chatId}/messages`);
  await page.getByRole("textbox", { name: "Сообщение", exact: true }).fill("Повторяемый вопрос");
  await page.getByRole("button", { name: "Отправить", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("Нет связи с сервером");
  const accepted = page.waitForResponse((r) => r.url().endsWith("/messages") && r.status() === 202);
  await page.getByRole("button", { name: "Повторить", exact: true }).click();
  const run = await (await accepted).json();
  stub.completeRun(run.request_id);
  await expect(page.locator(".msg__body")).toHaveText(ANSWER_WITH_REASONING);
  await expect(page.locator(".msg--user")).toHaveCount(1);
  expect(stub.requests.filter((r) => r.path.endsWith("/messages")).map((r) => r.body?.request_id))
    .toEqual([run.request_id, run.request_id]);
});

test("polling connection loss recovers without replacing the active question", async ({ page, stub }) => {
  const chatId = stub.createChat();
  await page.goto(`/chats/${chatId}`);
  stub.disconnectNext("GET", `/api/chats/${chatId}/status`);
  const id = await send(page, "Вопрос при обрыве связи");
  await expect(page.locator(".msg__connection")).toHaveText("Нет связи с сервером, повторяю…");
  stub.completeRun(id);
  await expect(page.locator(".msg__body")).toHaveText(ANSWER_WITH_REASONING);
  await expect(page.locator(".msg__connection")).toHaveCount(0);
  await expect(page.locator(".msg--user")).toHaveCount(1);
});
