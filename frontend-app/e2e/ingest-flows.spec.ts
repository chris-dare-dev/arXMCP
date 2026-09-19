/**
 * Add-source + ingest flows against the STATEFUL hermetic server on
 * :7801 (own instance — spec files run in parallel workers, so a
 * mutating file never shares a stateful server with another). Serial
 * + POST /e2e/reset per test.
 *
 * Covers the arx-b2 ingestion surfaces end-to-end in a real browser:
 *  - unified add-source URL leg: abs verbatim; ar5iv verbatim; the
 *    native arxiv.org/html DEGRADE path (the server mirrors the A1
 *    spine's 422 → the SPA retries via the abs form and says so);
 *  - XHR upload with a real multipart body + progress bar;
 *  - SSE-fed ingest stepper (scripted a23-shaped stage frames) to a
 *    succeeded terminal state;
 *  - failure run pinned at the failing stage with the stderr tail;
 *  - polling fallback when the SSE endpoint 404s (A1-spine mode).
 */
import { expect, test } from "@playwright/test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const BASE = "http://127.0.0.1:7801";
const HERE = path.dirname(fileURLToPath(import.meta.url));

test.describe.configure({ mode: "serial" });
test.use({ baseURL: BASE });

test.beforeEach(async ({ request }) => {
  const reset = await request.post(`${BASE}/e2e/reset`);
  expect(reset.ok()).toBe(true);
});

test("add source: abs URL routes verbatim to POST /papers", async ({ page }) => {
  await page.goto("/app/notebooks/fourier-duality");
  await expect(page.getByTestId("papers-status")).toHaveText("0 papers");

  await page.getByLabel("arXiv URL or paper id").fill("https://arxiv.org/abs/2401.11111");
  await expect(page.getByTestId("source-hint")).toHaveText(
    "arXiv abstract page → paper 2401.11111",
  );
  await page.getByRole("button", { name: "Add paper", exact: true }).click();
  await expect(page.getByTestId("addsource-status")).toHaveText("Added 2401.11111.");
  await expect(page.getByTestId("papers-status")).toHaveText("1 paper");
});

test("add source: ar5iv URL routes verbatim", async ({ page }) => {
  await page.goto("/app/notebooks/fourier-duality");
  await page
    .getByLabel("arXiv URL or paper id")
    .fill("https://ar5iv.labs.arxiv.org/html/2402.22222v3");
  await expect(page.getByTestId("source-hint")).toContainText("ar5iv HTML mirror");
  await page.getByRole("button", { name: "Add paper", exact: true }).click();
  await expect(page.getByTestId("addsource-status")).toHaveText("Added 2402.22222v3.");
});

test("add source: native arxiv.org/html URL degrades to the abs form on the A1 spine", async ({ page }) => {
  await page.goto("/app/notebooks/fourier-duality");
  await page.getByLabel("arXiv URL or paper id").fill("https://arxiv.org/html/2403.33333");
  await expect(page.getByTestId("source-hint")).toHaveText(
    "arXiv native HTML → paper 2403.33333",
  );
  await page.getByRole("button", { name: "Add paper", exact: true }).click();
  await expect(page.getByTestId("addsource-status")).toContainText("Added 2403.33333.");
  await expect(page.getByTestId("addsource-status")).toContainText(
    "does not accept arxiv.org/html URLs yet",
  );
  await expect(page.getByTestId("papers-status")).toHaveText("1 paper");
});

test("add source: invalid input is an inline state, no network", async ({ page }) => {
  await page.goto("/app/notebooks/fourier-duality");
  await page.getByLabel("arXiv URL or paper id").fill("https://example.com/abs/123");
  await expect(page.getByTestId("source-hint")).toContainText(
    "not an accepted arXiv source",
  );
});

test("upload: XHR multipart with progress bar → new junction row", async ({ page }) => {
  await page.goto("/app/notebooks/fourier-duality");
  await page
    .getByLabel(/HTML file/)
    .setInputFiles(path.join(HERE, "fixtures", "upload-sample.html"));
  // paper-id field stays operator-owned; the filename stem is not an id.
  await page.getByLabel("paper id", { exact: true }).fill("2404.44444");
  await page.getByRole("button", { name: "Upload", exact: true }).click();
  await expect(page.getByTestId("addsource-status")).toHaveText(
    "Uploaded 2404.44444 (created).",
  );
  await expect(page.getByTestId("papers-status")).toHaveText("1 paper");

  // Idempotent re-upload reports the updated_existing contract.
  await page
    .getByLabel(/HTML file/)
    .setInputFiles(path.join(HERE, "fixtures", "upload-sample.html"));
  await page.getByLabel("paper id", { exact: true }).fill("2404.44444");
  await page.getByRole("button", { name: "Upload", exact: true }).click();
  await expect(page.getByTestId("addsource-status")).toHaveText(
    "Uploaded 2404.44444 (replaced the stored copy).",
  );
  await expect(page.getByTestId("papers-status")).toHaveText("1 paper");
});

test("ingest: SSE-fed stepper advances to succeeded", async ({ page }) => {
  await page.goto("/app/notebooks/bridgeland-stability");
  // Wait out the SSE ready handshake so no stage frame can be missed.
  await expect(page.locator('section[data-transport="sse"]')).toBeAttached();
  await page.getByTestId("ingest-trigger").click();
  await expect(page.getByTestId("ingest-status-badge")).toHaveText("running");

  // Stage events arrive over the real EventSource: the stepper table
  // appears and rows advance in canonical order.
  await expect(page.getByTestId("ingest-stepper")).toBeVisible();
  await expect(page.getByTestId("ingest-transport")).toHaveText(
    "live stage events (SSE)",
  );
  const row = (stage: string) =>
    page.locator(`[data-stage="${stage}"]`);
  await expect(row("preflight")).toHaveAttribute("data-state", "finished");
  await expect(row("index")).toHaveAttribute("data-state", "finished", {
    timeout: 10_000,
  });
  await expect(page.getByTestId("ingest-status-badge")).toHaveText("succeeded", {
    timeout: 10_000,
  });
  await expect(page.getByTestId("ingest-line")).toContainText("succeeded");
  // The post-run reload picked up the fresh marker (health flips ok
  // with the new corpus version in the margin channel).
  await expect(page.getByLabel("Provenance").getByText("v1691")).toBeVisible();
});

test("ingest: failure pins the stepper at the failing stage with stderr tail", async ({ page, request }) => {
  const mode = await request.post(`${BASE}/e2e/ingest-mode`, {
    data: { mode: "fail" },
  });
  expect(mode.ok()).toBe(true);

  await page.goto("/app/notebooks/bridgeland-stability");
  await expect(page.locator('section[data-transport="sse"]')).toBeAttached();
  await page.getByTestId("ingest-trigger").click();
  await expect(page.getByTestId("ingest-status-badge")).toHaveText("failed", {
    timeout: 10_000,
  });
  await expect(page.locator('[data-stage="embed"]')).toHaveAttribute(
    "data-state",
    "failed",
  );
  await expect(page.getByTestId("ingest-failure")).toContainText(
    "failed at the embed stage",
  );
  await expect(page.getByTestId("ingest-stderr")).toContainText(
    "BGE-M3 embed batch failed",
  );
});

test("ingest: polling fallback when the SSE endpoint is absent (A1 spine)", async ({ page, request }) => {
  const sse = await request.post(`${BASE}/e2e/sse-mode`, {
    data: { enabled: false },
  });
  expect(sse.ok()).toBe(true);

  await page.goto("/app/notebooks/bridgeland-stability");
  await page.getByTestId("ingest-trigger").click();
  // No stage events: the labeled tri-state fallback replaces the
  // stepper; the transport line names the poll.
  await expect(page.getByTestId("stepper-fallback")).toContainText(
    "Stage events unavailable",
  );
  await expect(page.getByTestId("ingest-transport")).toHaveText(
    "polling /ingest/latest every 2 s",
  );
  await expect(page.getByTestId("ingest-stepper")).toHaveCount(0);
  await expect(page.getByTestId("ingest-status-badge")).toHaveText("succeeded", {
    timeout: 15_000,
  });
});
