# E10_S02 Research Brief 2 — Corpus-grounded + threat-surface focus

Researcher: agent-2 (parallel)
Date: 2026-05-14
Focus: in-codebase corpus data realities, threat surface, external SQLite behavior probing

---

## 1. What the chunker actually emits for `theorem_name`

The extractor lives in `ingest/chunker.py::_extract_theorem_name`. It looks
for a parenthetical inside theorem headings — e.g., `Theorem 3.1 (Riemann–Roch)`
— and extracts only the content inside the parentheses: `"Riemann–Roch"`. It
does NOT emit the numbered label (`"Theorem 3.1"`); that goes to `theorem_label`
via `_extract_theorem_label`. Specifically:

- `theorem_name` = `"Riemann–Roch"` (what the test at line 135 of
  `tests/test_chunker.py` pins: `assert stmt1.theorem_name == "Riemann–Roch"`)
- `theorem_label` = the LaTeX `\label{}` key, or `None` for auto-generated IDs

The test fixture at line 304 also confirms: `any(c.theorem_name == "Key Lemma"
for c in lemma_chunks)`.

**Consequence:** the brief's examples "Yoneda lemma", "Riemann-Roch theorem"
are realistic — these ARE the canonical parenthetical names the chunker emits.
AC2 (`find_lemma_by_name("Yoneda lemma")`) is satisfiable given correctly
structured LaTeX like `\begin{lemma}[Yoneda]`. The test corpus may not have
such entries, so tests MUST use synthetic fixtures, not the 50-paper corpus.

**Corpus scale estimate:** the 50-paper seed has chunks where `theorem_name IS NOT NULL`.
From `test_tools_all.py` line 338: the warm_app fixture exposes at least one
"Riemann-Roch" entry. Plausible range: 50–300 named theorems across 50 papers.
The v1 in-memory scan is described as "sub-millisecond" (lemma.py docstring).
The FTS5 index benefits clarity and correctness more than speed at this scale.

---

## 2. Current `find_lemma_by_name` behavior — exact contract

`server/handlers/lemma.py` is a 88-line in-memory scan:

- Reads **all columns** of the LanceDB chunks table via `to_arrow().to_pylist()`
- Filters by `theorem_name IS NOT NULL` and case-insensitive substring match
- Optional `paper_id` filter (validated via `is_valid_paper_id` from
  `ingest/identifiers.py` — already in place)
- Sorts: exact match first, then `chunk_id` ascending
- Returns: `retrieval_mode: "in_memory_scan"`, matches list with fields
  `chunk_id`, `label`, `paper_id`, `section_path`, `theorem_label`, `theorem_name`

**Response shape delta:** the v2 SQLite-backed handler adds `dedup_key`,
`display_name`, `confidence`. The fields `theorem_label` and `theorem_name`
overlap with `display_name` in different naming. The `label` computed field
(`_format_label(theorem_name, theorem_label)`) does NOT appear in the brief's
new schema. **Resolution:** the new response MUST be a superset. Keep `chunk_id`,
`paper_id`, `theorem_name` (or alias to `display_name`), `section_path` for
backward compat. Add `dedup_key`, `confidence`. Drop `label` (it was a
derived field; callers can derive it themselves). Update `retrieval_mode` to
`"fts5_exact"` or `"fts5_fuzzy"`.

**Existing test assertions in `tests/test_tools_all.py` that must keep passing:**
- Line 337: `sc["retrieval_mode"] == "in_memory_scan"` — THIS WILL BREAK.
  Must update to `"fts5_exact"` or similar. The test is in `TestToolSmoke.test_find_lemma_by_name_smoke`.
- Line 340: `any("riemann" in m["theorem_name"].lower() for m in sc["matches"])` — safe IF we keep `theorem_name` field.
- Line 396–403: `test_find_lemma_rejects_malformed_paper_id` — must keep passing (paper_id validation already implemented).

The `retrieval_mode` assertion at line 337 is the **only breaking change** in
existing tests. The implementer must update it alongside the handler swap.

---

## 3. SQLite FTS5 trigram — verified behavior (critical for AC4)

Live-tested against SQLite 3.51.0 on this machine.

**Finding: FTS5 trigram requires ALL query trigrams to appear in the indexed
value.** `riemanroch` has trigrams `{rie,iem,ema,man,ano,noc,och}`. The
indexed value `riemannroch` has trigrams `{rie,iem,ema,man,ann,nnr,nro,roc,och}`.
The query trigrams `ano` and `noc` do NOT appear in the indexed value — the
MATCH returns **zero rows**. **AC4 as written is unsatisfiable with FTS5 trigram.**

**What DOES work with trigram:**
- `"riemann"` matches `"riemannroch"` and `"riemann-roch"` (all 6 query
  trigrams appear in both indexed values). The current in-memory scan also
  passes this case.
- Prefix matching via `riemann*` (FTS5 prefix syntax) also works.

**Recommended resolution:** AC4 must be reframed. Two options:
1. **Normalize more aggressively before indexing.** Strip ALL non-alphanumeric
   characters AND collapse repeated letters: `"riemann-roch"` → `"riemanroch"`
   at index time AND query time. Then `riemanroch` MATCHES `riemanroch` exactly.
   This is the cleanest fix — the normalization function should be idempotent
   and apply symmetrically to both sides.
2. **Add `rapidfuzz` or `difflib` for Levenshtein post-filtering.** Adds a
   dep (prefer stdlib `difflib.SequenceMatcher` for zero-dep). But this is
   a post-FTS5 pass, not a DB-level index.

**Recommended:** option 1. The `normalized_name` column stores the
aggressively-normalized form. Querying with the same normalization applied to
the user input makes AC4 pass. The brief's description of FTS5 trigram as
"fuzzy" was misleading — it is substring-tolerant, not typo-tolerant. With
symmetric normalization, we get typo-tolerance at the normalization level.

---

## 4. The brief's FTS5 schema inconsistency

The brief's `CREATE VIRTUAL TABLE theorem_names_fts USING fts5(... content='')` 
lists `display_name, paper_id, chunk_id, section_path, confidence` as FTS5
columns on a **contentless** table. SQLite FTS5 contentless tables (`content=''`)
do NOT store content and CANNOT return non-`rowid` columns from SELECT. You
can only get `rowid` from a contentless FTS5 search.

**Verified correct pattern:** use `content=theorem_names` (external content
FTS5). The FTS5 table references the base `theorem_names` table by rowid. After
`INSERT INTO theorem_names_fts(theorem_names_fts) VALUES ('rebuild')`, a JOIN
query returns all base-table columns:

```sql
SELECT t.*
FROM theorem_names_fts
JOIN theorem_names t ON t.id = theorem_names_fts.rowid
WHERE theorem_names_fts MATCH ?
```

This works in SQLite 3.51.0 (live-tested). The brief's two-table schema is
correct in spirit; only the `content=''` token needs to be `content=theorem_names`.

**FTS5 schema for E10_S02:**

```sql
CREATE TABLE theorem_names (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    dedup_key TEXT UNIQUE NOT NULL,
    normalized_name TEXT NOT NULL,
    display_name TEXT NOT NULL,
    paper_id TEXT NOT NULL,
    chunk_id TEXT NOT NULL,
    section_path TEXT NOT NULL,  -- JSON array, opaque TEXT
    confidence REAL NOT NULL
);
CREATE INDEX idx_theorem_names_paper_id ON theorem_names(paper_id);
CREATE VIRTUAL TABLE theorem_names_fts USING fts5(
    normalized_name,
    content=theorem_names,
    content_rowid=id,
    tokenize='trigram case_sensitive 0'
);
```

After inserts, caller must `INSERT INTO theorem_names_fts(theorem_names_fts) VALUES ('rebuild')` to sync.

---

## 5. Async pattern — `asyncio.to_thread` (stdlib sqlite3)

`server/cache_sqlite.py` already uses `asyncio.to_thread` with stdlib `sqlite3`.
The docstring is explicit: "Stdlib ``sqlite3`` is sync; we offload all calls
via ``asyncio.to_thread`` to keep the event loop unblocked. This keeps the
project's no-new-deps discipline intact (``aiosqlite`` would have been a thin
wrapper around the same pattern)."

**`pyproject.toml` change: none.** `sqlite3` is stdlib. No new deps needed.
The theorem-names DB handler must follow the same pattern: open the SQLite
connection in a `asyncio.to_thread` call, use WAL mode + PRAGMA synchronous=NORMAL.

---

## 6. `Resources` integration pattern

`server/resources.py` already has `definitions_table: Any | None = None` and
`equations_table: Any | None = None` as optional `@dataclass` fields, opened
conditionally in `startup()` with a `try/except (ValueError, FileNotFoundError)`
guard. The theorem-names DB follows the same pattern:

```python
# Add to Resources dataclass:
theorem_names_db: Any | None = None  # sqlite3.Connection (E10_S02)

# In startup(), after existing optional tables:
theorem_names_db_path = Path(config.lancedb_path).parent.parent / "index" / "sqlite" / "theorem_names.db"
if theorem_names_db_path.exists():
    theorem_names_db = await asyncio.to_thread(
        lambda: _open_theorem_names_db(theorem_names_db_path)
    )
```

On missing DB, the handler returns `index_status: "absent"` (matching the
`get_definitions` pattern). No server startup failure.

`Config` needs a new field `theorem_names_db_path: Path = Path("var/arxmcp/index/sqlite/theorem_names.db")`.

---

## 7. SQL injection on `name` argument

The handler takes user-supplied `name`. Parameterized queries (`?` placeholder)
handle SQL injection. FTS5 MATCH operand injection is the remaining surface:
a value like `"AND OR NOT *"` triggers FTS5 parse errors. **Guard:** wrap the
user query in double-quotes before passing to MATCH:

```python
safe_query = '"' + name_normalized.replace('"', '""') + '"'
cursor.execute("SELECT ... FROM theorem_names_fts ... WHERE theorem_names_fts MATCH ?", (safe_query,))
```

FTS5 double-quotes produce a phrase query (exact phrase), which is safe and
semantically correct for the exact-match path. For the fuzzy path use the
unquoted trigram query instead.

---

## 8. TOOL_SCHEMA_VERSION bump discipline

From `server/tools.py`: `TOOL_SCHEMA_VERSION: int = 3` (current, post-E10_S01).
The `FIND_LEMMA_BY_NAME.description` currently says "v1 ships an in-memory
case-insensitive substring scan... The full-text (SQLite FTS5) index lands in
E10_S02; the API stays stable across the swap." This text must be updated in
E10_S02 to reflect the shipped FTS5 backend.

Per `tests/test_server_tool_schema.py`: `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH: int = 3`.
Any description change triggers hash drift. Run `pytest --update-tool-schema-hash`
and bump `TOOL_SCHEMA_VERSION` to 4. Update `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH`
to 4 in lock-step.

---

## 9. Single-writer contract for the indexer

Per `ingest/index_definitions.py` (the prior art): "`:func:`index_definitions_for_paper`
assumes a **single-writer-per-paper** contract — callers MUST serialize concurrent
invocations for the same ``paper_id``." SQLite WAL mode tolerates concurrent
readers but serializes writers at the file level. For the theorem-names indexer:
- Per-paper idempotency: `INSERT OR REPLACE INTO theorem_names (dedup_key, ...)`.
  The `dedup_key` PRIMARY KEY (or UNIQUE constraint) acts as the merge key.
  Unlike the definitions indexer (which deletes then inserts to remove stale
  rows), theorem-names uses UPSERT — safer for concurrent writes.
- The FTS5 rebuild step (`INSERT INTO theorem_names_fts(theorem_names_fts) VALUES ('rebuild')`)
  is expensive on a large corpus; prefer incremental: insert into `theorem_names_fts`
  immediately after each `theorem_names` insert, keeping both in sync.

---

## 10. `confidence` field

When the chunker emits `theorem_name` via parenthetical extraction, confidence
is 1.0 (the chunker found an explicit `(Name)` in the heading). Reserve the
float for future heuristics (body-text extraction would emit 0.7). Version 1
should set `confidence = 1.0` for all chunker-derived entries.

---

## Open questions — different angles from peer

1. **FTS5 schema inconsistency is a blocker.** `content=''` (contentless)
   cannot return non-rowid columns. Correct form is `content=theorem_names`
   (external content). Every query pattern changes. Brief must be corrected
   before implementation starts.

2. **AC4 "riemanroch" matching is unsatisfiable with raw trigram.** Live
   verification proves FTS5 trigram MATCH requires ALL query trigrams in the
   indexed value; `riemanroch` and `riemannroch` differ on two trigrams
   (`ano/noc` vs `ann/nnr`). The only safe path to AC4 is symmetric aggressive
   normalization at both index and query time (strip hyphens, collapse repeated
   chars). The brief must either update AC4's example or update normalization spec.

3. **Corpus theorem_name reality:** the chunker emits names like `"Riemann–Roch"`,
   `"Key Lemma"` from parentheticals. Only tests with synthetic fixtures will
   reliably exercise AC2/AC3 (Yoneda lemma); the 50-paper math.AG seed may not
   contain a Yoneda lemma. Tests should build in-memory SQLite fixtures, not
   depend on the live corpus.

4. **Response shape backward compat:** `test_tools_all.py` line 337 asserts
   `retrieval_mode == "in_memory_scan"`. This assertion WILL break when the
   handler swaps to FTS5. The implementer must update this test.
   `theorem_name` field must be preserved (line 340 assertion checks it).

5. **Single-writer contract:** differs from definitions indexer — use `INSERT OR REPLACE`
   (UPSERT on `dedup_key`) rather than delete+insert. Safer for concurrent
   access; explicitly documented.

6. **`Config` needs new field:** `theorem_names_db_path: Path`. Tests that
   instantiate `Config()` with no args get the default. Tests that need the
   DB absent pass a path to a non-existent file. Pattern mirrors
   `cache_db_path`.

7. **FTS5 MATCH injection:** phrase-quote the user input before passing to
   FTS5 MATCH. Parameterized `?` handles SQL injection; double-quoting handles
   FTS5 query syntax injection.

---

## External writes required

- `var/arxmcp/index/sqlite/theorem_names.db` — runtime write by
  `ingest/index_theorem_names.py`. No pre-existing file; created on first
  indexer run.
- `pyproject.toml` — NO change. `sqlite3` is stdlib.
- `server/config.py` — new `theorem_names_db_path` field.
- `server/resources.py` — new `theorem_names_db: Any | None = None` field.
- `server/tools.py` — `TOOL_SCHEMA_VERSION` bump to 4; update
  `FIND_LEMMA_BY_NAME.description`.
- `tests/test_tools_all.py` — update `retrieval_mode` assertion (line 337).
- `tests/test_server_tool_schema.py` — update hash + `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH` to 4.
