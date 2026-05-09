# E07_S03 — Research brief 1

## 1. In-codebase context

### Tier-3 cache spec — quoted from `.claude/notes/07-multi-agent-caching.md:155-166`

```
### Tier 3: rerank-set memo

key   = sha256(query_embedding_hash + sorted_candidate_id_tuple_hash + reranker_version)
value = reranked top-k order
ttl   = 1 hour
store = in-process LRU
```

Rationale (line 164): *"when 4 agents ask similar (not identical) questions,
their top-200 candidate sets after Phase-1 BM25 + Phase-2 ANN overlap heavily.
Reranker is the most expensive stage. Hit rates of 40–60% are realistic."*
This Tier-3 store is **separate from the singleflight** — singleflight only
collapses concurrent in-flight calls; the LRU memoizes completed results for an
hour. **The brief only asks for the singleflight wrapper this milestone**;
it does NOT ask for the LRU. Punt the LRU to a follow-up.

### BGE-reranker-v2-m3 reference — `.claude/notes/10-references-and-prior-art.md:154-156`

> *"BAAI/bge-reranker-v2-m3 — `https://huggingface.co/BAAI/bge-reranker-v2-m3`
> Default v1 reranker."*

No commit-SHA pin recorded yet (the embedder pin lives at
`ingest/embedder.py:112`). E07_S03 must add it.

### Three-phase pipeline — `.claude/notes/05-storage-and-indexing.md:329-331`

> *"Phase 3 (expensive): `bge-reranker-v2-m3` local cross-encoder. Gated by
> `ARXMCP_ENABLE_RERANK` environment variable (default `false`). When disabled,
> Phase-2 RRF order is returned directly. Take top-k (default 10, max 50)."*

### `server/config.py` — current state

`enable_rerank: bool = False` already exists at `server/config.py:106` (added in
E06_S01). `max_concurrent_reranks: int = 4` lives at line 120. The
`@field_validator("max_concurrent_embeddings", "max_concurrent_reranks")` at
line 176 enforces `>= 1`. Pydantic-settings forbids extras
(`extra="forbid"`, line 82) so any new env var MUST be a declared field.
**E07_S03 adds `rerank_model_sha: str = "<pinned-sha>"`** (env name
`ARXMCP_RERANK_MODEL_SHA` via the `ARXMCP_` prefix at line 80).

### `server/resources.py` — `_load_reranker_or_raise()` and singleflight

`server/resources.py:425-442` is a **placeholder** that always raises
`RerankerUnavailableError`. The docstring says: *"The actual reranker
integration in E07 will replace this function's body with the real model load
(transformers + sentence-transformers, similar to `ingest.embedder`)."*

`Resources.reranker_model: Any | None = None` at line 228, populated when
`enable_rerank=True` (line 312-314). `Resources.rerank_singleflight:
Singleflight` at line 227 is constructed unconditionally at line 358 and
**ready to consume**. `Resources.rerank_semaphore` at line 226, constructed
at line 357, ready to consume.

The generic `Singleflight` class at `server/resources.py:124-201` has contract:

- `async def run(self, key: str, coro_factory) -> Any` (line 150).
- `coro_factory` is a no-arg callable returning a coroutine (NOT the coroutine
  itself; line 151-153). Per-key `asyncio.shield` discipline isolates caller
  cancellation from the shared task.
- `dedup_count` property at line 198 — incremented on every fast-path hit. This
  is the observation surface; see Open Questions.

### `ingest/embedder.py` — pinned-SHA pattern

`ingest/embedder.py:112` defines `BGE_M3_COMMIT_SHA` as a module-level constant
with the verification recipe in the docstring at lines 108-110:

```
curl -s https://huggingface.co/api/models/BAAI/bge-m3 \
  | python -c "import sys,json;print(json.load(sys.stdin)['sha'])"
```

The constant is consumed by `AutoTokenizer.from_pretrained(..., revision=SHA)`
(line 266) and `AutoModel.from_pretrained(..., revision=SHA, trust_remote_code=False)`
(line 290-294). Threat 6 from `08-security-observability-ops.md`.

### `tests/retrieval/test_ann.py` — fixture pattern to copy

The `_dual_corpus()` builder at lines 70-145 returns
`(stmt_chunks, proof_chunks)` of `ChunkRecord`s. `_seeded_dual_lancedb`
(line 215) writes them via `ingest.store.write_chunks`. The mock-encode pattern
at line 198-211 replaces `server.query_encoder.encode_query` with a deterministic
stub via `monkeypatch.setattr(qe_mod, "encode_query", _fake_encode_async)` and
`monkeypatch.setattr(ann_mod, "encode_query", _fake_encode_async)`. **For
E07_S03 the same approach** lets the rerank path be tested without loading
the real cross-encoder model.

### `tests/test_server_startup.py` — current rerank-on path

Line 469-484: `test_enable_rerank_without_model_raises` hits
`Resources.startup(Config(enable_rerank=True))` and expects
`RerankerUnavailableError`. **There is no test today that mocks a working
reranker through startup.** E07_S03 must (a) replace
`_load_reranker_or_raise()` with a real loader, and (b) update this test so
it now passes the load when a stub model is patched in (or use a fast
sentinel).

## 2. Prior decisions and lessons

### Tier-3 cache-stats verification

**Recommend:** verify via `Resources.rerank_singleflight.dedup_count` directly,
mirroring the E07_S02 reinterpretation (research-synthesis.md, D2). The brief
AC #3 *"verifiable via cache-stats endpoint"* is the same fiction as E07_S02 AC
#4 — `/debug/cache-stats` does not exist (verified by grep across the codebase
including `server/health.py`). The dedup counter on the existing `Singleflight`
class is the canonical observation surface. Spell this out in the implementation
summary as a deliberate AC reinterpretation.

### Where the SHA constant lives

**Recommend:** declare `ARXMCP_RERANK_MODEL_SHA` as a `Config` field
(env-overridable per the brief) AND mirror the embedder convention by also
defining a module-level `BGE_RERANKER_V2_M3_COMMIT_SHA` constant in
`server/retrieval/rerank.py`. The Config field's default is the constant.
Rationale:

- **Brief verbatim**: *"loaded from a pinned commit SHA recorded in
  `server/config.py`"* — this requires the config field.
- **Convention**: the loader call site (`AutoModelForSequenceClassification.from_pretrained(..., revision=SHA)`)
  reads the constant directly so a misconfigured env var cannot silently
  swap models. The Config field is for the startup drift check; the constant
  is the canonical pin used by the loader.
- **Single source of truth**: a regression test in
  `tests/test_query_encoder.py::TestSingleSourceOfTruth` already enforces this
  for the embedder; extend the same test to the reranker constant.

### Comparing local model dir's git ref against pinned SHA

**Recommend:** use `huggingface_hub.try_to_load_from_cache` or
`huggingface_hub.snapshot_download` semantics — the HuggingFace cache is
laid out as `~/.cache/huggingface/hub/models--BAAI--bge-reranker-v2-m3/snapshots/<commit-sha>/...`,
and the snapshot directory name IS the commit SHA. So:

```python
from huggingface_hub import HfApi  # already a transitive dep of transformers
api = HfApi()
local_revision = api.repo_info(
    "BAAI/bge-reranker-v2-m3", revision=config.rerank_model_sha
).sha  # this is the resolved commit
```

Simpler: check the `snapshots/` subdirectory of the cached model repo for the
SHA prefix. **Mismatch → `logger.warning(...)`**, NOT a raise — the brief is
explicit: *"A mismatch is a startup warning, not a fatal error — the server
continues but logs the drift."*

### `rerank` signature — no-op shape

`ANNPhase.query` returns `list[tuple[str, float]]`. The brief mandates the same
shape for `RerankPhase.rerank(query_text, candidates, top_k)`. **No-op path:**
when `enable_rerank=False`, `return list(candidates)[:top_k]` — preserves
input order AND scores verbatim. AC #1: *"With `ARXMCP_ENABLE_RERANK=false`,
`RerankPhase.rerank(...)` returns input candidates in original order"* — the
input scores are the RRF fused scores from Phase 2; pass them through unchanged.

### `k` propagation

`server/handlers/search.py:70` defines `MAX_K = 50`; `server/handlers/search.py:86`
declares `k: Annotated[int, Field(ge=1, le=MAX_K, ...)] = 10`. **Confirmed.**
`RerankPhase.rerank(...)` accepts `top_k: int` with the same bounds; raise
`ValueError` if `top_k < 1` or `top_k > 50` (defense-in-depth, mirroring
`ANNPhase.query`'s pattern at `server/retrieval/ann.py:351-357`).

### Singleflight key construction

The Tier-3 spec key is
`sha256(query_embedding_hash + sorted_candidate_id_tuple_hash + reranker_version)`.

**Recommend:**

1. **Query embedding hash:** `sha256(query_vec.tobytes())` where `query_vec`
   is the float32 1024-dim vector returned by `encode_query`. `.tobytes()`
   is byte-stable for a fixed dtype/shape. This avoids re-encoding inside
   `RerankPhase` — the caller (E07_S04 handler) already has the vector and
   passes it in. **Add `query_vec: np.ndarray` as a kwarg to `rerank()`**
   so the singleflight key can be built without re-encoding.
2. **Candidate id tuple hash:** `sha256("\n".join(sorted(cid for cid, _ in candidates)).encode("utf-8"))`.
   Sort ASC by `chunk_id` per the project-wide determinism rule
   (`06-mcp-server-design.md`).
3. **Reranker version:** the short form
   `f"bge-reranker-v2-m3@{BGE_RERANKER_V2_M3_COMMIT_SHA[:8]}"` — same shape
   as `EMBEDDER_VERSION` at `ingest/embedder.py:117`.

Wrap all three into the final hex key:
`sha256(query_hash + cand_hash + version_str.encode()).hexdigest()`.

## 3. External sources

- **BGE-reranker-v2-m3 model card** —
  `https://huggingface.co/BAAI/bge-reranker-v2-m3`. ~568M params (multilingual,
  XLM-RoBERTa-large backbone). MIT-license-compatible. Loaded via
  `AutoModelForSequenceClassification.from_pretrained(...)` + matching tokenizer;
  output is a single logit per `(query, passage)` pair (cross-encoder
  classification head). Inference: tokenize as
  `tokenizer([(q, p) for p in passages], padding=True, truncation=True,
  max_length=512, return_tensors="pt")`, forward, take `logits[:, 0]` (or
  `outputs.logits.squeeze()`) as the score. Higher = more relevant.
- **FlagEmbedding (BGE official SDK)** — adds `FlagReranker` convenience but
  brings heavy deps. The codebase rejected it for the embedder
  (`E03_S01/research-synthesis.md` — *"AutoModel, not FlagEmbedding"*); apply
  the same standard here. Use bare `transformers` + `torch`.
- **HuggingFace Hub local-cache layout** —
  `~/.cache/huggingface/hub/models--{org}--{name}/snapshots/{commit-sha}/`.
  The snapshot dir IS the SHA; that's the drift-check primitive.
- **MCP design notes** — no rerank-specific MCP constraint beyond the existing
  loopback-binding + 256 KB inline cap (config.py:130). `search_papers`
  already returns ResourceLink blocks; reranker scores propagate via the
  existing `score` field in `structuredContent.results[*]`.

## Open questions

1. **Token length for the cross-encoder**: BGE-reranker-v2-m3 supports up to
   8192 tokens (XLM-R-large extended), but reranking 50 candidates at 8K
   tokens each is ~10 seconds CPU. **Recommend** capping at `max_length=512`
   (matches the embedder's `MAX_TOKENS`) for v1 to satisfy AC #2 (5-second
   budget). Document the trade-off; revisit in E07_S04 when nDCG data is in.
2. **Test for AC #2 (5-second load + score)**: requires the actual model
   download (~2.3 GB). The brief's AC #4 (`-k "not requires_model"` passes
   without download) implies `pytest.mark.requires_model` for the slow path.
   Mark the 5-second test accordingly so CI without GPUs/cache can skip it.
3. **`encode_query` re-call in `rerank()`**: the brief is silent on whether
   `RerankPhase` needs the query *vector* or just the query *text*. A
   cross-encoder consumes text directly (no vector). The Singleflight key
   needs the vector hash. **Decision**: caller passes both `query_text`
   (for the cross-encoder) and `query_vec` (for the cache key) into
   `rerank()`. The E07_S04 handler will already have both.

## External writes the implementation will require

None. Pure-internal milestone:
- `server/retrieval/rerank.py` (new)
- `server/config.py` (modify — add `rerank_model_sha` field)
- `server/resources.py` (modify — replace `_load_reranker_or_raise()` body
  with the real loader; add SHA-drift check)
- `server/retrieval/__init__.py` (modify — re-export `RerankPhase`)
- `tests/retrieval/test_rerank.py` (new)
- `tests/test_server_startup.py` (modify — add a passing-rerank-load case
  using a mocked model)

No git push, PR, ticket, infra mutation, or third-party API call. The
HuggingFace download (if AC #2 is run locally) is an artifact fetch the
operator already performs for the embedder; nothing the implementation
itself sends out.
