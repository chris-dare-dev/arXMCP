# Changelog

The notable changes to arXMCP. The format loosely follows
[Keep a Changelog](https://keepachangelog.com/), and the project adheres to
[Semantic Versioning](https://semver.org/) (currently in the `0.x`
pre-release line — see [docs/releasing.md](docs/releasing.md)).

Two layers live here:

- **Releases** — versioned, dated sections (`## [x.y.z] — date`) and the
  rolling `## Unreleased` section above them. This is the layer that maps to
  git tags and [GitHub Releases](https://github.com/chris-dare-dev/arXMCP/releases).
- **Epic history** — the longer-form, epic-grain record (E01–E14) below the
  releases, kept because arXMCP shipped its substrate epic-by-epic before
  adopting tagged releases.

Per-milestone detail is in
[`.claude/notes/milestones/<EXX_SYY>/`](.claude/notes/milestones/); per-commit
detail is in `git log`.

> **First release.** `v0.1.0` will tag the current pre-release substrate
> (E01–E14). It is prepared but not yet cut — see
> [docs/releasing.md](docs/releasing.md).

---

## Unreleased

### 2026-07-31 — corpus-freshness seam (issue #207)

The server no longer serves a stale corpus after an ingest. Previously,
clicking **Ingest** in the `/ui/` console completed the subprocess and
bumped `corpus-version.json` while the running server kept serving its
memoized pre-ingest table — and echoed the OLD `corpus_version` in the
response envelope as truth. `server/corpus.py` declared this
invalidation a MUST and asserted the implementation honored it; the
keying half was real, the invalidation half had no implementation at
all.

- **NEW: `server/corpus_freshness.py`** — `FreshnessGate` (throttle +
  single-flight, injectable clock) and `read_marker_off_loop`. The
  module docstring is where "who owns corpus agreement" is answered,
  including the boundary it does NOT cover: only the LanceDB dataset
  carries a version marker, so the other seven on-disk stores are
  re-opened at whatever state they are in rather than proven to agree.
  (That census also corrects the issue's store count: eight, not
  seven — `documents.db` is a fifth SQLite store.)
- **NEW: `Resources._bind_corpus`** — the single post-startup corpus
  binding path, shared by `late_bind` and the new rebind. Builds every
  handle before publishing any, so a failed rebind keeps serving the
  previous corpus intact. Also recomputes `startup_chunk_count` /
  `startup_unindexed_rows` and re-opens the definitions, equations,
  theorem-names and paper-metadata handles, which `late_bind` never did.
- **NEW: `Resources.on_ingest_complete`** — wired to the ingest
  tracker's `on_success_callback` in place of `late_bind`, which
  returned `False` immediately once bootstrap mode was off, so every
  ingest after the first invalidated nothing.
- **NEW: request-path probe** at the MCP tool-dispatch seam, catching
  out-of-band ingest (`make ingest`, a terminal `notebook_ingest` run,
  a backup restore). Throttled by
  `ARXMCP_CORPUS_FRESHNESS_INTERVAL_SECONDS` (default 2s; negative
  disables the pull path — the push path stays on).
- **FIXED: `purge_other_corpus_versions` had zero callers repo-wide.**
  Now invoked via `RetrievalCache.open(purge_other_versions=True)` on
  every rebind, before the Tier-1 rehydrate.
- **FIXED: Tier-3 survived a corpus bump.** Its key is
  `sha256(embedding + candidate_ids + reranker_version)` with no corpus
  version, so a re-ingest that rewrites a chunk's body under the same
  `chunk_id` left a reachable, stale rerank memo. New
  `RetrievalCache.invalidate_corpus_version` drops it. Tier-2 had the
  same hole when #207 was written; #204 closed it first by folding
  `corpus_version` into the scope fingerprint, so clearing Tier-2 here
  is now reclamation rather than correctness.
- **Constitution:** `.claude/notes/06-mcp-server-design.md` rule 2
  ("the MCP server does NOT auto-switch") is marked SUPERSEDED with
  the reasoning and the trade-off that survives it.

### 2026-05-22 — `proof-verify` handler-wiring (m9): UI ingest trigger + status polling

Track-D frontend is complete. The operator can now click "Ingest
now" in the per-notebook UI, see live status updates via htmx
polling, and read the last 1 KB of stderr on failure — all without
the daemon's event loop ever blocking. The MCP surface and
`EXPECTED_TOOL_SCHEMA_SHA256` are unchanged.

- **NEW: `server/ingest_tracker.py`** (~250 LOC) — `IngestTaskTracker`
  class that spawns `python -m tools.notebook_ingest <slug>` as a
  subprocess via `asyncio.create_subprocess_exec`, tracks the
  `asyncio.Task` in `_tasks: dict[str, asyncio.Task]` to prevent
  GC, and updates the DB row on completion via a `done_callback`.
  Bounded by `asyncio.Semaphore(1)` so at most one ingest runs
  across the daemon at any time (FM-1 closure). Subprocess (NOT
  in-process `to_thread`) was chosen so an ingest crash cannot
  crash the daemon AND stderr capture is native via
  `asyncio.subprocess.PIPE` (AC #2 explicit requirement). Cold-
  start cost (~30s BGE-M3 reload) is amortized over minutes-to-
  hours of ingest.
- **NEW: `prepare_stderr_tail` pipeline** — truncate to 1024 bytes
  → redact absolute paths down to `var/arxmcp/` via regex → decode
  → HTML-escape. Pipeline closes both FM-3 (Threat 2 — `<retrieved_chunk>`
  literal escape) and FM-4 (AC #2 — no absolute paths beyond
  `var/arxmcp/` leak into the UI).
- **NEW: 2 REST routes** in `server/routes/notebooks.py`:
  - `POST /ui/api/notebooks/{slug}/ingest` — 202 Accepted; returns
    an HTML fragment that the htmx UI swaps into `#ingest-status`.
    Sequencing: validate → 409-check → INSERT row → spawn task →
    return (FM-7 closure — row exists before first poll).
  - `GET /ui/api/notebooks/{slug}/ingest/latest` — htmx polling
    endpoint. Returns 200 for `running` / `none`, **HTTP 286 for
    terminal states** (`success` / `failed`). HTTP 286 is the
    htmx-documented canonical polling-stop signal; the client
    stops polling automatically on terminal-state response,
    zero JS required.
- **NEW: `NotebooksStore` additive migration v1 → v2** —
  `notebook_ingest_runs` table added via `CREATE TABLE IF NOT
  EXISTS` (NOT the original DROP-AND-RECREATE pattern, which
  would wipe live notebook metadata). Schema: `(id, slug, status,
  started_at, finished_at, exit_code, stderr_tail)` with FK
  cascade on `slug`. The migration ladder is now staged per-
  version so a future bump must explicitly add a v2→v3 branch.
- **NEW: 5 new `NotebooksStore` methods** —
  `insert_ingest_run`, `update_ingest_run`, `get_latest_ingest_run`,
  `has_running_ingest` (cross-restart 409 fallback),
  `mark_orphaned_runs_failed` (FM-5 startup-recovery: marks any
  `running` row older than 1 hour as `failed` so a daemon-crash-
  mid-ingest doesn't leave the row stuck in limbo).
- **EDIT: `server/main.py`** — lifespan opens `IngestTaskTracker`
  AFTER `NotebooksStore` AND after running orphan-recovery.
  Lifespan finally calls `tracker.shutdown(timeout_seconds=5.0)`
  to cancel in-flight tasks before closing the store.
- **EDIT: `frontend/templates/notebook_detail.html`** — added
  "Ingest now" form + `<div id="ingest-status">` placeholder
  with `hx-trigger="load"` so the page loads the latest status
  on first paint AND polls every 2s once a run is in flight.
- **Out-of-scope assertion (AC #4)** — `tests/test_m9_scope_invariants.py`
  greps `frontend/` for `iframe|preview` and fails if any match.
  Defends against an accidental m10 (sandboxed iframe preview)
  leak into m9.
- **Test surface** — +23 net-new tests:
  - `tests/test_ingest_endpoint.py` (~22 tests) — trigger happy
    path, 409 collision, path redaction (5 parametrized cases),
    HTML escape (Threat 2), latest endpoint (none/404/missing
    notebook), HTTP 286 on terminal (success + failure),
    additive migration preserves rows + creates new table,
    orphan recovery, direct tracker unit tests.
  - `tests/test_m9_scope_invariants.py` (1 test) — grep-based
    AC #4 defense.

`make test`: **2461 passed** (+23 from m8), 9 skipped, 1 xfailed.
Ruff clean. `EXPECTED_TOOL_SCHEMA_SHA256` unchanged (AC: no new
MCP tools).

### 2026-05-22 — `proof-verify` handler-wiring (m8): htmx + Jinja2 UI shell, ar5iv upload

First operator-facing browser UI for the per-notebook workflow.
Single-page htmx app rendered server-side via Jinja2; vendored htmx
(no Node toolchain, no CDN runtime fetch); multipart upload endpoint
for ar5iv HTML files. The MCP surface and `EXPECTED_TOOL_SCHEMA_SHA256`
are unchanged.

- **NEW: `frontend/templates/`** — `base.html` + `index.html` +
  `notebook_detail.html`. Templates render via FastAPI's
  `Jinja2Templates` with an EXPLICITLY constructed `jinja2.Environment`
  + `autoescape=select_autoescape(html, htm, xml, default_for_string=True)`
  (m8 synthesis: explicit > implicit; the Starlette default protects
  the same extensions but the explicit form prevents a future
  template-loader change from silently disabling autoescape).
- **NEW: `frontend/static/`** — vendored `htmx.min.js` (htmx 2.0.10,
  0BSD-licensed, 51 KB) with a header comment naming the version
  + source URL (`https://cdn.jsdelivr.net/npm/htmx.org@2.0.10/...`)
  + license. Plus `app.css` — minimal CSS, no external fonts, no
  CDN imports. AC #5 satisfied: zero internet fetches at runtime.
- **NEW: `server/routes/ui.py`** — `GET /ui/` (landing page;
  notebook list + create form) and `GET /ui/notebooks/{slug}`
  (detail page; paper list + URL-paste form + drag-drop upload
  card). Both routes are wired via `app.include_router(ui_router,
  prefix="/ui")`.
- **NEW: upload endpoint** — `POST /ui/api/notebooks/{slug}/papers/upload`
  in `server/routes/notebooks.py`. Accepts multipart with form
  fields `paper_id` (validated via `is_valid_paper_id` — m1 rect
  F3 `\Z`-anchor hardening inherited) and `file` (the ar5iv HTML).
  On-disk filename is derived EXCLUSIVELY from `paper_id` (m8 FM-4
  path-traversal defense — `file.filename` is used ONLY for logging).
  Magic-byte sniff (first 16 bytes start with `<!` or `<h`) rejects
  forged-extension non-HTML uploads with HTTP 422 (FM-2). Atomic
  write via `os.replace()` so readers never see a partial file
  (FM-5). Duplicate `(slug, paper_id)` returns HTTP 200 with the
  on-disk file updated (idempotent overwrite — the upload itself
  succeeded; the junction row already existed).
- **AC #3: ar5iv URL normalizer extension** — m7's
  `_arxiv_url_to_paper_id` accepted only `arxiv.org/abs/<id>`; m8
  extends `_ACCEPTED_HOSTS` to also accept
  `ar5iv.labs.arxiv.org/html/<id>` via a new `_HOST_PATH_PREFIX`
  dispatch dict. The m7 happy-path tests still pass; the m7
  "ar5iv-rejected" test was inverted to assert ar5iv is now
  accepted (moved to `tests/test_ui_html_pages.py::TestAr5ivUrlNormalizer`).
- **AC #4: `RequestBodySizeLimitMiddleware.prefix_caps`** —
  per-prefix cap-override mechanism. Default cap stays at 1 MB;
  the m8 wiring sets `prefix_caps={"/ui/api/notebooks":
  10 * 1024 * 1024}` so ar5iv uploads (typically 100 KB–5 MB,
  occasionally up to 10 MB) pass while every other path keeps the
  1 MB ceiling. Prefix-match form (`path == p or path.startswith(p +
  "/")`) — NOT substring; FM-3 parity with the m7 SecFetchSite
  carve-out so `/uiOTHER` and `/evil-ui/x` stay at the default cap.
- **Static mount + `_BYTE_CAP_EXEMPT_PREFIXES` extension** —
  `app.mount("/ui/static", StaticFiles(...))` for the vendored
  assets. `/ui` added to `_BYTE_CAP_EXEMPT_PREFIXES` so the 51 KB
  htmx file (well under 256 KB but defensive) and large notebook-
  list HTML pages bypass the response-body cap.
- **Explicit deps** — `jinja2>=3.1.3` (closes CVE-2024-22195 in
  `xmlattr`) and `python-multipart>=0.0.18` (closes CVE-2024-53981
  multipart DoS) added to `pyproject.toml` with per-line comments.
  Both were transitive via `mcp`; the project's "no implicit deps"
  discipline requires explicit declaration (the `pyyaml` comment
  is the precedent).
- **Test surface** — +67 net-new tests across three new files
  + ~3 from m7-rect edits to existing files = +70 total suite
  delta (corrected from initial draft per m8 rect F5):
  - `tests/test_ui_html_pages.py` (27 tests) — landing page,
    detail page, static assets, path-traversal defense via
    Starlette `StaticFiles`, ar5iv URL acceptance, Jinja2
    autoescape XSS-defense.
  - `tests/test_upload_handler.py` (29 tests) — happy path,
    magic-byte sniff (15 parametrized cases incl. PNG/PDF/ZIP/EXE),
    filename sanitization (FM-4 dot-dot + shell-metachar cases),
    atomic write, duplicate upload semantics, paper_id validation
    (incl. m1-rect-F3 trailing-newline rejection), notebook
    existence, empty-file rejection.
  - `tests/security/test_request_body_prefix_caps.py` (11 tests)
    — the middleware extension itself: default cap on non-carve
    paths, raised cap on `/ui/api/notebooks/*`, prefix-not-
    substring matching enforced (`/ui/api/notebooksOTHER` stays at
    default), exceeding the raised cap still 413s, direct unit
    tests of the `_effective_max_bytes` helper.
- **`security-threat-model-coverage.md`** extended under Threat 4
  to cite the new test file (the threat-coverage invariant test
  passes).

`make test`: **2425 passed** (+70 from m7), 9 skipped, 1 xfailed.
Ruff clean. `EXPECTED_TOOL_SCHEMA_SHA256` unchanged (AC: no new
MCP tools).

### 2026-05-22 — `proof-verify` handler-wiring (m7): notebook REST API + SecFetchSite carve-out

First-cut HTTP UI surface for the per-notebook workflow. Adds the
six routes the m8 htmx UI will consume, backed by a new SQLite table
file. The MCP surface is unchanged — `EXPECTED_TOOL_SCHEMA_SHA256`
remains pinned, no new MCP tools shipped.

- **NEW: `server/notebooks_store.py`** — `NotebooksStore` class
  mirroring `cache_sqlite.py::Tier1Store` (asyncio.to_thread +
  asyncio.Lock + WAL mode). Two tables: `notebooks(slug PRIMARY KEY,
  display_name, lancedb_path, created_at)` and
  `notebook_papers(slug, paper_id, added_at, FOREIGN KEY ON DELETE
  CASCADE)`. `PRAGMA foreign_keys = ON` per connection so the
  cascading delete fires (FM-7 closure). Backed by a SEPARATE DB file
  (`var/arxmcp/cache/notebooks.db`) — NOT in the existing
  `retrieval.db` — so a schema-version bump on either side doesn't
  trigger the OTHER's DROP-AND-RECREATE migration (FM-6).
- **NEW: `server/routes/notebooks.py`** — six FastAPI routes mounted
  at `/ui/api` via `app.include_router(notebooks_router,
  prefix="/ui/api")`:
  - `GET /notebooks` — list (ordered by `created_at DESC`)
  - `POST /notebooks` — create (201; 409 on duplicate slug)
  - `DELETE /notebooks/{slug}` — metadata-only (204; on-disk
    `var/arxmcp/notebooks/<slug>/` survives — destructive wipe is
    `tools/notebook_purge.py`'s job, per the m7 brief deletion
    semantics resolved 2026-05-21)
  - `GET /notebooks/{slug}/papers` — list junction rows
  - `POST /notebooks/{slug}/papers` — normalize arxiv URL via new
    `_arxiv_url_to_paper_id()` helper (host whitelist + `/abs/`
    prefix + `is_valid_paper_id()` post-validation per m1 rect F3
    hardening), insert junction row
  - `DELETE /notebooks/{slug}/papers/{paper_id}` — single-row
    removal (uses `{paper_id:path}` to accept the embedded slash in
    old-style IDs like `hep-th/0001234`)
- **NEW: `SecFetchSiteMiddleware` `exempt_prefixes` arg** — path-
  prefix carve-out so the htmx UI's same-origin POSTs to
  `/ui/api/*` pass without 403'ing on `Sec-Fetch-Site: same-origin`.
  Wired with `exempt_prefixes=("/ui",)` in `server/main.py`. The
  MCP surface (`/mcp`) is NOT in any exempt prefix and continues
  rejecting same-origin (the DNS-rebinding defense from
  `08-security-observability-ops.md` Threat 5 is preserved on the
  MCP surface).
- **Config field**: `Config.notebooks_db_path: Path` defaulting to
  `var/arxmcp/cache/notebooks.db`. The custom env-var scanner
  (`_scan_unknown_arxmcp_env_vars`) picks the field up automatically
  via `Config.model_fields`.
- **Test surface**: +44 tests across
  `tests/test_notebook_api.py` (CRUD, URL normalizer, FK cascade,
  POST-after-delete, store persistence) and 15 tests in
  `tests/security/test_sec_fetch_site_carveout.py` (the carve-out
  itself: `/mcp` still rejects same-origin; `/ui/api/*` accepts it;
  prefix-not-substring matching enforced so `/uiOTHER` and
  `/evil-ui/...` stay rejected — FM-3 closure).
- **`security-threat-model-coverage.md`** extended with the m7
  carve-out under Threat 5 (origin spoofing); the threat-coverage
  invariant test now sees `test_sec_fetch_site_carveout.py` as
  cited.

`make test`: **2355 passed** (+59 from m4 baseline), 9 skipped, 1
xfailed. Ruff clean. `EXPECTED_TOOL_SCHEMA_SHA256` unchanged
(verified — no new MCP tools).

### 2026-05-22 — `proof-verify` handler-wiring (m4): notebook-fixture validator + BM25 sentinels

Closes the operational integration for the two user-curated math notebooks
(bridgeland-stability — 39 papers, shimura-varieties — 12 papers). The
per-notebook LanceDB indices were already populated during the m5 spike
(which ran the rerank-lift evaluation against the live notebook trees);
m4's job was to verify them, close the BM25 sentinel gap that m6's F2
closure designed for, and ship a small validator for the per-notebook
`queries.json` fixtures.

- **New: `tools/validate_notebook_fixtures.py`** — standalone validator
  for the per-notebook `queries.json` schema. Separate from the existing
  `tools/validate_eval_fixtures.py` (the global eval validator has a
  closed-schema guard against extra top-level keys, and the notebook
  fixtures use paper-level relevance — `expected_relevant_papers:
  ["<arxiv_id>", ...]` — whereas the global validator expects
  chunk-level `relevant_chunks: [{chunk_id, relevance}, ...]`). The new
  validator enforces top-level + per-query required keys, slug match,
  `MIN_NOTEBOOK_QUERIES = 5` floor, valid arXiv-ID format on every
  `expected_relevant_papers` entry, and membership in the notebook's
  `papers.txt`. 29 tests at `tests/tools/test_validate_notebook_fixtures.py`
  (including happy-path smoke tests against both real notebooks).
- **BM25 sentinels closed** — `var/arxmcp/index/bm25/v157/.notebook_slug`
  (= `bridgeland-stability`) and `var/arxmcp/index/bm25/v49/.notebook_slug`
  (= `shimura-varieties`) written manually. These BM25 indices were
  built BEFORE the m6 F2 sentinel logic landed, so they were sitting
  unclaimed; the manual write closes the latent BM25 collision risk a
  future third notebook would expose.
- **Both notebooks verified end-to-end via daemon launch + `tools/list`** —
  bridgeland daemon on port 7733 and shimura daemon on port 7734 each
  reported the canonical 7 tools and returned notebook-specific paper
  IDs on a sanity-check `search_papers` call (1309.4265, 1607.01262 for
  bridgeland; 2310.16184, 1105.0887 for shimura). Smoke logs at
  `var/arxmcp/notebooks/<slug>/ops/daemon-m4-smoke.log`.
- **AC arithmetic correction** — the brief said `paper_count >= 80` but
  was written for a 100-paper notebook size. The actual notebooks are
  39 and 12 papers; m4 records the verified `COUNT(DISTINCT paper_id)`
  (39 and 12 exact) against the corrected 80%-of-actual thresholds
  (≥ 31 and ≥ 10). The `corpus-version.json::paper_count = 1` artifact
  (per-batch count, not cumulative) is noted in the m4 deviations.

### 2026-05-21 — `proof-verify` handler-wiring (m1 + m2): `paper_id` filter goes live in `search_papers`

The downstream `/proof-verify` per-notebook pipeline can now scope a
`search_papers` call to a specific arXiv paper id, and the response echoes
back which filter was actually honored. The hybrid + rerank pipeline
modules (E07) remain unwired pending a 100-paper curated fixture proving
measurable lift; only the cheap filter-wiring half of the pivot has landed.

- **m1** — `search_papers` now honors `filters={"paper_id": "<id>"}` (or a
  list of ids) end-to-end. The string form is canonicalized to a sorted
  one-element list before predicate construction so a single-id call and
  a list-of-one call share a cache key (F4 from m1 critique). Predicates
  are built with `LanceDB.where(predicate, prefilter=True)` and combined
  with the BGE-M3 ANN search; unsupported filter keys are surfaced in
  `filter_warnings` with per-key strings and capped via
  `MAX_FILTER_KEY_LEN=64` so a malicious key cannot blow the response
  envelope (F2 from m1 critique). The `paper_id` value list is capped at
  `MAX_PAPER_ID_FILTER_ITEMS=100` and SQL-escaped via single-quote
  doubling. Trailing-newline rejection in `is_valid_paper_id` (and the
  parity copy in `ingest/chunker.py` + `tools/validate_eval_fixtures.py`)
  was hardened by replacing the regex `$` anchor with `\Z` (F3 from m1
  critique).
- **m2** — Filtered responses now carry a `filters_applied` object that
  echoes the canonical form of every key actually honored (currently just
  `paper_id`). The field is absent — not null — when no filter was passed,
  preserving byte-stability for the no-filter cache hit. The echo is
  scoped to `SUPPORTED_FILTER_KEYS`; unsupported keys remain in
  `filter_warnings` and never appear in the echo (a regression guard
  pinned by `TestFiltersAppliedHelper.test_unsupported_keys_excluded_from_echo`).
  Schema bumped v8→v9; `TOOL_SCHEMA_VERSION` bumped 8→9; the
  `tools/list` byte-hash (`EXPECTED_TOOL_SCHEMA_SHA256` +
  `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH`) was re-pinned in lockstep via
  `pytest --update-tool-schema-hash`. The BP1 hash (`EXPECTED_BP1_SHA256`
  in `tests/test_prompts.py`) was NOT re-pinned: the canonical BP1
  surface measured by `_live_tools_payload` is `{name, description}` per
  tool only and does not include `_meta.tool_schema_version`, so the
  version bump does not drift this hash. See `server/tools.py::register_all`
  (m2 rect F6) for the orchestrator-side `_meta`-strip contract that
  preserves this property.
- **Out of scope (deferred):** The wider `degraded` / `degraded_reasons`
  schema-vs-runtime gap surfaced during m2 research is tracked as a
  future milestone; m2 deliberately did not widen scope. The hybrid +
  rerank wiring (m4 / m5) is gated on the 100-paper curated fixture
  proving measurable lift; the 2026-05-20 spike found dense-only already
  returns the right paper at top-1 on the 22-paper math.AG notebook.

### 2026-05-10 — Doc-layout consolidation

- Restricted root-of-repo Markdown to five files only: `README.md`,
  `CLAUDE.md`, `CHANGES.md`, `SECURITY.md`, `OWNERS.md`.
- Moved `TIER-GATES.md` from repo root to `.claude/TIER-GATES.md`.
- Moved `server/prompts.md` to `.claude/notes/prompts-bp-discipline.md`.
- Moved 7 internal-reference docs from `docs/` to `.claude/docs/`:
  `chunker-fixtures.md`, `eval-curation.md`, `model-policy.md`,
  `orchestrator-rules.md`, `proof-chain-workflow.md`,
  `retrieval-quality-report.md`, `snippet-contract.md`. Only
  `docs/install.md` (operator-facing) remains under `docs/`.
- Deleted `ROADMAP.md` (was a self-superseded redirect; the authoritative
  roadmap lives at `.claude/roadmap/README.md`).
- Updated test path constants in `tests/test_proof_chain.py`,
  `tests/test_snippet_contract.py`, `tests/test_model_selector.py`,
  `tests/test_prompts.py`, and `tests/test_tier_gates_doc.py` for the
  new locations. Dropped the `TestReadmeLinksTierGates` AC since
  TIER-GATES is no longer user-facing.
- Updated `Makefile` and `tools/validate_eval_fixtures.py` references.
- README rewritten to project scope only (what / how / layout); CLAUDE.md
  expanded with the new doc-placement rule and updated paths.
- New: `CHANGES.md`, `SECURITY.md`, `OWNERS.md`.

---

## E09 — Citation Graph (2026-05-10, SHIPPED — closes H7)

The agent runtime can now traverse the citation graph in 2 MCP rounds.

- **E09_S01** — Kùzu schema v1 + OpenAlex bulk citation ingest.
  Embedded graph at `var/arxmcp/index/kuzu/`; `kuzu==0.11.3` pinned
  exactly (upstream archived 2025-10-10). Two-pass resolution +
  citation; idempotent MERGE upserts; polite-pool User-Agent +
  `?mailto=`; atomic-write checkpoint; fetch-failure tracking;
  `oa_work_id` collision detection.
- **E09_S02** — INSPIRE-HEP per-paper enrichment (hep-th / math-ph).
  Schema bumped to v2 (`doi` / `journal_ref` / `inspire_id` columns).
  Split-writer pattern closes F4 from E09_S01 (OpenAlex owns prose;
  INSPIRE owns identifiers + bibliographic refs).
  COALESCE-in-ON-MATCH so a re-MERGE with NULL doesn't clobber
  previously stamped data.
- **E09_S03** — `server/graph_queries.py::cite_neighbors(chunk_id,
  depth, direction)` async library + `CitationNeighbor` dataclass.
  Variable-length Cypher with `relationships(p)` projection;
  Python-side dedup + filter + ordering; LanceDB batched chunk-id
  lookup with `kind="stmt"` priority fallback. Intra-paper `\ref{}`
  ingest pass (`ingest/intra_paper_refs.py`) populates
  `source="intra-paper"` self-edges.
- **E09_S04** — Documents and tests the 2-round agent pattern
  (`cite_neighbors` + bulk parallel `get_chunk`). Synthetic 50-paper
  graph perf gate: ≤500 ms for `depth=2`. Closes **H7**.

---

## E08 — Agent Runtime + Caching (SHIPPED)

- **E08_S01** — Python regex query router → 4 RouteTags
  (`LOOKUP`, `SYNTHESIS`, `VERIFICATION`, `AUTOFORMALIZATION`). Closes H1
  (no Sonnet planner).
- **E08_S02** — Role-as-user-turn-prefix; BP1+BP2 prompt-cache
  breakpoint placement; BP3 dropped (closes H2). Role prefixes ≤50
  tokens; closed-at-four-roles invariant.
- **E08_S03** — 3-tier MCP-side retrieval cache: SQLite exact memo +
  FAISS semantic-query memo + LRU rerank-set memo. Prometheus
  metrics; corpus-version keyed; fall-through-on-failure discipline.
- **E08_S04** — Tool-use ID canonicalization (`toolu_{counter:08d}`)
  + per-`Mcp-Session-Id` retrieval caps (3 search + 4 chunk).
- **E08_S05** — Model-selection policy: Haiku/Sonnet only, Opus
  forbidden in `server/` source. Verifier pass dropped (closes H10).

---

## E07 — Hybrid Retrieval (SHIPPED)

- **E07_S01** — Phase-1 BM25 over `body_tokens`.
- **E07_S02** — Phase-2 dual-ANN (`embedding_stmt` + `embedding_proof`) + RRF.
- **E07_S03** — Phase-3 BGE-reranker-v2-m3 cross-encoder, env-gated.
- **E07_S04** — End-to-end hybrid eval target nDCG@5 ≥ 0.80 (gate run
  pending fixture curation).

---

## E06 — MCP Server (SHIPPED)

- **E06_S01** — FastAPI + Streamable HTTP at `/mcp`; loopback bind;
  pure-ASGI middleware; `BodySizeCapMiddleware`; eager BGE-M3 startup.
- **E06_S02** — `arxmcp-shim` stdio↔HTTP bridge for Claude Code;
  byte-pass-through; loopback-only egress.
- **E06_S03** — 7 MCP tools registered (`search_papers`, `get_chunk`,
  `find_equation`, `get_definitions`, `find_lemma_by_name`,
  `get_paper`, `cite_neighbors`).
- **E06_S04** — 150-char snippet contract for `search_papers` rows;
  no summary field; no Citations API dependency.
- **E06_S05** — Origin validation, host validation, security headers,
  body-size caps.
- **E06_S06** — `tools/list` byte-stability test (closes BP1
  prompt-cache invariant at the wire).

---

## E05 — Eval Harness (SHIPPED; fixture curation pending)

- **E05_S01** — 20 hand-labeled `(query, chunk_id, relevance)` triples
  (fixture stub committed; curation per
  [`.claude/docs/eval-curation.md`](.claude/docs/eval-curation.md)).
- **E05_S02** — nDCG@5 + Recall@10 pytest harness with `--ndcg-min` flag.
- **E05_S03** — Tier-0 / Tier-1 gate documentation (now
  [`.claude/TIER-GATES.md`](.claude/TIER-GATES.md)).

---

## E04 — Vector Store (SHIPPED)

- **E04_S01** — LanceDB `chunks` v1 schema (dual `embedding_stmt` +
  `embedding_proof`; `embedding_eq` reserved); HNSW + scalar indices;
  idempotent `merge_insert(on="chunk_id")`.
- **E04_S02** — MVCC via `dataset.checkout(version=N)`. Closes the
  symlink-atomic-swap MEDIUM finding.
- **E04_S03** — `corpus_version` marker file + reader cache key.
- **E04_S04** — BM25 index over `body_tokens` (closes H4 — no fictional
  Tantivy LaTeX analyzer).

---

## E03 — Embedder (SHIPPED)

- **E03_S01** — BGE-M3 dual-column encoder; pinned commit SHA;
  `trust_remote_code=False`; safetensors-only (Threat 6 closure).
- **E03_S02** — Idempotent re-embed.
- **E03_S03** — Singleflight wrapper for query encoding (closes the
  GIL-on-embedder MEDIUM finding).

---

## E02 — Chunker (SHIPPED)

- **E02_S01** — Theorem-aware structural chunker; dual 512-token
  statement + proof chunks (closes H3).
- **E02_S02** — Per-paper preamble macro extractor.
- **E02_S03** — `body_tokens` regex pre-tokenizer.
- **E02_S04** — Chunker version stamping + content-addressable
  `chunk_id` (`arxiv:<paper_id>:<sha256[:16]>`).
- **E02_S05** — Chunker fixture suite + regeneration runbook
  ([`.claude/docs/chunker-fixtures.md`](.claude/docs/chunker-fixtures.md)).

---

## E01 — Vertical Slice (DONE)

- Repo skeleton + 50-paper math.AG seed corpus
  (`tools/seed-papers.txt`) + single-paper hand-fetch
  (`tools/fetch_one_paper.py`) + seed-corpus walk
  (`tools/fetch_seed.py`). Per-milestone subspecs (S04–S10) were
  superseded by E02–E06 milestones and are recorded as
  `SUPERSEDED_BY` in
  [`.claude/roadmap/README.md`](.claude/roadmap/README.md).

---

## Epic status

E01–E11, E13, E14 have **shipped** (E12 scoped-out, folded into E11);
specialized indices (E10), scale cutover (E11), security audit (E13), and
observability/ops (E14) are all in `main`. A handful of Tier-5/6+ follow-ups
remain unstarted. See [`.claude/roadmap/README.md`](.claude/roadmap/README.md)
for the authoritative per-milestone status.

---

## Releases

No git tags cut yet; `v0.1.0` is prepared (see
[docs/releasing.md](docs/releasing.md)). Once releases exist, link each
version section to its compare range, e.g.:

- [Unreleased]: https://github.com/chris-dare-dev/arXMCP/compare/v0.1.0...HEAD
- [0.1.0]: https://github.com/chris-dare-dev/arXMCP/releases/tag/v0.1.0
