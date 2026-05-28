# Critique — notebook-retrieval-m2

**Critic:** adversary
**Generated:** 2026-05-28T00:00:00Z
**Commit range:** 12c86640fca88913ed5a36acff6470ab9a9d77d5..2f341ba030f5669837191de2be3e0a1397fbf846
**Verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES: the core routing + cache-isolation design is sound and the
  no-notebook path is provably byte-identical, but one common-path filter
  combination (`notebook` + `source_kind`) raises an uncaught 500.
- 0 CRITICAL, 1 HIGH, 2 MEDIUM, 1 LOW.
- Highest-risk: `server/handlers/search.py:472-475` + `:604-634` — a
  `source_kind` predicate is built unconditionally and run against a notebook
  table that lacks the column (verified live: raises `LanceError(Schema)`).
- The `source_kind`-absent guard was applied to the OUTPUT read
  (`_arrow_to_rows`, `:869`) but NOT to the WHERE predicate path — the
  implementer fixed half of the same gap.
- Cache byte-stability axis: clean for AC3/AC4 — `notebook` is genuinely
  retained through `_canonicalize_filters` (`:339`) and excluded from
  `filters_applied` (`:304-308`); X-1/X-2 confirmed unchanged (schema + prompt
  tests green, `TOOL_SCHEMA_VERSION` still 15).
- Deviation #3 (shared corpus_version in key) is a real but TTL-bounded
  self-staleness and is honestly scoped; it does NOT cross-serve between
  notebooks. It IS a documented departure from the locked synthesis §1.2.
- Threat-1 (path traversal) is double-validated (handler boundary + registry)
  with no TOCTOU; security, no-fork, local-first, MCP-spec, tier-sequencing
  axes all clean.

## Severity calibration

| level | meaning | rectification phase action |
|---|---|---|
| CRITICAL | data loss, security regression, broken core invariant, or shippable-bug-in-production-now | always fix in Phase 4 |
| HIGH | wrong behavior reachable on common path, or load-bearing constraint violated | always fix in Phase 4 |
| MEDIUM | subtle correctness, missing test, latent foot-gun | fix only if cheap (≤ 30 LOC, small test surface) |
| LOW | style, naming, micro-perf | defer (record under `deferred_findings`) |

## Findings

### F1 — source_kind filter + notebook routing raises an uncaught 500

- **Severity:** HIGH
- **Source:** adversary
- **File:** server/handlers/search.py:471-475 (predicate build) + 604-634 (ANN exec)
- **What:** When `filters={"notebook":"<slug>","source_kind":"textbook"}` is
  supplied, the handler unconditionally builds a `source_kind IN (...)`
  predicate (`:471-475`) and runs it via `search_table.where(predicate,
  prefilter=True)` (`:622`/`:629`) against the routed notebook's table. Verified
  live against `var/arxmcp/notebooks/bridgeland-stability/lancedb`: that table
  was ingested before the m9 `source_kind` migration and lacks the column, so
  LanceDB raises `RuntimeError: LanceError(Schema): No field named source_kind`.
- **Why it matters:** The exception propagates out of the `span_ann` block
  unhandled — it is NOT one of the `(NotebookError, CorpusNotIngestedError)`
  caught at `:503`, nor a `ValueError`. It surfaces as a 500, violating AC5's
  "missing/empty/traversal slug → clean typed error not 500" contract for the
  adjacent (and equally plausible) case of a valid notebook + a real filter key.
  The implementer recognized this exact column-absence gap and guarded the
  OUTPUT read (`_arrow_to_rows`, `:869`) but left the PREDICATE path exposed —
  the fix is half-complete. `paper_id` is safe (core column, present in every
  chunks table); only `source_kind` (m9-era) is at risk.
- **Proposed fix:** In the notebook-routing block (after `search_table` is
  resolved, around `:507`), when `source_kind_predicate is not None`, check
  `"source_kind" in search_table.schema.names` (or catch the LanceError around
  the ANN and convert). Cleaner: gate the predicate — if the routed notebook
  table lacks `source_kind`, raise a clean `ValueError` ("filters['source_kind']
  is not supported on notebook '<slug>' — its corpus predates the source_kind
  migration") OR drop the predicate and emit a `filter_warnings` entry. Prefer
  the explicit `ValueError` so the agent is not silently served unfiltered rows.
- **Regression guard:** Add `TestHandlerNotebookRouting::test_source_kind_filter_on_notebook_without_column`
  — route to a notebook fake whose `_FakeTable` raises `LanceError` (or whose
  arrow schema omits `source_kind`) on a `source_kind` WHERE, and assert a clean
  `ValueError` (or a `filter_warnings` entry), never an unhandled exception.

### F2 — notebook corpus_version is NOT threaded into the cache key (synthesis §1.2 not implemented)

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** server/handlers/search.py:538-540 + 716-723 (cache calls); server/cache.py:333-341,392-401 (unchanged)
- **What:** Research-synthesis §1.2 (the LOCKED design) mandated adding an
  optional `corpus_version: int | None` override to `lookup_search`/
  `store_search` and passing the notebook's version on a notebook call, so the
  Tier-1 key becomes `(q, filters-with-notebook, k, NOTEBOOK_version, level)`.
  This was NOT done: `server/cache.py` is untouched in the diff, and the handler
  passes only `query/filters/k/level` to both `lookup_search` (`:538-540`) and
  `store_search` (`:716-723`). The key therefore salts on the SHARED
  process-pinned `RetrievalCache._corpus_version` (`cache.py:243`), never the
  notebook's.
- **Why it matters:** AC3 cross-notebook isolation still holds (two distinct
  slugs → distinct `filters_json` → distinct keys; verified). The real
  consequence is self-staleness: a re-ingest that bumps ONLY notebook A's
  on-disk version leaves A's prior cache entries reachable for up to the 1h
  Tier-1 TTL, because the key salt (shared version) did not move. It does NOT
  cross-serve to a different notebook. This is honestly disclosed as
  implementation-summary deviation #3, but it is a departure from the locked
  synthesis §1.2 — the synthesis explicitly called this "the one place
  brief-2's zero-cache-change is insufficient." Calibrated MEDIUM: bounded,
  documented, not on the hot path, but a real correctness window the locked
  design intended to close.
- **Proposed fix:** Either (a) implement §1.2 as specified — add the optional
  `corpus_version` kwarg to `lookup_search`/`store_search` (default `None` →
  `self._corpus_version`, preserving AC4 byte-identity) and pass
  `override_corpus_version` from the handler; ~15 LOC + 2 tests; or (b) if the
  deviation is accepted as-is, the summary's "known limitation" framing is fine
  but the synthesis §1.2 should be annotated as deliberately descoped so the
  next reader does not assume it shipped.
- **Regression guard:** `test_notebook_version_salts_cache_key` — assert
  `lookup_search(..., corpus_version=369)` and `lookup_search(..., corpus_version=49)`
  for the same query+filters+k+level derive different Tier-1 keys, and that
  `corpus_version=None` reproduces the pre-m2 shared-version key byte-for-byte.

### F3 — AC3 isolation has no end-to-end regression guard through the real cache

- **Severity:** MEDIUM
- **Source:** adversary
- **File:** tests/test_search_notebook_routing.py:374 (cache stubbed None) + 39-106 (TestCacheKeyIsolation)
- **What:** Every handler test stubs the cache out
  (`monkeypatch.setattr("server.handlers.search.get_cache", lambda: None)`,
  `:374`), so no test exercises a notebook query through `cache.lookup_search`/
  `store_search`. `TestCacheKeyIsolation` (`:39-106`) calls
  `canonical_key_components` directly with hand-built dicts that already contain
  `notebook` — it proves the KEY function isolates, but not that the HANDLER
  passes `notebook` into the cache call. The single guard on the handler-side
  invariant is `test_canonicalize_retains_notebook_key` (`:44`), which only
  covers `_canonicalize_filters`, not the lookup/store call sites.
- **Why it matters:** The brief's explicit ask — "a test that would FAIL if
  someone later strips notebook from canonical_filters" — is only partially met.
  A future refactor that strips `notebook` between `_canonicalize_filters` and
  `cache.lookup_search` (e.g. "clean up the routing key before caching") would
  silently regress AC3 cross-notebook isolation and ALL 23 tests would still
  pass. The most byte-stability-critical claim of the milestone is under-guarded
  at the integration boundary.
- **Proposed fix:** Add one handler-level test that installs a real (or
  minimally-faithful) cache via `set_cache`, issues the same query for two
  notebooks, and asserts the two calls produced two distinct Tier-1 keys (or
  two distinct stored entries / no cross-hit). Reuse an in-memory `Tier1Store`
  over `tmp_path` rather than `lambda: None`.
- **Regression guard:** `test_two_notebooks_do_not_cross_serve_via_real_cache`
  — warm notebook A's result into a real cache, then query notebook B with the
  identical query/k/level and assert B does NOT receive A's rows (miss → B's own
  table), proving the slug reaches the cache key end-to-end.

### F4 — LRU eviction drops the dict ref but never closes the LanceDB handle

- **Severity:** LOW
- **Source:** adversary
- **File:** server/resources.py:805-810 (eviction) + 822-828 (shutdown rationale)
- **What:** On registry overflow, `notebook_table` calls
  `self._notebook_tables.popitem(last=False)` (`:806`) which drops the
  `(table, info)` reference but performs no explicit close; reclamation of the
  underlying LanceDB connection/fds relies on GC. `Resources.shutdown` likewise
  never iterates `_notebook_tables`.
- **Why it matters:** Bounded by `MAX_NOTEBOOK_TABLE_SLOTS = 16` and consistent
  with the project's documented convention (shutdown comment `:823-825`:
  "LanceDB Table objects do not expose an explicit close … releasing the
  reference is sufficient"). The only residual risk is transient over-allocation
  on a busy event loop where GC lags eviction. Latent, not on the common path,
  and matches existing practice — hence LOW, not a blocker.
- **Proposed fix:** None required for ship. If a future LanceDB API exposes
  `Table.close()`, call it in both the eviction loop and a new
  `_notebook_tables`-draining block in `shutdown`. Document the GC-reliance in
  the `notebook_table` docstring for the next reader.
- **Regression guard:** N/A at LOW; if fixed, assert eviction invokes the close
  hook via a fake table that records `close()` calls.

## What was done well

- The chosen cache-isolation mechanism (notebook rides in `filters_json`, key
  function untouched) is the lower-blast-radius option on the repo's most
  byte-stability-critical code, exactly as `.claude/notes/07-multi-agent-caching.md`
  counsels; `_canonicalize_filters` correctly preserves `notebook` (`:339`).
- AC4 byte-identity is real and provable: `envelope(..., override_corpus_version=None)`
  reduces to the pre-m2 path (`server/tools.py:411-416`), and the no-notebook
  cache key is unchanged — both backed by passing tests.
- X-1/X-2 are genuinely untouched: no `ToolMeta`/`Field`/handler-signature edit,
  `TOOL_SCHEMA_VERSION` still 15, and `tests/test_server_tool_schema.py` +
  `tests/test_prompts.py` pass (65 tests green including these).
- Threat-1 is defended in depth: `validate_slug` at the handler boundary
  (`:447`) BEFORE any path use, re-validated inside `notebook_table` (`:760`)
  and again via `notebook_dir`'s symlink + containment check — no TOCTOU.
- The `source_kind`-absent OUTPUT guard (`_arrow_to_rows:869`) correctly
  identifies and handles a REAL latent gap (verified: the live bridgeland table
  lacks `source_kind` but has `embedding_stmt`).
- The FM-8 concurrency guard (asyncio.Lock + double-check, `:759-763`) is
  correct, and the lock is created via `default_factory=asyncio.Lock` — safe
  with no running loop at dataclass construction on Python 3.12.
- The fork-C/fork-A precedence (per-call wins, `:498-509`) and the AC7
  cache_db_path reconciliation are coherent and clearly documented in both the
  code comments and `docs/install.md` / `.claude/notes/06-mcp-server-design.md`.
- Error conversion discipline is clean: `NotebookError` and
  `CorpusNotIngestedError` are both mapped to `ValueError` at the boundary
  (`:448-452`, `:503-506`), satisfying AC5 for the slug/un-ingested cases.
- Deviations are disclosed honestly rather than hidden — deviation #3 (cache
  salt) and #4 (boot requirement) are both surfaced with their consequences.
- ruff clean on all four changed source/test files; no banned patterns
  (`BaseHTTPMiddleware`, `import anthropic`, `0.0.0.0`, `assert` for invariants,
  external-write calls) introduced; no dependency/infra files touched.

## Recommended rectification order

1. **F1** (HIGH) — gate or catch the `source_kind` predicate on notebook tables
   lacking the column; this is a reachable 500 and the highest-leverage fix.
2. **F3** (MEDIUM) — add the end-to-end cache regression guard; cheap and
   directly protects the milestone's central AC3 claim. Pairs naturally with F2.
3. **F2** (MEDIUM) — either implement synthesis §1.2's corpus_version override
   or annotate it as deliberately descoped; decide-then-document.
4. **F4** (LOW) — defer; record under deferred findings.

## Rectification status

<!-- Phase 4 appends one bullet per finding; do not pre-populate -->
