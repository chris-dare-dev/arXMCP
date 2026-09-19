/**
 * THE MANDATED E2E — AC-B.20, as a single Playwright test.
 *
 *   create a notebook → upload a source (ar5iv HTML fixture) → observe
 *   ingest progress to digested/complete → open the observability
 *   panel and inspect request logs showing the ingest's requests.
 *
 * Default-suite variant: runs against the STATEFUL hermetic server on
 * :7804 (own instance — mutating spec files never share a stateful
 * server) with the scripted fast ingest, per the AC's own letter
 * ("Default suite runs it against a stubbed fast ingest"). The opt-in
 * live variant against the real server is mandated-flow.live.spec.ts.
 *
 * Step-4 honesty note (what "request logs showing the ingest's
 * requests" means on the merged server): the a23 requests ring records
 * MCP tool calls (tools._wrap_with_observability) — a notebook ingest
 * is a subprocess run, not a tool call, so it does NOT mint rows
 * there. What the merged server genuinely shows for an ingest run is:
 *   - the LOGS ring (root-logger RingBufferLogHandler): the trigger's
 *     own uvicorn.access record + the upload/tracker records;
 *   - the INGEST ring (Connections history): the run's stage events.
 * The flow therefore inspects the Logs tail for the ingest's request
 * records, the Connections ingest history for the run's stage rows,
 * and the Requests surface for the retained tool-call traffic (its
 * actual contract).
 *
 * A screenshot is saved at each step (E2E_SHOT_DIR overrides the
 * destination; default test-results/mandated-flow/). AC-B.2 rides
 * along: the whole flow is captured loopback-only.
 */
import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const BASE = "http://127.0.0.1:7804";
const HERE = path.dirname(fileURLToPath(import.meta.url));
const SHOT_DIR =
  process.env.E2E_SHOT_DIR ??
  path.join(HERE, "..", "test-results", "mandated-flow");

const SLUG = "fourier-mukai-e2e";
const PAPER_ID = "2404.44444";

test.use({ baseURL: BASE });

let shot = 0;
async function snap(page: Page, name: string): Promise<void> {
  fs.mkdirSync(SHOT_DIR, { recursive: true });
  shot += 1;
  await page.screenshot({
    path: path.join(SHOT_DIR, `${String(shot).padStart(2, "0")}-${name}.png`),
    fullPage: true,
  });
}

test("AC-B.20: create → upload → digested → inspect request logs", async ({
  page,
  request,
}) => {
  const reset = await request.post(`${BASE}/e2e/reset`);
  expect(reset.ok()).toBe(true);

  // AC-B.2 rider: capture every request the flow makes.
  const urls: string[] = [];
  page.on("request", (r) => urls.push(r.url()));

  // ---- Step 1: create a notebook -----------------------------------
  await page.goto("/app/");
  await expect(page.getByTestId("notebooks-status")).toHaveText("2 notebooks");
  await snap(page, "index");

  await page.getByLabel("slug").fill(SLUG);
  await page.getByLabel("display name").fill("Fourier–Mukai E2E");
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("create-status")).toHaveText(
    `Notebook ${SLUG} created.`,
  );
  await expect(page.getByTestId("notebooks-status")).toHaveText("3 notebooks");
  await snap(page, "notebook-created");

  await page.getByRole("link", { name: "Fourier–Mukai E2E" }).click();
  await expect(page.getByTestId("detail-title")).toHaveText("Fourier–Mukai E2E");
  // Fresh notebook: honest no-marker health state, zero papers.
  await expect(page.getByTestId("health-sentence")).toContainText(
    "run `make ingest` first",
  );
  await expect(page.getByTestId("papers-status")).toHaveText("0 papers");
  await snap(page, "detail-fresh");

  // ---- Step 2: upload a source (ar5iv HTML fixture) ----------------
  await page
    .getByLabel(/HTML file/)
    .setInputFiles(path.join(HERE, "fixtures", "upload-sample.html"));
  await page.getByLabel("paper id", { exact: true }).fill(PAPER_ID);
  await page.getByRole("button", { name: "Upload", exact: true }).click();
  await expect(page.getByTestId("addsource-status")).toHaveText(
    `Uploaded ${PAPER_ID} (created).`,
  );
  await expect(page.getByTestId("papers-status")).toHaveText("1 paper");
  await snap(page, "source-uploaded");

  // ---- Step 3: ingest to digested/complete -------------------------
  // Wait out the SSE ready handshake so no stage frame can be missed.
  await expect(page.locator('section[data-transport="sse"]')).toBeAttached();
  await page.getByTestId("ingest-trigger").click();
  await expect(page.getByTestId("ingest-status-badge")).toHaveText("running");
  await expect(page.getByTestId("ingest-stepper")).toBeVisible();
  const row = (stage: string) => page.locator(`[data-stage="${stage}"]`);
  await expect(row("preflight")).toHaveAttribute("data-state", "finished");
  await snap(page, "ingest-running");

  await expect(row("index")).toHaveAttribute("data-state", "finished", {
    timeout: 10_000,
  });
  await expect(page.getByTestId("ingest-status-badge")).toHaveText(
    "succeeded",
    { timeout: 10_000 },
  );
  await expect(page.getByTestId("ingest-line")).toContainText("succeeded");
  // Digested: the post-run reload shows the fresh marker — health ok
  // with the new corpus version in the margin channel.
  await expect(page.getByTestId("health-sentence")).toContainText(
    "marker and LanceDB agree",
  );
  await expect(page.getByLabel("Provenance").getByText("v1691")).toBeVisible();
  await snap(page, "ingest-digested");

  // ---- Step 4: inspect request logs for the ingest -----------------
  // Logs tail: the ingest's own request + run records are in the ring.
  await page.goto("/app/logs");
  await expect(page.getByTestId("logs-status")).toContainText("live (SSE)");
  await expect(page.getByTestId("logs-viewport")).toContainText(
    `POST /api/v1/notebooks/${SLUG}/ingest`,
  );
  await expect(page.getByTestId("logs-viewport")).toContainText(
    `uploaded ar5iv HTML: slug=${SLUG} paper_id=${PAPER_ID}`,
  );
  await expect(page.getByTestId("logs-viewport")).toContainText(
    "finished: exit_code=0",
  );
  await snap(page, "logs-ingest-records");

  // Connections: the run's stage events sit in the ingest history.
  await page.goto("/app/connections");
  await expect(page.getByTestId("trust-header")).toBeVisible();
  await expect(
    page.getByTestId("ingest-history-row").filter({ hasText: SLUG }).first(),
  ).toBeVisible();
  await snap(page, "connections-ingest-history");

  // Requests surface: renders its actual contract (retained tool-call
  // traffic + cap rejections) — the observability panel is inspectable
  // end-to-end after the run.
  await page.goto("/app/requests");
  await expect(page.getByTestId("requests-status")).toContainText("retained");
  await expect(page.getByTestId("lane-sketcher")).toBeVisible();
  await snap(page, "requests-surface");

  // ---- AC-B.2 rider: the whole flow was loopback-only --------------
  const offOrigin = urls.filter((u) => !u.startsWith(`${BASE}/`));
  expect(offOrigin, "zero external network requests").toEqual([]);
});
