# Critique — notebook-retrieval-m2 (merged)

**Critics:** adversary (only — no infra-scoped files changed, oss-scout not requested)
**Generated:** 2026-05-28
**Commit range:** `12c86640..2f341ba`
**Merged verdict:** SHIP-WITH-FIXES

## Executive summary

- SHIP-WITH-FIXES. The core fork-A routing + cache-isolation design is sound and
  the no-notebook path is provably byte-identical (AC4), but one common-path
  filter combination raises an uncaught 500.
- Counts: **0 CRITICAL, 1 HIGH, 2 MEDIUM, 1 LOW**.
- Single critic (adversary); no cross-critic agreement section (infra-safety did
  not fire — no Makefile/infra/CI/Dockerfile edits; oss-scout not requested).
- **F1 (HIGH)** is the blocker: `notebook` + `source_kind` filter runs a
  `source_kind` predicate against a pre-m9 notebook table that lacks the column
  → `LanceError(Schema)` → 500. The implementer guarded the OUTPUT read but left
  the PREDICATE path exposed — a half-complete fix of the same column-absence gap.
- Cache byte-stability axis is clean for AC3/AC4; X-1/X-2 confirmed unchanged.
  Threat-1 double-validated, no TOCTOU. Security/no-fork/local-first/MCP-spec/
  tier-sequencing axes all clean.

## Cross-critic agreement

_None — no file:line region was flagged by ≥ 2 critics._

<!-- end:cross-critic-agreement -->

## Findings (preserved IDs from critique-adversary.md)

### F1 — source_kind filter + notebook routing raises an uncaught 500 (HIGH)
- **File:** `server/handlers/search.py` — `source_kind` predicate build + the ANN
  exec block that runs `search_table.where(predicate, prefilter=True)`.
- **What:** `filters={"notebook":"<slug>","source_kind":"textbook"}` builds a
  `source_kind = '...'` predicate and runs it against the routed notebook table.
  Pre-m9 notebook tables lack the `source_kind` column → `RuntimeError:
  LanceError(Schema): No field named source_kind` (verified live). It is not
  caught by the `(NotebookError, CorpusNotIngestedError)` handler nor a
  `ValueError` → surfaces as a 500, violating AC5 for the valid-notebook +
  real-filter case.
- **Fix:** when a `source_kind` predicate is active AND the routed notebook table
  lacks the column, raise a clean `ValueError` ("filters['source_kind'] not
  supported on notebook '<slug>' — its corpus predates the source_kind
  migration") rather than letting LanceDB 500. Prefer explicit error over
  silently dropping the predicate (don't serve unfiltered rows as if filtered).
- **Regression guard:** route to a notebook whose table omits `source_kind`;
  assert a clean `ValueError`, never an unhandled exception.

### F2 — notebook corpus_version not threaded into the cache key (synthesis §1.2) (MEDIUM)
- **File:** `server/handlers/search.py` cache calls; `server/cache.py` lookup_search/
  store_search (unchanged in the diff).
- **What:** Locked synthesis §1.2 mandated an optional `corpus_version` override on
  `lookup_search`/`store_search`, passing the notebook's version so the Tier-1 key
  salts on the NOTEBOOK's version. Not implemented — the key salts on the shared
  process-pinned version. AC3 isolation still holds (notebook in filters_json);
  the consequence is TTL-bounded self-staleness on a notebook re-ingest (no
  cross-serve). Disclosed as impl-summary deviation #3, but it departs from the
  locked design.
- **Fix:** implement §1.2 — add `corpus_version: int | None = None` to
  `lookup_search`/`store_search` (default None → `self._corpus_version`,
  preserving AC4 byte-identity), pass `override_corpus_version` from the handler.
- **Regression guard:** assert distinct notebook versions → distinct Tier-1 keys,
  and `corpus_version=None` reproduces the pre-m2 key byte-for-byte.

### F3 — AC3 isolation has no end-to-end regression guard through the real cache (MEDIUM)
- **File:** `tests/test_search_notebook_routing.py` (cache stubbed `None`;
  `TestCacheKeyIsolation` calls the key function directly with hand-built dicts).
- **What:** No test exercises a notebook query through a real
  `cache.lookup_search`/`store_search`. A future refactor stripping `notebook`
  between `_canonicalize_filters` and the cache call would silently regress AC3
  and all 23 tests would still pass.
- **Fix:** add a handler-level test with a real `Tier1Store` (over `tmp_path`):
  warm notebook A's result, query notebook B with the identical query/k/level,
  assert B does not receive A's rows (slug reaches the cache key end-to-end).

### F4 — LRU eviction drops the dict ref but never closes the LanceDB handle (LOW)
- **File:** `server/resources.py` eviction (`popitem(last=False)`) + shutdown.
- **What:** Eviction relies on GC to reclaim the LanceDB handle; matches the
  project's existing convention (LanceDB `Table` exposes no `close()`; the
  shutdown comment documents reference-release as sufficient). Bounded at 16.
- **Disposition:** DEFER (LOW). Latent, off the common path, matches existing
  practice. If a future LanceDB API exposes `close()`, call it in eviction +
  shutdown.

## Recommended rectification order
1. F1 (HIGH) — gate/convert the source_kind predicate on notebook tables lacking
   the column. Reachable 500; highest leverage.
2. F3 (MEDIUM) — end-to-end cache regression guard; cheap; protects the central
   AC3 claim. Pairs with F2.
3. F2 (MEDIUM) — implement synthesis §1.2's corpus_version override (the locked
   design); ~15 LOC + 2 tests.
4. F4 (LOW) — defer.

## Rectification status

Generated: 2026-05-28. Re-verify gate: F1 (HIGH) re-read at the cited region and
confirmed live-valid (source_kind predicate runs against `search_table` with no
column guard) before fixing. No findings invalidated.

- **F1 (HIGH) — FIXED.** `server/handlers/search.py`: after resolving the routed
  notebook table, if a `source_kind` predicate is active AND
  `"source_kind" not in search_table.schema.names`, raise a clean `ValueError`
  ("not supported on notebook … predates the source_kind migration") instead of
  letting LanceDB 500. Regression guards:
  `tests/test_search_notebook_routing.py::TestHandlerNotebookRouting::test_source_kind_filter_on_legacy_notebook_raises`
  (+ `::test_source_kind_filter_on_migrated_notebook_ok` guards against a
  false-positive on post-m9 tables).
- **F2 (MEDIUM) — FIXED (implemented synthesis §1.2).** `server/cache.py`:
  `lookup_search`/`store_search` gained an optional `corpus_version: int | None`
  (default None → `self._corpus_version`, AC4 byte-identity); the handler threads
  `override_corpus_version` (the notebook's version) into all three cache calls,
  so the Tier-1 key salts on the NOTEBOOK's version (closes the self-staleness
  window the locked design intended). Regression guards:
  `TestCacheCorpusVersionOverride::test_override_threads_into_tier1_key` +
  `::test_none_override_byte_identical_to_shared`.
- **F3 (MEDIUM) — FIXED.** Added
  `TestHandlerNotebookRouting::test_two_notebooks_do_not_cross_serve_via_real_cache`
  — a REAL `Tier1Store`/`RetrievalCache`, two notebooks with a COLLIDING
  corpus_version (369), identical query/k/level: warming A then querying B serves
  B's rows, not A's. Would FAIL if `notebook` were stripped from
  `canonical_filters` (the exact AC3 regression the brief asked to guard).
- **F4 (LOW) — DEFERRED.** Eviction relies on GC to reclaim the LanceDB handle —
  matches the project's existing convention (LanceDB `Table` exposes no
  `close()`; the shutdown comment documents reference-release as sufficient),
  bounded at 16 slots. Revisit if/when a LanceDB `Table.close()` API lands.

**Net rect tests:** +5 (`test_source_kind_filter_on_legacy_notebook_raises`,
`test_source_kind_filter_on_migrated_notebook_ok`,
`test_two_notebooks_do_not_cross_serve_via_real_cache`,
`TestCacheCorpusVersionOverride` ×2). notebook-routing file now 28 tests.
