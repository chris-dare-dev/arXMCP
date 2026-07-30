---
name: research-synthesis
milestone: adhoc-20260712-698fead
phase: research-complete
brief_source: inline
---

# Research synthesis — adhoc-20260712-698fead

Kuzu 0.11.3 close-discipline fix for the residual `finally: del db` sites,
following the proven idiom shipped in `adhoc-20260712-955c958` (commit `6c5ff0d`).
Both researchers (explore + general) returned `complete`; no BLOCKER.

## Affected files (deduped) — 5 files, inline path

| # | File | Change |
|---|---|---|
| 1 | `server/graph_queries.py` | Site 1 `cite_neighbors` (async): add `conn = None` before try, replace `finally: del db` (L378-379) with nested close. `db` opened at L372 **before** try → no db-guard needed. |
| 2 | `ingest/intra_paper_refs.py` | Site 2 `ingest`: add `conn = None` before try, replace `finally: del db` (L387-388) with nested close. `db` at L348 before try → no db-guard needed. |
| 3 | `ops/restore_drill_check.py` | Site 3 `smoke_check_kuzu`: **Option A** — pre-init BOTH `db = None` and `conn = None`, keep `db = kuzu.Database(...)` inside the existing `try/except`, add a `finally` after the except with `is not None` guards on BOTH closes. |
| 4 | `tests/test_graph_queries.py` | (a) Convert the in-file `kuzu_db` fixture teardown (`del db` at L93) to nested close; (b) add the double-reopen regression test. |
| 5 | `tests/test_intra_paper_refs.py` | Convert 4 `del db` teardowns (L141 fixture, L264, L290, L339) to nested close. |

Estimated diff: ~60-80 LOC across 5 files, purely mechanical + 1 new test.
No novel architecture → **inline path** (≤300 LOC AND ≤5 files). Mid-flight
≥6-file scope gate not tripped.

## Site 3 decision — Option A (preserve exception contract)

`smoke_check_kuzu` opens `db` *inside* a `try/except Exception → raise
RuntimeError("...is unreadable...")`. `run_check()` catches exactly
`except RuntimeError` to return a clean exit-code-1. The brief's literal pattern
(unconditional `db.close()`) would raise `UnboundLocalError` when
`kuzu.Database()` itself fails (live-verified by the general researcher),
masking the intended RuntimeError and crashing the CLI with a raw traceback.
Option A keeps `db` inside the try, guards both closes → **no behavior change**
(binding AC). This is the one site where `if db is not None:` is required (the 5
already-shipped sites never need it because their `db` open is unconditional).

## The canonical nested-close block (must match 955c958 byte-for-byte in shape)

```python
db = kuzu.Database(...)
conn = None
try:
    conn = kuzu.Connection(db)
    ... body ...
finally:
    try:
        if conn is not None:
            conn.close()
    finally:
        db.close()
```

Nested (not flat `if conn is not None: conn.close(); db.close()`) is
NON-NEGOTIABLE — the flat form skips `db.close()` if `conn.close()` raises,
leaking the lock (worse than `del db`). 955c958 synthesis Decision 1 rejected
the flat form explicitly.

## Acceptance criteria (deduped, merged from both briefs)

1. All 3 production sites contain no `del db`; each closes conn-before-db,
   nested. Verify: `grep -rn "del db" server/graph_queries.py ingest/intra_paper_refs.py` → empty.
2. Site 3 pre-inits BOTH `db = None` and `conn = None` and guards the inner
   close with `if db is not None:`. A `kuzu.Database()` failure must still
   surface as `RuntimeError("restored Kùzu DB at ... is unreadable: ...")`,
   NOT `UnboundLocalError` — so `run_check`'s `except RuntimeError` still catches it.
3. New regression test in `tests/test_graph_queries.py` calls `cite_neighbors`
   twice against the same `kuzudb_path` in one process and asserts no
   `"Could not set lock on file"` RuntimeError (call convention:
   `cite_neighbors(CHUNK_A, depth=1, direction="cites", kuzudb_path=kuzu_db, lancedb_path=None)`).
4. All 4 `del db` teardowns in `tests/test_intra_paper_refs.py` (L141, L264,
   L290, L339) converted to nested close.
5. `test_graph_queries.py`'s own `kuzu_db` fixture teardown (L93) converted too
   (in-file; required so the new test cleanly isolates the close path).
6. `ruff check .` clean; Windows pytest green (3923+ preserved, no new skips).
7. POSIX re-verification (`make test` on macOS/Linux) logged as an OUTSTANDING
   residual in the commit message — this Windows session cannot self-certify
   against the CLAUDE.md §4.1 POSIX test authority.

## external_writes_required (verbatim from brief-2)

- `git push origin main` — user-authorized at the Phase 4 boundary (CLAUDE.md
  §4.4: per-event authorization, re-asked every time; NOT performed by the
  pipeline). No new network calls, no corpus writes, no new deps.

## Open questions / flagged residuals (max 5)

1. **`test_proof_chain.py:116`** — the one remaining kuzu `del db` (a
   `graph_corpus` fixture reopening the same path `cite_neighbors` tests use).
   Distinct from the LanceDB `del db` at `test_proof_chain.py:205` (false
   positive — must NOT touch). Out of the literal brief; **flagged as a tracked
   fast-follow** (explore brief §3.1 recommends surfacing at critique, not
   silently absorbing). Folding it in would trip the ≥6-file scope gate.
2. **Regression-test RED/GREEN uncertainty (general Finding 4)** — a bare
   30×-reopen script did NOT reproduce the lock error; only a deliberately-held
   Connection did. The test may be GREEN even on `del db` code in a bare run.
   MITIGATION: this Windows box CAN exercise the Windows-specific bug — during
   Phase 2 verification, revert site 1 to `del db` and confirm the new test's
   behavior under the FULL pytest run before trusting it as a guard. If it
   can't be made to reliably reproduce, document honestly that it asserts the
   close-path works (AC-satisfying) rather than deterministically catching the
   lock error.
3. **Site 3 has zero existing test coverage** of its open/query path
   (`test_restore_drill.py` only tests the dir-absent branch). Consider a small
   test that a corrupt kuzu dir still yields RuntimeError (guards the Option A
   UnboundLocalError risk). Optional — weigh at implement time.
4. **CLAUDE.md §7 stale claim** (general Finding 1): `cite_neighbors` is NO
   LONGER a v1 stub — it's wired to the live MCP tool (`server/tools.py:946`,
   `server/handlers/citations.py`). Raises the real-world consequence of site 1
   (a Windows lock error surfaces to agents as `graph_status: "unavailable"`).
   Doc correction only — out of scope; note for a future doc pass.
5. **Windows is the test authority for THIS bug** but NOT for the suite. Run the
   Windows pytest to prove green here; POSIX remains the user's to re-verify.
