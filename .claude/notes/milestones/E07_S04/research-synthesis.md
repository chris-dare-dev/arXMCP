# E07_S04 — Research synthesis

## Both researchers agree on these load-bearing facts

1. **`tests/eval/fixtures/queries.json` is an EMPTY STUB** (`{"queries": []}`). The Tier-0 cold-start matrix in `tests/eval/test_retrieval_quality.py:14-28` SKIPs (does not fail) on empty fixtures. So the brief's literal AC #1 ("pytest passes with nDCG@5 ≥ 0.80") **cannot be satisfied** by E07_S04 alone — the wire-up can land but the actual gate run is blocked on a separate curation deliverable.

2. **`tests/eval/test_retrieval_quality.py` already exists and is dual-column ANN today** (E05_S02 work). It reads `--ndcg-min` (default 0.70), runs two `tbl.search()` calls per query, MIN-distance dedup, top-10 cutoff, nDCG@5 + Recall@10. Writes `var/arxmcp/ops/eval/results-<v>.jsonl` + `aggregate-<v>.json`. Cold-start matrix already provides skip protection.

3. **`--ndcg-min` already exists**; `--hybrid` and `--rerank` do not. The conftest docstring at line 27 already anticipates this milestone: *"E07_S04 raises this to ``0.80`` for the hybrid + reranker pipeline (Tier-1 → Tier-2)."*

4. **`pytest.mark.eval` does NOT exist** (only `requires_model` does, registered at `pyproject.toml:118-120`). Brief literal "marked `@pytest.mark.eval`" requires a new marker.

5. **All three phases exist on `Resources`** with the documented signatures:
   - `BM25Phase.query(query_text, filters=None, top_n=200) -> tuple[list[tuple[str,float]], list[str]]` (sync; tuple second element is `filter_warnings`)
   - `ANNPhase.query(query_text, bm25_candidates, top_n=50) -> list[tuple[str,float]]` (async; **internally calls** `encode_query`)
   - `RerankPhase.rerank(query_text, query_vec, candidates, top_k) -> list[tuple[str,float]]` (async; **needs `query_vec` separately** for the Tier-3 cache key)

6. **The brief deliverables list omits `server/handlers/search.py`.** Only three files are listed: the eval test, the docs file, and `server/config.py`. The handler-rewrite is NOT part of E07_S04.

7. **Default test run does not exclude eval today** (`pyproject.toml:117` is `addopts = "-q"`). The cold-start matrix is the load-bearing skip mechanism.

8. **nDCG consumes ranks, not scores** (`tests/eval/metrics.py:144-148`). So E07_S03's F5 score-semantics gap (RRF score vs sigmoid logit) does NOT bite the eval — but document for future readers.

## Decisions for the implementer

| ID | Decision | Rationale |
|---|---|---|
| D1 | **Orchestrator lives as a helper inside `tests/eval/test_retrieval_quality.py` (sibling of `_run_queries_against_corpus`).** Not in the handler, not in a new `server/retrieval/hybrid.py`. | Brief deliverables explicitly omit both. The phases were designed as peers expecting an external orchestrator (`server/retrieval/ann.py:237-241` documents this). E08 (agent runtime) will lift the orchestration into `search.py` when the live server actually serves hybrid retrieval. |
| D2 | **Register `--hybrid` and `--rerank` flags in `tests/conftest.py`** (single `pytest_addoption` site). Both `action="store_true"`. Expose two fixtures (`hybrid: bool`, `rerank: bool`). | Mirrors the existing `--ndcg-min` pattern at `tests/conftest.py:33-43`. |
| D3 | **`--rerank` without `--hybrid` raises `pytest.UsageError`** at fixture-setup time. | Reranking only RRF candidates is the design. Mutually-coherent contract per Brief 1. |
| D4 | **Register `eval` marker in `pyproject.toml`** (one line under existing `markers` list) AND apply `@pytest.mark.eval` to `test_retrieval_quality`. Do NOT add `-m "not eval"` to addopts. | Cold-start matrix remains the load-bearing skip mechanism (already correct behavior). The marker enables `pytest -m "not eval"` opt-in exclusion (E11 may flip this). |
| D5 | **`--rerank` requires `ARXMCP_RUN_REAL_BGE_RERANKER=1` env-var** (matches E07_S03 convention). When `--rerank` is set without the env-var, `pytest.skip("set ARXMCP_RUN_REAL_BGE_RERANKER=1 to exercise reranker")`. | The 2.3 GB model download is opt-in. Mirrors `tests/retrieval/test_rerank.py:743-746`. |
| D6 | **Latency instrumentation: `time.monotonic()` per phase.** Record per-query JSONL row with `bm25_ms`, `ann_ms`, `rerank_ms`, `total_ms`. Aggregate p50/p95 in `aggregate-<v>.json`. AC #4 asserts p95 ≤ 2s at k=10. | Brief explicit. The existing `score_and_write` accepts arbitrary per-row keys. |
| D7 | **`ARXMCP_ENABLE_RERANK` config flip is a POST-eval-run edit.** Wire-up does NOT change the default (`enable_rerank: bool = False`). After running the eval and writing the report, IF reranker is needed → flip to True in a follow-up commit. IF reranker is not needed → leave False. | Default OFF is a security + performance default. Brief: "set to its production value based on findings" — the findings come AFTER the run, not before. |
| D8 | **Trust the singleflight for the double-encode.** Orchestrator calls `encode_query(query)` once for `query_vec` (used by RerankPhase). `ANNPhase.query` ALSO calls `encode_query(query)` internally. The query_encoder singleflight collapses the duplicate to one forward pass. | Cleaner than threading `query_vec` through `ANNPhase.query`. Per E07_S02 research synthesis D8. |
| D9 | **Document the SKIP path explicitly in `docs/retrieval-quality-report.md`.** The harness lands in this milestone; the actual nDCG gate run is blocked on a populated 20-query fixture (separate deliverable, likely a curator step before E11_S05). The report records "preliminary findings: gate run pending populated fixture". | Avoids ship-without-context. Brief AC #1 is partially-met: "the harness CAN run the gate; the gate result is pending curation." |
| D10 | **`docs/retrieval-quality-report.md` schema:** per-phase nDCG@5 table (BM25-only, +ANN, +Rerank columns; one row per pipeline configuration AND/OR per query when fixture lands), p50/p95 latency table, narrative on reranker necessity, link to the latest `aggregate-<v>.json`. Marked PRELIMINARY until curated fixture lands. | E11_S05 will read this for the 200K cutover go/no-go decision. |

## Reinterpreted acceptance criteria

The brief's literal AC #1 + #2 are blocked on the empty-queries fixture. We scope-down to the wire-up that COULD pass when the fixture is populated:

| Brief AC | Reinterpretation | Status (after this milestone) |
|---|---|---|
| `pytest ... --hybrid --rerank --ndcg-min=0.80` passes | wire-up: harness runs the hybrid pipeline AND the test SKIPs cleanly when fixture is empty (per cold-start matrix). When fixture is populated AND reranker is downloaded, the gate runs the eval. | met (wire-up); gate-run pending curation |
| nDCG@5 ≥ 0.80 on 20 queries | same blocker | pending curation |
| `docs/retrieval-quality-report.md` states whether reranker is required | preliminary report shipped with PENDING tag; final answer requires fixture | met (preliminary) |
| Latency p95 ≤ 2s at k=10 | the test asserts it; assertion fires on populated fixture | met (assertion landed) |

The brief's risk-note ("This milestone is the single explicit Tier-1 exit gate") is honored by leaving the harness ready to run; the gate flips when the fixture and corpus are populated.

## Open questions

1. **Will a populated 20-query fixture land before this PR is reviewed?** If yes, the gate runs and the report becomes final. If no, the wire-up lands with a documented PENDING state.

2. **The handler integration into `server/handlers/search.py` is deferred.** E08 (agent runtime) is the natural venue. Confirm with the next milestone owner.

## External writes the implementation will require

None. All deliverables are local file edits:
- `tests/eval/test_retrieval_quality.py` (modify — add `@pytest.mark.eval`, hybrid orchestrator helper, latency instrumentation)
- `tests/conftest.py` (modify — add `--hybrid`, `--rerank` flags + fixtures)
- `pyproject.toml` (modify — register `eval` marker)
- `docs/retrieval-quality-report.md` (new — schema + preliminary findings)
- `server/config.py` (modify — POST-eval, IF reranker is needed)

No git push, PR creation, ticket mutation, or third-party API call. The first `--rerank` invocation downloads `BAAI/bge-reranker-v2-m3` (~2.3 GB) from HuggingFace Hub on the operator's machine — same pattern as E07_S03; not an authorized agent write.
