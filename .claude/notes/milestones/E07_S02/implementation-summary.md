# E07_S02 — Implementation summary

**One-line:** Phase-2 dual-ANN retrieval — `ANNPhase` searches `embedding_stmt` + `embedding_proof` columns, fuses with the BM25 candidates via `reciprocal_rank_fusion(k=60)`, returns top-50 fused candidates.

## Files

### NEW: `server/retrieval/rrf.py` (~110 LOC)

Pure-Python RRF utility per Cormack-Clarke-Büttcher 2009. `RRF_K = 60` module constant. `reciprocal_rank_fusion(lists: Sequence[Sequence[str]], k=RRF_K) -> list[tuple[str, float]]`. Sort key `(score desc, chunk_id asc)` matches the project-wide determinism convention.

### NEW: `server/retrieval/ann.py` (~270 LOC)

`ANNPhase` class:
- **`__init__(chunks_table)`** — cheap; just caches the LanceDB handle. No expensive load → no async startup classmethod required.
- **`query(query_text, bm25_candidates, top_n=50)`** (async) — encodes the query ONCE via `encode_query` (singleflight-wrapped); runs two sequential `tbl.search(vec, vector_column_name=...)` calls (one per column); adapts to chunk_id-only ranked lists; fuses via RRF; returns top-N.

Module constants: `DEFAULT_TOP_N = 50`, `PER_COLUMN_LIMIT = 50`, `EMBEDDING_COLUMNS = ("embedding_stmt", "embedding_proof")`.

Helper `_distance_to_score(dist) -> float` — L2 distance on unit vectors → cosine in [0, 1] (`max(0, 1 - dist/2)`). Mirrors the existing `server/handlers/search.py:260-264`.

Helper `_ann_search_one_column(chunks_table, vec, column, limit)` — wraps the LanceDB `.search().limit().to_arrow()` call in a try/except that catches LanceDB exceptions broadly and returns `[]` on failure (graceful degradation when a column has no rows / no HNSW index — closes the brief risk note).

### MODIFIED: `server/retrieval/__init__.py`

Re-exports `ANNPhase`, `RRF_K`, `reciprocal_rank_fusion` alongside the existing `BM25Phase` exports.

### MODIFIED: `server/resources.py`

Added `ann_phase: Any | None = None` field on the `Resources` dataclass. Inserted step 4c in `Resources.startup` (after `bm25_phase` step 4b): `ann_phase = ANNPhase(chunks_table=chunks_table)`. Cheap construction (no expensive load), so no async startup needed.

### NEW: `tests/retrieval/test_ann.py` (~580 LOC, 30 tests)

Test classes:
- **`TestRRF`** (11 tests) — RRF formula correctness: `RRF_K == 60`; single-list passthrough; two-list additive fusion; descending-sort with explicit tiebreak math (`a, c, b` order); chunk_id ascending tiebreak; empty outer / inner lists tolerated; zero/negative k rejected; determinism (byte-identical across runs); default-k matches `RRF_K`.
- **`TestScoreConversion`** (5 tests) — distance 0 → 1.0; distance 2 → 0.0; distance 1 → 0.5; None → 0.0; out-of-range distance clamped to 0.
- **`TestANNPhaseQuery`** (7 tests) — dual-corpus smoke; pure-ANN fallback (brief AC #1); RRF includes all input sources (brief AC #2); fused scores descending (brief AC #3); top_n cap; default `top_n == 50`; `PER_COLUMN_LIMIT == 50`; `top_n=0` rejected.
- **`TestGracefulDegradation`** (2 tests) — stmt-only corpus + empty BM25 → still returns ANN results; stmt-only + non-empty BM25 → fuses BM25 + stmt only without crashing on the empty proof column.
- **`TestSingleflightContract`** (2 tests) — brief AC #4 reinterpreted: single ANNPhase.query → dedup counter unchanged; two concurrent identical queries → counter += 1 (proves the encode call routes through the singleflight wrapper, coalescing duplicates).
- **`TestResourcesIntegration`** (1 test) — `Resources.startup(cfg)` populates `r.ann_phase`; `r.ann_phase.chunks_table is r.chunks_table` (no redundant copy).

## Acceptance criteria

| Brief AC | Reinterpretation | Status | Evidence |
|---|---|---|---|
| `ANNPhase.query("perverse...", bm25_candidates=[])` returns ≥ 1 | unchanged | met | `TestANNPhaseQuery::test_pure_ann_fallback_with_empty_bm25` |
| RRF output contains candidates from both BM25 list AND both ANN lists | unchanged | met | `TestANNPhaseQuery::test_rrf_includes_all_input_sources` |
| `fused_score` values descending | unchanged | met | `TestANNPhaseQuery::test_fused_scores_descending` + `TestRRF::test_output_sorted_descending` |
| Both embedding calls go through the shared Singleflight wrapper | reinterpreted: there is only ONE encode call per `ANNPhase.query` (one encoder, two columns, one query vector); the call routes through the singleflight (verified via `get_singleflight_dedup_count()` which deduplicates concurrent identical queries) | met | `TestSingleflightContract` (2 tests) |
| `pytest tests/retrieval/test_ann.py` passes | unchanged | met | 30 passed |

## Deviations from the brief (documented in research-synthesis.md)

1. **Encoder strategy.** The brief implies two encoders ("prose encoder" / "LaTeX encoder" embedding the query text twice). The codebase has ONE BGE-M3 encoder (`ingest/embedder.py:112`); the dual columns are KIND-ROUTED at index time (`kind == "proof"` → `embedding_proof`; everything else → `embedding_stmt`). Implementation calls `encode_query` ONCE and reuses the single 1024-dim vector against both columns.

2. **Brief AC #4 wording.** "verifiable via the singleflight hit counter in `/debug/cache-stats`" — that endpoint does not exist. Test uses `server.query_encoder.get_singleflight_dedup_count()` instead (the in-process getter; thread-safe per `query_encoder.py:187`).

3. **Handler integration deferred.** `server/handlers/search.py` is NOT rewired to use `ANNPhase` in this milestone. The deliverables list only `ann.py` / `rrf.py` / `test_ann.py`; the handler swap (replacing the dense-only block at `search.py:105-129`) is a later milestone (likely E07_S04 once Phase 3 lands).

## What this milestone closes

- Brief AC #1 (pure-ANN fallback) — graceful degradation when BM25 list is empty.
- Brief AC #2 (RRF includes all sources) — verified end-to-end with synthetic candidates from each input.
- Brief AC #3 (fused_score descending) — explicit sort assertion + tiebreak math.
- Brief AC #4 (singleflight wrapper) — reinterpreted; concurrent-dedup test proves the routing.
- Brief risk note — graceful degradation when `embedding_proof` column has zero rows / no HNSW.

## External writes the orchestrator must authorize

None. Purely-internal retrieval milestone. The pinned tool-schema hash from E06_S06 is unaffected (no tool surface bytes change).

## Project check command

`ruff check .` — clean.
`pytest -q` — **872 passed, 3 skipped** (was 842 pre-milestone — +30 from this milestone, no regressions).
