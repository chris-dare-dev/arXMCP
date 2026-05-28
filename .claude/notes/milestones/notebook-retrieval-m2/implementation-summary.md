# Implementation Summary — notebook-retrieval-m2 (fork A)

**Path:** inline (orchestrator main session)
**Base SHA:** `12c86640fca88913ed5a36acff6470ab9a9d77d5` (m9 complete)
**Generated:** 2026-05-28

---

## One-line

Fork A: `search_papers(filters={"notebook": "<slug>"})` routes a single call to
that notebook's lancedb without a server relaunch — the same dense-only
`embedding_stmt` path m1 ships, just per-call. Cache isolation is free
(`notebook` rides in `filters_json` → the Tier-1 key); a bounded LRU
`Resources.notebook_table(slug)` registry holds per-notebook handles. ~3 source
files + 1 test file.

## Acceptance criteria status

- **[AC1] routing ✅** `filters.notebook=<slug>` runs the ANN over that
  notebook's table. Verified: `TestHandlerNotebookRouting::test_routes_to_notebook_table`
  (bridgeland slug → `0705.3794` in results, shared corpus rows absent).
- **[AC2] same dense path / envelope shape ✅** Routes the unchanged dense-only
  ANN over `embedding_stmt` (proof excluded, `retrieval_mode="dense_only"`).
  Verified: `::test_envelope_shape_and_retrieval_mode`.
- **[AC3] cross-notebook cache isolation ✅** `notebook` stays in
  `canonical_filters` → in the Tier-1 key's `filters_json` → two notebooks with
  the same query + colliding `corpus_version` get DISTINCT keys.
  **Zero change to `canonical_key_components`.** Verified:
  `TestCacheKeyIsolation` (4 tests: retains key, distinct keys, same-key,
  no-notebook byte-identity).
- **[AC4] no-notebook byte-identity ✅** No `filters.notebook` → shared table +
  shared `corpus_version`; `envelope(payload, override_corpus_version=None)` ==
  `envelope(payload)`; the no-notebook cache key is unchanged.
  Verified: `::test_no_notebook_uses_shared_and_shared_version`,
  `TestEnvelopeOverride::test_override_none_is_byte_identical`,
  `TestCacheKeyIsolation::test_no_notebook_key_byte_identical_to_today`.
- **[AC5] clean errors / Threat-1 ✅** Traversal slug → `ValueError`
  ("not a valid notebook slug"); non-str → `ValueError`; un-ingested notebook →
  `ValueError` (converted from `CorpusNotIngestedError`), not a 500. Verified:
  `::test_traversal_slug_raises_value_error`, `::test_non_str_notebook_raises_value_error`,
  `::test_un_ingested_notebook_raises_value_error`, +
  `TestNotebookTableRegistry::test_traversal_slug_rejected` /
  `::test_un_ingested_raises_corpus_not_ingested`.
- **[AC6] notebook corpus_version echo ✅** Envelope echoes the NOTEBOOK's pinned
  version (369), not the process-wide shared version (101). Verified:
  `::test_envelope_echoes_notebook_corpus_version`.
- **[AC7] reconcile m1 F1 cache_db_path ✅** Documented: m1's per-notebook
  `cache_db_path` derivation fires ONLY under fork-C (`ARXMCP_NOTEBOOK` set);
  fork-A (env unset) uses the shared `cache_db_path` + slug-in-key. Two
  complementary mechanisms governing mutually-exclusive runtime modes — not two
  competing ones. No code change needed; m1's config tests remain green.
- **[AC8] docs ✅** `docs/install.md` § notebook serving + `.claude/notes/06-mcp-server-design.md`
  (fork A routing) updated.
- **[X-1] `EXPECTED_TOOL_SCHEMA_SHA256` UNCHANGED ✅** No ToolMeta / Field /
  handler-signature edit (`notebook` is a key inside the free-form `filters`
  dict). Verified: `tests/test_server_tool_schema.py` green.
- **[X-2] `EXPECTED_BP1_SHA256` UNCHANGED ✅** No prompt/tool-surface edit.
  Verified: `tests/test_prompts.py` green.
- **[X-3] ruff clean; make test green ✅** (full-suite result appended below).

## New / changed code

- **`server/tools.py`** — `envelope(payload, *, override_corpus_version=None)`:
  optional per-call version override (default None → byte-identical shared path).
- **`server/resources.py`** — `MAX_NOTEBOOK_TABLE_SLOTS = 16`; two private
  `Resources` fields (`_notebook_tables` OrderedDict LRU + `_notebook_tables_lock`);
  `async def notebook_table(slug)` — validates the slug (Threat-1), lazily opens +
  memoizes the notebook's chunks-table with `open_chunks_table_with_fallback`,
  bounded LRU eviction, asyncio-locked double-check (FM-8). Un-ingested →
  `CorpusNotIngestedError`.
- **`server/handlers/search.py`** — `_ROUTING_FILTER_KEYS = {"notebook"}`; extract
  + validate `notebook_slug` at the boundary; route the ANN to
  `r.notebook_table(slug)` (per-call wins over fork-C, FM-7); echo the notebook's
  corpus_version (AC6); exclude `notebook` from `filter_warnings`; **guard
  `_arrow_to_rows` against an absent `source_kind` column** (pre-m9 notebook
  tables lack it — fork A is the first path to query them).

## New tests

- `tests/test_search_notebook_routing.py` — 23 tests across `TestCacheKeyIsolation`
  (4), `TestEnvelopeOverride` (2), `TestArrowRowsSourceKindGuard` (1),
  `TestNotebookTableRegistry` (5: traversal, un-ingested, memoization, LRU
  eviction, concurrent-same-slug), `TestHandlerNotebookRouting` (11).

## Deviations from the brief

1. **Slug-in-key via filter-preservation, not a new key axis** (synthesis §4) —
   `notebook` stays in `filters`; `canonical_key_components` is untouched. Lower
   blast radius on the byte-stability-critical cache code; AC3/AC4 hold by
   construction.
2. **`source_kind`-absent guard added** (not in the brief) — a latent m9 gap that
   fork A is the first to expose: per-notebook tables predate m9's `source_kind`
   migration, so `_arrow_to_rows` had to tolerate the absent column.
3. **Cache key keeps the SHARED corpus_version salt** (not the notebook's) — AC3
   isolation holds via notebook-in-filters regardless; threading the notebook's
   version into the cache *key* would have required touching the cache key
   function (rejected per §4). Consequence: a notebook re-ingest that bumps only
   that notebook's version leaves a TTL-bounded staleness window (default 1h);
   restarting the server clears it. Documented as a known limitation; the
   envelope (AC6) always reflects the correct notebook version.
4. **Demo realization** — the brief's "NO `ARXMCP_NOTEBOOK` set" demo cannot boot
   on this workstation (the shared corpus is empty → `CorpusNotIngestedError` at
   startup). Realistic deployment: boot via `ARXMCP_NOTEBOOK=<nb>` (fork C) OR an
   ingested shared corpus, then route other notebooks per-call via
   `filters.notebook`. m2 does NOT change the boot requirement (out of scope).

## External writes required

None — local server code + tests + docs.

## Commit range

`12c86640..<HEAD>` (filled after the feat commit lands).
