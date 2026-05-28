# Research Brief — textbook-ingest-m9

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-28T14:50:00Z

---

## In-codebase context

### Load-bearing constraints

From `.claude/notes/07-multi-agent-caching.md` §"Property 1: Tool definitions are byte-stable":
> "Pin tool JSON schemas. Sort properties alphabetically at serialization time. Freeze descriptions as constants in source. A casual edit to a tool description blows every sub-agent's cache."
> "Bump the hash deliberately when intentionally changing schema; treat as an API version bump."

From `.claude/notes/07-multi-agent-caching.md` §"Tier 1 — Exact-query":
> `key = sha256(canonical_form(query) + filters_json + k + corpus_version)`
> `filters_json = json.dumps(filters or {}, sort_keys=True, separators=(",", ":"))`

**Cache key participation confirmed:** `server/cache_sqlite.py::canonical_key_components` (lines 170–171) builds `filters_json = json.dumps(filters or {}, sort_keys=True, separators=(",", ":"))` and includes it in the SHA-256 key. A `{"source_kind": "textbook"}` filters dict produces a different hash than `{}` — source_kind participates automatically once it is in the filters dict passed through. No special implementation needed for OQ-6; the existing mechanism is correct.

**SUPPORTED_FILTER_KEYS location:** `server/retrieval/bm25.py` line 117: `SUPPORTED_FILTER_KEYS: frozenset[str] = frozenset({"paper_id"})`. There is a PARALLEL copy at `server/handlers/search.py` line 208: `SUPPORTED_FILTER_KEYS: frozenset[str] = frozenset({"paper_id"})`. Both must be updated — the handler's copy drives `filter_warnings` generation (line 515); the bm25.py copy drives `_apply_supported_filters`.

**`_apply_supported_filters` structure:** `server/retrieval/bm25.py` lines 664–706. Takes `candidates: list[tuple[str, float]]` — a list of `(chunk_id, score)` tuples. The paper_id branch parses `chunk_id` to extract paper_id (splits on `arxiv:` prefix). A `source_kind` branch CANNOT parse the chunk_id to get `source_kind` — the chunk_id format is `textbook:<slug>:<16-hex>` or `arxiv:<paper_id>:<16-hex>`. The source_kind IS inferrable from the prefix, but this is fragile. The correct approach is a LanceDB pre-filter predicate (see OQ-2 recommendation below).

**Result-envelope gap:** `server/handlers/search.py::_arrow_to_rows` (lines 691–726) builds each result row with fields: `chunk_id`, `label`, `paper_id`, `score`, `section_path`, `snippet`. It reads columns: `chunk_id`, `paper_id`, `section_path`, `theorem_name`, `theorem_label`, `body_text`, `_distance`. It does NOT read `source_kind` from the Arrow result. From `.claude/docs/snippet-contract.md` §(f): "None of these columns surface in the search-result envelope yet." **e4 must add `source_kind` to `_arrow_to_rows`.** This adds a new field to the result-row dict, which changes the tool result shape and bumps `TOOL_SCHEMA_VERSION`.

**OQ-1 — embed-write-notebook-LanceDB path for textbook chunks:** `ingest/textbook_chunker.py` line 43: "6. Writes chunk JSONs only — NOT LanceDB. Embedding/LanceDB-write is a downstream step." `tools/notebook_ingest.py` calls `run_bulk_ingest(paper_ids, lancedb_staging_path=lancedb_path, ...)` — this is the arXiv bulk ingest path, which processes arXiv papers only. Neither `notebook_ingest.py` nor `ingest/bulk_ingest.py` contains any reference to `chunk_textbook`, `textbook_chunker`, or `source_kind="textbook"`. **The embed→write-notebook-LanceDB path for textbook chunks does NOT exist.** m7 writes chunk JSONs to `var/arxmcp/notebooks/<slug>/chunks/<flat_paper_id>/`; no code embeds those JSONs and writes them to the notebook's LanceDB. The live Milne demo is undeliverable from m9 code. m9 ships the filter CAPABILITY (synthetic-LanceDB test) + documents the embed-write gap as a follow-up.

**TOOL_SCHEMA_VERSION current:** `server/tools.py` line 130: `TOOL_SCHEMA_VERSION: int = 13`. Adding `source_kind` to the SEARCH_PAPERS description changes the description bytes → changes the `tools/list` response hash → requires `TOOL_SCHEMA_VERSION 13→14` + re-pin of `EXPECTED_TOOL_SCHEMA_SHA256`.

**BP1 impact:** `EXPECTED_BP1_SHA256` is pinned to `server/prompts.py`. m9 does NOT change `server/prompts.py`. Verify by reading the hash pin and confirming no prompts.py edit — do NOT re-pin blindly.

---

## Prior decisions and lessons

From MEMORY.md (auto-injected):

- `ingest/chunker.py::_compute_chunk_id` hardcodes `arxiv:` prefix; textbook chunker uses `_compute_textbook_chunk_id` emitting `textbook:<slug>:<sha>` (textbook-ingest-m7 finding).
- `CHUNKER_VERSION = "v1.1"` is shared; `TEXTBOOK_CHUNKER_VERSION = "tv1.0"` is separate (textbook-ingest-m7).
- `ChunkRecord` already carries all m2 fields — no dataclass extension needed.
- The E13 doc-placement pattern: audit docs go under `.claude/docs/` not `docs/`.
- notebook-retrieval-m1 shipped as fork C (ARXMCP_NOTEBOOK env var), dense-only.

From `git log --oneline -5`: m8 completed 2026-05-28, m7 also complete. notebook-retrieval-m1 is the immediately prior dependency and is COMPLETE (state.json phase: "complete").

**Critical pattern from notebook-retrieval-m1:** fork C means `ARXMCP_NOTEBOOK=<slug>` → `Config.derive_notebook_lancedb_path` rewrites `lancedb_path` to `var/arxmcp/notebooks/<slug>/lancedb/`. The server serves a per-notebook LanceDB. The `search_papers` handler uses `r.chunks_table` from the startup-bound Resources; when `ARXMCP_NOTEBOOK` is set, that table IS the notebook's LanceDB.

**`_apply_supported_filters` is on the BM25 path only.** For notebook-retrieval-m1 fork C (dense-only), BM25 is bypassed. The filter seam for the dense path is the LanceDB `.where()` predicate in the ANN call (lines 480–488 of `server/handlers/search.py`). The `paper_id` branch already uses `.where(paper_id_predicate, prefilter=True)`. Adding source_kind as a pre-filter predicate there is consistent with the existing dense-path implementation.

**`_apply_supported_filters` in bm25.py operates on `(chunk_id, score)` tuples.** Source_kind is NOT encoded in chunk_id reliably enough for production use — the prefix heuristic (`textbook:` vs `arxiv:`) would work for current enum values but is fragile if future source_kinds are added. Pre-filter is the correct approach for dense path; for BM25 path (when/if used for hybrid), a parallel `source_kind` branch in `_apply_supported_filters` parsing the chunk_id prefix is acceptable as belt-and-braces.

---

## External sources

### MCP spec (2025-06-18) — tool inputSchema

Fetched from `https://modelcontextprotocol.io/specification/2025-06-18/server/tools`. Key findings:

**No MUST clause requiring enumeration of filter keys.** The spec shows `inputSchema` as "JSON Schema defining expected parameters" with an example showing enumerated `properties`. There is NO MUST clause requiring that a `dict`-typed argument enumerate its keys in the schema's `properties`. A free-form `object` (`type: object` without enumerated sub-properties) is spec-compliant.

**Schema byte-stability is a project-internal BP1 discipline requirement, NOT an MCP spec requirement.** The MCP spec does NOT require that `inputSchema` be byte-stable. The re-pin requirement comes entirely from `.claude/notes/07-multi-agent-caching.md` §"Property 1: Tool definitions are byte-stable."

**Does adding source_kind change the BYTE-level tool schema?** Yes, but ONLY if the SEARCH_PAPERS tool description or the `filters` argument description is changed. The `filters` parameter is typed as `dict[str, Any] | None` in the handler signature — FastMCP renders this as `{"type": "object"}` in the inputSchema without enumerating keys. Adding `source_kind` support does NOT change the schema structure unless the string description of `filters` is updated. However, the brief requires updating the description to document `filters.source_kind={arxiv|textbook}` — this description change is what causes the byte-level schema change and the re-pin.

**No protocol-level streaming for tool results.** The spec shows `tools/call` as a request/response (not streaming). Tool results return a `content` array + optional `structuredContent`. Pagination is only on `tools/list` (via `nextCursor`). The `search_papers` `cursor` arg for pagination does NOT introduce a protocol violation — it is an application-layer reserved field, ignored at v1.

**Conclusion for OQ-5:** The MCP spec does not require enumerating `source_kind` in the JSON Schema. Updating the description string of `filters` IS the byte-level change that re-pins the hash. TOOL_SCHEMA_VERSION 13→14 + re-pin is correct; it is NOT spec-required but IS project-required (BP1 discipline). No streaming violation introduced.

---

## Failure-mode analysis

**FM-1 — Under-fill (post-retrieval approach).** If ANN returns k candidates and ALL are arXiv chunks, a post-retrieval `source_kind=textbook` filter drops them all → empty result. With `k=10` and a corpus that is 95% arXiv, the probability of zero textbook chunks in the top-10 is high. The brief's over-fetch pattern for `paper_id` (`OVER_FETCH_FACTOR=4` in bm25.py) would help, but the dense path does NOT apply over-fetching today. **LanceDB pre-filter avoids this entirely** — the ANN search runs over only the source_kind=textbook sub-corpus, filling top-k from textbook chunks directly. This is the critical failure mode that mandates pre-filter over post-retrieval for source_kind.

**FM-2 — Invalid source_kind value injection.** An LLM passes `filters={"source_kind": "'; DROP TABLE chunks;--"}` or `{"source_kind": "unknown_value"}`. Threat: (a) SQL injection into the LanceDB `.where()` predicate if the value is interpolated without validation; (b) silent empty results if the unknown value matches nothing. Mitigation: validate `source_kind` value against `_ALLOWED_SOURCE_KINDS = {"arxiv", "textbook"}` (from `ingest/store.py`) at the handler boundary BEFORE building any LanceDB predicate. Invalid value should raise `ValueError` (consistent with `paper_id` validation posture) or surface in `filter_warnings`. LanceDB does not accept bound parameters for predicates (`server/handlers/search.py` line 121 comment: "LanceDB does not accept bound parameters for predicates today"); manual escape is needed but structural validation is the primary defense. The `source_kind` value must be whitelist-validated, not just escaped.

**FM-3 — Cache collision.** A `source_kind=textbook` query MUST NOT serve a cached unfiltered result. **This failure mode does NOT exist** with the current implementation: `canonical_key_components` in `cache_sqlite.py` line 171 includes `filters_json = json.dumps(filters or {}, sort_keys=True)`. `{"source_kind": "textbook"}` produces a different `filters_json` than `{}`. Cache collision is architecturally prevented. However: a test is still required to confirm the key is used correctly by the `cache.lookup_search` / `cache.store_search` call path in `search.py` — the AC in the brief correctly requires this.

**FM-4 — Tool-schema hash drift.** If the implementer updates the SEARCH_PAPERS description or `filters` arg description but forgets to: (a) bump `TOOL_SCHEMA_VERSION` 13→14, OR (b) re-pin `EXPECTED_TOOL_SCHEMA_SHA256` via `pytest --update-tool-schema-hash`. Consequence: the byte-stability test in `tests/test_server_tool_schema.py` fails (good — caught before push). But if the re-pin is done with the WRONG hash (e.g. running `--update-tool-schema-hash` before wiring the description change), the pin is wrong and BP1 cache is poisoned. **The correct order:** wire the description change + version bump FIRST, then run `--update-tool-schema-hash` ONCE at the end.

**FM-5 — source_kind=None / NULL chunks (legacy rows).** Pre-m2 arXiv rows in a migrated chunks table have `source_kind="arxiv"` (explicitly backfilled via `_TEXTBOOK_MIGRATION_DEFAULTS`: `"source_kind": "cast('arxiv' as string)"`). From `ingest/store.py` line 291: `"source_kind": "cast('arxiv' as string)"`. So NULL source_kind rows should not exist in practice (migration backfills to "arxiv"). However, the schema declares `source_kind` as nullable. If a NULL row exists and a `source_kind=textbook` LanceDB pre-filter is applied, NULL rows are excluded (standard SQL NULL != 'textbook'). If a `source_kind=arxiv` filter is applied, NULL rows are ALSO excluded by the predicate — potential false negative. The handler should document that NULL source_kind is treated as "not matching any filter" — acceptable behavior.

**FM-6 — The Milne demo over-claim.** No code path exists to embed textbook chunk JSONs (from m7's `var/arxmcp/notebooks/<slug>/chunks/`) and write them to the notebook's LanceDB. If the brief is read as requiring the literal demo, the implementer would falsely claim "e4 done" while the Milne/Caraiani chunks are not in any notebook LanceDB. **Resolution:** m9 ships the CAPABILITY proven by synthetic test + documents the embed-write gap (`tools/notebook_ingest.py` handles arXiv papers only; a `tools/notebook_textbook_ingest.py` or equivalent is the follow-up). The gap must be documented in the implementation-summary.

**FM-7 — `_arrow_to_rows` reads non-existent column.** If e4 adds `source_kind` to `_arrow_to_rows` by reading `arrow.column("source_kind")` but the column is absent from the Arrow result (e.g. an old un-migrated table), LanceDB raises a `KeyError`. The column was backfilled for pre-m2 tables via `_migrate_chunks_schema_if_needed`. But a synthetic test fixture that creates a LanceDB table without the m2 columns would fail. The synthetic test must explicitly write the `source_kind` column to the test fixture.

---

## Recommendation

**For OQ-2 (filter application point):** Use LanceDB pre-filter (`where("source_kind = 'textbook'", prefilter=True)`) threaded into the ANN query, identical to the existing `paper_id` predicate pattern in `server/handlers/search.py` lines 479–488. Reason: (1) post-retrieval under-fill (FM-1) makes post-retrieval wrong for sparse textbook corpora; (2) the LanceDB `.where()` API is already used and tested for `paper_id`; (3) `source_kind` is a first-class chunks-table column that LanceDB can filter efficiently. Build the source_kind predicate in the handler (parallel to `_build_paper_id_predicate`) as a simple string `f"source_kind = '{validated_value}'"` after whitelist validation. Also add a `source_kind` branch to `_apply_supported_filters` (for the BM25 path) using the chunk_id prefix heuristic as belt-and-braces — but the pre-filter is the authoritative path.

**For OQ-1 (live demo vs capability):** m9 ships capability only. Document the embed-write gap: "To run the Milne demo, implement `tools/notebook_textbook_ingest.py` that calls `chunk_textbook`, `embed_paper` (with textbook chunk JSONs), and `write_chunks(lancedb_path=notebook_lancedb_path)`." The arXiv `tools/notebook_ingest.py` handles arXiv papers; a parallel tool for textbook PDFs is a follow-up epic (textbook-ingest-e4 follow-up or e5).

**For OQ-5 (MCP spec compliance):** The MCP spec does NOT require enumerating `source_kind` as a named property in the inputSchema. Adding it to the filters arg description string IS the byte-level change that drives the re-pin. Bump TOOL_SCHEMA_VERSION 13→14; re-pin after wiring, not before.

**For enum validation of source_kind value:** Use `ValueError` (not `filter_warnings`), consistent with the `paper_id` validation posture. The `paper_id` branch raises `ValueError` for invalid values (`_build_paper_id_predicate` lines 160–196). source_kind should do likewise. The set of valid values is `{"arxiv", "textbook"}` — from `ingest/store.py::_ALLOWED_SOURCE_KINDS`.

**For source_kind in result rows:** Add `source_kind` to `_arrow_to_rows` by reading `arrow.column("source_kind").to_pylist()`. This adds a new field to the result dict, changes the snippet-contract schema (section f of `snippet-contract.md` explicitly defers this to m4/e4), and requires the schema file `server/schemas/search_papers_result.json` to be updated.

---

## Open questions

**OQ-1 (resolved):** The embed→write-notebook-LanceDB path for textbook chunks does NOT exist. m9 ships the filter CAPABILITY via a synthetic test. The live Milne demo is operator-gated on a follow-up `notebook_textbook_ingest.py` tool that does not yet exist. Document the gap in implementation-summary.md; do not block m9 on building it.

**OQ-2 (resolved):** Use LanceDB pre-filter (`.where("source_kind = 'textbook'", prefilter=True)`), same pattern as `paper_id`. Post-retrieval in `_apply_supported_filters` is supplementary (BM25 path), not the primary enforcement.

**OQ-5 (resolved):** MCP spec does not require enumerating filter keys. The re-pin is driven by updating the `filters` description string (BP1 project discipline). TOOL_SCHEMA_VERSION 13→14 + re-pin of `EXPECTED_TOOL_SCHEMA_SHA256`. `EXPECTED_BP1_SHA256` untouched (no prompts.py change). No protocol violation introduced; no streaming violation.

**OQ-3 (resolved from code):** source_kind is NOT in the current result rows (`_arrow_to_rows` does not read that column). The snippet-contract §(f) explicitly defers this to e4. Must be added.

**OQ-4 (resolved):** Reject invalid source_kind values with `ValueError` (consistent with paper_id pattern), not `filter_warnings`. `filter_warnings` is for unknown/deferred keys — source_kind is a KNOWN key with a KNOWN valid-value set.

**OQ-6 (resolved from code):** Cache-key already includes `filters_json = json.dumps(filters or {})`. source_kind participates automatically. No implementation change needed for cache isolation.

---

## External writes the implementation will require

None — this milestone is purely local. All changes are:
- `server/retrieval/bm25.py` (SUPPORTED_FILTER_KEYS + _apply_supported_filters)
- `server/handlers/search.py` (source_kind predicate + _arrow_to_rows + SUPPORTED_FILTER_KEYS + description + validation)
- `server/tools.py` (TOOL_SCHEMA_VERSION bump + description update)
- `server/schemas/search_papers_result.json` (add source_kind field)
- `.claude/docs/snippet-contract.md` §(f) update (note that source_kind now surfaces)
- `tests/test_*` (new filter-seam tests, synthetic-LanceDB end-to-end test)
- `tests/test_server_tool_schema.py` re-pin via `pytest --update-tool-schema-hash`

No git push, no PR, no infra mutation, no third-party API call.
