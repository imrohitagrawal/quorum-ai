import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  timeout: 60000,
  expect: {
    timeout: 10000,
  },
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: [
    ["html"],
    ["list"],
    ["junit", { outputFile: "results.xml" }],
  ],
  // Self-start the FastAPI app so the accessibility (axe) spec and the other
  // browser contracts have a live server. Reuses an already-running server
  // locally; always starts a fresh one in CI. The UI is static/no-build, so no
  // network access is required to serve /ui (query POSTs are mocked per-test).
  webServer: {
    command:
      "cd .. && UV_CACHE_DIR=.uv-cache PYTHONPATH=src SENTRY_DSN='' uv run uvicorn product_app.main:app --host 127.0.0.1 --port 18085",
    url: "http://127.0.0.1:18085/ui",
    timeout: 120_000,
    reuseExistingServer: !process.env.CI,
  },
  use: {
    baseURL: "http://127.0.0.1:18085",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: {
        ...devices["Desktop Chrome"],
        // Escape hatch for environments that provision a system Chromium
        // instead of Playwright's bundled build (leave unset in normal CI so
        // the pinned browser is used).
        launchOptions: process.env.PW_EXECUTABLE_PATH
          ? { executablePath: process.env.PW_EXECUTABLE_PATH }
          : {},
      },
    },
    {
      name: "firefox",
      use: { ...devices["Desktop Firefox"] },
    },
    {
      name: "webkit",
      use: { ...devices["Desktop Safari"] },
    },
    {
      name: "mobile",
      use: { ...devices["iPhone 13"] },
    },
  ],
});