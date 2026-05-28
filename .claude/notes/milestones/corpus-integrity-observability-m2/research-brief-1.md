# Research Brief — corpus-integrity-observability-m2

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-28T00:00:00Z

## In-codebase context

### Key seams and load-bearing code

**1. `DegradedState` dataclass — `server/corpus.py:110-138`**

```python
@dataclass(frozen=True, slots=True)
class DegradedState:
    reason: str
    fallback_version: int
    original_version: int
```

`DegradedState` is a frozen dataclass with exactly 3 fields today. The m2
brief requires setting `DegradedState.reason="chunk_count_diverged"` at startup.
The existing `reason` values are only `"corpus_corruption"` (set by
`open_chunks_table_with_fallback`). The `chunk_count_diverged` reason is NEW and
must be added to the enumerated label space in `refresh_degraded_mode_metric`
(currently only knows `"corpus_corruption"` and `"hosted_embedder_outage"` —
`server/health.py:638`).

**2. `Resources.degraded` field — `server/resources.py:280-285`**

```python
#: Failure-mode degradation marker (E14_S05 D2). ``None`` on
#: the happy path. Set to a :class:`server.corpus.DegradedState`
#: when ``open_chunks_table_with_fallback`` activated the N-1
#: fallback. Read by :func:`server.health.readyz` (degraded body)
#: and by ``server.observability.metrics.DEGRADED_MODE_ACTIVE``
#: scrape refresh.
degraded: DegradedState | None = None
```

This is already the field the brief wants to use. The m2 logic sets it to
`DegradedState(reason="chunk_count_diverged", fallback_version=0,
original_version=0)` when divergence exceeds tolerance. The `fallback_version`
and `original_version` fields have no meaning for the count-diverged case — the
implementer should use sentinel values (0 or the same version) and document this.

**3. `Resources.startup` sequence — `server/resources.py:305-712`**

The startup sequence is: (1) read marker, (2) open LanceDB, (3) load BGE-M3,
(4) reranker, (4b) BM25, (4c) ANN, (5) concurrency primitives, (5c) reranker
warmup, (6) cache, (6b) definitions/equations, (6d) theorem names, (6e) Lean
REPL. The `count_rows()` call belongs **after step 2** (table open), because the
table handle is needed. It should happen BEFORE the BM25 phase (step 4b) which
already calls `chunks_table.to_arrow()` for its live_chunk_ids set — that full
scan at `resources.py:407-409` is a separate, heavier operation than `count_rows()`.

Currently a `count_rows()` call already exists at `resources.py:476` inside the
reranker warmup (step 5c), but it is gated by `config.enable_rerank` and is
not cached. The m2 requirement is an UNCONDITIONAL, CACHED `count_rows()` at
step 2 or immediately after.

**4. `readyz` handler — `server/health.py:159-228`**

The `/readyz` degraded path at `server/health.py:199-217` already handles
`resources.degraded is not None` by returning:
```json
{
  "status": "degraded",
  "reason": resources.degraded.reason,
  "fallback_version": resources.degraded.fallback_version,
  "original_version": resources.degraded.original_version,
  "warm": {...}
}
```
No changes to `readyz` handler logic are needed — the brief's AC ("readyz
reports degraded with reason=chunk_count_diverged") is already satisfied by the
existing degraded path as long as `resources.degraded` is set correctly.

**5. `refresh_degraded_mode_metric` — `server/health.py:625-642`**

```python
def refresh_degraded_mode_metric(resources: Resources) -> None:
    from server.observability.metrics import DEGRADED_MODE_ACTIVE
    degraded = getattr(resources, "degraded", None)
    if degraded is None:
        for reason in ("corpus_corruption", "hosted_embedder_outage"):
            DEGRADED_MODE_ACTIVE.labels(reason=reason).set(0.0)
        return
    DEGRADED_MODE_ACTIVE.labels(reason=degraded.reason).set(1.0)
```

This function hardcodes `"corpus_corruption"` and `"hosted_embedder_outage"` in
its zero-out pass. When `resources.degraded.reason="chunk_count_diverged"`, the
new reason is set to 1.0 but the zero-out pass on the happy path will NOT zero
it out on recovery (process restart clears it anyway — stateless gauge). The
implementer must add `"chunk_count_diverged"` to the enumeration in the zero-out
loop at `server/health.py:638`.

**6. Gauge registration pattern — `server/health.py:92-97`**

```python
CORPUS_VERSION_GAUGE = Gauge(
    "arxmcp_corpus_version",
    "The integer corpus_version the server pinned at startup. "
    "Constant for the process lifetime; restart to pick up a new "
    "corpus version.",
)
```

The two new gauges should follow this exact pattern: module-level `Gauge(...)`
at the top of `server/health.py` (no labels — they are scalar). The gauge values
are SET ONCE in `refresh_metrics_from_singleton_state` (or a dedicated helper
called from it) using `resources.corpus_info.chunk_count` (marker value) and
`resources.cached_chunk_count` (table-derived, cached at startup).

**7. `refresh_metrics_from_singleton_state` — `server/health.py:237-298`**

This function is called: (a) at startup, `main.py:311`, after resources are
attached; and (b) at every `/metrics` scrape, `main.py:633`. Since the new
gauges must reflect startup-cached values (not recomputed per scrape), they
should be unconditionally set in this function using the cached field on
`Resources` — the Prometheus `Gauge.set()` semantics are: last set value is
reported; no recomputation happens inside Prometheus client. Setting them here
(even on every scrape) is fine as long as the underlying `Resources` field is
set once at startup.

**8. Tolerance config — `server/config.py` `eq_ted_weight` float validator pattern**

The pattern for a bounded float config field is:
```python
eq_ted_weight: float = 0.5

@field_validator("eq_ted_weight")
@classmethod
def validate_eq_ted_weight(cls, v: float) -> float:
    if not 0.0 <= v <= 1.0:
        raise ValueError(f"ARXMCP_EQ_TED_WEIGHT must be in [0.0, 1.0]; got {v}.")
    return v
```

The m2 tolerance field should mirror this: `chunk_count_divergence_tolerance:
float = 0.05` with a `@field_validator` rejecting values outside `[0.0, 1.0]`.
The env var would be `ARXMCP_CHUNK_COUNT_DIVERGENCE_TOLERANCE`.

**9. Where the new `Resources` field lives**

The brief says "compute count_rows() ONCE (cache it on Resources)". The
`Resources` dataclass has existing optional fields like `reranker_model: Any |
None = None`. The new field should be: `cached_chunk_count: int | None = None`.
Set to the result of `chunks_table.count_rows()` in `startup()`, immediately
after step 2 (LanceDB open). This makes it non-None for any server that has a
table, and eliminates any chance of re-computing per scrape.

**10. BM25 live_chunk_ids scan at `resources.py:407-409`**

```python
live_chunk_ids = set(
    chunks_table.to_arrow().column("chunk_id").to_pylist()
)
```

This already materializes the full table. The m2 `count_rows()` call can be
placed BEFORE this and its result stored; the BM25 path does not need to call
`count_rows()` separately. No double-counting concern.

### Prometheus client version and Gauge.set() semantics

`prometheus_client==0.25.0` (pinned in uv.lock). `Gauge.set(value)` stores
the value in an atomic float; it does NOT recompute on scrape. A gauge set once
at startup reports that value until the next `set()` call. This is exactly the
"startup-cached, NEVER recomputed per scrape" contract the brief requires.

### EXPECTED_TOOL_SCHEMA_SHA256 / EXPECTED_BP1_SHA256

m2 adds no new MCP tools and modifies no tool-schema fields. The `tools/list`
response is unchanged. Both hashes stay frozen. **No re-pinning required.**

### m2 does NOT touch `server/corpus.py`

`DegradedState` has no enum — the `reason` field is a plain `str`. Adding
`"chunk_count_diverged"` requires no changes to `corpus.py`. It is a new string
constant, not a new dataclass variant.

## Prior decisions and lessons

**m1 shipped commit `8e58c42` ("feat(ingest): corpus-version marker counts from
committed table").** The marker's `chunk_count` now equals `tbl.count_rows()`
after a write. The m2 startup reconciliation therefore has accurate data to
compare against at the time of m2's AC verification.

**m1 synthesis §1 (load-bearing):** "version gates the cache key — counts are
observability-only." The m2 comparison is purely observational: a divergence
between `corpus_info.chunk_count` and `chunks_table.count_rows()` does NOT
abort startup, does NOT reject requests, and does NOT affect retrieval. The
WARN + degraded state is informational ("WARN-and-serve" per the brief).

**m1 critique F4 (LOW):** documents that `dataset_version` is captured before
`count_rows()` reads. The same single-writer invariant applies to m2's startup
reconciliation: no concurrent writer can change the table between steps 2 and
the `count_rows()` call.

**From `server/health.py:199-217`:** The existing `/readyz` degraded path
already returns `reason`, `fallback_version`, and `original_version`. The m2
`DegradedState(reason="chunk_count_diverged", fallback_version=0,
original_version=0)` will produce a valid body. The `fallback_version` and
`original_version` fields are semantically meaningless for a count-diverged
reason — the implementer should document this in a comment; their values are 0
(or the corpus_info.version if more meaningful).

**`refresh_degraded_mode_metric` enumeration gap:** The zero-out loop at
`health.py:638` does not know about `"chunk_count_diverged"`. If the server
restarts in a non-diverged state, the gauge would carry the stale `1.0` label
from the prior startup — but in practice Prometheus re-initializes the registry
on process start, so this is only a concern for a running server that dynamically
transitions, which CANNOT happen here (degraded is set once at startup and never
cleared). Still: add `"chunk_count_diverged"` to the zero-out enumeration for
correctness and documentation.

**git log:** Recent commits confirm corpus-integrity-observability-m1 is
complete (`a54f8f3`). No in-flight work touches `server/health.py`,
`server/resources.py`, or `server/config.py`.

## External sources

**prometheus_client 0.25.0 Gauge semantics (confirmed via source):** `Gauge.set(value)`
writes atomically to a `_ValueClass` (an atomic float). No background thread;
no recomputation on scrape. The `make_asgi_app()` ASGI app calls
`generate_latest()` which iterates registered collectors and reads their current
stored values. Setting a Gauge once at startup and never calling `.set()` again
produces a constant value at every subsequent scrape — this is the standard,
documented behavior and is exactly what the brief requires.

**MCP spec:** Not consulted — this milestone adds no new tools, no new MCP
protocol surface. `/readyz` is not an MCP endpoint; it is a FastAPI HTTP
endpoint. The degraded response body changes its `reason` value but not its
shape. Tool schema is unchanged. No spec consultation needed.

## Recommendation

**Add `cached_chunk_count: int | None = None` to the `Resources` dataclass.
Set it immediately after step 2 (LanceDB open) in `Resources.startup()` via
`await loop.run_in_executor(None, chunks_table.count_rows)`. Add
`chunk_count_divergence_tolerance: float = 0.05` to `Config` with a
`[0.0, 1.0]` validator. In startup, after setting `cached_chunk_count`, compare
it against `corpus_info.chunk_count` using the tolerance; if `|actual -
marker| / max(actual, 1) > tolerance`, log WARN with both values and set
`resources.degraded = DegradedState(reason="chunk_count_diverged",
fallback_version=0, original_version=0)`. Add two unlabeled Gauges
`arxmcp_corpus_chunk_count_marker` and `arxmcp_corpus_chunk_count_actual` to
`server/health.py`. Set them in `refresh_metrics_from_singleton_state` from
`resources.corpus_info.chunk_count` and `resources.cached_chunk_count`. Add
`"chunk_count_diverged"` to the zero-out loop in `refresh_degraded_mode_metric`.**

This approach:
- Uses the already-wired `resources.degraded` field and the existing `/readyz`
  degraded path — zero changes to handler routing.
- Satisfies the "set once, never per scrape" AC by caching on `Resources`.
- Is ~50 LOC across 3 files: `server/config.py`, `server/resources.py`,
  `server/health.py` (no new files).
- The gauge registration belongs in `server/health.py` (not
  `server/observability/metrics.py`) to match `CORPUS_VERSION_GAUGE` which is
  already there and semantically similar.

**Critical: `count_rows()` is synchronous I/O.** Like the LanceDB open in step
2, it must be wrapped in `await loop.run_in_executor(None, ...)` to avoid
blocking the event loop.

## Open questions

**No open questions — implementation can proceed on the above recommendation.**

Two potential questions that are pre-answered:
- "Where to put the two new gauges: `server/health.py` or
  `server/observability/metrics.py`?" → `server/health.py` to match
  `CORPUS_VERSION_GAUGE`.
- "What values for `fallback_version`/`original_version` in the
  count-diverged `DegradedState`?" → Use `0` for both (sentinel); document
  in a comment that these fields are corpus-corruption semantics and are
  meaningless in the count-diverged case.

## External writes the implementation will require

None — this milestone is purely local. No git push, PR creation, infra
mutation, or third-party API call.
