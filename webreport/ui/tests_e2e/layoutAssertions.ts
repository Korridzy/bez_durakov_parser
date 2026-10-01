import { expect, type Page } from "@playwright/test";

export async function expectViewportContained(page: Page): Promise<void> {
  const bounds = await page.evaluate(() => ({
    width: document.documentElement.scrollWidth, viewport: window.innerWidth,
    height: document.documentElement.scrollHeight, viewportHeight: window.innerHeight,
  }));
  expect(bounds.width, "horizontal page overflow").toBeLessThanOrEqual(bounds.viewport);
  expect(bounds.height, "vertical page overflow").toBeLessThanOrEqual(bounds.viewportHeight);
}

export async function expectColumnAligned(page: Page): Promise<void> {
  const message = await page.locator(".conversation > .msg").last().boundingBox();
  const composer = await page.locator(".composer").boundingBox();
  expect(message).not.toBeNull();
  expect(composer).not.toBeNull();
  if (message === null || composer === null) throw new Error("Missing conversation/composer");
  expect(Math.abs(message.x - composer.x), "column left").toBeLessThanOrEqual(1);
  expect(Math.abs(message.width - composer.width), "column width").toBeLessThanOrEqual(1);
}

export async function expectDrawerSeparate(page: Page): Promise<void> {
  const drawer = await page.getByRole("dialog", { name: "Отчёты чата" }).boundingBox();
  const composer = await page.locator(".chat-composer-bar").boundingBox();
  expect(drawer).not.toBeNull();
  expect(composer).not.toBeNull();
  if (drawer === null || composer === null) throw new Error("Missing drawer/composer");
  expect(drawer.y + drawer.height, "drawer covers composer").toBeLessThanOrEqual(composer.y + 1);
}
