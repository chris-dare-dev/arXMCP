/**
 * Citation-graph views (arx-b3, WS-B over WS-A A5; AC-B.23).
 *
 * Tier-0 — the MANDATORY accessible surface: a nested neighbor list
 * (traverse / expand / focus), plain buttons and lists so it is fully
 * keyboard + screen-reader operable with standard semantics. This is
 * the acceptance surface for AT; it renders whenever the endpoint
 * answers and is never removed.
 *
 * Tier-2 — the 3d-force-graph WebGL view: strictly opt-in behind a
 * button, lazily imported ONLY at activation (AC-B.22: no WebGL
 * context, no three.js parse before the surface is asked for),
 * feature-detected (no WebGL → a quiet note, Tier-0 stands), data
 * caption per NO-18 (papers / edges / corpus version), and a freeze
 * discipline delegated to Force3D (<= 3 s cooldown; camera moves only
 * on user action).
 *
 * The a45 REST endpoint is on a PARALLEL branch: this page
 * feature-detects it at runtime and renders honest degraded states
 * for route-absent (A1 spine), graph "absent" (Kùzu store not
 * ingested) and graph "unavailable" (store not queryable).
 */
import {
  lazy,
  Suspense,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { useApi } from "../../api/ApiProvider";
import {
  GRAPH_DIRECTIONS,
  type GraphDirection,
  type GraphNeighbor,
  type GraphStatus,
} from "../../api/graph";
import { useGraphApi } from "../../api/GraphProvider";
import { useObsApi } from "../../api/ObsProvider";
import type { ObsStatus } from "../../api/obs";
import type { PageEnvelope, PaperRow } from "../../api/types";

/** Lazy 3-D chunk: parsed only when the operator opens the view. */
const Force3D = lazy(() => import("./Force3D"));

const FETCH_LIMIT = 50;
/** AC-B.23: the 3-D view renders <= 2k nodes. */
export const MAX_3D_NODES = 2000;

type NodeFetch =
  | { phase: "loading" }
  | { phase: "ok"; status: GraphStatus; rows: GraphNeighbor[] }
  | { phase: "route-absent" }
  | { phase: "error"; detail: string };

/** Default WebGL probe — overridable in tests (jsdom has no WebGL,
 * which conveniently exercises the degrade path for real). */
function defaultWebglProbe(): boolean {
  try {
    const canvas = document.createElement("canvas");
    return (
      canvas.getContext("webgl2") !== null ||
      canvas.getContext("webgl") !== null
    );
  } catch {
    return false;
  }
}

function isDirection(v: string | null): v is GraphDirection {
  return v !== null && (GRAPH_DIRECTIONS as readonly string[]).includes(v);
}

// ---------------------------------------------------------------------------
// Tier-0 branch renderer
// ---------------------------------------------------------------------------

function NeighborItem({
  neighbor,
  path,
  fetches,
  expanded,
  onToggle,
  onFocus,
}: {
  neighbor: GraphNeighbor;
  /** Paper ids from the root down to this node's parent — the cycle
   * guard: an ancestor never re-expands below itself. */
  path: string[];
  fetches: Map<string, NodeFetch>;
  expanded: Set<string>;
  onToggle: (paperId: string) => void;
  onFocus: (paperId: string) => void;
}) {
  const id = neighbor.paper_id;
  const isCycle = path.includes(id);
  const isExpanded = !isCycle && expanded.has(id);
  const branch = fetches.get(id);
  const branchDomId = `branch-${[...path, id].join("-").replaceAll(".", "_")}`;

  return (
    <li className="graph-node" data-testid={`node-${id}`}>
      <span className="graph-node-head">
        <span className="chip">{id}</span>
        <span className="microlabel">
          {neighbor.edge_kind} · hop {neighbor.hop_distance} · {neighbor.source}
        </span>
        {neighbor.chunk_id !== null && (
          <span className="chip graph-in-corpus">in corpus</span>
        )}
        <span className="reg-telemetry note-muted">
          confidence {neighbor.confidence.toFixed(2)}
        </span>
        {isCycle ? (
          <span className="note-muted">(cycle — expanded above)</span>
        ) : (
          <button
            type="button"
            aria-expanded={isExpanded}
            aria-controls={branchDomId}
            data-testid={`expand-${id}`}
            onClick={() => onToggle(id)}
          >
            {isExpanded ? "Collapse" : "Expand"}
          </button>
        )}
        <button
          type="button"
          data-testid={`focus-${id}`}
          onClick={() => onFocus(id)}
        >
          Focus
        </button>
      </span>
      {isExpanded && (
        <div id={branchDomId}>
          {branch === undefined || branch.phase === "loading" ? (
            <p className="reg-telemetry note-muted">Loading neighbors…</p>
          ) : branch.phase === "error" ? (
            <p className="reg-telemetry malformed-note">{branch.detail}</p>
          ) : branch.phase === "route-absent" ? (
            <p className="reg-telemetry malformed-note">
              graph API vanished mid-exploration
            </p>
          ) : branch.rows.length === 0 ? (
            <p className="reg-telemetry note-muted">
              No further edges recorded for {id}.
            </p>
          ) : (
            <ul className="graph-tree">
              {branch.rows.map((n) => (
                <NeighborItem
                  key={`${n.paper_id}-${n.edge_kind}`}
                  neighbor={n}
                  path={[...path, id]}
                  fetches={fetches}
                  expanded={expanded}
                  onToggle={onToggle}
                  onFocus={onFocus}
                />
              ))}
            </ul>
          )}
        </div>
      )}
    </li>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export function GraphPage({
  webglSupported = defaultWebglProbe,
  /** Injectable reduced-motion read — checked at TRIGGER time
   * (AC-B.16), not cached at mount. */
  prefersReducedMotion = () =>
    window.matchMedia("(prefers-reduced-motion: reduce)").matches,
}: {
  webglSupported?: () => boolean;
  prefersReducedMotion?: () => boolean;
} = {}) {
  const { slug = "" } = useParams();
  const api = useApi();
  const graph = useGraphApi();
  const obs = useObsApi();

  const [searchParams, setSearchParams] = useSearchParams();
  const direction: GraphDirection = isDirection(searchParams.get("direction"))
    ? (searchParams.get("direction") as GraphDirection)
    : "cites";
  const paramPaper = searchParams.get("paper");

  const [papers, setPapers] = useState<PaperRow[] | null>(null);
  const [papersError, setPapersError] = useState<string | null>(null);
  const [fetches, setFetches] = useState<Map<string, NodeFetch>>(new Map());
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [status, setStatus] = useState<ObsStatus | null>(null);
  const [tier2, setTier2] = useState<"closed" | "open" | "no-webgl">("closed");
  const rootHeadingRef = useRef<HTMLHeadingElement>(null);
  /** Exploration generation: bumped when direction/notebook change
   * invalidates the edge set, so an in-flight fetch from the OLD
   * generation can never write stale rows into the fresh map. */
  const genRef = useRef(0);

  // Junction papers → root picker + default root.
  useEffect(() => {
    let cancelled = false;
    void api
      .GET("/api/v1/notebooks/{slug}/papers", {
        params: { path: { slug }, query: { limit: 500 } },
      })
      .then((res) => {
        if (cancelled) return;
        if (res.data === undefined) {
          setPapers([]);
          setPapersError(
            `GET /api/v1/notebooks/${slug}/papers failed (${res.response?.status ?? "network"}).`,
          );
          return;
        }
        const page = res.data as unknown as PageEnvelope<PaperRow>;
        setPapers(page.items);
      })
      .catch(() => {
        if (cancelled) return;
        setPapers([]);
        setPapersError("papers fetch failed (network)");
      });
    return () => {
      cancelled = true;
    };
  }, [api, slug]);

  // Corpus version for the NO-18 caption (best-effort; quiet dash).
  useEffect(() => {
    let cancelled = false;
    void obs.status().then((s) => {
      if (!cancelled) setStatus(s);
    });
    return () => {
      cancelled = true;
    };
  }, [obs]);

  const root = paramPaper ?? papers?.[0]?.paper_id ?? null;

  const fetchNode = useCallback(
    (paperId: string) => {
      const gen = genRef.current;
      setFetches((m) => {
        if (m.has(paperId)) return m;
        const next = new Map(m);
        next.set(paperId, { phase: "loading" });
        return next;
      });
      void graph
        .neighbors(slug, {
          paper_id: paperId,
          direction,
          depth: 1,
          limit: FETCH_LIMIT,
        })
        .then((result) => {
          if (genRef.current !== gen) return; // stale generation
          setFetches((m) => {
            const next = new Map(m);
            if (result.kind === "ok") {
              next.set(paperId, {
                phase: "ok",
                status: result.body.graph_status,
                rows: result.body.neighbors,
              });
            } else if (result.kind === "unavailable") {
              next.set(paperId, { phase: "route-absent" });
            } else {
              next.set(paperId, { phase: "error", detail: result.detail });
            }
            return next;
          });
        });
    },
    [graph, slug, direction],
  );

  // Direction or notebook change invalidates the explored edge set.
  useEffect(() => {
    genRef.current += 1;
    setFetches(new Map());
    setExpanded(new Set());
  }, [slug, direction]);

  // Root fetch.
  useEffect(() => {
    if (root !== null) fetchNode(root);
  }, [root, fetchNode]);

  const onToggle = useCallback(
    (paperId: string) => {
      setExpanded((s) => {
        const next = new Set(s);
        if (next.has(paperId)) next.delete(paperId);
        else next.add(paperId);
        return next;
      });
      fetchNode(paperId);
    },
    [fetchNode],
  );

  const onFocus = useCallback(
    (paperId: string) => {
      const next = new URLSearchParams(searchParams);
      next.set("paper", paperId);
      setSearchParams(next, { replace: true });
      setExpanded(new Set());
      // Keyboard users land back on the (re-rooted) tree heading.
      setTimeout(() => rootHeadingRef.current?.focus(), 0);
    },
    [searchParams, setSearchParams],
  );

  const setDirection = useCallback(
    (d: GraphDirection) => {
      const next = new URLSearchParams(searchParams);
      next.set("direction", d);
      setSearchParams(next, { replace: true });
    },
    [searchParams, setSearchParams],
  );

  const rootFetch = root !== null ? fetches.get(root) : undefined;

  // Accumulated exploration model — feeds the caption and Tier-2.
  const model = useMemo(() => {
    const inCorpus = new Map<string, boolean>();
    const links = new Map<string, { source: string; target: string }>();
    if (root !== null) inCorpus.set(root, true);
    for (const [from, fetch] of fetches) {
      if (fetch.phase !== "ok") continue;
      if (!inCorpus.has(from)) inCorpus.set(from, false);
      for (const n of fetch.rows) {
        inCorpus.set(
          n.paper_id,
          (inCorpus.get(n.paper_id) ?? false) || n.chunk_id !== null,
        );
        const [source, target] =
          direction === "cited_by" ? [n.paper_id, from] : [from, n.paper_id];
        links.set(`${source}→${target}`, { source, target });
      }
    }
    const nodes = [...inCorpus.entries()].map(([id, corpus]) => ({
      id,
      inCorpus: corpus,
    }));
    return { nodes, links: [...links.values()] };
  }, [fetches, root, direction]);

  // Stable identities: Force3D tears down the WebGL scene when its
  // data props change — these must only change when the model does.
  const { nodes3d, links3d } = useMemo(() => {
    const nodes = model.nodes.slice(0, MAX_3D_NODES);
    const ids = new Set(nodes.map((n) => n.id));
    return {
      nodes3d: nodes,
      links3d: model.links.filter(
        (l) => ids.has(l.source) && ids.has(l.target),
      ),
    };
  }, [model]);

  const caption = `${model.nodes.length} paper${model.nodes.length === 1 ? "" : "s"} · ${
    model.links.length
  } edge${model.links.length === 1 ? "" : "s"} explored · corpus ${
    status?.corpus_version != null ? `v${status.corpus_version}` : "version unknown"
  }${model.nodes.length > MAX_3D_NODES ? ` · 3-D view capped at ${MAX_3D_NODES} nodes` : ""}`;

  const openTier2 = useCallback(() => {
    if (!webglSupported()) {
      setTier2("no-webgl");
      return;
    }
    setTier2("open");
  }, [webglSupported]);

  return (
    <section aria-labelledby="graph-h" className="obs-page">
      <div className="section-header">
        <h2 id="graph-h">Citation graph</h2>
      </div>
      <p className="reg-telemetry">
        <Link to={`/notebooks/${slug}`}>← notebook {slug}</Link>
      </p>

      <div className="graph-controls">
        <div className="graph-control">
          <label htmlFor="graph-root-select">Root paper</label>
          <select
            id="graph-root-select"
            className="reg-telemetry"
            data-testid="root-select"
            value={root ?? ""}
            onChange={(e) => onFocus(e.target.value)}
          >
            {root !== null &&
              papers !== null &&
              !papers.some((p) => p.paper_id === root) && (
                <option value={root}>{root} (from exploration)</option>
              )}
            {(papers ?? []).map((p) => (
              <option key={p.paper_id} value={p.paper_id}>
                {p.paper_id}
              </option>
            ))}
          </select>
        </div>
        <div
          className="graph-control"
          role="group"
          aria-label="Traversal direction"
        >
          <span className="microlabel">direction</span>
          {GRAPH_DIRECTIONS.map((d) => (
            <button
              key={d}
              type="button"
              className="chip-toggle"
              aria-pressed={direction === d}
              data-testid={`direction-${d}`}
              onClick={() => setDirection(d)}
            >
              {d}
            </button>
          ))}
        </div>
      </div>
      {papersError !== null && (
        <p className="reg-telemetry note-muted">{papersError}</p>
      )}

      <p aria-live="polite" className="reg-telemetry" data-testid="graph-status">
        {root === null &&
          papers !== null &&
          "No papers in this notebook yet — add a source first."}
        {root !== null &&
          (rootFetch === undefined || rootFetch.phase === "loading") &&
          "Loading neighbors…"}
        {rootFetch?.phase === "route-absent" && "Graph API not on this server build."}
        {rootFetch?.phase === "error" && rootFetch.detail}
        {rootFetch?.phase === "ok" &&
          (rootFetch.status === "present"
            ? `${rootFetch.rows.length} direct ${direction} neighbor${
                rootFetch.rows.length === 1 ? "" : "s"
              } of ${root}`
            : `graph ${rootFetch.status}`)}
      </p>

      {rootFetch?.phase === "route-absent" && (
        <div className="empty-state" data-testid="graph-route-unavailable">
          <p>
            This server build does not expose{" "}
            <code className="reg-telemetry">
              GET /api/v1/notebooks/{"{slug}"}/graph/neighbors
            </code>
            .
          </p>
          <p>
            The graph read API ships with the arx-a45 server slice — run a
            build that includes it, then reload. The notebook&rsquo;s papers
            table remains the authoritative paper list.
          </p>
        </div>
      )}

      {rootFetch?.phase === "ok" && rootFetch.status === "absent" && (
        <div className="empty-state" data-testid="graph-absent">
          <p>The citation-graph store is absent on this workstation.</p>
          <p>
            Build it with{" "}
            <code className="reg-telemetry">python -m ingest.graph_ingest</code>{" "}
            (about 31 s for a 200-paper seed), then reload this page.
          </p>
        </div>
      )}

      {rootFetch?.phase === "ok" && rootFetch.status === "unavailable" && (
        <div className="empty-state" data-testid="graph-degraded">
          <p>
            The graph store exists but is not queryable; the server logged the
            failure at WARNING.
          </p>
          <p>
            Inspect the server logs, repair or re-ingest the Kùzu store, then
            reload this page.
          </p>
        </div>
      )}

      {rootFetch?.phase === "ok" && rootFetch.status === "present" && (
        <>
          <h3
            className="section-header"
            tabIndex={-1}
            ref={rootHeadingRef}
            data-testid="graph-root"
          >
            Neighbors of <span className="chip">{root}</span>
          </h3>
          {rootFetch.rows.length === 0 ? (
            <div className="empty-state" data-testid="graph-empty">
              <p>
                No {direction} edges recorded for {root}.
              </p>
              <p>
                Try another direction, or re-run the graph ingest to harvest
                more edges.
              </p>
            </div>
          ) : (
            <ul className="graph-tree" data-testid="graph-tree">
              {rootFetch.rows.map((n) => (
                <NeighborItem
                  key={`${n.paper_id}-${n.edge_kind}`}
                  neighbor={n}
                  path={[root ?? ""]}
                  fetches={fetches}
                  expanded={expanded}
                  onToggle={onToggle}
                  onFocus={onFocus}
                />
              ))}
            </ul>
          )}

          <p className="reg-telemetry graph-caption" data-testid="graph-caption">
            {caption}
          </p>

          <h3 className="section-header">3-D view</h3>
          <p className="reg-telemetry note-muted">
            The neighbor list above is the accessible surface; the 3-D view is
            an optional WebGL complement over the same explored data. Camera
            moves only on your drag/scroll.
          </p>
          {tier2 === "no-webgl" && (
            <p className="reg-telemetry" data-testid="webgl-note">
              No WebGL context is available in this browser session — the
              neighbor list above carries the full explored data.
            </p>
          )}
          {tier2 !== "open" ? (
            <button type="button" data-testid="open-3d" onClick={openTier2}>
              Open 3-D view
            </button>
          ) : (
            <>
              <button
                type="button"
                data-testid="close-3d"
                onClick={() => setTier2("closed")}
              >
                Close 3-D view
              </button>
              <Suspense
                fallback={
                  <p className="reg-telemetry" data-testid="loading-3d">
                    Loading 3-D view…
                  </p>
                }
              >
                <Force3D
                  nodes={nodes3d}
                  links={links3d}
                  caption={caption}
                  reducedMotion={prefersReducedMotion()}
                />
              </Suspense>
            </>
          )}
        </>
      )}
    </section>
  );
}
