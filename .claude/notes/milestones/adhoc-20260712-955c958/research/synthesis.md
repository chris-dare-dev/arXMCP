---
milestone_id: "adhoc-20260712-955c958"
phase: research-complete
research_mode: deep
external_writes_required:
  - "git push origin main"
---

# Research synthesis — adhoc-20260712-955c958

Kùzu DB lifecycle: move production graph-ingest off `del db` to explicit
`conn.close(); db.close()`, then unskip the 8 Windows-guarded tests.
Three briefs (explore / general / adversarial) fully agree on root cause,
API, and the corrected plan below.

## Decisions locked from research (Phase 2 executes these)

1. **Close structure = nested `try/finally`, NOT flat, NOT `with`.**
   The brief's literal `finally: if conn is not None: conn.close(); db.close()`
   is UNSAFE — if `conn.close()` raises, `db.close()` is skipped and the lock
   leaks (worse than `del db`). Use per site:
   ```python
   db = kuzu.Database(str(db_path))
   conn = None
   try:
       conn = kuzu.Connection(db)
       ... existing body unchanged ...
   finally:
       try:
           if conn is not None:
               conn.close()
       finally:
           db.close()
   ```
   `conn = None` is initialized BEFORE `try:` (a `kuzu.Connection(db)`
   construction failure otherwise → `UnboundLocalError` masking the real
   error). `db` never needs a None-guard (always created before `try:`).
   `with kuzu.Database(...) as db, kuzu.Connection(db) as conn:` is
   equivalent+idiomatic (kuzu 0.11.3 supports both context managers) but
   REJECTED here: it forces re-indenting 90–140-line function bodies at 5
   sites → large churn for no behavioral gain.

2. **Convert EVERY `del db` open/close in all 3 test files + the helper**,
   not a hand-picked subset. Per the adversarial per-test trace, only
   `test_f3_..._on_resume` (test_graph_ingest.py) is green from the
   production fix alone; the other 7 depend on the `populated_db` fixture
   (test_inspire_ingest.py:159–181) and/or their own inline `del db` blocks
   (`test_f1` never calls a production site at all — 100% test-body/fixture
   dependent). Consistency + the unskip trap both require the full sweep.

3. **kuzu 0.11.3 API (confirmed vs sha256-pinned v0.11.3 source + installed
   pkg):** `Database.close()` and `Connection.close()` both exist, are
   idempotent, force native release (not GC-timing dependent); a live
   `Connection` holds a strong ref to its `Database` (`self.database`) — the
   exact reason `del db` alone can't drop the refcount while `conn` lives.
   Close order connection→database is kuzu's own DOCUMENTED precondition,
   not just an empirical Windows nuance.

4. **Rewrite the stale comment** at `ingest/kuzudb_schema.py:141-144` — it
   claims `del db` closes deterministically/implicitly on Windows, the exact
   opposite of the verified root cause.

## Affected files (deduped) — EXACTLY 6, surgical scope

**Production (3 files, 5 finally-block sites):**
- `ingest/kuzudb_schema.py` — `apply_schema` (finally L140-145; comment
  L141-144 to rewrite) and `read_schema_version` (finally L182-183).
- `ingest/graph_ingest.py` — `ingest` (finally L667-668).
- `ingest/inspire_ingest.py` — `enrich` (finally L718-719) and `main` inline
  block (finally L820-821).

**Tests (3 files):**
- `tests/_graph_helpers.py` — `build_synthetic_kuzu_graph` teardown (L122);
  DELETE the `kuzu_reopen_unsupported_on_windows` marker (L27-45) AND its
  now-orphaned `import sys` (L18) + `import pytest` (L23) (both used ONLY by
  the marker → ruff F401 otherwise).
- `tests/test_graph_ingest.py` — 7 `del db` sites
  (156,184,244,274,322,347,398) → explicit close; remove the marker import
  (L20) and the 1 decorator (L765, `test_f3_fetch_failure_tracked_and_retried_on_resume`).
- `tests/test_inspire_ingest.py` — 22 `del db` sites incl. the `populated_db`
  fixture (L159-181) → explicit close; remove the marker import (L37) and the
  7 decorators (L223,571,632,720,846,891,980).

`pytest` STAYS imported in both test files (used elsewhere); only the
`from tests._graph_helpers import kuzu_reopen_unsupported_on_windows` lines go.

## Acceptance criteria (traced to brief)

- AC1: all 5 production `finally: del db` sites use the nested-close
  structure (§Decision 1); no `del db` remains in the 3 production files
  (`grep -rn "del db" ingest/kuzudb_schema.py ingest/graph_ingest.py ingest/inspire_ingest.py` → empty).
- AC2: the 8 previously-skipped tests RUN and PASS on this Windows 11 /
  kuzu 0.11.3 workstation (requires the fixture + per-test teardown
  conversions of Decision 2, not just production).
- AC3: `ruff check .` clean (the 4 orphaned-import deletions are the concrete
  failure mode to watch).
- AC4: marker + all 8 decorators + 2 marker-imports fully removed.
- AC5 (residual, NOT satisfiable here): POSIX `make test` (ruff + full
  pytest) re-verified green by the user on macOS/Linux. This Windows session
  can prove the 8 tests pass + ruff clean HERE, but POSIX now runs the NEW
  explicit-close code path for the first time (it previously exercised the
  old `del db` path via advisory-lock tolerance), so "POSIX was already
  green" is NOT evidence the new code is green there. Must be surfaced, never
  silently claimed.

## external_writes_required

```yaml
external_writes_required:
  - "git push origin main"
```
Only true external write; per-event authorized by the user at Phase 4. All
test fetch paths are monkeypatched — zero network egress in this diff's test
scope. POSIX `make test` is an acceptance residual (a local read-only run),
NOT an external write, and is tracked separately (AC5), NOT in this ledger.

## Open questions / residuals (max 5)

1. **Out-of-scope sibling bugs (SURFACE + fast-follow, do NOT fix here).**
   Identical `del db` bug at `server/graph_queries.py::cite_neighbors`
   (L372-379) — the LIVE, wired MCP tool path (a 2nd `cite_neighbors` call
   in one long-running Windows server session hits the lock as a user-facing
   failure, not a test artifact; highest consequence) — and
   `ingest/intra_paper_refs.py::ingest` (L348-388). Plus
   `ops/restore_drill_check.py` (~L141-156) which has NO lifecycle mgmt at
   all. User scoped "EXACTLY these 6 files"; hold scope, flag prominently in
   the final summary, spawn a fast-follow for `graph_queries.py`.
2. **POSIX residual (AC5)** — cannot run from Windows; user must `make test`
   on macOS/Linux before this is "fully verified."
3. **`del db` in 3 out-of-scope test files** (`test_graph_queries.py`,
   `test_intra_paper_refs.py`, `test_proof_chain.py`) + an unmarked
   `test_v1_to_v2_migration_is_idempotent` in test_inspire_ingest.py share
   the reopen pattern; unverified whether they currently pass/flake on
   Windows. Not in scope; note that new Windows failures could surface there.
4. **QueryResult objects not explicitly closed** (minor) — kuzu docs say
   close QueryResult+Connection before Database; the 5 functions close
   conn+db but not their `result` locals. Low-risk (one-way ref chain,
   `QueryResult.__del__` calls close). Defer as polish.
5. **"Exactly 8 guarded" may be an empirically-observed subset** — after the
   fix, run the FULL test_inspire_ingest.py / test_graph_ingest.py (not just
   the 8) on Windows to confirm no other reopen-heavy test regresses.

## Phase 2 path decision

- Estimated diff: ~35 `del db`→nested-close conversions + marker/decorator/
  import removals ≈ **~230–260 LOC across 6 files**. Well under the 800-LOC
  abort; `allow_large_diff=false` is fine.
- Path = **INLINE** (orchestrator writes it). The >5-files heuristic would
  say "delegated," but surgical mode FORCES inline: the guards to remove live
  in the UNCOMMITTED working tree; a `milestone-implementer` worktree off
  HEAD would not contain them. The 6-file count is the pre-sized intended
  scope, not mid-flight creep.
- Stage ONLY these 6 files for the commit; leave all other WIP untouched.
