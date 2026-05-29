# Research Synthesis — corpus-integrity-observability-m3

**Merged from:** research-brief-1.md (seam map + live-verified lancedb API) +
research-brief-2.md (failure modes + the degraded-vs-WARN resolution).
**Generated:** 2026-05-29.
**Verdict:** INLINE-or-DELEGATED, ~4–5 files, no novel architecture (mirrors m2
verbatim). Purely local. Builds the scout CAND-10 unindexed-rows tripwire. Both
briefs concur; divergences resolved in §3.

## 1. The locked design (mirror corpus-integrity-observability-m2 exactly)

A startup tripwire for the silent brute-force-ANN-fallback class: at
`Resources.startup`, after the m2 `count_rows` block, compute the total HNSW
`num_unindexed_rows` ONCE, cache it on a new `Resources.startup_unindexed_rows: int = -1`
field, and expose a scalar gauge `arxmcp_corpus_unindexed_rows` set once from the cached
value in `refresh_metrics_from_singleton_state` (NEVER per scrape). On a real non-zero
count: WARN (naming the per-index breakdown). **WARN + gauge ONLY — do NOT flip `/readyz`
to degraded** (§3 D1).

- **`server/resources.py`** — add `startup_unindexed_rows: int = -1` beside
  `startup_chunk_count` (~:331). Insert a "step 2c" block immediately after the m2 block
  (~after :483, before the BGE-M3 load), mirroring the m2 try/except + the FM-7
  `degraded is None` guard. Add `startup_unindexed_rows=startup_unindexed_rows` to the
  `cls(...)` construction (~:784).
- **`server/health.py`** — add `CORPUS_UNINDEXED_ROWS = Gauge("arxmcp_corpus_unindexed_rows", ...)`
  beside `CORPUS_CHUNK_COUNT_MARKER`/`_ACTUAL` (~:100-120) — NOT `server/metrics.py`
  (this is a startup-set corpus-health gauge, like the m2 gauges, not a scrape-time
  sentinel-bridged one). Set it in `refresh_metrics_from_singleton_state` right after the
  m2 gauge sets, **getattr-defended**:
  `CORPUS_UNINDEXED_ROWS.set(getattr(resources, "startup_unindexed_rows", -1))`.
- **`tools/regen_metrics_fixture.py`** — seed the new gauge in `populate_registry`
  (`CORPUS_UNINDEXED_ROWS.set(0)`), then regenerate `tests/fixtures/metrics_sample.txt`
  via `uv run python -m tools.regen_metrics_fixture`. **MANDATORY** (this bit e2 AND e3 —
  `TestRegenFixture` fails otherwise).
- `refresh_degraded_mode_metric` zero-out tuple is **UNCHANGED** (no new degraded reason).
- No `server/config.py` toggle — the tripwire is always-on (like the m2 reconciliation).

## 2. Load-bearing facts (both briefs, lancedb 0.30.2 LIVE-VERIFIED)

- **The API (verified at runtime against the installed 0.30.2, not docs):**
  `tbl.list_indices() -> Iterable[IndexConfig]` (each has `.name`, `.columns`,
  `.index_type`). **CORRECTION (m3 critique F1): this returns ALL indexes, NOT
  vector-only — `_create_indices` also builds a scalar `paper_id` BTree, so
  `list_indices()` returns `[embedding_stmt_idx(IvfHnswSq), paper_id_idx(BTree)]`.
  The implementation MUST filter to vector index types (`index_type` contains
  HNSW/IVF) before counting, else the scalar index defeats the D2 no-vector-index
  → -1 sentinel.** `tbl.index_stats(name) ->
  Optional[IndexStatistics]` with `.num_unindexed_rows: int` (+ `num_indexed_rows`,
  `index_type`, ...). The method is `list_indices()` — there is NO `list_indexes()` in
  0.30.2. `index_stats(name)` can return `None` for an unknown/dropped index → MUST guard.
  The chain: `for ic in tbl.list_indices(): s = tbl.index_stats(ic.name); if s is not None: total += s.num_unindexed_rows`.
- **It is a PURE TRIPWIRE.** `_create_indices` (`ingest/store.py:563`) runs SYNCHRONOUSLY
  inside `write_chunks` before it returns, so on the normal post-ingest path
  `num_unindexed_rows == 0`. Verified: after `_create_indices` → 0; after `tbl.add(rows)`
  without re-index → `len(rows)`. Any non-zero at the pinned version is genuinely abnormal
  (partial write / corruption / a future async-index path).
- **MVCC is safe (FM-4):** `index_stats` on the checked-out (version-pinned) table reflects
  that version's coverage; the marker is written AFTER `_create_indices` completes, so the
  pinned version is always fully indexed in normal operation. Note it in a comment.
- **Index names are discovered, never hardcoded.** (The briefs disagree on the actual
  names — R1 live-saw `embedding_stmt_idx`/`embedding_proof_idx` auto-derived from the
  column since `_create_indices` passes no `name=`; R2 cited the docstring's
  `hnsw_stmt`/`hnsw_proof`. This is MOOT — the code iterates `list_indices()`; tests should
  STUB `list_indices`/`index_stats` rather than assert specific names.)
- **m2 templates to mirror** (`server/resources.py` `startup_chunk_count` field + the
  count_rows try/except at ~:439 + the FM-7 `degraded is not None` skip at ~:451;
  `server/health.py` the `CORPUS_CHUNK_COUNT_*` gauges + their setter at ~:518 +
  getattr-defense). `count_rows`/`index_stats` are sync I/O → wrap the discover+sum loop in
  a single helper run via `await loop.run_in_executor(None, _count_unindexed, chunks_table)`.
- **No MCP surface change:** `/metrics` is operational. `EXPECTED_TOOL_SCHEMA_SHA256` +
  `EXPECTED_BP1_SHA256` FROZEN; no `server/tools.py`/`server/prompts.py` change. No new
  dependency. `assert` banned for invariants (use try/except + WARN-and-continue).

## 3. Divergences + refinements resolved (orchestrator synthesis note)

**D1 — degraded vs WARN-only (the open design question). RESOLVED → WARN + gauge ONLY;
do NOT add `DegradedState(reason="unindexed_rows")` and do NOT flip `/readyz` to 503.**
Both briefs land here. Reasoning (brief-2): the m2 degraded contract is for CORRECTNESS
degradation (`chunk_count_diverged` = the marker disagrees with the table → possible data
loss). Unindexed rows are PERFORMANCE-only — brute-force ANN returns IDENTICAL results,
just slower. A 503 would eject a correct-serving server from the load balancer — an
over-reaction. The gauge is itself the Prometheus-alertable signal
(`arxmcp_corpus_unindexed_rows > 0`) without the 503. The zero-out tuple in
`refresh_degraded_mode_metric` is therefore UNCHANGED (adding an unset label is misleading).

**D2 — the sentinel rule: no-index ⇒ -1, NOT 0 (brief-2 FM-2 refinement; ADOPT over
brief-1's return-0).** The cached `startup_unindexed_rows` is:
- **-1 (unavailable/unknown)** when: the API raises (FM-1), OR `list_indices()` is empty /
  no ANN index exists (FM-2 — a never-indexed corpus brute-forces EVERYTHING; reporting 0
  there is a dangerous false-clean), OR every `index_stats` returned `None`.
- **0 (checked & clean)** ONLY when ≥1 ANN index exists AND all report `num_unindexed_rows == 0`.
- **>0 (abnormal)** when ≥1 index reports unindexed rows → WARN.
Concretely: track `index_count` (configs seen with a non-None stat); `if index_count == 0:
startup_unindexed_rows = -1` else `= total`. This distinguishes "fully indexed" from
"could not determine", so the gauge never lies about coverage.

## 4. Failure modes → required handling (brief-2)

- **FM-1 API raises (top risk):** wrap the whole discover+sum loop in `try/except Exception`
  → `startup_unindexed_rows = -1`, WARN (`exc_info=True`), NEVER fail startup, `/readyz`
  still 200 (mirror m2 FM-2). Gauge reports `-1.0`.
- **FM-2 no index exists:** → -1 per D2 (not 0).
- **FM-3 `index_stats(name)` returns None:** guard `if stats is not None` (don't add to
  total, don't count toward `index_count`).
- **FM-4 MVCC:** safe by design (pinned version is fully indexed); comment it.
- **FM-5 gauge staleness:** startup-cached, never refreshed — by design (process pinned to
  its corpus version; restart to refresh). Comment "STALE BY DESIGN" like m2.
- **FM-6 two indexes, different counts:** a SINGLE scalar sum gauge; the WARN names the
  per-index breakdown (`stmt=…, proof=…, total=…`). No per-index label (negligible benefit,
  extra time series).
- **FM-8 metrics-fixture regen:** MANDATORY — seed the gauge in `populate_registry` +
  regenerate `metrics_sample.txt`.

## 5. Acceptance criteria

1. Given a corpus with unindexed rows (stub `index_stats` to report non-zero, OR a
   real `tbl.add`-without-reindex fixture), when the server starts, then it logs a WARN
   naming the count and `arxmcp_corpus_unindexed_rows` is non-zero.
2. Given a fully-indexed corpus (≥1 index, all `num_unindexed_rows == 0`), when the server
   starts, then no WARN and the gauge is `0`.
3. Given `list_indices()`/`index_stats()` raising OR no ANN index present, when the server
   starts, then it does NOT crash — cached value is `-1`, gauge reports `-1.0`, a WARN is
   logged, and `/readyz` still reaches 200.
4. The gauge is set once at startup from the single cached value; a test asserts
   `index_stats` is NOT called per `/metrics` scrape (mirror m2's count_rows-once test).
5. A startup regression test for the FM-7 guard (degraded already set ⇒ unindexed check
   skipped, not clobbered) — the m2 adversary flagged the absence of this; include it from
   the start.
6. `EXPECTED_TOOL_SCHEMA_SHA256` + `EXPECTED_BP1_SHA256` UNCHANGED; no `CHUNKER_VERSION`
   bump; `make test` green (incl. the regenerated fixture).

## 6. Implementation order

1. `server/resources.py` — field + step-2c block (helper `_count_unindexed`, try/except →
   -1, D2 no-index rule, FM-7 skip, WARN with per-index breakdown) + `cls(...)` arg.
2. `server/health.py` — `CORPUS_UNINDEXED_ROWS` gauge + getattr-defended setter in
   `refresh_metrics_from_singleton_state`.
3. `tools/regen_metrics_fixture.py` — seed the gauge; regenerate `metrics_sample.txt`.
4. Tests: AC-1..AC-6 (stub `chunks_table.list_indices`/`index_stats` for the non-zero +
   raises + no-index + None cases; the gauge-once scrape test; the FM-7 startup test). A
   new `tests/test_corpus_unindexed_guard.py` or extend `tests/test_corpus_count_reconciliation.py`.

## 7. Open questions

**None blocking.** Both briefs reported "no open questions"; the degraded-vs-WARN question
is resolved (§3 D1) and the no-index sentinel is resolved (§3 D2).

## 8. External writes required

**None** — purely local (`server/resources.py`, `server/health.py`,
`tools/regen_metrics_fixture.py`, `tests/fixtures/metrics_sample.txt`, tests). Both concur.
