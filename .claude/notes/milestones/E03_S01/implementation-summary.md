# E03_S01 Implementation Summary

**Commit:** 8ee41be — `feat(ingest): dual-column BGE-M3 embedder with NPZ store (E03_S01)`
**Branch:** `claude/gallant-blackburn-b89422`
**Files changed:** 4 (2 new, 2 modified)
**Net diff:** +1362 / −5

## Files

| Path | New / Modified | Purpose |
|---|---|---|
| `ingest/embedder.py` | NEW | Public `embed_paper` / `embed_corpus`, lazy `_get_model` / `_get_tokenizer`, `_build_embed_input`, `_encode_batch`, `_write_embeddings_npz`, `EmbedStats`, atomic NPZ writes, ops logging |
| `tests/test_embedder.py` | NEW | 26 unit tests across 9 classes |
| `pyproject.toml` | modified | adds `torch>=2.0`, `safetensors>=0.4`, `numpy>=1.24` |
| `ingest/chunker.py` | modified | docstring on `_get_tokenizer` updated to acknowledge that the embedder introduces torch (the chunker itself still avoids it) |

## Decisions exercised from research-synthesis.md

- D1 NPZ-first ✓ — `var/arxmcp/corpus/embeddings/<paper_id>/embeddings.npz`
  with `chunk_ids_stmt`, `embedding_stmt`, `chunk_ids_proof`,
  `embedding_proof` arrays (no LanceDB import).
- D2 `BGE_M3_COMMIT_SHA = "5617a9f61b028005a4858fdac845db406aefb181"` ✓
  (verified single source of truth via
  `TestModuleContract.test_bge_m3_commit_sha_defined_exactly_once`).
- D3 Threat 6 load form ✓ — `revision=BGE_M3_COMMIT_SHA,
  trust_remote_code=False`, asserted by `TestThreat6` for both model
  and tokenizer.
- D4 CLS pool + explicit `F.normalize` ✓ — exercised by
  `TestVectorContract.test_shape_1024_and_l2_normalized` (norm ≈ 1.0
  to within 1e-5).
- D5 Routing ✓ — `TestRouting` covers proof, section/definition,
  fall-through (lemma/remark).
- D6 F3 fallback ✓ — `TestF3Fallback`.
- D7 NFC ✓ — `TestEmbedInputBuild.test_applies_nfc_normalization`.
- D8 Token-budget warn+truncate (never raise) ✓ —
  `TestTokenBudget.test_overlong_input_warn_and_truncate`.
- D9 `PER_PAPER_FAILURE_EXCEPTIONS` ✓ —
  `TestModuleContract.test_per_paper_failure_exceptions_targeted`.
- D10 Atomic NPZ writes ✓ — `TestAtomicWrite`. Discovered and fixed a
  np.savez subtlety: when given a path string, np.savez auto-appends
  `.npz`, which would break the os.replace tmp pattern. Fixed by
  handing np.savez an already-opened file handle.
- D11 `torch.set_num_threads(os.cpu_count() or 4)` ✓ — applied at
  model load.
- D12 pyproject.toml adds ✓.

## Test results

- 347 passed, 1 skipped (the skip is pre-existing unrelated to this
  milestone).
- `ruff check .` clean.

## Acceptance-criteria mapping

| Brief criterion | Test |
|---|---|
| Model loaded from pinned commit SHA | `TestThreat6.test_model_loaded_with_pinned_revision` |
| `BGE_M3_COMMIT_SHA` defined exactly once | `TestModuleContract.test_bge_m3_commit_sha_defined_exactly_once` |
| `kind="stmt"` → `embedding_stmt`, null `embedding_proof` | `TestRouting.test_kind_section_definition_route_to_embedding_stmt` |
| `kind="proof"` → `embedding_proof`, null `embedding_stmt` | `TestRouting.test_kind_proof_routes_to_embedding_proof` |
| All vectors shape (1024,) and L2-normalized | `TestVectorContract.test_shape_1024_and_l2_normalized` |
| Embedding input ≤ 512 tokens (warn + truncate, never raise) | `TestTokenBudget.test_overlong_input_warn_and_truncate` |
| `embed-stats.jsonl` entry per run | `TestStatsLogging.test_jsonl_line_per_paper` |
| Integration test passes without GPU | All tests are CPU-only — fake model factory uses `torch.zeros` / `torch.arange`, no `.cuda()` |

## Out-of-scope (deferred per brief)

- Idempotent skip logic (E03_S02): the embedder always re-encodes; the
  NPZ overwrite via os.replace is atomic so partial writes are not
  observable.
- Singleflight for query encoding (E03_S03).
- HNSW index creation (E04_S01).
- Query-time encoding (E06 / Sonnet B).
- LanceDB write path (E04_S01) — the embedder writes NPZ; E04_S01's
  `ingest/store.py` reads the NPZ.

## Pre-existing tokenizer-pinning gap (out of scope, surfaced for follow-up)

`ingest/chunker.py:_get_tokenizer` calls
`AutoTokenizer.from_pretrained("BAAI/bge-m3")` without `revision=...` —
a Threat 6 violation pre-dating this milestone. The embedder pins both
its tokenizer and model, so the embedder's pipeline is compliant. The
chunker's tokenizer-only path (used for token-budget enforcement) is
not Threat 6 compliant. Fixing it is a one-line change in a follow-up.
