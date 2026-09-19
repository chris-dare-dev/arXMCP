/**
 * Citation-graph read-API seam (arx-b3, WS-B over WS-A A5).
 *
 * GET /api/v1/notebooks/{slug}/graph/neighbors lives on the PARALLEL
 * arx-a45 branch (server/routes/api_v1.py::graph_neighbors_v1), NOT
 * on this branch's A1 spine — so it is absent from the IF-1 dump and
 * must be feature-detected at runtime. This module is the
 * hand-maintained twin of that contract (field-for-field match
 * verified against stage2/arx-a45 @ aea4592): the REST endpoint
 * mirrors the MCP `cite_neighbors` envelope vocabulary and
 * degradation semantics exactly, stamped with `format_version` (the
 * /api/v1 envelope; corpus_version requires warm retrieval Resources
 * the read surface must not depend on).
 *
 * Result vocabulary, two layers deep — both honest, never conflated:
 *  - transport: ok / unavailable (route absent — the A1 spine; the
 *    graph UI degrades to a teaching state) / error (transient or
 *    domain: unknown notebook, invalid paper_id → the 422 detail).
 *  - data (inside ok): graph_status "present" / "absent" (Kùzu store
 *    not ingested) / "unavailable" (store exists, not queryable) with
 *    empty neighbors on the degraded pair — HTTP 200 both.
 *
 * Same-origin relative URLs only (connect-src 'self', AC-B.2); tests
 * inject a fetch double via makeGraphApi(fetchImpl, base).
 */

/** CitationNeighbor verbatim (server/graph_types.py; rows ordered
 * (hop_distance ASC, paper_id ASC) by the shared library entry). */
export interface GraphNeighbor {
  /** Representative stmt-kind chunk id, or null when the paper is in
   * the graph but not in the chunked corpus. */
  chunk_id: string | null;
  paper_id: string;
  edge_kind: string;
  hop_distance: number;
  source: string;
  confidence: number;
}

export type GraphDirection = "cites" | "cited_by" | "depends_on";
export const GRAPH_DIRECTIONS: readonly GraphDirection[] = [
  "cites",
  "cited_by",
  "depends_on",
];

export type GraphStatus = "present" | "absent" | "unavailable";

export interface GraphNeighborsBody {
  format_version: number;
  slug: string;
  paper_id: string;
  direction: GraphDirection;
  depth: number;
  limit: number;
  graph_status: GraphStatus;
  neighbors: GraphNeighbor[];
}

export type GraphResult =
  | { kind: "ok"; body: GraphNeighborsBody }
  | { kind: "unavailable" }
  | { kind: "error"; detail: string };

export interface GraphQuery {
  paper_id: string;
  direction?: GraphDirection;
  depth?: 1 | 2;
  limit?: number;
}

export interface GraphApi {
  neighbors(slug: string, q: GraphQuery): Promise<GraphResult>;
}

async function readDetail(res: Response, fallback: string): Promise<string> {
  try {
    const body = (await res.json()) as { detail?: unknown };
    if (typeof body.detail === "string") return body.detail;
    if (Array.isArray(body.detail)) {
      const msgs = body.detail
        .map((d) => (d as { msg?: string }).msg)
        .filter((m): m is string => typeof m === "string");
      if (msgs.length > 0) return msgs.join("; ");
    }
  } catch {
    /* non-JSON error body — fall through */
  }
  return fallback;
}

export function makeGraphApi(fetchImpl?: typeof fetch, base = ""): GraphApi {
  const doFetch: typeof fetch = fetchImpl ?? ((...args) => fetch(...args));

  return {
    async neighbors(slug: string, q: GraphQuery): Promise<GraphResult> {
      const params = new URLSearchParams({ paper_id: q.paper_id });
      if (q.direction !== undefined) params.set("direction", q.direction);
      if (q.depth !== undefined) params.set("depth", String(q.depth));
      if (q.limit !== undefined) params.set("limit", String(q.limit));
      const path = `${base}/api/v1/notebooks/${encodeURIComponent(
        slug,
      )}/graph/neighbors?${params.toString()}`;

      let res: Response;
      try {
        res = await doFetch(path);
      } catch {
        return { kind: "error", detail: "graph neighbors fetch failed (network)" };
      }
      if (res.status === 404) {
        // Route-absent (A1 spine: {"detail": "Not Found"}) vs unknown
        // notebook (the a45 handler names the slug). Same documented
        // seam as the caps client; pinned by tests on both sides.
        const detail = await readDetail(res, "Not Found");
        if (detail === "Not Found") return { kind: "unavailable" };
        return { kind: "error", detail };
      }
      if (!res.ok) {
        return {
          kind: "error",
          detail: await readDetail(
            res,
            `graph neighbors fetch failed (${res.status})`,
          ),
        };
      }
      try {
        return { kind: "ok", body: (await res.json()) as GraphNeighborsBody };
      } catch {
        return { kind: "error", detail: "graph neighbors returned non-JSON" };
      }
    },
  };
}

/** App-wide default (same-origin). */
export const graphApi = makeGraphApi();
