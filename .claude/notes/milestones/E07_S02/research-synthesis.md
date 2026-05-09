# E07_S02 — Research synthesis

## Both researchers agree on these load-bearing facts

1. **The brief's "prose encoder" / "LaTeX encoder" framing is fictional / superseded.** The codebase has ONE BGE-M3 encoder. The dual columns (`embedding_stmt`, `embedding_proof`) are KIND-ROUTED, not query-encoded differently:
   - `ingest/embedder.py:19-22`: routing is `kind == "proof"` → `embedding_proof`; everything else → `embedding_stmt`.
   - `.claude/notes/05-storage-and-indexing.md:282-296`: "the original `embedding_prose` / `embedding_latex` dual columns are replaced by `embedding_stmt`...and `embedding_proof`".
   - One encoder feeds the chunk's `preamble + body_text` (NFC-normalized) to BGE-M3 verbatim — no math-stripping, no LaTeX-macro variant.

2. **Query encoding is exactly ONE call per query.** `server/query_encoder.py:284`: `encode_query(query_text) -> np.ndarray` returns one 1024-dim L2-normalized vector. Both ANN searches (over `embedding_stmt` and `embedding_proof`) use the SAME query vector against different columns. The brief's "embedded twice" is wrong.

3. **`/debug/cache-stats` does not exist.** Verified by grep. The brief AC #4 ("verifiable via the singleflight hit counter in /debug/cache-stats") is not satisfiable as written. The hit counter is exposed via `server.query_encoder.get_singleflight_dedup_count()` (line 187) and as `arxmcp_embed_singleflight_dedup_total` on `/metrics`.

4. **`BM25Phase.query` returns `tuple[list[tuple[str,float]], list[str]]`.** ANNPhase's `query(query_text, bm25_candidates, top_n=50)` per the brief takes a pre-extracted candidate list — the caller (a future hybrid-search orchestrator) destructures the BM25 tuple and passes only the first element. ANNPhase does NOT depend on BM25Phase.

5. **Both columns ARE indexed in production.** `ingest/store.py:411-435` builds `IVF_HNSW_SQ` indexes on both `embedding_stmt` and `embedding_proof` whenever each column has ≥1 non-null row. Distance type defaults to L2; BGE-M3 vectors are L2-normalized so L2 and cosine produce identical rankings (`store.py:407-408`).

6. **RRF k=60 is the canonical default.** `.claude/notes/05-storage-and-indexing.md:328` quotes it directly: "Reciprocal Rank Fusion (k=60) across the Phase-1 BM25 list and both ANN lists. Take top-50." Cormack-Clarke-Büttcher 2009 SIGIR paper is the source. No deviation.

7. **No two-vector LanceDB search.** Two sequential `tbl.search(vec, vector_column_name=...).limit(k).to_arrow()` calls — one per column. Parallel fan-out is a future optimization.

8. **`ANNPhase` does NOT touch `server/handlers/search.py`.** The handler-rewrite (replacing the dense-only block at `search.py:105-129` with a hybrid call) is deferred to a later milestone (likely E07_S04). E07_S02 ships `ANNPhase` standalone + `Resources.ann_phase` wiring only.

## Decisions for the implementer

| ID | Decision | Rationale |
|---|---|---|
| D1 | **One encode_query call per ANNPhase.query.** Both ANN searches use the same vector against different `vector_column_name` values. | Forced by reality (one encoder); also avoids burning the singleflight dedup counter unnecessarily. |
| D2 | **AC #4 reinterpretation.** Test that the encode call goes through the singleflight (i.e. `encode_query` is called, not the raw embedder). Optionally also test that two concurrent identical queries dedup to 1 forward pass via `get_singleflight_dedup_count()`. | The brief's `/debug/cache-stats` reference is fiction; the in-process getter is the canonical observation surface. |
| D3 | **`reciprocal_rank_fusion(lists, k=60)` signature: `lists: Sequence[Sequence[str]]`** — pure chunk_ids, RRF ignores source scores by definition. Caller adapts BM25's tuple list and ANN's tuple lists into chunk_id lists. | Cleanest contract; matches the original RRF paper. |
| D4 | **Return `list[tuple[str, float]]` from RRF**, sorted (`fused_score_desc`, `chunk_id_asc`). | Brief AC #3 + project determinism convention from `06-mcp-server-design.md` (mirrors `search.py:128`). |
| D5 | **Sequential ANN searches** for v1; document parallel fan-out as a future optimization. | Seed-scale latency is sub-10ms each; sequential is fine. Parallel adds complexity that isn't yet justified. |
| D6 | **Graceful degradation on empty inputs.** Empty `bm25_candidates` → fuse only the two ANN lists. Empty `embedding_proof` results (zero rows OR no HNSW index) → fuse `bm25` + `stmt` only. Both ANNs empty + non-empty BM25 → return BM25 ranked list re-projected through RRF. All three empty → return `[]`. | Brief risk note + AC #1 (pure-ANN fallback when BM25 empty). |
| D7 | **`Resources.ann_phase`** — add a duck-typed field on the dataclass; instantiate in `Resources.startup` AFTER `bm25_phase` (lines ~340 of `resources.py`). Constructor takes only `chunks_table` (no per-request state, no expensive load). | Lifecycle parity with `bm25_phase`; constructor is cheap so no separate `await ANNPhase.startup(...)` async classmethod required. |
| D8 | **Test fixture extends E07_S01's `_curated_corpus`** — must include BOTH `kind="stmt"` AND `kind="proof"` chunks so `embedding_proof` has rows and the dual-ANN path can be exercised. Use random L2-normalized vectors; ANN quality is tested via deterministic cosine similarity, not retrieval relevance. | Brief AC #2 ("RRF output contains candidates from both the BM25 list and both ANN lists") needs both ANN columns populated. |
| D9 | **`RRF_K = 60` as a module-level constant in `server/retrieval/rrf.py`.** Exposed for tests. | Single source of truth. |
| D10 | **Score conversion: `1 - dist / 2`** for L2-on-unit-vectors → cosine in [0,1]. Reuse the existing `_distance_to_score` helper from `server/handlers/search.py:260-264` — extract to `server/retrieval/_helpers.py` (or duplicate; cheaper). | Consistency with the existing dense path; the conversion will be the same in the eventual handler integration. |

## Reinterpreted acceptance criteria

| Brief AC | Reinterpretation | How verified |
|---|---|---|
| `ANNPhase.query("perverse sheaves on flag varieties", bm25_candidates=[])` returns ≥ 1 result | Unchanged | Test seeds non-empty `embedding_stmt`; asserts non-empty result |
| RRF output contains candidates from both BM25 list AND both ANN lists | Unchanged (provided fixture seeds all three) | Test asserts at least one chunk_id from each input source appears in the RRF output |
| `fused_score` values are descending | Unchanged | Test asserts `scores == sorted(scores, reverse=True)` |
| Both embedding calls go through the shared Singleflight wrapper | **Reinterpreted** to "the (single) embedding call goes through the singleflight wrapper" — observable via `get_singleflight_dedup_count()` not `/debug/cache-stats` | Test reads the in-process counter |
| `pytest tests/retrieval/test_ann.py` passes | Unchanged | The whole-suite check |

## Open questions

1. **Helper extraction**: should the `_distance_to_score` helper move to a shared module or stay duplicated? Recommend duplicate for v1 — extraction is a cosmetic refactor that can land alongside the eventual `search.py` handler swap (E07_S04).

2. **`Resources.ann_phase` field naming**: `ann_phase` mirrors `bm25_phase`. Confirm; no alternative recommended.

## External writes the implementation will require

None. Pure-Python additions:
- `server/retrieval/ann.py` (new)
- `server/retrieval/rrf.py` (new)
- `server/retrieval/__init__.py` (modify — re-export new symbols)
- `server/resources.py` (modify — add `ann_phase` field + startup wire-up)
- `tests/retrieval/test_ann.py` (new)

No git push, PR creation, ticket mutation, infra change, or third-party API call. The new code reads only the LanceDB chunks table that `Resources.startup` already opens.
