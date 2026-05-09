# E07_S02 — Research Brief 1 (Phase-2 dual-ANN + RRF)

## 1. In-codebase context

### Design constitution: `.claude/notes/05-storage-and-indexing.md`

The 2026-05-06 update **supersedes the brief's wording**. Quote the rules:

- Lines 53-57: *"the original `embedding_prose` / `embedding_latex`
  dual columns are replaced by `embedding_stmt` (nullable; set for
  `kind="stmt"` chunks) and `embedding_proof` (nullable; set for
  `kind="proof"` chunks). Embedding dimension is fixed at 1024
  (BGE-M3)."*
- Lines 60-61: HNSW knobs — *"HNSW on `embedding_stmt` (M=16,
  efConstruction=200). HNSW on `embedding_proof` (M=16,
  efConstruction=200)."*
- Lines 286-296 (the controlling RRF spec): the two embeddings are
  **kind-gated**, not query-time dual-encoded. *"`embedding_stmt`
  (set for `kind="stmt"` chunks): preamble + statement text, ≤512
  tokens... `embedding_proof` (set for `kind="proof"` chunks):
  preamble + statement header + proof window, ≤512 tokens with
  64-token overlap... Retrieval fuses both via Reciprocal Rank
  Fusion at query time over `embedding_stmt` ANN and `embedding_proof`
  ANN results."*
- Lines 322-331 (the three-phase pipeline): *"Phase 2 (medium): Dual
  ANN search — one query embedding over `embedding_stmt` and one
  over `embedding_proof`, top-50 each. Reciprocal Rank Fusion (k=60)
  across the Phase-1 BM25 list and both ANN lists. Take top-50."*

### Embedder contract: `ingest/embedder.py`

- One model only: BGE-M3 pinned at `BGE_M3_COMMIT_SHA` (line 112);
  `EMBEDDING_DIM=1024` (line 122).
- Routing rule (lines 952-960): `kind == "proof"` →
  `embedding_proof`; everything else (stmt, section, definition,
  ...) → `embedding_stmt`. **Same encoder, different chunks.**
- Per the schema invariant in `ingest/schema.py:135-138`, *"a chunk_id
  appears in EXACTLY ONE of the two lists (never both, never
  neither)."*

### Singleflight contract: `server/query_encoder.py`

- `encode_query(query_text: str) -> np.ndarray` — single text →
  single 1024-dim float32 L2-normalized vector (lines 284-366).
- Canonical key: `unicodedata.normalize("NFC", query.strip())`
  (line 227). **Two callers with the same canonical key share one
  forward pass; different keys do not coalesce.**
- Counter source: `get_singleflight_dedup_count()` (lines 187-197);
  exposed via `/metrics` as
  `arxmcp_embed_singleflight_dedup_total` (per `server/health.py:79`).
  **There is no `/debug/cache-stats` endpoint** — the brief AC #4 is
  unobservable through that path; it is observable through `/metrics`
  + the in-process getter.

### Lifecycle: `server/resources.py`

- `Resources.embed_semaphore` (line 225) bounds DISTINCT-query
  concurrency BEFORE the singleflight (lines 22-32).
- `Resources.bm25_phase` (line 230) is duck-typed; populated by
  `BM25Phase.startup` at lines 323-339.
- `Resources.startup` is the place to construct `ANNPhase` (no
  dependencies it lacks: `chunks_table` is open at line 287,
  `bm25_phase` at line 331).

### BM25 contract: `server/retrieval/bm25.py`

- Return shape (lines 534, 549-557):
  `tuple[list[tuple[str, float]], list[str]]`. **First element**
  (the `(chunk_id, score)` candidate list) is what RRF consumes.
  The implementer MUST destructure: `bm25_candidates, warnings =
  resources.bm25_phase.query(text)`. **Propagate `warnings`** into
  the search-handler envelope (research-synthesis D9).
- Default `top_n=200` (`DEFAULT_TOP_N`, line 102) matches the design
  note line 325 ("Take top-200").
- Per the synthesis (line 25), `BM25Phase.query` is a SYNC method;
  CPU-bound but sub-millisecond at seed scale — call directly, no
  `asyncio.to_thread` needed.

### Existing search handler: `server/handlers/search.py`

- The dense-only path is at `lines 105-117`:
  ```python
  async with r.embed_semaphore:
      query_vec = await encode_query(query)
  arrow = (
      r.chunks_table.search(query_vec, vector_column_name="embedding_stmt")
      .limit(k * 5 if level != "theorem" else k)
      .to_arrow()
  )
  ```
  **Integration seam for E07_S02:** REPLACE `lines 105-129` (the
  semaphore + encode + single search + dedup) with a call to
  `ANNPhase.query(query, bm25_candidates, top_n=k * 5)`, then run the
  existing `_dedup_keep_best` and `_arrow_to_rows` over the fused
  list. Result envelope (lines 143-153) needs `retrieval_mode`
  changed from `"dense_only"` to `"hybrid_rrf"` and the
  `excluded_kinds` field re-thought (proof chunks now ARE retrieved
  by RRF). **NB: the brief says E07_S02 owns the
  ANNPhase only; the handler-rewrite may be a separate ticket** —
  confirm via state.json or sequence.

### LanceDB API surface

Single-vector search, two calls:
`tbl.search(vec, vector_column_name="embedding_stmt").limit(50)
.to_arrow()` and again with `"embedding_proof"`. **No batched
two-vector search exists in the LanceDB Python API as of 0.30.**
L2 distance on unit vectors → cosine similarity; the existing
`_distance_to_score` helper at `server/handlers/search.py:260-264`
does `1 - dist/2` for that conversion. Reuse it.

### Test pattern: `tests/retrieval/test_bm25.py`

- Fixture pattern (lines 168-197): `_bm25_root` (monkeypatched
  artifact root) + `_seeded_lancedb` (real `write_chunks` corpus) +
  `_bm25_phase` (built sync via `BM25Phase._sync_startup`).
- For `test_ann.py`: build a real seeded LanceDB with **both**
  `kind="stmt"` and `kind="proof"` chunks (current `_curated_corpus`
  ships only stmt — extend it). Use random L2-normalized vectors;
  the AC tests structure, not retrieval quality.

## 2. Prior decisions and lessons — questions resolved

**Q: Two encoders or one?** ONE encoder, two columns. Schema note
05 lines 53-57 and the embedder routing at `ingest/embedder.py:952-960`
agree. The brief's "prose encoder" / "LaTeX encoder" wording is
**fictional / superseded**. At query time the SAME `encode_query`
output vector is fed to both column searches.

**Implication for the singleflight AC.** The brief AC #4 ("Both
embedding calls go through the shared Singleflight wrapper") is
SATISFIED TRIVIALLY — there is only ONE encode call per query. Two
ANN searches against ONE query vector. Update the AC interpretation
in the implementation summary; verify via the dedup counter NOT
incrementing for a single-query path (it only increments on
duplicate concurrent calls).

**Q: Two-vector LanceDB search?** No. Two sequential
`tbl.search(...).vector_column_name(...).limit(50).to_arrow()`
calls. They CAN be parallelized via `asyncio.to_thread` /
`gather`, but the seed-scale latency is sub-10ms each — sequential is
fine for v1; document the parallel-fan-out as a future
optimization.

**Q: Does `embedding_proof` actually have rows in the seed
corpus?** Verified via `ingest/store.py:411-422`: when a column has
zero non-null rows, HNSW build is skipped and `created["hnsw_proof"]
= False`. The risk note in the brief is real — `ANNPhase.query`
MUST handle `chunks_table.search(..., vector_column_name=
"embedding_proof")` returning zero rows (or raising) gracefully.
Treat empty proof results as an empty ranked list, RRF-fuse the rest.

**Q: Is k=60 the canonical RRF default?** Yes, per
Cormack-Clarke-Buettcher 2009 (see §3 below). `.claude/notes/05-storage-and-indexing.md:328`
literalizes this: *"Reciprocal Rank Fusion (k=60)."* No deviation.

**Q: Which observability surface for AC #4?** The only existing
hook is `get_singleflight_dedup_count()` at
`server/query_encoder.py:187`. Test by issuing TWO concurrent
identical queries and asserting the counter increments by 1.

## 3. External sources

- **RRF original paper.** Cormack, Clarke, Buettcher, "Reciprocal
  Rank Fusion outperforms Condorcet and individual Rank Learning
  Methods" (SIGIR 2009). Formula and `k=60` default both originate
  here.
- **LanceDB Python API 0.30**:
  `Table.search(query_vector, vector_column_name="embedding_stmt")
  .limit(k).to_arrow()` returns a PyArrow table with all source
  columns plus a `_distance` column.
- **BGE-M3** (BAAI). Single transformer (XLM-RoBERTa-large, 1024
  hidden); CLS-pool + L2-normalize for the dense embedding. ONE
  model, not a "prose encoder" + "LaTeX encoder" pair.
- **MCP design notes** §06-mcp-server-design.md govern result
  determinism; fused score ordering must remain `(score_desc,
  chunk_id_asc)` to keep cross-agent prompt-cache hits viable.

## Open questions

1. **Handler integration timing.** Does E07_S02 also wire `ANNPhase`
   into `server/handlers/search.py` (replacing the dense-only block
   at lines 105-129), or is that handler swap deferred to a later
   ticket? The deliverables list only `ANNPhase`/`rrf.py`/test
   files. **Recommended: ship `ANNPhase` standalone, add an
   `ANNPhase.startup` classmethod analogous to `BM25Phase.startup`,
   wire in a follow-up task.** The brief's risk note about
   "REPLACE the dense-only logic in this handler later" supports
   deferring.
2. **BM25-empty fallback semantics.** AC #1 says
   `bm25_candidates=[]` must still return ≥ 1 result. The synthesis
   answer: pass only the two ANN lists to `reciprocal_rank_fusion`
   and skip BM25 from the fusion entirely. Trivial; mention in test.
3. **Proof-column-empty handling.** When `embedding_proof` HNSW
   index does not exist (seed corpus, all stmt), the search call
   may either return empty Arrow OR raise. Wrap the proof search in
   a try/except and degrade to single-ANN + BM25 RRF (matches the
   brief's risk note).

## External writes the implementation will require

**Zero.** Pure-Python additions under `server/retrieval/` and
`tests/retrieval/`. No git push, PR creation, ticket mutation,
infra change, or third-party API call. All artifacts live under
already-existing var paths.
