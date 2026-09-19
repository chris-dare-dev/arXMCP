/**
 * Mock server for tests (IF-1 decoupling: "B builds/mocks against the
 * file; no live server needed"). A fetch-compatible function serving
 * canned /api/v1 + /status payloads matching the REAL response shapes
 * (server/routes/api_v1.py `_page` envelope + notebooks_store row
 * fields; server/health.py /readyz-family bodies).
 * Used by Vitest (unit) and by the Playwright harness through the
 * same route table (e2e reuses mockRoute over page.route()).
 */

import type { HealthResult, NotebookRow, PageEnvelope, PaperRow } from "./types";

export const FIXTURE_NOTEBOOKS: NotebookRow[] = [
  {
    slug: "bridgeland-stability",
    display_name: "Bridgeland stability",
    lancedb_path: "var/arxmcp/notebooks/bridgeland-stability/lancedb",
    created_at: "2026-06-22T03:08:28Z",
    notebook_kind: "arxiv",
    parse_status: "skipped",
    parse_error: null,
    parsed_html_path: null,
    discovery_category: "math.AG",
    description: "Stability conditions on derived categories",
  },
  {
    slug: "fourier-duality",
    display_name: "Fourier duality",
    lancedb_path: "var/arxmcp/notebooks/fourier-duality/lancedb",
    created_at: "2026-06-15T22:16:29Z",
    notebook_kind: "arxiv",
    parse_status: "skipped",
    parse_error: null,
    parsed_html_path: null,
    discovery_category: "math.AG",
    description: "Fourier-Mukai transforms and duality",
  },
];

export const FIXTURE_STATUS = {
  status: "ready",
  corpus_version: 1690,
} as const;

/** Junction rows per slug (store.list_papers ordering:
 * added_at DESC, paper_id ASC). */
export const FIXTURE_PAPERS: Record<string, PaperRow[]> = {
  "bridgeland-stability": [
    { paper_id: "0705.3794", added_at: "2026-06-22T03:10:02Z" },
    { paper_id: "1109.5069", added_at: "2026-06-22T03:09:11Z" },
  ],
  "fourier-duality": [],
};

/** Health fixtures: one clean marker, one drifted (the 211 silent-drift
 * class the indicator exists to surface). drift = actual - marker,
 * matching server/routes/notebooks.py::notebook_health. */
export const FIXTURE_HEALTH: Record<string, HealthResult> = {
  "bridgeland-stability": {
    format_version: 1,
    slug: "bridgeland-stability",
    status: "ok",
    marker_chunk_count: 12672,
    actual_chunk_count: 12672,
    marker_paper_count: 2,
    actual_paper_count: 2,
    drift: 0,
    corpus_version: 1690,
    detail: null,
    marker_created_at: "2026-06-22T04:00:11Z",
    chunker_version: "2",
    embedder_version: "bge-m3@567", // BGE-M3 revision pin style
  },
  "fourier-duality": {
    format_version: 1,
    slug: "fourier-duality",
    status: "drift",
    marker_chunk_count: 2051,
    actual_chunk_count: 2050,
    marker_paper_count: 1,
    actual_paper_count: 1,
    drift: -1,
    corpus_version: 1517,
    detail:
      "marker says 2051 chunks / 1 papers; LanceDB has 2050 chunks / 1 papers. "
      + "Run `make reconcile NOTEBOOK=fourier-duality` (or POST reconcile-marker).",
    marker_created_at: "2026-06-15T23:00:41Z",
    chunker_version: "2",
    embedder_version: "bge-m3@567",
  },
};

/** Canned discovery candidates (POST /discover proposes; EPHEMERAL —
 * the propose→confirm contract means nothing persists server-side). */
export const FIXTURE_DISCOVER = [
  {
    paper_id: "2406.01234",
    title: "Stability conditions under Fourier–Mukai transforms",
    abstract_head:
      "We study the behaviour of Bridgeland stability conditions under "
      + "Fourier–Mukai transforms between derived categories of smooth "
      + "projective varieties…",
    submitted_date: "2026-06-30",
  },
  {
    paper_id: "2406.05678",
    title: "Derived categories of K3 surfaces revisited",
    abstract_head:
      "A new proof of the derived Torelli theorem for K3 surfaces, with "
      + "applications to moduli of stable objects…",
    submitted_date: "2026-06-28",
  },
];

/** Build an application/json Response (exported for per-test fetches). */
export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const json = jsonResponse;

export function pageEnvelope<T>(items: T[], limit = 50, offset = 0): PageEnvelope<T> {
  return {
    format_version: 1,
    items: items.slice(offset, offset + limit),
    total: items.length,
    limit,
    offset,
  };
}

/** Route table. Fixed keys first, then per-notebook path patterns.
 * STATELESS by design — mutation flows build per-test fetches so
 * fixture state never leaks between tests (e2e statefulness lives in
 * tools/app_e2e_server.py instead). */
export function mockRoute(method: string, pathname: string): Response | null {
  const verb = method.toUpperCase();
  const key = `${verb} ${pathname}`;
  switch (key) {
    case "GET /api/v1/notebooks":
      return json(pageEnvelope(FIXTURE_NOTEBOOKS));
    case "GET /status":
      return json(FIXTURE_STATUS);
  }

  const health = pathname.match(/^\/api\/v1\/notebooks\/([^/]+)\/health$/);
  if (health && verb === "GET") {
    const body = FIXTURE_HEALTH[health[1]];
    return body !== undefined
      ? json(body)
      : json({ detail: `notebook '${health[1]}' not registered` }, 404);
  }

  const papers = pathname.match(/^\/api\/v1\/notebooks\/([^/]+)\/papers$/);
  if (papers && verb === "GET") {
    const rows = FIXTURE_PAPERS[papers[1]];
    return rows !== undefined
      ? json(pageEnvelope(rows))
      : json({ detail: `notebook '${papers[1]}' not found` }, 404);
  }

  const ingestLatest = pathname.match(
    /^\/api\/v1\/notebooks\/([^/]+)\/ingest\/latest$/,
  );
  if (ingestLatest && verb === "GET") {
    // Fixture world has no runs; stateful run scripting lives in
    // tools/app_e2e_server.py (e2e) and IngestPanel.test.tsx (unit).
    return json({
      format_version: 1,
      slug: ingestLatest[1],
      status: "none",
      terminal: false,
    });
  }

  return null;
}

/** fetch-compatible entry point for makeClient(mockFetch). */
export const mockFetch: typeof fetch = (input, init) => {
  const url = new URL(
    typeof input === "string" || input instanceof URL ? String(input) : input.url,
    "http://127.0.0.1",
  );
  const method = init?.method ?? (input instanceof Request ? input.method : "GET");
  const res = mockRoute(method, url.pathname);
  return Promise.resolve(res ?? json({ error: "not_mocked", path: url.pathname }, 404));
};
