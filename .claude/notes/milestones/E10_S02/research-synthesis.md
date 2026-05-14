# E10_S02 — Research Synthesis

Merged from [research-brief-1.md](research-brief-1.md) and
[research-brief-2.md](research-brief-2.md). Both researchers
converged on three load-bearing findings that the brief got wrong;
the resolutions in §3 below are the most important part of this
synthesis.

---

## 1. Headline findings (consensus across both researchers)

| # | brief assumption | reality (live-verified) | resolution |
|---|---|---|---|
| 1 | `content=''` FTS5 returns `display_name`, `paper_id`, etc. on SELECT | **Contentless FTS5 can only return rowid.** Brief schema is internally inconsistent. | **Two-table schema** — regular `theorem_names` for data, contentless FTS5 over `normalized_name` for index, JOIN by rowid. |
| 2 | "FTS5 trigram fuzzy match" satisfies AC4 (`"riemanroch"` matches "Riemann-Roch") | **FALSE.** FTS5 trigram MATCH requires ALL query trigrams to appear in the indexed value. Researcher 2 live-verified this against SQLite 3.51.0: `"riemanroch"` has trigrams `{ano, noc}` that are not in `"riemannroch"` → MATCH returns 0 rows. | **Add a Python-side trigram Jaccard fallback** after FTS5 MATCH returns empty. Tractable at v1 scale (~hundreds of theorems). |
| 3 | "API stays stable across the swap" (per the existing `FIND_LEMMA_BY_NAME` description) | **Partially false.** The response shape grows: `dedup_key`, `display_name`, `confidence` are new fields. Existing `test_tools_all.py` line 337 asserts `retrieval_mode == "in_memory_scan"` and breaks. | **Superset response** — keep `chunk_id`, `paper_id`, `theorem_name`, `section_path` (back-compat); add new fields. `retrieval_mode` taxonomy updated to 4 values. |

---

## 2. Load-bearing quotes

### Design constitution — `.claude/notes/05-storage-and-indexing.md` § "Table: theorem_names"

> "Mathlib-style exact-match index on theorem labels.
> ```
> name                 string (primary key)      # "Yoneda lemma", normalized
> paper_id             string
> chunk_id             string
> confidence           float
> ```
> Indexes: full-text on `name` (FTS5-style trigram for fuzzy match)."

This is the design note's original sketch. The milestone brief
**extends** it with `dedup_key`, `display_name`, `section_path` to
handle the cross-paper "Lemma 3.4" collision.

### Existing tool description — `server/tools.py::FIND_LEMMA_BY_NAME`

> "Find theorems/lemmas/propositions by their natural-language
> name. v1 ships an in-memory case-insensitive substring scan
> over chunks where theorem_name is non-null. The full-text
> (SQLite FTS5) index lands in E10_S02; the API stays stable
> across the swap."

The "API stays stable" claim is contradicted by the response shape
change (D7 below). The description text must change anyway — both
to remove the deferred-language and to document the new shape.

### Chunker output — `tests/test_chunker.py:135`

> `assert stmt1.theorem_name == "Riemann–Roch"`

Confirms `theorem_name` is the parenthetical from `\begin{theorem}[Name]`;
the chunker DOES emit canonical names like "Riemann–Roch" (note the
em-dash). Tests can rely on `theorem_name` being a clean parenthetical
string.

### BP1 cache discipline — `.claude/notes/07-multi-agent-caching.md:40-49`

> "Pin tool JSON schemas. Sort properties alphabetically at
> serialization time. Freeze descriptions as constants in source.
> A casual edit to a tool description blows every sub-agent's cache."

`TOOL_SCHEMA_VERSION` is at 3 (post-E10_S03); bumps to 4. Hash repin
procedure is the established
`pytest --update-tool-schema-hash` flag + manual
`EXPECTED_BP1_SHA256` update.

---

## 3. Design decisions (resolves the disagreements)

### D1. Two-table SQLite schema — contentless FTS5 + regular `theorem_names`

Both researchers agree the brief's single-table contentless FTS5
schema is broken. Pick the cleanest fix: a regular
`theorem_names` table with all data and a contentless FTS5
virtual table that indexes only `normalized_name`. Queries that
need data JOIN by `rowid` to the regular table.

```sql
CREATE TABLE theorem_names (
    dedup_key TEXT PRIMARY KEY,
    normalized_name TEXT NOT NULL,
    display_name TEXT NOT NULL,
    paper_id TEXT NOT NULL,
    chunk_id TEXT NOT NULL,
    section_path TEXT NOT NULL,   -- JSON array
    confidence REAL NOT NULL
);
CREATE INDEX idx_theorem_names_paper_id ON theorem_names(paper_id);
CREATE INDEX idx_theorem_names_normalized_name
    ON theorem_names(normalized_name);

CREATE VIRTUAL TABLE theorem_names_fts USING fts5(
    normalized_name,
    content='',
    tokenize='trigram case_sensitive 0'
);

PRAGMA user_version = 1;
```

The two tables stay in sync via explicit INSERT/DELETE pairs in
a transaction (Researcher 1's pattern). External-content FTS5
(`content=theorem_names`) would also work but requires `rebuild`
or triggers; contentless is simpler.

### D2. Three-step lookup hierarchy — exact, FTS5 trigram, Python-side Jaccard fallback

The handler tries in order, returning at the first non-empty hit:

1. **Exact match** on `normalized_name`. Direct SQL with the
   `idx_theorem_names_normalized_name` index. `retrieval_mode="fts5_exact"`.
2. **FTS5 trigram MATCH** (substring-tolerant). FTS5 returns rowids;
   JOIN to base table for the columns. `retrieval_mode="fts5_trigram"`.
3. **Python-side trigram Jaccard fallback** (typo-tolerant). Loads
   ALL `normalized_name` values from the base table, computes
   Jaccard against the query trigrams, returns rows with score
   ≥ 0.3 sorted descending. `retrieval_mode="fuzzy_jaccard"`.

The Jaccard step is what makes AC4 satisfiable. At v1 scale
(hundreds of theorems) it's <1ms. At Tier-4 scale (~50K) it's
~10ms — acceptable for a fallback that fires only when exact
and FTS5 MATCH both return empty.

When `paper_id` is provided, the SQL WHERE clauses add
`AND paper_id = ?` to steps 1 and 2; step 3 filters the loaded
candidate set in Python.

### D3. `normalized_name` recipe

```python
def normalize(name: str) -> str:
    # Lowercase, NFKD-decompose, strip combining marks, then strip
    # everything that isn't ASCII alphanumeric.
    nfkd = unicodedata.normalize("NFKD", name.lower())
    no_marks = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "", no_marks)
```

Examples:
- `"Riemann–Roch"` → `"riemannroch"` (em-dash stripped, both ann-
  doubled letters preserved)
- `"Yoneda Lemma"` → `"yonedalemma"`
- `"Lemma 3.4"` → `"lemma34"`

Applied **symmetrically** at index time and query time — the
indexer stores the normalized form; the handler normalizes the
caller's `name` argument before lookup.

### D4. `confidence` recipe

v1 sets `confidence = 1.0` for every chunker-emitted
`theorem_name` row. The chunker only emits the field when it found
an explicit `(Name)` parenthetical in the heading — that's a
high-confidence signal. The float column stays in the schema so a
future milestone can introduce heuristic-based extraction with
lower confidences.

### D5. `dedup_key` recipe

```python
key_input = paper_id + "\x00" + theorem_name + "\x00" + section_path_json
dedup_key = hashlib.sha256(key_input.encode("utf-8")).hexdigest()[:16]
```

`\x00` separator prevents collisions like `("ab", "cd")` vs `("a", "bcd")`.
The 16-hex truncation matches the chunk_id discipline from
`ingest/identifiers.py`.

`section_path_json` is `json.dumps(section_path, separators=(",", ":"),
ensure_ascii=False)` — canonical JSON of the list. The list is
already in document-breadcrumb order so we do NOT sort.

### D6. Database location + Config field

The SQLite DB lives at `var/arxmcp/index/sqlite/theorem_names.db`.
Add `theorem_names_db_path: Path = Path("var/arxmcp/index/sqlite/theorem_names.db")`
to `Config` (next to `cache_db_path`).

### D7. Response shape — superset of current

The new handler response carries every field the v1 handler did,
plus the new fields:

```python
{
    "matches": [
        {
            "chunk_id": "arxiv:2401.00001:0000000000000001",   # preserved
            "paper_id": "2401.00001",                          # preserved
            "section_path": ["3. Main results"],               # preserved
            "theorem_name": "Yoneda Lemma",                    # preserved (== display_name)
            "dedup_key": "abc123def4567890",                   # NEW
            "display_name": "Yoneda Lemma",                    # NEW (alias of theorem_name)
            "confidence": 1.0,                                 # NEW
        },
        ...
    ],
    "retrieval_mode": "fts5_exact" | "fts5_trigram" | "fuzzy_jaccard" | "in_memory_scan_fallback",
    "corpus_version": N,
}
```

The v1 handler also returned `label` (derived from
`_format_label(theorem_name, theorem_label)`) and `theorem_label`.
These are derivable from the new fields by callers; **drop both**.

### D8. Graceful in-memory-scan fallback when the SQLite DB is absent

Mirror the E10_S01 `definitions_table` / E10_S03 `equations_table`
pattern. `Resources.startup()` opens the SQLite DB lazily; if the
file doesn't exist or fails to open, `theorem_names_db` stays
`None` and the handler falls back to the v1 in-memory scan over
the chunks table. `retrieval_mode="in_memory_scan_fallback"` in
that case.

### D9. FTS5 query injection guard — phrase-quote the user input

```python
# Escape any internal double-quotes, then wrap the whole thing.
safe = '"' + name.replace('"', '""') + '"'
cur.execute(
    "SELECT rowid FROM theorem_names_fts WHERE normalized_name MATCH ?",
    (safe,),
)
```

Phrase-quoting tells FTS5 to treat the whole input as a literal
substring (the trigram tokenizer handles substring matching
internally). This blocks FTS5 query-syntax injection
(`AND`, `OR`, `NOT`, `*`, `^`).

### D10. Concurrency — single-writer-per-table

Same contract as E10_S01 / E10_S03: callers must serialize
concurrent invocations of `index_theorem_names_for_paper`. SQLite
WAL mode tolerates concurrent readers but serializes writers at
the file level. Document in the indexer's module docstring.

The indexer uses `INSERT OR REPLACE INTO theorem_names`
(UPSERT keyed on `dedup_key`) plus a DELETE+INSERT on the
contentless FTS5 table — both wrapped in a single transaction
per row.

### D11. New deps — none

`sqlite3` is stdlib. No `pyproject.toml` change. The cleanest
possible dep story for a new index.

---

## 4. Forced cross-file changes

| File | Change | Why |
|---|---|---|
| `server/theorem_names_store.py` (NEW) | Async SQLite store mirroring `server/cache_sqlite.py` | Owns the DB connection, WAL mode, schema migration, query helpers |
| `ingest/index_theorem_names.py` (NEW) | Walks the chunks table; writes rows to the SQLite store | Streaming indexer matching E10_S01/S03 pattern |
| `server/handlers/lemma.py` | Rewritten — 3-step dispatch + graceful fallback | Implements D2 |
| `server/tools.py` | `TOOL_SCHEMA_VERSION` 3→4; new `FIND_LEMMA_BY_NAME.description` | BP1 cache discipline |
| `server/resources.py` | Add `theorem_names_db: Any \| None` field + lazy open | Mirror E10_S01/S03 |
| `server/config.py` | Add `theorem_names_db_path: Path` field + validator | Operator override |
| `tests/test_server_tool_schema.py` | Re-pin hash + `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH=4` | Via `--update-tool-schema-hash` |
| `tests/test_prompts.py` | Re-pin `EXPECTED_BP1_SHA256` | Manual after description change |
| `server/schemas/search_papers_result.json` | Bump `version` 3→4 + `$id` | Snippet contract cross-check |
| `tests/test_tools_all.py` | Update `retrieval_mode` assertion + (maybe) seed SQLite | Existing test asserts `"in_memory_scan"` |
| `tests/test_theorem_names.py` (NEW) | AC1–AC5 coverage + regression tests for D9 injection guard | Per brief |
| `tests/fixtures/theorem_names/` (NEW, maybe) | Synthetic theorem fixtures if needed | Real corpus may not have a Yoneda lemma |

---

## 5. Landmines the implementer must respect

1. **`assert` banned.** Use `if … raise RuntimeError(…)`.
2. **HEREDOC commits.** Description contains backslashes.
3. **`uv run python -m pytest`** — not system pytest.
4. **TOOL_SCHEMA_VERSION 3→4** via `pytest --update-tool-schema-hash`.
5. **`EXPECTED_BP1_SHA256` manual repin** after description change.
6. **`search_papers_result.json::version`** bumps 3→4 in lockstep.
7. **No new `.md` files** in `server/`, `ingest/`, `tests/`.
8. **Phrase-quote FTS5 MATCH input** (D9).
9. **`is_valid_paper_id` gates `paper_id`** at the handler boundary
   (the existing handler already does this; new handler must too).
10. **Concurrency contract — single-writer-per-table** (D10).
    Document explicitly.

---

## 6. Test surface

### AC coverage

- **AC1** — two papers with `"Lemma 3.4"` produce two separate
  entries. Direct unit test on the indexer: stage two chunks with
  identical `theorem_name` but different `paper_id`, run the
  indexer, assert two `dedup_key` rows exist.
- **AC2** — `find_lemma_by_name("Yoneda lemma")` returns results
  across all papers. Hand-seed the SQLite DB with three rows
  (Yoneda from paper A, paper B; Riemann-Roch from paper C);
  query the handler; assert two rows returned, both with
  `theorem_name == "Yoneda Lemma"`.
- **AC3** — `find_lemma_by_name("Yoneda lemma", paper_id="2401.01234")`
  returns only that paper's matches. Same fixture; assert the
  filter actually fires.
- **AC4** — `find_lemma_by_name("riemanroch")` (typo) returns
  "Riemann-Roch" entries. Tests the Python-side Jaccard fallback
  (FTS5 MATCH alone fails this case). Stage "Riemann-Roch" in
  the DB; query with the typo; assert the row is returned with
  `retrieval_mode == "fuzzy_jaccard"`.
- **AC5** — `pytest tests/test_theorem_names.py` passes.

### Beyond-AC tests

- Normalize function correctness (em-dashes, NFKD, alphanum strip).
- FTS5 MATCH injection guard — pass `name = '" OR 1=1 --'` and
  assert no crash, sensible response.
- `paper_id` validation — pass malformed paper_id; assert
  ValueError.
- Graceful fallback — Resources stub with `theorem_names_db=None`;
  assert `retrieval_mode == "in_memory_scan_fallback"`.
- Idempotency — run the indexer twice on the same paper; row
  count unchanged.
- Hash anchors stable after the description change repin.

---

## 7. Open questions for the implementer

1. **Empty/whitespace-only `name`.** Mirror the E10_S01 `term`
   handling — collapse to a sentinel and return empty matches
   list with `retrieval_mode="fts5_exact"` (no work to do). The
   handler's Pydantic `min_length=1` already rejects literal empty
   strings, but a whitespace-only string passes that and would
   normalize to `""`.
2. **`k` cap behavior.** The existing handler caps at `MAX_K = 50`.
   Preserve.
3. **Jaccard threshold tuning.** Start at 0.3. Make it a
   module-level constant `_JACCARD_THRESHOLD = 0.3` so future
   tuning is one-line.
4. **`section_path` JSON list ordering.** Document-breadcrumb order
   (already canonical from the chunker); do NOT sort.

---

## 8. External writes required

**None gated.** Only local file system writes:

```
| type | target | why |
|---|---|---|
| local | var/arxmcp/index/sqlite/theorem_names.db | new SQLite DB created lazily at first index call |
```

No `pyproject.toml` changes. No `uv lock` regeneration.

---

## 9. Suggested implementation order

1. `server/theorem_names_store.py` — sync SQLite open/migrate/query
   helpers wrapped in `asyncio.to_thread` per the
   `server/cache_sqlite.py` pattern.
2. `ingest/index_theorem_names.py` — walks chunks table, writes
   rows. Includes the `normalize_name`, `_dedup_key`,
   `_trigrams` helpers.
3. `tests/test_theorem_names.py` — fixture setup, AC1–AC5,
   normalize tests, injection guard.
4. `server/handlers/lemma.py` — 3-step dispatch + in-memory
   fallback.
5. `server/resources.py` — open `theorem_names_db` at startup,
   mirror E10_S01/S03.
6. `server/config.py` — add `theorem_names_db_path`.
7. `server/tools.py` — description update + version bump.
8. `tests/test_server_tool_schema.py` — re-pin via
   `pytest --update-tool-schema-hash`.
9. `tests/test_prompts.py` — re-pin `EXPECTED_BP1_SHA256`.
10. `server/schemas/search_papers_result.json` — bump version.
11. `tests/test_tools_all.py` — update `retrieval_mode`
    assertion at line 337; possibly seed SQLite for the smoke test.
12. `make test`; commit.

---

## 10. Done-when checklist

- [ ] Brief AC1–AC5 each have a verifiable test.
- [ ] `TOOL_SCHEMA_VERSION == 4` and all three hash anchors repinned.
- [ ] FTS5 MATCH injection guard test passes.
- [ ] `paper_id` validation passes (existing test stays green).
- [ ] Graceful fallback test passes (SQLite DB absent).
- [ ] Idempotency test passes (re-run indexer; row count stable).
- [ ] `make test` green; ruff clean.
- [ ] Implementation summary documents the trigram MATCH limit
      and the Jaccard fallback as the actual mechanism that
      satisfies AC4 (the brief's framing is incorrect — be
      honest about it).
