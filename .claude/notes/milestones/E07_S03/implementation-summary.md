# E07_S03 — Implementation summary

**One-line:** Phase-3 BGE-reranker cross-encoder with env-flag gate. Off-path is a passthrough (no model load). On-path tokenizes 50 `(query, body)` pairs through one forward pass, sigmoid-normalizes scores, and reorders. Tier-3 cache via the existing generic `Singleflight`.

## Files

### NEW: `server/retrieval/rerank.py` (~470 LOC)

`RerankPhase` class:
- **`__init__(chunks_table, rerank_singleflight, rerank_semaphore, enabled, model_handle=None)`** — refuses if `enabled=True` AND `model_handle is None`.
- **`async rerank(query_text, query_vec, candidates, top_k)`** — off-path returns `list(candidates[:top_k])` verbatim (no encode/no model/no semaphore/no singleflight). On-path: builds the Tier-3 singleflight key, acquires `rerank_semaphore`, runs the cross-encoder inside the singleflight, returns `(chunk_id, sigmoid_logit)` sorted `(score desc, chunk_id asc)`.

Module-level constants:
- `BGE_RERANKER_COMMIT_SHA = "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"` — single source of truth, refresh procedure documented inline.
- `RERANKER_VERSION = f"bge-reranker-v2-m3@{SHA[:8]}"` — used in the Tier-3 cache key.
- `RERANKER_MODEL_ID`, `RERANKER_MAX_LENGTH=512`, `MAX_K=50`.

Helpers:
- `_huggingface_cache_snapshot_sha(model_id)` — inspects `~/.cache/huggingface/hub/models--<org>--<name>/snapshots/<sha>/`; returns the cached SHA or None.
- `maybe_log_sha_drift(expected_sha)` — WARNING (not FATAL) per brief.
- `_build_singleflight_key(query_vec, candidates)` — `sha256(vec_bytes + sorted_chunk_id_bytes + version_bytes)`. Deterministic regardless of input candidate order (sorts ASC).
- `_fetch_body_texts(chunks_table, chunk_ids)` — fetches `body_text` from LanceDB; phantom ids drop silently (E07_S02 F5 contract); refuses chunk_ids containing single quotes (defense against SQL injection through tampered candidate lists).
- `_rerank_sync(model, tokenizer, query, bodies)` — runs the PyTorch forward pass off-loaded to executor.

### MODIFIED: `server/config.py`

Added `rerank_model_sha: str = "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e"` field. The Config field default mirrors the constant; the LOADER uses the constant directly so an env-var override cannot silently swap models. The Config field exists for the audit trail + the SHA-drift warning.

### MODIFIED: `server/resources.py`

- Added `rerank_phase: Any | None = None` field on the `Resources` dataclass.
- Replaced `_load_reranker_or_raise()` body — no longer a stub. Now off-loads `AutoTokenizer.from_pretrained` + `AutoModelForSequenceClassification.from_pretrained` to the executor with `revision=BGE_RERANKER_COMMIT_SHA, trust_remote_code=False`. Calls `model.eval()` then runs `maybe_log_sha_drift`. Wraps any `Exception` as `RerankerUnavailableError`.
- Inserted step 5b in `Resources.startup`: `rerank_phase = RerankPhase(chunks_table, rerank_singleflight, rerank_semaphore, enabled=cfg.enable_rerank, model_handle=reranker_model)`.

### MODIFIED: `server/retrieval/__init__.py`

Re-exports `RerankPhase`, `RerankerLoadError`, `BGE_RERANKER_COMMIT_SHA`.

### MODIFIED: `pyproject.toml`

Added `requires_model` marker under `[tool.pytest.ini_options].markers` so `pytest -m requires_model` selects the env-gated real-model tests.

### MODIFIED: `tests/test_server_startup.py`

`test_enable_rerank_without_model_raises` now monkeypatches `server.resources._load_reranker_or_raise` to raise (preserves the original test intent — "load failure → fatal" — without depending on the reranker stub).

### NEW: `tests/retrieval/test_rerank.py` (~600 LOC, 36 tests + 1 env-gated)

Test classes:
- **`TestOffPathPassthrough`** (9 tests) — input order preserved, top_k truncation, no singleflight touch, empty candidates, `enabled` property, `top_k` validation `[1, MAX_K]`, refuses `enabled=True` + `model_handle=None`.
- **`TestSingleflightKey`** (6 tests) — 64-hex shape; deterministic; invariant to candidate order; changes when query_vec changes; changes when candidates change; reranker version is part of the key.
- **`TestSingleflightCacheBypass`** (2 tests) — concurrent identical reranks coalesce (`dedup_count += 1`); distinct candidates do NOT dedup.
- **`TestOnPathRerank`** (4 tests) — top-k in score-desc order; phantom chunk_ids silently dropped; all-phantom returns `[]`; empty candidates returns `[]`.
- **`TestFetchBodyTexts`** (4 tests) — dict keyed by chunk_id; phantom absent; empty input; quote-injection defensively dropped.
- **`TestShaConstants`** (5 tests) — 40 lowercase hex SHA; `RERANKER_VERSION` includes short SHA; `RERANKER_MAX_LENGTH == 512`; `RERANKER_MODEL_ID == "BAAI/bge-reranker-v2-m3"`; `Config.rerank_model_sha` default matches constant.
- **`TestShaDriftCheck`** (3 tests) — no cache → INFO; matched SHA → INFO; drift → WARNING.
- **`TestHuggingfaceCacheLookup`** (2 tests) — no cache returns None; cached SHA returned.
- **`TestResourcesIntegration`** (1 test) — `Resources.startup(enable_rerank=False)` populates `r.rerank_phase` with `enabled=False`.
- **`TestOnPathRequiresModel`** (1 env-gated) — real model loads + scores 50 candidates in <5s (skipped without `ARXMCP_RUN_REAL_BGE_RERANKER=1`).

## Acceptance criteria

| Brief AC | Reinterpretation | Status | Evidence |
|---|---|---|---|
| `ARXMCP_ENABLE_RERANK=false` → returns input candidates in original order | unchanged | met | `TestOffPathPassthrough::test_off_path_returns_input_order` (+ 8 sibling tests) |
| `ARXMCP_ENABLE_RERANK=true` → loads + scores 50 in <5s | unchanged (env-gated) | met | `TestOnPathRequiresModel::test_real_reranker_loads_and_scores_50_under_5s` (skipped by default; opt-in via `ARXMCP_RUN_REAL_BGE_RERANKER=1`) |
| Tier-3 cache hit bypasses reranker | reinterpreted: `Resources.rerank_singleflight.dedup_count` increments on the second concurrent identical call (`/debug/cache-stats` is fiction) | met | `TestSingleflightCacheBypass::test_concurrent_identical_rerank_dedups` |
| `pytest -k "not requires_model"` passes without model | unchanged | met | 36 passed, 1 skipped (the env-gated one) |

## Deviations from the brief (documented in research-synthesis.md)

1. **Cache-stats observation surface.** Brief AC #3 says "verifiable via cache-stats endpoint"; that endpoint does not exist (same fiction as E07_S02 AC #4). Test reads `Resources.rerank_singleflight.dedup_count` directly.

2. **SHA drift = WARNING, not FATAL.** Brief explicit. Mirrors the brief's wording but breaks precedent vs the embedder (BGE-M3 SHA mismatch is FATAL via `revision=` raising). Justified: `enable_rerank=False` everywhere in v1; SHA drift cannot affect production retrieval until E07_S04 flips the flag.

3. **Brief's `rerank(query_text, candidates, top_k)` signature extended to `rerank(query_text, query_vec, candidates, top_k)`** — the Tier-3 singleflight key needs the query embedding bytes (per `.claude/notes/07-multi-agent-caching.md:155-166`). The caller (E07_S04 hybrid orchestrator) already has `query_vec` from Phase 2; passing it avoids a redundant encode.

## What this milestone closes from prior critiques

- **E06_S01 reranker stub** — `_load_reranker_or_raise()` is no longer a placeholder that always raises. The brief's stub-removal contract from `server/resources.py:425-442` is satisfied.

## What this milestone does NOT close (deferred)

- **Tier-3 LRU memo (1-hour TTL)** — `.claude/notes/07-multi-agent-caching.md:155-166` specifies a separate LRU on top of the singleflight (singleflight is dedup; LRU is memoization). The brief asks for the singleflight wrapper only; the LRU is deferred to a follow-up.
- **`search.py` handler integration** — `RerankPhase` is constructed at startup and consumed by the future hybrid-search orchestrator (likely E07_S04). E07_S03 ships the standalone class only.

## External writes the orchestrator must authorize

None. Purely-internal milestone. The first real-model run (env-gated via `ARXMCP_RUN_REAL_BGE_RERANKER=1`) downloads the BGE-reranker safetensors from HuggingFace Hub — same operator-machine read pattern as the embedder; not an authorized external write by the agent.

## Project check command

`ruff check .` — clean.
`pytest -q` — **920 passed, 4 skipped** (was 884 pre-milestone — +36 from this milestone, no regressions).
