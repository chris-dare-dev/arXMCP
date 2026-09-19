/**
 * Test doubles for the observability surfaces (vitest only — nothing
 * here is imported by app code, so none of it reaches the bundle).
 *
 * The fixtures mirror the arx-a23 payload shapes exactly (request
 * events from tools._wrap_with_observability, log records from
 * RingBufferLogHandler, session rows from snapshot_sessions, ingest
 * stage events from publish_ingest_stage_event) with deterministic
 * timestamps anchored at 2026-07-04T12:00:00Z.
 */
import type {
  IngestEventRow,
  LogRecord,
  ObsApi,
  ObsPage,
  ObsResult,
  RequestEvent,
  SessionRow,
} from "../../api/obs";
import type { EventSourceLike } from "./useObsFeed";

/** 2026-07-04T12:00:00Z as wall-clock seconds. */
export const T0 = 1783166400;

type Ring<T> = (T & { seq: number; ts: number })[];

export const FIXTURE_LOGS: Ring<LogRecord> = [
  { seq: 1, ts: T0 + 1, level: "INFO", name: "server.tools", message: "search_papers served", event: "tool_call", tool: "search_papers", session_id: "a1b2c3d4e5f60718", role: "sketcher" },
  { seq: 2, ts: T0 + 2, level: "INFO", name: "server.cache", message: "tier1 hit", event: "cache_probe", tool: "search_papers" },
  { seq: 3, ts: T0 + 3, level: "WARNING", name: "server.session", message: "cap approaching", event: "cap_check", session_id: "a1b2c3d4e5f60718", role: "sketcher" },
  { seq: 4, ts: T0 + 4, level: "ERROR", name: "server.ingest", message: "latexml conversion failed", event: "ingest_stage", tool: "get_chunk" },
  { seq: 5, ts: T0 + 5, level: "INFO", name: "server.health", message: "readyz probe", event: "probe" },
  { seq: 6, ts: T0 + 6, level: "INFO", name: "server.health", message: "readyz probe", event: "probe" },
  { seq: 7, ts: T0 + 7, level: "INFO", name: "server.health", message: "readyz probe", event: "probe" },
];

export const FIXTURE_REQUESTS: Ring<RequestEvent> = [
  {
    seq: 1, ts: T0 + 10, tool: "search_papers", status: "ok", error_code: null,
    session_id: "a1b2c3d4e5f60718", role: "sketcher", profile: "default",
    notebook: "bridgeland-stability", latency_ms: 42.5, cache_layer: "tier1",
    result_bytes: 2048, k: 5, corpus_version: 1690,
    phases_ms: { cache_probe: 1.2, embed: 18.3, ann: 20.1 },
  },
  {
    seq: 2, ts: T0 + 20, tool: "get_chunk", status: "ok", error_code: null,
    session_id: "a1b2c3d4e5f60718", role: "sketcher", profile: "default",
    notebook: null, latency_ms: 3.1, cache_layer: "tier2",
    result_bytes: 4096, k: null, corpus_version: 1690,
  },
  {
    seq: 3, ts: T0 + 30, tool: "search_papers", status: "cap", error_code: "RETRIEVAL_CAP_REACHED",
    session_id: "a1b2c3d4e5f60718", role: "sketcher", profile: "default",
    notebook: null, latency_ms: 0.4, cache_layer: null,
    result_bytes: null, k: 5, corpus_version: null,
  },
  {
    seq: 4, ts: T0 + 40, tool: "lean_verify", status: "error", error_code: "RuntimeError",
    session_id: "0f1e2d3c4b5a6978", role: "tactician", profile: "pipeline",
    notebook: null, latency_ms: 130.9, cache_layer: null,
    result_bytes: null, k: null, corpus_version: null,
  },
];

export const FIXTURE_SESSIONS: SessionRow[] = [
  {
    session_id_prefix: "a1b2c3d4e5f60718",
    created_at: T0 - 600,
    last_seen_at: T0 + 30,
    roles_seen: ["sketcher"],
    counts: { search_papers: 3, get_chunk: 1 },
    caps: {
      search_papers: { limit: 3, used: 3, remaining: 0 },
      get_chunk: { limit: 4, used: 1, remaining: 3 },
    },
    hourly: { used: 4, limit: 1000, window_seconds: 3600 },
  },
  {
    session_id_prefix: "0f1e2d3c4b5a6978",
    created_at: T0 - 7200,
    last_seen_at: T0 - 3600,
    roles_seen: ["tactician", "fixer"],
    counts: { search_papers: 1 },
    caps: { search_papers: { limit: 3, used: 1, remaining: 2 } },
    hourly: { used: 1, limit: 1000, window_seconds: 3600 },
  },
];

export const FIXTURE_INGEST: Ring<IngestEventRow> = [
  { seq: 1, ts: T0 + 100, kind: "ingest", slug: "bridgeland-stability", stage: "preflight", phase: "finished", run_id: 3 },
  { seq: 2, ts: T0 + 110, kind: "ingest", slug: "bridgeland-stability", stage: "chunk", phase: "finished", run_id: 3, detail: { papers_ok: 2 } },
  { seq: 3, ts: T0 + 120, kind: "ingest", slug: "bridgeland-stability", stage: "run", phase: "finished", run_id: 3 },
  { seq: 4, ts: T0 + 130, kind: "parse", slug: "spectral-textbook", stage: "mineru", phase: "failed", run_id: 9, detail: { error: "exit 1" } },
];

function page<T>(items: Ring<T>, q: { limit?: number; since_seq?: number }): ObsPage<T & { seq: number; ts: number }> {
  const filtered =
    q.since_seq !== undefined ? items.filter((i) => i.seq > q.since_seq!) : items;
  const newestFirst = [...filtered].reverse();
  const limit = q.limit ?? 100;
  return {
    format_version: 1,
    items: newestFirst.slice(0, limit),
    total: newestFirst.length,
    limit,
    offset: 0,
    latest_seq: items.length > 0 ? items[items.length - 1].seq : 0,
  };
}

export interface FakeObsWorld {
  logs: Ring<LogRecord>;
  requests: Ring<RequestEvent>;
  sessions: SessionRow[];
  ingest: Ring<IngestEventRow>;
  status: { status: string; corpus_version: number | null } | null;
  /** Flip to simulate the A1 spine (all four GETs 404). */
  unavailable: boolean;
  /** Flip to simulate transient failures. */
  failing: boolean;
}

export function makeFakeObs(overrides: Partial<FakeObsWorld> = {}): {
  api: ObsApi;
  world: FakeObsWorld;
} {
  const world: FakeObsWorld = {
    logs: [...FIXTURE_LOGS],
    requests: [...FIXTURE_REQUESTS],
    sessions: [...FIXTURE_SESSIONS],
    ingest: [...FIXTURE_INGEST],
    status: { status: "ready", corpus_version: 1690 },
    unavailable: false,
    failing: false,
    ...overrides,
  };
  function guard<T>(make: () => ObsResult<T>): Promise<ObsResult<T>> {
    if (world.unavailable) return Promise.resolve({ kind: "unavailable" });
    if (world.failing) {
      return Promise.resolve({ kind: "error", detail: "GET failed (503)" });
    }
    return Promise.resolve(make());
  }
  const api: ObsApi = {
    requests: (q = {}) => guard(() => ({ kind: "ok", page: page(world.requests, q) })),
    logsTail: (q = {}) => guard(() => ({ kind: "ok", page: page(world.logs, q) })),
    sessions: () =>
      guard(() => ({
        kind: "ok",
        page: {
          format_version: 1,
          items: world.sessions,
          total: world.sessions.length,
          limit: 100,
          offset: 0,
        },
      })),
    ingestEvents: (q = {}) => guard(() => ({ kind: "ok", page: page(world.ingest, q) })),
    status: () => Promise.resolve(world.status),
  };
  return { api, world };
}

/** Scriptable EventSource double (the IngestPanel.test pattern). */
export class FakeEventSource implements EventSourceLike {
  static instances: FakeEventSource[] = [];
  closed = false;
  onerror: ((this: unknown, ev: Event) => unknown) | null = null;
  private listeners: Record<string, ((ev: MessageEvent) => void)[]> = {};

  constructor(public url: string) {
    FakeEventSource.instances.push(this);
  }

  static reset() {
    FakeEventSource.instances = [];
  }

  addEventListener(type: string, l: (ev: MessageEvent) => void) {
    (this.listeners[type] ??= []).push(l);
  }

  close() {
    this.closed = true;
  }

  emit(type: string, payload: unknown) {
    for (const l of this.listeners[type] ?? []) {
      l({ data: JSON.stringify(payload) } as MessageEvent);
    }
  }

  fail() {
    this.onerror?.call(undefined, new Event("error"));
  }
}
