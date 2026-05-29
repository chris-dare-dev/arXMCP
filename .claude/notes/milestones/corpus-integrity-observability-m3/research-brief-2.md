# Research Brief — corpus-integrity-observability-m3

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-29T18:30:00Z

## In-codebase context

### lancedb version pin (authoritative)

`uv.lock` pins `lancedb==0.30.2`. Verified at runtime:

```
IndexStatistics(
  num_indexed_rows: int,
  num_unindexed_rows: int,          # rows NOT covered by this index
  index_type: Literal['IVF_HNSW_SQ', ...],
  distance_type: Optional[Literal['l2', 'cosine', 'dot']],
  num_indices: Optional[int],
  loss: Optional[float]
)
```

`tbl.list_indices() -> Iterable[IndexConfig]`; each `IndexConfig` has `.name`, `.columns`,
`.index_type`. So `for ic in tbl.list_indices(): tbl.index_stats(ic.name)` is the
correct chain — NOT `list_indexes()` (confirmed with `dir(LanceTable)`; no `list_indexes`
variant exists in 0.30.2). `index_stats(name)` returns `Optional[IndexStatistics]` — it
can return `None` when the index name is not found (e.g. stale name).

### Known index names set by `_create_indices` (`ingest/store.py:563`)

`_create_indices` creates exactly two HNSW indexes:
- `"hnsw_stmt"` on `embedding_stmt`
- `"hnsw_proof"` on `embedding_proof`

The function is called synchronously INSIDE `write_chunks` before `write_chunks` returns
(`store.py:862`). This makes `num_unindexed_rows == 0` on the normal post-ingest path.
**Non-zero is always abnormal** (partial write, corruption, or future async-index path).

### m2 pattern (load-bearing precedent from `research-synthesis.md`)

The synthesis locked:

- `Resources.startup_chunk_count: int = -1` field on the `Resources` dataclass
  (`server/resources.py:331`)
- count computed via `await loop.run_in_executor(None, chunks_table.count_rows)` with
  `try/except` → `-1` sentinel on failure
- FM-7 guard: "Run reconciliation ONLY when `degraded is None`; otherwise log INFO
  'skipping chunk_count reconciliation: <reason> fallback active.'"
- Gauges (`CORPUS_CHUNK_COUNT_MARKER`, `CORPUS_CHUNK_COUNT_ACTUAL`) declared in
  `server/health.py` beside `CORPUS_VERSION_GAUGE` (lines 104–120)
- Set via `refresh_metrics_from_singleton_state` — O(1), never per-scrape
- `refresh_degraded_mode_metric` zero-out tuple at `health.py:957-963` already contains
  `"chunk_count_diverged"` from m2

**CRITICAL note:** `05-storage-and-indexing.md` confirms the two HNSW indexes are named
per `_create_indices`: `hnsw_stmt` + `hnsw_proof`. No contradiction with the milestone brief.

### `/readyz` degraded mechanics

From `server/health.py:228-240`: when `resources.degraded is not None`, `/readyz` returns
HTTP 503 with `{"status": "degraded", "reason": ..., "fallback_version": ...,
"original_version": ...}`. This path is already fully general — any `DegradedState.reason`
value flows through unchanged.

### Metrics fixture re-gen trap (confirmed pattern from e2 and e3)

`tools/regen_metrics_fixture.py::populate_registry` imports `server.health` and
`server.metrics` as side-effect imports (lines 71-73). Any new `Gauge` declared at module
level in `server/health.py` (or `server/metrics.py`) is registered at import time. A new
`arxmcp_corpus_unindexed_rows` gauge WILL appear in `generate_latest()` output but will
NOT be seeded in `populate_registry`. `tests/test_daily_metrics_report.py:371` (the
`TestRegenFixture` test) will fail until:

1. `populate_registry()` seeds the new gauge (e.g. `CORPUS_UNINDEXED_ROWS.set(0)`)
2. `tests/fixtures/metrics_sample.txt` is regenerated via
   `uv run python -m tools.regen_metrics_fixture`

This is the exact same trap that bit e2 (m2) and e3 — it is **mandatory** in the
implementation plan.

## Prior decisions and lessons

### git log context

Recent commits confirm m2 is complete (`a8c7414f`). The m1 marker fix ships at `8e58c42`.
m3 is the next in the `corpus-integrity-observability-*` sequence; no conflicting in-flight
work visible.

### m2 critique findings

The m2 adversary critique flagged that the FM-7 clobber guard had no startup regression
test (F1, HIGH). The rectifier added it. The m3 brief must include the same test from the
start so the adversary does not repeat the finding.

### `refresh_degraded_mode_metric` zero-out tuple

`health.py:957-963` currently enumerates `("corpus_corruption", "hosted_embedder_outage",
"chunk_count_diverged")`. IF m3 adds a new `DegradedState.reason="unindexed_rows"`, this
tuple MUST be extended. However (see Recommendation below), m3 should NOT add degraded.

### Banned patterns

- `assert` banned for invariants in `server/` — use `if ... raise RuntimeError` or
  WARN-and-continue.
- `baseHTTPMiddleware` and `anthropic` SDK: not relevant here.
- `KMP_DUPLICATE_LIB_OK=TRUE` in `tests/conftest.py`: not touched.
- No new MCP tool surface → `EXPECTED_TOOL_SCHEMA_SHA256` and `EXPECTED_BP1_SHA256` stay
  frozen. No re-pin needed.

## External sources

**LanceDB 0.30.2 API (verified at runtime, not from docs):**

```python
tbl.list_indices() -> Iterable[IndexConfig]   # IndexConfig.name, .columns, .index_type
tbl.index_stats(index_name: str) -> Optional[IndexStatistics]
IndexStatistics.num_unindexed_rows: int       # the field we need
```

`index_stats` returns `None` when the named index does not exist (e.g. `hnsw_proof` was
skipped because `embedding_proof` had zero non-null rows — `_create_indices:612` handles
this case and does NOT call `create_index`; the index name will not appear in
`list_indices()`). Therefore iterating `list_indices()` and calling `index_stats` on each
is safe — but callers must still guard against `None` return.

Anthropic prompt-caching docs: not relevant (no MCP surface change).

MCP spec: not relevant (not touching any tool or `/mcp` path).

## Recommendation

**WARN+gauge only. Do NOT add `DegradedState(reason="unindexed_rows")` or flip `/readyz`
to 503.**

Reasoning: the m2 synthesis defined the degraded contract as "correctness degradation"
— `chunk_count_diverged` was added because a divergence means the server is lying about
its corpus (WARN-and-serve is the right UX, but degraded signals the operator that
something is broken enough to warrant a reindex). Unindexed rows are a **performance
issue only**: brute-force ANN still returns identical results. The `08-security-
observability-ops.md` degraded-mode table documents: "LanceDB corrupt on restart → Open
fails → Fall back to previous dataset version… alert." That is a correctness regression.
A partially-unindexed table is not.

The "non-zero is always abnormal" framing is correctly handled by WARN+gauge: the gauge
itself is a Prometheus-alertable signal (operators can wire `arxmcp_corpus_unindexed_rows
> 0` alert) without pulling the server from rotation via 503. Returning 503 for a
perf-only anomaly would cause load-balancer ejection for a server that is serving correct
results — an OVER-reaction.

**Concrete recommendation:** WARN+gauge only. Set `startup_unindexed_rows: int = -1` on
`Resources`. Expose as `CORPUS_UNINDEXED_ROWS` scalar gauge in `server/health.py` (beside
`CORPUS_VERSION_GAUGE`). Set once in `refresh_metrics_from_singleton_state`. Never per
scrape. `refresh_degraded_mode_metric` zero-out tuple is NOT extended (no new reason).

## Failure-mode analysis

### FM-1 — `list_indices()` or `index_stats()` API raises (top risk)

**Trigger:** lancedb version drift, or the sync API behaves unexpectedly on a
checked-out (read-only) table handle.
**Symptom:** `AttributeError`, `RuntimeError`, or similar propagates into startup.
**Mitigation:** Wrap the ENTIRE `list_indices` + `index_stats` loop in `try/except
Exception`. On exception: set `startup_unindexed_rows = -1`, log WARN with
`exc_info=True`, proceed. Startup MUST NOT fail (mirror m2 FM-2). Gauge reports `-1.0`.
Mirror the pattern at `resources.py:443-449` exactly.

### FM-2 — No index exists yet (empty table or pre-index corpus)

**Trigger:** `list_indices()` returns an empty iterable because the corpus was written
before `_create_indices` was called (cold-start with a raw LanceDB table, or a corpus
written by an older store version).
**Symptom:** The sum loop produces `total_unindexed = 0`. But `0` here means "no index to
report on" — NOT "fully indexed."
**Resolution recommendation:** Distinguish "no ANN indexes present" from "fully indexed"
by checking `if not any_index_found: set startup_unindexed_rows = -1` (unknown, not 0).
A gauge of `-1.0` signals "could not determine" whereas `0.0` signals "checked and clean."
This prevents a false-clean signal on a corpus that was never indexed.
**Concrete rule:** after the loop, if `total_unindexed == 0 AND index_count == 0`, set
`startup_unindexed_rows = -1` (not 0). If `index_count > 0 AND total_unindexed == 0`,
set `startup_unindexed_rows = 0` (truly clean).

### FM-3 — `index_stats(name)` returns `None` for a named index

**Trigger:** `list_indices()` returns an `IndexConfig` with name `"hnsw_stmt"`, but
`index_stats("hnsw_stmt")` returns `None` (edge case: index in metadata but dropped or
corrupt).
**Symptom:** `NoneType` has no `num_unindexed_rows` → `AttributeError` if unchecked.
**Mitigation:** Guard with `if stats is not None: total += stats.num_unindexed_rows`.
Treat `None` as 0 contribution (cannot determine for this index). Log a DEBUG note.

### FM-4 — MVCC checkout semantics: does `index_stats` reflect the checked-out version?

**Trigger:** The server pins a specific corpus_version via `dataset.checkout(version=N)`
(`resources.py:401-407`). `list_indices()` / `index_stats()` are called on the checked-out
table. New rows written AFTER version N (by a concurrent ingest) would have `num_unindexed_
rows > 0` at the live tip but not at version N.
**Finding:** This is SAFE by design. The checked-out table handle returns index stats
relative to the pinned version. `_create_indices` runs synchronously inside `write_chunks`
and the version marker is written AFTER `_create_indices` completes (`store.py:63-68`). So
at the pinned version, the index is always up to date. Any `num_unindexed_rows > 0` at
the pinned version is genuinely anomalous. **No mitigation needed; note in a code
comment.**

### FM-5 — Gauge staleness by design

**Trigger:** A new ingest run adds rows and `_create_indices` runs again on the new
version while the server is still serving the old pinned version. The server does NOT pick
up the new index; it stays on version N.
**Symptom:** The gauge shows the startup-time value forever.
**Design intent:** This IS the intended contract — "startup-cached, never recomputed."
The server is process-lifetime-pinned to its corpus version. Restart to refresh (same note
as m2 FM-5). Add code comment: "STALE BY DESIGN; restart to pick up a new corpus version."

### FM-6 — Two indexes with different `num_unindexed_rows` (sum vs per-index)

**Trigger:** `hnsw_stmt` has 500 unindexed rows; `hnsw_proof` has 200. Sum = 700.
**Question from brief:** single sum gauge or per-index label?
**Recommendation:** Single scalar sum gauge `arxmcp_corpus_unindexed_rows`. The WARN log
MUST include per-index breakdown: `"unindexed_rows: hnsw_stmt=500, hnsw_proof=200,
total=700"`. A per-index gauge family (with `index_name` label) adds 2 time series for
negligible benefit — a single scalar is sufficient for alerting and the log carries the
breakdown. Keep it simple.

### FM-7 — `refresh_degraded_mode_metric` zero-out enumeration (NOT needed for m3)

**Trigger:** m2 added `"chunk_count_diverged"` to the zero-out tuple. IF m3 added
`"unindexed_rows"` as a degraded reason, it would also need to be added.
**Resolution:** Since m3 does NOT add degraded, no change to the zero-out tuple is needed.
**Important:** Do NOT add `"unindexed_rows"` to the tuple — it would register a label that
is never set, which is benign but misleading. No change.

### FM-8 — Metrics fixture regen (mandatory, previously bit e2 and e3)

**Trigger:** Adding `CORPUS_UNINDEXED_ROWS = Gauge(...)` to `server/health.py` causes it
to appear in `generate_latest()`. `TestRegenFixture` in
`tests/test_daily_metrics_report.py:305` will fail if `populate_registry()` does not seed
the gauge and `metrics_sample.txt` is not regenerated.
**Mitigation (mandatory):** Add `from server.health import CORPUS_UNINDEXED_ROWS` +
`CORPUS_UNINDEXED_ROWS.set(0)` inside `populate_registry()` in
`tools/regen_metrics_fixture.py`. Then regenerate: `uv run python -m
tools.regen_metrics_fixture`. This is load-bearing — do not skip.

## Open questions

No open questions — implementation can proceed on the above recommendation.

The OPEN DESIGN QUESTION from the brief (WARN+gauge vs degraded) is resolved:
**WARN+gauge only.** Reasoning is in the Recommendation section above.

## External writes the implementation will require

None — this milestone is purely local.

Files expected to change: `server/resources.py` (new cached field + startup block),
`server/health.py` (new gauge declaration + `refresh_metrics_from_singleton_state` setter),
`tools/regen_metrics_fixture.py` (seed the new gauge), `tests/fixtures/metrics_sample.txt`
(regenerated), and test files under `tests/` (AC-1 through AC-4 + FM-7 pattern from m2).
No `git push`, PR, infra mutation, or third-party API call.
