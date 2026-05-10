# E07_S04 — Research brief 1

## 1. In-codebase context

### Critical files

- `tests/eval/test_retrieval_quality.py:1-361` — the existing harness from E05_S02. It runs **dense-only dual-column ANN** today (lines 233-260): `tbl.search(query_vec, vector_column_name=col)` per column over `EMBEDDING_COLUMN_NAMES`, MIN-distance dedup, top-10 (FINAL_TOP_K=10 line 96), nDCG@5. Reads `--ndcg-min` via the `ndcg_min` fixture (line 113). The cold-start matrix lines 14-23 SKIPs (does not fail) when corpus or fixture is empty. Output: `var/arxmcp/ops/eval/results-<v>.jsonl` + `aggregate-<v>.json` (drift baseline for E11_S04). Only one test, no `@pytest.mark.eval` marker today (despite the milestone brief claiming the marker exists).
- `tests/eval/fixtures/queries.json` — **EMPTY STUB**: `{"queries": []}`. The Tier-0 gate would `pytest.skip` today. **E05_S02 shipped curation runbook (`docs/eval-curation.md`) but did not perform the curation.** This is the load-bearing blocker for E07_S04 — see Open Questions.
- `tests/conftest.py:21-63` — `pytest_addoption` registers `--ndcg-min` (default 0.70) + the `ndcg_min` fixture. E07_S04 must add `--hybrid` and `--rerank` in the same `pytest_addoption` block, plus matching fixtures (`hybrid: bool`, `rerank: bool`).
- `server/handlers/search.py:78-158` — the dense-only path (`vector_column_name="embedding_stmt"` only, line 113). Sort `(score_desc, chunk_id_asc)` line 128. Returns `retrieval_mode: "dense_only"` (line 151). E07_S04 must rewire this to call BM25 → ANN+RRF → optional Rerank.
- `server/resources.py:222-240` — `Resources` dataclass already carries `bm25_phase`, `ann_phase`, `rerank_phase` (E07_S01-S03). All three are constructed at startup (lines 332-383). The eval harness can construct them via `Resources.startup(Config())` — but currently the harness opens the LanceDB table directly via `open_chunks_table()` (line 178) and bypasses `Resources` entirely.
- `server/retrieval/bm25.py:529-630` — `BM25Phase.query(text, filters, top_n=200)` returns `(candidates, filter_warnings)`.
- `server/retrieval/ann.py:306-421` — `ANNPhase.query(query_text, bm25_candidates, top_n=50)` does the encode + dual ANN + RRF in one async call. **The encoding lives inside `ANNPhase.query` (line 389)**, NOT outside.
- `server/retrieval/rerank.py:456-499` — `RerankPhase.rerank(query_text, query_vec, candidates, top_k)`. Off-path returns `list(candidates[:top_k])` verbatim. Requires `query_vec` — but `ANNPhase.query` does not return it (the orchestrator must encode separately or extract via the singleflight). See Open Q3.
- `.claude/notes/05-storage-and-indexing.md:312-331` — the canonical 3-phase contract. Quotes verbatim:

  > "**Phase 1 (cheap, broad):** BM25 over `body_tokens` using Python `rank_bm25` … Take top-200."
  > "**Phase 2 (medium):** Dual ANN search — one query embedding over `embedding_stmt` and one over `embedding_proof`, top-50 each. Reciprocal Rank Fusion (k=60) … Take top-50."
  > "**Phase 3 (expensive):** `bge-reranker-v2-m3` local cross-encoder. Gated by `ARXMCP_ENABLE_RERANK` … When disabled, Phase-2 RRF order is returned directly. Take top-k (default 10, max 50)."

- `.claude/notes/09-feature-priorities.md:38-58` — Tier-1 exit is qualitative ("retrieval over 1,000 papers reliably surfaces the right theorem"). The numerical 0.80 target lives in `TIER-GATES.md` (single source). No latency budget appears in `09-…` — the brief's "p95 ≤ 2 s at k=10" is the new contract.
- `TIER-GATES.md:18` — gate command: `pytest tests/eval/test_retrieval_quality.py --ndcg-min=0.80 passes with **BM25 hybrid + reranker** active (E07)`. Lines 117-138 specify the Tier-1 → Tier-2 row. **The `--hybrid` and `--rerank` flags from the brief are NOT mentioned in `TIER-GATES.md`** — E07_S04 must update the gate row to mention the new flags.
- `docs/` format — four existing markdown docs (`chunker-fixtures.md`, `eval-curation.md`, `install.md`, `snippet-contract.md`). Each opens with `# <Title>` and a one-paragraph framing sentence. Mirror this for `docs/retrieval-quality-report.md`.
- `pyproject.toml:118-120` — only one custom marker: `requires_model`. The brief says the test is `@pytest.mark.eval` and excluded from default — **today it is NOT marked and it DOES run on `make test` (skipped via the cold-start matrix)**. E07_S04 must register `eval` as a marker AND add `@pytest.mark.eval` to the test, AND add it to `addopts` (e.g. `-q -m "not eval"`) so the default test run excludes it.

## 2. Prior decisions and lessons

### Recommended approach: orchestrator in `search.py`, not a new module

**Recommendation: rewire `server/handlers/search.py` directly.** Three reasons:
1. The handler is already the assembly point: it acquires `embed_semaphore`, encodes the query, writes the wire envelope. Adding BM25 → RRF → Rerank inline keeps the call chain visible.
2. A separate `server/retrieval/hybrid.py` orchestrator splits ownership for one consumer (the handler) and one test (the eval). Premature abstraction.
3. The eval test can construct `Resources.startup(Config(enable_rerank=...))` and call `handle_search_papers` directly (it's an async function, not a FastAPI dependency), exercising the same code path the live server runs.

The handler change:
- Replace lines 105-117 (encode + single-column ANN) with: `bm25_cands, _w = r.bm25_phase.query(query, top_n=200)`; `query_vec = await encode_query(query)` (need it for rerank); `fused = await r.ann_phase.query(query, bm25_cands, top_n=50)`; `reranked = await r.rerank_phase.rerank(query, query_vec, fused, top_k=k)`; then fetch body+meta for the top-k chunk_ids via `chunks_table.search().where(f"chunk_id IN (...)")`.
- Set `retrieval_mode` to one of `"hybrid"` (rerank off) or `"hybrid+rerank"` (rerank on) so the wire surface and the snippet contract test still pass.
- ANN already encodes (`ann.py:389`); the singleflight in `query_encoder` collapses the duplicate encode call so the second `await encode_query(query)` for the rerank path is free.

### Latency instrumentation

The brief says "p95 ≤ 2 s at k=10". The brief also says: "Latency p95 for the full pipeline (with rerank if enabled) is ≤ 2 seconds at k=10 on the seed corpus". **Measure at the handler boundary** with `time.perf_counter()` around the four stages: encode, BM25, ANN+RRF, Rerank, fetch+envelope. Emit per-query latency into the per-query JSONL (extend `_run_queries_against_corpus` to record `phase_latency_ms: {bm25, ann, rerank, total}`). Aggregate p50/p95 in `score_and_write` and write into `aggregate-<v>.json`.

### `ARXMCP_ENABLE_RERANK` decision protocol

Default is `False` (`server/config.py:106`). Procedure:
1. Run `pytest tests/eval/test_retrieval_quality.py --hybrid --ndcg-min=0.80` (rerank OFF). If pass → leave `enable_rerank=False`. Document in report.
2. If fail, run `pytest ... --hybrid --rerank --ndcg-min=0.80`. If pass → flip `enable_rerank: bool = True` (line 106). Document.
3. If both fail, the milestone blocks; do NOT lower the threshold. Per `TIER-GATES.md:158-162`, "the retrieval pipeline is debugged before Tier-2 begins."

### Three flags, two semantics

`--ndcg-min` (existing) + `--hybrid` (new, opt-in to BM25+ANN+RRF) + `--rerank` (new, opt-in to phase 3, requires `--hybrid`). The default test run (`pytest`) stays dense-only against threshold 0.70 so existing CI doesn't regress. The new gate command flips both flags. **`--rerank` without `--hybrid` should error** (mutually-coherent contract; reranking only RRF candidates is the design).

### Reranker model is 2.3 GB

Brief explicit. Documenting prerequisite in `docs/retrieval-quality-report.md` is mandatory: "running with `--rerank` requires `BAAI/bge-reranker-v2-m3` snapshot present at `~/.cache/huggingface/hub/`". The model loads via `Resources.startup(Config(enable_rerank=True))` which calls `_load_reranker_or_raise()` — that DOWNLOADS on first run.

### Phantom-ids tolerance

`server/retrieval/ann.py:330-337` documents that ANN does not cross-check BM25 ids; `rerank.py:55-60` silently drops phantoms. Both are fine for the eval — the harness only cares about chunk_ids that round-trip to the corpus.

### Mark `@pytest.mark.eval` and exclude by default

Brief: "marked `@pytest.mark.eval` and excluded from the default test run". Today neither is true. E07_S04 must:
1. Register `eval` in `pyproject.toml:118-120` markers.
2. Decorate the test (`@pytest.mark.eval` above `def test_retrieval_quality`).
3. Add `-m "not eval"` to `addopts` so `make test` excludes it. The Tier-0 gate (`make eval`) and the new Tier-1 invocation explicitly select it.

## 3. External sources

- **nDCG metric (TREC-IR convention).** `DCG_p = sum_{i=1..p} (2^rel_i - 1) / log2(i+1)`; `nDCG_p = DCG_p / IDCG_p`. The harness uses `tests/eval/metrics.py:ndcg_at_k` — confirm it matches the binary-relevance form OR the graded form in `queries.json`. The brief lists the curator can assign multi-grade relevance (`relevance` field per chunk).
- **pytest custom flags.** `parser.addoption(...)` is called from `conftest.py:pytest_addoption` and surfaces fixtures via `request.config.getoption(...)`. Pattern already used at `conftest.py:33-43` for `--ndcg-min`; mirror it.
- **MCP tool result semantics.** `CallToolResult.structuredContent` plus `content[0]` JSON-pretty print plus `content[1..N]` ResourceLink (E06_S04). The retrieval-mode swap does not change the wire shape — only the `retrieval_mode` string + the actual candidate ranking change.
- **RRF k=60 default.** Cormack/Clarke/Büttcher SIGIR 2009. Pinned in `server/retrieval/rrf.py:53` (RRF_K).
- **BGE-reranker-v2-m3.** HuggingFace `BAAI/bge-reranker-v2-m3`. Cross-encoder (single sequence-pair logit). Pinned SHA `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e` in `server/retrieval/rerank.py:116`.

## Open questions

1. **The 20-query fixture is empty.** `tests/eval/fixtures/queries.json` ships as `{"queries": []}`. Without curation, `pytest --hybrid --rerank --ndcg-min=0.80` will SKIP, not pass — AC #1 cannot be satisfied. **The implementer must either (a) escalate to a human curator to populate 20 triples per `docs/eval-curation.md`, or (b) re-scope E07_S04 to land the harness changes only and defer the actual gate run.** Recommend (b) with a `BLOCKED` state until curation lands.
2. **Seed corpus state.** The harness needs `corpus-version.json` present. Verify whether a seed corpus has been ingested in the worktree (`var/arxmcp/index/lancedb/corpus-version.json` existence). If not, the gate also SKIPs.
3. **Rerank's `query_vec` argument.** `RerankPhase.rerank` requires the query vector for the singleflight key. `ANNPhase.query` encodes internally (line 389) and does not return the vector. The handler must call `encode_query(query)` separately (the singleflight collapses the duplicate so cost is one forward pass). Confirm acceptable, or propose `ANNPhase.query` return `(fused, query_vec)`.
4. **Latency measurement under `pytest-asyncio`.** `time.perf_counter()` around `await` is correct on a single event loop. Confirm the test still uses one loop per run (E05_S02 F2 fix in `_run_queries_against_corpus` uses `asyncio.new_event_loop()` once — preserve that).
5. **Reranker enable in eval.** The harness should construct `Resources.startup(Config(enable_rerank=request.config.getoption("--rerank")))` so the test's `--rerank` flag actually toggles model load. Confirm the `Resources` lifecycle is run once per pytest session (use a session-scoped fixture).

## External writes the implementation will require

None. Pure-internal changes:
- `tests/eval/test_retrieval_quality.py` (modify — add `@pytest.mark.eval`, hybrid/rerank branches, latency instrumentation)
- `tests/conftest.py` (modify — add `--hybrid` / `--rerank` flags + fixtures)
- `server/handlers/search.py` (modify — rewire to BM25 → ANN+RRF → Rerank via `Resources.{bm25,ann,rerank}_phase`)
- `server/config.py` (modify — possibly flip `enable_rerank` default; decided by eval results)
- `pyproject.toml` (modify — register `eval` marker, add `-m "not eval"` to addopts)
- `docs/retrieval-quality-report.md` (new — per-phase nDCG lift, p50/p95 latency, reranker necessity finding)
- `TIER-GATES.md` (modify — update Tier-1 → Tier-2 row to cite the new flag surface)
- `Makefile` (optional — add `make eval-tier1` shortcut)

No git push, PR creation, ticket mutation, or third-party API call. The only HTTP-egress side-effect is the BGE-reranker safetensors download from HuggingFace Hub on first `--rerank` run — operator-machine read pattern, same as the embedder.
