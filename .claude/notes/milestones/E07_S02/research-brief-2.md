# E07_S02 — Research Brief 2

## 1. In-codebase context

### Both embedding columns ARE populated, but the brief mis-states the encoder strategy

Both `embedding_stmt` and `embedding_proof` are populated by a SINGLE BGE-M3 encoder over the chunk's `preamble + "\n\n" + body_text`. There is **no** "prose encoder" vs "LaTeX encoder" — there is exactly one model (`BAAI/bge-m3` pinned at `BGE_M3_COMMIT_SHA`, `ingest/embedder.py:112`), routed by chunk `kind`:

> "Routing. `kind == "proof"` → `embedding_proof`; everything else (`stmt`, `section`, `definition`, `lemma`, `proposition`, ...) → `embedding_stmt`. The third column `embedding_eq` is reserved for E10_S03 and is always NULL — the embedder never populates it." (`ingest/embedder.py:19-22`)

`05-storage-and-indexing.md:282` makes the kind-gating explicit: *"The original `embedding_prose` / `embedding_latex` dual columns are replaced by `embedding_stmt` (nullable; set for `kind="stmt"` chunks) and `embedding_proof`"*. The brief's "prose-only, math stripped to `[MATH]` tokens" / "raw LaTeX with expanded macros" framing is **stale design language** that no longer reflects the implementation. Per `_build_embed_input` (`ingest/embedder.py:311-328`), the embedder NFC-normalizes `preamble + body_text` and feeds it whole to BGE-M3 — no math-stripping, no LaTeX-macro variant.

**Implication for E07_S02.** Query encoding requires exactly ONE call to `encode_query(query_text)`, not two. Both ANN searches use the SAME query vector against `embedding_stmt` and `embedding_proof`. This contradicts the brief's "the query text is embedded twice" and "Both embedding calls go through the shared `Singleflight` wrapper". The implementer should call `encode_query` once and reuse the vector.

### HNSW indexes exist on both columns

`ingest/store.py:411-435` creates `IVF_HNSW_SQ` indices on BOTH `embedding_stmt` and `embedding_proof` after every `write_chunks` (with `num_partitions=1, m=16, ef_construction=200`), gated by `_count_non_null(tbl, column) > 0`. A column with zero non-null rows is skipped (recorded as `False` in the `indices_created` dict — `store.py:417-422`). For the seed corpus (E04_S03 shipped), both indices exist whenever both kinds of chunks are present. Distance type defaults to L2; `store.py:407-408` confirms *"BGE-M3 vectors are L2-normalized so l2 and cosine produce identical rankings."*

### Query encoder API: single vector

`server/query_encoder.py:284`: `async def encode_query(query_text: str) -> np.ndarray` — returns ONE 1024-dim float32 L2-normalized vector. `server/handlers/search.py:107` calls it once: `query_vec = await encode_query(query)`. Score conversion in `_distance_to_score`: `1 - _distance / 2` (yields cosine similarity in [0,1] for unit-normalized vectors — `search.py:260-264`).

### Singleflight semantics — only ONE encode per (query) anyway

`server/query_encoder.py:205-227`: `_canonicalize` is `unicodedata.normalize("NFC", query_text.strip())`. The singleflight key is the canonicalized text. **Two calls with the same `query_text` would coalesce automatically** (`SINGLEFLIGHT_DEDUP_COUNT` increments). So even if the implementer naïvely called `encode_query(query)` twice, only one forward pass would fire. **But you should still only call it once** — the second call only deduplicates within a 100ms window (`DEDUP_WINDOW_S`, `query_encoder.py:97`) and would needlessly burn the dedup counter that the brief's AC tries to verify.

The generic `Singleflight` class at `server/resources.py:124-201` is for the reranker (E07_S03), not for the embedder. It's wired into `Resources.rerank_singleflight` (`resources.py:344`) but currently unused.

### BM25Phase return shape and integration

`server/retrieval/bm25.py:534`: `query` returns `tuple[list[tuple[str, float]], list[str]]` — `(candidates, filter_warnings)`. `ANNPhase.query(query_text, bm25_candidates, top_n=50)` per the brief takes `bm25_candidates` as a `list[tuple[str, float]]`, so the **caller** must destructure the BM25 tuple and pass only the first element. The brief's signature accepts a pre-extracted list — `ANNPhase` does NOT call `BM25Phase.query` itself.

### Test fixture pattern to mirror

`tests/retrieval/test_bm25.py:74-197`: `_curated_corpus` (5 targets + 25 decoys), `_embeddings_for` (random L2-normalized 1024-dim vectors so `write_chunks` succeeds — line 149-165), `_seeded_lancedb` (writes via `write_chunks`, returns `(lancedb_path, version)`), `_bm25_phase` (calls `BM25Phase._sync_startup`). For `test_ann.py`, mirror this exactly but ALSO populate `chunks_proof` so `embedding_proof` has rows for the dual-ANN path. The current `_embeddings_for` only writes `chunk_ids_stmt` (line 161-163: `chunk_ids_proof=[]`); the new fixture must include at least one `kind="proof"` chunk and a non-empty `embedding_proof` array.

### `/debug/cache-stats` does NOT exist

`grep -r "/debug/cache-stats"` in `server/` returns nothing. It's only referenced in `.claude/notes/07-multi-agent-caching.md:312` and the open-todo at `.claude/notes/09-feature-priorities.md:70`. The brief's AC4 *"verifiable via the singleflight hit counter in /debug/cache-stats"* is **not satisfiable as written** — the test must read `server.query_encoder.get_singleflight_dedup_count()` directly (the thread-safe getter, `query_encoder.py:187`) or `qe_mod.SINGLEFLIGHT_DEDUP_COUNT`.

## 2. Prior decisions and lessons

### Recent log

E07_S01 (`8f127cf`, `89dae1e`) shipped `BM25Phase` with the documented contract drift to `tuple[list, list]` (synthesis D9 reconciled per E07_S01 critique F5). E04_S03 (`6d12138`, `01adfce`) shipped the corpus-version marker — `Resources.startup` reads it and refuses to boot on cold-start (`resources.py:262-269`). E04_S04 (`61ed46c`, `5a14fa5`) shipped `bm25.pkl` + `chunk_ids.json` artifacts. The `Resources.startup` order is: corpus marker → LanceDB open → BGE-M3 warm → reranker (deferred) → BM25Phase. **There is no ANNPhase wiring yet** — E07_S02 must add `Resources.ann_phase` (or simply construct on demand; see Open Q1).

### "Prose encoder vs LaTeX encoder" — single encoder, single representation

Confirmed from `.claude/notes/05-storage-and-indexing.md:282-296` and `ingest/embedder.py:1-22`. The dual-COLUMN strategy is a kind-routed split, not a dual-ENCODER strategy. **The implementer must NOT** introduce a second BGE-M3 instance, a math-stripping tokenizer, or any "LaTeX encoder" abstraction.

### LanceDB search API and scoring

`server/handlers/search.py:113`: `r.chunks_table.search(query_vec, vector_column_name="embedding_stmt").limit(k).to_arrow()` — returns an Arrow table with a `_distance` column. Score conversion is `1 - dist/2` (cosine on unit vectors). Same pattern works for `embedding_proof`. **Performance:** the seed corpus is ~30 chunks; a single ANN search is sub-ms with HNSW. At 200K-chunk scale (per `05-storage-and-indexing.md:337-348`) HNSW with `m=16, ef_construction=200` is the indexed path; the brief's "top-50 per column" is a small enough K that the index is the dominant cost (single-digit ms expected). No empirical numbers in repo yet.

### E04_S03 actually shipped both columns

`ingest/store.py:411-435` creates HNSW indices on BOTH columns when non-empty. The risk note's "degrade gracefully to single-ANN" applies only when a corpus has NO proof chunks (e.g. E07_S01's `_curated_corpus` — all `kind="stmt"`). The implementer must implement the degraded path AND test it (the brief's `tests/retrieval/test_bm25.py` fixture is one such corpus).

### RRF k=60 source

`05-storage-and-indexing.md:328` quotes `k=60` directly: *"Reciprocal Rank Fusion (k=60) across the Phase-1 BM25 list and both ANN lists. Take top-50."* The value `k=60` is the canonical default from Cormack, Clarke & Büttcher (SIGIR 2009, "Reciprocal Rank Fusion outperforms Condorcet and individual Rank Learning Methods"); not arbitrary. Mirror as a module-level constant `RRF_K = 60` in `server/retrieval/rrf.py`.

### Function signature: caller provides BM25 list

Brief deliverable: `ANNPhase.query(query_text, bm25_candidates, top_n=50)`. The AC `bm25_candidates=[]` confirms the caller passes the pre-extracted list (and may pass empty for symbolic-only queries). `ANNPhase` does NOT depend on `BM25Phase` — it is a peer phase. Wiring lives outside (in a future `HybridSearch` orchestrator, not part of E07_S02).

## 3. External sources

- **Cormack, Clarke & Büttcher (2009)** — "Reciprocal Rank Fusion outperforms Condorcet and individual Rank Learning Methods" (SIGIR 2009). Section 3 defines `score(d) = sum_i 1/(k + rank_i(d))` and recommends `k=60` empirically. Same formula, same constant — verbatim adoption is correct.
- **LanceDB Python docs** — `Table.search(query, vector_column_name=...)` returns a `Query` builder; `.limit(k).to_arrow()` materializes results with a `_distance` column. With `IVF_HNSW_SQ` index present, search is HNSW-backed; without it, brute-force.
- **BGE-M3 model card (BAAI/bge-m3)** — single-model multi-functionality (dense + sparse + colbert); the codebase uses dense only (CLS pool + L2 normalize, `ingest/embedder.py:405-410`).

## Open questions

1. **Where does `ANNPhase` live in `Resources`?** Brief says "initialized once at server startup". Recommend: add `Resources.ann_phase: ANNPhase | None = None` and instantiate in `Resources.startup` after `bm25_phase` (line ~340 of `resources.py`). Constructor takes `chunks_table` only (no per-request state). The handler in `server/handlers/search.py` is NOT yet rewired to use phases — that integration is presumably E07_S04. E07_S02 just lands the class.
2. **Test for AC4 (singleflight verification).** Since `/debug/cache-stats` doesn't exist, the test must call `server.query_encoder.get_singleflight_dedup_count()` before/after `ANNPhase.query` and assert the counter behavior. **Concrete recommendation:** call `_reset_for_tests()` (line 374), then call `ANNPhase.query(text)` once and assert `get_singleflight_dedup_count() == 0` (no dedup, only one encode). If the implementer follows this brief and calls `encode_query` exactly once per query, the dedup counter will not increment — the AC's literal "Both embedding calls go through the shared Singleflight wrapper" is best satisfied by ONE call (which IS through the wrapper) rather than two redundant calls.
3. **RRF input list shape.** `reciprocal_rank_fusion(lists, k=60)`: should each list be `list[str]` (chunk_ids only, ranked) or `list[tuple[str, float]]` (with scores)? RRF ignores the source scores by definition (only ranks matter). Recommend: accept `list[Sequence[str]]` for clarity. The caller maps `[(cid, _) for cid, _ in bm25_candidates]` and `[cid for cid, _ in ann_stmt_results]` etc. — minor adapter.

## External writes the implementation will require

Zero. No git pushes, no PR creation, no ticket mutations, no infra changes, no third-party API calls. Pure in-process Python; tests run against tmp_path-scoped LanceDB fixtures.
