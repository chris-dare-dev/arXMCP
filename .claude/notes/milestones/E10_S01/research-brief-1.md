# E10_S01 Research Brief 1 — Definitions Index and get_definitions Tool

## 1. In-Codebase Context

### What already exists

**`server/handlers/definitions.py` is NOT a stub — it is a v1 implementation.** The handler:
- Reads from `var/arxmcp/corpus/preamble/<paper_id>/preamble.json` (the file written by `ingest/preamble.py`)
- Parses raw macro lines via `_NEWCMD_RE` + `_balance_braces` to extract `{symbol, expansion}` pairs
- Returns full table (sorted by symbol) or term-filtered (exact match only)
- Returns `{macros: [], extraction_status: "no_preamble"}` when preamble is absent

The v1 handler does NOT: use a LanceDB `definitions` table, paginate with `next_cursor`, do prefix-match fallback, or capture `definition_id`, `symbol_raw`, `defining_chunk_id`, or `scope`. It reads a flat JSON file at request time rather than a pre-built index.

**There is NO `ingest/index_definitions.py` and NO `definitions` LanceDB table.** The `definitions` table schema is specified in `.claude/notes/05-storage-and-indexing.md` lines 92–104 but has never been created.

**`expand_macro` does NOT exist.** No such tool is registered in `server/tools.py`. `ALL_TOOLS` has exactly 7 entries: `search_papers`, `get_chunk`, `find_equation`, `get_definitions`, `find_lemma_by_name`, `get_paper`, `cite_neighbors`. The brief's "absorbs expand_macro" framing refers to a planned tool that was never shipped — there is no migration risk.

**`GET_DEFINITIONS` ToolMeta already exists** in `server/tools.py`:
```python
GET_DEFINITIONS = ToolMeta(
    name="get_definitions",
    description=(
        "Return the per-paper notation/macro table for the given "
        "paper_id. With term: returns only the macro whose symbol "
        "matches term (exact). Without term: returns the full table. "
        "Source: the per-paper preamble.json written by the E02_S02 "
        "preamble extractor; one entry per \\newcommand."
    ),
)
```
The description is pinned in the current `EXPECTED_TOOL_SCHEMA_SHA256 = "4623e8988f8346da38eaa882303da7a4ef5a4c9a6c13211d867a04c50018fd41"`. **Any description change requires `TOOL_SCHEMA_VERSION` bump + `pytest --update-tool-schema-hash`.**

**BP1 constraint (`.claude/notes/07-multi-agent-caching.md` lines 40–49):**
> "Pin tool JSON schemas. Sort properties alphabetically at serialization time. Freeze descriptions as constants in source. A casual edit to a tool description blows every sub-agent's cache."

The handler signature `handle_get_definitions(paper_id, term=None)` is already wired. Adding `cursor` or `page` parameters to the signature would change the `inputSchema` bytes, invalidating BP1. **Adding parameters = schema drift = mandatory version bump + hash repin.**

### Definitions table schema (load-bearing quote)

From `.claude/notes/05-storage-and-indexing.md` lines 92–104:
```
definition_id        string (primary key, content-addressable)
paper_id             string
symbol               string    # canonical form, e.g. "\mathcal{A}"
symbol_raw           string    # author's form, e.g. "\AA"
expansion            string    # human-readable expansion text
defining_chunk_id    string
scope                enum {paper, section, theorem}

Indexes: B-tree on (paper_id, symbol), B-tree on symbol_raw.
```

### Preamble extractor output (E02_S02)

`ingest/preamble.py` produces `PreambleDoc.macros`: a sorted, deduplicated list of normalised macro-definition strings like `"\\newcommand{\\R}{\\mathbb{R}}"`. It handles `\newcommand`, `\renewcommand`, `\providecommand`, `\DeclareMathOperator`, `\def`/`\edef`/`\gdef`/`\xdef`, and `\let`. The handler's existing `_NEWCMD_RE` + `_extract_pairs` only handles `\newcommand`/`\renewcommand`/`\DeclareMathOperator` — `\def`, `\gdef`, `\let` are extracted by the preamble extractor but will be unparsed by the current handler regex. The indexer must handle all macro forms.

`PreambleDoc` does NOT carry `symbol_raw` or `defining_chunk_id`. The `macros` list has the raw macro text; parsing must extract the symbol name. The preamble extractor is SEPARATE from chunker output: preamble entries represent `scope="paper"`. For `scope="section"` or `scope="theorem"`, the source is chunker output (`ChunkRecord` with `kind="definition"` or `kind="notation"` — both exist in `_ALLOWED_KINDS` in `ingest/store.py`).

### LanceDB writer pattern (from `ingest/store.py`)

The idempotent upsert uses `merge_insert(on="chunk_id")`. For the definitions table, the upsert key should be `definition_id` (content-addressable primary key). B-tree index creation uses:
```python
tbl.create_scalar_index("paper_id", replace=True)
```
LanceDB ≥ 0.6 (the pinned version) supports `create_scalar_index` — the `index_type="BTREE"` kwarg may or may not be supported. The chunks writer calls `tbl.create_scalar_index("paper_id", replace=True)` without specifying `index_type`. Check LanceDB 0.6 docs for whether composite `(paper_id, symbol)` B-tree is achievable or whether two separate scalar indexes suffice.

### Tool-schema hash protocol

From `tests/test_server_tool_schema.py`:
- `EXPECTED_TOOL_SCHEMA_SHA256` is pinned at `"4623e8988f8346da38eaa882303da7a4ef5a4c9a6c13211d867a04c50018fd41"`
- Re-pinning requires: bump `TOOL_SCHEMA_VERSION` in `server/tools.py`, then `pytest tests/test_server_tool_schema.py --update-tool-schema-hash`
- The flag refuses to run in CI (`_running_in_ci()` check)

---

## 2. Prior Decisions and Lessons

**`expand_macro` was never shipped.** The brief's risk note ("absorbs expand_macro") refers to a planned tool. No migration needed, no 8th tool entry to remove.

**Pagination adds a handler parameter, changing inputSchema bytes.** The v1 handler signature is `handle_get_definitions(paper_id, term=None)`. Adding `cursor: str | None = None` changes the tool's `inputSchema` — this is a BP1 schema event, requiring `TOOL_SCHEMA_VERSION` bump. The description text also needs updating from "Source: the per-paper preamble.json…" to reflect the LanceDB `definitions` table. **Both changes are unavoidable; both require the hash repin procedure.**

**`assert` ban.** From CLAUDE.md §4.7: "assert is BANNED for invariants — Python `-O` strips them. Use `if … raise RuntimeError(…)` instead." The indexer must not use `assert` for validation.

**Doc-placement rule.** No Markdown in `ingest/` or `tests/`. The indexer `ingest/index_definitions.py` may have a docstring; no `.md` companion file.

**`_ALLOWED_KINDS` in `ingest/store.py`** already includes `"definition"` and `"notation"` — chunks with these kinds exist in the corpus and are the source for scope ≠ `paper` entries.

**No `definitions` table yet.** There is no placeholder or stub in the LanceDB dataset. The indexer creates it on first run.

**Preamble-derived entries do NOT have a `defining_chunk_id`.** The preamble is extracted from the .tex source, not from a chunked representation. The `defining_chunk_id` field should be nullable or set to a sentinel (e.g. `""`) for preamble-derived entries. The schema spec says `defining_chunk_id: string` without nullable annotation — the implementer must decide.

---

## 3. External Sources

**LanceDB scalar index API (v0.6+):** `tbl.create_scalar_index(column_name, index_type="BTREE", replace=True)`. Composite indexes are NOT supported in LanceDB at this version — `(paper_id, symbol)` cannot be a single B-tree index. The correct approach is two separate scalar indexes: one on `paper_id` and one on `symbol`. The note says "B-tree on `(paper_id, symbol)`" but this must be decomposed.

**MCP cursor pagination:** The MCP spec (2025-06-18) uses opaque string cursor tokens for pagination on list endpoints. The convention is to return `nextCursor` as an opaque string (not an integer offset). For alphabetically-sorted symbol lists, the natural cursor is the last-seen `symbol` value (encoded as-is or base64). This is cleaner than integer offsets because it survives concurrent index updates. `nextCursor: null` means no more pages.

---

## Open Questions

1. **`definition_id` content-address recipe.** The brief says "content-addressable" but not the hash input. Recommendation: `sha256(paper_id + ":" + symbol + ":" + expansion)[:16]` — same pattern as `chunk_id` (`sha256(canonical_chunk_bytes)[:16]`). Avoids collisions on same-symbol-different-expansion (re-definition).

2. **`symbol_raw` for preamble entries.** The preamble extractor normalizes macro names (NFC, whitespace-collapsed) but the `macros` list stores the full line. The `symbol` is the canonical form; `symbol_raw` should be the author's form AS WRITTEN in the .tex (before any normalization). For `\newcommand{\AA}{\mathcal{A}}`, `symbol_raw="\AA"` and `symbol="\mathcal{A}"` — but we don't have the canonical expansion pre-computed; that's the point of the definitions index. The implementer needs to decide: is `symbol_raw` the command NAME (`\AA`) and `symbol` the expansion (`\mathcal{A}`)? Or does `symbol` represent the normalized command name? The brief's example (`symbol="\mathcal{A}"`, `symbol_raw="\AA"`) confirms: `symbol_raw` is the author's macro command, `symbol` is the expanded/canonical form. Computing `symbol` (the expansion) from the preamble line requires running the brace-walker to extract the body.

3. **`defining_chunk_id` for preamble-derived entries.** No chunk corresponds to a preamble declaration. Use `""` (empty string) or declare the column `nullable=True` in PyArrow schema and store NULL. Recommend NULL (nullable column) to distinguish "from preamble" from "from chunk with chunk_id=X".

4. **Scope for definition-environment entries.** Chunker outputs `ChunkRecord` with `kind="definition"` and `section_path: list[str]`. If `section_path` is empty, scope is `paper`; if non-empty at section depth, scope is `section`; if the chunk has a `theorem_label`, scope is `theorem`. This heuristic needs to be pinned.

5. **Case-insensitive prefix match on LaTeX commands.** The brief says "fall back to case-insensitive prefix match" for `term` lookup. LaTeX commands ARE case-sensitive (`\AA` ≠ `\Aa`). Case-insensitive matching is therefore semantically wrong for symbols. Recommendation: exact match on `symbol`, then exact match on `symbol_raw`, then case-insensitive prefix on `symbol_raw` only (not on `symbol`). Flag this to the implementer as a potential semantic hazard.

6. **Both "paper unknown" and "paper known but no preamble" return `[]`.** The brief says "empty list (not a 404)". The v1 handler already returns `{macros: [], extraction_status: "no_preamble"}` for absent preamble files. The new handler should similarly return `{definitions: [], ...}` for both cases — confirming no distinction is needed.

7. **Composite B-tree index.** LanceDB 0.6 `create_scalar_index` does not support composite (multi-column) indexes. Two separate scalar indexes on `paper_id` and `symbol` are the correct implementation, not one composite index. The note's "B-tree on `(paper_id, symbol)`" should be read as "individual B-tree indexes on `paper_id` and on `symbol`."

8. **Handler description update triggers hash repin.** The existing `GET_DEFINITIONS` description references "the per-paper preamble.json written by the E02_S02 preamble extractor." After this milestone, the source is the LanceDB `definitions` table. Updating the description is semantically correct but requires `TOOL_SCHEMA_VERSION = 2` + hash repin.

---

## External Writes Required

| type | target | why |
|---|---|---|
| lancedb_write | `var/arxmcp/index/lancedb/definitions` table | `ingest/index_definitions.py` creates and populates the definitions LanceDB table from preamble JSON + chunker output |

No pushes, PRs, API calls, or infra mutations required. All writes are local to `var/arxmcp/`.
