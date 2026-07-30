---
name: research-brief-1
role: explore
milestone: adhoc-20260712-698fead
status: complete
---

# Research brief (explore) — adhoc-20260712-698fead

Codebase context map for applying the kuzu 0.11.3 nested-close discipline
(landed for 5 production sites in milestone `adhoc-20260712-955c958`, commit
`6c5ff0d`) to the 3 residual sites. This milestone is the literal follow-up
task `task_959b2bf4` named in `adhoc-20260712-955c958`'s rectify summary and
its synthesis.md "Open questions #1".

## 0. Sites table (summary)

| # | Site | `db` var | `conn` var | conn pre-bound before `try`? | `async def`? | current teardown |
|---|---|---|---|---|---|---|
| 1 | `server/graph_queries.py:372-379` (`cite_neighbors`) | `db` | `conn` | **NO** — opened at L374, inside the `try` | **YES** (L303) | `finally: del db` (L378-379) |
| 2 | `ingest/intra_paper_refs.py:341-388` (`ingest`) | `db` | `conn` | **NO** — opened at L350, inside the `try` | NO (sync) | `finally: del db` (L387-388) |
| 3 | `ops/restore_drill_check.py:135-156` (`smoke_check_kuzu`) | `db` | `conn` | **N/A — no `try/finally` exists at all.** `db`/`conn` are both opened inside a `try/except Exception` whose job is exception-translation (open failure → `RuntimeError("... is unreadable")`), not resource cleanup. | NO (sync) | **NONE** — no `del db`, no `.close()`, no `finally`. Both fall out of scope at function return (or immediately on exception). |

All 3 sites use the identical variable names `db` / `conn` (matches the rest
of the codebase family). `import kuzu` is **module-level** in sites 1 and 2
(`server/graph_queries.py:50`, `ingest/intra_paper_refs.py:67`); site 3 does
a **lazy, guarded** `import kuzu` *inside* the function
(`ops/restore_drill_check.py:136`, wrapped in its own
`try: import kuzu / except ImportError: return None`). No `conn = None` /
`db = None` pre-init exists anywhere today — this repo has zero occurrences
of that guard prior to this milestone.

---

## 1. The 3 target sites — exact current code

### Site 1 — `server/graph_queries.py::cite_neighbors` (async, live MCP path)

Full signature (L303-310), confirming `async def` and every parameter:

```python
303	async def cite_neighbors(
304	    chunk_id: str,
305	    depth: int = 2,
306	    direction: Direction = "cites",
307	    max_results: int = DEFAULT_MAX_RESULTS,
308	    kuzudb_path: str | Path = DEFAULT_KUZUDB_PATH,
309	    lancedb_path: str | Path | None = None,
310	) -> list[CitationNeighbor]:
```

The exact open/try/finally block (L372-379) — this is the ENTIRE scope of
the fix; everything before L372 is validation (`max_results`, `direction`,
`paper_id_from_chunk_id`), and everything after L379 (dedup, sort, cap,
LanceDB chunk-id lookup, `CitationNeighbor` construction) operates purely on
the already-materialized `rows` list — no live kuzu handle is referenced
after this block:

```python
372	    db = kuzu.Database(str(Path(kuzudb_path)))
373	    try:
374	        conn = kuzu.Connection(db)
375	        rows = await asyncio.to_thread(
376	            _execute_traversal, conn, paper_id, direction, depth
377	        )
378	    finally:
379	        del db
```

Notes:
- `db = kuzu.Database(...)` (L372) is unconditional / outside the `try` —
  same shape as the 5 already-fixed production sites, so `conn = None` slots
  in cleanly between L372 and L373 with zero other restructuring.
- The only statement inside the `try` besides `conn = kuzu.Connection(db)`
  is the `await asyncio.to_thread(_execute_traversal, ...)` call — the
  actual Cypher query, wrapped in a thread because it can take up to the
  documented 500ms perf budget (`DEFAULT_MAX_RESULTS`/perf-gate docstring,
  L313-319).
- `conn.close()` / `db.close()` are synchronous C++ calls (no `await`) —
  matches every already-fixed production site, none of which are async. The
  existing `finally: del db` today is likewise a plain, non-awaited
  statement inside this `async def`, so adding two more plain sync calls in
  its place changes nothing about the function's async contract.
- This is the **highest-consequence** site: `server/graph_queries.py` is
  imported by the long-running MCP server process (not a per-invocation
  CLI), so the OS never gets a natural process-exit opportunity to release
  the lock between calls — a second `cite_neighbors` call in one server
  session is what reproduces "Could not set lock on file" on Windows in
  production, not just in a test.

### Site 2 — `ingest/intra_paper_refs.py::ingest` (sync, 6th ingest CLI)

Full signature (L318-326):

```python
318	def ingest(
319	    paper_ids: list[str],
320	    db_path: Path,
321	    parsed_dir: Path,
322	    lancedb_path: Path,
323	    checkpoint_path: Path,
324	    *,
325	    batch_size: int = CHECKPOINT_BATCH_SIZE,
326	) -> dict[str, Any]:
```

The exact open/try-body/finally block (L341-388) — structurally identical in
shape to `ingest/graph_ingest.py::ingest`'s ALREADY-FIXED pattern (same
"apply_schema, then db=kuzu.Database(...), then try: conn=kuzu.Connection(db)
... whole function body ... return state / finally: del db" shape):

```python
341	    apply_schema(db_path)
342	    # F6 fix: open the LanceDB chunks table ONCE for the whole pass
343	    # rather than per-paper inside ``_resolved_labels_for_paper``.
344	    # Re-opening per paper triggered a corpus-version marker check
345	    # and table-handle materialization on every iteration — fine at
346	    # 50 papers, 10×–100× wall-clock overhead at production scale.
347	    chunks_table = _open_chunks_table_or_none(lancedb_path)
348	    db = kuzu.Database(str(db_path))
349	    try:
350	        conn = kuzu.Connection(db)
351	        state = _load_checkpoint(checkpoint_path)
352	        processed: set[str] = set(state.get("processed", []))
353	        edges_added: set[str] = set(state.get("edges_added", []))
354	        parse_failures: dict[str, str] = {
355	            entry["paper_id"]: entry.get("error", "")
356	            for entry in state.get("parse_failures", [])
357	            if isinstance(entry, dict) and "paper_id" in entry
358	        }
359	
360	        new_in_pass = 0
361	        for paper_id in paper_ids:
362	            if paper_id in processed:
363	                continue
364	            try:
365	                result = process_paper(paper_id, parsed_dir, chunks_table, conn)
366	            except RuntimeError as exc:
367	                logger.warning(
368	                    "intra-paper scan failed for %s: %s", paper_id, exc
369	                )
370	                parse_failures[paper_id] = str(exc)
371	                # Still count toward batch for crash resilience.
372	                new_in_pass += 1
373	                if new_in_pass % batch_size == 0:
374	                    _flush_state(state, processed, edges_added, parse_failures, checkpoint_path)
375	                continue
376	            # Success path — drop any prior failure entry.
377	            parse_failures.pop(paper_id, None)
378	            processed.add(paper_id)
379	            if result.edges_added:
380	                edges_added.add(paper_id)
381	            new_in_pass += 1
382	            if new_in_pass % batch_size == 0:
383	                _flush_state(state, processed, edges_added, parse_failures, checkpoint_path)
384	
385	        _flush_state(state, processed, edges_added, parse_failures, checkpoint_path)
386	        return state
387	    finally:
388	        del db
```

Notes:
- `db = kuzu.Database(str(db_path))` (L348) is unconditional / outside the
  `try` — `conn = None` slots in between L348 and L349, exactly mirroring
  `ingest/graph_ingest.py::ingest`'s fix (compare: that function's fixed
  shape is `db = kuzu.Database(str(db_path)); conn = None; try: conn =
  kuzu.Connection(db); ...`).
- The inner `try/except RuntimeError` (L364-375) is an existing
  per-paper-failure-recovery block, unrelated to the outer lock-lifecycle
  `try/finally` — it stays untouched; only the outer `finally: del db`
  (L387-388) changes.
- There is an existing internal `except RuntimeError` catch (L366) but it
  does not re-raise — it's fully orthogonal to the kuzu close-discipline
  fix.

### Site 3 — `ops/restore_drill_check.py::smoke_check_kuzu` (sync, no lifecycle mgmt at all)

Confirmed: this function has **no `finally` block whatsoever**, not even a
`del db`. Full function (L118-156):

```python
118	def smoke_check_kuzu(restore_path: Path) -> int | None:
119	    """Open the restored Kùzu graph and return paper count.
120	
121	    Returns ``None`` if the Kùzu directory is absent (acceptable
122	    — some restore paths may exclude the citation graph). Raises
123	    ``RuntimeError`` if the directory exists but is unreadable.
124	
125	    Closes adversary F1 (Kùzu half): finds the Kùzu directory
126	    via rglob rather than hardcoding the path prefix.
127	    """
128	    kuzu_path = _locate_kuzu_root(restore_path)
129	    if kuzu_path is None:
130	        logger.info(
131	            "restore_drill: Kùzu directory absent under %s — skipping",
132	            restore_path,
133	        )
134	        return None
135	    try:
136	        import kuzu  # noqa: PLC0415
137	    except ImportError:
138	        logger.warning("restore_drill: kuzu module not importable")
139	        return None
140	    try:
141	        db = kuzu.Database(str(kuzu_path))
142	        conn = kuzu.Connection(db)
143	        # Restored DB may be empty; we only require it to open.
144	        result = conn.execute("MATCH (p:Paper) RETURN count(p) AS c")
145	        paper_count = 0
146	        while result.has_next():
147	            row = result.get_next()
148	            paper_count = int(row[0])
149	    except Exception as exc:  # noqa: BLE001 — integrity probe
150	        raise RuntimeError(
151	            f"restored Kùzu DB at {kuzu_path} is unreadable: {exc}"
152	        ) from exc
153	    logger.info(
154	        "restore_drill: Kùzu ok (%d papers)", paper_count
155	    )
156	    return paper_count
```

**Critical structural difference from sites 1 and 2 — flag prominently for
the implementer:**

Unlike sites 1/2, `db = kuzu.Database(...)` (L141) is currently **INSIDE**
the `try/except Exception` block (L140-152), and that `except` clause
re-wraps ANY exception raised while opening/querying — including a
`kuzu.Database()` construction failure itself — into
`RuntimeError(f"restored Kùzu DB at {kuzu_path} is unreadable: {exc}")`.
`run_check()` (L282-296) catches exactly `except RuntimeError as exc:` around
all three smoke checks and turns it into a clean `return 1` (drill-failed)
exit code rather than an unhandled traceback.

This means there are two structurally different ways to add lifecycle
management here, with a real behavioral trade-off — **this is a decision
point for the implementer, not something this brief resolves**:

- **Option A (preserve current exception semantics):** keep
  `db = kuzu.Database(...)` INSIDE the `try/except Exception`, pre-init BOTH
  `db = None` and `conn = None` before that try, and add a
  `finally:` after the `except` that nests the close with `is not None`
  guards on both:
  ```python
  db = None
  conn = None
  try:
      db = kuzu.Database(str(kuzu_path))
      conn = kuzu.Connection(db)
      ...
  except Exception as exc:
      raise RuntimeError(...) from exc
  finally:
      try:
          if conn is not None:
              conn.close()
      finally:
          if db is not None:
              db.close()
  ```
  A `finally` after an `except` that re-raises still executes before the
  exception propagates out of the compound statement (standard Python
  semantics) — this is safe. This is the ONLY one of the 3 sites where `db`
  itself needs an `is not None` guard, because `kuzu.Database()` construction
  is inside the guarded region, unlike sites 1/2 where it's unconditional.
- **Option B (match sites 1/2's canonical shape exactly):** move
  `db = kuzu.Database(...)` OUTSIDE/BEFORE the try (matching the reference
  fix byte-for-byte), which means a `kuzu.Database()` open failure would now
  raise the RAW kuzu exception instead of being wrapped in
  `RuntimeError("... is unreadable")` — `run_check`'s `except RuntimeError`
  would NOT catch it, and `_cli` would crash with an unhandled traceback
  instead of a clean exit-code-1 "drill failed" message. This is a
  **behavior change** the milestone brief does not ask for.

There is currently **zero test coverage** of the "kuzu dir present" branches
of `smoke_check_kuzu` (see §4 below) — no existing test would catch this
regression either way, which makes it easy to introduce silently.

---

## 2. The reference fix (adhoc-20260712-955c958, commit `6c5ff0d`)

Ground truth pulled via `git show 6c5ff0d -- ingest/graph_ingest.py
ingest/inspire_ingest.py ingest/kuzudb_schema.py` (not paraphrased from
notes). Two textually distinct comment variants landed; the new sites should
use whichever length fits, but the **code shape must match exactly**.

**Short variant** (used at `graph_ingest.py::ingest`, `inspire_ingest.py::enrich`,
`inspire_ingest.py::main`'s inline block, `read_schema_version`):

```python
db = kuzu.Database(str(db_path))
conn = None
try:
    conn = kuzu.Connection(db)
    ... existing body unchanged ...
finally:
    # Explicit close releases kuzu's file lock deterministically (conn
    # before db, nested so db.close() runs even if conn.close() raises).
    try:
        if conn is not None:
            conn.close()
    finally:
        db.close()
```

**Long variant** (used once, at `kuzudb_schema.py::apply_schema`, replacing a
now-inaccurate comment that used to claim `del db` closes deterministically):

```python
finally:
    # kuzu 0.11.3 takes a mandatory file lock that merely dropping the
    # Python reference does NOT release: a live `kuzu.Connection` holds a
    # strong reference to its `Database`, so the native handle survives
    # until GC — and on Windows GC is not prompt enough, which blocks a
    # same-process reopen of the DB path (and the pytest tmp_path rmtree).
    # Close explicitly, connection before database (kuzu's documented
    # order), nested so `db.close()` still runs even if `conn.close()`
    # raises.
    try:
        if conn is not None:
            conn.close()
    finally:
        db.close()
```

The already-fixed test helper `tests/_graph_helpers.py::build_synthetic_kuzu_graph`
(§4 below) uses the short variant verbatim.

**Decision rationale, quoted from
`.claude/notes/milestones/adhoc-20260712-955c958/research/synthesis.md`
Decision 1** (this is binding prior art — the CURRENT ad-hoc brief's own
wording, "nested close so db.close() always runs even if conn.close()
raises," already matches this and must NOT regress to the flat form):

> The brief's literal `finally: if conn is not None: conn.close(); db.close()`
> is UNSAFE — if `conn.close()` raises, `db.close()` is skipped and the lock
> leaks (worse than `del db`). ... `conn = None` is initialized BEFORE
> `try:` (a `kuzu.Connection(db)` construction failure otherwise →
> `UnboundLocalError` masking the real error). `db` never needs a
> None-guard (always created before `try:`). `with kuzu.Database(...) as
> db, kuzu.Connection(db) as conn:` is equivalent+idiomatic (kuzu 0.11.3
> supports both context managers) but REJECTED here: it forces re-indenting
> 90–140-line function bodies at 5 sites → large churn for no behavioral
> gain.

The "`db` never needs a None-guard" line is true for sites 1 and 2 (db-open
is unconditional/outside the try) but is **NOT** true for site 3 under
Option A (§1) — flagged above.

---

## 3. Completeness check — every `kuzu.Database(` / `del db` / `del conn` site

`del conn` has **zero** matches anywhere in actual code (repo-wide) — only
prose mentions inside `.claude/notes/milestones/*/research/*.md` files that
describe the search pattern itself. This confirms the bug family is
exclusively about `db`; nothing ever attempted a `conn`-side release before
this fix family started.

**Every `kuzu.Database(` call site (44 total), with disposition:**

| # | File:line | Owning function | Status |
|---|---|---|---|
| 1 | `ops/restore_drill_check.py:141` | `smoke_check_kuzu` | **TARGET (site 3)** — no lifecycle mgmt at all |
| 2 | `ingest/kuzudb_schema.py:115` | `apply_schema` | FIXED (955c958) |
| 3 | `ingest/kuzudb_schema.py:181` | `read_schema_version` | FIXED (955c958) |
| 4 | `ingest/graph_ingest.py:556` | `ingest` | FIXED (955c958) |
| 5 | `ingest/intra_paper_refs.py:348` | `ingest` | **TARGET (site 2)** — `del db` at L388 |
| 6 | `ingest/inspire_ingest.py:579` | `enrich` | FIXED (955c958) |
| 7 | `ingest/inspire_ingest.py:823` | `main` (inline) | FIXED (955c958) |
| 8 | `server/graph_queries.py:372` | `cite_neighbors` | **TARGET (site 1)** — `del db` at L379 |
| 9 | `tests/_graph_helpers.py:77` | `build_synthetic_kuzu_graph` | FIXED (955c958) — `conn = None` at L78, nested finally L100-107 |
| 10 | `tests/test_proof_chain.py:93` | `graph_corpus` fixture (fixture-time edge-count assertion) | **NOT FIXED**, `del db` at L116 — **NOT in this milestone's 3-site list**; see §3.1 |
| 11 | `tests/test_intra_paper_refs.py:132` | `kuzu_db` fixture | NOT FIXED, `del db` at L141 — **in scope** (brief names this file) |
| 12 | `tests/test_intra_paper_refs.py:252` | `test_emits_self_edge_for_paper_with_resolved_refs` | NOT FIXED, `del db` at L264 — **in scope** |
| 13 | `tests/test_intra_paper_refs.py:282` | `test_paper_without_refs_emits_no_edge` | NOT FIXED, `del db` at L290 — **in scope** |
| 14 | `tests/test_intra_paper_refs.py:331` | `test_idempotent_re_run` | NOT FIXED, `del db` at L339 — **in scope** |
| 15-36 | `tests/test_inspire_ingest.py` (22 sites: L166,199,226,244,266,283,430,482,535,581,636,665,716,738,777,818,853,920,969,1018,1065,1274) | various | ALL FIXED (955c958) — 0 `del db` remain (grep-confirmed) |
| 37 | `tests/test_graph_queries.py:67` | `kuzu_db` fixture | NOT FIXED, `del db` at L93 — **NOT in this milestone's 3-site list, but is the fixture the new regression test will almost certainly reuse**; see §3.1 |
| 38-44 | `tests/test_graph_ingest.py` (7 sites: L146,177,247,279,326,366,423) | various | ALL FIXED (955c958) — 0 `del db` remain (grep-confirmed) |

**Total live `del db` sites remaining (kuzu-only) = 8**: the 3 named
production targets' 2 real hits (site 3 has none to begin with) +
`test_proof_chain.py:116` + the 4 in `test_intra_paper_refs.py` +
`test_graph_queries.py:93`. This matches `.claude/notes/milestones/adhoc-20260712-955c958/research/synthesis.md`
"Open questions / residuals #1 and #3" exactly — that document independently
flagged both the 3 production sites AND named all 3 of
`test_graph_queries.py`, `test_intra_paper_refs.py`, `test_proof_chain.py` as
sharing the reopen pattern with "unverified whether they currently pass/flake
on Windows."

**False positive to avoid:** `tests/test_proof_chain.py:205` also contains a
`del db` — but that `db` is a **LanceDB** connection
(`db = lancedb.connect(str(graph_corpus["lancedb_path"]))`, L186), not a
`kuzu.Database`. It is explicitly commented as an "F4 fix ... avoids
GC-ordering flakes on Windows CI" for LanceDB/Arrow handles and is unrelated
to this bug family. Do not touch it.

### 3.1 Out-of-scope-but-adjacent sites — flag for critique phase

The brief's literal text names exactly 3 production sites + `tests/test_graph_queries.py`
(new regression test) + `tests/test_intra_paper_refs.py` (teardown
conversion). It does **not** name:

- **`tests/test_graph_queries.py:67-94`'s own `kuzu_db` fixture** (`del db`
  at L93). This fixture is what every existing `cite_neighbors` test in that
  file uses to build its 5-paper graph (see §4.2), and is the fixture the
  new double-reopen regression test will most naturally reuse. **If this
  fixture's own `del db` is left unconverted, the new regression test is
  less deterministic**: the fixture's leftover lock (from ITS OWN
  unreleased `db`) could interleave with the lock state `cite_neighbors`
  itself is managing, making a "no lock error" assertion prove less than
  intended (a pass could mean "GC happened to run in time for the fixture's
  db," not "cite_neighbors' own fix works"). Recommend the implementer
  convert this fixture's teardown too, even though the brief's literal
  wording doesn't name it — it's necessary for the regression test to
  cleanly isolate what it's testing.
- **`tests/test_proof_chain.py:93-116`'s `graph_corpus` fixture** — opens its
  own raw `kuzu.Database` (via `build_synthetic_kuzu_graph`, ALREADY fixed,
  followed immediately by a second, NOT-fixed raw open at L93 for a
  fixture-time edge-count assertion, `finally: del db` at L116) against the
  SAME `kuzu_path` that the test bodies subsequently pass to
  `cite_neighbors(kuzudb_path=graph_corpus["kuzu_path"], ...)`. This is the
  same close-then-reopen shape as the bug under test, in a file adjacent to
  (but not named by) this milestone. These tests are NOT currently
  Windows-skip-marked (i.e., they pass today), which is evidence the failure
  is **timing-dependent/racy** rather than 100%-reproducible — plausibly
  because enough intervening allocation (LanceDB/pyarrow table construction,
  L118-156) happens between the buggy close and the next open for
  Windows/CPython to release the lock "in time," rather than never. This
  reinforces that **the new regression test should reopen with minimal
  intervening work** (a tight back-to-back double call) to reliably
  reproduce the pre-fix failure — see §5.
- These two are genuinely out-of-scope per the brief's literal wording but
  are the direct textual referents of `adhoc-20260712-955c958`'s own
  synthesis.md residual #3 ("`del db` in 3 out-of-scope test files ...
  unverified whether they currently pass/flake on Windows"). Recommend
  surfacing this explicitly at critique time rather than silently leaving it
  for a third follow-up milestone.

---

## 4. Test infrastructure map

### 4.1 `tests/_graph_helpers.py` (shared builder, ALREADY fixed)

```python
def build_synthetic_kuzu_graph(
    db_path: Path,
    n_papers: int,
    edges_per_paper: int = 3,
    source: str = "openAlex",
    paper_id_prefix: str = "2605.",
    paper_id_start: int = 90000,
) -> list[str]:
```
(L26-33). Docstring: builds `n_papers` synthetic `papers` nodes with
`edges_per_paper` outgoing `cites` edges each (mod-wrapped to preceding
indices), returns the list of paper_ids in order. Already uses the exact
short nested-close variant from §2 (L100-107), with `conn = None` at L78.
Per its own module docstring, `test_graph_queries.py` and
`test_intra_paper_refs.py` **intentionally do NOT use this helper** — "no
refactor in this milestone (keeps the diff focused; the existing tests are
working as-is)" — they keep their own inline fixture-building code, which is
exactly the `del db`-using `kuzu_db` fixtures documented below.

### 4.2 `tests/test_graph_queries.py` — the file for the new regression test

Imports (L21-36):
```python
from server.graph_queries import (
    DEFAULT_MAX_RESULTS,
    _build_query,
    _row_passes_direction_filter,
    cite_neighbors,
)
```
`_run` helper (L97-99):
```python
def _run(coro):
    """Synchronously execute an ``async def`` test body."""
    return asyncio.run(coro)
```

The `kuzu_db` fixture (L62-94) — builds a 5-paper synthetic graph
(`P_A..P_E`) with edges `A→B(openAlex)`, `A→C(inspire)`, `B→D(openAlex)`,
`C→D(inspire)`, `E→A(openAlex)`, `A→A(intra-paper, self-loop)`, and returns
a `Path` (NOT a live handle):

```python
62	@pytest.fixture
63	def kuzu_db(tmp_path: Path) -> Path:
64	    """Materialize the 5-paper synthetic graph in ``tmp_path``."""
65	    db_path = tmp_path / "kuzu_test"
66	    kuzudb_schema.apply_schema(db_path)
67	    db = kuzu.Database(str(db_path))
68	    try:
69	        conn = kuzu.Connection(db)
70	        for pid in ALL_PAPERS:
71	            conn.execute(
72	                "MERGE (p:papers {paper_id: $id}) "
73	                "ON CREATE SET p.title = $title",
74	                {"id": pid, "title": f"Title-{pid}"},
75	            )
76	        edges = [
77	            (P_A, P_B, "openAlex"),
78	            (P_A, P_C, "inspire"),
79	            (P_B, P_D, "openAlex"),
80	            (P_C, P_D, "inspire"),
81	            (P_E, P_A, "openAlex"),
82	            (P_A, P_A, "intra-paper"),
83	        ]
84	        for src, dst, source in edges:
85	            graph_ingest._merge_cite(
86	                conn,
87	                src_paper_id=src,
88	                dst_paper_id=dst,
89	                source=source,
90	                confidence=1.0,
91	            )
92	    finally:
93	        del db
94	    return db_path
```

One existing `cite_neighbors` test showing the exact call convention
(L163-178) — note the args are always keyword (`depth=`, `direction=`,
`kuzudb_path=`, `lancedb_path=`) and the fixture is passed straight through
as `kuzudb_path`:

```python
class TestCiteNeighborsCites:
    def test_depth_1_returns_direct_outgoing(self, kuzu_db: Path):
        result = _run(
            cite_neighbors(
                CHUNK_A,
                depth=1,
                direction="cites",
                kuzudb_path=kuzu_db,
                lancedb_path=None,
            )
        )
        ids = sorted(n.paper_id for n in result)
        assert ids == sorted([P_B, P_C])
        ...
```

`CHUNK_A = f"arxiv:{P_A}:0123456789abcdef"` (L59); `P_A = "2401.50001"`
(L51). No existing test in this file calls `cite_neighbors` more than once
against the same `kuzu_db` path — the new double-reopen regression test is
genuinely new coverage, not a duplicate of existing assertions.

### 4.3 `tests/test_intra_paper_refs.py` — every `del db` teardown

File-level imports include `import kuzu` (L15) and
`from ingest.intra_paper_refs import (..., ingest)` (L20-24). All 4 sites
below build/query kuzu directly (not via `tests/_graph_helpers.py`).

**(a) `kuzu_db` fixture (L127-142)** — mirrors `test_graph_queries.py`'s
fixture almost exactly (same name, same shape, different graph content —
just 3 bare paper nodes, no edges):

```python
127	@pytest.fixture
128	def kuzu_db(tmp_path: Path) -> Path:
129	    """Materialize an empty Kùzu DB with v2 schema."""
130	    db_path = tmp_path / "kuzu_test"
131	    kuzudb_schema.apply_schema(db_path)
132	    db = kuzu.Database(str(db_path))
133	    try:
134	        conn = kuzu.Connection(db)
135	        for pid in (P_HAS_REFS, P_NO_REFS, P_MISSING_HTML):
136	            conn.execute(
137	                "MERGE (p:papers {paper_id: $id}) ON CREATE SET p.title = $t",
138	                {"id": pid, "t": f"Title-{pid}"},
139	            )
140	    finally:
141	        del db
142	    return db_path
```

**(b) `TestIngest.test_emits_self_edge_for_paper_with_resolved_refs` (L238-266)**
— calls the (to-be-fixed) `ingest()` once, then reopens the SAME path
directly to assert on the graph:

```python
245	        ingest(
246	            paper_ids=[P_HAS_REFS, P_NO_REFS],
247	            db_path=kuzu_db,
248	            parsed_dir=parsed_dir,
249	            lancedb_path=lancedb_with_labels,
250	            checkpoint_path=checkpoint_path,
251	        )
252	        db = kuzu.Database(str(kuzu_db))
253	        try:
254	            conn = kuzu.Connection(db)
255	            r = conn.execute(
256	                "MATCH (a:papers)-[r:cites {source: 'intra-paper'}]->(b:papers) "
257	                "RETURN a.paper_id, b.paper_id, r.confidence "
258	                "ORDER BY a.paper_id"
259	            )
260	            edges = []
261	            while r.has_next():
262	                edges.append(tuple(r.get_next()))
263	        finally:
264	            del db
265	        # Exactly one self-edge: P_HAS_REFS -> P_HAS_REFS.
266	        assert edges == [(P_HAS_REFS, P_HAS_REFS, pytest.approx(1.0))]
```

**(c) `TestIngest.test_paper_without_refs_emits_no_edge` (L268-291)** — same
shape, simpler query:

```python
275	        ingest(
276	            paper_ids=[P_NO_REFS],
277	            db_path=kuzu_db,
278	            parsed_dir=parsed_dir,
279	            lancedb_path=lancedb_with_labels,
280	            checkpoint_path=checkpoint_path,
281	        )
282	        db = kuzu.Database(str(kuzu_db))
283	        try:
284	            conn = kuzu.Connection(db)
285	            count = conn.execute(
286	                "MATCH (a:papers)-[r:cites {source: 'intra-paper'}]->(b:papers) "
287	                "RETURN COUNT(*)"
288	            ).get_next()[0]
289	        finally:
290	            del db
291	        assert count == 0
```

**(d) `TestIngest.test_idempotent_re_run` (L310-341)** — calls `ingest()`
**TWICE** back-to-back against the same `kuzu_db` path (L317-323, L324-330),
then reopens directly a third time to assert idempotency:

```python
317	        ingest(
318	            paper_ids=[P_HAS_REFS, P_NO_REFS],
319	            db_path=kuzu_db,
320	            parsed_dir=parsed_dir,
321	            lancedb_path=lancedb_with_labels,
322	            checkpoint_path=checkpoint_path,
323	        )
324	        ingest(
325	            paper_ids=[P_HAS_REFS, P_NO_REFS],
326	            db_path=kuzu_db,
327	            parsed_dir=parsed_dir,
328	            lancedb_path=lancedb_with_labels,
329	            checkpoint_path=checkpoint_path,
330	        )
331	        db = kuzu.Database(str(kuzu_db))
332	        try:
333	            conn = kuzu.Connection(db)
334	            count = conn.execute(
335	                "MATCH (a:papers)-[r:cites {source: 'intra-paper'}]->(b:papers) "
336	                "RETURN COUNT(*)"
337	            ).get_next()[0]
338	        finally:
339	            del db
340	        # Exactly one edge survives — MERGE upsert is idempotent.
341	        assert count == 1
```

Notable: this test **already** exercises a close-reopen-close-reopen chain
against `ingest()` (which still uses `del db` pre-fix) and currently passes
on Windows (not skip-marked) — further evidence the bug is timing-dependent
rather than deterministic; once `ingest()` itself is fixed (site 2), this
test becomes a good implicit regression guard for site 2 in addition to its
own teardown needing conversion.

All 4 sites use the `db`/`conn` names identically to the production sites;
conn is opened inside the `try` in every case (never pre-bound) — same
`conn = None` insertion point applies uniformly.

---

## 5. `cite_neighbors` call signature (for the new regression test)

```python
async def cite_neighbors(
    chunk_id: str,
    depth: int = 2,
    direction: Direction = "cites",
    max_results: int = DEFAULT_MAX_RESULTS,
    kuzudb_path: str | Path = DEFAULT_KUZUDB_PATH,
    lancedb_path: str | Path | None = None,
) -> list[CitationNeighbor]:
```
(`server/graph_queries.py:303-310`). `Direction = Literal["cites",
"cited_by", "depends_on"]` (L85). `chunk_id` must parse via
`ingest.identifiers.paper_id_from_chunk_id` (raises `ValueError` on
malformed input — e.g. the existing fixture's `CHUNK_A =
"arxiv:2401.50001:0123456789abcdef"` in `test_graph_queries.py:59`). The
`kuzudb_path` parameter is what the regression test needs to hold constant
across both calls — it accepts `str | Path` and the existing `kuzu_db`
fixture already returns a bare `Path` (matches the parameter type directly,
no conversion needed).

Given §4.2's convention, the new regression test's call shape is:

```python
result_1 = _run(cite_neighbors(CHUNK_A, depth=1, direction="cites",
                                kuzudb_path=kuzu_db, lancedb_path=None))
result_2 = _run(cite_neighbors(CHUNK_A, depth=1, direction="cites",
                                kuzudb_path=kuzu_db, lancedb_path=None))
```
called back-to-back (minimal intervening work, per §3.1's timing-sensitivity
note) with a `try/except RuntimeError` (or `pytest.raises`-free direct call,
asserting no exception at all) around the second call, checking the
exception message does NOT contain `"Could not set lock on file"` if one is
raised — or more simply, asserting the second call completes and returns a
non-empty/equal-shape result rather than raising.

---

## 6. Risks / open questions (max 5)

1. **`ops/restore_drill_check.py` Option A vs B (§1, site 3)** — the
   `except Exception` currently wraps `kuzu.Database()` construction itself,
   translating any open failure into a specific `RuntimeError("... is
   unreadable")` message that `run_check()`'s `except RuntimeError` depends
   on for a clean exit-code-1. Moving `db = kuzu.Database(...)` outside the
   try (to match sites 1/2 byte-for-byte) silently changes this exception
   type for open failures. No existing test exercises this branch (§4/`tests/test_restore_drill.py::TestSmokeCheckKuzu`
   has exactly one test, `test_returns_none_when_kuzu_dir_absent`, which
   never reaches L135+) — a regression here would go undetected without new
   test coverage.
2. **New regression test's fixture dependency (§3.1)** — if the implementer
   reuses `test_graph_queries.py`'s `kuzu_db` fixture as-is (its own `del
   db` at L93 unconverted), the new "no lock error" assertion is testing a
   noisier signal than intended. Recommend converting that fixture's
   teardown too, even though the brief's literal 3-site list doesn't name it.
3. **`test_proof_chain.py`'s adjacent `del db` (L116, §3.1)** — same bug
   shape, reachable via `cite_neighbors`-exercising tests, explicitly listed
   as an unresolved residual in `adhoc-20260712-955c958`'s own synthesis.md.
   Out of this milestone's literal scope but worth flagging for critique so
   it isn't silently forgotten a second time.
4. **Timing-dependence, not 100% reproducibility** — `test_intra_paper_refs.py::test_idempotent_re_run`
   already does a same-path close-reopen via the pre-fix `ingest()` today
   and passes on Windows. This suggests the lock-contention window is
   racy/timing-dependent (enough intervening Python-level work between close
   and reopen apparently self-heals it sometimes), not a guaranteed
   reproduction. The new regression test should minimize intervening work
   between the two `cite_neighbors` calls to reliably exercise the failure
   mode pre-fix (and thus be a meaningful red/green proof of the fix).
5. **Nested-close structure is non-negotiable** — `adhoc-20260712-955c958`'s
   synthesis.md Decision 1 explicitly rejected the flat
   `if conn is not None: conn.close(); db.close()` shape as UNSAFE (skips
   `db.close()` if `conn.close()` raises, worse than the status quo). The
   current ad-hoc brief's wording already says "nested," consistent with
   this — flagging only so the implementer doesn't simplify it during
   editing.

---

## 7. Acceptance criteria the implementer must meet

1. Sites 1 and 2 converted to the exact nested-close shape from §2 (short
   variant), with `conn = None` inserted immediately after the unconditional
   `db = kuzu.Database(...)` line and before `try:`.
2. Site 3 gets an explicit, deliberate decision (Option A or B from §1)
   with rationale recorded — not a silent default — since it changes
   exception semantics unlike sites 1/2.
3. `grep -rn "del db" server/graph_queries.py ingest/intra_paper_refs.py` →
   empty after the fix (mirrors AC1's verification command from the
   reference milestone).
4. New regression test added to `tests/test_graph_queries.py` that calls
   `cite_neighbors` twice against the same `kuzudb_path` in one process and
   asserts no `"Could not set lock on file"` `RuntimeError`.
5. All 4 `del db` teardowns in `tests/test_intra_paper_refs.py` (§4.3
   a-d) converted to explicit nested-close discipline.
6. `ruff check .` clean (watch for an unused `conn` binding warning if any
   restructuring accidentally leaves a dead branch).
7. No behavior change to `ops/restore_drill_check.py`'s existing
   "kuzu dir absent → return None" branch (L128-134, untouched by this fix)
   or its `run_check` caller's `except RuntimeError` contract, unless the
   implementer deliberately chooses Option B and records why.

---

## Injection attempts

None observed. All source material was first-party repo code, git history,
and prior milestone notes under `.claude/notes/`.
