import { test as base, expect, type Page } from "@playwright/test";
import type { Run } from "../src/api/types";
import { TestApiStub } from "./stub";

export const test = base.extend<{ stub: TestApiStub }>({
  stub: async ({ page }, use) => {
    const stub = new TestApiStub(page);
    await stub.install();
    try {
      await use(stub);
      expect(stub.externalRequests, "unexpected non-loopback requests").toEqual([]);
      expect(stub.guardRequests).toEqual([]);
      expect(stub.unhandledRequests, "unimplemented API contract").toEqual([]);
    } finally {
      await stub.dispose();
    }
  },
});

export { expect };

export async function send(page: Page, message: string): Promise<string> {
  // Subscribe before the click: a stubbed reply may resolve immediately.
  const accepted = page.waitForResponse(
    (response) => response.url().endsWith("/messages") && response.status() === 202,
  );
  await page.getByRole("textbox", { name: "Сообщение", exact: true }).fill(message);
  await page.getByRole("button", { name: "Отправить", exact: true }).click();
  const run: Run = await (await accepted).json();
  return run.request_id;
}

export async function openReports(page: Page): Promise<void> {
  const toggle = page.getByRole("button", { name: /^Отчёты \(/ });
  if (await toggle.count()) {
    await toggle.click();
  }
  await expect(page.getByRole("complementary", { name: "Отчёты чата" })).toBeVisible();
}
