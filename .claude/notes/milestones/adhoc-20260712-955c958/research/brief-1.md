---
milestone_id: "adhoc-20260712-955c958"
researcher_role: "explore"
injection_attempts: 0
---

# Research brief (explore) — adhoc-20260712-955c958

All line numbers verified live against the ACTUAL on-disk working tree
(Windows 11, `git diff --stat` confirms the 3 test files carry only
additive today's-sweep hunks: `_graph_helpers.py` +22, `test_graph_ingest.py`
+2, `test_inspire_ingest.py` +8, zero deletions — matches the brief's
"surgical mode" description exactly).

## Affected files / context

### A. Full Kùzu lifecycle site inventory (repo-wide grep)

`kuzu.Database(`, `kuzu.Connection(`, `del db`, `del conn`, `.close()` near
kuzu, across `ingest/`, `server/`, `tools/`, `tests/`:

- **`tools/`** — zero kuzu references (confirmed via grep; brief's premise
  that `tools/` is clean holds).
- **`ingest/`** — 6 raw `kuzu.Database(` sites across **4 files** (not 3 —
  see §B).
- **`server/`** — 1 raw `kuzu.Database(` site (`server/graph_queries.py`),
  not named in the brief — see §B.
- **`tests/`** — every `test_*graph*`/`test_*inspire*`/`test_intra_paper*`/
  `test_proof_chain*` file builds its own inline Kùzu fixtures via the same
  `db = kuzu.Database(...); try: conn = kuzu.Connection(db); ...; finally:
  del db` shape — see §C and §H.
- All other `.close()` hits repo-wide (`tests/test_cache.py`,
  `tests/test_lean_repl.py`, `tests/test_notebook_api.py`,
  `server/graph_queries.py`'s async `Context`/store `.close()` calls, etc.)
  are **unrelated** SQLite/aiosqlite/LeanRepl closers, not Kùzu — noise-free,
  no additional Kùzu sites hiding there.

### B. Production `finally`-block sites — 5 named by the brief + 2 NOT named

All 7 sites share the **identical structural shape**: `db =
kuzu.Database(str(path))` OUTSIDE any `try`, then `try: conn =
kuzu.Connection(db)` as the **first statement inside try**, ending
`finally: del db`. This matters for the fix: `conn` is never referenced in
today's `finally`, but the brief's fix references it — see Risk 1.

1. **`ingest/kuzudb_schema.py::apply_schema`** (lines 114–145):
   ```
   114  db_path.parent.mkdir(parents=True, exist_ok=True)
   115  db = kuzu.Database(str(db_path))
   116  try:
   117      conn = kuzu.Connection(db)
            ... (statements, ALTER TABLE, MERGE _schema_meta) ...
   140  finally:
   141      # kuzu.Database closes implicitly when the Python object is GC'd;
   142      # explicitly drop the local reference so the close runs deterministically
   143      # (matters on Windows where the open file handle blocks parent rmtree
   144      # in pytest tmp_path teardown).
   145      del db
   ```
   **Note:** the comment at 141–144 states the OPPOSITE of the now-verified
   root cause (implicit-GC-close is exactly what does NOT reliably happen
   here) — stale/misleading once fixed; flagged as Risk 5.

2. **`ingest/kuzudb_schema.py::read_schema_version`** (lines 163–183):
   ```
   170  if not db_path.exists():
   171      return None
   172  db = kuzu.Database(str(db_path))
   173  try:
   174      conn = kuzu.Connection(db)
   175      result = conn.execute(...)
   179      if not result.has_next(): return None
   181      return int(result.get_next()[0])
   182  finally:
   183      del db
   ```
   Early-return at 170–171 is BEFORE `db` is created — no cleanup concern
   there.

3. **`ingest/graph_ingest.py::ingest`** (lines 555–668): `apply_schema(db_path)`
   at 555 (internal open+close) THEN `db = kuzu.Database(str(db_path))` at
   556, `try:` 557, `conn = kuzu.Connection(db)` 558 (first in try), ~110
   lines of PASS-1/PASS-2 body, `finally: del db` at **667–668**.

4. **`ingest/inspire_ingest.py::enrich`** (lines 570–719): `apply_schema(db_path)`
   at 578 THEN `db = kuzu.Database(str(db_path))` at 579, `try:` 580,
   `conn = kuzu.Connection(db)` 581 (first in try), `finally: del db` at
   **718–719**.

5. **`ingest/inspire_ingest.py::main`** (CLI, lines 803–821): `apply_schema(args.kuzudb)`
   at 803 (unconditional) THEN, only in the `else` branch (no `--seed-file`),
   `db = kuzu.Database(str(args.kuzudb))` at 816, `try:` 817, `conn =
   kuzu.Connection(db)` 818, `paper_ids = sorted(_existing_paper_ids(conn))`
   819, `finally: del db` at **820–821**.

**NOT named by the brief — same pattern, same bug exposure:**

6. **`ingest/intra_paper_refs.py`** (lines 341–388): `apply_schema(db_path)`
   at 341 THEN `db = kuzu.Database(str(db_path))` at 348, `try:` 349, `conn
   = kuzu.Connection(db)` 350, per-paper loop calling `process_paper(...,
   conn)`, `finally: del db` at **387–388**.

7. **`server/graph_queries.py::cite_neighbors`** (lines 360–380, `async def`
   at line 303): `db = kuzu.Database(str(Path(kuzudb_path)))` at 372,
   `try:` 373, `conn = kuzu.Connection(db)` 374, `rows = await
   asyncio.to_thread(_execute_traversal, conn, ...)` 375–377, `finally: del
   db` at **378–379**. `conn.close()`/`db.close()` are plain sync calls
   (kuzu bindings are sync C++); safe to call directly in the `finally`
   without `await` — consistent with the rest of this function.

   **This site is the live MCP-tool runtime path.**
   `server/handlers/citations.py::handle_cite_neighbors` (the WIRED, non-stub
   handler per `citations.py:1-6` docstring — "Replaces the v1 empty stub…
   verification-feedback-m1") calls `cite_neighbors(...)` on **every**
   `cite_neighbors` tool invocation (`server/handlers/citations.py:111-118`).
   A long-running `make up` server process on a Windows dev workstation that
   receives **two or more** `cite_neighbors` calls will hit this exact "IO
   exception: Could not set lock on file" on the second call — this is a
   **live-server correctness bug on Windows**, not merely a test/CLI
   artifact. (Production Linux containers are unaffected — POSIX advisory
   locks tolerate the overlap, per the brief's verified root cause.)

### C. Test-file teardown inventory (the 3 files named in TESTS scope)

- **`tests/_graph_helpers.py::build_synthetic_kuzu_graph`** (lines 98–123):
  `kuzudb_schema.apply_schema(db_path)` 98 (internal open+close) THEN `db =
  kuzu.Database(str(db_path))` 99, `try:` 100, `conn = kuzu.Connection(db)`
  101, MERGE loop + `graph_ingest._merge_cite(...)` calls, `finally: del
  db` at **122**. Exactly 1 real code `del db` site in this file — grep
  hits 4 total but 3 are prose (`` `del db` `` mentioned in the marker's own
  docstring/reason string at lines 29, 36, 42 — all disappear naturally
  when the marker block is deleted).

- **`tests/test_graph_ingest.py`** — exactly **7** `del db` sites (grep
  `-c` confirmed), none in the 1 decorated test's own body (see §E #8):
  156, 184 (`TestSchemaMigration`), 244, 274, 322, 347 (`TestIngestHappyPath`),
  398 (`TestResume`).

- **`tests/test_inspire_ingest.py`** — exactly **22** `del db` sites (grep
  `-c` confirmed). The `populated_db` fixture (lines 159–181, single
  open/close) is reused by ~15 non-decorated tests that each additionally
  open `kuzu.Database(str(populated_db))` once more in their own body
  (e.g. lines 396, 442, 489, 529, 697, 733(dup w/ #E4), 762…) — i.e. most
  tests in this file ALSO reopen the same path once, just not in the dense
  2–4×-reopen shape the 7 decorated tests exhibit. See Risk 3.

### D. `kuzu_reopen_unsupported_on_windows` — every reference, repo-wide

Confirmed via a repo-wide grep (only match outside the 3 files below is
the milestone's own `state.json`, which is metadata, not code):

- **1 definition**: `tests/_graph_helpers.py:38-45`.
- **2 importers**, both already accounted for by the brief — no
  third importer exists anywhere in the repo:
  - `tests/test_graph_ingest.py:20`
  - `tests/test_inspire_ingest.py:37`
- **8 decorator applications** total:
  - `tests/test_graph_ingest.py:765` → `test_f3_fetch_failure_tracked_and_retried_on_resume`
  - `tests/test_inspire_ingest.py:223` → `test_simulated_v1_db_migrates_to_v2`
  - `tests/test_inspire_ingest.py:571` → `test_both_sources_edges_coexist`
  - `tests/test_inspire_ingest.py:632` → `test_f1_inspire_remerge_preserves_doi_when_response_drops_field`
  - `tests/test_inspire_ingest.py:720` → `test_f2_enrich_accepts_old_style_hep_th_id`
  - `tests/test_inspire_ingest.py:846` → `test_f6_failure_run_flushes_checkpoint_at_batch_size`
  - `tests/test_inspire_ingest.py:891` → `test_f8_arxiv_categories_filter_anchor_for_post_f9`
  - `tests/test_inspire_ingest.py:980` → `test_f3_fetch_failure_tracked_and_retried`

### E. Close-and-reopen trigger per guarded test (structural read, not executed)

1. **`test_f3_fetch_failure_tracked_and_retried_on_resume`**
   (`test_graph_ingest.py:766-816`): no raw `kuzu.Database()` in the test
   body at all — the reopen is entirely via **2 calls to
   `graph_ingest.ingest(seed_ids=..., db_path=db_path, ...)`** against the
   same `db_path` (lines 790 and 806), simulating a resume. Each call
   internally does `apply_schema` (open+close) + its own open+close — 4
   total raw opens across the test.
2. **`test_simulated_v1_db_migrates_to_v2`** (`test_inspire_ingest.py:224-261`):
   densest pattern — 3 explicit `db = kuzu.Database(...)` calls in the test
   body (228, 244, 255) PLUS 1 more inside `kuzudb_schema.apply_schema(db_path)`
   at 252 — 4 total opens on one path, hand-building a v1 schema then
   verifying the v2 migration.
3. **`test_both_sources_edges_coexist`** (`test_inspire_ingest.py:572-620ish`):
   2 explicit opens on `populated_db` (579, 602) — likely OpenAlex-edge
   write then INSPIRE-edge write verification.
4. **`test_f1_inspire_remerge_preserves_doi_when_response_drops_field`**
   (`test_inspire_ingest.py:633-680ish`): 2 explicit opens on `populated_db`
   (648, 664) — write DOI, re-merge with DOI dropped, verify DOI survives.
5. **`test_f2_enrich_accepts_old_style_hep_th_id`**
   (`test_inspire_ingest.py:721-775ish`): 2 explicit opens on `populated_db`
   (733, 762).
6. **`test_f6_failure_run_flushes_checkpoint_at_batch_size`**
   (`test_inspire_ingest.py:847-880ish`): `apply_schema` (861) + 1 explicit
   open (867, `del db` 875) for setup, THEN (not shown in this grep window
   but implied by the test name/F6 checkpoint-flush semantics) calls
   `inspire_ingest.enrich(...)` which reopens internally — setup-reopen via
   production-call pattern, same class as #1.
7. **`test_f8_arxiv_categories_filter_anchor_for_post_f9`**
   (`test_inspire_ingest.py:892-930ish`): same shape as #6 — `apply_schema`
   (906) + 1 explicit open (911, `del db` 923) then an `enrich()` call.
8. **`test_f3_fetch_failure_tracked_and_retried`**
   (`test_inspire_ingest.py:981-1026`): no raw `kuzu.Database()` call
   visible in this test's own body in the grep window — almost certainly
   calls `inspire_ingest.enrich(...)` **twice** (resume pattern, mirroring
   #1) rather than opening the DB directly.

**Assessment:** all 8 tests reopen the same on-disk path ≥2 times within
one Python process, either directly or via ≥2 calls into a production
function that itself opens+closes. Once the 5 (or 7 — see Risk 2) named
production sites AND the helper's `finally: del db` (§C) move to explicit
`conn.close(); db.close()` with the `conn = None` guard, the structural
cause these 8 tests exercise is removed at every point they touch. Nothing
found suggests a reason any of the 8 would still fail post-fix.

### F. kuzu pin + installed module capabilities

- `pyproject.toml:142`: `"kuzu==0.11.3"`. `uv.lock:85`: `{ name = "kuzu",
  specifier = "==0.11.3" }`; a `kuzu-0.11.3-*-win_amd64.whl` exists for
  cp311/cp312/cp313 (uv.lock:718,723,728).
- Installed at `.venv\Lib\site-packages\kuzu\__init__.py`, confirmed via
  `uv run python -c "import kuzu"`: `kuzu.__version__ == "0.11.3"`.
  `hasattr(kuzu.Database, 'close') == True`, `hasattr(kuzu.Connection,
  'close') == True`. `kuzu.Database` also exposes a
  `check_for_database_close` method (undocumented here; possibly useful for
  a defensive post-close assertion in tests, not required by the brief).

### G. `tests/conftest.py` — no Kùzu-specific fixtures

Read in full (336 lines). Autouse fixtures present: `KMP_DUPLICATE_LIB_OK`
env-var setdefault/cleanup (lines 36–49, unrelated — faiss/PyTorch OpenMP),
`_patched_store_stats_path`, `_patched_bm25_stats_path`,
`_patched_bm25_index_root`, `_reset_session_state_for_tests`,
`_patched_cache_db_path`, `_patched_operator_settings_db`. **None reference
Kùzu, `kuzudb`, or any of the graph test files' `db_path`/`populated_db`/
`kuzu_db` fixtures** — those are all locally defined inside each test file
against `tmp_path`, fully self-contained. No cross-file interaction risk.

### H. Residual risk NOT covered by the brief's 6-file scope (same bug pattern, unguarded)

Beyond §B's 2 extra production sites, 3 more test files build/reopen Kùzu
DBs with the identical `del db`-only teardown and carry **zero** Windows
accommodation (no skip, no reference to
`kuzu_reopen_unsupported_on_windows`) — confirmed via grep for
`win32|platform` returning no matches in either file:

- **`tests/test_graph_queries.py`** — `kuzu_db` fixture (lines 62-94, `del
  db` at 93) builds+closes, then **every test** calls `cite_neighbors(...)`
  (imports at line 34), which reopens the same path again inside
  `server/graph_queries.py` (§B.7). That is a 2-open reopen chain on every
  single test in this file.
- **`tests/test_intra_paper_refs.py`** — a module-level fixture opens+closes
  (132/141), and 3 separate tests in `TestIngest` (252/264, 282/290,
  331/339) each reopen that same `kuzu_db` path again.
- **`tests/test_proof_chain.py`** — imports `build_synthetic_kuzu_graph`
  from `_graph_helpers.py` directly (line 41); its `graph_corpus` fixture
  (lines 66+) calls `build_synthetic_kuzu_graph()` (1 open/close), THEN
  reopens immediately for a fixture-time edge-count assertion (`db =
  kuzu.Database(str(kuzu_path))` at line 93, `del db` at line 116), and the
  test bodies then call `cite_neighbors(...)` (imported line 37), which
  reopens a THIRD time via `server/graph_queries.py`. A second `del db` site
  exists at line 205 (likely a second fixture/test). This file has the
  densest reopen chain of any file in the repo and is entirely outside
  the brief's declared scope.

Fixing `tests/_graph_helpers.py::build_synthetic_kuzu_graph`'s teardown (in
scope) will improve `test_proof_chain.py` partially, but its own inline
`del db` sites (93-116, 205) and its dependency on `cite_neighbors` (§B.7,
out of scope) remain untouched by a strictly-6-file fix.

## Acceptance criteria the implementer must meet

1. All 5 brief-named production `finally` blocks — `ingest/kuzudb_schema.py`
   lines 140-145 (`apply_schema`) and 182-183 (`read_schema_version`);
   `ingest/graph_ingest.py` lines 667-668; `ingest/inspire_ingest.py` lines
   718-719 and 820-821 — replace `del db` with: `conn = None` initialized
   before the `try`, and `finally: if conn is not None: conn.close();
   db.close()` (close connection before database, per the brief's verified
   ordering).
2. `tests/_graph_helpers.py::build_synthetic_kuzu_graph`'s `finally: del
   db` (line 122) and the matching teardown blocks in
   `tests/test_graph_ingest.py` (7 sites: 156,184,244,274,322,347,398) and
   `tests/test_inspire_ingest.py` (22 sites) move to the same
   explicit-close discipline.
3. `tests/_graph_helpers.py`'s `kuzu_reopen_unsupported_on_windows` marker
   (lines 38-45) is deleted, along with its now-orphaned `import sys`
   (line 18) — confirmed via grep that `sys.` and `pytest.` appear ONLY
   inside the marker block in this file, so `import pytest` (line 23)
   likely also becomes unused **unless** a later part of this fix adds a
   new `pytest.fixture`/`pytest.raises` usage; verify before deleting.
4. All 8 `@kuzu_reopen_unsupported_on_windows` decorator lines (§D) and the
   2 import lines (`test_graph_ingest.py:20`, `test_inspire_ingest.py:37`)
   are removed.
5. The 8 previously-skipped tests (§D/§E) run and pass on this Windows 11 /
   kuzu 0.11.3 workstation.
6. `ruff check .` is clean after the edit — the unused-import risk in AC#3
   is the concrete failure mode to watch for.
7. The stale comment at `ingest/kuzudb_schema.py:141-144` ("kuzu.Database
   closes implicitly when the Python object is GC'd") asserts the opposite
   of the verified root cause and should be corrected alongside the code
   change, not left to mislead the next reader.

## Risks and open questions

1. **Unbound-`conn` correctness hazard (all 7 sites, not just 5).** In
   every site (§B), `conn = kuzu.Connection(db)` is the FIRST statement
   inside `try` — if it raises, today's `finally: del db` never references
   `conn` so it's safe; the NEW `finally: if conn is not None: conn.close();
   db.close()` pattern is invalid without the brief's specified `conn =
   None` pre-`try` initialization. Missing that guard turns a rare
   `Connection` construction failure into a new `NameError` masking the
   original error.
2. **Scope gap: 2 production sites with the identical bug, not named by
   the brief.** `ingest/intra_paper_refs.py:341-388` and, more importantly,
   `server/graph_queries.py:360-380` — the latter is the live,
   already-wired `cite_neighbors` MCP tool's read path
   (`server/handlers/citations.py:111-118`), meaning this Windows lock bug
   is reachable from a **running `make up` server**, not just ingest CLIs
   and tests. Whether to extend this milestone's scope to cover these 2
   sites or file a fast-follow is a decision Phase 2/the user should make
   explicitly, not one this research brief resolves.
3. **Unknown status of structurally-identical unguarded reopens elsewhere.**
   `tests/test_graph_queries.py`, `tests/test_intra_paper_refs.py`,
   `tests/test_proof_chain.py`, and even inside the two in-scope files
   themselves (e.g. `test_inspire_ingest.py:209-221
   test_v1_to_v2_migration_is_idempotent`, which calls `apply_schema` 3×
   back-to-back plus 1 explicit reopen — a reopen density comparable to
   the guarded `test_simulated_v1_db_migrates_to_v2`) all reopen the same
   path without any Windows skip. This session cannot execute pytest
   (read-only/git-grep-only constraint) so it is unverified whether these
   currently fail, flake, or reliably pass on Windows — flagging as an
   open question rather than asserting either way. Phase 2 should not be
   surprised if new Windows failures surface here even after the declared
   6-file fix lands cleanly.
4. **POSIX re-verification is structurally impossible from this session.**
   This is a Windows 11 workstation; the brief's own ACCEPTANCE requires
   POSIX to "stay green and be re-verified there" and explicitly says this
   "likely must be performed by the user on their macOS/Linux workstation."
   Confirmed: no POSIX runner is available here. This MUST be surfaced as
   an explicit residual in the milestone's final summary, not silently
   marked complete.
5. **`tests/test_inspire_ingest.py`'s `populated_db` fixture is reused by
   ~15 non-decorated tests** that each reopen it once (§C). This is a
   lighter reopen pattern (2 total opens) than the 8 guarded tests
   (3-4+ opens), which may explain why the sweep's live Windows run didn't
   catch them — but it also means the "exactly 8" list may be an
   empirically-observed subset rather than an exhaustive one; worth a
   quick sanity pass (run the full file, not just the 8) once the fix is
   in, before declaring victory.
