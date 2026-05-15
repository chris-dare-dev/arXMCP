# E11_S04 Research Brief 1 — Codebase Mechanics

**Axis:** In-codebase mechanics (Researcher 1 of 2)
**Milestone:** E11_S04 — Drift watchdog: per-corpus-version nDCG@5 regression alert
**Date:** 2026-05-15

---

## 1. In-codebase context

### 1.1 Existing eval harness — `tests/eval/test_retrieval_quality.py`

The harness is a single pytest function:

```python
@pytest.mark.eval
def test_retrieval_quality(
    ndcg_min: float,
    hybrid: bool,
    rerank: bool,
) -> None:
```

It is NOT a standalone callable — it is pytest-native: it reads
fixtures from pytest conftest/conftest `--ndcg-min`, `--hybrid`,
`--rerank` CLI flags. It dispatches to two internal helpers:

- `_run_queries_against_corpus(queries, tbl, encode_query)` — dense-only ANN path
- `_run_hybrid_against_corpus(queries, tbl, encode_query, *, corpus_version, rerank_enabled)` — full 3-phase: BM25 → ANN+RRF → optional rerank, using `Resources.startup(cfg)`

Both helpers return `list[dict]` (`per_query_rows`). The aggregate
is computed and written by the factored-out function:

```python
def score_and_write(
    per_query_rows: list[dict],
    corpus_version: int,
    ndcg_min: float,
    output_dir: Path,
    *,
    assert_latency_p95: bool = False,
) -> None:
```

`score_and_write` writes two files:
- `var/arxmcp/ops/eval/results-<corpus_version>.jsonl` — per-query rows
- `var/arxmcp/ops/eval/aggregate-<corpus_version>.json` — `{corpus_version, ndcg5_mean, query_count, recall10_mean, timestamp}`

The module docstring explicitly designates `aggregate-<v>.json` as
"the drift-detection baseline that E11_S04's watchdog will compare
against on a schedule." The `metrics.py` module docstring carries a
`TODO(E11_S04)` noting it is the first non-test consumer of
`ndcg_at_k` and `recall_at_k`.

**Key insight:** `score_and_write` is pure Python — no pytest
dependency. The watchdog can call it directly in-process. It does
NOT need to shell out to pytest.

**Cold-start skip matrix** (from the test module docstring):

| `read_corpus_version()` | `len(queries)` | Behavior |
|---|---|---|
| `None` | 0 | `pytest.skip("both pending")` |
| `None` | 20 | `pytest.skip("corpus not ingested")` |
| `CorpusVersionInfo` | 0 | `pytest.skip("queries not curated")` |
| `CorpusVersionInfo` | 20 | RUN |

The watchdog inherits this matrix: it cannot run when either the
corpus or the fixture is absent.

### 1.2 `tests/eval/fixtures/queries.json` — current state

```json
{
  "schema_version": "1.0",
  "chunker_version": "v1.0",
  "created_at": "2026-05-08",
  "queries": []
}
```

**Zero queries.** Per CLAUDE.md §7: "eval fixture...still being
hand-labeled." The curation runbook (`eval-curation.md`) requires a
human researcher; automation is explicitly disallowed. This is the
dominant landmine — see §A below.

### 1.3 Retrieval pipeline public entry points

From `tests/eval/test_retrieval_quality.py::_run_hybrid_against_corpus`:

The hybrid path uses `server.resources.Resources` — instantiated as
`resources = await Resources.startup(cfg)` — then calls:

```python
bm25_candidates, _ = resources.bm25_phase.query(query_text, top_n=200)
fused = await resources.ann_phase.query(query_text, bm25_candidates, top_n=50)
ranked = await resources.rerank_phase.rerank(query_text, query_vec, fused, top_k=10)
```

The watchdog can replicate this pattern exactly — `Resources.startup`
is the programmatic entry point. No pytest subprocess needed.

`server.config.Config` controls `enable_rerank: bool = False` via
`ARXMCP_ENABLE_RERANK` (env prefix `ARXMCP_`). The reranker also
requires `ARXMCP_RUN_REAL_BGE_RERANKER=1` env at test time (per
`test_retrieval_quality.py:202`).

### 1.4 `server/metrics.py` — existing pattern for a new gauge

Current gauges:

```python
CACHE_BYTES_GAUGE: Gauge = Gauge(
    "arxmcp_cache_bytes",
    "Approximate byte usage per cache tier. ...",
    labelnames=["tier"],
)
```

The `LATEXML_DRIFT_DETECTED_COUNTER` is the closest analogue to the
new `arxmcp_eval_ndcg5` — a metric incremented by a one-shot cron
process with exposure to `/metrics` deferred until the server reads
a sentinel file (per the F8 note in `server/metrics.py`:
"production exposure deferred to E14"). The pattern is:

1. Define `EVAL_NDCG5_GAUGE: Gauge = Gauge("arxmcp_eval_ndcg5", ..., labelnames=["corpus_version"])`
2. The watchdog script sets it in its own process — the metric is
   present only during watchdog execution.
3. The server exposes it at `/metrics` only if it reads the JSON
   report at scrape time (see §E below — this is the cross-process
   metric-exposure problem).

### 1.5 `server/corpus.py` — opening the STAGING LanceDB

`open_chunks_table` signature:

```python
def open_chunks_table(
    lancedb_path: str | Path | None = None,
    version: int | None = None,
) -> lancedb.table.Table:
```

Pass `lancedb_path=DEFAULT_LANCEDB_STAGING_PATH` and `version=None`
to open the staging dataset's live tip (what was just written by
`oai_delta` or `re_embed`). Pass an explicit `version=N` to pin
to a specific staging version. The watchdog should use `version=None`
(staging tip) since the staging `corpus-version.json` holds the
post-write version integer.

**Critical:** the staging path `var/arxmcp/index/lancedb-staging/`
has its OWN `corpus-version.json` written by `write_chunks` after
every per-paper write. The watchdog reads the staging
`corpus-version.json` via:

```python
read_corpus_version(lancedb_path=DEFAULT_LANCEDB_STAGING_PATH)
```

The active `var/arxmcp/index/lancedb/corpus-version.json` is never
touched during the watchdog run.

### 1.6 `ingest/store.py` — DEFAULT_LANCEDB_PATH and staging

```python
DEFAULT_LANCEDB_PATH = REPO_ROOT / "var" / "arxmcp" / "index" / "lancedb"
CORPUS_VERSION_MARKER_NAME = "corpus-version.json"
```

The staging path is defined in `ingest/bulk_ingest.py`:

```python
DEFAULT_LANCEDB_STAGING_PATH = (
    REPO_ROOT / "var" / "arxmcp" / "index" / "lancedb-staging"
)
```

### 1.7 `ingest/oai_delta.py` — watchdog integration point

The delta loop writes to `lancedb-staging/` via `ingest_one_paper`.
The `corpus-version.json` under `lancedb-staging/` is updated after
every per-paper write. After the delta loop finishes all papers
(or fails), there is no explicit "corpus version finalized" hook.

**Where the watchdog hooks in:** The cron script
`ops/cron/arxmcp-delta.sh` calls `python -m ingest.oai_delta`. The
watchdog should be called from a wrapper script AFTER `oai_delta`
exits 0. The delta loop does NOT call the watchdog internally (that
would be a circular dependency: `oai_delta` should not import
`ops/watchdog_eval`).

The natural integration:

```bash
# ops/cron/arxmcp-delta.sh (extended):
exec flock -n "${LOCK_PATH}" bash -c "
  ${UV_BIN} run python -m ingest.oai_delta "$@" &&
  ${UV_BIN} run python -m ops.watchdog_eval --staging
"
```

OR: a separate nightly timer step after `oai_delta.timer` completes.

### 1.8 `ingest/re_embed.py` — re-embed sentinel

`re_embed.py` writes `RE_EMBED_PROGRESS_NAME = "re-embed-progress.json"`
to the staging path with `status="complete"` when finished. The
watchdog does NOT need to read this sentinel — it runs against the
staging `corpus-version.json`, which is the source of truth for
"what version is in staging." The re-embed progress file is consumed
by E11_S05 (cutover gate), not by the watchdog.

However, the watchdog SHOULD check that staging has a valid
`corpus-version.json` before running, since `write_chunks` could
fail and leave staging in a half-written state.

### 1.9 `TIER-GATES.md` — Tier-5 cutover

The Tier-5 cutover gate (from `.claude/TIER-GATES.md`) is:

> **Drift watchdog stable:** the latest scheduled nDCG@5 measurement
> (per E11_S04's drift watchdog) is within 5% of the previous
> baseline. "Within 5%" means
> `|aggregate.ndcg5_mean - prior.ndcg5_mean| / prior.ndcg5_mean <= 0.05`.

Note: the TIER-GATES document defines "within 5%" as a SYMMETRIC
absolute-value check, while the milestone brief defines it as a
relative REGRESSION (one-directional: decline only). The brief's
formulation is correct for an alert (we don't alert on improvement).
See §3 for math clarification.

### 1.10 E11 prior milestone artifacts relevant to watchdog

From git log:
- `8b3ad32 feat(ingest,ops): partial re-embed driver (E11_S03)` — ships `re_embed.py`
- `f043dab rect(ingest,ops): close 2 HIGH + 6 MEDIUM + 5 LOW from E11_S03 critique`
- `2e0bcdd rect(ingest,ops): close 2 CRITICAL + 4 HIGH + 6 MEDIUM from E11_S02 critique`

**E11_S02 IS2 pattern (--resume no-op):** The E11_S02 critique
flagged a `--resume` flag that was a no-op. The watchdog has no
`--resume` semantics — it is always idempotent: re-running against
the same corpus version overwrites the same JSON report file.

**E11_S01 F1 pattern (silent stale-embed reuse):** The E11_S01
critique flagged silent reuse of stale embeddings. The analogous
watchdog risk is **silent stale-metric reuse** — if the watchdog
crashes after writing a JSON report but before writing the quarantine
flag, a subsequent run sees the report already exists and skips
recomputation. Mitigation: always recompute; never skip based on
report-file existence (no memoization of watchdog results).

**E11_S03 F1 (O(N²) full-table-scan):** The re-embed driver had an
O(N²) bug — per-paper full-table-scan. The watchdog runs N queries
(N=20 today), not N papers. The asymptotic risk is trivially bounded.

---

## 2. Prior decisions and lessons

**From the retrieval quality test module docstring (line 38-39):**
> "The aggregate file is the drift-detection baseline for E11_S04."

This is the canonical baseline source. No other file serves this
role.

**From `server/metrics.py` (F8 on LATEXML_DRIFT_DETECTED_COUNTER):**
> "production exposure via the server's /metrics endpoint is deferred
> to E14 (observability/ops). The v1 operational signal is the cron
> job's non-zero exit + ERROR log + sentinel file."

This is the established pattern for one-shot-process metrics. E11_S04
should follow it exactly.

**From `.claude/docs/retrieval-quality-report.md` (status PRELIMINARY):**
All nDCG@5 numbers are PENDING — the 20-query fixture has never been
populated. The brief's AC1 ("nDCG@5 ≥ 0.80 against seed corpus")
is aspirational until the fixture is curated.

---

## 3. External sources — nDCG math

Järvelin & Kekäläinen 2002 plain form (as implemented in
`tests/eval/metrics.py`):

```
DCG@k = sum_{i=1}^{k} rel_i / log2(i+1)
nDCG@k = DCG@k / IDCG@k
```

**The brief's "> 5% RELATIVE regression" math:**

The brief says: "a 0.80 → 0.76 drop = 5% relative regression."
Check: `(0.80 - 0.76) / 0.80 = 0.05`. Correct.

Formal: alert triggers when
`(prev_ndcg5 - new_ndcg5) / prev_ndcg5 > threshold_pct / 100`.

Equivalently: `new_ndcg5 < prev_ndcg5 * (1 - threshold_pct / 100)`.

NOT `(new - old) / old < -0.05` (that's the same thing written
differently). NOT `abs(...) > 0.05` (which would also alert on
improvement). The TIER-GATES.md uses the symmetric form
(`|delta| / prior <= 0.05`) which is looser for the cutover gate
— the watchdog uses the one-directional form (decline only).

---

## 4. Critical landmines

### A. The eval fixture is a 0-query stub today

`queries.json` has `"queries": []`. The watchdog CANNOT detect
5% regression with 0 queries. With 4 queries it cannot either
(sampling variance dominates — one query's nDCG@5 can move ±0.25
from run to run due to corpus churn, swamping the 5% signal).

**Recommendation:** option (b) — run anyway but pass unconditionally
when fixture is underpowered. Specifically:

- Define `MIN_QUERIES_FOR_REGRESSION_CHECK = 10` (half the target
  fixture size, not 20 — allows early partial curation to produce
  useful signal).
- When `len(queries) < MIN_QUERIES_FOR_REGRESSION_CHECK`:
  compute nDCG@5 (for the metric), write the JSON report with
  `regression_vs_prev=null, alert_triggered=false`,
  emit `arxmcp_eval_ndcg5`, exit 0.
- When `len(queries) == 0`: skip the entire run, exit 0 with a
  clear log message: "fixture empty — no eval run."

This means AC1 ("nDCG@5 ≥ 0.80 against seed corpus") can only be
verified after the fixture is curated. The integration test for AC1
must be `requires_model`-marked and skipped on the empty stub.

### B. Programmatic eval vs shell-out to pytest

`score_and_write` in `test_retrieval_quality.py` has no pytest
dependency and is directly importable. The hybrid runner
`_run_hybrid_against_corpus` likewise has no pytest
import at the function level (it imports from `server.*`). It does
call `pytest.fail(...)` for fixture-malformed errors — those paths
must be replaced in the watchdog's copy with `RuntimeError` raises.

**Recommendation:** do NOT subprocess out to pytest. Instead:

1. Import `tests.eval.metrics.ndcg_at_k`, `recall_at_k`, `_mean`
   directly (the `TODO(E11_S04)` in metrics.py anticipates this).
2. Copy the `_run_hybrid_against_corpus` logic into
   `ops/watchdog_eval.py`, replacing `pytest.fail` with
   `RuntimeError`. This is ~80 lines.
3. Call `score_and_write` from `test_retrieval_quality.py` — it is
   already pytest-free.

The metrics module docstring says: "If a non-test path needs
`ndcg_at_k` or `recall_at_k`, relocate this module to a top-level
`eval/` package." The implementer should follow this advice: move
`tests/eval/metrics.py` to `eval/metrics.py` and update both the
test import and the watchdog import. This is a refactor, not a copy,
and it eliminates the `tests.*` import from production code.

### C. Comparison baseline: first run with no prior report

The watchdog compares against `ops/eval-reports/corpus_vN-1.json`.
On the first-ever run, there is no prior report.

**Recommendation:** When no prior report exists (first run, or
prior report absent/unreadable), emit `regression_vs_prev=null`,
`alert_triggered=false`, exit 0. Write the current report as the
new baseline. Do NOT alert — there is nothing to regress from.

This also handles the case where the prior report was from a broken
watchdog run (corrupt file, wrong schema). The watchdog should catch
`json.JSONDecodeError` and `KeyError` on the prior report and treat
them the same as "no prior report."

### D. Staging-vs-active LanceDB

`open_chunks_table` accepts `lancedb_path`. The watchdog calls:

```python
staging_info = read_corpus_version(lancedb_path=DEFAULT_LANCEDB_STAGING_PATH)
tbl = open_chunks_table(
    lancedb_path=DEFAULT_LANCEDB_STAGING_PATH,
    version=staging_info.version,
)
```

This pins to the exact LanceDB version recorded in staging's
`corpus-version.json` — the post-index version written by
`write_chunks`. The active server's pinned version (from
`var/arxmcp/index/lancedb/corpus-version.json`) is never opened.

The staging BM25 index is a separate concern: `bm25_indexer.py`
writes to `var/arxmcp/index/bm25/corpus_v<N>.pkl`. The hybrid
pipeline's `BM25Phase` must point at the staging BM25 artifact,
not the active one. The watchdog must pass the correct BM25 index
path (derived from `staging_info.version`) to `Config` or to
`Resources.startup`. Check `server/config.py` for the BM25 path
config key — if it is not configurable, this is a blocking gap
the implementer must resolve.

### E. Metric persistence across processes (cross-process exposure)

The watchdog is a one-shot script. When it exits, any in-process
Prometheus gauge is gone. The brief says "emitted at /metrics."

**Recommendation:** Follow the `LATEXML_DRIFT_DETECTED_COUNTER`
pattern established in `server/metrics.py` F8:

1. Watchdog writes the JSON report to
   `ops/eval-reports/corpus_vN.json`.
2. The MCP SERVER's `refresh_metrics_from_singleton_state` (or a
   scrape-time hook) reads the most-recent JSON report on each
   `/metrics` scrape and sets `EVAL_NDCG5_GAUGE.labels(...).set(...)`.
3. The gauge in the server process reflects the last watchdog run.

This is documented as "v1 operational signal = non-zero exit + log
+ JSON report; server-side metric reflection = E14 scrape hook."
Do NOT claim in the AC that the gauge is live-updated; it is
file-backed-at-scrape.

### F. Quarantine semantics

The brief says "corpus-version.json is NOT advanced." But
`write_chunks` in `ingest/store.py` writes the staging
`corpus-version.json` as a postcondition of every successful
`merge_insert`. The STAGING corpus-version.json IS already written.
The active corpus-version.json is never touched by the delta loop.

"Quarantine" means: E11_S05's cutover script refuses to promote
`lancedb-staging/` → `lancedb/` when the watchdog has flagged a
regression. The concrete mechanism:

**Recommendation:** The watchdog writes
`var/arxmcp/ops/eval-quarantine.flag` when `alert_triggered=true`.
E11_S05's cutover script reads this file before promoting. Operator
clears the flag after investigation. Mirror the `delta-timeout.flag`
pattern from E11_S02 (D8).

### G. `ARXMCP_EVAL_REGRESSION_THRESHOLD_PCT` env var

Validate at parse time:
- Must be numeric (reject non-numeric strings).
- Must be `> 0` (reject 0 — a 0% threshold means any improvement
  would be flagged as regression when prev=1.0, which is nonsensical;
  actually 0% threshold means `new < prev*1.0` = any decline, but
  float precision makes `0.0` pathological).
- Must be `<= 100` (a 100% threshold means nDCG@5 must go to zero
  before alerting — effectively disabling the watchdog).
- Default: `5.0`.

Use `float(os.environ.get("ARXMCP_EVAL_REGRESSION_THRESHOLD_PCT", "5.0"))` and
raise `ValueError` on parse failure.

### H. `ARXMCP_ENABLE_RERANK`

In `server/config.py`, `enable_rerank: bool = False` is the
pydantic-settings field. For the watchdog (a standalone script
not using `Config` as a server), the simplest approach:

```python
enable_rerank = os.environ.get("ARXMCP_ENABLE_RERANK", "false").lower() == "true"
```

But the `_run_hybrid_against_corpus` path uses `Config(enable_rerank=rerank_enabled)`,
which also validates all other `ARXMCP_*` env vars. The workaround
from `test_retrieval_quality.py:380-392` (catch `pydantic.ValidationError`
with a clear diagnostic) applies here too.

### I. Test surface

**Recommendation:**

1. **Default test suite (unit, no model):** stub the retrieval
   pipeline. Inject synthetic `per_query_rows` into `score_and_write`.
   Assert JSON report shape, quarantine flag, exit code, metric gauge
   value. Does NOT require a live corpus or LanceDB.
2. **`requires_model`-marked integration test:** runs against the
   real seed corpus + populated fixture. Asserts nDCG@5 ≥ 0.80.
   Skipped by default; gates the Tier-5 cutover.

The existing `test_retrieval_quality.py::TestScoreAndWrite` (called
in `test_metrics.py`) provides the template — the watchdog's
`score_and_write` wrapper is a thin caller of the same function
and can be unit-tested the same way.

---

## 5. Open questions for the implementer

1. **BM25 staging path:** Does `server/config.py` expose a configurable
   BM25 index path? If not, how does the watchdog point `BM25Phase`
   at the staging BM25 artifact (corpus_v<staging_N>.pkl) rather than
   the active one? This may require passing `bm25_path` to
   `Resources.startup` or a new `Config` field.

2. **`metrics.py` relocation:** Should `tests/eval/metrics.py` be moved
   to `eval/metrics.py` now (as the module docstring's TODO suggests),
   or should the watchdog do a local copy of `ndcg_at_k`? Moving
   is the cleaner path but it's a cross-repo refactor touching the
   existing test imports.

3. **Report output directory:** The brief says
   `ops/eval-reports/corpus_vN.json`. Should this be in
   `var/arxmcp/ops/eval-reports/` (runtime data, gitignored) or
   `ops/eval-reports/` (source tree)? The `var/` convention for
   runtime data is used by `store-stats.jsonl`, `eval/aggregate-*.json`,
   etc. Recommend `var/arxmcp/ops/eval-reports/` — the brief says
   "gitignored for large corpora," consistent with the `var/` placement.

4. **Fixture minimum threshold:** Is `MIN_QUERIES_FOR_REGRESSION_CHECK = 10`
   the right floor, or should the watchdog alert only at full 20
   queries? Given the current 0-query state, a lower floor (even 1)
   is pragmatic for early regression detection.

5. **Server-side scrape hook for `arxmcp_eval_ndcg5`:** Where exactly
   does the server read the most-recent JSON report to set the gauge?
   `server/health.py::refresh_metrics_from_singleton_state` is the
   existing hook. The implementer must add the report-reader there
   and decide which report file to read (the latest by mtime, or
   the one matching the active corpus version).

---

## 6. External writes required by the implementation

| type | target | why |
|---|---|---|
| file creation | `ops/watchdog_eval.py` | Main deliverable |
| file creation | `var/arxmcp/ops/eval-reports/` dir | Runtime report storage (gitignored) |
| file mutation | `server/metrics.py` | Add `EVAL_NDCG5_GAUGE` + scrape-hook |
| file mutation | `server/health.py` | Add report-reader in `refresh_metrics_from_singleton_state` |
| file creation | `docs/ops/drift-watchdog.md` | Operator runbook (see CLAUDE.md §1 for placement: under `.claude/docs/` if agent-internal, under `docs/ops/` if operator-facing) |
| file mutation | `ops/cron/arxmcp-delta.sh` OR new `ops/cron/arxmcp-watchdog.sh` | Integrate watchdog into nightly cron pipeline |
| file mutation | `tests/eval/metrics.py` → `eval/metrics.py` | Relocation (if taken) |
| file mutation | `ingest/bulk_ingest.py` | Re-export `DEFAULT_LANCEDB_STAGING_PATH` for watchdog import |

No push, PR, ticket, or third-party API call is required. All writes
are local filesystem.

**Doc placement note (CLAUDE.md §1):** `docs/ops/drift-watchdog.md`
is an operator-facing runbook (referenced by the brief). It should
live under `docs/` only if it is linked from the root `README.md`;
otherwise it must go under `.claude/docs/`. Per the brief deliverables
it is `docs/ops/drift-watchdog.md` — the implementer must confirm
this is operator-facing before placing it in `docs/`.
