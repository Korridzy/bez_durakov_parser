import type { Page } from "@playwright/test";
import { expect, test } from "./fixtures";
import { TestApiStub } from "./stub";
import { testValidationCases } from "./testValidationCases";

const EXTERNAL_URL = "https://example.com/api/x";

async function fetchExternal(page: Page) {
  const failed = page.waitForEvent("requestfailed", {
    predicate: (request) => request.url() === EXTERNAL_URL, timeout: 5_000,
  });
  const fetchError = await page.evaluate(async (url) => {
    try {
      await fetch(url);
      return null;
    } catch (error) {
      if (!(error instanceof Error)) throw error;
      return { name: error.name, message: error.message };
    }
  }, EXTERNAL_URL);
  const networkError = (await failed).failure()?.errorText;
  console.log("EGRESS", JSON.stringify({ url: EXTERNAL_URL, fetchError, networkError }));
  return { fetchError, networkError };
}

function expectGuardBlocked(result: Awaited<ReturnType<typeof fetchExternal>>, probe: TestApiStub) {
  expect(result.fetchError).toEqual({ name: "TypeError", message: "Failed to fetch" });
  expect(probe.externalRequests).toEqual([EXTERNAL_URL]);
  expect(probe.guardRequests).toEqual([EXTERNAL_URL]);
  // Docker isolation also rejects fetch, but cannot produce this client-abort code.
  expect(result.networkError, "abort-specific browser failure").toContain("net::ERR_BLOCKED_BY_CLIENT");
}

test("normal browser journey makes zero non-loopback requests", async ({ page, stub }) => {
  const seed = stub.seedFinished({ saved: true });
  await page.goto(`/chats/${seed.chatId}`);
  await page.locator(".msg__reasoning-summary").click();
  await page.getByRole("link", { name: "Сохранённые отчёты", exact: true }).click();
  await expect(page.getByRole("cell", { name: "1234.5678", exact: true })).toBeVisible();
  expect(stub.externalRequests).toEqual([]);
  expect(stub.guardRequests).toEqual([]);
});

test("external api URL is aborted and counted rather than handled by the API stub", async ({ context }) => {
  const page = await context.newPage();
  const probe = new TestApiStub(page);
  await probe.install();
  try {
    await page.goto("/");
    expectGuardBlocked(await fetchExternal(page), probe);
  } finally {
    await probe.dispose();
    await page.close();
  }
});

test("registered fallback guard fails the same abort-specific assertions", async ({ context }) => {
  const page = await context.newPage();
  const probe = new TestApiStub(page);
  await probe.install({ guard: "fallback" });
  try {
    await page.goto("/");
    const result = await fetchExternal(page);
    expect(() => expectGuardBlocked(result, probe)).toThrow("abort-specific browser failure");
  } finally {
    await probe.dispose();
    await page.close();
  }
});

test("disabled abort route is detected by independent zero-egress assertion", async ({ context }) => {
  const page = await context.newPage();
  const probe = new TestApiStub(page);
  await probe.install({ guard: "off" });
  try {
    await page.goto("/");
    const outgoing = page.waitForEvent("request", {
      predicate: (r) => r.url() === "https://example.com/api/x", timeout: 5_000,
    });
    await page.evaluate(() => fetch("https://example.com/api/x").catch((error: unknown) => {
      if (!(error instanceof TypeError)) throw error;
      return null;
    }));
    await outgoing;
    expect(() => expect(probe.externalRequests, "unexpected non-loopback requests").toEqual([]))
      .toThrow("unexpected non-loopback requests");
    expect(probe.externalRequests).toEqual(["https://example.com/api/x"]);
    expect(probe.guardRequests).toEqual([]);
  } finally {
    await probe.dispose();
    await page.close();
  }
});

test("malformed requests match native and semantic backend envelopes without persistence", async ({ page, stub }) => {
  const chatId = stub.createChat();
  await page.goto(`/chats/${chatId}`);
  const results = await page.evaluate(async ({ id, cases }) => {
    const responses = [];
    for (const entry of cases) {
      const response = await fetch(entry.path.replace(":id", id), {
        method: entry.method, headers: { "Content-Type": "application/json" },
        ...(entry.body === null ? {} : { body: entry.body }),
      });
      responses.push({ name: entry.name, status: response.status, body: await response.json() });
    }
    const detail = await (await fetch(`/api/chats/${id}`)).json();
    return { responses, messages: detail.messages, active: detail.active_run, last: detail.last_run };
  }, { id: chatId, cases: testValidationCases });
  expect(results.responses).toHaveLength(testValidationCases.length);
  for (const [index, response] of results.responses.entries()) {
    const entry = testValidationCases[index];
    if (entry === undefined) throw new Error("Missing validation case");
    console.log("VALIDATION", JSON.stringify(response));
    expect(response.name).toBe(entry.name);
    expect(response.status).toBe(422);
    expect(response.body, entry.name).toEqual(entry.expected);
  }
  expect(results.messages).toEqual([]);
  expect(results.active).toBeNull();
  expect(results.last).toBeNull();
});
