import { expect, test } from "./fixtures";
import { expectColumnAligned, expectDrawerSeparate, expectViewportContained } from "./layoutAssertions";

for (const width of [360, 1440]) {
  test(`initial screen remains contained at ${width}px`, async ({ page, stub }, info) => {
    expect(stub.chats.size).toBe(0);
    await page.setViewportSize({ width, height: width === 360 ? 740 : 900 });
    await page.goto("/chats");
    await expect(page.locator(".conversation--empty")).toBeVisible();
    await expectViewportContained(page);
    const conversation = await page.locator(".conversation--empty").boundingBox();
    const composer = await page.locator(".composer").boundingBox();
    expect(conversation).not.toBeNull();
    expect(composer).not.toBeNull();
    if (conversation === null || composer === null) throw new Error("Missing empty conversation/composer");
    expect(Math.abs(conversation.x - composer.x)).toBeLessThanOrEqual(1);
    expect(Math.abs(conversation.width - composer.width)).toBeLessThanOrEqual(1);
    await page.screenshot({ path: info.outputPath(`task-26-initial-${width}-${info.project.name}.png`) });
  });
}

test("wide answer table keeps numeric cells on one line at 360px", async ({ page, stub }, info) => {
  const seed = stub.seedFinished({
    reasoning: null,
    answer: [
      "| Место | Команда | Всего очков | Игр | Среднее | Изменение | Сезон | Побед |",
      "| --- | --- | ---: | ---: | ---: | ---: | --- | ---: |",
      "| 1 | однажды было дважды | 880 539,5 | 130 | 1234.5678 | -12,75 | 2026/27 | 45 |",
    ].join("\n"),
  });
  await page.setViewportSize({ width: 360, height: 740 });
  await page.goto(`/chats/${seed.chatId}`);
  const table = page.locator(".msg__body table");
  await expect(table).toBeVisible();
  const metrics = await table.evaluate((node) => {
    const cells = [...node.querySelectorAll("th, td")].map((cell) => {
      const range = document.createRange();
      range.selectNodeContents(cell);
      return {
        text: cell.textContent,
        textHeight: range.getBoundingClientRect().height,
        lineHeight: parseFloat(getComputedStyle(cell).lineHeight),
      };
    });
    const wrapper = node.parentElement;
    return {
      cells,
      wrapperTag: wrapper?.tagName,
      overflowX: wrapper === null ? null : getComputedStyle(wrapper).overflowX,
      scrollWidth: wrapper?.scrollWidth ?? 0,
      clientWidth: wrapper?.clientWidth ?? 0,
      documentWidth: document.documentElement.scrollWidth,
      viewportWidth: innerWidth,
    };
  });
  console.info("task-26 wide table", JSON.stringify(metrics));
  await page.screenshot({ path: info.outputPath(`task-26-table-360-${info.project.name}.png`) });
  for (const cell of metrics.cells) {
    // Measure the rendered text, not a CSS declaration that could still clip it.
    expect.soft(cell.textHeight, `${cell.text} must stay on one line`).toBeLessThanOrEqual(cell.lineHeight);
  }
  expect.soft(metrics.wrapperTag).toBe("DIV");
  expect.soft(metrics.overflowX).toBe("auto");
  expect.soft(metrics.scrollWidth).toBeGreaterThan(metrics.clientWidth);
  expect(metrics.documentWidth).toBeLessThanOrEqual(metrics.viewportWidth);
  await expectViewportContained(page);
  const count = table.getByRole("cell", { name: "130", exact: true });
  await count.evaluate((node) => node.scrollIntoView({ block: "nearest", inline: "center" }));
  await expect(count).toBeInViewport();
  await page.screenshot({ path: info.outputPath(`task-26-table-numbers-360-${info.project.name}.png`) });
  // The last column must be reachable by scrolling the table's own wrapper.
  await table.evaluate((node) => {
    const wrapper = node.parentElement;
    if (wrapper !== null) wrapper.scrollLeft = wrapper.scrollWidth;
  });
  await expect(table.getByRole("cell", { name: "45", exact: true })).toBeInViewport();
});

test("answer table region supports keyboard scrolling at 360px", async ({ page, stub }, info) => {
  const seed = stub.seedFinished({
    reasoning: null,
    answer: [
      "| Команда | Игр | Всего очков | Среднее | Изменение | Сезон | Побед |",
      "| --- | ---: | ---: | ---: | ---: | --- | ---: |",
      "| однажды было дважды | 130 | 880 539,5 | 1234.5678 | -12,75 | 2026/27 | 45 |",
    ].join("\n"),
  });
  await page.setViewportSize({ width: 360, height: 740 });
  await page.goto(`/chats/${seed.chatId}`);
  const wrapper = page.locator(".msg__body .markdown__table-wrap");
  await expect(wrapper).toBeVisible();

  // Start from a fresh page and use Tab, never locator.focus() or a prior scroll.
  let tabCount = 0;
  while (tabCount < 10) {
    await page.keyboard.press("Tab");
    tabCount += 1;
    if (await wrapper.evaluate((node) => node === document.activeElement)) break;
  }
  await expect(wrapper).toBeFocused();
  const focus = await wrapper.evaluate((node) => ({
    role: node.getAttribute("role"),
    tabIndex: node.getAttribute("tabindex"),
    label: node.getAttribute("aria-label"),
    focusVisible: node.matches(":focus-visible"),
    outlineStyle: getComputedStyle(node).outlineStyle,
    outlineWidth: parseFloat(getComputedStyle(node).outlineWidth),
    outlineColor: getComputedStyle(node).outlineColor,
    scrollLeft: node.scrollLeft,
  }));
  console.info("task-26 keyboard focus", JSON.stringify({ tabCount, ...focus }));
  await page.screenshot({ path: info.outputPath(`task-26-table-focus-360-${info.project.name}.png`) });
  expect.soft(focus.role).toBe("region");
  expect.soft(focus.tabIndex).toBe("0");
  expect.soft(focus.label?.trim()).toBeTruthy();
  expect(focus.focusVisible).toBe(true);
  expect(focus.outlineStyle).not.toBe("none");
  expect(focus.outlineStyle).not.toBe("hidden");
  expect(focus.outlineWidth).toBeGreaterThan(0);
  expect(focus.scrollLeft).toBe(0);

  // Return the promise inside an object so the listener is armed before input.
  const scrollSignal = await wrapper.evaluateHandle((node) => ({
    moved: new Promise<number>((resolve, reject) => {
      const before = node.scrollLeft;
      const onScroll = () => {
        if (node.scrollLeft <= before) return;
        clearTimeout(timeout);
        node.removeEventListener("scroll", onScroll);
        resolve(node.scrollLeft);
      };
      const timeout = setTimeout(() => {
        node.removeEventListener("scroll", onScroll);
        reject(new Error("ArrowRight did not scroll the focused table"));
      }, 5_000);
      node.addEventListener("scroll", onScroll);
    }),
  }));
  try {
    await page.keyboard.press("ArrowRight");
    const scrollLeft = await scrollSignal.evaluate(({ moved }) => moved);
    console.info("task-26 keyboard scroll", JSON.stringify({ key: "ArrowRight", scrollLeft }));
    expect(scrollLeft).toBeGreaterThan(focus.scrollLeft);
  } finally {
    await scrollSignal.dispose();
  }
  await expectViewportContained(page);
});

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
