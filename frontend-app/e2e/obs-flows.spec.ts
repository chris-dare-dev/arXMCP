/**
 * Observability flows against the STATEFUL hermetic server on :7802
 * (own instance — mutating spec files never share a stateful server).
 * Serial + POST /e2e/reset per test.
 *
 * Covers the arx-b3 surfaces end-to-end in a real browser (AC-B.19):
 *  - live log tail over the real SSE stream (scripted emits appear
 *    without reload); pause freezes the tail, the "N new lines" pill
 *    counts arrivals, resume jumps to them (WCAG 2.2.2);
 *  - facet chips filter the tail; the URL carries the facet state;
 *  - requests: lane hero renders role traffic; the waterfall drawer
 *    opens with the phases that ran and Escape closes it;
 *  - connections: trust header + roster cap meters + ingest history;
 *  - polling fallback: SSE endpoint 404 (A1 spine) still tails via
 *    the since_seq poll;
 *  - obs-endpoints-absent mode: every surface states the degraded
 *    truth instead of breaking.
 */
import { expect, test } from "@playwright/test";

const BASE = "http://127.0.0.1:7802";

test.describe.configure({ mode: "serial" });
test.use({ baseURL: BASE });

test.beforeEach(async ({ request }) => {
  const reset = await request.post(`${BASE}/e2e/reset`);
  expect(reset.ok()).toBe(true);
});

test("logs: live tail appends scripted SSE lines without reload", async ({
  page,
  request,
}) => {
  await page.goto("/app/logs");
  await expect(page.getByTestId("logs-status")).toContainText("live (SSE)");
  const before = await page.getByTestId("log-row").count();

  const emit = await request.post(`${BASE}/e2e/obs-emit`, {
    data: { topic: "logs", count: 2 },
  });
  expect(emit.ok()).toBe(true);

  await expect(page.getByTestId("log-row")).toHaveCount(before + 2);
  await expect(page.getByTestId("logs-viewport")).toContainText("live line");
});

test("logs: pause freezes the tail; the pill counts new lines; resume shows them", async ({
  page,
  request,
}) => {
  await page.goto("/app/logs");
  await expect(page.getByTestId("logs-status")).toContainText("live (SSE)");
  const before = await page.getByTestId("log-row").count();

  await page.getByTestId("logs-pause").click();
  await expect(page.getByTestId("logs-status")).toContainText("paused");

  await request.post(`${BASE}/e2e/obs-emit`, { data: { topic: "logs", count: 3 } });

  const pill = page.getByTestId("logs-pill");
  await expect(pill).toContainText("3 new lines");
  // Display stayed frozen while paused.
  await expect(page.getByTestId("log-row")).toHaveCount(before);

  await pill.click();
  await expect(page.getByTestId("log-row")).toHaveCount(before + 3);
  await expect(page.getByTestId("logs-status")).toContainText("following");
  await expect(page.getByTestId("logs-pill")).toHaveCount(0);
});

test("logs: facet chips filter the closed field set and land in the URL", async ({
  page,
}) => {
  await page.goto("/app/logs");
  await expect(page.getByTestId("logs-status")).toContainText("live (SSE)");

  await page
    .getByTestId("facet-level")
    .getByRole("button", { name: /^ERROR/ })
    .click();
  await expect(page.getByTestId("log-row")).toHaveCount(1);
  await expect(page.getByTestId("log-row")).toContainText(
    "latexml conversion failed",
  );
  expect(new URL(page.url()).searchParams.get("level")).toBe("ERROR");

  // The inspector renders sorted-key JSON + the redaction notice.
  await page.getByTestId("log-row").click();
  await expect(page.getByTestId("inspector-redaction")).toContainText(
    "redacted at source",
  );
});

test("requests: lane hero + waterfall drawer with the phases that ran", async ({
  page,
}) => {
  await page.goto("/app/requests");
  await expect(page.getByTestId("requests-status")).toContainText("retained");

  // The four fixed role lanes exist; sketcher carries fixture pulses.
  await expect(page.getByTestId("lane-sketcher").locator("circle")).toHaveCount(3);
  await expect(page.getByTestId("lane-tactician").locator("circle.pulse-error")).toHaveCount(1);
  // Cap meters ride the sketcher lane from the sessions snapshot.
  await expect(
    page.getByTestId("lane-sketcher").getByTestId("cap-search_papers"),
  ).toBeVisible();

  // R6-lite: the rejection strip counts the cap event.
  await expect(page.getByTestId("cap-rejection-strip")).toContainText(
    "1 cap/authz rejection",
  );

  await page.getByTestId("request-open-1").click();
  await expect(page.getByTestId("waterfall-drawer")).toBeVisible();
  await expect(page.getByTestId("phase-embed")).toBeVisible();
  await expect(page.getByTestId("waterfall-drawer")).toContainText(
    "cache_probe: 1.2 ms",
  );
  await page.keyboard.press("Escape");
  await expect(page.getByTestId("waterfall-drawer")).toHaveCount(0);

  // Single-bar fallback on a phase-less call.
  await page.getByTestId("request-open-2").click();
  await expect(page.getByTestId("waterfall-fallback")).toContainText(
    "no phase capture",
  );
});

test("connections: trust header, roster cap meters, ingest history", async ({
  page,
}) => {
  await page.goto("/app/connections");
  await expect(page.getByTestId("trust-header")).toContainText("corpus v1690");
  await expect(page.getByTestId("trust-header")).toContainText(
    "2 sessions tracked",
  );

  const fresh = page.getByTestId("session-a1b2c3d4e5f60718");
  await expect(fresh.getByTestId("cap-search_papers")).toContainText("3/3");
  await expect(fresh.getByTestId("cap-get_chunk")).toContainText("1/4");

  await expect(page.getByTestId("ingest-history-row")).toHaveCount(4);
  await expect(page.getByTestId("ingest-history-row").first()).toContainText(
    "mineru",
  );
});

test("logs: polling fallback tails new lines when the SSE endpoint 404s", async ({
  page,
  request,
}) => {
  await request.post(`${BASE}/e2e/sse-mode`, { data: { enabled: false } });
  await page.goto("/app/logs");
  await expect(page.getByTestId("logs-status")).toContainText(
    "polling every 2 s",
  );
  await expect(page.getByTestId("logs-stream-banner")).toBeVisible();
  const before = await page.getByTestId("log-row").count();

  await request.post(`${BASE}/e2e/obs-emit`, { data: { topic: "logs", count: 1 } });
  // The 2 s since_seq poll picks it up without any stream.
  await expect(page.getByTestId("log-row")).toHaveCount(before + 1, {
    timeout: 10_000,
  });
});

test("A1-spine mode: every surface states the degraded truth", async ({
  page,
  request,
}) => {
  await request.post(`${BASE}/e2e/obs-mode`, { data: { enabled: false } });

  await page.goto("/app/logs");
  await expect(page.getByTestId("logs-unavailable")).toContainText(
    "GET /api/v1/logs/tail",
  );
  await page.goto("/app/requests");
  await expect(page.getByTestId("requests-unavailable")).toContainText(
    "GET /api/v1/requests",
  );
  await page.goto("/app/connections");
  await expect(page.getByTestId("roster-unavailable")).toContainText(
    "GET /api/v1/sessions",
  );
  await expect(page.getByTestId("ingest-history-status")).toContainText(
    "unavailable on this server build",
  );
});
