# E10_S02 — Implementation Summary

**One-line summary.** Replaced the v1 in-memory substring scan
behind `find_lemma_by_name` with a SQLite FTS5 trigram index +
Python-side Jaccard fallback. The index lives in a new
project-scoped SQLite file; the handler falls back gracefully to
the legacy in-memory scan when the index is absent. **Closes
MEDIUM: theorem-name dedup** — two papers with "Lemma 3.4" now
produce two separate entries keyed by
`sha256(paper_id+theorem_name+section_path)`.

**Commit range.** `7aa124f..HEAD` (Phase-2 base
`7aa124f` → implementation HEAD at commit time).

---

## Acceptance criteria — status

- [x] **AC1** — Two papers each with a "Lemma 3.4" produce two
      separate entries. Verified by
      [TestIndexer::test_ac1_two_papers_same_lemma_label](tests/test_theorem_names.py)
      and [TestTheoremNamesStore::test_dedup_two_papers_same_name](tests/test_theorem_names.py).
- [x] **AC2** — `find_lemma_by_name("Yoneda lemma")` returns
      results across all indexed papers. Verified by
      [TestHandler::test_ac2_yoneda_across_papers](tests/test_theorem_names.py).
- [x] **AC3** — `find_lemma_by_name("Yoneda lemma", paper_id=...)`
      restricts to that paper. Verified by
      [TestHandler::test_ac3_paper_id_filter](tests/test_theorem_names.py).
- [x] **AC4** — Fuzzy search: `find_lemma_by_name("riemanroch")`
      returns "Riemann-Roch" entries. Phase-1 verified FTS5
      trigram MATCH alone CANNOT satisfy this (query trigrams
      `ano,noc` are not substrings of "riemannroch" — MATCH returns
      0 rows). The handler's third step — Python-side trigram
      Jaccard with default threshold 0.3 — satisfies the AC
      (empirical score ≈ 0.7, comfortably above the threshold).
      Verified by
      [TestHandler::test_ac4_typo_routes_through_fuzzy_jaccard](tests/test_theorem_names.py)
      AND [TestTheoremNamesStore::test_fuzzy_jaccard_handles_typo](tests/test_theorem_names.py)
      (the latter asserts both that FTS5 fails AND Jaccard wins,
      pinning the design intent).
- [x] **AC5** — `pytest tests/test_theorem_names.py` passes — 41
      tests green. Full suite: 1423 passed (+41 from 1382
      baseline), 4 skipped, ruff clean.

---

## Files added / changed

### New

- `server/theorem_names_store.py` — async SQLite wrapper modeled on
  `server/cache_sqlite.py`. Owns the two-table schema (regular
  `theorem_names` + contentless FTS5 `theorem_names_fts`), the
  pure-function helpers (`normalize_name`, `trigrams`,
  `trigram_jaccard`, `dedup_key`, `serialize_section_path`,
  `fts5_phrase_quote`), and the three-step read path
  (`exact_match`, `fts5_match`, `fuzzy_jaccard`).
- `ingest/index_theorem_names.py` — streaming indexer. Walks the
  chunks Arrow table; filters by `theorem_name IS NOT NULL`;
  computes dedup keys; UPSERTs via the store. Idempotent per
  paper (delete-then-insert sweep).
- `tests/test_theorem_names.py` — 41 tests covering pure helpers
  (15), store (10 inc. FTS5 injection guard + idempotency), indexer
  (3), handler (8 inc. AC1–AC4, paper_id validation, all-punctuation
  edge).

### Changed

- `server/handlers/lemma.py` — rewritten. Three-step dispatch
  with `retrieval_mode` ∈ `{fts5_exact, fts5_trigram, fuzzy_jaccard,
  in_memory_scan_fallback}`. Preserves back-compat fields
  (`chunk_id`, `paper_id`, `theorem_name`, `section_path`) and
  adds new ones (`dedup_key`, `display_name`, `confidence`).
- `server/resources.py` — added optional
  `theorem_names_db: Any | None` field; lazy-open at startup;
  closed cleanly on shutdown.
- `server/config.py` — added `theorem_names_db_path: Path` config
  field (default `var/arxmcp/index/sqlite/theorem_names.db`).
- `server/tools.py` — bumped `TOOL_SCHEMA_VERSION` 3→4; rewrote
  `FIND_LEMMA_BY_NAME.description` to document the three-step
  lookup hierarchy.
- `server/schemas/search_papers_result.json` — bumped `version`
  3→4 and `$id` to `v4.json`.
- `tests/test_server_tool_schema.py` — re-pinned hash + version via
  `pytest --update-tool-schema-hash`.
- `tests/test_prompts.py` — re-pinned `EXPECTED_BP1_SHA256`.
- `tests/test_tools_all.py` — updated
  `test_find_lemma_by_name_smoke` to accept any of the new
  `retrieval_mode` values (the existing fixture doesn't seed the
  SQLite index, so the actual mode is `in_memory_scan_fallback`).

---

## Design decisions worth surfacing for Phase-3

These are the synthesis D1-D11 decisions implemented as-shipped.
Phase-3 may legitimately question any of them.

1. **Two-table schema** (D1). Regular `theorem_names` table for
   the canonical data + contentless FTS5 `theorem_names_fts` for
   the trigram index. The brief's single-table `content=''` schema
   was internally inconsistent; this is the live-tested fix.
2. **Three-step lookup** (D2): exact → FTS5 trigram → Python
   Jaccard. The Jaccard step is what makes AC4 satisfiable
   (synthesis verified FTS5 alone fails the case).
3. **Symmetric aggressive normalization** (D3). NFKD-decompose,
   strip combining marks, drop all non-ASCII-alphanumeric. Same
   function applied at index time and query time.
4. **`confidence = 1.0`** (D4) for every chunker-emitted row. The
   chunker only fills `theorem_name` when it found a parenthetical
   in the heading — that's a high-confidence signal. Reserved for
   future heuristics.
5. **`dedup_key = sha256(paper_id + \x00 + theorem_name + \x00 + section_path_json)[:16]`**
   (D5). NUL separators prevent boundary collisions; 16 hex
   matches the chunk-id discipline.
6. **DB at `var/arxmcp/index/sqlite/theorem_names.db`** (D6) —
   sibling of the LanceDB indices.
7. **Superset response shape** (D7). Preserves back-compat fields;
   adds `dedup_key`, `display_name`, `confidence`. Drops the
   derived `label` and `theorem_label` (callers can format from
   `display_name`).
8. **Graceful in-memory-scan fallback** (D8). Mirrors the
   E10_S01/E10_S03 "absent index → graceful degrade" pattern.
   `retrieval_mode="in_memory_scan_fallback"` flags the path.
9. **FTS5 phrase-quoting** (D9). User input goes through
   `fts5_phrase_quote` so `AND`/`OR`/`NOT`/`*`/`^` cannot escape
   the literal. Verified by a unit test that passes
   `'OR NOT * "'` as the query.
10. **Single-writer-per-table** (D10). Documented in the store
    module docstring; SQLite WAL serializes writers at the file
    level.
11. **No new deps** (D11). `sqlite3` is stdlib. `pyproject.toml`
    untouched.

---

## Forced-by-this-milestone cross-file changes

All landed and verified:

- `TOOL_SCHEMA_VERSION` bumped 3→4.
- `EXPECTED_TOOL_SCHEMA_SHA256` re-pinned via
  `pytest --update-tool-schema-hash`. New value:
  `5cc94a589168ed55f5fe12a709d4415a393aff7a193eae94bb16a3b7285a994c`.
- `EXPECTED_TOOL_SCHEMA_VERSION_AT_HASH` re-pinned to `4`.
- `EXPECTED_BP1_SHA256` re-pinned to
  `bb82e869b1cd97823194c54b19100f3d300c6577ce4c92d4812df550ee7fb652`.
- `search_papers_result.json::$id` bumped to `v4.json`; `version`
  bumped to `4`.

---

## Test count delta

| Metric | Before | After |
|---|---|---|
| Tests passing | 1382 | 1423 |
| Tests skipped | 4 | 4 |
| Tests failing | 0 | 0 |
| Ruff status | clean | clean |

New tests live in `tests/test_theorem_names.py` (41 tests). The
+41 delta tracks exactly.

---

## External writes required

**None.** All writes are local:

```
| type | target | why |
|---|---|---|
| local | var/arxmcp/index/sqlite/theorem_names.db | new SQLite DB created lazily at first index call |
```

No `pyproject.toml` changes. No `uv lock` regeneration. The Phase-4
external-write boundary is vacuous; only `git push` requires user
authorization at the end.

---

## Deviations from the brief

1. **FTS5 schema rewritten.** The brief's
   `CREATE VIRTUAL TABLE theorem_names_fts USING fts5(..., content='')`
   listed `display_name`, `paper_id`, etc. as FTS5 columns on a
   contentless table. Contentless FTS5 cannot return non-rowid
   columns; the brief's column list is internally inconsistent.
   Synthesis D1 split this into a regular `theorem_names` table
   (data) + contentless `theorem_names_fts` (trigram index only),
   joined by rowid.
2. **AC4 mechanism is Python-side Jaccard, not FTS5 trigram.** The
   brief assumed FTS5 trigram MATCH would tolerate the
   "riemanroch" → "riemannroch" typo. Synthesis verified live this
   is not the case (FTS5 trigram MATCH requires ALL query trigrams
   to appear in the indexed value; `ano,noc` are missing). The
   handler's third step — Python-side trigram Jaccard with
   threshold 0.3 — satisfies the AC instead. This is documented
   in the tool description and the synthesis.
3. **Response shape is a superset, not strictly stable.** The
   brief said "the API stays stable across the swap"; in reality
   the response shape gains `dedup_key`, `display_name`,
   `confidence` (synthesis D7). Back-compat is preserved by
   keeping the v1 fields.
4. **FTS5 contentless DELETE workaround.** Standard
   `DELETE FROM theorem_names_fts WHERE rowid = ?` is not
   supported on contentless tables; the supported form is
   `INSERT INTO theorem_names_fts(theorem_names_fts, rowid, ...) VALUES ('delete', ?, ?)`
   — implemented in `TheoremNamesStore.upsert_rows` and
   `delete_paper`. Surfaced during test-time integration; not a
   brief-level deviation but worth recording.

These deviations are documented in the synthesis (§3 D1-D11) and
the rectifier should not "fix" them without explicit user
direction.
