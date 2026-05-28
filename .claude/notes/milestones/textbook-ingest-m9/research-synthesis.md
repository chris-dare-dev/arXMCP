# Research Synthesis — textbook-ingest-m9 (e4)

**Orchestrator merge** of `research-brief-1.md` (in-codebase) and `research-brief-2.md` (external + failure-mode + MCP-spec). The two briefs CONVERGE on all six open questions; brief-2 supplies the FM-1 under-fill analysis that decides OQ-2 and the MCP-spec confirmation for OQ-5. No divergence.

## All 6 open questions RESOLVED

### OQ-1 — live demo vs capability (BLOCKING scope): ship CAPABILITY, document gap
Both briefs independently confirmed: **no embed→write-notebook-LanceDB path exists for textbook chunks.** m7 writes chunk JSONs to `var/arxmcp/notebooks/<slug>/chunks/`; nothing embeds them and writes the notebook's `lancedb/`. `tools/notebook_ingest.py` → `run_bulk_ingest` handles arXiv paper_ids only; `chunk_textbook` has zero callers outside its module. So the literal "Milne/Caraiani chunks come back" demo is **operator-gated on an unbuilt driver**.
- **m9 ships the filter CAPABILITY**, tested against a SYNTHETIC notebook LanceDB seeded directly via `ingest.store.write_chunks(chunks, embed_record, lancedb_path=tmp)` with mixed textbook+arxiv chunks.
- **Document the gap** in implementation-summary.md + flag a follow-up: a `tools/notebook_textbook_ingest.py` (chunk_textbook → embed → write_chunks to the notebook lancedb) is needed before the live demo. Do NOT build it in m9 (Won't-list).

### OQ-2 — filter application point: LanceDB PRE-FILTER (authoritative) + BM25 branch (belt-and-braces)
**Decided by FM-1 (under-fill), brief-2:** a post-retrieval `source_kind=textbook` filter over ANN candidates that are mostly arxiv drops them all → empty results even when textbook chunks exist. The dense path does NOT over-fetch today. **LanceDB pre-filter avoids this**: the ANN runs over only the matching sub-corpus, filling top-k correctly.
- **Dense path (the live path for notebooks — authoritative):** build a `source_kind` predicate (parallel to `_build_paper_id_predicate`) and chain `.where(predicate, prefilter=True)` in the ANN query (`server/handlers/search.py` ~lines 479–488, alongside the existing paper_id predicate). Predicate string: `f"source_kind = '{validated_value}'"` — built ONLY after whitelist validation (FM-2).
- **BM25 path (supplementary):** add a `source_kind` branch to `_apply_supported_filters` (`server/retrieval/bm25.py`) inferring source_kind from the chunk_id prefix (`textbook:` → textbook, `arxiv:` → arxiv). This keeps the filter coherent if/when the hybrid path is active for a corpus. NOT the primary enforcement; the candidates are `(chunk_id, score)` tuples with no source_kind column, so prefix-inference is the only option there.

### OQ-3 — result-envelope source_kind: ADD it
`_arrow_to_rows` (`server/handlers/search.py` ~691–726) currently reads `chunk_id, paper_id, section_path, theorem_name, theorem_label, body_text, _distance` and builds a 6-key row (`chunk_id, label, paper_id, score, section_path, snippet`) — NO source_kind. The snippet contract §(f) explicitly defers surfacing source_kind to "e4". **e4 adds `source_kind` to `_arrow_to_rows`** (read the column → include in the row dict). This adds a result-row field. NOTE: it does NOT change `EXPECTED_TOOL_SCHEMA_SHA256` (that hashes the tool INPUT schema, not result rows) — but it DOES update `server/schemas/search_papers_result.json` + the snippet-contract doc.

### OQ-4 — enum validation: raise ValueError, whitelist {arxiv, textbook}
Mirror the `paper_id` posture: `_build_paper_id_predicate` raises `ValueError` on invalid values ("clear error, not 500"). source_kind validates against `_ALLOWED_SOURCE_KINDS = {"arxiv", "textbook"}` (`ingest/store.py`) at the handler boundary BEFORE building any predicate. Invalid value → `ValueError` (NOT a `filter_warnings` entry — that's for unknown/deferred KEYS; source_kind is a KNOWN key with a known value set). **FM-2 (load-bearing security):** LanceDB does NOT accept bound parameters for predicates (`search.py:121` comment), so the value is string-interpolated into the `.where()` clause — **whitelist validation is the primary SQL-injection defense, not escaping.** Validate against the frozenset; reject anything else before interpolation.

### OQ-5 — tool-schema re-pin: TOOL_SCHEMA_VERSION 13→14 + EXPECTED_TOOL_SCHEMA_SHA256
MCP spec (2025-06-18, fetched by brief-2) does NOT require enumerating filter keys in `inputSchema`; the `filters` arg is a free-form `object`. The re-pin is driven entirely by **widening the SEARCH_PAPERS description string** to document `filters.source_kind={arxiv|textbook}` (BP1 byte-stability discipline, `07-multi-agent-caching.md` Property 1 — NOT an MCP requirement). Steps: wire the description change FIRST, then `TOOL_SCHEMA_VERSION 13→14`, then re-pin `EXPECTED_TOOL_SCHEMA_SHA256` via `pytest --update-tool-schema-hash` ONCE at the end (FM-4: re-pinning before the wiring poisons the hash). `EXPECTED_BP1_SHA256` (`tests/test_prompts.py`) is UNAFFECTED — no `server/prompts.py` change; verify, don't re-pin. No protocol/streaming violation introduced.

### OQ-6 — cache-key participation: automatic
`server/cache_sqlite.py::canonical_key_components` builds `filters_json = json.dumps(filters or {}, sort_keys=True, separators=(",", ":"))` into the SHA-256 key (both Tier-1 + Tier-2). `{"source_kind":"textbook"}` → distinct key from `{}`. No cache code change. A test still confirms the lookup/store path passes filters through (FM-3).

## LOAD-BEARING implementation constraints

1. **Two copies of `SUPPORTED_FILTER_KEYS`** — `server/retrieval/bm25.py:117` AND `server/handlers/search.py:208`. Add `"source_kind"` to BOTH in lockstep (the handler copy drives `filter_warnings` + `filters_applied`; the bm25 copy drives `_apply_supported_filters`).
2. **Whitelist-validate the source_kind value before ANY LanceDB predicate interpolation** (FM-2 — no bound params in LanceDB; whitelist is the injection defense).
3. **Pre-filter is authoritative for the dense/notebook path** (FM-1 under-fill); BM25 prefix-inference branch is supplementary.
4. **Re-pin order:** wire description → bump version → `--update-tool-schema-hash` last (FM-4).
5. **Synthetic test fixture MUST write the `source_kind` column** (FM-7 — `_arrow_to_rows` reading a missing column raises). Seed via `write_chunks` with proper ChunkRecord source_kind + a zero/dummy embedding EmbedRecord.
6. **NULL source_kind** rows are excluded by any `source_kind = X` predicate (standard SQL NULL semantics). Acceptable + documented; migration backfills legacy rows to `"arxiv"` so NULLs shouldn't occur (FM-5).

## Orchestrator synthesis note — final decisions

- Filter: LanceDB `.where("source_kind = '<validated>'", prefilter=True)` on the dense ANN path (authoritative) + a `source_kind` branch in `_apply_supported_filters` (chunk_id-prefix inference) for the BM25 path. Both `SUPPORTED_FILTER_KEYS` copies updated.
- Validation: `ValueError` on a value not in `{"arxiv","textbook"}`, at the handler boundary, before predicate build.
- Result envelope: add `source_kind` to `_arrow_to_rows` + `server/schemas/search_papers_result.json` + snippet-contract §(f) note. Does NOT touch `EXPECTED_TOOL_SCHEMA_SHA256`.
- Tool schema: widen SEARCH_PAPERS description; `TOOL_SCHEMA_VERSION 13→14`; re-pin `EXPECTED_TOOL_SCHEMA_SHA256` last; confirm `EXPECTED_BP1_SHA256` unchanged.
- Scope: CAPABILITY only (synthetic-LanceDB test). Live Milne demo + the `notebook_textbook_ingest` driver = documented follow-up, NOT m9.
- Tests: filter-seam unit (dense pre-filter + BM25 branch), handler enum-validation, cache-key isolation, synthetic-LanceDB end-to-end (mixed corpus: no-filter→both, source_kind=textbook→textbook only, row carries source_kind), tool-schema-hash regression green post-re-pin.

## External writes the implementation will require

| type | target | why | blocking? |
|---|---|---|---|
| (none) | | | |

Purely local. Files: `server/retrieval/bm25.py`, `server/handlers/search.py`, `server/tools.py`, `server/schemas/search_papers_result.json`, `.claude/docs/snippet-contract.md`, `tests/*` (new + tool-schema re-pin). No git push, no GH issue, no infra mutation, no third-party API call.

## Size + path

~Server-side filter wiring across ~6 files + tests. Estimated ~350-450 LOC (incl. tests). Coherent single feature (source_kind filter). **INLINE** — no clean two-part partition; the handler + bm25 + tool-schema changes are interlocked, and the tool-schema re-pin must happen in one coordinated commit.

## Follow-up flagged (out of m9)
- **`tools/notebook_textbook_ingest.py`** (or equivalent): the missing driver that embeds m7's textbook chunk JSONs and writes them to the notebook's LanceDB — the prerequisite for the live Milne/Caraiani demo. File as a follow-up issue at e4-close.
