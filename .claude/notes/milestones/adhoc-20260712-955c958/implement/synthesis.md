# Implement synthesis — adhoc-20260712-955c958

## Built
- **AC1 — production del db removed (5 sites).** All converted to the nested
  explicit-close (conn before db; `db.close()` guaranteed even if
  `conn.close()` raises), each with `conn = None` before `try:`:
  `ingest/kuzudb_schema.py` `apply_schema` + `read_schema_version`;
  `ingest/graph_ingest.py` `ingest`; `ingest/inspire_ingest.py` `enrich` +
  `main`. `grep "del db"` over the 3 production files → 0. Stale/misleading
  comment at kuzudb_schema.py apply_schema rewritten to state the real cause.
- **AC2 — 8 tests unskipped and green on Windows.** Removed the marker + all
  8 decorators; converted the `populated_db` fixture, `build_synthetic_kuzu_graph`,
  and every per-test open/close (7 in test_graph_ingest.py, 22 in
  test_inspire_ingest.py) to the same nested explicit-close. Result on this
  Windows 11 / kuzu 0.11.3 box: `test_graph_ingest.py` + `test_inspire_ingest.py`
  = **76 passed, 0 skipped**.
- **AC3 — ruff clean.** Removed orphaned `import sys` + `import pytest` from
  `_graph_helpers.py` and the two `from tests._graph_helpers import
  kuzu_reopen_unsupported_on_windows` lines. `ruff check .` (whole repo) →
  All checks passed.
- **AC4 — marker fully removed.** Repo-wide grep for
  `kuzu_reopen_unsupported_on_windows` in `*.py` → 0 references.

Chose the **nested `try/finally`** over kuzu's `with A, B:` context managers
(both exist in 0.11.3): the `with` form would force re-indenting 90–140-line
function bodies at 5 sites for zero behavioral gain (research Decision 1).

## Branching note
Main-only repo (CLAUDE.md §4.1). Commits land directly on `main`. Surgical
mode: staged ONLY the 6 milestone files; all other uncommitted WIP (the
2026-07-12 Windows test-greening sweep, phantom CRLF, untracked dirs) left
exactly as-is.

## Files touched (6, the declared surgical scope)
- `ingest/kuzudb_schema.py` — 2 production teardowns + comment rewrite.
- `ingest/graph_ingest.py` — 1 production teardown.
- `ingest/inspire_ingest.py` — 2 production teardowns.
- `tests/_graph_helpers.py` — marker + `sys`/`pytest` imports removed; helper teardown converted.
- `tests/test_graph_ingest.py` — 7 teardowns converted; import + 1 decorator removed.
- `tests/test_inspire_ingest.py` — 22 teardowns converted; import + 7 decorators removed.

Diff: 6 files, +257 −71 (≈328 lines touched; under the 350 mid-flight LOC line).
The 6-file count is the pre-sized, user-approved surgical scope, not creep.

## Deferred (residuals — NOT in this milestone's 6-file scope)
- `server/graph_queries.py::cite_neighbors` (L372-379) — identical `del db`
  bug on the LIVE MCP tool path; a 2nd call in one server session hits the
  Windows lock. No test exercises a double call, so it is latent (its test
  file `test_graph_queries.py` passes today — single reopen tolerated).
  **Highest-consequence residual; recommend a fast-follow.**
- `ingest/intra_paper_refs.py::ingest` (L348-388) — same pattern, 6th ingest CLI.
- `ops/restore_drill_check.py` (~L141-156) — opens a kuzu Database/Connection
  with no lifecycle management at all.
- QueryResult objects not explicitly closed in the 5 functions (kuzu docs
  suggest it; low-risk — one-way ref chain, `QueryResult.__del__` closes).

## external_writes_required
- `git push origin main` (only external write; user-authorized at Phase 4).
- (Residual, NOT a write) POSIX `make test` re-verification — see below.

## Test deltas
No new test files. The 8 guarded tests become live regression coverage for
this exact fix (they fail on Windows without it). Verification run on Windows:
- In-scope: `test_graph_ingest.py` + `test_inspire_ingest.py` → 76 passed, 0 skipped.
- Dependent/sibling: `test_proof_chain.py` (17), `test_graph_queries.py` (34),
  `test_intra_paper_refs.py` (15) → 66 passed, no regression.
- Other importers: security/test_source_ingest, test_arxiv_api,
  test_definitions_index, test_discover_for_notebook, test_server_startup →
  158 passed, 1 pre-existing Windows symlink skip (WinError 1314; not ours).
- **Total: 300 passed, 0 failed, 1 pre-existing skip.**

## Check gate results
- ruff check . : PASS (whole repo clean).
- pytest (all files touching the changed modules): PASS (300 passed, 1 pre-existing skip).
- Full-suite pytest on Windows: NOT run — CLAUDE.md records 29 pre-existing
  Windows-platform failures unrelated to this change; a targeted 300-test
  sweep of the affected subsystem is the meaningful Windows gate.
- **POSIX `make test`: OUTSTANDING RESIDUAL** — this Windows session cannot
  run it. POSIX now executes the NEW explicit-close path for the first time
  (it previously exercised `del db` via advisory-lock tolerance), so "POSIX
  was already green" is not evidence the new code is green there. Must be
  run by the user on macOS/Linux before this is fully verified.
- git status: NOT empty (unrelated pre-existing WIP remains, by design in
  surgical mode). The 6 milestone files are the only ones committed.
