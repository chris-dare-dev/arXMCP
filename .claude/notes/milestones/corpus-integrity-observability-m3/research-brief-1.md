# Research Brief — corpus-integrity-observability-m3

**Agent:** milestone-researcher (brief-1)
**Generated:** 2026-05-29T18:30:00Z

## In-codebase context

### Design notes that apply

- `05-storage-and-indexing.md` — defines the two HNSW indexes: "HNSW on `embedding_stmt`
  (M=16, efConstruction=200). HNSW on `embedding_proof` (M=16, efConstruction=200)."
- `07-multi-agent-caching.md` — confirms tool definitions must remain byte-stable; this
  milestone adds NO tool surface changes (operational endpoint only). No BP1 impact.
- `08-security-observability-ops.md` — metrics convention: "Prometheus exposition format
  on `/metrics`"; plain `gauge` names (no `_total`).

### ingest/store.py — `_create_indices` (lines 563–633)

The two HNSW indexes are built by `_create_indices(tbl)`. Their **canonical names as
assigned by lancedb 0.30.2** are:
- `"embedding_stmt_idx"` (column `embedding_stmt`, index_type `IvfHnswSq`)
- `"embedding_proof_idx"` (column `embedding_proof`, index_type `IvfHnswSq`)

**Verified empirically** against lancedb 0.30.2 installed at `.venv/`: lancedb auto-names
the index `<column_name>_idx` when no explicit name is passed to `create_index`. The
`_create_indices` code does NOT pass a `name=` kwarg, so the name is always derived from
the column name.

The relevant verbatim code at `ingest/store.py:618–626`:

```python
        tbl.create_index(
            vector_column_name=column,
            index_type="IVF_HNSW_SQ",
            num_partitions=1,
            m=16,
            ef_construction=200,
            replace=True,
        )
```

Note: despite the `_create_indices` docstring using names `"hnsw_stmt"` / `"hnsw_proof"`,
the actual registered index names are `"embedding_stmt_idx"` / `"embedding_proof_idx"`.
The milestone brief correctly says to discover names via `tbl.list_indices()` — do NOT
hardcode.

### LanceDB 0.30.2 index API (live-verified)

**Version pin:** `lancedb>=0.6` in `pyproject.toml`; resolved to `0.30.2` in `uv.lock`.

**`tbl.list_indices()` → `list[IndexConfig]`**

Each `IndexConfig` has three attributes: `.name: str`, `.columns: list[str]`,
`.index_type: str` (e.g. `"IvfHnswSq"`). Only ANN/vector indexes are returned (scalar
indexes are NOT).

**`tbl.index_stats(index_name: str)` → `IndexStatistics`**

`IndexStatistics` attributes (live-verified): `num_indexed_rows`, `num_unindexed_rows`,
`index_type`, `distance_type`, `num_indices`, `loss`.

**`num_unindexed_rows` semantics (empirically confirmed):**

- After `_create_indices`: `num_unindexed_rows == 0`
- After `tbl.add(new_rows)` WITHOUT re-indexing: `num_unindexed_rows == len(new_rows)`

This confirms the brief's assertion: in normal arXMCP operation `num_unindexed_rows == 0`
(pure tripwire), and non-zero means partial write or corruption.

**API pattern the implementer must use:**

```python
indices = tbl.list_indices()          # list[IndexConfig]
for idx in indices:
    stats = tbl.index_stats(idx.name) # IndexStatistics
    # stats.num_unindexed_rows is the field
```

### server/resources.py — the m2 pattern to mirror

**`Resources` dataclass field (current, line 331):**
```python
    startup_chunk_count: int = -1
```

**m2 block insertion point (lines 424–483):** after `open_chunks_table_with_fallback`
(step 2, lines 401–422) and BEFORE step 3 BGE-M3 load (line 485). The m3 block should go
**immediately after the m2 block ends** (line 483), before step 3.

**m2 count_rows block (lines 439–441) — exact template for m3 try/except:**
```python
            startup_chunk_count = await loop.run_in_executor(
                None, chunks_table.count_rows
            )
```

**FM-7 guard (lines 451–456) — exact template for m3 `degraded is not None` skip:**
```python
        if degraded is not None:
            logger.info(
                "Resources.startup: skipping chunk_count reconciliation "
                "(degraded=%s already active — more severe).",
                degraded.reason,
            )
```

**`cls(...)` constructor call (lines 766–785):** `startup_chunk_count=startup_chunk_count`
is already in the call. The m3 field `startup_unindexed_rows=startup_unindexed_rows` must
be added here.

### server/health.py — the m2 gauge pattern to mirror

**Gauge placement (lines 100–120):** `CORPUS_CHUNK_COUNT_MARKER` and
`CORPUS_CHUNK_COUNT_ACTUAL` are scalar unlabeled `Gauge` objects beside
`CORPUS_VERSION_GAUGE` (line 93). The m3 gauge `CORPUS_UNINDEXED_ROWS` must go in the
same block in `server/health.py` (NOT `server/metrics.py`). Rationale: this is a
startup-set corpus health gauge, same as the m2 gauges. The sentinel gauges in
`server/metrics.py` are scrape-time/OAI-sentinel-bridged; this is not.

**`refresh_metrics_from_singleton_state` (lines 495–565):** m2 writes gauges at lines
518–519:
```python
    CORPUS_CHUNK_COUNT_MARKER.set(resources.corpus_info.chunk_count)
    CORPUS_CHUNK_COUNT_ACTUAL.set(resources.startup_chunk_count)
```
The m3 gauge set call goes immediately after line 519:
```python
    CORPUS_UNINDEXED_ROWS.set(resources.startup_unindexed_rows)
```

**`refresh_degraded_mode_metric` (lines 943–965):** The current zero-out tuple at
lines 958–962:
```python
        for reason in (
            "corpus_corruption",
            "hosted_embedder_outage",
            "chunk_count_diverged",
        ):
```

**If m3 does NOT introduce a new DegradedState reason (recommended — see below), this
tuple is unchanged.** Only add a new reason if the design resolves to "flip /readyz".

### Key constraint from CLAUDE.md §4.7 (banned patterns)

> "`assert` is BANNED for invariants — Python `-O` strips them. Use `if … raise
> RuntimeError(…)` instead."

The m3 implementation uses `try/except` with WARN-and-continue, so no `assert` risk.

### metrics_sample.txt regeneration requirement (LOAD-BEARING)

`tests/test_daily_metrics_report.py` line 371 checks `tests/fixtures/metrics_sample.txt`
against the output of `tools/regen_metrics_fixture.py`. Adding a new gauge family to
`server/health.py` **will cause this test to fail** unless the fixture is regenerated:

```bash
uv run python -m tools.regen_metrics_fixture
```

This bit e2 and e3. The implementer must regenerate the fixture after adding the new gauge.

## Prior decisions and lessons

### m2 implementation-summary.md key patterns to carry forward

1. **`startup_chunk_count: int = -1` field** — use `-1` as sentinel (not `None`) because
   Prometheus needs a numeric value always. Replicate with `startup_unindexed_rows: int = -1`.

2. **Defensive `getattr` in `refresh_metrics_from_singleton_state`** — m2 added getattr
   for gauge reads on partial/duck-typed Resources (test fake that omits the field).
   Add the same for `startup_unindexed_rows`.

3. **`count_rows()` is sync I/O → `run_in_executor`** — `index_stats()` is also sync
   (lancedb 0.30.2 uses a background event loop internally but the Python API is
   synchronous). Use `loop.run_in_executor(None, ...)` for the `list_indices()` +
   `index_stats()` calls. Since these are sequential (loop over indices), wrap the
   whole block in a single sync helper or a lambda.

4. **`EXPECTED_TOOL_SCHEMA_SHA256` and `EXPECTED_BP1_SHA256` are unaffected** — m3
   touches `/metrics` only (an operational HTTP endpoint), not any MCP tool definition
   or `server/prompts.py`. Both hashes stay frozen. Confirmed.

5. **Recent git log** (top 3 relevant): `18a4733` (corpus-integrity-observability-e3
   complete), `e01dee7` (e3 rectification). The e2 and e3 milestones preceded m2 and m3
   in the corpus-integrity series; m2 shipped the count_rows reconciliation. m3 is the
   next step.

### From MEMORY.md (auto-injected)

The `prometheus-gauge-set-not-recomputed` entry confirms: `Gauge.set(value)` stores an
atomic; `generate_latest()` reads it at scrape time — no recomputation. `set_function()`
is the recompute-on-scrape variant. The m3 gauge must use plain `.set()`, not
`.set_function()`.

The `sentinel-gauge-placement-rule` entry confirms startup-set gauges live in
`server/health.py`; scrape-time sentinel-bridged gauges in `server/metrics.py`.

### Scout CAND-10 (challenge.md ~line 398) key quote

> "v0: Use `tbl.list_indices()` to discover active index names, then call `index_stats()`
> for each. Wrap in a try/except that logs a WARNING on unknown index names but does not
> fail startup. The gauge value defaults to 0 if `index_stats()` is unavailable."

This is the prescribed approach; it resolves the hardcoded-names fragility.

**No conflicts between the milestone brief and the codebase were found.**

## External sources

This milestone does not touch the MCP server tool surface or prompt-cache schema; no
MCP spec consultation is needed. No Anthropic prompt-caching docs are relevant. The
lancedb API was verified directly against the installed package (0.30.2) rather than
external docs.

## Recommendation

**Mirror m2 exactly, with the following concrete design:**

1. **`server/resources.py`** — add `startup_unindexed_rows: int = -1` to the `Resources`
   dataclass (beside `startup_chunk_count` at line 331). Insert a step-2c block immediately
   after the m2 block (after line 483, before step 3 at line 485):

   ```python
   # 2c. HNSW unindexed-rows tripwire (corpus-integrity-observability-m3).
   # Discover index names via list_indices() (NOT hardcoded — challenge Axis 8).
   # Call index_stats() per index, sum num_unindexed_rows. Non-zero is ALWAYS
   # abnormal in normal operation (_create_indices runs synchronously in write_chunks).
   # FM-2 style: try/except → -1 sentinel + WARN, NEVER fail startup.
   # FM-7: skip entirely when degraded already set.
   if degraded is not None:
       startup_unindexed_rows = -1
       logger.info("Resources.startup: skipping unindexed-rows check (degraded=%s).",
                   degraded.reason)
   else:
       try:
           def _count_unindexed(tbl):
               total = 0
               for idx in tbl.list_indices():
                   stats = tbl.index_stats(idx.name)
                   total += stats.num_unindexed_rows
               return total
           startup_unindexed_rows = await loop.run_in_executor(
               None, _count_unindexed, chunks_table)
           if startup_unindexed_rows > 0:
               logger.warning(
                   "Resources.startup: %d unindexed HNSW rows detected — "
                   "ANN queries will brute-force over these rows. Non-zero is "
                   "ALWAYS abnormal (partial write or corruption). "
                   "Re-run ingest to rebuild the index.",
                   startup_unindexed_rows,
               )
       except Exception as exc:  # noqa: BLE001 — non-fatal observability
           logger.warning(
               "Resources.startup: index_stats() unavailable (%s); "
               "skipping unindexed-rows check. Retrieval is unaffected.", exc)
           startup_unindexed_rows = -1
   ```

   Add `startup_unindexed_rows=startup_unindexed_rows` to the `cls(...)` call at line 784.

2. **`server/health.py`** — add a single scalar gauge after `CORPUS_CHUNK_COUNT_ACTUAL`
   (line 120):

   ```python
   CORPUS_UNINDEXED_ROWS = Gauge(
       "arxmcp_corpus_unindexed_rows",
       "Total HNSW unindexed rows across all ANN indexes, read once at startup. "
       "-1 = check unavailable (index_stats() raised). 0 = fully indexed (normal). "
       "Non-zero is always abnormal; re-run ingest to rebuild.",
   )
   ```

   In `refresh_metrics_from_singleton_state` (line 519), add after the m2 gauge sets:
   ```python
   CORPUS_UNINDEXED_ROWS.set(getattr(resources, "startup_unindexed_rows", -1))
   ```
   Use `getattr`-defended (not direct access) for consistency with the existing
   duck-typed `Resources` test-fake pattern (m2 implementation-summary deviation note).

3. **Do NOT flip `/readyz` to degraded on non-zero unindexed rows.** Brute-force ANN
   serves CORRECT results (just slower) — this is a performance, not a correctness,
   degradation. WARN + gauge is sufficient. The `refresh_degraded_mode_metric` zero-out
   tuple at line 958 is unchanged (no new reason string added).

4. **Regenerate `tests/fixtures/metrics_sample.txt`** after adding the gauge:
   `uv run python -m tools.regen_metrics_fixture`. This is MANDATORY — the fixture
   test will fail otherwise.

5. **No new config.py toggle needed.** The guard is always-on (like the m2 count_rows
   reconciliation). No operator opt-in/opt-out knob for a tripwire.

## Open questions

No open questions — implementation can proceed on the above recommendation.

The one "open design question" in the brief (degrade `/readyz` or not) is resolved:
WARN + gauge only, NOT degraded. Rationale: brute-force ANN is correct-but-slower, not
a corpus-correctness failure. The m2 precedent for degraded was chunk_count divergence
(correctness concern — the marker disagrees with the table, indicating actual data loss
or corruption). Unindexed rows have no correctness impact, only latency.

## External writes the implementation will require

None — this milestone is purely local. No git push, PR creation, infra mutation, or
third-party API call required. (Confirmed in state.json `external_writes_required: []`.)
