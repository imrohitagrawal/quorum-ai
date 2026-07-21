import { defineConfig, devices } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  timeout: 60000,
  expect: {
    timeout: 10000,
  },
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  // RB-4 flake policy: ZERO retries by default, CI included. A retry converts
  // a real intermittent regression into a green check — the gate keeps saying
  // "pass" while the contract it guards holds only two runs in three. Masking
  // is explicit opt-in (`PW_RETRIES=2 npx playwright test ...`) for local
  // triage only; the blocking lane additionally pins `--retries=0` at the call
  // site (see tests/unit/test_e2e_flake_policy.py). A spec that fails >0/10 in
  // flake-scan.yml is QUARANTINED with a ledger row — never retried, never
  // given a wider timeout.
  retries: Number(process.env.PW_RETRIES ?? 0),
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
    // NOT "on-first-retry": with the RB-4 zero-retry policy there is never a
    // first retry, so that setting would capture a trace exactly never —
    // removing the masking and the diagnostics in one move. A failure now has
    // to be debuggable from its single run, so the trace is retained whenever
    // that run fails.
    trace: "retain-on-failure",
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