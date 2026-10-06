import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests_e2e",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: true,
  timeout: 30_000,
  expect: { timeout: 8_000 },
  reporter: [["list"], ["json", { outputFile: "test-results/results.json" }]],
  use: {
    ...devices["Desktop Chrome"],
    baseURL: "http://127.0.0.1:4173",
    viewport: { width: 1440, height: 900 },
    locale: "ru-RU",
    timezoneId: "UTC",
    serviceWorkers: "block",
    actionTimeout: 8_000,
    navigationTimeout: 10_000,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "no-preference", use: { contextOptions: { reducedMotion: "no-preference" } } },
    { name: "reduce", use: { contextOptions: { reducedMotion: "reduce" } } },
  ],
  webServer: {
    command: "npm run build && npx vite preview --host 127.0.0.1 --port 4173 --strictPort",
    url: "http://127.0.0.1:4173",
    reuseExistingServer: false,
    timeout: 60_000,
    gracefulShutdown: { signal: "SIGTERM", timeout: 5_000 },
  },
});
