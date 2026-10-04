// Browser end-to-end tests. Run in CI (the browser is installed there):
//   npm i --no-save @playwright/test@1.49.1 && npx playwright install --with-deps chromium && npx playwright test
// Starts a real backend on a throwaway SQLite database and the Vite dev server in front of it.
import { defineConfig, devices } from "@playwright/test";

const db = "sqlite:///./e2e.db";

export default defineConfig({
  testDir: "e2e",
  testMatch: "**/*.e2e.ts", // not *.test.ts / *.spec.ts, so vitest never picks these up
  timeout: 60_000,
  retries: process.env.CI ? 1 : 0,
  workers: 1, // one shared backend database
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: { baseURL: "http://localhost:5173", trace: "retain-on-failure", screenshot: "only-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      command: `cd ../backend && rm -f e2e.db && NETCARE_DATABASE_URL=${db} python -m alembic upgrade head && `
        + `NETCARE_DATABASE_URL=${db} NETCARE_NOTIFICATIONS_WORKER=false python -m uvicorn app.main:app --port 8000`,
      url: "http://localhost:8000/health",
      timeout: 120_000,
      reuseExistingServer: false,
    },
    { command: "npm run dev -- --port 5173 --strictPort", url: "http://localhost:5173", timeout: 120_000, reuseExistingServer: false },
  ],
});
