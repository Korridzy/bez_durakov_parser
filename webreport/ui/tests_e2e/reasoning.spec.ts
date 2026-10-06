import { expect, send, test } from "./fixtures";
import {
  ANSWER_WITH_REASONING, ANSWER_WITHOUT_REASONING, FAILURE_MESSAGE,
  REASONING_FULL, REASONING_PARTIAL,
} from "./testData";

test("reasoning is collapsed above the successful answer", async ({ page, stub }) => {
  // Given a fresh chat; when a turn completes with reasoning.
  const chatId = stub.createChat();
  await page.goto(`/chats/${chatId}`);
  const id = await send(page, "обычный отчёт");
  stub.completeRun(id);
  const bubble = page.locator(".msg--assistant");
  // Then the native expander precedes the answer and is initially closed.
  await expect(bubble.getByText(ANSWER_WITH_REASONING, { exact: true })).toBeVisible();
  await expect(bubble.locator("summary")).toHaveText("Рассуждения");
  await expect(bubble.locator(".msg__reasoning-body")).toBeHidden();
  expect(await bubble.locator("details").evaluate((node) => node.hasAttribute("open"))).toBe(false);
  expect(await bubble.evaluate((node) => {
    const reasoning = node.querySelector("details");
    const answer = node.querySelector(".msg__body");
    return reasoning !== null && answer !== null &&
      Boolean(reasoning.compareDocumentPosition(answer) & Node.DOCUMENT_POSITION_FOLLOWING);
  })).toBe(true);
});

test("click reveals every segment of the full reasoning", async ({ page, stub }) => {
  const chatId = stub.createChat();
  await page.goto(`/chats/${chatId}`);
  stub.completeRun(await send(page, "обычный отчёт"));
  const bubble = page.locator(".msg--assistant");
  await bubble.locator("summary").click();
  for (const segment of REASONING_FULL.split("\n\n")) {
    await expect(bubble.getByText(segment, { exact: true })).toBeVisible();
  }
});

test("no expander when reasoning is absent", async ({ page, stub }) => {
  const chatId = stub.createChat();
  await page.goto(`/chats/${chatId}`);
  stub.completeRun(await send(page, "без рассуждений"), {
    answer: ANSWER_WITHOUT_REASONING, reasoning: null,
  });
  await expect(page.locator(".msg--assistant").getByText(ANSWER_WITHOUT_REASONING)).toBeVisible();
  await expect(page.locator(".msg__reasoning")).toHaveCount(0);
});

test("failed turn has a collapsed partial label and the error", async ({ page, stub }) => {
  const chatId = stub.createChat();
  await page.goto(`/chats/${chatId}`);
  stub.completeRun(await send(page, "сбой отчёта"), {
    failure: FAILURE_MESSAGE, reasoning: REASONING_PARTIAL,
  });
  const bubble = page.locator(".msg--assistant");
  await expect(bubble.getByRole("alert")).toHaveText(FAILURE_MESSAGE);
  await expect(bubble.locator("summary")).toHaveText("Рассуждения (неполные)");
  await expect(bubble.locator(".msg__reasoning-body")).toBeHidden();
  await bubble.locator("summary").click();
  await expect(bubble.getByText(REASONING_PARTIAL, { exact: true })).toBeVisible();
  await expect(page.locator(".report-card")).toHaveCount(0);
});
