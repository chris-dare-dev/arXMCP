/**
 * Observability read-API seam (arx-b3, WS-B over WS-A A3).
 *
 * The four R1-R8 read endpoints + the IF-2 multiplexed SSE stream live
 * on the arx-a23 branch (server/routes/observability.py), NOT on this
 * branch's A1 spine — so they are absent from the IF-1 openapi.json
 * dump and the generated schema.d.ts cannot type them. This module is
 * the hand-maintained twin of the a23 contract (field-for-field match
 * verified against server/routes/observability.py +
 * server/observability/events.py + server/session.snapshot_sessions on
 * stage2/arx-a23), with the same degrade discipline the b2 surfaces
 * established: a 404 from an A1-spine server is an "unavailable"
 * result, never an exception — the pages render an honest degraded
 * state and the SPA needs zero client changes at integration.
 *
 * Same-origin relative URLs only (connect-src 'self', AC-B.2); tests
 * inject a fetch double via makeObsApi(fetchImpl, base).
 */

/** The observability page envelope (a23 `_page_envelope`): the api_v1
 * `_page` shape plus the ring cursor for since_seq polling. */
export interface ObsPage<T> {
  format_version: number;
  items: T[];
  total: number;
  limit: number;
  offset: number;
  /** Ring cursor — absent on /sessions and /tool-calls (not rings). */
  latest_seq?: number;
}

/** One request event (R1) — emitted by server/tools.py
 * _wrap_with_observability; ring stamps seq + ts. */
export interface RequestEvent {
  seq: number;
  /** Wall-clock seconds (ms precision float). */
  ts: number;
  tool: string;
  status: "ok" | "error" | "denied" | "cap" | string;
  error_code: string | null;
  /** 16-char session-id prefix (the repo's log discipline). */
  session_id: string | null;
  role: string | null;
  profile: string | null;
  notebook: string | null;
  latency_ms: number;
  cache_layer: string | null;
  result_bytes: number | null;
  k: number | null;
  corpus_version: number | null;
  /** Only present when phases actually ran (R5) — the waterfall
   * renders what ran, never phantom phases. */
  phases_ms?: Record<string, number>;
}

/** One post-redaction log record (R2). The shape is the JsonFormatter
 * payload: stdlib record attrs minus formatter internals, plus any
 * `extra` fields (event, tool, session_id, role, request_id, ...).
 * Redaction happened at source (handler-level RedactionFilter) BEFORE
 * the record entered the ring — this client renders verbatim and
 * never re-derives. */
export interface LogRecord {
  seq: number;
  ts: number;
  level?: string;
  /** Logger name (stdlib `name`). */
  name?: string;
  message?: string;
  [extra: string]: unknown;
}

/** One session row (R3/R7) — server/session.snapshot_sessions. */
export interface SessionRow {
  session_id_prefix: string;
  created_at: number;
  last_seen_at: number;
  roles_seen: string[];
  counts: Record<string, number>;
  caps: Record<string, { limit: number; used: number; remaining: number }>;
  hourly: { used: number; limit: number; window_seconds: number };
}

/** One ingest/parse stage event (R4) — publish_ingest_stage_event. */
export interface IngestEventRow {
  seq: number;
  ts: number;
  kind: "ingest" | "parse" | string;
  slug: string;
  stage: string;
  phase: "started" | "finished" | "failed" | string;
  run_id?: number;
  paper_id?: string;
  detail?: Record<string, unknown>;
}

/** The trust-surface view of GET /status.
 *
 * `/status` (server/health.py::status_endpoint) is IETF
 * `application/health+json`: `{status, description, checks}` with NO
 * top-level `corpus_version` — the shared corpus version lives nested at
 * `checks["corpus:version"][0].observedValue` (a number, present only on a
 * warm server; absent in bootstrap/cold state). This interface is the
 * flattened projection the trust surfaces actually consume; `status()`
 * below does the extraction, so `corpus_version` is a real number on a warm
 * server and an explicit `null` (never `undefined`) when no corpus is
 * pinned. Consumers may therefore keep a strict `!== null` guard. */
export interface ObsStatus {
  status: string;
  corpus_version: number | null;
}

/** One health+json component check (server/health.py). Only the two fields
 * the trust surface reads are typed; the rest (`componentType`, `time`, …)
 * are ignored. */
interface HealthCheck {
  status?: string;
  observedValue?: unknown;
}

/** Health+json body shape (server/health.py::status_endpoint). */
interface HealthJson {
  status?: string;
  checks?: Record<string, HealthCheck[]>;
  /** Some deployments/mocks expose the version flat; tolerated as a
   * fallback so a flat `{status, corpus_version}` body still resolves. */
  corpus_version?: unknown;
}

/** Extract the shared corpus version from a `/status` health+json body.
 *
 * Prefers the health+json location (`checks["corpus:version"][0]
 * .observedValue`); falls back to a top-level `corpus_version` when a
 * deployment or fixture serves the flat shape. Returns `null` (never
 * `undefined`) when neither is a number — the honest "no corpus pinned"
 * state a bootstrap/cold server reports, which the trust header renders as
 * "no corpus version" rather than the literal "vundefined". */
export function corpusVersionFromStatus(body: HealthJson): number | null {
  const observed = body.checks?.["corpus:version"]?.[0]?.observedValue;
  if (typeof observed === "number") return observed;
  if (typeof body.corpus_version === "number") return body.corpus_version;
  return null;
}

/**
 * Three-state result: `unavailable` is the A1-spine 404 (endpoint not
 * on this server build — structural, do not retry); `error` is a
 * transient failure (network, 5xx) the page may retry.
 */
export type ObsResult<T> =
  | { kind: "ok"; page: ObsPage<T> }
  | { kind: "unavailable" }
  | { kind: "error"; detail: string };

export interface RingQuery {
  limit?: number;
  offset?: number;
  since_seq?: number;
}

export interface ObsApi {
  requests(q?: RingQuery): Promise<ObsResult<RequestEvent>>;
  logsTail(q?: RingQuery & { level?: string }): Promise<ObsResult<LogRecord>>;
  sessions(q?: { limit?: number; offset?: number }): Promise<ObsResult<SessionRow>>;
  ingestEvents(q?: RingQuery & { slug?: string }): Promise<ObsResult<IngestEventRow>>;
  /** null on any failure — the trust header degrades to a quiet dash. */
  status(): Promise<ObsStatus | null>;
}

function buildQuery(params: Record<string, string | number | undefined>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined) q.set(k, String(v));
  }
  const s = q.toString();
  return s === "" ? "" : `?${s}`;
}

export function makeObsApi(fetchImpl?: typeof fetch, base = ""): ObsApi {
  const doFetch: typeof fetch = fetchImpl ?? ((...args) => fetch(...args));

  async function getPage<T>(path: string): Promise<ObsResult<T>> {
    let res: Response;
    try {
      res = await doFetch(`${base}${path}`);
    } catch {
      return { kind: "error", detail: `GET ${path} failed (network)` };
    }
    if (res.status === 404) return { kind: "unavailable" };
    if (!res.ok) return { kind: "error", detail: `GET ${path} failed (${res.status})` };
    try {
      return { kind: "ok", page: (await res.json()) as ObsPage<T> };
    } catch {
      return { kind: "error", detail: `GET ${path} returned non-JSON` };
    }
  }

  return {
    requests: (q = {}) =>
      getPage<RequestEvent>(`/api/v1/requests${buildQuery({ ...q })}`),
    logsTail: (q = {}) =>
      getPage<LogRecord>(`/api/v1/logs/tail${buildQuery({ ...q })}`),
    sessions: (q = {}) =>
      getPage<SessionRow>(`/api/v1/sessions${buildQuery({ ...q })}`),
    ingestEvents: (q = {}) =>
      getPage<IngestEventRow>(`/api/v1/ingest-events${buildQuery({ ...q })}`),
    status: async () => {
      try {
        const res = await doFetch(`${base}/status`);
        if (!res.ok) return null;
        // /status is health+json ({status, description, checks}) — NOT the
        // flat {status, corpus_version} an earlier draft of this twin
        // assumed. Project it: keep the top-level status word, and lift the
        // shared corpus version out of checks["corpus:version"] (null when
        // the server is bootstrap/cold and has no corpus pinned).
        const body = (await res.json()) as HealthJson;
        return {
          status: typeof body.status === "string" ? body.status : "",
          corpus_version: corpusVersionFromStatus(body),
        };
      } catch {
        return null;
      }
    },
  };
}

/** App-wide default (same-origin). */
export const obsApi = makeObsApi();
