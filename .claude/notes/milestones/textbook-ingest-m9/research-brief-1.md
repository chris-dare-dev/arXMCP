# Research Brief — textbook-ingest-m9

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-28T00:00:00Z

---

## In-codebase context

### 1. The filter seam (OQ-2 / the core of e4)

**`server/retrieval/bm25.py` — SUPPORTED_FILTER_KEYS and `_apply_supported_filters`**

Line 117 (verbatim):
```python
SUPPORTED_FILTER_KEYS: frozenset[str] = frozenset({"paper_id"})
```

Lines 123–125 (verbatim):
```python
DEFERRED_FILTER_KEYS: frozenset[str] = frozenset(
    {"categories", "year_min", "year_max", "authors", "include_withdrawn"}
)
```

The retrieval flow at lines 579–606: when a supported filter is present, the BM25
scorer over-fetches by `OVER_FETCH_FACTOR=4`, builds candidates as
`list[tuple[str, float]]` (chunk_id, score), then calls `_apply_supported_filters(candidates, filters)` at line 606. A full-corpus retry fires at lines 613–627 if the over-fetch produced zero results.

`_apply_supported_filters` (lines 664–706): iterates over `candidates`,
parses the `chunk_id` to extract `paper_id` by stripping `"arxiv:"` prefix and
splitting on the last colon. **Critical gap:** the function hardcodes `if not chunk_id.startswith("arxiv:"):` at line 699 — it unconditionally skips any chunk whose ID uses the `"textbook:"` prefix. Adding `source_kind` filtering here requires a NEW branch (not patching `paper_id` branch). The filter cannot reuse the paper_id extraction logic since `source_kind` is not encoded in the `chunk_id`.

**The candidate object at the filter point:** BM25 candidates are
`tuple[str, float]` — just `(chunk_id, score)`. They do NOT carry `source_kind`.
For `paper_id` filtering, the BM25 path parses `source_kind` out of the chunk_id
prefix (`arxiv:` vs future `textbook:`). For `source_kind` filtering in BM25 this
means the filter must infer `source_kind` from the chunk_id prefix — e.g. `textbook:` prefix → `source_kind="textbook"`. This is a clean derivation, no LanceDB lookup needed.

**Dense ANN path (the only path for notebooks):** `server/handlers/search.py`
builds a LanceDB prefilter predicate via `_build_paper_id_predicate` and chains
`.where(predicate, prefilter=True)` at line 484. For `source_kind`, the dense path
would chain `.where("source_kind = 'textbook'", prefilter=True)` — a simple
string column predicate. The LanceDB `chunks` table carries `source_kind` as a
utf8 column (schema.py:160). Per notebook-retrieval-m1 implementation summary: "Retrieval is the SAME dense-only path the shared corpus uses." So for notebooks, e4 only needs to handle the dense ANN path.

**`server/handlers/search.py` — filter infrastructure:**

Line 208 (verbatim):
```python
SUPPORTED_FILTER_KEYS: frozenset[str] = frozenset({"paper_id"})
```

This is a SECOND copy of SUPPORTED_FILTER_KEYS in the handler (mirroring bm25.py).
Both must be updated in lockstep. The handler's `_inject_filters_applied` (line 211)
includes only keys from `SUPPORTED_FILTER_KEYS` in the echo — adding `source_kind`
to the frozenset automatically includes it in `filters_applied`.

`_canonicalize_filters` (line 260) normalizes `paper_id` str→list. It has no
normalization for `source_kind` (a plain string). No canonicalization needed for
`source_kind`.

**How invalid paper_id values are handled today (verbatim docstring):**
`_build_paper_id_predicate` raises `ValueError` — "clear error, not 500" per line 146
comment. This is the posture to mirror for invalid `source_kind` values: raise
`ValueError` with a clear message listing the allowed enum values `{"arxiv", "textbook"}`.

**Filter warnings:** unsupported keys surface in `filter_warnings` (lines 513–521).
After adding `source_kind`, callers passing unrecognized keys still get warnings.
Invalid values (e.g. `source_kind="preprint"`) should raise, matching `paper_id`'s
raise posture — NOT a warning.

### 2. Result-envelope `source_kind` (OQ-3)

`_arrow_to_rows` (lines 691–726 of `server/handlers/search.py`) reads these Arrow
columns: `chunk_id`, `paper_id`, `section_path`, `theorem_name`, `theorem_label`,
`body_text`, `_distance`. It does NOT read `source_kind`. The result row dict built
at lines 717–725 has 6 keys: `chunk_id`, `label`, `paper_id`, `score`,
`section_path`, `snippet`. **`source_kind` is NOT in the result row today.**

From `.claude/docs/snippet-contract.md` section (f) (verbatim):
> "None of these columns surface in the search-result envelope yet — the snippet
> contract above is unchanged."

And explicitly: "e4 (cross-corpus `source_kind` filter)" is listed as the trigger
for surfacing `source_kind` in the envelope.

**e4 must add `source_kind` to `_arrow_to_rows`** — read the column and include it
in the result dict. This changes the result row shape, which is a byte-stability
concern. However, the SEARCH_PAPERS description does not enumerate the result row
fields — the hash lives in `EXPECTED_TOOL_SCHEMA_SHA256` (the tool input schema
hash, not the result schema). Adding `source_kind` to result rows does NOT change
`inputSchema` and does NOT change `EXPECTED_TOOL_SCHEMA_SHA256`. The result envelope
field addition is transparent to the BP1 hash.

**But:** widening the SEARCH_PAPERS description string (to document
`filters.source_kind`) DOES change the `tools/list` response bytes → requires
`TOOL_SCHEMA_VERSION 13→14` + `EXPECTED_TOOL_SCHEMA_SHA256` re-pin. The snippet
contract json schema at `server/schemas/search_papers_result.json` may also need
updating (add `source_kind` to the row properties).

### 3. Tool-schema + BP1 (OQ-5)

`TOOL_SCHEMA_VERSION: int = 13` at `server/tools.py` line 130. The version history
at lines 94–129 shows v13 landed with textbook-ingest-m3 (SEARCH_PAPERS description
widened to document paper_id textbook support). v14 is the correct bump for m9.

`EXPECTED_TOOL_SCHEMA_SHA256` lives in `tests/test_server_tool_schema.py` line 94
and is re-pinned via `pytest --update-tool-schema-hash` (documented at line 31).

`EXPECTED_BP1_SHA256` in `tests/test_prompts.py` (line 642) is UNAFFECTED — BP1
covers `server/prompts.py` content, not tool definitions. Confirmed: no `prompts.py`
change is required for m9.

CLAUDE.md §9 "add a new tool" runbook: steps 4 applies to a schema CHANGE:
> "Re-pin `EXPECTED_TOOL_SCHEMA_SHA256` in `tests/test_server_tool_schema.py`...
> Use `pytest --update-tool-schema-hash` to regenerate."

Run `--update-tool-schema-hash` AFTER wiring the description change, NEVER before.

### 4. Cache-key participation (OQ-6)

`server/cache_sqlite.py` `canonical_key_components` (line 144) encodes:
```python
filters_json = json.dumps(filters or {}, sort_keys=True, separators=(",", ":"))
```
The entire `filters` dict is JSON-serialized (sort_keys=True for determinism) and
length-prefixed into the SHA-256 hash. Adding `source_kind` to filters does NOT
require any cache code change — it is automatically hashed as part of the filters
JSON. A query with `filters={"source_kind":"textbook"}` produces a distinct cache
key from an unfiltered query. **OQ-6 is resolved: `source_kind` participates in
the cache key by construction.**

From `server/cache.py` line 271 (verbatim):
> "filters_json = json.dumps(filters or {}, sort_keys=True, separators=(',', ':'))"
> (via canonical_key_components)

The same `canonical_key_components` function drives both Tier-1 and Tier-2
fingerprints (F12 fix from E08_S03), so `source_kind` is hashed at both tiers.

### 5. OQ-1 — live demo vs capability (BLOCKING)

**m7's write path:** `ingest/textbook_chunker.py::chunk_textbook` writes chunk JSON
files to `var/arxmcp/notebooks/<slug>/chunks/<flat_paper_id>/` (confirmed at
`textbook_chunker.py` line 288-289 docstring verbatim: "Writes `var/arxmcp/notebooks/<slug>/chunks/<flat_paper_id>/<hash>.json`
per chunk + a `chunk_manifest.json`. Does NOT write LanceDB.").

**Is there an embed→write-notebook-LanceDB path for textbook chunks?**

Checked `ingest/embedder.py`, `ingest/store.py::write_chunks`,
`tools/notebook_ingest.py`, `ingest/bulk_ingest.py`. Findings:

- `tools/notebook_ingest.py` calls `ingest.bulk_ingest.run_bulk_ingest` — this
  handles arXiv paper_ids only (no textbook handling whatsoever in `bulk_ingest.py`).
- `chunk_textbook` in `ingest/textbook_chunker.py` has ZERO callers outside its own
  module in the entire codebase. No driver picks up the chunk JSONs and passes them
  to the embedder.
- `ingest/embedder.py` reads chunk manifests from
  `var/arxmcp/corpus/chunks/<paper_id>/chunk_manifest.json` (arXiv path). There is
  no code path that reads textbook chunk JSONs from
  `var/arxmcp/notebooks/<slug>/chunks/` and feeds them to the embedder.
- `ingest/store.py::write_chunks` can accept textbook chunks if called with proper
  `EmbedRecord` + `ChunkRecord` list + a `lancedb_path` pointing to a notebook's
  LanceDB, but NO driver builds that EmbedRecord from textbook chunks.

**Conclusion: NO embed→write-notebook-LanceDB path exists for textbook chunks.**
The textbook chunk JSON → embed → notebook LanceDB pipeline is an unbuilt gap.
The literal "Milne/Caraiani chunks come back" demo is operator-gated on building
this missing driver (out of m9 scope per the brief's explicit Won't-list).

`write_chunks` CAN be called directly in tests with synthetic `ChunkRecord` +
`EmbedRecord` (zero-padded embeddings) to seed a notebook LanceDB with textbook
AND arXiv chunks. This is the correct test strategy for m9's synthetic-LanceDB
end-to-end AC.

### 6. Prior decisions and design notes

Snippet contract (`.claude/docs/snippet-contract.md` §f) explicitly lists "m4 (cross-corpus `source_kind` filter)" as the trigger to surface `source_kind` in the result envelope. m9 = e4 = that milestone.

Design note `06-mcp-server-design.md` §"Notebook-scoped retrieval (fork C)" (added
in notebook-retrieval-m1): retrieval is dense-only; `_apply_supported_filters` runs
on the BM25 candidate path which is OFF for notebooks. For notebook-served queries,
the `source_kind` filter operates as a LanceDB prefilter predicate (`.where` call),
consistent with how `paper_id` filtering works on the dense path.

**No constraint conflicts.** The brief's scope is consistent with what exists.

---

## Prior decisions and lessons

From memory: textbook-ingest-m3 bumped `TOOL_SCHEMA_VERSION` 12→13 and re-pinned
`EXPECTED_TOOL_SCHEMA_SHA256` when SEARCH_PAPERS description was widened to document
`paper_id` textbook support. m9 (e4) follows the SAME pattern: description widening
+ `13→14` bump + hash re-pin. This is the confirmed m3 precedent.

From memory: `_compute_chunk_id` in `chunker.py` hardcodes `arxiv:` prefix;
textbook chunker uses `_compute_textbook_chunk_id` emitting `textbook:` prefix.
The BM25 `_apply_supported_filters` function (lines 698–703) explicitly checks
`if not chunk_id.startswith("arxiv:"):` and skips non-arxiv chunks. For
`source_kind` filtering in BM25, the implementer must infer source_kind from the
chunk_id prefix (`textbook:` → `"textbook"`, `arxiv:` → `"arxiv"`) rather than
reading a column — since BM25 candidates only carry `(chunk_id, score)`.

From `git log --oneline -5`:
- `2dcf6bb` — notebook-retrieval-m1 state finalized (complete)
- `c9c96c0` — m1 critique closed
- `7dabd0a` — textbook-ingest-m8 state finalized (complete)

notebook-retrieval-m1 AC [X-1]: `EXPECTED_TOOL_SCHEMA_SHA256` UNCHANGED (no
tools.py/handler/Field edit). m9 WILL change tools.py description → re-pin is
mandatory, not optional.

---

## External sources

Not consulted — this milestone is purely local server filter wiring. No MCP spec
changes (no new tool), no prompt-caching API changes (no prompts.py change),
no new external dependencies.

---

## Recommendation

**Implement `source_kind` as a LanceDB prefilter predicate on the dense path (not
post-retrieval in BM25), validate at the handler boundary with `raise ValueError`
(matching `paper_id` posture), and add `source_kind` to `_arrow_to_rows`.**

Reasoning: notebooks use dense-only retrieval (confirmed by notebook-retrieval-m1);
the BM25 path is inactive for notebook queries; a LanceDB `.where("source_kind =
'textbook'", prefilter=True)` mirrors the existing `paper_id_predicate` pattern
exactly and requires no candidate-shape changes. For the BM25 path (shared corpus
queries), infer `source_kind` from chunk_id prefix in `_apply_supported_filters`.

Specific steps:
1. Add `"source_kind"` to both `SUPPORTED_FILTER_KEYS` frozensets (bm25.py:117
   and search.py:208).
2. In `server/handlers/search.py`: validate `filters["source_kind"]` against
   `{"arxiv", "textbook"}` before the cache lookup (raise ValueError on invalid,
   same as paper_id). Build a LanceDB predicate `f"source_kind = '{value}'"` and
   chain `.where(source_kind_predicate, prefilter=True)` in the ANN path (alongside
   or instead of the paper_id_predicate, supporting both simultaneously).
3. In `server/retrieval/bm25.py::_apply_supported_filters`: add a `source_kind`
   branch that infers source_kind from chunk_id prefix (`textbook:` → `"textbook"`,
   `arxiv:` → `"arxiv"`) and filters accordingly.
4. Add `source_kind` column read in `_arrow_to_rows`; include in result dict.
5. Widen SEARCH_PAPERS description; bump `TOOL_SCHEMA_VERSION 13→14`;
   re-pin `EXPECTED_TOOL_SCHEMA_SHA256` via `pytest --update-tool-schema-hash`.
6. Confirm `EXPECTED_BP1_SHA256` unchanged (no prompts.py edit).
7. Tests: synthetic notebook LanceDB via `write_chunks(chunks, embed_record,
   lancedb_path=tmp_path)` with mixed textbook+arxiv chunks; filter tests on both
   dense and BM25 paths.

---

## Open questions

**OQ-1 (live demo vs capability):** RESOLVED — NO embed→write path exists for
textbook chunks. m9 ships the filter CAPABILITY only, tested against a synthetic
notebook LanceDB seeded via `write_chunks`. The operator steps (chunk→embed→write)
must be documented. Flag the missing textbook ingest driver as a follow-up issue.
No blocker on m9 implementation.

**OQ-2 (filter application point):** RESOLVED — Use LanceDB prefilter predicate
on the dense path (consistent with paper_id); infer from chunk_id prefix on the
BM25 path. Post-retrieval BM25 branch is simple (chunk_id already carries the
prefix); prefilter for ANN is consistent with existing pattern.

**OQ-3 (result-envelope source_kind):** RESOLVED — NOT currently in the result
row. e4 must add it via `_arrow_to_rows`. Does NOT change `EXPECTED_TOOL_SCHEMA_SHA256`
(tool inputSchema unchanged). Does update snippet-contract result JSON schema.

**OQ-4 (enum-validation placement + failure mode):** RESOLVED — raise ValueError
(same as paper_id's raise posture). Invalid value → clear error, not a warning.
Valid values: `{"arxiv", "textbook"}` from `ingest/store.py::_ALLOWED_SOURCE_KINDS`.

**OQ-5 (tool-schema re-pin):** RESOLVED — yes, description widening changes
`EXPECTED_TOOL_SCHEMA_SHA256` → `TOOL_SCHEMA_VERSION 13→14` + hash re-pin. ONE
coordinated re-pin via `pytest --update-tool-schema-hash`. `EXPECTED_BP1_SHA256`
is untouched (no prompts.py change).

**OQ-6 (cache-key participation):** RESOLVED — `filters` dict is JSON-serialized
(sort_keys=True) in `canonical_key_components` (cache_sqlite.py:171). Adding
`source_kind` to filters participates in the key automatically. No cache code change
needed.

No open questions remain — implementation can proceed on the above recommendation.

---

## External writes the implementation will require

None — this milestone is purely local.
