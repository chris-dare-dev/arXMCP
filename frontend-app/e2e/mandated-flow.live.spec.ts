/**
 * THE MANDATED E2E — LIVE VARIANT (AC-B.20's opt-in "real pipeline"
 * marker, requires_model-style): the same four-step flow driven
 * against a REAL arxmcp-server process (started from this worktree
 * with ARXMCP_BOOTSTRAP_MODE=1, serving the committed dist at /app),
 * ingesting a REAL arXiv paper (ar5iv HTML) through the REAL pipeline
 * (chunker → BGE-M3 embedder → LanceDB + marker + per-notebook BM25).
 *
 * Opt-in: set ARXMCP_E2E_LIVE=1 (skipped otherwise — the default
 * suite runs the hermetic mandated-flow.spec.ts twin instead). The
 * operator boots the server first; no webServer entry exists for it.
 *
 * TWO DISCLOSED BRIDGE STEPS (this branch's cross-slice seams — the
 * REST surface alone cannot reach a completed ingest on the A1 spine;
 * both are what tools/notebook_init.py + tools/notebook_fetch.py
 * would have done, performed by the test as "the operator"):
 *   1. papers.txt — tools/notebook_ingest.py reads nb_dir/papers.txt;
 *      the REST junction insert (upload/add-paper) never writes it.
 *      The spec writes the uploaded paper id there after the upload.
 *   2. global ar5iv cache — bulk_ingest's cache rung reads
 *      var/arxmcp/cache/ar5iv/<id>.html (the m8 REST upload stores its
 *      copy under nb_dir/ar5iv/ for the preview route instead). The
 *      runner pre-places the paper's HTML at that global-cache path;
 *      the spec validates it exists and uploads the SAME file through
 *      the SPA, so the bytes the UI uploaded are the bytes the
 *      pipeline ingests.
 * Both seams are named integration findings in the arx-b3 slice
 * report (a45 kept papers.txt bulk ingest for arxiv notebooks).
 *
 * Step-4 on the INTEGRATED branch (stage2-integration): the a23
 * observability read-APIs and the a45 graph endpoint are now present
 * on the same server as this UI, so this spec asserts the REAL
 * surfaces — the live SSE stepper (not the b2-spine tri-state poll
 * fallback this spec asserted before the merge), the logs ring
 * carrying the ingest's genuinely-emitted records, the connections
 * ingest history, the requests surface under its tool-call contract,
 * and (step 5) the Tier-0/Tier-2 graph page feature-detecting the
 * real /graph/neighbors endpoint. The pre-integration degraded-state
 * assertions live on in the branch history (stage2/arx-b3) and the
 * degrade paths remain covered hermetically via /e2e/sse-mode +
 * /e2e/obs-mode.
 *
 * The ar5iv HTML must exist at var/arxmcp/cache/ar5iv/<PAPER_ID>.html
 * under the worktree before the run (a real cached arXiv paper; the
 * operator/runner places it — network fetch politeness is out of
 * scope for an E2E).
 */
import { expect, test, type Page } from "@playwright/test";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const LIVE = process.env.ARXMCP_E2E_LIVE === "1";
const BASE = process.env.ARXMCP_LIVE_BASE ?? "http://127.0.0.1:7733";
const HERE = path.dirname(fileURLToPath(import.meta.url));
const WORKTREE = process.env.ARXMCP_WORKTREE_ROOT ?? path.join(HERE, "..", "..");
const SHOT_DIR =
  process.env.E2E_SHOT_DIR ??
  path.join(HERE, "..", "test-results", "mandated-flow-live");

/** Real arXiv paper (ar5iv HTML, math.AG — Bridgeland-stability
 * corpus member); ~1.8 MB, well under the 10 MB arxiv-kind cap. */
const PAPER_ID = process.env.ARXMCP_LIVE_PAPER_ID ?? "0705.3794";
const CACHE_HTML = path.join(
  WORKTREE, "var", "arxmcp", "cache", "ar5iv", `${PAPER_ID}.html`,
);

// Unique per run: repeated live runs must not collide on the registry.
// BOTH identifiers must be unique — the worktree registry persists
// across runs (every prior run leaves its row), and step 1 navigates
// by the link's accessible name, which strict-mode collides against
// any leftover row sharing the display name (fix-pass finding 1: a
// fixed display name broke the first independent re-run).
const SLUG = `e2e-live-${Date.now().toString(36)}`;
const DISPLAY = `Live E2E ${SLUG} — Fourier–Mukai`;

test.use({ baseURL: BASE });
test.skip(!LIVE, "live variant is opt-in: set ARXMCP_E2E_LIVE=1");

let shot = 0;
async function snap(page: Page, name: string): Promise<void> {
  fs.mkdirSync(SHOT_DIR, { recursive: true });
  shot += 1;
  await page.screenshot({
    path: path.join(SHOT_DIR, `${String(shot).padStart(2, "0")}-${name}.png`),
    fullPage: true,
  });
}

test("AC-B.20 live: create → upload → REAL ingest to digested → observability surfaces", async ({
  page,
}) => {
  // Real BGE-M3 cold start + embed dominate; budget generously and
  // let the report record the actual duration.
  test.setTimeout(600_000);

  if (!fs.existsSync(CACHE_HTML)) {
    throw new Error(
      `live fixture missing: ${CACHE_HTML} — place a cached ar5iv HTML ` +
        `for ${PAPER_ID} there first (see spec header).`,
    );
  }

  const urls: string[] = [];
  page.on("request", (r) => urls.push(r.url()));

  // ---- Step 1: create a notebook (real registry write) -------------
  await page.goto("/app/");
  await expect(page.getByTestId("notebooks-status")).toBeVisible();
  await snap(page, "index-live");

  await page.getByLabel("slug").fill(SLUG);
  await page.getByLabel("display name").fill(DISPLAY);
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("create-status")).toHaveText(
    `Notebook ${SLUG} created.`,
  );
  await snap(page, "notebook-created-live");

  await page.getByRole("link", { name: DISPLAY }).click();
  await expect(page.getByTestId("detail-title")).toHaveText(DISPLAY);
  await expect(page.getByTestId("health-sentence")).toContainText(
    "run `make ingest` first",
  );
  await snap(page, "detail-fresh-live");

  // ---- Step 2: upload the REAL ar5iv HTML (XHR multipart) ----------
  await page.getByLabel(/HTML file/).setInputFiles(CACHE_HTML);
  await page.getByLabel("paper id", { exact: true }).fill(PAPER_ID);
  await page.getByRole("button", { name: "Upload", exact: true }).click();
  await expect(page.getByTestId("addsource-status")).toHaveText(
    `Uploaded ${PAPER_ID} (created).`,
    { timeout: 30_000 },
  );
  await expect(page.getByTestId("papers-status")).toHaveText("1 paper");
  await snap(page, "source-uploaded-live");

  // ---- Disclosed bridge steps (see spec header) ---------------------
  const nbDir = path.join(WORKTREE, "var", "arxmcp", "notebooks", SLUG);
  fs.writeFileSync(
    path.join(nbDir, "papers.txt"),
    `# written by mandated-flow.live.spec.ts (branch seam: REST never writes this)\n${PAPER_ID}\n`,
    "utf-8",
  );

  // ---- Step 3: REAL ingest to digested ------------------------------
  // Integrated server: the a23 SSE endpoint exists — wait out the
  // ready handshake so the trigger's own preflight frame cannot be
  // missed, then assert the LIVE SSE path (the poll stays on as the
  // authoritative terminal-state reader by design, but the stepper
  // must be fed by real stage events, never the tri-state fallback).
  await expect(page.locator('section[data-transport="sse"]')).toBeAttached();
  await page.getByTestId("ingest-trigger").click();
  await expect(page.getByTestId("ingest-status-badge")).toHaveText("running");
  await expect(page.getByTestId("ingest-stepper")).toBeVisible();
  const row = (stage: string) => page.locator(`[data-stage="${stage}"]`);
  await expect(row("preflight")).toHaveAttribute("data-state", "finished");
  await snap(page, "ingest-running-live");

  // chunk → BGE-M3 embed → LanceDB + marker + BM25, for real. The
  // chunk/embed/index completions are run-summary-derived (a23 R4),
  // so they land at run end together with the terminal row.
  await expect(page.getByTestId("ingest-status-badge")).toHaveText(
    "succeeded",
    { timeout: 480_000 },
  );
  await expect(row("index")).toHaveAttribute("data-state", "finished", {
    timeout: 15_000,
  });
  await expect(page.getByTestId("ingest-line")).toContainText("succeeded");
  await expect(page.getByTestId("health-sentence")).toContainText(
    "marker and LanceDB agree",
    { timeout: 15_000 },
  );
  await snap(page, "ingest-digested-live");

  // The marker written by the real run is on disk in the worktree.
  const marker = path.join(nbDir, "lancedb", "corpus-version.json");
  expect(fs.existsSync(marker), `marker written at ${marker}`).toBe(true);

  // ---- Step 4: inspect request logs for the ingest (real rings) -----
  // Logs tail: the ingest's genuinely-emitted records are in the ring
  // (the trigger's uvicorn.access line + the run-finished record).
  await page.goto("/app/logs");
  await expect(page.getByTestId("logs-status")).toContainText("live (SSE)");
  await expect(page.getByTestId("logs-viewport")).toContainText(
    `POST /api/v1/notebooks/${SLUG}/ingest`,
  );
  // The upload handler's own INFO record (server.routes.notebooks).
  // NOTE (integration honesty): the hermetic twin also scripts an
  // "ingest run N finished: exit_code=0" log row, but the REAL
  // tracker emits no such log line - run terminal state is
  // authoritatively asserted in step 3 (badge + marker + health);
  // the twin divergence is a named Stage-3 follow-up.
  await expect(page.getByTestId("logs-viewport")).toContainText(
    `uploaded ar5iv html: slug=${SLUG} paper_id=${PAPER_ID}`,
  );
  await snap(page, "logs-ingest-records-live");

  // Connections: the run's stage events sit in the ingest history.
  await page.goto("/app/connections");
  await expect(page.getByTestId("trust-header")).toBeVisible();
  await expect(
    page.getByTestId("ingest-history-row").filter({ hasText: SLUG }).first(),
  ).toBeVisible();
  await snap(page, "connections-ingest-history-live");

  // Requests surface: renders its real contract. A subprocess ingest
  // mints no MCP tool-call rows (the b3 report's disclosed
  // interpretation), so the honest live state is an empty retained
  // window on the live SSE transport — not an "unavailable" banner.
  await page.goto("/app/requests");
  await expect(page.getByTestId("requests-status")).toContainText("retained");
  await expect(page.getByTestId("requests-status")).toContainText(
    "live (SSE)",
  );
  await snap(page, "requests-surface-live");

  // ---- Step 5: Tier-0/Tier-2 graph feature-detects the endpoint -----
  // The a45 REST graph endpoint is live on this branch and this
  // worktree's Kuzu store is ingested (204 nodes / 20 edges): the
  // graph page must take the real-API branch, never the
  // "Graph API not on this server build" route-absent state.
  await page.goto(`/app/notebooks/${SLUG}/graph`);
  await expect(page.getByTestId("graph-status")).toContainText(
    `neighbors of ${PAPER_ID}`,
    { timeout: 15_000 },
  );
  await expect(page.getByTestId("graph-root")).toBeVisible();
  await snap(page, "graph-feature-detected-live");

  // ---- AC-B.2 rider: loopback-only against the real server ---------
  const offOrigin = urls.filter((u) => !u.startsWith(`${BASE}/`));
  expect(offOrigin, "zero external network requests").toEqual([]);
});
