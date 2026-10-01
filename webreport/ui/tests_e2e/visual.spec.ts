import { expect, test } from "./fixtures";
import { expectColumnAligned, expectDrawerSeparate, expectViewportContained } from "./layoutAssertions";

for (const width of [360, 768, 1024, 1440]) {
  test(`chat active run fits ${width}px`, async ({ page, stub }, info) => {
    const seed = stub.seedFinished();
    stub.startRun(seed.chatId, "Долгий вопрос по данным");
    await page.setViewportSize({ width, height: 900 });
    await page.goto(`/chats/${seed.chatId}`);
    await expect(page.getByRole("status")).toHaveText("Думаю…");
    const animated = await page.locator(".thinking-mark__arc").first().evaluate(
      (node) => getComputedStyle(node).animationName,
    );
    expect(animated === "none").toBe(info.project.name === "reduce");
    await expectViewportContained(page);
    await expectColumnAligned(page);
    await page.screenshot({ path: info.outputPath(`task-18-chat-${width}-${info.project.name}.png`) });
  });

  test(`saved preview fits ${width}px`, async ({ page, stub }, info) => {
    const seed = stub.seedFinished({ saved: true });
    await page.setViewportSize({ width, height: 900 });
    await page.goto(`/saved/${seed.reportId}`);
    await expect(page.getByRole("cell", { name: "1234.5678", exact: true })).toBeVisible();
    await expectViewportContained(page);
    await expect(page.getByRole("button", { name: "Обновить", exact: true })).toBeInViewport();
    await page.screenshot({ path: info.outputPath(`task-18-saved-${width}-${info.project.name}.png`) });
  });
}

test("360px reports drawer leaves the composer visible and focusable", async ({ page, stub }, info) => {
  const seed = stub.seedFinished();
  await page.setViewportSize({ width: 360, height: 900 });
  await page.goto(`/chats/${seed.chatId}`);
  await page.getByRole("button", { name: "Отчёты (1)", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "Отчёты чата" })).toBeVisible();
  await expectDrawerSeparate(page);
  await expectColumnAligned(page);
  await expectViewportContained(page);
  const composer = page.getByRole("textbox", { name: "Сообщение", exact: true });
  await composer.focus();
  await expect(composer).toBeFocused();
  await page.screenshot({ path: info.outputPath(`task-18-drawer-360-${info.project.name}.png`) });
  await composer.press("Escape");
  await expect(page.getByRole("dialog", { name: "Отчёты чата" })).toBeHidden();
});

test("outside-container wide table fails the same overflow assertion", async ({ page, stub }) => {
  const seed = stub.seedFinished({ saved: true });
  await page.setViewportSize({ width: 360, height: 900 });
  await page.goto(`/saved/${seed.reportId}`);
  await expect(page.getByRole("cell", { name: "1234.5678", exact: true })).toBeVisible();
  await expectViewportContained(page);
  await page.evaluate(() => {
    const table = document.createElement("table");
    table.id = "test-wide-table";
    table.style.cssText = "width:3000px;min-width:3000px;position:absolute;top:0;left:0";
    table.innerHTML = "<tr><td>Deliberate overflow fixture</td></tr>";
    document.body.append(table);
  });
  try {
    await expect(expectViewportContained(page)).rejects.toThrow("horizontal page overflow");
  } finally {
    await page.locator("#test-wide-table").evaluate((node) => node.remove());
  }
  await expectViewportContained(page);
});
