# E10_S01 — Research Synthesis

Merged from `research-brief-1.md` and `research-brief-2.md`. Where the
two briefs disagree, both positions are surfaced and one is picked with
reasoning. Load-bearing constraints are **quoted, not paraphrased**.

---

## 1. State of play (strong consensus across both researchers)

1. **`server/handlers/definitions.py` is a LIVE v1 handler — not a stub.**
   It reads `var/arxmcp/corpus/preamble/<paper_id>/preamble.json` directly
   at request time, parses macro lines via `_NEWCMD_RE` + `_balance_braces`,
   returns `{macros: [...], extraction_status: ..., paper_id, term}` (only
   `symbol` + `expansion` per entry — no `symbol_raw`, `definition_id`,
   `defining_chunk_id`, or `scope`). **E10_S01 is a REPLACEMENT of this
   handler, not a greenfield build.**

2. **`expand_macro` was never shipped.** `ALL_TOOLS` in `server/tools.py`
   has exactly 7 entries: `SEARCH_PAPERS`, `GET_CHUNK`, `FIND_EQUATION`,
   `GET_DEFINITIONS`, `FIND_LEMMA_BY_NAME`, `GET_PAPER`, `CITE_NEIGHBORS`.
   The brief's "absorbs the former `expand_macro` tool" framing refers to
   a planned tool that was never committed. **No 8th tool to remove. No
   migration risk for the 7-tool surface count.**

3. **No `ingest/index_definitions.py` exists.** Primary new deliverable.

4. **No `definitions` LanceDB table exists.** Indexer creates it on first
   run. `ingest/schema.py` today contains only `CHUNKS_SCHEMA_V1` +
   `EmbedRecord` — a new `DEFINITIONS_SCHEMA_V1` constant is needed.

5. **`GET_DEFINITIONS` ToolMeta description must change.** Current text
   references "the per-paper preamble.json written by the E02_S02
   preamble extractor." After this milestone the source is the LanceDB
   `definitions` table. **Description-text change blows BP1 cache** —
   `TOOL_SCHEMA_VERSION` must bump from `1` → `2`, and
   `EXPECTED_TOOL_SCHEMA_SHA256` in `tests/test_server_tool_schema.py`
   must be re-pinned via `pytest --update-tool-schema-hash`.

6. **Adding a `cursor` (pagination) parameter to the handler signature
   changes `inputSchema` bytes** — same BP1 hash-repin event. The
   description + cursor changes are bundled in a single
   `TOOL_SCHEMA_VERSION = 2` bump.

7. **LanceDB pinned `lancedb>=0.6`** (verified from `pyproject.toml:60`).
   `ingest/store.py:441` uses `tbl.create_scalar_index("paper_id",
   replace=True)` — NO `index_type` kwarg. We follow the same call shape.

8. **The preamble extractor (`ingest/preamble.py`) handles MORE forms
   than the current handler.** Extractor covers `\newcommand`,
   `\renewcommand`, `\providecommand`, `\DeclareMathOperator` (and
   starred), `\def`, `\edef`, `\gdef`, `\xdef`, `\let`. The v1 handler's
   `_NEWCMD_RE` regex covers only the first three. **The indexer must
   handle every form the extractor produces** — reuse the extractor's
   own normalized `PreambleDoc.macros` list and add a richer parser.

9. **Existing test fixture is reusable.** `tests/fixtures/preamble/sample.tex`
   has 15 macros covering every form the extractor handles. The
   `_patched_extract` helper in `tests/test_preamble.py` patches
   `RAW_DIR`/`PREAMBLE_DIR`/`PREAMBLE_LOG_PATH` onto `tmp_path` — reuse
   this pattern in `tests/test_definitions_index.py`.

---

## 2. Load-bearing quotes (do not paraphrase)

### Definitions-table schema — `.claude/notes/05-storage-and-indexing.md` lines 92–104

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

### BP1 cache discipline — `.claude/notes/07-multi-agent-caching.md` lines 40–49

> "Pin tool JSON schemas. Sort properties alphabetically at serialization
> time. Freeze descriptions as constants in source. A casual edit to a
> tool description blows every sub-agent's cache."

### envelope-key sort — `server/tools.py::envelope`

All dict keys in tool-result payloads are emitted alphabetically sorted
by `_sort_dict(payload)`. New handler response keys (`corpus_version`,
`definitions`, `next_cursor`, `paper_id`, `term`, `total`) serialize in
sorted order automatically; we do not have to write the dict already
sorted, but we MUST NOT bypass `envelope()`.

---

## 3. Design decisions (resolved disagreements + open-question rulings)

These are the decisions the Phase-2 implementer should follow. Each
is annotated with the brief(s) that supported it.

### D1. `definition_id` content-address recipe — `sha256(f"{paper_id}:{symbol}:{expansion}").hexdigest()[:16]`

Brief 1 proposed this exact recipe; Brief 2 was silent. Matches the
existing `chunk_id` content-addressable pattern in `ingest/identifiers.py`.
Two different expansions of the same symbol within the same paper
(redefinition) produce distinct `definition_id`s, but the dedup rule
(D4) decides which row survives.

### D2. `defining_chunk_id` for preamble-derived entries — synthetic sentinel `f"{paper_id}:preamble"`

Brief 1 preferred nullable; Brief 2 preferred the sentinel. **Pick the
sentinel.** The design-note schema spec says `defining_chunk_id: string`
with no nullable annotation; making it non-nullable matches that text.
The sentinel `f"{paper_id}:preamble"` is greppable and traceable, and
will not collide with real `chunk_id`s (those match
`^<paper_id>:c\d+$`).

### D3. `symbol` vs. `symbol_raw` canonicalization — `symbol` = bare command name; `symbol_raw` = same; `expansion` = body

Brief 1 surfaced ambiguity (could `symbol` be the expansion?). Brief 2
proposed the cleaner rule: for `\newcommand{\AA}{\mathcal{A}}`,
`symbol="\\AA"`, `symbol_raw="\\AA"`, `expansion="\\mathcal{A}"`. **Pick
Brief 2's rule.** The design-note example (`symbol="\mathcal{A}"`,
`symbol_raw="\AA"`) is inconsistent with how `\newcommand` works
syntactically — the LEFT side of the brace pair is always the macro
NAME, not the expansion. Treat the design-note example as documentation
drift and store `symbol == symbol_raw == bare command name` (e.g.
`\AA`). The author-form vs. canonical-form distinction matters more
when we later add normalization (e.g. `\mathbb{R}` ↔ `\R` via
expansion-tracing) — that's out of v1 scope and out of this milestone's
scope.

**Implication:** the `symbol` and `symbol_raw` columns will store
identical values at v1 — both fields are kept in the schema for
forward compatibility with future canonicalization, but the indexer
populates them identically today.

### D4. Dedup rule when a symbol is redefined within the same paper — last-seen wins

Brief 2 proposed this; Brief 1 was silent. Aligns with TeX semantics
(`\renewcommand` overrides `\newcommand`). The preamble extractor
processes macro lines in source order; the indexer iterates in that
order and the final `add()` call uses delete-then-insert per `paper_id`
so re-runs cannot leave stale rows.

### D5. Definition-environment chunks — DEFERRED in v1; preamble-only ingestion

Brief 2 advocated deferral; Brief 1 raised a heuristic without
recommending it. **Defer.** The brief's "Out of scope: Semantic
expansion of definition text" language leans toward this. The
`scope` enum stays in the schema (`paper`/`section`/`theorem`) for
forward compatibility, but at v1 every row has `scope="paper"`. Add
a v1.1 sub-milestone note in `.claude/notes/` if needed; do NOT add
infrastructure for scope ≠ paper in this commit. Document explicitly
in the implementation summary that environment-derived rows are
deferred.

### D6. Indexer source — call `load_preamble()` from `ingest/preamble.py`, not re-parse with a narrower regex

Brief 2 explicit; Brief 1 implicit (mentioned the parser-coverage gap).
Reusing the extractor's output means the indexer is "downstream
consumer" not "second parser." Avoids skew between extractor and
indexer.

### D7. Case-insensitive prefix match — apply ONLY to `symbol_raw`, NOT `symbol`

Brief 1 (correctly) flagged that LaTeX commands are case-sensitive
(`\AA` ≠ `\Aa`), making case-insensitive matching semantically wrong
for `symbol`. Brief 2 didn't address. **Apply Brief 1's ruling.** The
fallback hierarchy is:
1. Exact match on `symbol`
2. Exact match on `symbol_raw`
3. Case-insensitive prefix match on `symbol_raw` ONLY

Returns an empty list if no match — never raises.

### D8. LanceDB indexes — two separate scalar indexes (`paper_id` and `symbol_raw`), document that `(paper_id, symbol)` from the design note is satisfied by per-column indexes

Both briefs agree LanceDB ≥ 0.6 does not support composite scalar
indexes. The design-note text "B-tree on `(paper_id, symbol)`" is
semantically satisfied by per-column indexes since LanceDB's query
planner can use both. The third index requested by the design note
("B-tree on `symbol_raw`") becomes a redundant index given the
`symbol_raw` index also benefits from being scanned independently.
**Create two scalar indexes:** `paper_id`, `symbol_raw`. (Do NOT also
index `symbol` — `symbol_raw == symbol` at v1 per D3.) Document this
choice in `ingest/index_definitions.py` module docstring.

### D9. Pagination cursor encoding — integer offset, base64-encoded as opaque string

Brief 1 preferred opaque symbol-string cursor; Brief 2 preferred integer
offset. **Pick integer offset.** Simpler. The corpus is sortable
deterministically by `(symbol, definition_id)` so offset-based
pagination is stable across requests in the absence of concurrent
ingest, which is the v1 contract. Encode as base64 of `str(offset)`
for MCP opaqueness. `next_cursor=null` means no more pages.

### D10. Per-paper replacement on re-ingest — delete-then-insert, not merge_insert

Brief 2 explicit. `tbl.delete(f"paper_id = '{paper_id}'")` followed by
`tbl.add(arrow_table)` cleanly handles the case where a paper goes from
15 definitions to 12 (merge_insert would leave 3 orphaned rows). The
brief says re-running for a paper "replaces them (keyed by `paper_id`)."

---

## 4. Forced changes outside `ingest/index_definitions.py` + `server/handlers/definitions.py`

These are NOT optional. Phase 4's checklist must verify each:

| File | Change | Why |
|---|---|---|
| `ingest/schema.py` | Add `DEFINITIONS_SCHEMA_V1` PyArrow schema constant | New table; mirror the `CHUNKS_SCHEMA_V1` pattern |
| `server/tools.py` | Update `GET_DEFINITIONS` description text; bump `TOOL_SCHEMA_VERSION` from `1` → `2`; add `cursor` arg to `inputSchema` | BP1 cache discipline; new pagination contract |
| `tests/test_server_tool_schema.py` | Re-pin `EXPECTED_TOOL_SCHEMA_SHA256` via `pytest --update-tool-schema-hash` | Tool description + inputSchema changed |
| `server/resources.py` (or equivalent) | Expose a `definitions_table` handle or open-helper for the new table | Handler must use same LanceDB connection pattern as `corpus.py` |
| `tests/test_handlers_definitions.py` (if it exists; otherwise extends `tests/test_handlers_<something>.py`) | Update to assert against LanceDB-backed shape; remove preamble.json-direct-read assumptions | Behavior change |

The Phase-1 researchers did not call out whether `server/resources.py`
exists or what its shape is. The implementer should grep first; if a
single `Resources` class exists, add a `definitions_table` lazy
property. If handlers open LanceDB inline today, follow the existing
inline pattern.

---

## 5. Landmines the implementer must respect (CLAUDE.md §8)

1. **`assert` is BANNED.** Use `if … raise RuntimeError(…)` for every
   invariant in `ingest/index_definitions.py`.
2. **`uv run python -m pytest`** — never the system `pytest` (3.9 vs.
   3.11+ required).
3. **HEREDOC commits.** Commit message will contain apostrophes
   ("author's", "paper's"). Use `git commit -F - <<'COMMIT_EOF' …
   COMMIT_EOF`.
4. **No `--no-verify`, no `--no-gpg-sign`.**
5. **GET_DEFINITIONS description re-pin** is mandatory; do not commit
   with a stale hash.
6. **No Markdown in `ingest/` or `tests/`.** Module docstrings are
   fine; companion `.md` files are not.
7. **`server/` source must not reference `claude-opus`** — pinned by
   `tests/test_model_selector.py::TestForbiddenStrings`. Not directly
   touched by this milestone but worth knowing.
8. **`anthropic` SDK not at runtime** — server is a tool provider. Not
   directly touched; worth knowing.

---

## 6. Test surface (≥ what the brief's acceptance criteria require)

`tests/test_definitions_index.py` (new) must cover:

1. AC1 — `get_definitions(paper_id="2401.01234")` returns paginated
   entries; reusing `tests/fixtures/preamble/sample.tex` (15 macros)
   means page 1 has all 15 with `next_cursor=null`. Add a "synthetic
   200-entry" fixture path or a `range(0, 200)`-generated macro list
   to verify two-page pagination with a non-null `next_cursor` on
   page 1.
2. AC2 — `get_definitions(paper_id="...", term="\\R")` returns the
   `\mathbb{R}` expansion exactly. Term-not-found returns `[]`.
3. AC3 — A paper with no `\newcommand` (empty preamble.json or no
   preamble at all) returns `{definitions: [], total: 0, next_cursor: null}`.
   No 404 or error.
4. AC4 — After indexer runs, the LanceDB `definitions` table has
   scalar indexes on `paper_id` AND `symbol_raw`. Verify via
   `tbl.list_indices()`.
5. AC5 — Implicit: `pytest tests/test_definitions_index.py` passes.
6. **Beyond brief AC:** idempotency test — running the indexer twice
   on the same paper leaves the row count unchanged (delete-then-insert
   does not leak stale rows).
7. **Beyond brief AC:** D6 coverage — a paper with mixed `\newcommand`
   + `\def` + `\let` declarations produces correct rows for each form.
8. **Beyond brief AC:** D7 coverage — prefix-match fallback works on
   `symbol_raw` but does NOT case-fold `symbol`.
9. **Beyond brief AC:** `EXPECTED_TOOL_SCHEMA_SHA256` updated; existing
   `tests/test_server_tool_schema.py` passes with the new pin.

The existing handler tests (whatever path they live at — likely
`tests/test_handlers_definitions.py` if present, otherwise inline in
`tests/test_handlers.py`) will need updating in lockstep.

---

## 7. Open questions remaining for the implementer

None blocking. D1–D10 above resolve every question both briefs
surfaced. The implementer should:

1. Confirm `server/resources.py` shape (lazy `definitions_table`
   property vs. inline open).
2. Confirm exact `pytest --update-tool-schema-hash` flag name from
   `tests/conftest.py` (briefs assert it exists; verify).
3. Decide whether to extend `tests/test_handlers_definitions.py`
   (if present) or write a fresh `tests/test_definitions_index.py`.
   Recommended: keep handler tests in their current file (rename
   assertions only) and put indexer tests in the fresh file.

---

## 8. External writes required

**None.** This milestone is purely local. The only writes are to
`var/arxmcp/index/lancedb/definitions.lance/` (LanceDB table on local
disk), which is an INTERNAL data write, not an external one. The
external-write boundary gate at Phase 4 is therefore **vacuous** —
the implementer commits locally; the user is asked only for the
`git push` authorization at the very end.

```
| type | target | why |
|---|---|---|
| —    | —      | (empty) |
```

---

## 9. Suggested implementation order

1. `ingest/schema.py` — add `DEFINITIONS_SCHEMA_V1`.
2. `ingest/index_definitions.py` — new indexer using `load_preamble()`
   + delete-then-insert.
3. `tests/test_definitions_index.py` — fresh tests against the
   indexer, using the `_patched_extract` fixture pattern.
4. `server/handlers/definitions.py` — rewrite handler to read from
   LanceDB `definitions` table, add pagination, add prefix-fallback,
   keep `(paper_id, term=None)` signature shape (term arg is unchanged;
   only `cursor` is new — or push pagination via tool input schema if
   we want it visible in `tools/list`).

   **Decision point at implementation time:** does the `cursor` arg
   belong in the handler signature (visible in `tools/list`
   `inputSchema`) or as an internal pagination kept hidden behind a
   single-page response? The brief says "paginated at 100 entries per
   page with a `next_cursor` field" — this implies the CLIENT can ask
   for the next page, so the cursor must be a tool argument.
   **Add `cursor` to the inputSchema.** The implementer should keep
   it optional with default `None`.
5. `server/tools.py` — update `GET_DEFINITIONS` description; add
   `cursor` to its `inputSchema`; bump `TOOL_SCHEMA_VERSION` to `2`.
6. `tests/test_server_tool_schema.py` — re-pin via
   `pytest --update-tool-schema-hash` (or whatever the flag is named —
   verify in `conftest.py`).
7. `tests/test_handlers_definitions.py` (if present, otherwise the
   relevant existing handler test) — update for new response shape.
8. Run `make test`; fix anything broken; commit.

---

## 10. Done-when checklist

The Phase-2 implementer can mark this milestone "implement-complete"
when all of:

- [ ] Brief AC1–AC5 each have a verifiable artifact (test, command).
- [ ] `EXPECTED_TOOL_SCHEMA_SHA256` is updated and
      `tests/test_server_tool_schema.py` passes.
- [ ] `TOOL_SCHEMA_VERSION == 2`.
- [ ] Idempotency test passes (D10).
- [ ] D6 mixed-macro-form coverage test passes.
- [ ] D7 prefix-match-only-on-symbol_raw test passes.
- [ ] `make test` reports the new pass count with zero failures and
      `ruff check .` clean.
- [ ] Implementation summary at
      `.claude/notes/milestones/E10_S01/implementation-summary.md`
      enumerates every AC with met/unmet/N+1 reason.
