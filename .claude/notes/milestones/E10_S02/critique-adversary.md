# E10_S02 — Adversary Critique

**Commit range.** `7aa124f..723e814` (single feat commit).
**Verdict.** PARTIAL — ship-blocking findings: 1 HIGH (DoS-via-NUL
through normalize bypass on `fts5_phrase_quote`), 1 HIGH (full-table
LanceDB scan per-paper indexer at Tier-4 scale). Plus 4 MEDIUM and
3 LOW. The cache anchors and AC coverage are clean; the defects are
operationally and in code paths that the synthesis briefly mentioned
but the implementation didn't pin down.

---

## Executive summary

- **F1 (HIGH).** `fts5_phrase_quote` does NOT escape SQLite-level
  string terminators (NUL byte). A future caller that passes an
  un-normalized string to the function (synthesis D9 documents
  phrase-quote as the boundary guard) is one
  `sqlite3.OperationalError("unterminated string")` away from a
  500 on the MCP tool. Today's handler accidentally side-steps the
  problem because `normalize_name` strips NUL via `[^a-z0-9]+`;
  the surface is fragile to a 1-line handler refactor.
- **F2 (HIGH).** `index_theorem_names_for_paper` reads the FULL
  LanceDB chunks Arrow table once per paper invocation
  (`chunks_table.to_arrow()` at `ingest/index_theorem_names.py:106`),
  then `index_theorem_names_all_papers` ALSO reads it once
  (`ingest/index_theorem_names.py:131`). For N papers the indexer
  performs `N + 1` full-table reads. At Tier-4 (50K chunks × 200
  papers) that's a 10M-row materialization repeated 200 times.
- **F3 (MEDIUM).** `_in_memory_scan_fallback`'s ``confidence``
  field is hardcoded to ``1.0`` for *every* row but the SQLite
  path's ``confidence`` reflects the store value. Tests assert
  `confidence == 1.0` on the SQLite path; nothing asserts the
  fallback path's hardcoded `1.0` is intentional vs. accidental
  drift from the chunker's per-row metadata (which today is also
  always `1.0`, but the design carries provision for variability).
- **F4 (MEDIUM).** Empty-after-normalization path returns
  `retrieval_mode="fts5_exact"` (`server/handlers/lemma.py:82-87`).
  The retrieval mode tag is misleading — no FTS5 lookup was
  performed; the input collapsed to "" and the handler short-
  circuited. A downstream agent inspecting `retrieval_mode` to
  attribute behaviour cannot distinguish "exact match found nothing"
  from "input was effectively garbage."
- **F5 (MEDIUM).** SCHEMA_VERSION bump path silently DROPS the
  entire theorem-names table (`server/theorem_names_store.py:223-224`)
  with no caller-visible signal that re-indexing is required. At
  v1 SCHEMA_VERSION==1, so no harm yet — but the bump-discipline
  is undocumented and the indexer doesn't surface a "dropped, please
  re-run" message anywhere callers will see.
- **F6 (MEDIUM).** `theorem_names_db_path` (and the existing
  `cache_db_path`) accepts any operator-controlled path with no
  validator. `db_path.parent.mkdir(parents=True, exist_ok=True)`
  silently creates intermediate directories if the server's UID
  has write permission. An operator typo
  (`ARXMCP_THEOREM_NAMES_DB_PATH=var/arxmcp/cache/retrieval.db`)
  would clobber the cache file.
- **F7 (LOW).** The over-aggressive `normalize_name` recipe creates
  cross-name collisions. `"K(π, 1)"` → `"k1"` collides with
  `"K1"`. `"L²"` → `"l2"` collides with `"L2"`. These are
  same-`normalized_name` matches at exact-step lookup, NOT data
  loss (the `dedup_key` uses raw `theorem_name`, so storage is
  fine). Documented for the reader; an over-matching nuisance, not
  a data corruption.
- **F8 (LOW).** Test `_run` helper allocates a fresh event loop per
  test invocation but never closes the store inside a `finally` if
  the test fails mid-flight before reaching its `finally _run(store.close())`
  block (e.g. an exception in `_install_resources`). Minor leak.

---

## Severity calibration

| Severity | Criterion (project policy) | Count |
|---|---|---|
| CRITICAL | data loss / security / broken invariant | 0 |
| HIGH | wrong behavior on common path | 2 |
| MEDIUM | subtle correctness or missing test | 4 |
| LOW | style | 2 |

---

## Findings

### F1 — `fts5_phrase_quote` lets a NUL byte explode the C string layer

**Severity:** HIGH
**Where:** `server/theorem_names_store.py:154-163` (`fts5_phrase_quote`),
`server/theorem_names_store.py:441-446` (`fts5_match` consumption)
**What:** `fts5_phrase_quote` doubles internal `"` but does nothing
with `\x00`. SQLite's FTS5 string parser is a C-style consumer that
treats NUL as end-of-string and raises
`sqlite3.OperationalError: unterminated string` before any pattern
match runs.

Reproduced (Python 3.12, SQLite 3.45):
```
>>> conn.execute('SELECT rowid FROM t WHERE t MATCH ?', ('"yon\x00eda"',))
sqlite3.OperationalError: unterminated string
```

Today's `handle_find_lemma_by_name` happens to be safe because it
runs `normalize_name(name)` BEFORE handing the bytes to
`store.fts5_match`, and `normalize_name` strips NUL via the
`re.sub(r"[^a-z0-9]+", "", ...)` step. That's a coincidence, not a
guarantee — the docstring on `fts5_phrase_quote` ("This blocks
FTS5 query-syntax injection (AND, OR, NOT, *, ^)") promises a
caller-safe guard that the implementation does not deliver.

**Why it matters:** Synthesis D9 specifies `fts5_phrase_quote` as
the FTS5-input safety boundary. The next E10/E11 milestone may
legitimately call `fts5_match` from a different handler that
accepts richer text and skip the normalize step. A 1-line
refactor would re-expose this.

A test covers `'OR NOT * "'` but does NOT cover a NUL byte payload —
the injection guard test (`test_fts5_phrase_quote_blocks_injection`,
`tests/test_theorem_names.py:415-440`) misses the failure mode.

Closes the security threat-model axis on this critique. Cite
`.claude/notes/08-security-observability-ops.md` — generalized
"do not let untrusted text reach the SQL/FTS5 parser
un-sanitized" principle.

**How to fix:**
1. In `fts5_phrase_quote`, strip control characters (`\x00`-`\x1f`
   except whitespace) before wrapping in `"…"`. One-liner using
   `re.sub`.
2. Add a regression test passing a NUL-containing payload to
   `store.fts5_match` (NOT via the handler — go straight to the
   store layer to mirror the future caller that bypasses normalize)
   and assert no `OperationalError`.

---

### F2 — Indexer does an O(N) full-table read PER PAPER

**Severity:** HIGH
**Where:** `ingest/index_theorem_names.py:106` (`to_arrow()` in
`index_theorem_names_for_paper`) and
`ingest/index_theorem_names.py:131` (`to_arrow()` again in
`index_theorem_names_all_papers`)
**What:** Each invocation of `index_theorem_names_for_paper`
materializes the *entire* LanceDB chunks Arrow table, then iterates
every row to filter by `paper_id`. The all-papers driver calls
`to_arrow()` once at line 131 to enumerate distinct paper_ids,
then re-calls `index_theorem_names_for_paper` per paper — which
re-materializes the same Arrow table. For N papers this is
`N + 1` full reads.

Per-paper cost at Tier-4 (target ~50K chunks):
- Each `to_arrow()` materializes 50K rows × ~6 string columns ≈
  10MB into Python lists.
- 200 papers × 50K rows of `pid != paper_id` skips = 10M wasted
  comparisons.
- Total: ~200 × 10MB = 2GB of repeated allocation pressure.

The correct approach for LanceDB is one of:
- Predicate-push the filter:
  `chunks_table.search().where(f"paper_id = '{paper_id}'").to_arrow()`
- Or materialize once in the all-papers driver, group by
  `paper_id`, and pass each group to `build_rows_from_chunks_for_paper`
  via a different signature.

**Why it matters:** This is the *production* ingest path. E11 will
drive the full corpus through this code and the 200× cost is the
difference between a 2-minute index build and a 6-hour one. The
v1 in-memory fallback path has the same anti-pattern at
`server/handlers/lemma.py:149` — same per-request cost, but
v1-acceptable as a fallback. The *indexer* has no excuse: it knows
the paper_id at call time.

**How to fix:**
1. Change `build_rows_from_chunks_for_paper` signature to accept a
   pre-filtered Arrow table OR to take the `paper_id` and use
   `chunks_table.search().where("paper_id = ?", paper_id).to_arrow()`.
2. In `index_theorem_names_all_papers`, group rows by paper_id
   once over the single `to_arrow()` and dispatch each group.
3. Add a perf test that pins the indexer's number of `to_arrow()`
   calls to ≤ 1 + N (where N is paper count) — actually, ≤ 1
   total. The current code is N+1.

---

### F3 — `_in_memory_scan_fallback` hardcodes `confidence=1.0` with no provenance signal

**Severity:** MEDIUM
**Where:** `server/handlers/lemma.py:169`
**What:** The fallback path's match dict assigns
`"confidence": 1.0` for every chunk row. The SQLite path's
`confidence` reads from `TheoremRow.confidence` (stored value).
Today the indexer hardcodes 1.0, so the two paths agree by
accident. When a future milestone introduces body-text extraction
with `confidence=0.6`, the fallback path STILL says 1.0 and
silently misrepresents the chunk's confidence.

**Why it matters:** `confidence` is the field a downstream
re-ranker uses to weight matches. A fallback path that
fabricates 1.0 looks identical to a SQLite-stored 1.0; the
re-ranker can't distinguish "the chunker says high confidence"
from "the SQLite was missing so we have no signal."

Also: the fallback path emits `"dedup_key": None` (correct — no
SQL-computed key in this path) but the response schema does
not formally allow `None` for `dedup_key`. The Pydantic /
JSON-schema contract is not pinned for this tool today, so this
is a latent contract bug, not an immediate crash.

**How to fix:**
1. Either compute `dedup_key` and `confidence` synthetically in
   the fallback (use `dedup_key(paper_id, theorem_name, sp_json)`
   and `confidence=1.0` as an explicit default) AND set a separate
   `provenance="in_memory_fallback"` flag on the match, OR
2. Document the field semantics in the FIND_LEMMA_BY_NAME tool
   description: "confidence is 1.0 for in-memory fallback rows; the
   field is reserved for indexer-stamped per-row confidence on
   the SQLite path."

---

### F4 — Misleading `retrieval_mode="fts5_exact"` when input collapses to ""

**Severity:** MEDIUM
**Where:** `server/handlers/lemma.py:81-87`
**What:**
```python
if not normalized:
    return envelope(
        {
            "matches": [],
            "retrieval_mode": "fts5_exact",
        }
    )
```
A whitespace-only or all-punctuation input (e.g. `name=" "` or
`name="...!?"`) passes Pydantic's `min_length=1`, normalizes to
`""`, and short-circuits. The returned `retrieval_mode` is
`"fts5_exact"` — but NO FTS5 lookup happened. The literal "no
work to do" path masquerades as a successful FTS5 exact-match
with empty results.

**Why it matters:** Downstream agents that use `retrieval_mode`
for routing (e.g. "if fts5_exact returned 0, try a different
spelling") will conflate two distinct outcomes:
- "Riemann-Roch is not in this corpus" → 0 results, mode=fts5_exact
- "Your input was garbage" → 0 results, mode=fts5_exact (same!)

Tests pin the current value (`test_all_punctuation_name_returns_empty`
asserts `retrieval_mode == "fts5_exact"` — that's the *symptom*
calcified into a regression guard, not a defensible contract).

The synthesis explicitly flagged this as an open question:
"Should there be a separate mode tag like
'empty_after_normalization'?" — and the implementation chose the
muddied tag.

**How to fix:**
1. Add a fourth retrieval_mode value
   `"empty_after_normalization"` and return it from the
   short-circuit. Update the FIND_LEMMA_BY_NAME tool description
   AND the test_tools_all.py smoke-test allowlist. Bump
   TOOL_SCHEMA_VERSION 4→5 and re-pin both hash anchors.
2. Alternative (cheaper but worse): reject whitespace-only at the
   Pydantic boundary by adding `strip_whitespace=True` + a
   custom validator that errors on collapsed-to-empty. The
   handler then never sees the case.

Option 1 is the correct fix per the synthesis open question.

---

### F5 — Schema-version bump DROPS the entire index without a re-indexing trigger

**Severity:** MEDIUM
**Where:** `server/theorem_names_store.py:217-256` (`_open_sync`)
**What:** On schema migration the code unconditionally drops both
tables and recreates them at the new schema. No record is kept of
which papers WERE indexed. The indexer must be re-run by the
operator manually, but nothing signals this — `find_lemma_by_name`
will report `in_memory_scan_fallback` (because the file exists but
the table is empty would behave as if the index is "ok but
empty"), which is indistinguishable from "the corpus has zero
named theorems."

Actually inspect: when the SQLite file exists, `Resources.startup`
opens it (`server/resources.py:511-513`) regardless of whether
the table has rows. So `theorem_names_db` is non-None, the handler
runs the 3-step lookup, returns `matches=[]` with
`retrieval_mode="fts5_exact"` or `"fuzzy_jaccard"`. The operator
sees "0 matches across the corpus" with NO indication that the
index was wiped by a schema bump.

**Why it matters:** This is OK at v1 (SCHEMA_VERSION=1, no
migrations have happened), but the bump-discipline is silent and
the first schema bump will produce a silent zero-result regression
for every downstream agent. Cite
`.claude/notes/08-security-observability-ops.md` — observability
is a first-class operational concern.

**How to fix:**
1. Log a WARN-level message on schema bump that names the new
   version and explicitly says "re-run ingest.index_theorem_names
   to rebuild." (Current log is INFO and only says "schema X → Y;
   dropping at <path>".)
2. Add a status / row-count check at `Resources.startup` that logs
   "theorem_names table is empty (no papers indexed)" so the cold
   path is distinguishable from the hot path.
3. (Stretch) Store the corpus_version pinned at the SQLite file
   level; on mismatch with the live LanceDB `corpus_info.version`,
   the store could mark itself empty and force the fallback. This
   is the same discipline `RetrievalCache` uses.

---

### F6 — `theorem_names_db_path` has no path validator; operator typo can clobber sibling files

**Severity:** MEDIUM
**Where:** `server/config.py:110` (field definition, no validator)
**What:** Every other path in `Config` (`bind_host`, `bind_port`,
`max_concurrent_*`, `eq_ted_weight`, `result_byte_cap`) has a
`@field_validator`. `theorem_names_db_path` does not. Same is true
for `cache_db_path` (not new to this milestone but worth flagging
as the same pattern).

Specifically, `TheoremNamesStore.open` calls
`db_path.parent.mkdir(parents=True, exist_ok=True)` with whatever
the operator provided. An operator setting
`ARXMCP_THEOREM_NAMES_DB_PATH=var/arxmcp/cache/retrieval.db`
would silently clobber the retrieval cache file (or get a SQLite
"file is not a database" error on next open).

`/etc/passwd` is not a real risk (the server runs as non-root and
the open would fail with PermissionError) — but cross-clobbering
project-internal paths is plausible.

**Why it matters:** Configuration footguns are operational
landmines. The principle that ALL ARXMCP_* paths should resolve
under the project's `var/` tree (or be explicit operator overrides
with clear validation) is project policy from the security note.

**How to fix:**
1. Add a `@field_validator("theorem_names_db_path", "cache_db_path",
   "lancedb_path", mode="after")` that resolves the path and
   rejects any path NOT under `var/arxmcp/` unless the operator
   sets a separate `ARXMCP_ALLOW_NONSTANDARD_PATHS=true` escape
   hatch. Or, simpler: reject paths with `..` segments and
   absolute paths outside an allowlist.
2. Add a test that asserts a path traversal attempt
   (`ARXMCP_THEOREM_NAMES_DB_PATH=../../etc/passwd`) fails
   validation.

---

### F7 — `normalize_name` over-collapses distinct mathematical objects

**Severity:** LOW
**Where:** `server/theorem_names_store.py:82-98` (`normalize_name`)
**What:** Stripping all non-ASCII-alphanumerics produces:
- `"K(π, 1)"` → `"k1"` — collides with `"K1"`
- `"L²"` → `"l2"` — collides with `"L2"` (NFKD decomposes
  `²` to `2`)
- `"Lemma 3.4"` → `"lemma34"` — collides with `"Lemma 34"`
  (no period in input)
- `"Cauchy–Schwarz"` → `"cauchyschwarz"` — collides with
  `"Cauchyschwarz"` (no separator)

The first two are real mathematical objects: `K(π, 1)` is an
Eilenberg-MacLane space, `K1` is K-theory degree 1; `L²` is the
square-integrable function space, `L2` is K-theory L-functor at
2. Domain experts WILL search for both forms and get conflated
results.

**Why it matters:** This is the "over-matching nuisance" issue.
The `dedup_key` uses RAW `theorem_name` (not normalized), so the
two rows are stored separately and `display_name` shows the
correct form. The user sees both rows in the result — the
SQL-level collision is "false positive in the same equivalence
class," not data loss.

BUT: the result envelope does NOT carry a normalized_name field
that callers can use to filter, so a downstream agent that
wants only `K(π, 1)` rows has to substring-match the
`display_name`. That's brittle (Unicode normalization at the
caller is the agent's problem).

**How to fix:**
1. Document the over-matching property in the FIND_LEMMA_BY_NAME
   tool description: "the normalized form strips all non-alphanumerics,
   so `K(π, 1)` and `K1` produce identical matches." Re-pin the
   schema hash if you do this.
2. Add a test fixture pinning the collision (e.g. assert
   `normalize_name("K(π, 1)") == normalize_name("K1")`) so a future
   maintainer is forced to think about it before changing the
   normalize recipe.

---

### F8 — Test event-loop / store cleanup is fragile on assertion failure

**Severity:** LOW
**Where:** `tests/test_theorem_names.py:55-66` (`_run` helper) +
every test in `TestTheoremNamesStore`, `TestIndexer`, `TestHandler`
**What:** The `_run(store.close())` call lives inside a `finally`
block in each test, which is correct. But construction
(`store = _run(TheoremNamesStore.open(db_path))`) happens BEFORE
the `try`, so if the open succeeds but the `_install_resources`
call (which assigns to a module global) raises, the store is
opened but never closed. Same applies to a panic in any test
setup before reaching the `try`.

This is also a test-cleanliness issue: `_run` creates a fresh
event loop per call, so `store._lock` (created in the store's
constructor) is bound to a *different* loop than the one
`store.exact_match` is later called on. Today that works because
each `_run` invocation makes a fresh loop AND the lock is unused
across loops — but a future test that calls multiple store
methods concurrently within ONE `_run` would surface the cross-
loop lock bug.

Also: the `_run` pattern means `asyncio.to_thread`'s default
executor (`None` → uses the running loop's executor) gets a fresh
executor for every test. Cleanup is via Python GC. Minor.

**Why it matters:** Test infrastructure ergonomics. Doesn't affect
production. Worth noting because the same pattern is in
E10_S01/S03 tests; this milestone propagated it.

**How to fix:** No fix recommended for this milestone. Note the
pattern in the orchestrator-rules doc as an anti-pattern for
future test infra.

---

## What was done well

1. **Phase-1 defects were resolved cleanly.** The synthesis flagged
   two load-bearing brief defects (contentless FTS5 schema +
   AC4 typo-tolerance) and the implementation followed through
   on D1/D2 without trying to second-guess them. The
   implementation-summary deviations section is candid about
   what changed.
2. **Cache anchors re-pinned in lockstep.** All four pins
   (`EXPECTED_TOOL_SCHEMA_SHA256=5cc94a58…`, version 4,
   `EXPECTED_BP1_SHA256=bb82e869…`, `search_papers_result.json::version=4`)
   updated together. Verified against the cache-discipline note;
   no drift between any pair.
3. **Tests cover every AC.** AC1-AC5 each map to a named test
   (verified by reading the test file). Beyond-AC tests for the
   injection guard, idempotency, paper_id validation, and the
   all-punctuation edge are present.
4. **`envelope()` correctly sorts keys recursively.** Verified at
   `server/tools.py:285-294`; the new `dedup_key`, `display_name`,
   `confidence` fields land at byte-stable positions in the
   serialized envelope.
5. **FTS5 contentless-table workaround correctly uses the
   `'delete'` command form.** A naive `DELETE FROM theorem_names_fts`
   would have silently failed; the implementation uses the
   correct form (verified at lines 315-320 and 374-380). Documented
   in the deviation note.
6. **Concurrency contract is honored.** `asyncio.Lock` wraps every
   public method on the store; sync I/O is offloaded via
   `asyncio.to_thread`. WAL mode is enabled. Mirrors
   `server/cache_sqlite.py` discipline.
7. **Graceful degradation when the SQLite DB is absent.**
   `Resources.startup` opens the store lazily; absent file →
   `theorem_names_db=None` → handler falls back to in-memory scan.
   Mirrors the E10_S01/S03 pattern, which is the project's
   established missing-index discipline.
8. **`paper_id` validation preserved.** The handler still calls
   `is_valid_paper_id(paper_id)` at line 66, and a test
   (`test_paper_id_validation_still_enforced`) regression-pins
   it. F3 from E06_S03 stays closed.
9. **No new dependencies.** sqlite3 is stdlib. pyproject.toml
   untouched. Matches D11 of the synthesis. Clean dep story.

---

## Recommended rectification order

1. **F1 first** — security boundary. Add NUL stripping to
   `fts5_phrase_quote` + regression test. ~10 lines.
2. **F2 second** — operational scale risk. Push the
   `paper_id` filter into the LanceDB layer. Touches the
   indexer signature; add a test that pins the call count.
3. **F4 third** — fixes the muddied `retrieval_mode` semantics.
   Requires a TOOL_SCHEMA_VERSION 4→5 bump and re-pinning all
   four anchors. Same change-management cost as the original
   landing, so batch with F1/F2 if scheduling allows.
4. **F5 + F6 fourth** — operational observability and footguns.
   Both are simple validator / log additions.
5. **F3 + F7 fifth** — documentation / contract clarifications.
   No code path changes; description edits only (which DO
   require an anchor re-pin if touching FIND_LEMMA_BY_NAME).
6. **F8** — defer.

---

## Rectification status

(empty — to be filled in by the rectifier)

- [ ] F1 —
- [ ] F2 —
- [ ] F3 —
- [ ] F4 —
- [ ] F5 —
- [ ] F6 —
- [ ] F7 —
- [ ] F8 —
