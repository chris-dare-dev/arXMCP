# Research Synthesis — corpus-integrity-observability-m2

**Merged from:** research-brief-1.md (in-codebase seam map) + research-brief-2.md
(failure modes). **Generated:** 2026-05-28.
**Verdict:** INLINE, ~50–70 LOC across `server/config.py` + `server/resources.py` +
`server/health.py` + tests. Purely local. Depends on m1 (shipped `8e58c42`).

## 1. The locked design

At `Resources.startup()`, after the LanceDB table is open (step 2) and BEFORE the
BM25 full-table scan (step 4b, `resources.py:407-409`), compute `count_rows()` ONCE,
cache it on a new `Resources.startup_chunk_count: int` field, reconcile it against
the marker's `chunk_count`, and expose both via two scalar Prometheus gauges set
from the cached value. WARN-and-serve: divergence sets `Resources.degraded` but
never aborts startup or affects retrieval.

Both briefs independently converged on this and on "no `/readyz` handler change
needed — reuse the existing `resources.degraded` path." The only changed files are
`server/config.py`, `server/resources.py`, `server/health.py` (+ tests). No new file.

## 2. Load-bearing facts (quoted, both briefs concur)

- **`DegradedState` is a frozen 3-field dataclass** (`server/corpus.py:109-137`):
  `reason: str`, `fallback_version: int`, `original_version: int`. `reason` is a
  plain `str` — `"chunk_count_diverged"` is a NEW value, **NOT a schema change**.
  Existing values: `"corpus_corruption"`, `"hosted_embedder_outage"`.
- **`Resources.degraded: DegradedState | None`** (`resources.py:280-285`) is already
  the field `/readyz` reads. Setting it to a `chunk_count_diverged` state requires
  ZERO handler routing change — the `/readyz` degraded path (`health.py:199-217`)
  already serializes `reason` / `fallback_version` / `original_version`.
- **`/readyz` + `/metrics` are operational HTTP endpoints, NOT MCP surface.** `ALL_TOOLS`
  is untouched. `EXPECTED_TOOL_SCHEMA_SHA256` + `EXPECTED_BP1_SHA256` stay FROZEN
  (X-gate AC). No MCP-spec consultation needed.
- **`refresh_degraded_mode_metric` (`health.py:625-642`)** hardcodes a zero-out loop
  over `("corpus_corruption", "hosted_embedder_outage")`. The implementer MUST add
  `"chunk_count_diverged"` to this tuple (both briefs flag this — without it the
  per-reason gauge label is never zeroed; benign on restart since the registry
  re-inits, but required for correctness + documentation).
- **`CORPUS_VERSION_GAUGE` pattern (`health.py:92-97`)** is the exact template for the
  two NEW scalar (unlabeled) gauges `arxmcp_corpus_chunk_count_marker` +
  `arxmcp_corpus_chunk_count_actual`. They live in `server/health.py` (NOT
  `server/observability/metrics.py`) to sit beside `CORPUS_VERSION_GAUGE`.
- **`refresh_metrics_from_singleton_state` (`health.py:237-298`)** is called at
  startup (`main.py:311`) AND on every `/metrics` scrape (`main.py:633`). The two new
  gauges are `.set()` from the cached `int` field here — O(1) reads, NO `count_rows()`
  at scrape time. This is the mechanism that satisfies "never recomputed per scrape."
- **prometheus_client 0.25.0** (uv.lock): `Gauge.set(v)` stores an atomic float;
  `generate_latest()` reads the stored value — no recomputation, no user-function
  call on scrape (that's only `set_function()` gauges). Brief-2 verified empirically.
  Plain gauge names (no `_total`) are correct.
- **`count_rows()` is synchronous I/O** (brief-1, load-bearing) — wrap in
  `await loop.run_in_executor(None, chunks_table.count_rows)` exactly like the step-2
  LanceDB open, so the event loop is not blocked.
- **m1 dependency satisfied:** marker `chunk_count == tbl.count_rows()` after a write
  (commit `8e58c42`). A startup divergence now genuinely signals a post-write
  corruption event, not a pre-existing off-by-one.

## 3. Divergences resolved (orchestrator synthesis note)

**D1 — cached field name + sentinel.** brief-1: `cached_chunk_count: int | None = None`;
brief-2: `startup_chunk_count: int = -1`. **RESOLVED → `startup_chunk_count: int = -1`
(brief-2).** Reason: the gauge needs a numeric value always (Prometheus can't report
`None`), and `-1` doubles as the FM-2 "count unavailable" sentinel that the gauge can
surface (`-1.0`) for operators. `int | None` would force a `None`→number coercion at
the gauge anyway.

**D2 — `fallback_version` / `original_version` in the count-diverged DegradedState.**
brief-1: `0` sentinel; brief-2: `corpus_info.version` for both. **RESOLVED → use
`corpus_info.version` for both (brief-2).** Reason: the `/readyz` body then shows the
real pinned version rather than a confusing `0`; no actual fallback occurred so
`fallback == original == current version` is the honest representation. Document in a
comment that these fields carry corpus-corruption semantics and are N/A here.

**D3 — divergence formula.** brief-1: `|actual - marker| / max(actual,1) > tolerance`;
brief-2: `abs(actual - marker) > max(1, tolerance * marker)` with a `marker==0` guard
and a 1-row absolute floor. **RESOLVED → brief-2's formula:**
```python
if marker <= 0:
    diverged = actual > 0          # FM-3: no div-by-zero; 0/0 is NOT divergence
else:
    diverged = abs(actual - marker) > max(1, tolerance * marker)  # FM-4: 1-row floor
```
Reason: handles the empty-corpus div-by-zero (FM-3), the small-corpus single-row-noise
floor (FM-4), and is SYMMETRIC over direction (FM-6 — both rows-lost and rows-added
degrade; log the direction in the WARN). brief-1's formula div-by-zeros on `actual==0`
and lacks the floor.

## 4. Failure modes baked into the design (brief-2, the primary deliverable)

- **FM-1 marker missing (cold bootstrap) — non-issue.** `Resources.startup` raises
  `CorpusNotIngestedError` at `resources.py:329-336` BEFORE m2's code runs. No false
  `chunk_count_diverged` on a fresh corpus.
- **FM-2 `count_rows()` raises — RESOLVED by try/except.** Wrap the call; on exception
  log WARN, set `startup_chunk_count = -1`, SKIP reconciliation (divergence undefined),
  do NOT set degraded. Gauges report `-1.0` so operators see the count-miss. Startup
  proceeds (retrieval unaffected).
- **FM-3 both counts 0 — RESOLVED** by the `marker <= 0` guard (no divergence).
- **FM-4 tiny-corpus single-row noise — RESOLVED** by the `max(1, tolerance*marker)`
  floor.
- **FM-5 gauge staleness (re-ingest while live) — ACCEPTED + documented.** The server
  serves a pinned corpus version for its lifetime by design (`resources.py:14`); the
  gauges are process-lifetime snapshots. Add a code comment: "Stale by design; restart
  to refresh." This IS the brief's "startup-cached, never recomputed" contract.
- **FM-6 divergence direction — RESOLVED** by symmetric `abs()` + a `direction=` field
  (`rows_lost` / `rows_added`) in the WARN message.
- **FM-7 DegradedState clobber (TOP RISK, brief-2) — RESOLVED by an ordering guard.**
  If `open_chunks_table_with_fallback` already set `degraded =
  DegradedState(reason="corpus_corruption", ...)`, m2 MUST NOT overwrite it —
  corpus_corruption is more severe and wins. Run reconciliation ONLY when
  `degraded is None`; otherwise log INFO "skipping chunk_count reconciliation:
  <reason> fallback active." (The gauges are still set from the cached count either
  way.)

## 5. Acceptance criteria (from roadmap m2)

1. **Divergence > tolerance ⇒ WARN + degraded.** Given a marker whose `chunk_count`
   diverges from the live table by > tolerance, when the server starts, then it logs a
   WARN with both values (and direction) AND `/readyz` reports `degraded` with
   `reason="chunk_count_diverged"`.
2. **Matching counts ⇒ clean.** Given matching counts, when the server starts, then no
   WARN, not degraded, and the two gauges are equal.
3. **Single cached count, never per scrape.** Both gauges are set once at startup from
   a single cached `count_rows()`; a test asserts `count_rows()` is called AT MOST ONCE
   across startup + a `/metrics` scrape (mock the table's `count_rows`, assert
   `call_count == 1`).
4. **X-gates.** `EXPECTED_TOOL_SCHEMA_SHA256` + `EXPECTED_BP1_SHA256` UNCHANGED;
   `make test` green. (No tool surface change.)

Plus regression coverage for the failure modes that are reachable on common paths:
FM-7 (corpus_corruption wins — degraded NOT clobbered), FM-3 (0/0 ⇒ not degraded),
and FM-6 direction labeling.

## 6. Implementation plan (INLINE)

1. **`server/config.py`** — add `corpus_chunk_count_tolerance: float = 0.05` with a
   `@field_validator` enforcing `[0.0, 1.0]` (mirror the `eq_ted_weight` validator at
   `config.py:132-137`). Env var `ARXMCP_CORPUS_CHUNK_COUNT_TOLERANCE`.
2. **`server/resources.py`** — add `startup_chunk_count: int = -1` to the `Resources`
   dataclass. In `startup()`, after step-2 LanceDB open and before the BM25 scan:
   try/except `count_rows()` via `run_in_executor` → cache on the field; then, only if
   `degraded is None` and count ≥ 0, run the D3 divergence check → WARN (with direction)
   + set `degraded = DegradedState(reason="chunk_count_diverged",
   fallback_version=version, original_version=version)`. Comment the FM-5 staleness +
   FM-7 ordering + D2 sentinel semantics.
3. **`server/health.py`** — add `CORPUS_CHUNK_COUNT_MARKER` + `CORPUS_CHUNK_COUNT_ACTUAL`
   scalar gauges beside `CORPUS_VERSION_GAUGE`; in `refresh_metrics_from_singleton_state`
   set them from `resources.corpus_info.chunk_count` + `resources.startup_chunk_count`
   (O(1), no I/O); add `"chunk_count_diverged"` to the zero-out tuple in
   `refresh_degraded_mode_metric`.
4. **Tests** — `tests/` (likely `test_health.py` / `test_resources.py` or a new
   `test_corpus_reconciliation.py`): AC-1 (diverged ⇒ degraded + WARN via `caplog`),
   AC-2 (matching ⇒ clean + equal gauges), AC-3 (`count_rows` call_count == 1 across
   startup + scrape), FM-7 (corpus_corruption not clobbered), FM-3 (0/0 clean).
   `assert` is fine in tests; banned for invariants in `server/` (use
   `if … raise RuntimeError`).

## 7. Open questions

**None** — both briefs independently reported "no open questions." Field/env-var names
are recommendations; the implementer picks and documents them.

## 8. External writes required

**None** — purely local (`server/config.py`, `server/resources.py`, `server/health.py`
+ tests). No git push, PR, infra, or third-party API. (Both briefs concur.)
