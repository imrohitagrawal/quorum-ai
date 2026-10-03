import { defineConfig, devices } from "@playwright/test";

/**
 * The SIGNED-IN browser lane (W33 slice D, ADR-0142) — its own server and
 * port, so it never shares a backend (or the 18085 port) with the main lanes.
 *
 * `e2e/servers/signed_in_server.py` is a TEST-ONLY launcher: the real app with
 * Google sign-in switched on against a loopback token stub set IN-PROCESS
 * (never through an environment variable — ADR-0142 rejects that as a
 * critical risk), fresh temporary databases, and live execution off ($0).
 * The spec catches the Google consent page with `page.route` and redirects
 * the browser to the local callback; everything after that is real.
 *
 * Never reuse a running server: a stale one would carry another run's
 * accounts and databases.
 */
const PORT = 18096;

export default defineConfig({
  testDir: "./tests/signed-in",
  timeout: 90000,
  expect: { timeout: 10000 },
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  // RB-4: zero retries; masking is explicit opt-in for local triage only.
  retries: Number(process.env.PW_RETRIES ?? 0),
  workers: 1,
  reporter: [["list"], ["junit", { outputFile: "results.xml" }]],
  webServer: {
    command: `cd .. && UV_CACHE_DIR=.uv-cache PYTHONPATH=src:. uv run python e2e/servers/signed_in_server.py --port ${PORT}`,
    url: `http://127.0.0.1:${PORT}/ready`,
    timeout: 120_000,
    reuseExistingServer: false,
  },
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
