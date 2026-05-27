# Research Brief — embedder-truncation-m1

**Agent:** milestone-researcher (brief-2)
**Generated:** 2026-05-27T22:00:00Z

---

## In-codebase context

**Relevant design notes:** `04-parsing-and-chunking.md`, `07-multi-agent-caching.md`, `08-security-observability-ops.md`, `chunker-fixtures.md`, `snippet-contract.md`, `retrieval-quality-report.md`.

**Current token-budget constants** (`ingest/chunker.py:86-90`, verbatim from scan brief):

```python
BGE_M3_MAX_TOKENS = 512
PROOF_HEADER_RESERVE = 64
PROOF_MAX_TOKENS = BGE_M3_MAX_TOKENS - PROOF_HEADER_RESERVE  # 448
PROOF_WINDOW_OVERLAP = 64
STMT_MAX_TOKENS = BGE_M3_MAX_TOKENS  # preamble headroom is E02_S02's responsibility
```

**Current embedder constants** (`ingest/embedder.py:128`): `MAX_TOKENS = 512`. The pre-pass at lines 415-421 calls `tokenizer(texts, padding=False, truncation=False, return_length=True)` — **missing `add_special_tokens=False`**. This is the smoking-gun for change C.

**CHUNKER_VERSION = "v1.0"** (`ingest/chunker_types.py:45`). All 10 golden chunker fixtures (`tests/fixtures/chunker/2307.000*.expected.json`) pin `"chunker_version": "v1.0"` and specific `expected_chunk_ids`. A CHUNKER_VERSION bump requires regenerating all 10 expected.json files per `chunker-fixtures.md §Regenerating after a chunker change`.

**Fixture regeneration protocol** (verbatim from `chunker-fixtures.md`):
> "If a chunker change legitimately alters chunk_ids (e.g. a `chunker_version` bump from `"v1.0"` to `"v1.1"`):
> 0. **Do NOT modify any committed `index.html` files**.
> 1. **Bump** `CHUNKER_VERSION` in `ingest/chunker_types.py`.
> 2. **Re-bootstrap** all 10 `expected.json` files using the procedure above (loop over `_FIXTURE_SUITE_IDS`).
> 3. **Update** the eval harness (`tests/eval/fixtures/queries.json`) in lockstep.
> 4. **Land** all three changes ... in **one commit**."

Note: `tests/eval/fixtures/queries.json` is documented as "still an empty stub" in the retrieval-quality report. The AC for B-3 (nDCG@5 no-regress on queries.json) cannot be fully validated because the eval fixture is empty. The B-3 AC must be re-framed as: "run on notebook-scoped fixture from `var/arxmcp/notebooks/bridgeland-stability/queries.json` which IS populated."

**Cache impact of CHUNKER_VERSION bump** (from `07-multi-agent-caching.md`):
> "Tier 1 — Exact-query (SQLite LRU, 10K entries): key includes `corpus_version: int` as a mandatory component; stale entries from old corpus versions are unreachable by construction after a restart with a new `corpus-version.json`."

The re-embed bumps `corpus-version.json` version field. All Tier-1/2/3 cache entries become unreachable on server restart — this is correct behavior, not a bug.

**BP1/BP2 byte-stability** (`07-multi-agent-caching.md`): EXPECTED_TOOL_SCHEMA_SHA256 and EXPECTED_BP1_SHA256 must be UNCHANGED — this milestone does not touch `server/tools.py::ALL_TOOLS` or `server/prompts.py`. X-1 and X-2 are satisfied by construction if the implementer avoids those files.

**Snippet contract** (`snippet-contract.md §a`): "Every result row carries a single inline text field, `snippet`. The **content** is the first **150 characters** of the chunk's canonical body text." The 150-char cap applies to body_text content, NOT to the chunk's full body. Longer chunks (up to 2048 tokens) increase the embedding fidelity but the snippet field is derived from the first 150 chars of `body_text` regardless. **No snippet-contract violation from the 2048-token bump** — snippets remain 150-char byte-prefix slices.

**nDCG@5 eval baseline**: `retrieval-quality-report.md` has `_PENDING_` for all nDCG@5 values on the global 20-query fixture. The notebook-scoped spike (51 papers, bridgeland-stability) shows `dense-only R@10 = 0.936`. B-3 must use the notebook fixture, not the global one.

**Live dataset chunk counts** (verified by direct LanceDB query):
- `var/arxmcp/notebooks/bridgeland-stability/lancedb`: **6,804 rows**, `corpus-version.json` version 369
- `var/arxmcp/notebooks/shimura-varieties/lancedb`: **3,625 rows**, `corpus-version.json` version 49
- `var/arxmcp/index/lancedb`: main corpus table NOT FOUND (no `chunks` table — main corpus is empty)
- Total re-embed scope: **10,429 chunks** across 2 datasets

**BM25 index files**: `var/arxmcp/index/bm25/v{49,81,101,157,369}/bm25.pkl` — version-keyed per-dataset. After re-embed bumps corpus_version (369 → 370, 49 → 50), BM25 re-build is triggered automatically on next query (per `bm25_indexer.py:16`). No explicit rebuild step required.

**re_embed.py scope**: `run_re_embed()` takes `active_lancedb_path` as a parameter (default: main corpus). **It does NOT iterate over multiple datasets automatically.** The implementer must call it once per notebook dataset, or write a small driver loop. This is a gap in the roadmap brief's "re-embed every LanceDB dataset" AC.

**Safetensors at pinned SHA**: The `.no_exist/` directory contains `model.safetensors` — meaning this file was NOT found at SHA `5617a9f6` when HF was queried. The pinned SHA ships `pytorch_model.bin` only. This is the documented gap from the E13_S06 memory entry: "embedder CANNOT enforce `use_safetensors=True` because the pinned SHA ships `.bin`-only." The milestone does NOT change the SHA, so this remains a known deferred gap.

**CONFLICT FLAGGED — re_embed.py does not cover notebook datasets:**
**The milestone brief says "re-embed every paper in every LanceDB dataset under `var/arxmcp/notebooks/<slug>/lancedb/`" but `ingest/re_embed.py::run_re_embed()` is hard-coded to a single `active_lancedb_path` with no glob/enumeration logic for multiple datasets. The implementer must add a notebook-aware invocation loop or a CLI entry point that discovers all notebook LanceDB paths.**

---

## External sources

**BGE-M3 HuggingFace model card** (fetched 2026-05-27):

- **Native context length: 8192 tokens** (confirmed). Extended from XLM-RoBERTa-large's 512 via RetroMAE pretraining.
- **Dense vector dimension: 1024** (confirmed; same `hidden_size` in `config.json`).
- **`max_length` is specified at call-site**, not model load. The recommended FlagEmbedding API passes `max_length=8192` to `model.encode(...)` at call time.
- **No MUST-clause about instruction prefixes** — M3 explicitly does NOT require instruction prefixes (unlike BGE-v1.5). This is load-bearing for arXMCP because no instruction prefix is prepended.

**Tokenizer config at pinned SHA (5617a9f6) — read from local HuggingFace cache:**

```json
{
  "model_max_length": 8192,
  "tokenizer_class": "XLMRobertaTokenizer"
}
```

**`model_max_length` is 8192 at the pinned SHA.** This DOES NOT impose a 512 cap. The current `MAX_TOKENS = 512` in `ingest/embedder.py` is a project-level choice, not a tokenizer constraint. Raising to 2048 is safe — the tokenizer's `truncation=True, max_length=2048` will work correctly.

**Model config at pinned SHA:**

```json
{
  "max_position_embeddings": 8194,
  "hidden_size": 1024,
  "num_hidden_layers": 24,
  "num_attention_heads": 16,
  "position_embedding_type": "absolute"
}
```

**`max_position_embeddings = 8194`** (8192 + 2 for CLS/SEP). No sparse-attention or FlashAttention configuration. This is **standard full attention** (O(n²) in sequence length). At 2048 tokens, attention compute is 4× more than at 1024, 16× more than at 512. On CPU (no GPU), this is the dominant performance concern.

**`add_special_tokens` parameter**: The HuggingFace `tokenizers` library (and `transformers.AutoTokenizer`) adds CLS (`<s>`) and SEP (`</s>`) by default when `add_special_tokens=True` (the default). These consume 2 token slots. The fix for C is to pass `add_special_tokens=False` ONLY in the pre-pass length measurement (lines 415-421); the actual encode call (lines 437-443) must retain the default (`add_special_tokens=True`) because the XLM-RoBERTa model requires CLS/SEP for correct sentence-level embeddings.

**No version drift between project pin and current HF HEAD**: The project pins `BGE_M3_COMMIT_SHA = "5617a9f61b028005a4858fdac845db406aefb181"` (verified 2026-05-07). No model swap required.

---

## Failure mode analysis

**FM-1: VRAM/RAM exhaustion from 4× longer inputs (MEDIUM risk)**

- Trigger: BGE-M3 on CPU with `max_length=2048`. Standard XLM-RoBERTa full-attention is O(n²) in tokens. Going from 512 → 2048 is 4× length, 16× attention memory. A batch of 32 chunks at 2048 tokens ≈ 32 × 2048 × 2048 × 16 heads = potentially hundreds of MB of attention tensors in CPU RAM.
- Symptom: OOM kill during re-embed, corrupted staging LanceDB.
- Mitigation: Lower `EMBED_BATCH_DEFAULT` from 32 to 8 when `MAX_TOKENS > 1024`. Alternatively, document the reduced batch size in the commit message. The `EMBED_BATCH_DEFAULT = 32` constant is at `ingest/embedder.py:133`; it should either become dynamic (function of MAX_TOKENS) or the implementer should flag the recommended override.

**FM-2: Tokenizer `model_max_length` cap silently truncating at 512 (LOW risk — ruled out by external source check)**

- Trigger: If the tokenizer's internal `model_max_length` were 512, passing `max_length=2048` to `tokenizer(...)` would silently be overridden to 512 in some older transformers versions.
- Ruling out: The tokenizer_config.json at the pinned SHA shows `model_max_length: 8192`. The `transformers>=4.40` requirement means the `max_length` parameter wins. This failure mode is **eliminated** — confirmed by direct inspection of the HF cache.

**FM-3: Fixture regeneration creates a "broken window" commit (HIGH risk)**

- Trigger: The implementer regenerates the 10 `expected.json` files but does NOT update `tests/eval/fixtures/queries.json` in the same commit.
- Symptom: `TestFixtureSuite` passes, but any query in `queries.json` that references old chunk_ids (when the file is eventually populated) will silently be wrong.
- Mitigation: Per `chunker-fixtures.md`, the three changes (chunker source, fixture goldens, eval queries) MUST land in one commit. Since `queries.json` is currently an empty stub, this is low-impact today but must be noted for when it is populated.

**FM-4: re_embed.py only covers main corpus, missing notebook datasets (HIGH risk)**

- Trigger: Implementer runs `python -m ingest.re_embed` against the default `DEFAULT_LANCEDB_PATH` (main corpus, which has no chunks table today), skipping the notebook-scoped datasets.
- Symptom: B-4 AC fails — `corpus-version.json` in notebook datasets does NOT advance.
- Mitigation: The implementer must discover and iterate over `var/arxmcp/notebooks/*/lancedb/` explicitly. A driver script or a CLI flag `--all-datasets` is needed. This is the most operationally critical gap.

**FM-5: Wall-clock blowup on 2048-token batches (MEDIUM risk)**

- Trigger: Re-embedding 10,429 chunks at batch size 32 with 2048-token inputs. The scan brief estimated ~40 min for 137 papers (222+1096=1318 chunks from 2 datasets); 6,804+3,625=10,429 chunks is ~8× more. CPU O(n²) attention means each forward pass is 16× more compute per chunk.
- Symptom: The operator waits 3-8 hours for re-embed to finish.
- Mitigation: Document estimated wall-clock (8× more chunks × 4× more compute ≈ 32× the scan brief's estimate for a single paper → potentially hours). Reduce `EMBED_BATCH_DEFAULT` to 8 and advise the operator to run overnight.

**FM-6: BM25 index not rebuilt after corpus_version bump (LOW risk — auto-mitigated)**

- Trigger: BM25 index for `v369` is now stale (bridgeland-stability dataset). The re-embed produces a new corpus at v370.
- Symptom: First query after re-embed hits BM25 cold and triggers a rebuild — adds latency to the first search.
- Mitigation: Per `bm25_indexer.py` docstring, the indexer auto-builds on first query. No operator action needed; warn in commit message.

**FM-7: eval B-3 nDCG@5 baseline is undefined (MEDIUM risk — AC framing issue)**

- Trigger: `tests/eval/fixtures/queries.json` is an empty stub. The B-3 AC as written requires "nDCG@5 does NOT regress ... on `tests/eval/fixtures/queries.json`." This query fixture cannot produce a measurement.
- Symptom: B-3 AC cannot be verified as written; the milestone could falsely claim B-3 passed on an empty fixture.
- Mitigation: Re-frame B-3 to use the notebook-scoped fixture at `var/arxmcp/notebooks/bridgeland-stability/queries.json`. The spike at `.claude/notes/spikes/wiring-rerank-lift-100paper/note.md` shows R@10 = 0.936 as a pre-existing baseline to clear.

**FM-8: Chunk-id determinism claim untestable without model (MEDIUM risk)**

- The B-2 AC asks for an explicit "version-bump invalidates old hashes" test. Since chunk_ids are computed from `sha256(preamble_text + NFC(body_text))`, and the preamble is empty for all current ar5iv-only papers, chunk_ids depend only on `body_text`. The CHUNKER_VERSION bump changes the version string stored on the record but **does NOT change the sha256 hash of body_text** — the hash is body-content-addressable, not version-dependent. The chunk_id format is `arxiv:<paper_id>:<sha256(body_text)[:16]>`. Therefore the chunk_ids remain the SAME values after a version bump; only `chunker_version` field on the record changes. The B-2 AC needs re-framing: the test should assert that records emitted with `CHUNKER_VERSION="v1.1"` carry the new version string, not that the hex suffix changes.

---

## Recommendation

**Implement C and B as scoped, with three clarifications:**

1. **Change C (off-by-2 fix)**: Add `add_special_tokens=False` to `ingest/embedder.py:415`'s pre-pass call. Write a synthetic-input regression test (no real model needed) that mocks the tokenizer to return `length=514` with `add_special_tokens=True` and `length=512` with `add_special_tokens=False`, asserting that `truncated_count` is 0 for a 512-token chunk after the fix. This satisfies C-1 and C-2 without a `requires_model` dependency.

2. **Change B token budgets**: Raise `BGE_M3_MAX_TOKENS` to 2048, `STMT_MAX_TOKENS` to 1920, `PROOF_MAX_TOKENS` to 1856. Lower `EMBED_BATCH_DEFAULT` from 32 to 8 (or make it conditional on `MAX_TOKENS > 1024`) to avoid CPU OOM on 16× larger attention matrices.

3. **Re-embed invocation**: Write a small driver (e.g. `ingest/re_embed_all.py` or a `make re-embed-all` target) that discovers all notebook LanceDB paths via `glob("var/arxmcp/notebooks/*/lancedb/")` and calls `run_re_embed()` for each. The current `run_re_embed()` takes only a single path — the driver is the missing glue.

4. **B-2 and B-3 test re-framing** (per FM-7, FM-8): B-2 should assert `chunk.chunker_version == "v1.1"` on re-emitted records. B-3 should be measured against `var/arxmcp/notebooks/bridgeland-stability/queries.json` (populated), not the empty global fixture.

---

## Open questions

1. Should `EMBED_BATCH_DEFAULT` be lowered as a constant (visible change) or should the implementer add a `batch_size` parameter that defaults to a smaller value when `MAX_TOKENS > 1024`? The constant is used in multiple call sites — check all callers before deciding.

2. The roadmap brief says `PROOF_MAX_TOKENS` moves from 448 → 1856. The scan brief says 1920. The roadmap brief is authoritative (1856 = 2048 - 192 headroom). Confirm with implementer which value to use and ensure chunker.py and the roadmap brief are consistent.

3. Does the re-embed driver need to handle partial failures (one notebook dataset fails mid-embed)? `run_re_embed()` has resume semantics via `re-embed-progress.json`. The driver should propagate this per-dataset.

---

## External writes the implementation will require

None — this milestone is purely local. All changes are local file edits, in-process re-embed CPU work, and local LanceDB/BM25 writes. No git push, no PRs, no API calls, no infra mutations are required during implementation.
