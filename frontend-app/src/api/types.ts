/**
 * Hand-maintained response-body types for the /api/v1 surface.
 *
 * The IF-1 dump types every route/verb/parameter, but the v1 handlers
 * return plain dicts, so the generated `paths` types carry untyped
 * response bodies (`additionalProperties: true`). These interfaces
 * mirror the actual handler shapes (server/routes/api_v1.py `_page`
 * envelope; server/notebooks_store.py row fields) and are validated
 * against the mock fixtures in src/api/client.test.ts. When WS-A adds
 * response models to the dump, these narrow away.
 */

export interface NotebookRow {
  slug: string;
  display_name: string;
  lancedb_path: string;
  created_at: string;
  notebook_kind: string;
  parse_status: string;
  parse_error: string | null;
  parsed_html_path: string | null;
  discovery_category: string | null;
  description: string | null;
}

export interface PageEnvelope<T> {
  format_version: number;
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

export interface StatusBody {
  status: string;
  corpus_version: number | null;
}

/** Junction row from store.list_papers (added_at DESC, paper_id ASC). */
export interface PaperRow {
  paper_id: string;
  added_at: string;
}

/**
 * GET /api/v1/notebooks/{slug}/health — the drift report behind three
 * Stage-1 errata (211 rec 4/7). The marker_created_at / *_version
 * provenance fields are the arx-b2 additive MINOR (marker created_at
 * + chunker/embedder versions so the detail page renders the full
 * corpus-version.json stat block); optional so the client tolerates
 * an A1-spine server that predates them.
 */
export interface HealthResult {
  format_version: number;
  slug: string;
  status: "ok" | "drift" | "no_marker" | "malformed_marker";
  marker_chunk_count: number | null;
  actual_chunk_count: number | null;
  marker_paper_count: number | null;
  actual_paper_count: number | null;
  drift: number | null;
  corpus_version: number | null;
  detail: string | null;
  marker_created_at?: string | null;
  chunker_version?: string | null;
  embedder_version?: string | null;
}

/** POST /api/v1/notebooks/{slug}/reconcile-marker */
export interface ReconcileResult {
  format_version: number;
  slug: string;
  before: { chunk_count: number; paper_count: number };
  after: { chunk_count: number; paper_count: number };
  drift_resolved: number;
}

/** GET /api/v1/notebooks/{slug}/ingest/latest — plain-200 JSON poll;
 * `terminal` tells the poller when to stop (no htmx HTTP 286 here).
 *
 * Wire note: the server column value for a successful run is
 * `"success"` (NotebooksStore.INGEST_STATUS_SUCCESS, passed through by
 * api_v1 verbatim); useIngestProgress normalizes it to the SPA's
 * canonical `"succeeded"` at the poll seam, so consumers of this type
 * only ever observe `"succeeded"`. */
export interface LatestIngest {
  format_version: number;
  slug: string;
  status: "none" | "running" | "succeeded" | "failed" | string;
  terminal: boolean;
  run_id?: number;
  started_at?: string | null;
  finished_at?: string | null;
  exit_code?: number | null;
  stderr_tail?: string | null;
}

/** GET /api/v1/notebooks/{slug}/parse-status (textbook kind). */
export interface ParseStatus {
  format_version: number;
  slug: string;
  notebook_kind: string;
  parse_status: "skipped" | "pending" | "running" | "complete" | "failed" | string;
  parse_error: string | null;
  parsed_html_path: string | null;
}

/** POST /api/v1/notebooks/{slug}/discover — EPHEMERAL propose-only queue. */
export interface DiscoverCandidate {
  paper_id: string;
  title: string;
  abstract_head: string;
  submitted_date: string;
}

export interface DiscoverResult {
  format_version: number;
  slug: string;
  candidates: DiscoverCandidate[];
  count: number;
}

/** POST /api/v1/notebooks (201) — the delegated create body + stamp. */
export interface CreateNotebookResult {
  format_version: number;
  slug: string;
  display_name: string;
  lancedb_path: string;
  notebook_kind: string;
  created_at: string;
}

/** PATCH /api/v1/notebooks/{slug} — returns the STORED (control-char-
 * stripped) display_name, which the UI must echo, not its own input. */
export interface RenameResult {
  format_version: number;
  slug: string;
  display_name: string;
}

/** PATCH /api/v1/notebooks/{slug}/topic */
export interface TopicUpdateResult {
  format_version: number;
  slug: string;
  discovery_category: string;
  description: string;
}

/** POST /api/v1/notebooks/{slug}/papers (201) */
export interface AddPaperResult {
  format_version: number;
  slug: string;
  paper_id: string;
}

/**
 * One `event: ingest` frame from the IF-2 multiplexed SSE stream
 * (GET /api/v1/events/stream?topics=ingest — WS-A A3 contract:
 * stages preflight→mineru→latexml→chunk→embed→index, phases
 * started|finished|failed, plus run/queue pseudo-stages). Absent on
 * the A1 spine this slice builds against — the stepper falls back to
 * tri-state from the poll (the hook degrades, never breaks).
 */
export interface IngestStageEvent {
  kind: "ingest" | "parse" | string;
  slug: string;
  stage: string;
  phase: "started" | "finished" | "failed" | string;
  run_id?: number;
  paper_id?: string;
  detail?: Record<string, unknown>;
  seq?: number;
}
