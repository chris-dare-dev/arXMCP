---
milestone_id: "adhoc-20260712-955c958"
researcher_role: "adversarial"
injection_attempts: 0
---

# Research brief (adversarial) — adhoc-20260712-955c958

## Summary verdict

The root cause is real and independently re-verified against the actual installed
`kuzu==0.11.3` Python bindings in this repo's `.venv` (not just trusted from the brief's
prose). The proposed fix shape (explicit `conn.close()` then `db.close()`, guarded by a
`conn = None` sentinel) is correct in spirit but **as literally specified will not make
6 of the 8 target tests pass**, and its un-nested `finally` block introduces a new,
worse failure mode. Both are fixable with small, concrete corrections below. Ranked
findings follow; per-test verdicts are in the table after that.

## Ranked findings

### 1 (highest risk to AC) — THE UNSKIP TRAP: 6 of 8 tests depend on del-db sites the brief never names

I traced every one of the 8 `@kuzu_reopen_unsupported_on_windows` tests line-by-line.
Only **1 of 8** (`test_f3_fetch_failure_tracked_and_retried_on_resume`) depends
*solely* on the 5 named production sites. The other 7 all contain — or depend on a
fixture that contains — their **own** `db = kuzu.Database(...) / finally: del db`
blocks that the brief's "Sites:" list does not mention. Fixing only the 5 production
functions leaves these reopen races in place; the tests will very likely still raise
`RuntimeError: ... Could not set lock on file` after the skip decorator is removed.

Concrete evidence (`tests/test_inspire_ingest.py`):

- **`populated_db` fixture, lines 159–181** (specifically the open/close at
  166–180) is a `db = kuzu.Database(str(db_path)) / try: ... / finally: del db`
  block. It is a **prerequisite fixture for 4 of the 8 target tests**
  (`test_both_sources_edges_coexist`, `test_f1_inspire_remerge_preserves_doi_when_response_drops_field`,
  `test_f2_enrich_accepts_old_style_hep_th_id`,
  `test_f3_fetch_failure_tracked_and_retried`) plus roughly 15 other, currently
  non-skipped tests in the same file. It is **not named anywhere in the brief**.
- `test_simulated_v1_db_migrates_to_v2` (lines 224–261) contains **three** of its
  own del-db blocks (228–242, 244–250, 255–260), interleaved with the two named
  production calls (`apply_schema` at 252, `read_schema_version` at 254). Even
  with both production functions fixed, REOPEN #1 (244) and REOPEN #2 (255) will
  still race against the test's own unfixed 228–242 / 244–250 closes.
- `test_both_sources_edges_coexist` (lines 571–616) has its own del-db blocks at
  579–590 and 602–614, on top of the `populated_db` fixture and the `enrich()`
  production call.
- `test_f1_inspire_remerge_preserves_doi_when_response_drops_field` (lines
  632–682) has own del-db blocks at 648–653 and 664–675 and **never calls any of
  the 5 named production functions at all** — it only calls
  `inspire_ingest._merge_paper_inspire(conn, ...)`, a pure Cypher helper with no
  database lifecycle of its own. Fixing the 5 production sites has **zero**
  effect on whether this test passes; it is 100% test-body/fixture dependent.
- `test_f2_enrich_accepts_old_style_hep_th_id` (lines 720–772): own blocks at
  733–740 and 762–771, plus `populated_db` and one `enrich()` call.
- `test_f6_failure_run_flushes_checkpoint_at_batch_size` (lines 846–889): own
  block at 866–874, plus an explicit `apply_schema` call (860) and one `enrich()`
  call (876–884).
- `test_f8_arxiv_categories_filter_anchor_for_post_f9` (lines 891–966): own
  blocks at 910–922 and 951–966, plus `apply_schema` (906) and `enrich()` (942–948).

In `tests/test_graph_ingest.py`, `test_f3_fetch_failure_tracked_and_retried_on_resume`
(lines 765–816) is the one clean case — it calls `graph_ingest.ingest()` twice with no
direct `kuzu.Database()` calls of its own.

**Implementer action required:** interpret "update the matching del db teardown
blocks in tests/test_graph_ingest.py and tests/test_inspire_ingest.py" as *every*
`del db` occurrence that participates in a call chain reachable from one of the 8
tests — which in practice means essentially all of them, since `populated_db` alone
is reachable from 4 of the 8. The safest, simplest instruction to give the
implementer: convert **every** `kuzu.Database(...)/kuzu.Connection(...)` open/close
pair in `tests/test_graph_ingest.py`, `tests/test_inspire_ingest.py`, and
`tests/_graph_helpers.py` to the explicit-close discipline, not a hand-picked subset.

### 2 — MARKER-REMOVAL BREAKAGE: two files get dangling imports, both must lose lines the brief doesn't mention

Confirmed via `grep -rn "kuzu_reopen_unsupported_on_windows"` across the whole repo:
the marker is defined once (`tests/_graph_helpers.py:38`) and imported in exactly two
places — `tests/test_graph_ingest.py:20` (1 usage, line 765) and
`tests/test_inspire_ingest.py:37` (7 usages: 223, 571, 632, 720, 846, 891, 980). No
other file references it, confirming the brief's scope claim on this point.

But removing it correctly cascades further than "delete the marker definition":

- `tests/_graph_helpers.py` imports `sys` (line 18) and `pytest` (line 23) **solely**
  for the marker (`pytest.mark.skipif(sys.platform == "win32", ...)`, lines 38–39). I
  grepped the whole file for any other `sys.` / `pytest.` usage — none exists (the
  file's only other content is `build_synthetic_kuzu_graph` and
  `build_synthetic_lancedb`, neither of which touches `sys` or `pytest`). Deleting
  just the marker block and leaving `import sys` / `import pytest` in place produces
  two ruff **F401** (unused import) violations.
- `tests/test_graph_ingest.py:20` (`from tests._graph_helpers import
  kuzu_reopen_unsupported_on_windows`) is the file's only import from
  `_graph_helpers`; after removing the single `@kuzu_reopen_unsupported_on_windows`
  at line 765 it becomes unused → another F401.
- `tests/test_inspire_ingest.py:37` is likewise the file's only import from
  `_graph_helpers`; after removing all 7 decorator lines it becomes unused →
  another F401.

`pyproject.toml:213` has `select = ["E", "F", "I", "B", "UP", "SIM"]` — the "F"
(pyflakes) family is active, so all four of these are real, not hypothetical, and
directly threaten the "ruff check clean" acceptance criterion. This is an easy thing
to miss when the diff is "remove 8 decorator lines across 2 files" — the four
dangling-import deletions are a distinct, separate step.

### 3 — FINALLY-CLOSE-RAISES HAZARD: the brief's proposed structure can silently skip db.close()

I read the actual installed `kuzu==0.11.3` Python source
(`.venv/Lib/site-packages/kuzu/connection.py` and `database.py`, not just docs) to
verify this concretely rather than assume it.

`Connection.close()` (`connection.py:75-85`):
```python
def close(self) -> None:
    if self._connection is not None:
        self._connection.close()          # <-- compiled pybind11 call, CAN raise
    self._connection = None
    self.is_closed = True
```
`self._connection.close()` is a call into the compiled extension; if it raises, the two
lines after it never run (`is_closed` stays `False`). `Database.close()`
(`database.py:261-277`) is idempotent on a **second** call (`if self.is_closed: return`)
but sets `self.is_closed = True` **before** calling `self._database.close()` — so if
that call raises, a caller who catches and retries `db.close()` gets a silent no-op on
retry, not a real second attempt.

The brief's proposed shape is a **single, un-nested** `finally`:
```python
finally:
    if conn is not None:
        conn.close()
    db.close()
```
If `conn.close()` raises, `db.close()` is never reached — worse than the original bug,
because the original `del db` was at least unconditionally attempted. This would
convert a 100%-reproducible, well-understood failure into a rare, hard-to-diagnose one
that only fires under I/O pressure (disk-full, or — concretely, on Windows — an
antivirus/indexer transiently holding a handle on the just-written `.wal`/catalog
file during the final checkpoint flush that `close()` performs; `Database.__init__`'s
`auto_checkpoint`/`checkpoint_threshold` params confirm `close()` does real I/O, not a
no-op). This is not hypothetical for this exact codebase: the very `del db` comment
being replaced (`ingest/kuzudb_schema.py:141-144`, see finding 5) already documents a
Windows file-handle-contention concern in the same subsystem.

**Recommended structure.** Both `kuzu.Connection` and `kuzu.Database` already ship
`__enter__`/`__exit__` that call `.close()` (`connection.py:87-96`,
`database.py:106-115`) — this is very likely the library's own blessed idiom for
exactly this situation. Prefer:
```python
with kuzu.Database(str(db_path)) as db, kuzu.Connection(db) as conn:
    ...  # existing try-body, unchanged
```
This is strictly better than a manual `conn = None` sentinel + nested `try/finally`:
Python desugars `with A, B:` as nested `with A: with B:`, so `A.__exit__` (→
`db.close()`) is guaranteed to run even if entering/using `B` (`Connection(db)`)
raises — including the "conn never got assigned" case the brief's sentinel was
written to guard against — with no extra bookkeeping. If the implementer prefers to
keep manual `try/finally` (e.g. to minimize diff churn), the closing block must be
**nested**, not sequential:
```python
finally:
    try:
        if conn is not None:
            conn.close()
    finally:
        db.close()
```

### 4 — COMPLETENESS: the identical bug exists at two more production sites the brief doesn't scope in

`grep -rn "kuzu\.Database(\|kuzu\.Connection("` across the whole repo (not just the
6 named files) turns up two more **production** files with the byte-identical
`del db` pattern:

- **`server/graph_queries.py:372-379`** — this is the `cite_neighbors` **library**,
  the live, currently-wired path CLAUDE.md documents as real and callable today
  (`await server.graph_queries.cite_neighbors(...)`, used by the 2-round proof-chain
  workflow). Its finally block is `finally: del db` (line 378-379), same bug, same
  mechanism. This is materially **more** exposed than the ingest CLIs: ingest scripts
  typically run once per process invocation, but `cite_neighbors` is designed to be
  called repeatedly within one long-running MCP server process. On Windows (this
  project's dev platform, per the environment notes), a second `cite_neighbors` call
  in the same server session — e.g. a second proof-chain round — would very plausibly
  hit the same "Could not set lock on file" `RuntimeError`, but as a **live,
  user-facing tool-call failure**, not a test artifact. There is no test anywhere in
  the repo that calls `cite_neighbors` twice against the same DB path in one process
  to catch this (confirmed no `kuzu_reopen_unsupported_on_windows` reference near
  `test_graph_queries.py` / `test_proof_chain.py`), so this is currently a latent,
  undetected bug on Windows.
- **`ingest/intra_paper_refs.py:348-388`** — a 6th ingest CLI (`finally: del db` at
  387-388) with the same pattern; its own tests
  (`tests/test_intra_paper_refs.py:140-141, 263-264, 289-290, 338-339`) have 4 more
  `del db` blocks, none skip-marked.

The brief is explicit that "Scope is EXACTLY these 6 files," which is a defensible,
surgical choice given the milestone's stated context ("graph-ingest resource
management"). But the brief does not surface this gap the way it explicitly surfaces
the POSIX-verification residual — an operator reading only the ACCEPTANCE section
could reasonably believe the Windows kuzu-lock class of bug is fully closed after this
milestone, when the highest-traffic call site (`graph_queries.py`) is untouched.
Recommend the implementer add an explicit residual note (mirroring the brief's own
POSIX-gap transparency) rather than silently leaving it undocumented, and separately
consider whether `graph_queries.py` is cheap enough to include in this same diff given
it is the identical 6-line pattern.

### 5 — ORDER + PLATFORM DIVERGENCE: confirmed correct and mandatory, not just empirical; one minor addendum

`Database.close()`'s own docstring (`.venv/Lib/site-packages/kuzu/database.py:266-270`)
states: *"If you decide to manually close the database, make sure that all the
QueryResult and Connection objects are closed before calling this method."* This is
direct upstream confirmation — not merely an empirical Windows observation — that
`conn.close()` before `db.close()` is the library's own documented contract. The
brief's ordering choice is correct.

No test in `tests/test_graph_ingest.py`, `tests/test_inspire_ingest.py`, or
`tests/_graph_helpers.py` asserts on GC timing, `__del__`, `gc.collect()`, or leftover
lock files (grepped for all of these — zero matches), so there is no POSIX test that
would behave differently once closes become explicit rather than implicit; explicit
close is a strict superset of what GC eventually did, so no POSIX regression is
expected from the ordering change itself.

One gap the brief's fix doesn't address: the same docstring names `QueryResult`
objects too, and none of the 5 production functions explicitly close the
`QueryResult` they read before the outer `close()` calls (e.g. `read_schema_version`'s
`result` local, `_introspect_columns`'s `result` local). `QueryResult → Connection →
Database` is a one-way reference chain (verified: `query_result.py:42` stores
`self.connection`; `connection.py:40` stores `self.database`; no back-references
exist anywhere in these three files), so there's no cycle, and `QueryResult` already
defines `__del__` → `self.close()` (`query_result.py:58-59`), making this low-risk —
it is very unlikely to be the dominant cause of the observed lock bug (which is
squarely explained by finding 3's `Connection.database` reference alone). Low-priority
polish, not a blocker: wrapping query results in `with conn.execute(...) as result:`
or calling `.close()` explicitly would fully match kuzu's documented discipline.

### 6 — RETURN-PATH / USE-AFTER-CLOSE: clean, no escape at any of the 5 sites

Checked all 5 named production functions for whether `db`/`conn` escape the
try/finally (returned, stored on `self`, captured by a closure, or yielded):

- `apply_schema` (`ingest/kuzudb_schema.py:101-145`) returns `None`.
- `read_schema_version` (`ingest/kuzudb_schema.py:163-183`) returns `int | None`.
- `ingest` (`ingest/graph_ingest.py:517-668`) returns `state: dict[str, Any]`.
- `enrich` (`ingest/inspire_ingest.py:537-719`) returns `state: dict[str, Any]`.
- `main`'s inline block (`ingest/inspire_ingest.py:815-821`) materializes
  `paper_ids = sorted(_existing_paper_ids(conn))` — a plain `list[str]`, fully
  evaluated inside the `try` before `finally` runs — into a local that outlives the
  `with`/`finally`.

None of the five return, store, or yield `db` or `conn` themselves. Closing in
`finally` (or a `with` block) is safe at all 5 sites; no caller anywhere in the repo
depends on receiving a live handle back from any of these functions (confirmed no
other call site treats their return values as a database/connection object).

### 7 — SECONDARY WINDOWS LANDMINES: none found in the 8 tests' own bodies

Checked each of the 8 tests against the Windows landmines catalogued in
CLAUDE.md §8 (`os.getpgid`, POSIX-shell invocation, colons-in-filenames, symlinks).
None of the 8 tests spawn a subprocess, create a symlink, or invoke a shell. The one
string that could plausibly look like a filesystem hazard —
`test_f2_enrich_accepts_old_style_hep_th_id`'s `old_style_id = "hep-th/9711200"`
(contains a `/`) — is used only as a Cypher parameter value / graph node property,
never as a `Path` component or filename, so it does not trip the
colons-in-filenames-class of bug. `tmp_path`-based paths used across all 8 tests are
plain ASCII, no colons. This item is low-risk; listed for completeness per the
role brief, not because it surfaced anything.

## Per-test verdict

| # | Test | File:lines | Depends on the 5 named production sites | Depends on `populated_db` fixture | Depends on test's OWN del-db blocks | Verdict |
|---|---|---|---|---|---|---|
| 1 | `test_f3_fetch_failure_tracked_and_retried_on_resume` | `test_graph_ingest.py:765-816` | yes (`ingest`, `apply_schema` via `ingest`) | no | no | **Green after production fix alone** |
| 2 | `test_simulated_v1_db_migrates_to_v2` | `test_inspire_ingest.py:223-261` | yes (`apply_schema`, `read_schema_version`) | no | yes — 3 own blocks (228-242, 244-250, 255-260) | **Needs test-body fix**, not covered by production fix alone |
| 3 | `test_both_sources_edges_coexist` | `test_inspire_ingest.py:571-616` | yes (`apply_schema` via `enrich`, `enrich`) | yes | yes — 2 own blocks (579-590, 602-614) | **Needs fixture + test-body fix** |
| 4 | `test_f1_inspire_remerge_preserves_doi_when_response_drops_field` | `test_inspire_ingest.py:632-682` | **no** — never calls any of the 5 sites | yes | yes — 2 own blocks (648-653, 664-675) | **Production fix is irrelevant**; 100% fixture/test-body dependent |
| 5 | `test_f2_enrich_accepts_old_style_hep_th_id` | `test_inspire_ingest.py:720-772` | yes (`enrich`) | yes | yes — 2 own blocks (733-740, 762-771) | **Needs all three fixed** |
| 6 | `test_f6_failure_run_flushes_checkpoint_at_batch_size` | `test_inspire_ingest.py:846-889` | yes (`apply_schema` explicit + via `enrich`, `enrich`) | no | yes — 1 own block (866-874) | **Needs production fix + test-body fix** |
| 7 | `test_f8_arxiv_categories_filter_anchor_for_post_f9` | `test_inspire_ingest.py:891-966` | yes (`apply_schema` explicit + via `enrich`, `enrich`) | no | yes — 2 own blocks (910-922, 951-966) | **Needs production fix + test-body fix** |
| 8 | `test_f3_fetch_failure_tracked_and_retried` | `test_inspire_ingest.py:980-1025` | yes (`enrich`, called twice) | yes | no | **Green after production fix + fixture fix** |

Only 1 of 8 is green from the production-site fix alone; 6 of 8 need the
`tests/test_inspire_ingest.py` / `tests/test_graph_ingest.py` bodies (and, for 4 of
those 6, the `populated_db` fixture) also converted — none of which the brief's
"Sites:" list names.

## Acceptance criteria the implementer must meet

1. All 8 previously-skipped tests pass on Windows — this requires fixing the
   `populated_db` fixture (`tests/test_inspire_ingest.py:159-181`) and every
   per-test inline `del db` block (tests 2, 3, 4, 5, 6, 7 per the table above), not
   only the 5 named production sites.
2. `ruff check .` stays clean — requires deleting `import sys` and `import pytest`
   from `tests/_graph_helpers.py` and the now-unused
   `from tests._graph_helpers import kuzu_reopen_unsupported_on_windows` line from
   both `tests/test_graph_ingest.py:20` and `tests/test_inspire_ingest.py:37` (all
   four become dead once the marker + its 8 usages are removed).
3. No `del db` lifecycle remains at the 5 listed production sites
   (`ingest/kuzudb_schema.py:101-145,163-183`; `ingest/graph_ingest.py:517-668`;
   `ingest/inspire_ingest.py:537-719,815-821`) — each converted using a structure
   that does not skip `db.close()` if `conn.close()` raises (nested `try/finally`,
   or preferably `with kuzu.Database(...) as db, kuzu.Connection(db) as conn:`).
4. Close order is connection-before-database — this is not just an empirical
   Windows nuance, it is `kuzu.Database.close()`'s own documented precondition
   (`.venv/Lib/site-packages/kuzu/database.py:266-270`).
5. The `kuzu_reopen_unsupported_on_windows` marker is fully removed: the definition
   block in `_graph_helpers.py`, all 8 decorator usages, and the 3 now-dangling
   import statements identified in finding 2.
6. POSIX must stay green; this session cannot execute POSIX tests (Windows 11 /
   win32). Surface a POSIX `make test` run as the residual final gate, per the
   brief's own framing.
7. The implementer should explicitly acknowledge (not silently drop) that
   `server/graph_queries.py:372-379` and `ingest/intra_paper_refs.py:348-388` carry
   the identical bug outside this milestone's stated scope, given the brief already
   sets the precedent of surfacing residuals rather than hiding them.

## Risks and open questions

1. **Finally-close-raises hazard (finding 3).** The brief's literal proposed
   structure (`if conn is not None: conn.close(); db.close()` inside one
   un-nested `finally`) skips `db.close()` entirely if `conn.close()` raises —
   worse than the original bug. Fix: nested `try/finally`, or the `with A, B:`
   pattern (preferred; both classes already support it).
2. **Completeness gap (finding 4).** `server/graph_queries.py`'s `cite_neighbors`
   is the live-serving path most likely to actually hit a same-process reopen in
   normal operation (multiple tool calls / proof-chain rounds in one server
   session), yet it is entirely outside this milestone's 6-file scope and
   currently untested for this exact race on Windows.
3. **`populated_db` fixture omission (finding 1).** Not named anywhere in the
   brief, yet load-bearing for 4 of the 8 target tests. Conversely, the one helper
   the brief *does* name, `build_synthetic_kuzu_graph`
   (`tests/_graph_helpers.py:98-123`), is used exclusively by
   `tests/test_proof_chain.py` (grep-confirmed zero references from either target
   test file) — fixing it is harmless but does not move the needle on this
   milestone's acceptance criterion at all. This suggests the brief's file list was
   derived from "which test files import kuzu" rather than "which del-db blocks
   actually gate the 8 named tests."
4. **Stale rationale comment.** `ingest/kuzudb_schema.py:141-144` currently reads:
   *"kuzu.Database closes implicitly when the Python object is GC'd; explicitly
   drop the local reference so the close runs deterministically ... matters on
   Windows where the open file handle blocks parent rmtree in pytest tmp_path
   teardown."* This documents the previous author's belief that `del db` was
   sufficient/deterministic on Windows — exactly the premise this milestone's own
   root-cause investigation disproves. Left in place, it will actively mislead the
   next reader. Should be rewritten or removed as part of this diff (no equivalent
   comment exists at the other 4 sites).
5. **QueryResult objects left unclosed (finding 5, minor).** None of the 5
   production functions explicitly close the `QueryResult` objects they read before
   the outer `conn.close()`/`db.close()` run, contrary to kuzu's own documented
   "make sure that all the QueryResult and Connection objects are closed" guidance.
   Verified low-risk (no reference cycle; `QueryResult.__del__` already calls
   `close()`), but worth a follow-up pass for full discipline.
