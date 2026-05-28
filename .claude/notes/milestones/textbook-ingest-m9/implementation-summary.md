# Implementation Summary — textbook-ingest-m9 (e4)

**Summary:** `search_papers` now accepts `filters.source_kind={arxiv|textbook}` (LanceDB dense pre-filter + supplementary BM25-path branch) and every result row carries a `source_kind` tag. This is the e4 demoable CAPABILITY; the literal "Milne/Caraiani chunks come back" demo remains operator-gated on an unbuilt textbook embed→write-LanceDB driver (documented follow-up). Closes textbook-ingest-e4.

**Commit range:** `2dcf6bb..HEAD` (single feat commit + this summary).

## Acceptance criteria status

### Filter wiring
- [x] `"source_kind"` added to BOTH `SUPPORTED_FILTER_KEYS` copies (`server/retrieval/bm25.py` + `server/handlers/search.py`).
- [x] Dense path (authoritative): `_build_source_kind_predicate` builds `source_kind = '<validated>'`, threaded into the ANN `.where(..., prefilter=True)`. Pre-filter avoids the under-fill failure (m9 FM-1) that a post-retrieval filter would hit on a mostly-arXiv top-k.
- [x] BM25 path (supplementary): `_apply_supported_filters` gained a `source_kind` branch inferring kind from the chunk_id prefix (`_source_kind_from_chunk_id`). Filters compose (paper_id AND source_kind).
- [x] Enum validation at the handler boundary: invalid value → `ValueError` (mirrors paper_id posture). Whitelist `{arxiv, textbook}` is the PRIMARY SQL-injection defense (m9 FM-2 — LanceDB has no bound params).
- [x] Default: no source_kind filter → no `.where()` clause → chunks of any source_kind returned.
- [x] Combined paper_id + source_kind → single ANDed/parenthesized `.where()` (LanceDB `.where()` replaces on a second call; single-clause case stays byte-identical to pre-m9).

### Result-envelope tagging
- [x] `_arrow_to_rows` reads `source_kind` and includes it in each row (defensive `"arxiv"` fallback for a NULL). `server/schemas/search_papers_result.json` adds the `source_kind` enum property + `required` entry + `$id`/`version` bump. snippet-contract §(f) updated.

### Tool schema + BP1 discipline (the coordinated re-pin)
- [x] SEARCH_PAPERS description widened to document `filters.source_kind` + the per-row tag.
- [x] `TOOL_SCHEMA_VERSION 13→14`; `EXPECTED_TOOL_SCHEMA_SHA256` re-pinned via `pytest --update-tool-schema-hash`.
- [x] **`EXPECTED_BP1_SHA256` ALSO re-pinned** (483344e3…) — see "Deviation" below. lean_verify_result.json version 13→14 (global-version echo).

### Tests
- [x] `_build_source_kind_predicate` validation (valid arxiv/textbook, invalid, injection payload, non-str) — `TestBuildSourceKindPredicate`.
- [x] Handler wiring (predicate threaded + prefilter, combined filter, invalid raises, result row carries source_kind, no-filter no-where) — `TestSourceKindFilterWiring`.
- [x] BM25 branch (`_source_kind_from_chunk_id`, filter keeps-only, compose AND) — `TestBm25SourceKindBranch`.
- [x] Real-LanceDB pre-filter semantics (write mixed arxiv+textbook chunks via `write_chunks`, assert `.where("source_kind=...")` actually filters) — `tests/test_store.py::TestSourceKindPrefilter` (model-free, dummy vectors).
- [x] Cache-key isolation (source_kind participates in the filters_json key) — `TestCacheKeyDistinguishesFilterSets::test_source_kind_filter_distinct_cache_key`.
- [x] `_make_arrow_table` test helper updated to carry source_kind (m9 FM-7).
- [x] Tool-schema + snippet-contract + BP1 hash tests green post-re-pin.

### Out of scope (documented follow-up)
- The literal Milne/Caraiani live demo + the **missing `tools/notebook_textbook_ingest.py` driver** (embed m7's textbook chunk JSONs → write the notebook LanceDB). m7 writes chunk JSONs only; nothing loads them into a notebook's lancedb. **Tracked at [chris-dare-dev/arXMCP#8](https://github.com/chris-dare-dev/arXMCP/issues/8)** (filed at e4 close per the m9 critique F1 — the deferral is now live, not lost).

## Files changed
- `server/handlers/search.py` (source_kind predicate + validation + combined .where + _arrow_to_rows + SUPPORTED_FILTER_KEYS)
- `server/retrieval/bm25.py` (SUPPORTED_FILTER_KEYS + _source_kind_from_chunk_id + _apply_supported_filters source_kind branch)
- `server/tools.py` (SEARCH_PAPERS description + TOOL_SCHEMA_VERSION 13→14)
- `server/schemas/search_papers_result.json` (source_kind property + required + $id/version 14)
- `server/schemas/lean_verify_result.json` (version/$id 13→14 — global echo)
- `.claude/docs/snippet-contract.md` (§(f) — source_kind now surfaces)
- `tests/test_search_filter.py`, `tests/test_store.py`, `tests/test_snippet_contract.py`, `tests/test_server_tool_schema.py` (re-pin), `tests/test_prompts.py` (BP1 re-pin), `tests/test_handlers_lean_verify.py` (version pin)

## External writes required
None — purely local.

## Test counts
- `make test`: **3074 passed, 29 skipped, 1 xfailed, 3 pre-existing failures** (latexmlc SIGABRT ×2 + Kùzu cite_neighbors ×1 — unchanged).

## Deviation from the synthesis (recorded)
- **The synthesis (following BOTH researchers) claimed `EXPECTED_BP1_SHA256` was UNAFFECTED. That was wrong.** BP1 hashes the byte-region "system prompt + live `ALL_TOOLS`" (`tests/test_prompts.py::TestBP1ByteIdentityAcrossFanout`), so widening the SEARCH_PAPERS ToolMeta description drifts BP1 in LOCKSTEP with `EXPECTED_TOOL_SCHEMA_SHA256`. Both were re-pinned together — the documented paired-re-pin discipline (the BP1 test's own failure message says "ALL_TOOLS changed → test_server_tool_schema.py should also be failing — fix THAT first"). The researchers conflated this BP1 pin with the (separate) notion that BP1 covers only `server/prompts.py`. Caught + corrected during Phase 2 (the test failed loudly, as designed). No production-behavior impact — purely the cache-version bump that a tool-description change is supposed to cause.
- Also bumped `lean_verify_result.json` version 13→14: result-schema JSONs echo the global `TOOL_SCHEMA_VERSION` (cross-checked by `test_handlers_lean_verify.py`), so any global bump touches every result schema even when that tool's shape is unchanged. Established pattern.

## e4 status
**textbook-ingest-e4 is CLOSED** at m9 completion. textbook-ingest now has only **e5** (PDF threat-hardening doc + non-OA license truncation) remaining.
