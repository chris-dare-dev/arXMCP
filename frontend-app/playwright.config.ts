import { defineConfig, devices } from "@playwright/test";

/**
 * WS-B M0 harness (AC-B.14/16/21/2 seeds): axe zero-violation gate,
 * visual baselines (light+dark, reduced-motion forced), CSP + network
 * capture — against the hermetic e2e server (tools/app_e2e_server.py),
 * which serves the REAL committed dist through the REAL /app mount +
 * SecurityHeadersMiddleware, with a mock /api/v1. Single-machine
 * Windows baseline (the authoritative workstation).
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: "http://127.0.0.1:7799",
    trace: "retain-on-failure",
  },
  expect: {
    toHaveScreenshot: {
      // Font rasterization jitter allowance on the single baseline
      // machine; anything structural blows well past this.
      maxDiffPixelRatio: 0.02,
    },
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    {
      // Read-only instance: visual/axe/CSP suites. Never mutated.
      command: "python ../tools/app_e2e_server.py",
      url: "http://127.0.0.1:7799/app/",
      reuseExistingServer: true,
      timeout: 30_000,
    },
    {
      // Mutation instance: notebook-flows.spec.ts only (serial, with
      // POST /e2e/reset between tests) — stateful flows can never race
      // the screenshot baselines on 7799.
      command: "python ../tools/app_e2e_server.py --port 7800",
      url: "http://127.0.0.1:7800/app/",
      reuseExistingServer: true,
      timeout: 30_000,
    },
    {
      // Second mutation instance: ingest-flows.spec.ts only. Its own
      // port because spec FILES run in parallel workers — two mutating
      // files sharing one stateful server would race each other's
      // /e2e/reset.
      command: "python ../tools/app_e2e_server.py --port 7801",
      url: "http://127.0.0.1:7801/app/",
      reuseExistingServer: true,
      timeout: 30_000,
    },
    {
      // Third mutation instance: obs-flows.spec.ts only (arx-b3) —
      // same isolation rule as above.
      command: "python ../tools/app_e2e_server.py --port 7802",
      url: "http://127.0.0.1:7802/app/",
      reuseExistingServer: true,
      timeout: 30_000,
    },
    {
      // Fourth mutation instance: config-graph-flows.spec.ts only
      // (arx-b3 capabilities + graph) — same isolation rule.
      command: "python ../tools/app_e2e_server.py --port 7803",
      url: "http://127.0.0.1:7803/app/",
      reuseExistingServer: true,
      timeout: 30_000,
    },
    {
      // Fifth mutation instance: mandated-flow.spec.ts only (the
      // AC-B.20 named E2E) — same isolation rule. Its live twin
      // (mandated-flow.live.spec.ts) boots no server here: it is
      // opt-in via ARXMCP_E2E_LIVE against the real :7733 process.
      command: "python ../tools/app_e2e_server.py --port 7804",
      url: "http://127.0.0.1:7804/app/",
      reuseExistingServer: true,
      timeout: 30_000,
    },
    {
      // Sixth mutation instance: axe-ghost.spec.ts only (AC-B.14 on
      // the traffic-less states, which need /e2e/obs-clear to empty a
      // ring while the route stays 200). Its own port so the mutation
      // never races the 7799 read-only axe/visual baselines.
      command: "python ../tools/app_e2e_server.py --port 7805",
      url: "http://127.0.0.1:7805/app/",
      reuseExistingServer: true,
      timeout: 30_000,
    },
  ],
});
