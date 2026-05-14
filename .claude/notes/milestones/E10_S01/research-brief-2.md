# E10_S01 Research Brief 2 — Definitions Index and get_definitions Tool

## 1. In-Codebase Context

### What is already shipped

**`server/handlers/definitions.py` is fully implemented** — not a stub. It is an
operational v1 handler that parses `preamble.json` files on-the-fly at handler
call time. Key facts:

- It reads `var/arxmcp/corpus/preamble/<paper_id>/preamble.json` directly via
  `_preamble_path_for(paper_id)` — no LanceDB `definitions` table is involved.
- Returns `{"extraction_status": "ok", "macros": [...], "paper_id": ..., "term": ...}`.
- Each macro entry is `{"expansion": ..., "symbol": ...}` — only two fields,
  no `symbol_raw`, `definition_id`, `defining_chunk_id`, or `scope`.
- Exact match only on `term` (line 97: `parsed = [m for m in parsed if m["symbol"] == term]`).
- No pagination (`next_cursor` not implemented).
- The `_NEWCMD_RE` regex in the handler is simpler than `ingest/preamble.py`'s
  `_BRACED_HEAD_RE` — it handles `\newcommand`, `\renewcommand`,
  `\DeclareMathOperator` but NOT `\providecommand`, `\def`, `\let`.

The milestone's "two-mode handler with LanceDB-backed pagination and
`symbol_raw` field" is a **replacement** for the existing live handler, not a
greenfield build.

**`expand_macro` tool does NOT exist** anywhere in the codebase. `server/tools.py`
`ALL_TOOLS` has exactly 7 entries: `SEARCH_PAPERS`, `GET_CHUNK`,
`FIND_EQUATION`, `GET_DEFINITIONS`, `FIND_LEMMA_BY_NAME`, `GET_PAPER`,
`CITE_NEIGHBORS`. There is no 8th tool to remove. The brief's risk note
("absorbs the former `expand_macro` tool") is aspirational history — it was
never actually committed. The 7-tool surface count and BP1 hash are stable.

**`ingest/index_definitions.py` does NOT exist** — it is the primary new
deliverable. No `definitions` LanceDB table exists.

**`ingest/schema.py` contains NO definitions schema** — only `CHUNKS_SCHEMA_V1`
and `EmbedRecord`. The `definitions` table schema must be created fresh.

### Preamble extractor output shape

`ingest/preamble.py` produces a `PreambleDoc` dataclass (defined in
`ingest/preamble_types.py`). The `macros` field is a `list[str]` — each entry
is a full normalized macro declaration string such as:

```
"\\newcommand{\\R}{\\mathbb{R}}"
"\\DeclareMathOperator{\\Pic}{Pic}"
"\\def\\sheaf#1{\\mathcal{#1}}"
"\\let\\old=\\new"
```

The preamble extractor covers: `\newcommand`, `\renewcommand`,
`\providecommand`, `\DeclareMathOperator` (and starred), `\def`, `\edef`,
`\gdef`, `\xdef`, `\let`. The handler's `_NEWCMD_RE` currently handles fewer
forms than the extractor outputs. The indexer must parse all forms.

### Design note applicability

- **`.claude/notes/05-storage-and-indexing.md` lines 83–94**: Defines the
  `definitions` table schema exactly: `definition_id`, `paper_id`, `symbol`,
  `symbol_raw`, `expansion`, `defining_chunk_id`, `scope`. Indexes:
  "B-tree on `(paper_id, symbol)`, B-tree on `symbol_raw`."
  Note: LanceDB does NOT support composite B-tree indexes on multiple columns
  in a single `create_scalar_index` call — `(paper_id, symbol)` must be
  implemented as two separate scalar indexes or as a pre-computed compound key
  column (e.g. `paper_symbol_key = f"{paper_id}:{symbol}"`).

- **`.claude/notes/07-multi-agent-caching.md` lines 40–49**: "Pin tool JSON
  schemas. Sort properties alphabetically at serialization time. Freeze
  descriptions as constants in source." Since `expand_macro` never existed,
  NO tool is being removed. The `GET_DEFINITIONS` ToolMeta description must
  be updated to describe the new LanceDB-backed behavior. **This changes the
  `tools/list` wire bytes, so `EXPECTED_TOOL_SCHEMA_SHA256` in
  `tests/test_server_tool_schema.py` must be re-pinned** via:
  ```bash
  pytest tests/test_server_tool_schema.py --update-tool-schema-hash
  ```
  Additionally, `TOOL_SCHEMA_VERSION` in `server/tools.py` must be bumped
  from `1` to `2`.

- **`.claude/notes/07-multi-agent-caching.md`**: The `envelope()` helper in
  `server/tools.py` does `_sort_dict(payload)` — all dict keys in tool results
  must be emitted alphabetically sorted. The new handler's response keys
  (`corpus_version`, `definitions`, `next_cursor`, `paper_id`, `term`, `total`)
  must serialize in sorted order. `envelope()` handles this automatically.

### Existing tests to reuse

`tests/test_preamble.py` has a rich fixture at
`tests/fixtures/preamble/sample.tex` with 15 macros (5 `\newcommand` +
1 `\renewcommand` + 1 `\providecommand` + 2 `\DeclareMathOperator` +
4 `\def`-family + 2 `\let`). The `_patched_extract` helper patches
`RAW_DIR`/`PREAMBLE_DIR`/`PREAMBLE_LOG_PATH` onto `tmp_path`. Reuse this
fixture and patching pattern in `tests/test_definitions_index.py`.

The chunker's `kind="definition"` is already emitted (see `chunker.py`
line 167: `"definition": "definition"`, and line 187: `"notation":
"notation"`). Chunks with these kinds can be collected for the second
source (definition environment bodies). However `ChunkRecord` has no
`symbol` or `expansion` field — definition chunks just carry `body_text`.
The indexer must parse the `body_text` to extract symbol/expansion for
definition-environment entries, or treat the entire `body_text` as the
`expansion` with `symbol=""` (no clean symbol extraction from raw text).

---

## 2. Prior Decisions and Lessons

### CLAUDE.md §8 landmines that apply directly

**Landmine 1 — `assert` banned.** The indexer `ingest/index_definitions.py`
must use `if ... raise RuntimeError(...)` for invariant checks, not `assert`.
Example: verifying `paper_id` is non-empty before building a LanceDB row.

**Landmine 7 — HEREDOC commits.** Commit message for this milestone will
contain apostrophes (e.g., "don't", "paper's"). Use stdin HEREDOC form:
```bash
git commit -F - <<'COMMIT_EOF'
...
COMMIT_EOF
```

**Landmine 8 — uv run pytest.** All test runs must use:
```bash
/Users/chris.dare/Library/Python/3.9/bin/uv run python -m pytest
```

### Tool-schema hash re-pin is mandatory

The `GET_DEFINITIONS` description in `server/tools.py` reads today:
```
"Return the per-paper notation/macro table for the given paper_id. With
term: returns only the macro whose symbol matches term (exact). Without
term: returns the full table. Source: the per-paper preamble.json written
by the E02_S02 preamble extractor; one entry per \\newcommand."
```
After E10_S01 ships, the source changes from preamble.json runtime-parsing
to a LanceDB `definitions` table. The description must be updated. Any
description change blows BP1 cache. Bump `TOOL_SCHEMA_VERSION` from `1` to
`2` in `server/tools.py`, then regenerate the sha256 pin.

### `merge_insert` idempotency pattern (from `ingest/store.py`)

The existing LanceDB writer uses:
```python
tbl.merge_insert("chunk_id")
    .when_matched_update_all()
    .when_not_matched_insert_all()
    .execute(arrow_table)
```
The definitions indexer should use the same pattern keyed on `definition_id`
for per-row idempotency. For full-paper replacement (brief spec: "re-running
for a paper replaces all entries keyed by `paper_id`"), a delete-then-insert
via `tbl.delete(f"paper_id = '{paper_id}'")`  followed by `tbl.add(...)` is
cleaner and avoids stale rows from a prior run with more definitions.

### Handler transition: preamble.json → LanceDB

The current `handle_get_definitions` reads from the filesystem. The new
handler must open the LanceDB `definitions` table via `get_resources()` →
`r.config.lancedb_path` → `lancedb.connect(...).open_table("definitions")`,
mirroring the pattern in `server/corpus.py`. The server's `Resources` class
(used by all other handlers) must expose either a `definitions_table` handle
or a helper function for opening it.

---

## 3. External Sources

### LanceDB scalar indexes

LanceDB's `create_scalar_index(column, replace=True)` creates a B-tree scalar
index on a single column. **Composite indexes are not supported.** To satisfy
the design note's "(paper_id, symbol)" index requirement with fast lookup:
recommended approach is to index both `paper_id` and `symbol` individually as
two separate scalar indexes. This supports filtered queries like
`tbl.search().where("paper_id = 'X' AND symbol = 'Y'")` efficiently (the
planner uses both indexes). Alternatively, a synthetic `paper_id_symbol`
column storing `f"{paper_id}\x00{symbol}"` allows a single scalar index but
complicates queries.

**Recommendation:** two separate scalar indexes: `create_scalar_index("paper_id")` +
`create_scalar_index("symbol")`. Document as satisfying the design note's intent.

### LanceDB `merge_insert` and delete-replace

From LanceDB docs: `table.delete("paper_id = 'X'")` removes all rows matching
the predicate before a fresh `table.add(new_rows)`. This is the correct idiom
for full-paper replacement. `merge_insert(on="definition_id")` is appropriate
for individual-row upsert but does not remove stale rows.

### LanceDB pagination via `take` or offset scan

LanceDB tables support `.search().where(filter).limit(N).offset(M).to_arrow()`
for offset-based pagination. For 100-entry pages, the `next_cursor` field in
the MCP response can encode the integer offset (base64 or plain int). Token
cursors are not needed at this scale; offset-based pagination is simpler.

### MCP `nextCursor` shape

The MCP 2025-06-18 spec (https://modelcontextprotocol.io/specification/2025-06-18)
defines `nextCursor` as an opaque string on list-typed tool responses. Since
`get_definitions` returns a `dict` (not a list-pagination response), the cursor
should be embedded in the `structuredContent` payload as `next_cursor: str | null`,
not as a top-level MCP `nextCursor`. The brief spec says "paginated at 100 entries
per page with a `next_cursor` field" — this means in the tool result payload.

### LaTeX `\newcommand` symbol canonicalization

For argument-less macros: `\newcommand{\R}{\mathbb{R}}` → `symbol = "\\R"`,
`symbol_raw = "\\R"` (same), `expansion = "\\mathbb{R}"`.

For n-arg macros: `\newcommand{\Hom}[2]{\mathrm{Hom}(#1,#2)}` → `symbol = "\\Hom"`,
`symbol_raw = "\\Hom"`, `expansion = "\\mathrm{Hom}(#1,#2)"`. The `[2]` arity
is implicit in the expansion but not captured separately at v1.

**Recommendation:** `symbol` = the bare command name (e.g. `\Hom`), NOT
`\Hom{#1}{#2}`. The distinction of arity is visible in `expansion`; storing
`symbol` as just the command name enables clean exact-match lookups.

For `\let\old=\new`: `symbol = "\\old"`, `expansion = "\\new"`, `symbol_raw = "\\old"`.
For `\def\sheaf#1{\mathcal{#1}}`: `symbol = "\\sheaf"`, `expansion = "\\mathcal{#1}"`.

---

## Open Questions

1. **LanceDB composite index gap.** The brief says "B-tree index on
   `(paper_id, symbol)`" but LanceDB `create_scalar_index` takes a single
   column name. Implementer must choose: two separate scalar indexes (recommended)
   or a synthetic compound column. Document the choice in the indexer.

2. **`defining_chunk_id` for preamble-derived entries.** Preamble declarations
   have no corresponding ChunkRecord — the preamble is extracted from raw `.tex`,
   not from the LaTeXML HTML. What value goes in `defining_chunk_id`? Options:
   (a) a synthetic sentinel like `f"{paper_id}:preamble"` (not a real chunk_id),
   (b) `NULL` / empty string. The brief says the field is present but gives no
   sentinel convention. Option (a) is more useful for traceability.

3. **Definition-environment chunk → symbol extraction.** Chunks with
   `kind="definition"` or `kind="notation"` from the chunker carry raw
   `body_text` (e.g., "Let $\mathcal{A}$ denote the category of..."). There is
   no structured `symbol` field on `ChunkRecord`. The indexer can either: (a)
   skip definition-environment entries entirely in v1 (preamble-only) or
   (b) store the chunk as an entry with `symbol=""` and `expansion=body_text[:500]`.
   The brief implies both sources are indexed, but the chunker emits no parsed symbol.

4. **Dedup when preamble redefines the same symbol multiple times.** `_extract_macros`
   in `ingest/preamble.py` deduplicates on the full normalized macro string
   (line 251: `dict.fromkeys(normalised)`). Two `\newcommand{\R}{\mathbb{R}}` calls
   produce one entry. But `\newcommand{\R}{\mathbb{R}}` + `\renewcommand{\R}{\mathbb{Q}}`
   produce TWO distinct entries (different full strings). Which one wins in `definitions`?
   Recommendation: last-seen wins (the `renewcommand` entry is the live binding).

5. **`\let`, `\def`, `\providecommand` in scope?** `ingest/preamble.py` extracts all
   of them (lines 29–31 of module docstring). The current `server/handlers/definitions.py`
   `_NEWCMD_RE` only handles `\newcommand`, `\renewcommand`, `\DeclareMathOperator`.
   The new indexer should use the preamble extractor's `_extract_macros` directly
   (or call `load_preamble`) rather than re-parsing with a narrower regex.

---

## External Writes Required

This milestone requires NO external writes:

| type | target | why |
|---|---|---|
| — | — | No external writes |

- **`var/arxmcp/index/lancedb/definitions.lance/`** — local filesystem write.
  This is the LanceDB table on disk at the project-standard `lancedb_path`.
  It is an internal data write (same as the `chunks` table), not an external
  write. The orchestrator's external-write gate does NOT apply.
- No git pushes, no third-party APIs, no tickets, no infrastructure mutations.
