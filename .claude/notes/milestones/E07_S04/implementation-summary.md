# E07_S04 — Implementation summary

**One-line:** End-to-end hybrid eval harness wire-up (BM25 → ANN+RRF → optional Rerank), per-phase latency instrumentation, `@pytest.mark.eval` registration, and the `docs/retrieval-quality-report.md` template. The actual gate run is **blocked on a populated 20-query fixture** (separate deliverable).

## Files

### MODIFIED: `tests/conftest.py`

Added two new flags via `pytest_addoption`:
- `--hybrid` (`action="store_true"`) — switches the eval from dense-only ANN to BM25 → ANN+RRF.
- `--rerank` (`action="store_true"`) — adds Phase-3 cross-encoder. Requires `--hybrid` (raises `pytest.UsageError` otherwise) AND `ARXMCP_RUN_REAL_BGE_RERANKER=1` (env-gated; SKIPs when unset).

Added two corresponding fixtures (`hybrid: bool`, `rerank: bool`) that read the flag values via `request.config.getoption`. The `rerank` fixture is where the `--rerank` ⇒ `--hybrid` precondition raises.

### MODIFIED: `pyproject.toml`

Registered `eval` marker under `[tool.pytest.ini_options].markers` alongside the existing `requires_model`. Did NOT add `-m "not eval"` to `addopts` per synthesis D4 — the cold-start matrix in `test_retrieval_quality.py` is the load-bearing skip mechanism.

### MODIFIED: `tests/eval/test_retrieval_quality.py`

- Applied `@pytest.mark.eval` to `test_retrieval_quality`.
- Test body now branches on `hybrid` fixture: dense-only (`_run_queries_against_corpus`, E05_S02 default) vs hybrid (`_run_hybrid_against_corpus`, new).
- New helper `_run_hybrid_against_corpus(queries, tbl, encode_query, *, corpus_version, rerank_enabled)`:
  - Constructs `Resources.startup(Config(enable_rerank=rerank_enabled))` once for the whole run.
  - Per query: `encode_query` (once, for `query_vec`); BM25 (Phase 1, sync); dual-ANN+RRF (Phase 2, async); cross-encoder rerank (Phase 3, async, off-path is passthrough); compute nDCG@5 + Recall@10.
  - Records per-phase latency (`bm25_ms`, `ann_ms`, `rerank_ms`, `total_ms`) per query.
  - Trusts the query-encoder singleflight to collapse the double encode (we call `encode_query` once for `query_vec`; `ANNPhase.query` calls it again internally — the singleflight collapses to one forward pass per synthesis D8).
  - Wraps `Resources.shutdown()` in a 30s `wait_for` per the established convention.
- Extended `score_and_write` with `assert_latency_p95: bool = False` kwarg. When set, computes p50/p95/max for `total_ms`, asserts p95 ≤ `LATENCY_P95_MAX_SECONDS = 2.0` (AC #4). The aggregate JSON now also carries `latency_ms` (per-phase percentiles) + `pipeline` identity (`"hybrid"` or `"hybrid+rerank"`).
- New helper `_percentile(values, pct)` — pure-Python linear-interpolation percentile (avoids numpy at the eval-aggregate layer).
- `--rerank` env-gate: when `--rerank` is set without `ARXMCP_RUN_REAL_BGE_RERANKER=1`, SKIPs with the canonical message (mirrors `tests/retrieval/test_rerank.py:743-746`).

### NEW: `docs/retrieval-quality-report.md`

Preliminary findings document with:
- TL;DR table (4 questions, all marked PENDING / HARNESS LANDED).
- Pipeline-under-test table (3 flags + their effects).
- Per-phase nDCG@5 lift table (PENDING — populated when fixture lands).
- Latency profile table (PENDING).
- Reranker-necessity decision protocol (4 steps).
- "How to run the gate" runbook (4 prerequisites + 2 invocations).
- Open follow-ups (curate fixture; lift orchestrator into `search.py` for E08; update TIER-GATES.md).

The report is the canonical record E11_S05 will read for the 200K-paper scale-cutover go/no-go.

### NOT MODIFIED (deliberately)

- **`server/handlers/search.py`** — brief deliverables list omits this. Per synthesis D1, the orchestration lives in the eval test as a peer of `_run_queries_against_corpus`. E08 (agent runtime) will lift the helper into the handler when the live server actually serves hybrid retrieval.
- **`server/config.py:enable_rerank`** — POST-eval edit per synthesis D7. The default stays `False` until the gate run proves the reranker is required.

## Acceptance criteria

| Brief AC | Reinterpretation (per synthesis) | Status |
|---|---|---|
| `pytest ... --hybrid --rerank --ndcg-min=0.80` passes | Wire-up: harness runs the hybrid pipeline AND the test SKIPs cleanly when the fixture is empty (per cold-start matrix) | met (wire-up); gate-run pending fixture curation |
| nDCG@5 ≥ 0.80 on 20 queries | Same blocker — fixture is `{"queries": []}` | pending curation |
| `docs/retrieval-quality-report.md` states whether reranker is required | Preliminary report shipped with PENDING tags + decision protocol | met (preliminary) |
| Latency p95 ≤ 2 s at k=10 | `LATENCY_P95_MAX_SECONDS = 2.0` constant; assertion fires on populated fixture in the hybrid branch | met (assertion landed) |

## Deviations from the brief

1. **Orchestration location.** Brief implied the handler integration; deliverables list omits `server/handlers/search.py`. Implementation places the orchestrator in the eval test (synthesis D1). E08 will lift it into the handler — documented as a follow-up in the report.

2. **`server/config.py` change.** Brief lists this as a deliverable; implementation defers per synthesis D7 — the default stays `False` until the eval proves the reranker is necessary. The flip is a follow-up commit after a successful `--hybrid --rerank` run.

3. **Fixture/curation blocker.** Brief AC #1 + #2 cannot be satisfied until the 20-query fixture is curated. The harness wire-up CAN run the gate; the gate result is pending. Documented prominently in the report.

## What this milestone closes

- E05_S02's harness now supports the hybrid path (deferred from E05_S02).
- E07_S03's `Resources.rerank_phase` has its first non-test consumer.
- E11_S05 has the report file it needs for the 200K cutover go/no-go decision.

## External writes the orchestrator must authorize

None. Purely-internal — five file touches:
- `tests/conftest.py` (modify)
- `pyproject.toml` (modify)
- `tests/eval/test_retrieval_quality.py` (modify)
- `docs/retrieval-quality-report.md` (new)

The first `--rerank` invocation downloads BGE-reranker-v2-m3 (~2.3 GB) on the operator's machine — same pattern as E07_S03; not an authorized agent write.

## Project check command

`ruff check .` — clean.
`pytest -q` — **920 passed, 4 skipped** (same count as pre-milestone — the eval still SKIPs cleanly via the cold-start matrix; no regressions).
