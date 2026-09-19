/**
 * Graph-page test doubles: a deterministic synthetic citation world
 * (adjacency mirrors the a45 workstation graph's shape — real
 * bridgeland-notebook paper ids, hop-1 rows ordered paper_id ASC)
 * plus a scriptable GraphApi and a minimal ObsApi stub for the
 * caption's corpus version.
 */
import type {
  GraphApi,
  GraphNeighbor,
  GraphQuery,
  GraphResult,
  GraphStatus,
} from "../../api/graph";
import type { ObsApi } from "../../api/obs";

function n(
  paper_id: string,
  chunk_id: string | null,
  edge_kind = "cites",
): GraphNeighbor {
  return {
    chunk_id,
    paper_id,
    edge_kind,
    hop_distance: 1,
    source: "openAlex",
    confidence: 1.0,
  };
}

/** Adjacency at depth 1, per direction. `0705.3794 → 0708.2247`
 * closes a cycle back to the root (the cycle-guard fixture). */
export const FAKE_ADJACENCY: Record<string, Record<string, GraphNeighbor[]>> = {
  cites: {
    "0705.3794": [
      n("0708.2247", "0708.2247#stmt-0001"),
      n("0811.2435", null),
    ],
    "0708.2247": [n("0705.3794", "0705.3794#stmt-0002"), n("1106.5217", null)],
    "1109.5069": [n("1203.4613", "1203.4613#stmt-0007")],
  },
  cited_by: {
    "0705.3794": [n("1203.4613", "1203.4613#stmt-0007", "cited_by")],
  },
  depends_on: {},
};

export function makeFakeGraph({
  status = "present" as GraphStatus,
  transport = "ok" as "ok" | "unavailable" | "error",
  errorDetail = "boom",
}: {
  status?: GraphStatus;
  transport?: "ok" | "unavailable" | "error";
  errorDetail?: string;
} = {}) {
  const queries: { slug: string; q: GraphQuery }[] = [];
  const api: GraphApi = {
    async neighbors(slug, q): Promise<GraphResult> {
      queries.push({ slug, q });
      if (transport === "unavailable") return { kind: "unavailable" };
      if (transport === "error") return { kind: "error", detail: errorDetail };
      const direction = q.direction ?? "cites";
      const rows =
        status === "present"
          ? (FAKE_ADJACENCY[direction]?.[q.paper_id] ?? [])
          : [];
      return {
        kind: "ok",
        body: {
          format_version: 1,
          slug,
          paper_id: q.paper_id,
          direction,
          depth: q.depth ?? 2,
          limit: q.limit ?? 30,
          graph_status: status,
          neighbors: rows,
        },
      };
    },
  };
  return { api, queries };
}

/** ObsApi stub: only status() matters to the graph caption. */
export function makeObsStub(
  corpusVersion: number | null = 1690,
): ObsApi {
  return {
    requests: async () => ({ kind: "unavailable" }),
    logsTail: async () => ({ kind: "unavailable" }),
    sessions: async () => ({ kind: "unavailable" }),
    ingestEvents: async () => ({ kind: "unavailable" }),
    status: async () =>
      corpusVersion === null
        ? null
        : { status: "ready", corpus_version: corpusVersion },
  };
}
