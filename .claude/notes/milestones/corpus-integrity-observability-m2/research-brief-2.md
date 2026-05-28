# Research Brief — corpus-integrity-observability-m2

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-28T21:30:00Z

---

## In-codebase context

### DegradedState — existing structure (load-bearing)

`server/corpus.py:109-137` defines:

```python
@dataclass(frozen=True, slots=True)
class DegradedState:
    reason: str
    fallback_version: int
    original_version: int
```

The `reason` field is already a plain `str`. Today's known values:
`"corpus_corruption"` (LanceDB N-1 fallback) and `"hosted_embedder_outage"`.

**The milestone brief's `DegradedState.reason="chunk_count_diverged"` is a NEW
value for the existing `reason` field — it does NOT require a schema change to
`DegradedState` itself.** Only `fallback_version` and `original_version` are
semantically N/A for this case — both can be set to `corpus_info.version`
(i.e., same value, no actual fallback occurred).

### `refresh_degraded_mode_metric` label enumeration (CONFLICT FLAGGED)

`server/health.py:636-642`:
```python
for reason in ("corpus_corruption", "hosted_embedder_outage"):
    DEGRADED_MODE_ACTIVE.labels(reason=reason).set(0.0)
```

**This enumerate-known-reasons loop MUST be extended** to include
`"chunk_count_diverged"` or the gauge for that reason will never be zeroed on
recovery (e.g. restart with a repaired corpus). The implementer must add
`"chunk_count_diverged"` to this tuple.

### `/readyz` degraded path (load-bearing)

`server/health.py:203-217`: when `resources.degraded is not None`, `/readyz`
returns HTTP 503 with body:
```json
{"status": "degraded", "reason": "...", "fallback_version": ..., "original_version": ..., "warm": {...}}
```

The `chunk_count_diverged` case sets `degraded` WITHOUT an actual LanceDB
fallback. `fallback_version` and `original_version` fields must be populated
(the dataclass is `frozen=True, slots=True` — no optional fields). Using
`corpus_info.version` for both is the correct sentinel (no actual version
change occurred).

### `Resources` dataclass — no `startup_chunk_count` field yet

`server/resources.py:219-285`: the `Resources` dataclass has no
`startup_chunk_count` field today. The milestone requires adding one (an `int`
field, default 0 or annotated `int | None = None`). This field serves two
purposes:
1. Cache the single `count_rows()` result so gauges can read it without
   rescanning.
2. Allow the test to mock/assert `count_rows()` called exactly once.

### `startup()` execution order constraint

`server/resources.py:306-711`: `Resources.startup()` is a sequential async
method. `count_rows()` must be called AFTER step 2 (LanceDB table open,
`server/resources.py:354-375`) and BEFORE step 6 (cache open). The
reconciliation check + gauge population must run before `warm = True` is set
(so `/readyz` can reflect degraded state at first poll). The BM25 phase
(step 4b, `server/resources.py:402-413`) already calls
`chunks_table.to_arrow().column("chunk_id").to_pylist()` — a full table scan.
**The implementer should call `count_rows()` BEFORE the BM25 full-table scan
to ensure the count is from the same snapshot.**

### `DEGRADED_MODE_ACTIVE` gauge — `reason` label space

`server/observability/metrics.py:229-236`:
```python
DEGRADED_MODE_ACTIVE: Gauge = Gauge(
    "arxmcp_degraded_mode_active",
    "...",
    labelnames=["reason"],
)
```
The new `chunk_count_diverged` reason will naturally create a new label
series when set. **This gauge is distinct from the two new gauges the brief
introduces** (`arxmcp_corpus_chunk_count_marker` and
`arxmcp_corpus_chunk_count_actual`). Those are new `Gauge` objects with no
labels (scalar gauges), defined in `server/health.py` alongside the existing
`CORPUS_VERSION_GAUGE` pattern.

### `refresh_metrics_from_singleton_state` — scrape-time refresh hook

`server/health.py:237-297`: this function is called at EVERY `/metrics` scrape.
**The new chunk-count gauges must NOT read `count_rows()` here.** They must
read `resources.startup_chunk_count` (the cached value). This is the mechanism
that enforces "never per scrape." The correct implementation pattern:

```python
CORPUS_CHUNK_COUNT_ACTUAL.set(resources.startup_chunk_count)
CORPUS_CHUNK_COUNT_MARKER.set(resources.corpus_info.chunk_count)
```

Both calls are O(1) reads of cached Python integers — no I/O.

### `EXPECTED_TOOL_SCHEMA_SHA256` and `EXPECTED_BP1_SHA256` — unaffected

`server/health.py` and `server/resources.py` are infrastructure, not MCP tool
surface. `/readyz` and `/metrics` are operational endpoints, not MCP tools.
`ALL_TOOLS` in `server/tools.py` is untouched. `EXPECTED_TOOL_SCHEMA_SHA256`
and `EXPECTED_BP1_SHA256` remain frozen.

### m1 — just shipped (load-bearing dependency)

`corpus-integrity-observability-m1` completed at commit
`8e58c4263b4bb29260b4bff620260f7d21ffa319` (rect at
`da3a9ab23e1fcefd1cc4586fbd5f275004bef0e6`). The marker's `chunk_count` is now
correct (table-derived). m2's reconciliation check is therefore meaningful: a
divergence found at startup indicates a corruption event between the last write
and startup, not a pre-existing off-by-one.

---

## External sources

### prometheus_client 0.25.0 — Gauge `.set()` semantics (verified empirically)

Pin: `uv.lock` resolves `prometheus-client==0.25.0`; `pyproject.toml` pins
`>=0.20`. Confirmed via live Python invocation:

```
g = Gauge('test_gauge', 'test', registry=r)
g.set(42.0)
generate_latest(r) → b'test_gauge 42.0\n'
g.set(99.0)
generate_latest(r) → b'test_gauge 99.0\n'
```

**Key confirmed behaviors:**
1. `Gauge.set(value)` stores the value in a thread-safe atomic; it is NOT
   recomputed on scrape. `generate_latest()` reads the stored value directly.
2. A gauge set ONCE at startup and never updated will serve that value on every
   scrape indefinitely. This is the correct pattern for `startup_chunk_count`.
3. `_total` suffix is the `Counter` convention only. Plain gauge names like
   `arxmcp_corpus_chunk_count_marker` and `arxmcp_corpus_chunk_count_actual`
   are correct per Prometheus naming conventions.
4. Prometheus does NOT re-call any user function at scrape time for a
   `.set()`-based gauge (only `set_function()` gauges compute on scrape).
   The "never per scrape" AC is therefore trivially satisfied by NOT calling
   `count_rows()` in `refresh_metrics_from_singleton_state`.

### MCP spec 2025-06-18 — `/readyz` is not MCP surface

`/readyz` and `/metrics` are plain HTTP endpoints mounted outside the MCP
`/mcp` handler. The MCP spec governs `tools/list`, `tools/call`, and related
JSON-RPC methods. Operational HTTP endpoints are outside spec scope. No
`EXPECTED_TOOL_SCHEMA_SHA256` impact.

---

## Failure-mode analysis

### FM-1: Marker MISSING at startup (cold bootstrap)

**Trigger:** `corpus-version.json` absent — fresh `make bootstrap` before any
ingest run, or a deleted file.

**Current behavior:** `Resources.startup()` at `server/resources.py:329-336`
raises `CorpusNotIngestedError` and the server REFUSES to start. The
reconciliation code in m2 is never reached.

**Correct behavior:** m2 adds no new failure mode here. The cold-start guard
fires before m2's reconciliation. No false `chunk_count_diverged` degradation
on a fresh corpus.

**Mitigation:** no change needed — the existing pre-condition guard handles it.

### FM-2: `count_rows()` raises or hangs at startup

**Trigger:** LanceDB table opened but `count_rows()` fails (e.g., fragments
corrupted AFTER open, O/S signal during startup, or LanceDB internal bug).

**Risk:** if `count_rows()` raises, `Resources.startup()` will propagate the
exception and the server refuses to start. This is MORE aggressive than
WARN-and-serve.

**Recommendation:** wrap in `try/except Exception` (broad; non-fatal). On
exception, log WARN with the exception, set `startup_chunk_count = -1` (a
sentinel), skip the reconciliation check (divergence undefined if count is
unavailable), and do NOT set `degraded`. Set both gauges to -1.0 so operators
can detect the count-miss via metrics. Proceeding without the count is safe —
retrieval is unaffected.

### FM-3: Division-by-zero tolerance edge case — both counts are 0

**Trigger:** freshly written corpus with 0 chunks. Marker `chunk_count=0`,
`count_rows()=0`.

**Risk:** a percentage-based tolerance formula `abs(actual - marker) / marker
* 100` with `marker=0` raises `ZeroDivisionError`.

**Mitigation:** guard with `if marker == 0 and actual == 0: pass` (no
divergence — both empty). If `marker == 0` but `actual > 0`, divergence is
absolute (infinite percent) — WARN unconditionally. If `marker > 0` and
`actual == 0`, same: WARN unconditionally. The implementation should use an
absolute difference check when `marker == 0`:
```python
if marker == 0:
    diverged = actual != 0
else:
    diverged = abs(actual - marker) / marker > tolerance
```

### FM-4: Tolerance boundary — very small corpora (5% < 1 row)

**Trigger:** corpus with, say, 10 chunks. 5% tolerance = 0.5 rows (fractional).
Actual count = 10, marker = 10 → `abs(10-10)/10 = 0.0%` → no divergence.
But if actual = 11 (1 row added) → 10% → WARN.

**Risk:** for tiny corpora, a single row discrepancy trips the alert. This may
be acceptable (it IS a true divergence), but could fire spuriously during
development. The correct approach is to compute the check as
`abs(actual - marker) > max(1, tolerance * marker)` — an absolute floor of 1
row prevents constant noise on micro-corpora. Add this floor to the
implementation.

### FM-5: Gauge going stale — re-ingestion while server runs

**Trigger:** operator runs `make ingest` while the server is live. A new
corpus version is written to LanceDB. The server still serves the old
pinned version (by design: "restart the process to pick up a new corpus" —
`server/resources.py:14`). `startup_chunk_count` reflects the OLD version.

**Observable symptom:** `arxmcp_corpus_chunk_count_actual` reads the old
count. After ingest, the true table row count is higher, but the gauge does not
update. This is EXPECTED and intentional per the brief's "startup-cached,
never recomputed" design.

**Known limitation to document in code:** the gauges are process-lifetime
snapshots. Add a code comment in the startup block: "Stale by design: the
server serves a pinned corpus version for its full lifetime. Restart to
refresh. See corpus-integrity-observability-m2 brief."

### FM-6: Divergence direction — rows LOST vs. rows ADDED

**Trigger A (rows lost):** disk corruption, partial write, or a bug deleting
fragments. `actual < marker`.

**Trigger B (rows added):** concurrent ingest wrote a newer version to the
same LanceDB while the server is starting (rare on single-user workstation, but
structurally possible). `actual > marker`.

**Argument:** BOTH directions should degrade. Rows lost is clearly bad
(retrieval is incomplete). Rows added is also anomalous — it means the corpus
changed between marker write and server startup, which should not happen on this
project's single-writer model. An operator should know about it.

**Recommendation:** use `abs(actual - marker)` for the threshold check
(symmetric). Log the direction explicitly in the WARN message:
`"actual=%d marker=%d direction=%s"` where direction is `"rows_lost"` or
`"rows_added"`.

### FM-7: `DegradedState` already set for corpus_corruption before m2 runs

**Trigger:** `open_chunks_table_with_fallback` activates the N-1 fallback at
startup (existing E14_S05 logic, `server/resources.py:355-375`).
`degraded` is already set to `DegradedState(reason="corpus_corruption", ...)`.

**Risk:** m2's reconciliation check runs AFTER LanceDB open. If
`corpus_corruption` degraded state is already set, m2 should NOT clobber it
with `chunk_count_diverged`. A corpus that already activated the N-1 fallback
is more seriously degraded; `corpus_corruption` must win.

**Recommendation:** check `if degraded is not None: skip reconciliation` (or
at minimum `if degraded is not None: do not overwrite reason`). The
reconciliation is meaningful only on the happy path where the table opened
cleanly. When fallback is active, the count may legitimately differ (fallback
version has a different row count). Log at INFO: "skipping chunk_count
reconciliation: corpus_corruption fallback is active."

---

## Prior decisions and lessons

- **m1 just shipped** (state: complete). The write-time fix is the dependency.
  The test pattern from m1 used `write_chunks()` with synthetic `ChunkRecord`s;
  m2 tests should follow the same synthetic LanceDB seeding pattern.
- **`assert` is banned** for invariants (CLAUDE.md §4.7). Use
  `if count < 0: raise RuntimeError(...)` if any invariant check is needed.
- **`BaseHTTPMiddleware` is banned.** The new code in `Resources.startup` and
  `server/health.py` is not middleware — no risk here.
- **No `anthropic` SDK at runtime** in `server/`. No risk — this is pure
  arithmetic + Prometheus.
- **`refresh_metrics_from_singleton_state` is called at EVERY scrape** (it is
  hooked into the `/metrics` ASGI app request handler per `server/health.py`
  docstring). The chunk-count gauges must read the cached `int` field, not
  re-call `count_rows()`. Confirmed safe.
- **`KMP_DUPLICATE_LIB_OK=TRUE`** in `tests/conftest.py` is untouched by this
  milestone.
- **E13_S01 doc-placement pattern:** any new docs go under `.claude/docs/`, not
  `server/` or `docs/`.

---

## Recommendation

**Implement as follows:**

1. Add `startup_chunk_count: int = -1` field to `Resources` dataclass
   (`server/resources.py`).

2. In `Resources.startup()`, after step 2 (LanceDB open), before BM25:
   ```python
   try:
       actual_count = await loop.run_in_executor(None, chunks_table.count_rows)
   except Exception as exc:
       logger.warning("startup: count_rows() failed (%s); skipping reconciliation", exc)
       actual_count = -1
   ```

3. When `actual_count >= 0` and `degraded is None` (no prior corpus_corruption):
   - Compute divergence with `abs(actual - marker) > max(1, tolerance * marker)`,
     division-by-zero guarded.
   - On divergence: `logger.warning(...)`, set `degraded = DegradedState(
     reason="chunk_count_diverged", fallback_version=version, original_version=version)`.

4. Set `instance.startup_chunk_count = actual_count` on the constructed
   `Resources` instance.

5. Add two `Gauge` objects in `server/health.py` alongside `CORPUS_VERSION_GAUGE`:
   `CORPUS_CHUNK_COUNT_MARKER` and `CORPUS_CHUNK_COUNT_ACTUAL` (no labels).

6. In `refresh_metrics_from_singleton_state`: add two O(1) `.set()` calls
   reading `resources.startup_chunk_count` and `resources.corpus_info.chunk_count`.

7. Add `"chunk_count_diverged"` to the reason enumeration in
   `refresh_degraded_mode_metric` (`server/health.py:636-640`).

8. Expose `CORPUS_CHUNK_COUNT_TOLERANCE` as a `Config` field
   (`ARXMCP_CORPUS_CHUNK_COUNT_TOLERANCE`, default `0.05`), so operators can
   widen/narrow for large-corpus deployments.

**Why this approach:** it minimizes blast radius (only `Resources.startup`,
`server/health.py`, and `server/config.py` change), preserves all invariants,
and handles all 7 failure modes without introducing new crash paths.

---

## Open questions

No open questions — implementation can proceed on the above recommendation.

The tolerance config field name (`ARXMCP_CORPUS_CHUNK_COUNT_TOLERANCE`) is a
recommendation; the brief says "configurable" so any `ARXMCP_` env-var name is
fine. The implementer should pick a name and document it in `server/config.py`.

---

## External writes the implementation will require

None — this milestone is purely local.
