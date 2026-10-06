import { formatGeneratedAt } from "../src/reports/ReportPreview";
import { expect, openReports, send, test } from "./fixtures";
import { QUESTION, REPORT_ARGS, REPORT_TITLE } from "./testData";

test("finished reload restores multiple reports of only this chat", async ({ page, stub }) => {
  const seed = stub.seedFinished();
  stub.completeRun(stub.startRun(seed.chatId, "Второй вопрос"), { title: "Второй отчёт" });
  stub.seedFinished({ title: "Другой чат", reportTitle: "Чужой отчёт" });
  await page.goto(`/chats/${seed.chatId}`);
  // Settle initial hydration before arming reload's response subscription.
  await expect(page.locator(".msg--assistant")).toHaveCount(2);
  await expect(page.locator(".report-card")).toHaveCount(2);
  const detail = page.waitForResponse((r) => r.url().endsWith(`/api/chats/${seed.chatId}`))
    .then((response) => response.json());
  await page.reload();
  const body = await detail;
  expect(body.reports).toHaveLength(2);
  await expect(page.getByRole("complementary").getByRole("heading")).toHaveText("Отчёты чата (2)");
  await expect(page.locator(".report-card")).toHaveCount(2);
  await expect(page.getByRole("button", { name: /^Чужой отчёт / })).toHaveCount(0);
  await expect(page.locator(".msg--assistant")).toHaveCount(2);
});

test("preview preserves exact table and chart values and every parameter", async ({ page, stub }) => {
  const seed = stub.seedFinished();
  await page.goto(`/chats/${seed.chatId}`);
  await openReports(page);
  await page.getByRole("complementary").getByRole("button", { name: new RegExp(`^${REPORT_TITLE} `) }).click();
  const preview = page.locator(".report-preview");
  await expect(preview.getByRole("cell", { name: "1234.5678", exact: true })).toBeVisible();
  await expect(preview.locator("svg").getByText("1234.5678", { exact: true })).toBeVisible();
  await expect(preview.getByRole("heading", { name: "Параметры" })).toBeVisible();
  await expect(preview.locator("dd").filter({ hasText: QUESTION })).toBeVisible();
  await expect(preview.locator("dd").filter({ hasText: "read_rows" })).toBeVisible();
  for (const [key, value] of Object.entries(REPORT_ARGS)) {
    const row = preview.locator(".report-params__row").filter({ has: page.getByText(key, { exact: true }) });
    await expect(row.locator("dd")).toHaveText(String(value));
  }
  await expect(preview.locator(".report-preview__meta")).toContainText("Сформирован:");
});

test("save appears in Saved Reports independently of the open chat", async ({ page, stub }) => {
  const seed = stub.seedFinished();
  const otherChat = stub.createChat("Другой чат");
  await page.goto(`/chats/${seed.chatId}`);
  const saved = page.waitForResponse((r) => r.url().endsWith("/saved") && r.request().method() === "PUT");
  await page.getByRole("complementary").getByRole("button", { name: "Сохранить", exact: true }).click();
  await saved;
  await page.getByRole("navigation", { name: "Чаты", exact: true }).getByRole("link", { name: /Другой чат/ }).click();
  await expect(page).toHaveURL(`/chats/${otherChat}`);
  await expect(page.locator(".report-card")).toHaveCount(0);
  await page.getByRole("link", { name: "Сохранённые отчёты", exact: true }).click();
  await expect(page).toHaveURL(`/saved/${seed.reportId}`);
  await expect(page.locator(".report-preview").getByRole("heading", { name: REPORT_TITLE })).toBeVisible();
});

test("unsave removes only the bookmark and retains the chat report", async ({ page, stub }) => {
  const seed = stub.seedFinished({ saved: true });
  await page.goto(`/saved/${seed.reportId}`);
  await page.getByRole("button", { name: "Убрать из сохранённых" }).click();
  await expect(page).toHaveURL("/saved");
  await expect(page.locator(".saved-row")).toHaveCount(0);
  await page.getByRole("link", { name: "Чаты", exact: true }).click();
  await expect(page).toHaveURL(`/chats/${seed.chatId}`);
  await expect(page.getByRole("complementary").getByRole("button", { name: new RegExp(`^${REPORT_TITLE} `) }))
    .toBeVisible();
});

test("update replaces date and content in Saved and the chat preview", async ({ page, stub }) => {
  const seed = stub.seedFinished({ saved: true });
  if (seed.reportId === null) throw new Error("Expected a seeded report");
  const generatedBefore = stub.report(seed.reportId).generated_at;
  const expectedBefore = `Сформирован: ${formatGeneratedAt(generatedBefore)}`;
  const date = page.locator(".report-preview__meta > span").first();
  await page.goto(`/chats/${seed.chatId}`);
  await page.getByRole("complementary").getByRole("button", { name: new RegExp(`^${REPORT_TITLE} `) }).click();
  await expect(date).toHaveText(expectedBefore);
  const chatBefore = await date.innerText();
  await page.getByRole("link", { name: "Сохранённые отчёты", exact: true }).click();
  await expect(page).toHaveURL(`/saved/${seed.reportId}`);
  const meta = page.locator(".report-preview__meta");
  await expect(meta).toContainText("Версия 1");
  await expect(date).toHaveText(expectedBefore);
  const savedBefore = await date.innerText();
  await page.getByRole("button", { name: "Обновить", exact: true }).click();
  await expect(meta).toContainText("Версия 2");
  const generatedAfter = stub.report(seed.reportId).generated_at;
  const expectedAfter = `Сформирован: ${formatGeneratedAt(generatedAfter)}`;
  expect(generatedAfter).not.toBe(generatedBefore);
  await expect(date).toHaveText(expectedAfter);
  const savedAfter = await date.innerText();
  expect(savedAfter).not.toBe(savedBefore);
  await expect(page.getByRole("cell", { name: "9876.54321", exact: true })).toBeVisible();
  await page.locator(".report-preview").getByRole("link", { name: "Открыть чат" }).click();
  await page.getByRole("complementary").getByRole("button", { name: new RegExp(`^${REPORT_TITLE} `) }).click();
  await expect(page.getByRole("cell", { name: "9876.54321", exact: true })).toBeVisible();
  await expect(page.locator(".report-preview__meta")).toContainText("Версия 2");
  await expect(date).toHaveText(expectedAfter);
  const chatAfter = await date.innerText();
  expect(chatAfter).not.toBe(chatBefore);
  console.log("UPDATE_DATE", JSON.stringify({
    generatedBefore, generatedAfter, savedBefore, savedAfter, chatBefore, chatAfter,
  }));
});

test("update failure preserves the last content and generation date", async ({ page, stub }) => {
  const seed = stub.seedFinished({ saved: true });
  if (seed.reportId === null) throw new Error("Expected a seeded report");
  stub.updateFailure = true;
  const generatedBefore = stub.report(seed.reportId).generated_at;
  const expectedDate = `Сформирован: ${formatGeneratedAt(generatedBefore)}`;
  const date = page.locator(".report-preview__meta > span").first();
  await page.goto(`/chats/${seed.chatId}`);
  await page.getByRole("complementary").getByRole("button", { name: new RegExp(`^${REPORT_TITLE} `) }).click();
  await expect(date).toHaveText(expectedDate);
  const chatBefore = await date.innerText();
  await page.getByRole("link", { name: "Сохранённые отчёты", exact: true }).click();
  await expect(page).toHaveURL(`/saved/${seed.reportId}`);
  const meta = page.locator(".report-preview__meta");
  await expect(meta).toContainText("Версия 1");
  await expect(date).toHaveText(expectedDate);
  const savedBefore = await date.innerText();
  const failed = page.waitForResponse((response) =>
    response.url().endsWith("/update") && response.status() === 502,
  );
  await page.getByRole("button", { name: "Обновить", exact: true }).click();
  await failed;
  await expect(page.getByRole("alert")).toContainText("Обновить не удалось");
  await expect(page.getByRole("alert")).toContainText(
    `Показана версия от ${formatGeneratedAt(generatedBefore)}`,
  );
  expect(stub.report(seed.reportId).generated_at).toBe(generatedBefore);
  await expect(date).toHaveText(expectedDate);
  const savedAfter = await date.innerText();
  expect(savedAfter).toBe(savedBefore);
  await expect(meta).toContainText("Версия 1");
  await expect(page.getByRole("cell", { name: "1234.5678", exact: true })).toBeVisible();
  await page.locator(".report-preview").getByRole("link", { name: "Открыть чат" }).click();
  await page.getByRole("complementary").getByRole("button", { name: new RegExp(`^${REPORT_TITLE} `) }).click();
  await expect(date).toHaveText(expectedDate);
  expect(await date.innerText()).toBe(chatBefore);
  await expect(page.locator(".report-preview__meta")).toContainText("Версия 1");
  await expect(page.getByRole("cell", { name: "1234.5678", exact: true })).toBeVisible();
  console.log("UPDATE_DATE_RETAINED", JSON.stringify({
    generatedBefore, savedBefore, savedAfter, chatBefore, chatAfter: await date.innerText(),
  }));
});

test("update gets report_busy while its chat has an active run", async ({ page, stub }) => {
  const seed = stub.seedFinished({ saved: true });
  await page.goto(`/saved/${seed.reportId}`);
  await expect(page.locator(".report-preview__meta")).toContainText("Версия 1");
  stub.startRun(seed.chatId, "Активный вопрос");
  const conflict = page.waitForResponse((r) => r.url().endsWith("/update") && r.status() === 409);
  await page.getByRole("button", { name: "Обновить", exact: true }).click();
  await conflict;
  await expect(page.getByRole("alert")).toContainText("Отчёт занят");
  await expect(page.locator(".report-preview__meta")).toContainText("Версия 1");
});

test("chat deletion keeps its saved orphan updateable and removes unsaved reports", async ({ page, stub }) => {
  const seed = stub.seedFinished({ saved: true });
  stub.completeRun(stub.startRun(seed.chatId, "Несохранённый вопрос"), { title: "Несохранённый отчёт" });
  await page.goto(`/chats/${seed.chatId}`);
  await page.getByRole("button", { name: /^Действия с чатом/ }).click();
  await page.getByRole("menuitem", { name: "Удалить", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "Удалить", exact: true }).click();
  await expect(page).toHaveURL(/\/chats\/new$/);
  await page.getByRole("link", { name: "Сохранённые отчёты", exact: true }).click();
  await expect(page).toHaveURL(`/saved/${seed.reportId}`);
  await expect(page.locator(".saved-row")).toHaveCount(1);
  await expect(page.locator(".report-preview").getByText("Чат удалён", { exact: true })).toBeVisible();
  await expect(page.getByRole("link", { name: "Открыть чат", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Обновить", exact: true }).click();
  await expect(page.locator(".report-preview__meta")).toContainText("Версия 2");
});

test("successive sends retain both reports automatically", async ({ page, stub }) => {
  const chatId = stub.createChat();
  await page.goto(`/chats/${chatId}`);
  stub.completeRun(await send(page, "Первый отчёт"));
  await expect(page.locator(".msg--assistant")).toHaveCount(1);
  stub.completeRun(await send(page, "Второй отчёт"), { title: "Второй отчёт" });
  await expect(page.locator(".msg--assistant")).toHaveCount(2);
  await expect(page.locator(".report-card")).toHaveCount(2);
});
