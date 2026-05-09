# E07_S03 — Research synthesis

## Both researchers agree on these load-bearing facts

1. **`_load_reranker_or_raise()` exists as a placeholder** at `server/resources.py:425-442`. It always raises `RerankerUnavailableError` with a "deferred to E07" message. E07_S03 must replace the body; keep the signature.

2. **`Resources.rerank_singleflight` and `Resources.rerank_semaphore` are constructed but unused.** The generic `Singleflight` class at `server/resources.py:124-201` is ready; the semaphore (`max_concurrent_reranks=4`) is ready. E07_S03 is the first consumer.

3. **Use `transformers.AutoModelForSequenceClassification`, NOT `FlagEmbedding`.** Mirrors the embedder precedent (E03_S01 research-synthesis.md D1: "AutoModel, not FlagEmbedding" — keeping the dependency surface minimal). `pyproject.toml` already pins `transformers>=4.40` + `torch>=2.0`.

4. **Cross-encoder API**: `model(**inputs).logits.view(-1)` returns one logit per `(query, doc)` pair. Tokenize with `max_length=512` (latency budget), batch all 50 pairs in ONE forward pass. Optionally `sigmoid` to map to [0, 1].

5. **`server/config.py`**: `enable_rerank: bool = False` already exists at line 106. `max_concurrent_reranks: int = 4` already exists at line 120. **`ARXMCP_RERANK_MODEL_SHA` does NOT exist** — add it (Pydantic-settings with `extra="forbid"` requires a declared field).

6. **`/debug/cache-stats` does not exist.** Same fiction as E07_S02 AC #4. AC #3 reinterpreted: verify via `Resources.rerank_singleflight.dedup_count` directly.

7. **SHA mismatch is a WARNING, not FATAL** — the brief is explicit. This breaks precedent (BGE-M3 mismatch is FATAL via `revision=BGE_M3_COMMIT_SHA` + transformers raising). Justified by the opt-in default: `enable_rerank=False` everywhere in v1; SHA drift cannot affect production until E07_S04 flips the flag.

## Decisions for the implementer

| ID | Decision | Rationale |
|---|---|---|
| D1 | **Loader: `AutoModelForSequenceClassification.from_pretrained("BAAI/bge-reranker-v2-m3", revision=BGE_RERANKER_COMMIT_SHA, trust_remote_code=False)` + `.eval()` + `torch.no_grad()` at inference time.** | Mirrors `ingest/embedder.py:266-294`. Threat 6 (`08-security-observability-ops.md`) — `trust_remote_code=False` blocks RCE via crafted `modeling_*.py`. |
| D2 | **`BGE_RERANKER_COMMIT_SHA` lives as a module constant in `server/retrieval/rerank.py`. The Config field `rerank_model_sha: str = BGE_RERANKER_COMMIT_SHA` mirrors it.** The loader uses the CONSTANT directly (Config-derived value would let an env-var swap models silently). The Config field is for the startup drift check + audit trail. | Mirrors `BGE_M3_COMMIT_SHA` discipline. Threat 6. |
| D3 | **Replace `_load_reranker_or_raise()` body** with the real loader. Keep `async def`, return `(model, tokenizer)` tuple (or a small dataclass) so the rerank path has both. Keep `RerankerUnavailableError` for genuine load failures. Off-load to `loop.run_in_executor` since `from_pretrained` is sync I/O. | Lifecycle parity with the embedder. |
| D4 | **`RerankPhase` signature: `async def rerank(query_text, query_vec, candidates, top_k) -> list[tuple[str, float]]`.** `query_vec` is the L2-normalized 1024-dim float32 vector from `encode_query` (used for the Tier-3 cache key). Off-path returns `list(candidates[:top_k])` verbatim — no encode, no model, no semaphore, no singleflight. | Brief AC #1 + the Tier-3 key spec. The caller (E07_S04 handler) already has `query_vec` from Phase-2; passing it avoids a redundant encode. |
| D5 | **Singleflight key:** `sha256(query_vec.tobytes() + b"\\n" + b"\\n".join(sorted(cid.encode() for cid, _ in candidates)) + b"\\n" + reranker_version.encode()).hexdigest()`. Reranker version: `f"bge-reranker-v2-m3@{BGE_RERANKER_COMMIT_SHA[:8]}"`. | Brief: `(query_embedding_hash, sorted_candidate_id_tuple_hash, reranker_version)`. Sort ASC matches project-wide determinism. |
| D6 | **Two-tier concurrency:** acquire `r.rerank_semaphore` AROUND the `r.rerank_singleflight.run(...)` call. Semaphore caps distinct-rerank parallelism; singleflight collapses same-rerank duplication. | Mirrors `server/handlers/search.py:106-107`'s `embed_semaphore` + `encode_query`'s embedded singleflight pattern. |
| D7 | **Fetch `body_text` from LanceDB via** `chunks_table.search().where(f"chunk_id IN ({csv})").select(["chunk_id", "body_text"]).limit(len(candidates)).to_arrow()`. Re-index to preserve the input candidate order (LanceDB does not guarantee SQL-order on a `where`). Phantom ids (per E07_S02 F5 contract) silently drop from the rerank set; document. | Need `body_text` for cross-encoder input. The phantom-id skip matches the documented downstream-tolerance contract. |
| D8 | **SHA drift check at startup:** `huggingface_hub` cache layout is `~/.cache/huggingface/hub/models--BAAI--bge-reranker-v2-m3/snapshots/<sha>/`. Inspect the cache dir; if the snapshot SHA differs from `BGE_RERANKER_COMMIT_SHA`, log WARNING. Do NOT raise. | Brief explicit. The opt-in-default trade-off justifies the warning-only stance. |
| D9 | **AC #3 reinterpretation:** verify Tier-3 cache hit via `Resources.rerank_singleflight.dedup_count` (the existing `Singleflight.dedup_count` property at `server/resources.py:198`). `/debug/cache-stats` is fiction — same as E07_S02 AC #4. | Documented in implementation summary. |
| D10 | **Test marker:** introduce `@pytest.mark.requires_model` (registered in `pyproject.toml`'s `[tool.pytest.ini_options].markers`). Combined with `@pytest.mark.skipif(os.environ.get("ARXMCP_RUN_REAL_BGE_RERANKER") != "1", ...)` so `pytest -k "not requires_model"` (the brief AC) skips the model-loading test cleanly. The mock-only path covers everything else. | Brief AC #4 literal + existing convention from `tests/test_query_encoder.py`. |
| D11 | **Cross-encoder `max_length=512`** for v1. BGE-reranker-v2-m3 supports 8K but at 50 candidates × 8K tokens = ~10s on CPU; 512 keeps the brief's 5-second budget achievable on commodity hardware. Document trade-off; revisit in E07_S04 with nDCG data. | AC #2 (5-second budget) + observed cross-encoder costs. |
| D12 | **Score: `sigmoid(logit)` to bounded [0, 1].** Cross-encoder produces unbounded logits; sigmoid normalization makes the score interpretable alongside the existing dense cosine [0, 1] scores. | Convention from FlagEmbedding's `compute_score(normalize=True)`; consistency with existing score conventions in `search.py`. |

## Reinterpreted acceptance criteria

| Brief AC | Reinterpretation | How verified |
|---|---|---|
| `ARXMCP_ENABLE_RERANK=false` → returns input candidates in original order | unchanged | `test_off_flag_is_passthrough` |
| `ARXMCP_ENABLE_RERANK=true` → loads + scores 50 candidates within 5s | unchanged (env-gated under `requires_model` marker) | `test_rerank_50_candidates_under_5s_requires_model` |
| Tier-3 cache hit bypasses reranker | reinterpreted: `Resources.rerank_singleflight.dedup_count` increments on the second concurrent identical call (singleflight coalesces); `/debug/cache-stats` is fiction | `test_concurrent_identical_rerank_dedups` |
| `pytest -k "not requires_model"` passes without model | unchanged | the suite itself |

## Open questions

1. **Pin the SHA value.** The implementer must run `curl -s https://huggingface.co/api/models/BAAI/bge-reranker-v2-m3 | python -c "import sys,json;print(json.load(sys.stdin)['sha'])"` to get the current `main` SHA. Recommend running this once during implementation.

2. **`E07_S04` integration timing.** `RerankPhase` is constructed at startup and consumed by E07_S04's hybrid orchestrator. The brief implies `RerankPhase` is independent. Confirm: `RerankPhase` lives on `Resources.rerank_phase` (mirrors `bm25_phase`/`ann_phase`); the handler swap into `search.py` is E07_S04.

## External writes the implementation will require

None. Pure-internal:
- `server/retrieval/rerank.py` (new)
- `server/retrieval/__init__.py` (modify — re-export)
- `server/config.py` (modify — add `rerank_model_sha` field)
- `server/resources.py` (modify — replace `_load_reranker_or_raise` body, add `rerank_phase` field + startup wire-up)
- `tests/retrieval/test_rerank.py` (new)
- `pyproject.toml` (modify — add `requires_model` marker)

No git push, PR, ticket, infra mutation, or third-party API call. The first real-model run (env-gated) will download the BGE-reranker safetensors from HuggingFace Hub — same operator-machine read pattern as the embedder.
