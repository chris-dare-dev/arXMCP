# E03 — Embedder (NEW)

**Epic dependencies:** E02 (chunker produces `body_text`, `preamble_ref`, `chunker_version` on all chunks).

**Goal:** Encode each chunk's embedding-input view (preamble text prepended to `body_text`) with a self-hosted BGE-M3 model pinned to a specific commit SHA, writing results into two LanceDB columns — `embedding_stmt` for statement chunks and `embedding_proof` for proof-window chunks — plus a reserved nullable `embedding_eq` column for the equation index (E10). The embedder is idempotent, handles concurrent query encoding via a singleflight wrapper, and documents GIL interaction explicitly. No Voyage or any other provider is used; BGE-M3 serves both index-time and query-time encoding.

**Effort:** ~1.5 weeks calendar (M+S+M across three milestones).

**References:** `05-storage-and-indexing.md` § Embedding strategy (BGE-M3, 1024-dim, dual columns, HNSW parameters), `08-security-observability-ops.md` § Threat 6 (pinned model SHA, supply-chain security), `04-parsing-and-chunking.md` § Token budgets (512-tok max per embedding input).

---

### E03_S01 — `ingest/embedder.py` dual-column BGE-M3 encoder

**Status:** NEW
**Tier:** 0
**Effort:** M
**Dependencies:** E02_S01, E02_S02, E02_S04, E04_S01

**Description.** The embedder loads `BAAI/bge-m3` from a pinned HuggingFace commit SHA (the SHA is defined as a constant `BGE_M3_COMMIT_SHA` in `ingest/embedder.py` and must match the SHA pinned in the project's security manifest per `08-security-observability-ops.md` Threat 6). Loading from a floating tag like `"BAAI/bge-m3"` without a SHA is forbidden — it allows silent model substitution between runs, which would invalidate cached embeddings without a version bump.

Encoding proceeds in batches over all chunks in the LanceDB table (E04_S01). For each chunk, the embedding input is constructed as: `preamble_text + "\n\n" + body_text`, where `preamble_text` is read from `var/arxmcp/corpus/preamble/<paper_id>/preamble.json` via the `preamble_ref` hash. This view is what BGE-M3 encodes — it is never stored as a separate column; `body_text` in the table always contains only the raw chunk body.

Routing: for a chunk with `kind="stmt"`, the 1024-dimensional output vector is written to `embedding_stmt`; `embedding_proof` is left NULL. For `kind="proof"`, the vector is written to `embedding_proof`; `embedding_stmt` is left NULL. For `kind="section"` or `kind="definition"`, the vector is written to `embedding_stmt` (the primary search column) and `embedding_proof` is left NULL. A third column `embedding_eq` (1024-dim, nullable FixedSizeList<float32, 1024>) is reserved for the equation embedding index (E10_S03) — the embedder writes it as NULL for all rows and must not populate it.

Batch size defaults to 32 chunks. On CPU, this produces acceptable throughput for the 50-paper seed corpus. GPU acceleration is an E11 concern. The embedder logs per-paper throughput (chunks/sec) to `var/arxmcp/ops/embed-stats.jsonl` for comparison against E11's scale targets.

**Deliverables.**
- `ingest/embedder.py` — public API: `embed_corpus(lancedb_path: str, corpus_path: str, batch_size: int = 32) -> EmbedStats`
- `BGE_M3_COMMIT_SHA` constant defined in `embedder.py` (must match security manifest)
- `var/arxmcp/ops/embed-stats.jsonl` — per-run throughput log
- `pytest tests/test_embedder.py` — integration test: embed 5 chunks, assert vector shape (1024,), assert correct column routing

**Acceptance criteria.**
- [ ] Model loaded from pinned commit SHA, not floating tag. `BGE_M3_COMMIT_SHA` is defined exactly once.
- [ ] `kind="stmt"` chunks have non-null `embedding_stmt` and null `embedding_proof` after a run.
- [ ] `kind="proof"` chunks have non-null `embedding_proof` and null `embedding_stmt` after a run.
- [ ] `embedding_eq` is null on all rows after a run (reserved for E10).
- [ ] All embedding vectors have shape `(1024,)` and are L2-normalized (BGE-M3 default).
- [ ] Embedding input = `preamble_text + "\n\n" + body_text` does not exceed 512 BGE-M3 tokens (enforced by an assertion that logs a warning and truncates to 512 tokens rather than raising — truncation should be extremely rare if E02_S01 budget enforcement is correct).
- [ ] `embed-stats.jsonl` entry written per run, including paper count, chunk count, wall-clock seconds, and the pinned `BGE_M3_COMMIT_SHA`.
- [ ] Integration test passes without GPU (CPU-only mode).

**Out of scope.** Idempotent skip logic (E03_S02). Singleflight for query encoding (E03_S03). HNSW index creation (E04_S01). Query-time encoding (E06 / Sonnet B).

**Risk notes.**
- **Closes H3** (dual 512-tok columns): the two-column routing enforced here, combined with E02_S01's token budget enforcement and E04_S01's schema, is the complete fix. Reviewers can confirm H3 closure by tracing: E02_S01 (chunk budget) → E03_S01 (column routing) → E04_S01 (schema).
- **Closes H8** (BGE-M3 same model for index and query, no Voyage): this milestone uses BGE-M3 for index-time encoding. E06 (Sonnet B) uses the same `BGE_M3_COMMIT_SHA` constant for query-time encoding. Using a different model for index vs query would invalidate all cosine similarity scores. The constant is shared via `ingest/embedder.py` import to enforce this.

**Labels.** `area:embedder`, `kind:feature`, `tier:0`.

---

### E03_S02 — Idempotent re-embed

**Status:** NEW
**Tier:** 0
**Effort:** S
**Dependencies:** E03_S01, E02_S04

**Description.** The embedder must be safe to re-run without duplicating work or corrupting existing embeddings. This milestone adds skip logic: before encoding a chunk, the embedder checks whether the target embedding column is already populated AND whether the chunk's `chunker_version` matches the expected input version for the current embedder. If both conditions hold, the chunk is skipped.

The expected input version is defined as a constant `EXPECTED_CHUNKER_VERSION = "v1.0"` in `ingest/embedder.py`. If a chunk has `chunker_version != EXPECTED_CHUNKER_VERSION`, it must be re-embedded even if a vector is already present (because the chunk content may have changed). This version coupling is the MVCC handshake: a `chunker_version` bump (e.g. to `"v1.1"`) forces re-embed of all affected rows via the MVCC writer in E04_S02.

The skip logic is implemented as a pre-flight query over the LanceDB table: `SELECT chunk_id, chunker_version FROM chunks WHERE embedding_stmt IS NOT NULL OR embedding_proof IS NOT NULL`. This is fast (scalar scan, no vector load) and produces the set of already-embedded chunk IDs. The main encode loop skips any `chunk_id` in this set with a matching `chunker_version`.

Re-running the embedder on a stable corpus (no chunker version bump, no new papers) should produce zero LanceDB write operations and log a summary: `"Skipped N/N chunks — all up to date."` This idempotency is tested explicitly.

**Deliverables.**
- Updated `ingest/embedder.py` — skip logic added to `embed_corpus`
- `EXPECTED_CHUNKER_VERSION` constant in `embedder.py`
- `pytest tests/test_embedder_idempotent.py` — test: run embed twice, assert second run writes 0 rows

**Acceptance criteria.**
- [ ] Re-running on an unchanged corpus writes 0 rows and logs "all up to date".
- [ ] Changing a chunk's `chunker_version` to a mismatched value in a test fixture causes that chunk to be re-embedded on the next run.
- [ ] New chunks added since the last embed run are embedded on the next run (existing chunks with correct version are skipped).
- [ ] `EXPECTED_CHUNKER_VERSION` is defined as a constant in exactly one place.
- [ ] No race condition: if two embedder processes run concurrently on the same corpus, neither corrupts the other's rows (LanceDB's MVCC writer serializes writes; document this in the module docstring).

**Out of scope.** MVCC version management (E04_S02). BM25 index re-build on version bump (E04_S04). GPU acceleration (E11).

**Risk notes.**
- The idempotency guarantee is load-bearing for E11's scale-out: at 200K papers, re-embedding from scratch on every ingestion run would be prohibitively slow. The version-aware skip logic must be in place before E11 begins.

**Labels.** `area:embedder`, `kind:feature`, `tier:0`.

---

### E03_S03 — Singleflight wrapper for query encoding

**Status:** NEW
**Tier:** 0
**Effort:** M
**Dependencies:** E03_S01

**Description.** The MCP server (E06, Sonnet B) encodes each incoming `search_papers` query string using BGE-M3 before running ANN against the LanceDB table. Under concurrent load — for example, when multiple sub-agents in a multi-agent proof pipeline submit queries within the same 100ms window — naive per-request encoding would submit redundant forward passes to the model. The singleflight wrapper coalesces these: if two concurrent calls to `encode_query(query_text)` arrive with the same query string within 100ms of each other, only one BGE-M3 forward pass is issued and the result is shared.

Implementation uses a per-process dictionary mapping `query_text → asyncio.Future[np.ndarray]`. The first caller for a given query creates the Future and submits the encode task to a `ThreadPoolExecutor`. Subsequent callers within the deduplication window `await` the same Future. When the encode task completes, the Future is resolved and all waiters receive the result. Completed entries are evicted after 100ms (a `asyncio.get_event_loop().call_later` cleanup).

GIL interaction: BGE-M3's forward pass is implemented in PyTorch. PyTorch releases the GIL during the C++/CUDA kernel execution (both CPU and GPU paths). This means a `ThreadPoolExecutor` is sufficient and correct for concurrent encoding — the GIL is not held during the numerically expensive portion of the forward pass. This is documented explicitly in the module docstring with a reference to `torch.no_grad()` and PyTorch's GIL release semantics.

The singleflight wrapper is implemented in `server/query_encoder.py` (a server-layer module, not `ingest/`), because it is a runtime concern, not an ingestion concern. It imports `BGE_M3_COMMIT_SHA` from `ingest/embedder.py` to ensure the same model version is used.

**Deliverables.**
- `server/query_encoder.py` — `encode_query(query_text: str) -> np.ndarray` (async, singleflight)
- `ThreadPoolExecutor` with 1 worker (model is not thread-safe for concurrent forward passes; the executor serializes BGE-M3 calls while allowing async overlap of the await)
- `pytest tests/test_query_encoder.py` — test: send 10 concurrent encode calls with the same string, assert the model forward pass is invoked exactly once (mock the model)
- Module docstring: GIL release documentation and rationale for ThreadPoolExecutor

**Acceptance criteria.**
- [ ] 10 concurrent `encode_query("test query")` calls result in exactly 1 BGE-M3 forward pass (verified by mock call count in test).
- [ ] Each concurrent caller receives the identical numpy array (same object or byte-identical copy).
- [ ] Deduplication window is 100ms; a call arriving 101ms after the first is treated as a new request.
- [ ] Module docstring includes: "BGE-M3 forward pass releases the GIL inside PyTorch's C++ backend; ThreadPoolExecutor is therefore safe for concurrent callers."
- [ ] `BGE_M3_COMMIT_SHA` is imported from `ingest/embedder.py` — not redefined.
- [ ] Integration test (without mock): two calls with the same query string return vectors with cosine similarity ≥ 0.9999 (floating-point identical up to rounding).

**Out of scope.** Query-time BM25 lexical matching (E04_S04, E07 Sonnet B). Reranker (E07 Sonnet B). Server-side caching of full `search_papers` results by corpus_version (E08_S03, Sonnet B).

**Risk notes.**
- **Closes MEDIUM: singleflight on embedder + GIL.** The critique finding flagged both the missing deduplication and the incorrect assumption that Python threads cannot parallelize BGE-M3 calls. This milestone addresses both: the singleflight prevents redundant work, and the GIL documentation corrects the assumption.
- The ThreadPoolExecutor worker count is 1 to prevent true concurrent forward passes (BGE-M3 is not safe for concurrent calls to the same model instance). Parallelism is achieved at the async level (callers await the single in-flight future), not at the model level.

**Labels.** `area:embedder`, `kind:feature`, `tier:0`.
