# E07_S03 — Research Brief 2

## 1. In-codebase context

### `_load_reranker_or_raise()` exists as a placeholder

`server/resources.py:425-442` ships a stub that **always raises**
`RerankerUnavailableError(...)` with the message:
> "BGE-reranker-v2-m3 is not yet integrated (E07 will ship it). Set
> `ARXMCP_ENABLE_RERANK=false` until E07 lands."

The async signature `async def _load_reranker_or_raise() -> Any` is
the contract: returns one opaque "model handle" object, called from
`Resources.startup` step 4 (`server/resources.py:309-314`) only when
`config.enable_rerank` is True. **E07_S03 must replace the body**;
keep the signature and the `RerankerUnavailableError` raising
discipline (synthesis D6 in `server/resources.py:108-116`).

There is **no library yet**. `pyproject.toml:dependencies` has
`transformers>=4.40` + `torch>=2.0` + `safetensors>=0.4` but NOT
`FlagEmbedding`. Prior research-brief precedent (E03_S01
`research-brief-2.md:202-238`, `research-synthesis.md:73`) explicitly
chose **`AutoModel` over `FlagEmbedding`** for BGE-M3:
> "keeping the dependency surface" — single source of truth.

**Recommendation (one approach):** mirror the embedder. Use
`transformers.AutoModelForSequenceClassification.from_pretrained(
"BAAI/bge-reranker-v2-m3", revision=BGE_RERANKER_COMMIT_SHA,
trust_remote_code=False)` + `model.eval()` + `torch.no_grad()`. Do
**not** add `FlagEmbedding`. The cross-encoder forward pass produces
a single logit per `(query, doc)` pair; apply `sigmoid` to map to
[0, 1] (FlagEmbedding's `compute_score(..., normalize=True)` does
exactly this).

### `Resources.rerank_singleflight` is generic, currently unused

Constructed at `server/resources.py:358` as
`rerank_singleflight = Singleflight()` (the generic class defined at
`server/resources.py:124-201`). The class docstring (lines 130-131)
says verbatim:
> "The reranker (E07) will be the first non-test consumer; for
> E06_S01 this class ships instantiated under
> `Resources.rerank_singleflight` but unused."

Contract: `async def run(self, key: str, coro_factory) -> Any`
(line 150). `coro_factory` is a no-arg callable returning a
coroutine. Returns the resolved value verbatim — the generic `Any`
return type explicitly supports list-shaped values (the
``list[tuple[str, float]]`` ranking we need). Cancellation-safe via
`asyncio.shield` (closes F1, F3 from prior critiques).

### `Resources.rerank_semaphore` is unused today

Initialized at `server/resources.py:357` as
`asyncio.Semaphore(config.max_concurrent_reranks)` (default `4` per
`server/config.py:120`). **No consumer yet** — `grep -rn
rerank_semaphore` confirms only the resources construction site.
E07_S03 is the first consumer. Acquire it as
`async with r.rerank_semaphore:` AROUND the singleflight call (the
semaphore caps **distinct-rerank** parallelism; the singleflight
collapses **same-rerank** duplication — same two-tier discipline as
the embedder, `server/resources.py:20-38`).

### Config status — partial

- `enable_rerank: bool = False` already exists at `server/config.py:106`.
- `max_concurrent_reranks: int = 4` already exists at line 120.
- **`ARXMCP_RERANK_MODEL_SHA` does NOT exist.** Add it. Mirror the
  precedent at `ingest/embedder.py:103-112`: a refresh-procedure
  comment showing the `huggingface.co/api/models/...` curl, then the
  pinned constant. **However** — per the `extra="forbid"` rule
  (`server/config.py:82`), unknown `ARXMCP_*` env vars raise. So
  `ARXMCP_RERANK_MODEL_SHA` MUST be a `Config` field, not a bare
  module constant. Recommended: `rerank_model_sha: str = "<pin>"`
  with the pin **also** mirrored as a module-level constant
  `BGE_RERANKER_COMMIT_SHA` in a new `server/reranker_constants.py`
  (or inline in `server/retrieval/rerank.py`) for the cross-process
  test that validates "imports... not redefined" — same Threat-6
  discipline as `BGE_M3_COMMIT_SHA` (`server/query_encoder.py:44-48`).

### Test fixture pattern to mirror

`tests/retrieval/test_ann.py:182-258` defines:
- `_curated_chunk(...)` builder (lines 53-68)
- `_dual_corpus()` returning `(stmt, proof)` chunk lists (lines 70-134)
- `_embeddings_for_dual(...)` (lines 137-179)
- `@pytest.fixture _mocked_bge` patching `encode_query` to a fast
  deterministic stub (lines 182-211)
- `@pytest.fixture _seeded_dual_lancedb` writing via `write_chunks`
  (lines 214-224)
- `_open_chunks_table` helper (242-245)
- `_ann_phase_dual` fixture (248-251)

Mirror exactly: add `_mocked_reranker` patching `RerankPhase`'s model
load to a deterministic stub that scores by string-match length, and
a `_rerank_phase_dual` fixture wrapping `RerankPhase(...)`.

### `_canonicalize` for the singleflight key

`server/query_encoder.py:205-227`:
```py
return unicodedata.normalize("NFC", query_text.strip())
```
Two-step (D4): strip ASCII whitespace + NFC. The reranker
singleflight key needs the **same canonicalization** for the query
half, plus deterministic candidate sorting (`sorted(chunk_ids)` —
project-wide rule per `server/retrieval/ann.py:417` "(score desc,
chunk_id asc)").

## 2. Prior decisions and lessons

### Why hash the embedding (not the text)?

The brief specifies `(query_embedding_hash, sorted_candidate_id_tuple_hash, reranker_version)`. The cited rationale (`.claude/notes/07-multi-agent-caching.md:144`):
> "key = sha256(query_embedding_hash + sorted_candidate_id_tuple_hash + reranker_version)"

This is **deliberate** and ties Tier 3 to Tier 2's
near-duplicate semantics (07-multi-agent-caching.md:135-148): two
queries with cosine ≥ 0.97 produce essentially the same embedding,
and at the byte level either match (SHA equal) or do not (SHA
differ). The text-canonical key would over-fragment the cache for
near-duplicates. **Recommendation:** hash the L2-normalized float32
embedding as `hashlib.sha256(query_vec.tobytes()).hexdigest()`. This
requires the embedding to be computed first — fine, we need it
anyway for Phase 2. **Pass the already-computed `query_vec` from the
caller (E07_S04 orchestrator) into `RerankPhase.rerank(query_text,
query_vec, candidates, top_k)`** to avoid a redundant encode.
Alternative — extend the signature with `query_vec` as an optional
param defaulting to `None` and re-encoding when omitted — is uglier
and risks silent bypasses.

### Reranker SHA mismatch: WARNING, not FATAL

The brief is explicit:
> "A mismatch is a startup warning, not a fatal error — the server
> continues but logs the drift."

This **breaks precedent**: `ingest/embedder.py:264-267` pins the
embedder SHA via `revision=BGE_M3_COMMIT_SHA` so a mismatched
local cache **cannot load** (transformers raises). The asymmetry is
justified by the opt-in default: `enable_rerank=False` everywhere in
v1, so SHA drift cannot affect production retrieval until E07_S04
flips the flag. **Recommendation:** still pass `revision=
BGE_RERANKER_COMMIT_SHA` to `from_pretrained` (so transformers
fetches/validates the right ref), and additionally surface a
WARNING-level log if `huggingface_hub.snapshot_download(...)`
returns a path whose `.git/HEAD` differs (in practice, transformers
caches under `~/.cache/huggingface/hub/models--BAAI--bge-reranker-v2-m3/snapshots/<sha>/`, so the cached snapshot dir name IS the SHA — compare strings).

### Cross-encoder API surface

`AutoModelForSequenceClassification.from_pretrained("BAAI/bge-reranker-v2-m3", revision=SHA, trust_remote_code=False)` returns an
XLM-RoBERTa-large with a single-class regression head. Per the model
card (HuggingFace `BAAI/bge-reranker-v2-m3`):
```py
inputs = tokenizer(pairs, padding=True, truncation=True,
                   return_tensors="pt", max_length=512)
with torch.no_grad():
    scores = model(**inputs, return_dict=True).logits.view(-1).float()
# Optional: scores = torch.sigmoid(scores)
```
where `pairs = [[query, doc] for doc in docs]`. **One forward pass
batches all 50 candidates** — the brief's "5 second budget for 50
candidates" suggests batching, not a Python loop.

To fetch `body_text` for each candidate, query LanceDB:
`chunks_table.search().where(f"chunk_id IN ({ids_csv})").select(["chunk_id", "body_text"]).to_arrow()`. Order is **not preserved** —
build a dict and re-index by the input order.

### Off-path semantics

The brief: `RerankPhase.rerank(query_text, candidates, top_k)`
returns input candidates in original order when flag is False.
**Recommendation:** signature `async def rerank(self, query_text,
query_vec, candidates: Sequence[tuple[str, float]], top_k: int) ->
list[tuple[str, float]]`. Off-path returns `list(candidates[:top_k])`
verbatim — preserves the Phase-2 RRF score in the second tuple slot.
Off-path **does NOT touch** `query_text` / `query_vec` (no encode,
no model invocation, no semaphore acquisition, no singleflight
lookup). The test `test_off_flag_is_passthrough` should assert
`rerank(...) is_not <model> AND result == candidates[:top_k]`.

### Singleflight returns lists verbatim

`Singleflight.run` (server/resources.py:150-196) is generic on
`-> Any`; the resolved task value is returned verbatim through
`asyncio.shield(task)` at line 196. List values pass through
unchanged. The eviction callback (lines 188-191) only `pop`s the
key; it does not deep-copy or transform the value. **One subtlety:**
unlike the embedder singleflight (`query_encoder.py:332`,
`return result.copy()`), the generic singleflight does NOT defensive-
copy. Two callers receive **the same list object**. For an immutable
ranking this is fine, but **document explicitly** that
`RerankPhase.rerank` callers must NOT mutate the returned list.
Tuple elements are already immutable.

### `requires_model` marker convention

Existing convention is `@pytest.mark.skipif(os.environ.get("ARXMCP_RUN_REAL_BGE_M3") != "1", reason="...")` per `tests/test_query_encoder.py:802-810`. The brief uses
`pytest -k "not requires_model"` selection syntax — this matches
either a `@pytest.mark.requires_model` marker OR a class/function
NAMED with `requires_model`. **Recommendation:** introduce a real
`@pytest.mark.requires_model` marker (registered in `pyproject.toml`
under `[tool.pytest.ini_options]` `markers = ["requires_model: ..."]`)
**plus** `os.environ.get("ARXMCP_RUN_REAL_BGE_RERANKER") != "1"`
skipif. The marker enables `-k "not requires_model"` selection; the
env-gate prevents accidental network downloads in CI. Add a parallel
`ARXMCP_RUN_REAL_BGE_RERANKER` env to the existing pattern.

## 3. External sources

- **`AutoModelForSequenceClassification` API** (HuggingFace
  transformers): the canonical loader for cross-encoders.
  `model(**inputs).logits` shape is `[batch, num_labels=1]`; squeeze
  to a 1-D float tensor. Model card at
  `https://huggingface.co/BAAI/bge-reranker-v2-m3` confirms
  `num_labels=1` (regression head) and `max_length=8192` capability,
  though we should cap at 512 for latency.
- **`FlagEmbedding.FlagReranker`**: convenience wrapper. Signature
  `FlagReranker(model_name_or_path, use_fp16=True, normalize=False)`
  with `.compute_score(pairs, normalize=False) -> list[float]`. We
  REJECT this dependency per E03_S01 precedent.
- **`huggingface_hub.HfApi().model_info("BAAI/bge-reranker-v2-m3").sha`**: returns the current `main` commit SHA. Use this in the
  refresh-procedure comment (mirror `ingest/embedder.py:108-110`).
  Looking up against a local cache: snapshot dir name IS the SHA
  (`~/.cache/huggingface/hub/models--BAAI--bge-reranker-v2-m3/snapshots/<sha>/`).
- **BGE-reranker-v2-m3 model size**: ~2.27 GB safetensors
  (XLM-RoBERTa-large). First-call download similar magnitude to
  BGE-M3.

## Open questions

1. **Pin the SHA value.** The implementer must run the curl recipe
   from `ingest/embedder.py:108-110` (substituting `bge-reranker-v2-m3`)
   to get the current `main` SHA and write it into the new
   `BGE_RERANKER_COMMIT_SHA` constant. I cannot fetch it here.
2. **Caller signature decision.** Confirm with E07_S04's planned
   handler whether passing `query_vec` into `rerank(...)` is
   acceptable, or whether `RerankPhase` should re-encode internally
   (re-encoding is wasteful but trivially correct).

## External writes the implementation will require

**Zero.** All work is local: new file `server/retrieval/rerank.py`,
edits to `server/config.py` (add `rerank_model_sha`), edits to
`server/resources.py` (replace `_load_reranker_or_raise` body and
add SHA-drift WARNING), new file `tests/retrieval/test_rerank.py`,
and a `pyproject.toml` `markers` entry. No GitHub, GitLab, Jira,
HuggingFace push, model upload, or third-party API call. The first
real-model run (env-gated) will download the BGE-reranker safetensors
from HuggingFace Hub — that is a developer-machine read, not an
authorized external write by the agent.
