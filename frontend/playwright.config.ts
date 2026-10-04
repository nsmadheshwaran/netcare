// Browser end-to-end tests. Run them with a real backend on a throwaway SQLite database:
//   npm i --no-save @playwright/test && npx playwright install --with-deps chromium && npx playwright test
import { defineConfig, devices } from "@playwright/test";
import { BACKEND, DB_URL, PYTHON } from "./e2e/global-setup";

export default defineConfig({
  testDir: "e2e",
  testMatch: "**/*.e2e.ts", // not *.test.ts, so vitest never picks these up
  globalSetup: "./e2e/global-setup.ts", // fresh, migrated database
  timeout: 60_000,
  expect: { timeout: 10_000 },
  retries: process.env.CI ? 1 : 0,
  workers: 1, // one shared backend database
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: "http://localhost:5173",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    // Set E2E_BROWSER_CHANNEL=chrome (or msedge) to use a browser already installed on this machine,
    // instead of Playwright's own download. CI leaves it unset and uses the downloaded chromium.
    channel: process.env.E2E_BROWSER_CHANNEL || undefined,
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `${PYTHON} -m uvicorn app.main:app --port 8000`,
      cwd: BACKEND,
      env: { NETCARE_DATABASE_URL: DB_URL, NETCARE_NOTIFICATIONS_WORKER: "false" },
      url: "http://localhost:8000/health",
      timeout: 120_000,
      reuseExistingServer: false,
      stdout: "pipe",
      stderr: "pipe",
    },
    {
      command: "npm run dev -- --port 5173 --strictPort",
      url: "http://localhost:5173",
      timeout: 120_000,
      reuseExistingServer: false,
    },
  ],
});
