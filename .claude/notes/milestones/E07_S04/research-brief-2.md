# Research brief 2 — E07_S04

End-to-end eval; promote nDCG@5 to ≥ 0.80 with hybrid (BM25 → ANN+RRF
→ optional rerank). Most of the harness, fixtures, phases, and CLI
flag plumbing already exist; this milestone is mostly **wiring the
3-phase orchestration into the existing eval test, adding two flags,
running the eval, writing the docs, and possibly flipping one bool**.

## 1. In-codebase context (all paths absolute)

### The eval test exists; it is dense-only ANN today

`tests/eval/test_retrieval_quality.py` (E05_S02 work) is a complete,
shipped harness that already:

- reads `tests/eval/fixtures/queries.json` (currently `"queries": []`
  — empty stub from E05_S01),
- imports `read_corpus_version` + `open_chunks_table`,
- enforces a 4-cell cold-start matrix (lines 14–28: skip on missing
  corpus and/or empty queries — never fail on cold-start),
- runs **dual-column ANN only** today
  (`tests/eval/test_retrieval_quality.py:235-260`): two `tbl.search()`
  calls per query (one per `EMBEDDING_COLUMN_NAMES` entry), MIN-distance
  dedup, top-10 cutoff, nDCG@5 + Recall@10,
- writes `var/arxmcp/ops/eval/results-<v>.jsonl` and
  `aggregate-<v>.json`,
- calls `assert_threshold(ndcg5_mean, ndcg_min)` from
  `tests/eval/metrics.py:219` (raises `ThresholdNotMetError`).

The factor-out into `_run_queries_against_corpus` and
`score_and_write` (lines 193, 281) is exactly the boundary E07_S04
swaps: `score_and_write` is unit-tested in `tests/eval/test_metrics.py`
and stays untouched; only `_run_queries_against_corpus` (or a sibling
function) needs a hybrid variant.

### Fixture schema (verified at `tools/validate_eval_fixtures.py:309-433`)

```
{
  "schema_version": "1.0",
  "chunker_version": "v1.0",
  "created_at": "YYYY-MM-DD",
  "queries": [{"query_id": str, "query_text": str,
               "relevant_chunks": [{"chunk_id": str, "relevance": 0..3}, ...]}]
}
```

Today: 0 queries (`tests/eval/fixtures/queries.json:6`). E05_S03 / E11
own curation; this milestone CANNOT itself land 20 hand-labeled
queries (that's an out-of-scope deliverable). It will validate that
the harness *would* pass when the fixture and corpus are populated.

### `--ndcg-min` already exists; `--hybrid` and `--rerank` do not

`tests/conftest.py:33-43` registers `--ndcg-min` (default 0.70) plus
the `ndcg_min` fixture (line 60). The conftest docstring at line 27
explicitly anticipates this milestone: *"E07_S04 raises this to
``0.80`` for the hybrid + reranker pipeline (Tier-1 → Tier-2)."* A
single `parser.addoption("--hybrid", action="store_true")` and
matching `--rerank` are the only conftest changes. There is **only one
`pytest_addoption`** site in the repo (`tests/conftest.py:21`), so the
flag registration cannot collide.

### The `eval` marker does NOT exist; only `requires_model` does

`pyproject.toml:118-120` registers `requires_model` only. The brief
literal *"this test is marked `@pytest.mark.eval`"* requires a NEW
marker registration — see §2 for whether to take the literal or
reinterpret.

### Default test run does NOT exclude eval today

`pyproject.toml:117` is `addopts = "-q"`. There is no `--ignore=` or
`-m "not eval"` filter — `make test` invokes `pytest` which **does**
run `tests/eval/test_retrieval_quality.py`, but per the cold-start
matrix it always SKIPs on the empty fixture / no-corpus state (and
that's the correct behavior; see implementation summary). The
`Makefile:56` `eval` target is the explicit Tier-0 invocation. CI
inherits `make test`; the eval test is effectively a manual gate
because it skip-passes without prerequisites.

### Phases exist on `Resources` and are wired at startup

`server/resources.py:340-383` constructs `bm25_phase`, `ann_phase`,
and `rerank_phase`; `server/retrieval/__init__.py` re-exports them.
Phase signatures (verified):

- `BM25Phase.query(query_text, filters=None, top_n=200) ->
  tuple[list[tuple[str,float]], list[str]]` (sync; tuple second
  element is `filter_warnings`).
- `ANNPhase.query(query_text, bm25_candidates, top_n=50) ->
  list[tuple[str,float]]` async; **internally calls**
  `encode_query(query_text)` (`server/retrieval/ann.py:389`) — so the
  orchestrator must NOT also call `encode_query` ahead of it unless
  it wants to memoize and pass `query_vec` down.
- `RerankPhase.rerank(query_text, query_vec, candidates, top_k) ->
  list[tuple[str,float]]` async — **needs `query_vec` separately**
  for the Tier-3 cache key (`server/retrieval/rerank.py:457-481`).

This means the orchestrator must compute `query_vec` once with
`encode_query`, pass it to `RerankPhase.rerank` AND repeat the
encode inside `ANNPhase.query` (the per-query singleflight in
`encode_query` collapses this — verified in
`server/query_encoder.py`). One forward pass per query in practice.

### `server/handlers/search.py` is dense-only and untouched by brief

`server/handlers/search.py:112-118` runs a single ANN call against
`embedding_stmt`. The brief deliverables list does NOT include
`search.py`. The eval harness should call **the phases directly**, not
the handler — the handler is a wire-shape concern (resource_links,
envelope) that adds noise without changing rank order. See §2.

## 2. Prior decisions and lessons (recommendations)

### D-1. Where the orchestration lives → **inside the eval test fixture**

Three options: (a) `server/handlers/search.py`, (b) new
`server/retrieval/hybrid.py`, (c) the test itself. **Recommend (c)**:
write a `_run_hybrid_against_corpus(...)` helper next to the existing
`_run_queries_against_corpus` in
`tests/eval/test_retrieval_quality.py`. Reasons:

1. The brief deliverables list omits both `server/handlers/search.py`
   AND any new `server/retrieval/hybrid.py` file. Adding either is
   scope creep that the next milestone (E08 agent runtime) can rectify
   when the handler actually needs the hybrid path.
2. The existing test already factors `_run_queries_against_corpus` /
   `score_and_write` exactly so a sibling can be added without
   breaking the unit tests for `score_and_write`.
3. Per `server/retrieval/ann.py:237-241`: *"The class does NOT call
   `BM25Phase.query` — the caller (a future hybrid-search
   orchestrator) provides the BM25 candidate list as a separate
   argument."* The phases were designed as peers expecting an external
   orchestrator. The eval harness IS that first orchestrator.
4. If E08 later moves orchestration into `search.py`, the test helper
   becomes a thin wrapper around the handler call. No throwaway code.

The fixture instantiates a minimal `Resources`-like context (or
constructs `BM25Phase` / `ANNPhase` / `RerankPhase` directly from
`chunks_table` per their constructors) — same pattern E05's
`_run_queries_against_corpus` already uses.

### D-2. `--hybrid` and `--rerank` semantics

Add both as `action="store_true"` flags in `tests/conftest.py` and
expose two fixtures (`hybrid: bool`, `rerank: bool`). The
`test_retrieval_quality` body branches once: hybrid path vs current
ANN-only path. Default both False so the existing `make eval` (Tier-0)
invocation is unchanged. `--rerank` implies `--hybrid` (validate; if
`--rerank` without `--hybrid`, raise `pytest.UsageError` at fixture
setup time — quoting BR brief literal `--hybrid --rerank`).

### D-3. `pytest.mark.eval` — register but don't filter by default

The brief says the test IS marked `@pytest.mark.eval` AND excluded
from default. The cold-start matrix already provides skip protection;
adding a `not eval` filter would make `make test` greener but obscure
the explicit "fixture missing" / "corpus missing" diagnostic the
matrix provides. **Recommend**: register the marker in
`pyproject.toml:118-120` (one line), apply
`@pytest.mark.eval` to `test_retrieval_quality`, but do NOT add a
default `-m "not eval"` to `addopts`. The cold-start skip remains the
load-bearing mechanism. The marker enables `pytest -m "not eval"`
*opt-in* exclusion (E11 may flip this).

### D-4. Reranker activation is post-eval, not pre-eval

The brief deliverable *"`server/config.py` — `ARXMCP_ENABLE_RERANK`
set to its production value based on findings"* is a **post-run
edit**, not part of the wire-up commit. Sequence:

1. Land harness wire-up + orchestrator helper + flag registration +
   marker (one PR).
2. Run `pytest tests/eval/test_retrieval_quality.py --hybrid
   --rerank --ndcg-min=0.80` against a populated fixture/corpus.
3. Write `docs/retrieval-quality-report.md` with per-phase nDCG +
   p50/p95.
4. Iff reranker is needed, flip
   `server/config.py:106` `enable_rerank: bool = False → True`.

The default stays False until the eval proves it's needed
(`server/retrieval/rerank.py:13-16`: *"E07_S04 demonstrates that
nDCG@5 ≥ 0.80 requires the reranker; only then the flag flips on. If
nDCG@5 ≥ 0.80 is reached without rerank, the flag stays off"*).

### D-5. Reranker model-load env-gate: align with `requires_model`

`tests/retrieval/test_rerank.py:743-746` already pairs
`@pytest.mark.requires_model` with
`ARXMCP_RUN_REAL_BGE_RERANKER=1`. The eval test, when invoked with
`--rerank`, must require BOTH (since the model is 2.3 GB and not
available in CI). **Recommend**: when `--rerank` is set, the test
either (a) `pytest.skip("set ARXMCP_RUN_REAL_BGE_RERANKER=1 to
exercise reranker")` if the env-var is unset, OR (b) add the
`requires_model` marker conditionally. (a) is simpler and matches the
existing skip-cell discipline.

### D-6. Latency measurement: `time.monotonic()` per phase

Record per-phase elapsed time inside the orchestrator helper and emit
into the per-query JSONL row as `bm25_ms`, `ann_ms`, `rerank_ms`,
`total_ms` (additive new keys; existing `score_and_write` won't reject
them — it just dumps the rows verbatim). `score_and_write` then writes
percentile aggregates into `aggregate-<v>.json` (extension; coordinate
with E11_S04's drift watchdog schema). The brief AC4 asserts p95 ≤ 2 s
at k=10 — assert this in the test body alongside the nDCG threshold.

### D-7. Score-semantics from E07_S03 F5 — irrelevant for nDCG

`server/retrieval/rerank.py:501-514` documents that off-path returns
RRF scores while on-path returns sigmoid logits; **but nDCG only
consumes RANKS, not scores** (`tests/eval/metrics.py:144-148`). The
F5 wire-surface concern doesn't bite here. Document this in the
findings note so a future reader doesn't try to compare scores
across pipelines.

### D-8. `ANNPhase.query` already encodes; phase-3 needs the vec

To avoid the awkward "encode twice, dedup via singleflight" dance,
**recommend** the orchestrator helper bypasses `ANNPhase.query`'s
internal encode by computing `query_vec` first and calling the inner
`_ann_search_one_column` + `reciprocal_rank_fusion` directly, OR
accept the redundant `encode_query()` call and trust the
singleflight (cleaner; verified at `server/query_encoder.py`'s
singleflight). Recommend the **trust-singleflight** approach — keeps
`ANNPhase` as the consumer-grade entry point and the redundant call
collapses to ~0 cost.

## Open questions

1. **Will the implementer have a populated 20-query fixture and seed
   corpus when running this milestone?** The fixture is empty stub
   today. The brief is the gate, not the curation step — if neither
   exists, the wire-up lands and the eval *invocation* SKIPs.
   Document the SKIP path explicitly in the findings note.

2. **`docs/retrieval-quality-report.md` schema** is undefined in the
   brief. Recommend: per-phase nDCG@5 table (BM25-only, +ANN, +Rerank
   columns; one row per query), latency p50/p95 table, narrative
   conclusion on reranker necessity, link to the latest
   `aggregate-<v>.json`. This is the format E11_S05 will read for the
   200K cutover go/no-go.

## External writes the implementation will require

None. All deliverables are local file edits:
`tests/eval/test_retrieval_quality.py`, `tests/conftest.py`,
`pyproject.toml`, `docs/retrieval-quality-report.md`,
`server/config.py`. The `--rerank` real-model invocation downloads
BGE-reranker safetensors from HuggingFace Hub on the operator's
machine — same pattern as E07_S03; not an authorized agent write.
