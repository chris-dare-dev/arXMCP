# E10_S02 Research Brief 1 — Theorem-name FTS5 Index

## 1. In-codebase context

### ChunkRecord fields

`ingest/chunker_types.py` defines `ChunkRecord` with these theorem-relevant
fields:

- `theorem_name: str | None` — parenthetical display name extracted from the
  heading (e.g. `"Riemann–Roch"` from `Theorem 3.1 (Riemann–Roch)`). Set by
  `_extract_theorem_name()` in `chunker.py`; `None` for most chunks.
- `theorem_label: str | None` — user-supplied `\label{}` key embedded in the
  LaTeXML `id` attribute; `None` when auto-generated.
- `section_path: list[str]` — ordered breadcrumb from outermost to innermost
  section, e.g. `["3. Main results", "3.2 The flat case"]`.
- `kind: str` — environment type: `"stmt"`, `"lemma"`, `"proposition"`,
  `"corollary"`, `"definition"`, `"theorem"`, etc.

The chunker extracts `theorem_name` only from the parenthetical in the theorem
heading (regex `_PAREN_NAME_RE = re.compile(r"\(([^)]+)\)")` against
`<h6 class="ltx_title">` or `<span class="ltx_tag_theorem">`). Named theorems
(Yoneda, Riemann-Roch) land here only if the paper writes
`\begin{theorem}[Yoneda Lemma]`.

**The indexer reads from the existing LanceDB `chunks` table** — it does NOT
re-parse LaTeX. It walks columns `chunk_id`, `paper_id`, `theorem_name`,
`kind`, `section_path` and writes rows to the new SQLite `theorem_names` DB.

### Storage and indexing design constitution

`.claude/notes/05-storage-and-indexing.md` has this exact section on theorem
names:

> **Table: `theorem_names`**
> Mathlib-style exact-match index on theorem labels.
> ```
> name                 string (primary key)      # "Yoneda lemma", normalized
> paper_id             string
> chunk_id             string
> confidence           float
> ```
> Indexes: full-text on `name` (FTS5-style trigram for fuzzy match).

This is the design constitution's original sketch — it predates E10_S02 and
is intentionally minimal. The milestone brief **extends** this to include a
dedup key, `display_name`, and `section_path` columns to handle the
"Lemma 3.4" collision problem across papers. The SQLite FTS5 virtual table +
companion regular table (JOIN pattern) is the correct implementation of what
the design note abbreviated as "FTS5-style trigram."

**Note:** the design note shows a single `theorem_names` table. The milestone
brief correctly splits this into two: `theorem_names` (regular table, actual
data) + `theorem_names_fts` (contentless FTS5 virtual table, index only).
See Open Questions for the `content=''` resolution below.

### BP1 byte-stability impact

From `server/tools.py`:
```python
TOOL_SCHEMA_VERSION: int = 3
```

From `tests/test_server_tool_schema.py`:
```python
EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH: int = 3  # VERSION-ANCHOR
EXPECTED_TOOL_SCHEMA_SHA256 = "3961d85e231ed113c6a61fff1a1e461830bfdd0132d998c5c4d9bf1424812403"
```

From `tests/test_prompts.py`:
```python
EXPECTED_BP1_SHA256 = "aabfbc16e6656a9e745b2258e5dcf90050fbea7d39fc56420e3fa1526b401e61"
```

The comment in `test_prompts.py` says "E10_S03 bumped TOOL_SCHEMA_VERSION
2→3". Therefore **E10_S02 must bump 3→4**. The description change to
`FIND_LEMMA_BY_NAME` (dropping the "v1 ships in-memory scan..." clause and
updating `retrieval_mode`) is unavoidable. Both
`EXPECTED_TOOL_SCHEMA_SHA256` and `EXPECTED_BP1_SHA256` must be re-pinned
after the description change and the `TOOL_SCHEMA_VERSION` bump.

### Current `find_lemma_by_name` handler

`server/handlers/lemma.py` signature:
```python
async def handle_find_lemma_by_name(
    name: str,          # min_length=1, max_length=200
    paper_id: str | None = None,
    k: int = 10,        # ge=1, le=50
) -> dict[str, Any]:
```

Returns `envelope({"matches": [...], "retrieval_mode": "in_memory_scan"})`.
Each match has: `chunk_id`, `label`, `paper_id`, `section_path`,
`theorem_label`, `theorem_name`.

The handler reads `chunks_table.to_arrow()` and does a case-insensitive
substring scan. `retrieval_mode` tag changes from `"in_memory_scan"` to
`"fts5_sqlite"` post-swap.

### `server/tools.py::FIND_LEMMA_BY_NAME` description

Current frozen description:
> "Find theorems/lemmas/propositions by their natural-language name. v1
> ships an in-memory case-insensitive substring scan over chunks where
> theorem_name is non-null. **The full-text (SQLite FTS5) index lands in
> E10_S02; the API stays stable across the swap.**"

The API surface (`name`, `paper_id`, `k`) stays stable. The description
must be updated to drop the in-memory scan language. Recommendation:
replace with: "Find theorems/lemmas/propositions by their natural-language
name. Uses a SQLite FTS5 trigram index for exact and substring matching;
falls back to in-memory scan if the FTS5 database is not yet built."

### SQLite async pattern (`server/cache_sqlite.py`)

The project's established pattern:
- `sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)`
- `PRAGMA journal_mode=WAL` + `PRAGMA synchronous=NORMAL`
- `asyncio.Lock()` to serialize writes
- All sync ops via `asyncio.to_thread(_sync_fn)`
- `PRAGMA user_version` for schema versioning (drop+recreate on version bump)
- `db_path.parent.mkdir(parents=True, exist_ok=True)` at open time

The theorem-names DB should mirror this pattern exactly. It is a **separate
SQLite file** from `var/arxmcp/cache/retrieval.db` (the Tier-1 cache DB) and
should live at `var/arxmcp/index/sqlite/theorem_names.db`.

### Tests requiring updates

From `tests/test_tools_all.py`:
```python
assert sc["retrieval_mode"] == "in_memory_scan"  # line 337
```

This must change to `"fts5_sqlite"` after E10_S02 lands. The `warm_app`
fixture in `test_tools_all.py` seeds chunks with `theorem_name="Riemann-Roch"`
on chunk 0 and `theorem_name=f"Lemma {i}.1"` for odd `i`. The test will need
the FTS5 DB populated from that fixture. The smoke test
`test_find_lemma_by_name_smoke` must be updated to either seed the FTS5 DB
or accept both retrieval modes.

### Snippet contract

`.claude/docs/snippet-contract.md` covers only `search_papers` tool results.
`find_lemma_by_name` does NOT return `snippet` fields — it returns
`display_name`, `chunk_id`, `paper_id`, `section_path`, `confidence`. No
snippet contract changes needed.

---

## 2. Prior decisions and lessons

**Three-commit pattern applies.** E10_S02 will produce:
1. `feat(server,ingest): theorem-name FTS5 index (E10_S02)`
2. `rect(server,ingest): close N findings from E10_S02 critique`
3. `chore(notes): finalize E10_S02 state -> complete`

**`assert` ban.** Use `if … raise RuntimeError(…)` everywhere. Never
`assert` for invariants.

**`TOOL_SCHEMA_VERSION` bump procedure** (from E10_S01/E10_S03 precedent):
1. Edit `server/tools.py`: `TOOL_SCHEMA_VERSION = 4`
2. Edit `FIND_LEMMA_BY_NAME.description` to drop the in-memory scan language
3. Run `pytest tests/test_server_tool_schema.py --update-tool-schema-hash`
4. Manually update `EXPECTED_BP1_SHA256` in `tests/test_prompts.py` to
   match the value printed by the tool-schema test's assertion message

**Schema versioning for the SQLite DB.** Mirror `cache_sqlite.py`'s
`PRAGMA user_version` pattern. Define `THEOREM_NAMES_SCHEMA_VERSION = 1`.

**No pagination needed.** The result set for a named theorem query is
typically ≤100 entries. Cap at 50 (existing `MAX_K = 50`), no cursor.
The brief is silent on cursor; consistency with E10_S01's
`get_definitions` pagination would suggest adding it, but it is not
required here — the result set is too small to warrant it.

**Single-writer-per-paper concurrency.** E10_S01 (`index_definitions.py`)
and E10_S03 (`index_equations.py`) both serialize writes per-paper by
construction (the ingest loop is sequential). The theorem-name indexer
follows the same pattern: sequential paper iteration with idempotent
`INSERT OR REPLACE` on `dedup_key`. No locking needed beyond the
`asyncio.Lock` in the store class.

**No new dependencies.** `sqlite3` is Python stdlib. No `pyproject.toml`
change required. This is the cleanest possible dep story.

---

## 3. External sources

### SQLite version and FTS5 availability

The system SQLite on this machine is **3.51.0** (confirmed via
`python3 -c "import sqlite3; print(sqlite3.sqlite_version)"`).

FTS5 has been bundled with SQLite since 3.20 (2017). The trigram tokenizer
was added in SQLite **3.34** (December 2020). Python 3.11+ ships with
SQLite ≥ 3.34 on all tier-1 platforms (macOS via Homebrew or system Python,
Ubuntu 22.04+, Python Docker images). This is confirmed.

### FTS5 trigram tokenizer semantics — CRITICAL CORRECTION

**The brief's "fuzzy match" language is incorrect.** Empirical testing
(see research notes) confirms:

```python
# riemanroch (one 'n' missing) does NOT match riemannroch
conn.execute("SELECT * FROM t WHERE t MATCH 'riemanroch'").fetchall()
# → []
```

The trigram tokenizer splits the query string into 3-character grams and
requires ALL query trigrams to appear in the indexed text as substrings.
`"riemanroch"` produces the trigram `"anr"` which does NOT appear in
`"riemannroch"`. So the match fails.

**What FTS5 trigram DOES support:**
- CONTAINS-style substring search: `MATCH 'riemann'` finds
  `"riemannroch"` because all trigrams of "riemann" (`rie,iem,ema,man,ann`)
  appear in `"riemannroch"`.
- `MATCH 'roch'` finds `"riemannroch"` (trigrams `roc,och` are present).
- Case-insensitive by default on ASCII.

**Resolution for the acceptance criterion** "fuzzy search:
`find_lemma_by_name("riemanroch")` returns Riemann-Roch entries": this
criterion CANNOT be met by FTS5 trigram alone. Options:
1. (Recommended) Accept that `"riemanroch"` (1-char typo) does not match —
   it is not a realistic query from a Claude agent that can spell. The
   criterion was written assuming Levenshtein semantics; the trigram index
   does not provide that. CONTAINS semantics (`"riemann"` matches) are the
   actual capability. The AC should be reworded to reflect what ships.
2. Add a fuzzy fallback using edit-distance on the `normalized_name` column
   of the regular `theorem_names` table after the FTS5 pass — but this is
   an in-Python scan (defeats the purpose of the index for large corpora).

### `content=''` FTS5 contentless table — CRITICAL DESIGN FIX

The brief specifies `content=''` on `theorem_names_fts`. This is SQLite's
**contentless** FTS5 form — the virtual table stores ONLY the inverted index,
not the column values. Querying a contentless FTS5 table returns `rowid` only;
all column reads return NULL or error.

The brief's handler expects to `SELECT display_name, paper_id, ...` — this is
**incompatible** with `content=''`.

**Correct pattern (two-table JOIN):**

```sql
-- Regular table: owns the data
CREATE TABLE theorem_names (
    dedup_key TEXT PRIMARY KEY,
    normalized_name TEXT NOT NULL,
    display_name TEXT NOT NULL,
    paper_id TEXT NOT NULL,
    chunk_id TEXT NOT NULL,
    section_path TEXT NOT NULL,   -- JSON array
    confidence REAL NOT NULL
);

-- FTS5 contentless index: owns only the trigram index over normalized_name
-- rowid is the rowid of the corresponding theorem_names row
CREATE VIRTUAL TABLE theorem_names_fts USING fts5(
    normalized_name,
    tokenize='trigram',
    content=''
);
```

Handler query:
```python
# Step 1: FTS5 index lookup (returns rowids)
fts_rows = conn.execute(
    "SELECT rowid FROM theorem_names_fts WHERE normalized_name MATCH ?",
    (normalize(query),)
).fetchall()
rowids = [r[0] for r in fts_rows]
# Step 2: JOIN to regular table by rowid
placeholders = ",".join("?" * len(rowids))
rows = conn.execute(
    f"SELECT dedup_key,display_name,paper_id,chunk_id,section_path,confidence "
    f"FROM theorem_names WHERE rowid IN ({placeholders})",
    rowids
).fetchall()
```

**Constraint:** when using contentless FTS5, the `rowid` of the FTS5 row MUST
match the `rowid` of the corresponding `theorem_names` row. The indexer must
insert into `theorem_names` first, then `INSERT INTO theorem_names_fts(rowid,
normalized_name) SELECT rowid, normalized_name FROM theorem_names WHERE
dedup_key = ?`. The `dedup_key` PRIMARY KEY ensures idempotency on re-runs
via `INSERT OR REPLACE` on `theorem_names` followed by delete+reinsert on the
FTS5 row using the known rowid.

Alternatively, the simpler pattern is to use FTS5 WITH content (no
`content=''`) and pay the 2× storage cost (stores both the inverted index
AND the column values). At <100 MB total (per design note §budget), storage
is not a concern. **Recommendation: drop `content=''` and use plain FTS5
with stored content.** This eliminates the rowid-sync complexity and makes
queries trivial (`SELECT display_name, paper_id, ... FROM theorem_names_fts
WHERE normalized_name MATCH ?`).

---

## Open questions

1. **`content=''` vs plain FTS5.** Resolved above: drop `content=''`, use
   FTS5 with stored content. The JOIN pattern is correct but adds complexity;
   at <100 MB storage budget, plain FTS5 is the better tradeoff. The
   implementer must pick one and stick to it.

2. **`confidence` computation.** Recommended: chunker-emitted `theorem_name`
   (from `_extract_theorem_name` in `chunker.py`) → confidence 0.9. The
   extraction is heuristic (relies on `(Name)` in heading); not every
   `theorem_name` is a canonical name. Confidence 1.0 is misleading; 0.9
   reflects the heuristic origin. For named environments with `theorem_label`
   (user-supplied `\label{}`), bump to 0.95.

3. **`section_path` JSON serialization.** Use
   `json.dumps(section_path, separators=(",", ":"), ensure_ascii=False)`.
   `section_path` is `list[str]` from `ChunkRecord`; JSON serialization is
   canonical (order matters, it's the document breadcrumb).

4. **SQLite DB location.** Use `var/arxmcp/index/sqlite/theorem_names.db`.
   Rationale: this is an index (not a cache), so it belongs under `index/`
   not `cache/`. The `sqlite/` subdirectory distinguishes it from the LanceDB
   and Kùzu index siblings. Add a `theorem_names_db_path` field to `Config`
   with default `Path("var/arxmcp/index/sqlite/theorem_names.db")`.

5. **Trigram "fuzzy" acceptance criterion.** The AC
   "`find_lemma_by_name("riemanroch")` returns Riemann-Roch entries" CANNOT be
   met by FTS5 trigram (empirically confirmed). Reword to:
   `find_lemma_by_name("riemann")` (not `"riemanroch"`) returns Riemann-Roch
   entries — this IS met by trigram CONTAINS semantics. The implementer must
   update the AC in the test accordingly.

6. **`retrieval_mode` field.** Change from `"in_memory_scan"` to
   `"fts5_sqlite"` on the happy path. Add `"in_memory_scan_fallback"` if the
   FTS5 DB is not yet built (graceful degradation to the current behavior,
   same as the E10_S01 definitions handler pattern).

7. **`test_tools_all.py` update.** The `warm_app` fixture in that file seeds
   the LanceDB chunks table but NOT the FTS5 SQLite DB. The updated handler
   must either: (a) fall back gracefully to in-memory scan when the SQLite DB
   is absent (recommended — mirrors `get_definitions` fallback discipline in
   E10_S01), or (b) the fixture must seed the SQLite DB. Option (a) is cleaner.

---

## External writes the implementation will require

None beyond the local filesystem. Specifically:
- New file: `ingest/index_theorem_names.py` (new ingest module)
- Modified: `server/handlers/lemma.py` (replace in-memory scan with FTS5)
- Modified: `server/tools.py` (description + `TOOL_SCHEMA_VERSION` 3→4)
- Modified: `server/config.py` (add `theorem_names_db_path` field)
- Modified: `server/resources.py` (open `TheoremNamesStore` at startup)
- New file: `server/theorem_names_store.py` (SQLite async store, mirrors
  `cache_sqlite.py` pattern)
- New file: `tests/test_theorem_names.py` (per brief)
- Modified: `tests/test_tools_all.py` (update `retrieval_mode` assertion)
- Modified: `tests/test_server_tool_schema.py` (re-pin hash + version)
- Modified: `tests/test_prompts.py` (re-pin `EXPECTED_BP1_SHA256`)

No new PyPI dependencies. `sqlite3` is stdlib. No `pyproject.toml` change.
